#!/usr/bin/env python3
"""
Günlük İçerik Özeti - Cumhuriyet (Ergin Yıldızoğlu) + Patreon
Outlook/Hotmail üzerinden e-posta gönderir.
"""

import os
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import anthropic

# ─── AYARLAR ────────────────────────────────────────────────────────────────
OUTLOOK_EMAIL   = os.environ["OUTLOOK_EMAIL"]       # gönderici = alıcı
OUTLOOK_PASSWORD = os.environ["OUTLOOK_PASSWORD"]   # Outlook şifresi
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# Patreon yazarları — kendi URL'lerinle değiştir
PATREON_CREATORS = [
    {"name": "jxlhs",           "url": "https://www.patreon.com/c/jxlhs/posts"},
    {"name": "Bureau of Economy","url": "https://www.patreon.com/c/bureauofeconomy/posts"},
]

CUMHURIYET_AUTHOR_URL = "https://www.cumhuriyet.com.tr/yazarlar/ergin-yildizoglu"
# ────────────────────────────────────────────────────────────────────────────


def summarize(text: str, title: str) -> str:
    """Claude API ile metni özetle."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Aşağıdaki makaleyi Türkçe olarak 4-5 cümleyle özetle.
Ana argümanı, öne sürülen kanıtları ve sonucu kısaca aktar.
Başlık: {title}

Metin:
{text[:6000]}
"""
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


