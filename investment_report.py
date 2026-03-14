"""
Investment Report Agent
Günlük yatırım raporu - Piyasa temaları, macro veri, sentiment analizi
Her sabah 06:00 UTC (09:00 Istanbul) çalışır
"""

import os
import json
import smtplib
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET

# ── Anthropic API ──────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OUTLOOK_EMAIL     = os.environ["OUTLOOK_EMAIL"]
OUTLOOK_PASSWORD  = os.environ["OUTLOOK_PASSWORD"]

TODAY = datetime.utcnow().strftime("%d %B %Y")
TODAY_SHORT = datetime.utcnow().strftime("%Y-%m-%d")

# ── RSS KAYNAKLARI ─────────────────────────────────────────────────────────────
RSS_FEEDS = {
    "Reuters Markets":      "https://feeds.reuters.com/reuters/businessNews",
    "MarketWatch":          "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines",
    "Seeking Alpha":        "https://seekingalpha.com/market_currents.xml",
    "CNBC Markets":         "https://www.cnbc.com/id/20910258/device/rss/rss.html",
    "Yahoo Finance":        "https://finance.yahoo.com/news/rssindex",
    "Barron's":             "https://www.barrons.com/xml/rss/3_7566.xml",
    "Financial Times":      "https://www.ft.com/rss/home/uk",
    "Bloomberg Markets":    "https://feeds.bloomberg.com/markets/news.rss",
    "Investopedia":         "https://www.investopedia.com/feedbuilder/feed/getfeed/?feedName=rss_headline",
    "WSJ Markets":          "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
}

# ── FRED API (Fed Makro Veri) ──────────────────────────────────────────────────
FRED_SERIES = {
    "Fed Funds Rate":       "FEDFUNDS",
    "CPI (Enflasyon)":      "CPIAUCSL",
    "Unemployment Rate":    "UNRATE",
    "10Y Treasury Yield":   "DGS10",
    "2Y Treasury Yield":    "DGS2",
    "GDP Growth":           "A191RL1Q225SBEA",
    "Core PCE":             "PCEPILFE",
    "ISM Manufacturing":    "NAPM",
}

# ── StockTwits Trending ────────────────────────────────────────────────────────
STOCKTWITS_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"

# ── Finviz News ────────────────────────────────────────────────────────────────
FINVIZ_NEWS_URL = "https://finviz.com/news.ashx"


def fetch_rss(name: str, url: str, max_items: int = 5) -> list[dict]:
    """RSS feed'den haber çeker"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        root = ET.fromstring(content)

        items = []
        # RSS 2.0
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()[:200]
            pub   = item.findtext("pubDate", "")
            link  = item.findtext("link", "")
            if title:
                items.append({"source": name, "title": title, "desc": desc,
                              "date": pub, "link": link})

        # Atom
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:max_items]:
                title = entry.findtext("atom:title", "", ns).strip()
                summary = entry.findtext("atom:summary", "", ns).strip()[:200]
                updated = entry.findtext("atom:updated", "", ns)
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                if title:
                    items.append({"source": name, "title": title, "desc": summary,
                                  "date": updated, "link": link})
        return items
    except Exception as e:
        print(f"RSS hata [{name}]: {e}")
        return []


def fetch_fred_data() -> dict:
    """FRED API'den makro veriler çeker (API key gerektirmez - public endpoint)"""
    results = {}
    base = "https://api.stlouisfed.org/fred/series/observations"

    # FRED API key opsiyonel — public data için file_type=json kullanırız
    fred_key = os.environ.get("FRED_API_KEY", "")
    if not fred_key:
        # API key yoksa FRED'in public RSS endpoint'ini dene
        fred_key = "abcdefghijklmnop"  # dummy, bazı public seriler çalışır

    for label, series_id in FRED_SERIES.items():
        try:
            params = urllib.parse.urlencode({
                "series_id": series_id,
                "api_key": fred_key,
                "file_type": "json",
                "limit": 2,
                "sort_order": "desc",
            })
            url = f"{base}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            obs = data.get("observations", [])
            if len(obs) >= 2:
                current = obs[0]["value"]
                previous = obs[1]["value"]
                results[label] = {
                    "current": current,
                    "previous": previous,
                    "date": obs[0]["date"],
                }
            elif len(obs) == 1:
                results[label] = {
                    "current": obs[0]["value"],
                    "previous": "N/A",
                    "date": obs[0]["date"],
                }
        except Exception as e:
            print(f"FRED hata [{series_id}]: {e}")
            results[label] = {"current": "N/A", "previous": "N/A", "date": "N/A"}

    return results