def fetch_yildizoglu() -> list[dict]:
    """Cumhuriyet'ten Ergin Yıldızoğlu'nun son yazılarını çek."""
    articles = []
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(CUMHURIYET_AUTHOR_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Yazar sayfasındaki makale linkleri
        links = []
        for a in soup.select("a[href]"):
            href = a["href"]
            if "/yazarlar/ergin-yildizoglu/" in href and len(href) > 50:
                full = href if href.startswith("http") else "https://www.cumhuriyet.com.tr" + href
                if full not in links:
                    links.append(full)
            if len(links) >= 3:
                break

        cutoff = datetime.now() - timedelta(days=2)

        for url in links:
            try:
                r = requests.get(url, headers=headers, timeout=15)
                s = BeautifulSoup(r.text, "html.parser")

                title_tag = s.find("h1")
                title = title_tag.get_text(strip=True) if title_tag else "Başlık yok"

                # Tarih kontrolü
                date_tag = s.find("time")
                pub_date = None
                if date_tag and date_tag.get("datetime"):
                    try:
                        pub_date = datetime.fromisoformat(date_tag["datetime"][:10])
                    except Exception:
                        pass

                # Makale gövdesi
                body_tag = s.find("div", class_=lambda c: c and "article" in c.lower()) or \
                           s.find("div", class_=lambda c: c and "content" in c.lower())
                body = body_tag.get_text(" ", strip=True) if body_tag else ""

                if len(body) < 200:
                    continue

                summary = summarize(body, title)

                articles.append({
                    "source": "Cumhuriyet",
                    "author": "Ergin Yıldızoğlu",
                    "title": title,
                    "url": url,
                    "date": pub_date.strftime("%d.%m.%Y") if pub_date else "—",
                    "summary": summary,
                })
            except Exception as e:
                print(f"  [!] Makale çekilemedi: {url} — {e}")

    except Exception as e:
        print(f"[!] Cumhuriyet sayfası çekilemedi: {e}")

    return articles


def fetch_patreon(creator: dict) -> list[dict]:
    """Patreon yazarının public postlarını çek (ücretsiz içerikler)."""
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml",
    }

    try:
        resp = requests.get(creator["url"], headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Patreon public post başlıkları + linkleri
        post_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/posts/" in href:
                full = href if href.startswith("http") else "https://www.patreon.com" + href
                if full not in post_links:
                    post_links.append(full)
            if len(post_links) >= 3:
                break

        for url in post_links:
            try:
                r = requests.get(url, headers=headers, timeout=15)
                s = BeautifulSoup(r.text, "html.parser")

                title_tag = s.find("h1") or s.find("h2")
                title = title_tag.get_text(strip=True) if title_tag else "Başlık yok"

                # Patreon post gövdesi
                body_div = s.find("div", {"data-tag": "post-body"}) or \
                           s.find("div", class_=lambda c: c and "post" in (c or "").lower())
                body = body_div.get_text(" ", strip=True) if body_div else ""

                if len(body) < 100:
                    summary = "⚠️ Bu içerik üyelere özel ya da scraping engelliyor."
                else:
                    summary = summarize(body, title)

                articles.append({
                    "source": "Patreon",
                    "author": creator["name"],
                    "title": title,
                    "url": url,
                    "date": "—",
                    "summary": summary,
                })
            except Exception as e:
                print(f"  [!] Patreon post çekilemedi: {url} — {e}")

    except Exception as e:
        print(f"[!] Patreon sayfası çekilemedi ({creator['name']}): {e}")

    return articles


def build_html(all_articles: list[dict]) -> str:
    """Güzel HTML e-posta içeriği oluştur."""
    today = datetime.now().strftime("%d %B %Y, %A")

    cards = ""
    for a in all_articles:
        source_color = "#c0392b" if a["source"] == "Cumhuriyet" else "#8e44ad"
        cards += f"""
        <div style="background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.08);border-left:4px solid {source_color};">
          <div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">
            {a['source']} · {a['author']} · {a['date']}
          </div>
          <a href="{a['url']}" style="color:#1a1a2e;font-size:17px;font-weight:700;text-decoration:none;">
            {a['title']}
          </a>
          <p style="color:#444;font-size:14px;line-height:1.7;margin-top:10px;">{a['summary']}</p>
          <a href="{a['url']}" style="font-size:13px;color:{source_color};text-decoration:none;">
            → Tam yazıyı oku
          </a>
        </div>
        """

    if not cards:
        cards = "<p style='color:#888;'>Bugün yeni içerik bulunamadı.</p>"

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
      <div style="max-width:640px;margin:30px auto;padding:0 16px;">

        <!-- Header -->
        <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);
                    border-radius:12px;padding:28px;margin-bottom:24px;text-align:center;">
          <div style="font-size:28px;margin-bottom:6px;">📰</div>
          <h1 style="color:#fff;margin:0;font-size:22px;">Günlük İçerik Özeti</h1>
          <p style="color:#a0aec0;margin:6px 0 0;font-size:14px;">{today}</p>
        </div>

        {cards}

        <!-- Footer -->
        <div style="text-align:center;padding:16px;color:#aaa;font-size:12px;">
          Bu e-posta otomatik olarak oluşturulmuştur · Claude API ile özetlenmiştir
        </div>
      </div>
    </body>
    </html>
    """


def send_email(html_body: str, article_count: int):
    """Outlook SMTP üzerinden e-posta gönder."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📰 Günlük Özet — {article_count} yeni içerik · {datetime.now().strftime('%d.%m.%Y')}"
    msg["From"]    = OUTLOOK_EMAIL
    msg["To"]      = OUTLOOK_EMAIL  # kendine gönder

    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp-mail.outlook.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        server.sendmail(OUTLOOK_EMAIL, OUTLOOK_EMAIL, msg.as_string())
        print(f"✅ E-posta gönderildi: {article_count} makale")


def main():
    print(f"🚀 Digest başlıyor... [{datetime.now().strftime('%H:%M')}]")

    all_articles = []

    print("📰 Cumhuriyet çekiliyor...")
    all_articles += fetch_yildizoglu()

    for creator in PATREON_CREATORS:
        print(f"🎨 Patreon çekiliyor: {creator['name']}...")
        all_articles += fetch_patreon(creator)

    print(f"   Toplam {len(all_articles)} içerik bulundu.")

    html = build_html(all_articles)
    send_email(html, len(all_articles))


if __name__ == "__main__":
    main()