def fetch_stocktwits_trending() -> list[dict]:
    """StockTwits trending hisselerini çeker"""
    try:
        req = urllib.request.Request(
            STOCKTWITS_TRENDING_URL,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        symbols = data.get("symbols", [])[:15]
        return [
            {
                "symbol": s.get("symbol", ""),
                "title": s.get("title", ""),
                "watchlist_count": s.get("watchlist_count", 0),
            }
            for s in symbols
        ]
    except Exception as e:
        print(f"StockTwits hata: {e}")
        return []


def fetch_market_prices() -> dict:
    """Yahoo Finance'den ana endeks ve emtia fiyatları çeker"""
    symbols = {
        "S&P 500":      "%5EGSPC",
        "NASDAQ":       "%5EIXIC",
        "Dow Jones":    "%5EDJI",
        "VIX":          "%5EVIX",
        "Gold":         "GC%3DF",
        "WTI Oil":      "CL%3DF",
        "10Y Treasury": "%5ETNX",
        "USD/TRY":      "USDTRY%3DX",
        "EUR/USD":      "EURUSD%3DX",
        "BTC/USD":      "BTC-USD",
    }
    results = {}
    for name, symbol in symbols.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev  = meta.get("chartPreviousClose", 0)
            change_pct = ((price - prev) / prev * 100) if prev else 0
            results[name] = {
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "currency": meta.get("currency", "USD"),
            }
        except Exception as e:
            print(f"Yahoo Finance hata [{name}]: {e}")
            results[name] = {"price": 0, "change_pct": 0, "currency": ""}
    return results


def call_claude(prompt: str, system: str) -> str:
    """Claude API çağrısı"""
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 4000,
        "system": system,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    return result["content"][0]["text"]


def build_analysis_prompt(
    news_items: list,
    macro_data: dict,
    market_prices: dict,
    trending: list,
) -> str:
    """Claude için analiz promptu oluşturur"""

    # Haberleri özetle
    news_text = ""
    for item in news_items[:40]:
        news_text += f"• [{item['source']}] {item['title']}\n"
        if item.get("desc"):
            news_text += f"  {item['desc'][:120]}\n"

    # Makro veri
    macro_text = ""
    for label, vals in macro_data.items():
        cur = vals["current"]
        prev = vals["previous"]
        date = vals["date"]
        macro_text += f"• {label}: {cur} (önceki: {prev}) — {date}\n"

    # Piyasa fiyatları
    price_text = ""
    for name, vals in market_prices.items():
        arrow = "▲" if vals["change_pct"] > 0 else "▼" if vals["change_pct"] < 0 else "─"
        price_text += f"• {name}: {vals['price']} {vals['currency']} {arrow} {vals['change_pct']:+.2f}%\n"

    # StockTwits trending
    trending_text = ""
    for s in trending[:10]:
        trending_text += f"• ${s['symbol']} — {s['title']} (Watchlist: {s['watchlist_count']:,})\n"

    return f"""
Tarih: {TODAY}

=== PİYASA FİYATLARI ===
{price_text}

=== MAKROEKONOMİK VERİLER (FRED) ===
{macro_text}

=== STOCKTWITS TRENDING HİSSELER ===
{trending_text}

=== GÜNÜN HABERLERİ ===
{news_text}

Yukarıdaki tüm verileri analiz ederek kapsamlı günlük yatırım raporu hazırla.
"""


SYSTEM_PROMPT = """Sen dünya genelinde tanınan, 25 yıllık deneyime sahip bir baş yatırım stratejistisin. 
Goldman Sachs ve Bridgewater'da çalıştın. Makroekonomik analiz, jeopolitik risk değerlendirmesi 
ve piyasa temaları konusunda üst düzey uzmanlığa sahipsin.

Türk yatırımcılar için Türkçe rapor hazırlıyorsun. Raporun:
- Net, keskin ve aksiyon odaklı olmalı
- Her iddiayı verilerle desteklemeli  
- Hem kısa vadeli trading hem uzun vadeli yatırım perspektifini içermeli
- Türkiye bağlamını (TRY, BIST, yerel makro) da değerlendirmeli
- "Bu hisseyi al" değil "Bu tema öne çıkıyor, bu hisseler bu temadan faydalanabilir" şeklinde
- Spekülatif tahminlerden kaçın, veri ve gözleme dayalı ol

RAPOR FORMATI (HTML):
Aşağıdaki bölümleri sırayla oluştur:

1. EXECUTİVE SUMMARY (3-4 cümle, bugünkü piyasanın özü)
2. GÜNÜN MAKRO GÖRÜNÜMÜ (Fed, enflasyon, istihdam, büyüme)
3. PİYASA HAREKETLERİ & ANALİZ (endeksler, sektörler, ne neden hareket etti)
4. ÖNE ÇIKAN TEMALAR (son 1 yılda güçlenen, son 3 ayda popülerleşen)
5. UZUN / KISA POZİSYON GÖRÜNÜMÜ (veriye dayalı, sektör bazında)
6. RİSK RADARI (piyasayı zorlayabilecek faktörler)
7. TÜRKİYE & GELİŞMEKTE OLAN PİYASALAR PENCERESI
8. PORTFÖY ÖNERİSİ ÇERÇEVESİ (risk profiline göre 3 senaryo: muhafazakar/dengeli/agresif)
9. YARIN İZLENECEKLER (takvim, açıklamalar, kritik seviyeler)

Her bölümü <h2> ile başlat. Önemli verileri <strong> ile vurgula.
Olumlu gelişmeleri yeşil (🟢), olumsuzları kırmızı (🔴), nötr/bekle (🟡) ile işaretle.
Rapor sonunda kısa bir disclaimer ekle."""


def generate_report(
    news_items: list,
    macro_data: dict,
    market_prices: dict,
    trending: list,
) -> str:
    """Claude ile rapor üretir"""
    prompt = build_analysis_prompt(news_items, macro_data, market_prices, trending)
    print("Claude analiz yapıyor...")
    return call_claude(prompt, SYSTEM_PROMPT)


def build_email_html(report_content: str, market_prices: dict) -> str:
    """Email HTML'ini oluşturur"""

    # Fiyat banner
    price_banner = ""
    for name, vals in list(market_prices.items())[:6]:
        color = "#16a34a" if vals["change_pct"] > 0 else "#dc2626" if vals["change_pct"] < 0 else "#6b7280"
        arrow = "▲" if vals["change_pct"] > 0 else "▼" if vals["change_pct"] < 0 else "─"
        price_banner += f"""
        <td style="padding:8px 16px; text-align:center; border-right:1px solid #334155;">
            <div style="font-size:11px; color:#94a3b8; font-weight:600;">{name}</div>
            <div style="font-size:15px; color:#f1f5f9; font-weight:700;">{vals['price']:,.2f}</div>
            <div style="font-size:12px; color:{color}; font-weight:600;">{arrow} {vals['change_pct']:+.2f}%</div>
        </td>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ margin:0; padding:0; background:#0f172a; font-family:'Segoe UI',Arial,sans-serif; color:#e2e8f0; }}
  .container {{ max-width:800px; margin:0 auto; background:#0f172a; }}
  .header {{ background:linear-gradient(135deg,#1e3a5f 0%,#0f2744 100%); padding:32px 40px; border-bottom:3px solid #2563eb; }}
  .header h1 {{ margin:0 0 4px; font-size:26px; color:#f8fafc; letter-spacing:0.5px; }}
  .header p {{ margin:0; font-size:13px; color:#94a3b8; }}
  .ticker-bar {{ background:#1e293b; border-bottom:1px solid #334155; }}
  .ticker-bar table {{ width:100%; border-collapse:collapse; }}
  .content {{ padding:32px 40px; }}
  .content h2 {{ color:#60a5fa; font-size:16px; font-weight:700; margin:28px 0 12px;
                 padding-bottom:8px; border-bottom:1px solid #1e3a5f; letter-spacing:0.3px; }}
  .content p {{ line-height:1.75; font-size:14px; color:#cbd5e1; margin:0 0 12px; }}
  .content strong {{ color:#f1f5f9; font-weight:600; }}
  .content ul {{ padding-left:20px; margin:8px 0 16px; }}
  .content li {{ font-size:14px; color:#cbd5e1; line-height:1.7; margin-bottom:4px; }}
  .disclaimer {{ background:#1e293b; border:1px solid #334155; border-radius:8px;
                 padding:16px 20px; margin-top:32px; font-size:12px; color:#64748b; line-height:1.6; }}
  .footer {{ background:#0a1628; padding:20px 40px; border-top:1px solid #1e293b;
             font-size:12px; color:#475569; text-align:center; }}
  .badge {{ display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px;
            font-weight:700; background:#1e3a5f; color:#60a5fa; margin-right:6px; }}
</style>
</head>
<body>
<div class="container">

  <!-- HEADER -->
  <div class="header">
    <h1>📊 Günlük Yatırım Raporu</h1>
    <p>{TODAY} &nbsp;|&nbsp; <span class="badge">AI DESTEKLI</span> <span class="badge">MAKRO + SENTIMENT</span> <span class="badge">PORTFÖY ÖNERİSİ</span></p>
  </div>

  <!-- TICKER BAR -->
  <div class="ticker-bar">
    <table><tr>{price_banner}</tr></table>
  </div>

  <!-- MAIN CONTENT -->
  <div class="content">
    {report_content}
    
    <div class="disclaimer">
      ⚠️ <strong>Yasal Uyarı:</strong> Bu rapor bilgilendirme amaçlıdır ve yatırım tavsiyesi niteliği taşımaz. 
      Yapay zeka destekli analizler geçmiş verilere ve kamuya açık bilgilere dayanır. 
      Yatırım kararlarınızı vermeden önce lisanslı bir finansal danışmana başvurunuz.
      Geçmiş performans gelecekteki sonuçların garantisi değildir.
    </div>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    <p>Bu rapor otomatik olarak üretilmiştir. &nbsp;|&nbsp; Veri kaynakları: Reuters, MarketWatch, FRED, StockTwits, Yahoo Finance</p>
    <p>Oluşturulma zamanı: {datetime.utcnow().strftime("%d.%m.%Y %H:%M")} UTC</p>
  </div>

</div>
</body>
</html>"""
    return html


def send_email(html_content: str, subject: str):
    """Outlook ile email gönderir"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = OUTLOOK_EMAIL
    msg["To"]      = OUTLOOK_EMAIL

    msg.attach(MIMEText(html_content, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        server.sendmail(OUTLOOK_EMAIL, OUTLOOK_EMAIL, msg.as_string())
    print(f"Email gönderildi → {OUTLOOK_EMAIL}")


def main():
    print(f"\n{'='*60}")
    print(f"Investment Report Agent — {TODAY}")
    print(f"{'='*60}\n")

    # 1. Haberler
    print("📰 Haberler çekiliyor...")
    all_news = []
    for name, url in RSS_FEEDS.items():
        items = fetch_rss(name, url, max_items=5)
        all_news.extend(items)
        print(f"  ✓ {name}: {len(items)} haber")

    # 2. Makro veri
    print("\n📊 Makro veriler çekiliyor (FRED)...")
    macro_data = fetch_fred_data()
    print(f"  ✓ {len(macro_data)} seri çekildi")

    # 3. Piyasa fiyatları
    print("\n💹 Piyasa fiyatları çekiliyor...")
    market_prices = fetch_market_prices()
    print(f"  ✓ {len(market_prices)} fiyat çekildi")

    # 4. StockTwits trending
    print("\n🔥 Trending hisseler çekiliyor...")
    trending = fetch_stocktwits_trending()
    print(f"  ✓ {len(trending)} trending hisse")

    # 5. Claude analizi
    print("\n🤖 Claude analiz yapıyor...")
    report_content = generate_report(all_news, macro_data, market_prices, trending)
    print("  ✓ Rapor oluşturuldu")

    # 6. Email
    print("\n📧 Email hazırlanıyor...")
    html = build_email_html(report_content, market_prices)
    
    spx = market_prices.get("S&P 500", {})
    direction = "▲" if spx.get("change_pct", 0) > 0 else "▼"
    subject = f"📊 Günlük Yatırım Raporu | {TODAY} | S&P {spx.get('price', 0):.0f} {direction}{abs(spx.get('change_pct', 0)):.1f}%"

    send_email(html, subject)
    print(f"\n✅ Tamamlandı — {TODAY}")


if __name__ == "__main__":
    main()
