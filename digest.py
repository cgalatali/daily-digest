#!/usr/bin/env python3
"""
Günlük İçerik Özeti
- Cumhuriyet: Ergin Yıldızoğlu + Mehmet Ali Güller
- Patreon: jxlhs + Bureau of Economy
- YouTube: Cem Gürdeniz (transkript özeti)
Outlook/Hotmail üzerinden e-posta gönderir.
"""

import os
import re
import smtplib
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
import anthropic

# ─── AYARLAR ────────────────────────────────────────────────────────────────
OUTLOOK_EMAIL     = os.environ["OUTLOOK_EMAIL"]
OUTLOOK_PASSWORD  = os.environ["OUTLOOK_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
EXTRA_RECIPIENT   = "cgalatali@hotmail.com"  # Hotmail'e de gönder

PATREON_CREATORS = [
    {"name": "jxlhs",             "url": "https://www.patreon.com/c/jxlhs/posts"},
    {"name": "Bureau of Economy", "url": "https://www.patreon.com/c/bureauofeconomy/posts"},
]

CUMHURIYET_AUTHORS = [
    {
        "name": "Ergin Yıldızoğlu",
        "url":  "https://www.cumhuriyet.com.tr/yazarlar/ergin-yildizoglu",
        "slug": "ergin-yildizoglu",
    },
    {
        "name": "Mehmet Ali Güller",
        "url":  "https://www.cumhuriyet.com.tr/yazarlar/mehmet-ali-guller",
        "slug": "mehmet-ali-guller",
    },
]

YOUTUBE_CHANNELS = [
    {"name": "Cem Gürdeniz", "url": "https://www.youtube.com/@CemGurdenizz"},
    {"name": "Hasan Hoca",   "url": "https://www.youtube.com/playlist?list=PLyqYrMRr_KhCaVo2lPhTD83V-MX7Lz8FS", "type": "playlist"},
]
# ────────────────────────────────────────────────────────────────────────────


def summarize(text: str, title: str, content_type: str = "makale") -> str:
    """Claude API ile metni özetle."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if content_type == "video":
        instruction = """Sen deneyimli bir jeopolitik ve strateji analistisin. 
Aşağıdaki YouTube video transkriptini izlemiş gibi detaylı bir şekilde özetle.

Şu formatta yaz:
🎯 **Ana Tez:** (1-2 cümle — videonun temel argümanı)

📌 **Ele Alınan Başlıklar:**
• (her ana konuyu madde madde, 1-2 cümleyle açıkla)

💡 **Öne Çıkan Görüşler:** (konuşmacının özgün tespitleri veya dikkat çekici iddiaları)

🔚 **Sonuç:** (videonun genel çıkarımı veya çağrısı)

Uzman bakış açısıyla, sanki videoyu bizzat izlemiş gibi yaz. Türkçe olsun."""
    else:
        instruction = """Sen deneyimli bir siyasi/ekonomi analistisin.
Aşağıdaki makaleyi okumuş gibi detaylı özetle.

Şu formatta yaz:
🎯 **Ana Argüman:** (yazarın temel tezi, 1-2 cümle)

📌 **Ele Alınan Başlıklar:**
• (her ana konuyu madde madde, 1-2 cümleyle açıkla)

💡 **Öne Çıkan Tespitler:** (yazarın dikkat çekici iddiaları veya özgün yorumları)

🔚 **Sonuç:** (makalenin genel çıkarımı)

Uzman bakış açısıyla, sanki makaleyi bizzat okumuş gibi yaz. Türkçe olsun."""

    prompt = f"""{instruction}

Başlık: {title}

Metin:
{text[:9000]}
"""
    msg = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


# ─── CUMHURİYET ─────────────────────────────────────────────────────────────

def fetch_cumhuriyet_author(author: dict) -> list[dict]:
    """Cumhuriyet yazar sayfasından son yazıları çek."""
    articles = []
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = requests.get(author["url"], headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        links = []
        for a in soup.select("a[href]"):
            href = a["href"]
            if f"/yazarlar/{author['slug']}/" in href and len(href) > 60:
                full = href if href.startswith("http") else "https://www.cumhuriyet.com.tr" + href
                if full not in links:
                    links.append(full)
            if len(links) >= 2:
                break

        for url in links:
            try:
                r = requests.get(url, headers=headers, timeout=15)
                s = BeautifulSoup(r.text, "html.parser")

                title_tag = s.find("h1")
                title = title_tag.get_text(strip=True) if title_tag else "Başlık yok"

                date_tag = s.find("time")
                pub_date = None
                if date_tag and date_tag.get("datetime"):
                    try:
                        pub_date = datetime.fromisoformat(date_tag["datetime"][:10])
                    except Exception:
                        pass

                body_tag = (
                    s.find("div", class_=lambda c: c and "article" in c.lower()) or
                    s.find("div", class_=lambda c: c and "content" in c.lower())
                )
                body = body_tag.get_text(" ", strip=True) if body_tag else ""

                if len(body) < 200:
                    continue

                summary = summarize(body, title, "makale")

                articles.append({
                    "source":  "Cumhuriyet",
                    "author":  author["name"],
                    "title":   title,
                    "url":     url,
                    "date":    pub_date.strftime("%d.%m.%Y") if pub_date else "—",
                    "summary": summary,
                    "body":    body,
                    "type":    "article",
                })
            except Exception as e:
                print(f"  [!] Makale çekilemedi: {url} — {e}")

    except Exception as e:
        print(f"[!] Cumhuriyet sayfası çekilemedi ({author['name']}): {e}")

    return articles


# ─── PATREON ────────────────────────────────────────────────────────────────

def fetch_patreon(creator: dict) -> list[dict]:
    """Patreon yazarının public postlarını çek."""
    articles = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}

    try:
        resp = requests.get(creator["url"], headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")

        post_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/posts/" in href:
                full = href if href.startswith("http") else "https://www.patreon.com" + href
                if full not in post_links:
                    post_links.append(full)
            if len(post_links) >= 2:
                break

        for url in post_links:
            try:
                r = requests.get(url, headers=headers, timeout=15)
                s = BeautifulSoup(r.text, "html.parser")

                title_tag = s.find("h1") or s.find("h2")
                title = title_tag.get_text(strip=True) if title_tag else "Başlık yok"

                body_div = (
                    s.find("div", {"data-tag": "post-body"}) or
                    s.find("div", class_=lambda c: c and "post" in (c or "").lower())
                )
                body = body_div.get_text(" ", strip=True) if body_div else ""

                summary = (
                    "⚠️ Bu içerik üyelere özel ya da scraping engelliyor."
                    if len(body) < 100
                    else summarize(body, title, "makale")
                )

                articles.append({
                    "source":  "Patreon",
                    "author":  creator["name"],
                    "title":   title,
                    "url":     url,
                    "date":    "—",
                    "summary": summary,
                    "type":    "article",
                })
            except Exception as e:
                print(f"  [!] Patreon post çekilemedi: {url} — {e}")

    except Exception as e:
        print(f"[!] Patreon çekilemedi ({creator['name']}): {e}")

    return articles


# ─── YOUTUBE ────────────────────────────────────────────────────────────────

def get_latest_video_id(channel_url: str, url_type: str = "channel") -> tuple[str, str] | None:
    """Kanalın veya playlist'in son video ID ve başlığını çek."""
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        if url_type == "playlist":
            fetch_url = channel_url
        else:
            fetch_url = channel_url + "/videos"

        resp = requests.get(fetch_url, headers=headers, timeout=15)
        ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
        titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', resp.text)

        if ids:
            video_id = ids[0]
            title = titles[0] if titles else "Başlık yok"
            return video_id, title
    except Exception as e:
        print(f"  [!] YouTube çekilemedi: {e}")
    return None


def fetch_youtube_channel(channel: dict) -> list[dict]:
    """YouTube kanalının son videosunu yt-dlp ile transkriptle özetle."""
    import subprocess, json, tempfile, os
    articles = []

    result = get_latest_video_id(channel["url"], channel.get("type", "channel"))
    if not result:
        print(f"  [!] {channel['name']} için video bulunamadı.")
        return articles

    video_id, title = result
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    full_text = None

    # yt-dlp ile altyazı çek — tüm diller, JSON formatında
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "sub")
            cmd = [
                "yt-dlp",
                "--write-auto-sub",
                "--write-sub",
                "--sub-langs", "all",          # tüm dilleri dene
                "--sub-format", "json3",        # JSON format — parse kolay
                "--skip-download",
                "--no-warnings",
                "--output", out_path,
                video_url
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            print(f"  yt-dlp stdout: {result.stdout[:300]}")
            print(f"  yt-dlp stderr: {result.stderr[:300]}")

            all_files = os.listdir(tmpdir)
            print(f"  İndirilen dosyalar: {all_files}")

            # Türkçeyi önce, sonra diğerleri
            json_files = [f for f in all_files if f.endswith(".json3")]
            json_files.sort(key=lambda f: (0 if "tr" in f.lower() else 1))

            for jfile in json_files:
                try:
                    import json as _json
                    with open(os.path.join(tmpdir, jfile), "r", encoding="utf-8") as f:
                        data = _json.load(f)
                    # json3 formatı: events > segs > utf8
                    words = []
                    for event in data.get("events", []):
                        for seg in event.get("segs", []):
                            txt = seg.get("utf8", "").strip()
                            if txt and txt.strip():
                                words.append(txt)
                    if words:
                        full_text = " ".join(words)
                        print(f"  ✅ Transkript bulundu: {jfile}")
                        break
                except Exception as je:
                    print(f"  [!] JSON parse hatası {jfile}: {je}")
    except Exception as e:
        print(f"  [!] yt-dlp hatası: {type(e).__name__}: {e}")

    if not full_text:
        # Supadata.ai API ile transkript çek — cloud IP engeli yok
        try:
            supadata_key = os.environ.get("SUPADATA_API_KEY", "")
            if supadata_key:
                resp = requests.get(
                    "https://api.supadata.ai/v1/youtube/transcript",
                    params={"videoId": video_id, "lang": "tr", "text": "true"},
                    headers={"x-api-key": supadata_key},
                    timeout=30
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # content alanı düz metin veya segment listesi olabilir
                    if isinstance(data.get("content"), str):
                        full_text = data["content"]
                    elif isinstance(data.get("content"), list):
                        full_text = " ".join(s.get("text", "") for s in data["content"])
                    if full_text:
                        print(f"  ✅ Supadata transkript alındı ({len(full_text)} karakter)")
                    else:
                        print(f"  [!] Supadata boş döndü: {resp.text[:200]}")
                else:
                    print(f"  [!] Supadata hata {resp.status_code}: {resp.text[:200]}")
            else:
                print("  [!] SUPADATA_API_KEY secret eksik")
        except Exception as e:
            print(f"  [!] Supadata hatası: {type(e).__name__}: {e}")

    if not full_text:
        articles.append({
            "source":  "YouTube",
            "author":  channel["name"],
            "title":   title,
            "url":     video_url,
            "date":    "—",
            "summary": "⚠️ Bu video için transkript bulunamadı.",
            "type":    "video",
        })
        return articles

    summary = summarize(full_text, title, "video")
    articles.append({
        "source":  "YouTube",
        "author":  channel["name"],
        "title":   title,
        "url":     video_url,
        "date":    datetime.now().strftime("%d.%m.%Y"),
        "summary": summary,
        "type":    "video",
    })

    return articles


# ─── HTML & EMAIL ────────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "Cumhuriyet": "#c0392b",
    "Patreon":    "#8e44ad",
    "YouTube":    "#e74c3c",
}

SOURCE_ICONS = {
    "Cumhuriyet": "📰",
    "Patreon":    "🎨",
    "YouTube":    "🎬",
}


def build_html(all_articles: list[dict]) -> str:
    today = datetime.now().strftime("%d %B %Y, %A")
    cards = ""

    for a in all_articles:
        color = SOURCE_COLORS.get(a["source"], "#555")
        icon  = SOURCE_ICONS.get(a["source"], "📄")
        is_video = a["type"] == "video"

        # Videolar için "izle" linki, makaleler için tam metin emailda
        if is_video:
            footer = f'''<a href="{a["url"]}" style="font-size:13px;color:{color};text-decoration:none;">→ Videoyu izle</a>'''
        else:
            # Makale tam metni — varsa göster, yoksa link
            full_body = a.get("body", "")
            if full_body:
                footer = f'''<details style="margin-top:12px;">
              <summary style="font-size:13px;color:{color};cursor:pointer;font-weight:600;">→ Tam yazıyı oku</summary>
              <div style="margin-top:12px;font-size:14px;color:#333;line-height:1.8;border-top:1px solid #eee;padding-top:12px;">{full_body}</div>
            </details>'''
            else:
                footer = f'''<a href="{a["url"]}" style="font-size:13px;color:{color};text-decoration:none;">→ Siteye git</a>'''

        cards += f"""
        <div style="background:#fff;border-radius:10px;padding:20px;margin-bottom:20px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.08);border-left:4px solid {color};">
          <div style="font-size:11px;color:#888;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">
            {icon} {a['source']} · {a['author']} · {a['date']}
          </div>
          <div style="color:#1a1a2e;font-size:17px;font-weight:700;">
            {a['title']}
          </div>
          <p style="color:#444;font-size:14px;line-height:1.7;margin-top:10px;">{a['summary']}</p>
          {footer}
        </div>
        """

    if not cards:
        cards = "<p style='color:#888;'>Bugün yeni içerik bulunamadı.</p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:640px;margin:30px auto;padding:0 16px;">

    <div style="background:linear-gradient(135deg,#1a1a2e,#16213e);
                border-radius:12px;padding:28px;margin-bottom:24px;text-align:center;">
      <div style="font-size:28px;margin-bottom:6px;">📰</div>
      <h1 style="color:#fff;margin:0;font-size:22px;">Günlük İçerik Özeti</h1>
      <p style="color:#a0aec0;margin:6px 0 0;font-size:14px;">{today}</p>
    </div>

    {cards}

    <div style="text-align:center;padding:16px;color:#aaa;font-size:12px;">
      Bu e-posta otomatik olarak oluşturulmuştur · Claude API ile özetlenmiştir
    </div>
  </div>
</body>
</html>"""


def send_email(html_body: str, article_count: int):
    msg = MIMEMultipart("alternative")
    recipients = [OUTLOOK_EMAIL, EXTRA_RECIPIENT]
    msg["Subject"] = f"📰 Günlük Özet — {article_count} içerik · {datetime.now().strftime('%d.%m.%Y')}"
    msg["From"]    = OUTLOOK_EMAIL
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(OUTLOOK_EMAIL, OUTLOOK_PASSWORD)
        server.sendmail(OUTLOOK_EMAIL, recipients, msg.as_string())
        print(f"✅ E-posta gönderildi: {article_count} içerik → {recipients}")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print(f"🚀 Digest başlıyor... [{datetime.now().strftime('%H:%M')}]")
    all_articles = []

    for author in CUMHURIYET_AUTHORS:
        print(f"📰 Cumhuriyet çekiliyor: {author['name']}...")
        all_articles += fetch_cumhuriyet_author(author)

    for creator in PATREON_CREATORS:
        print(f"🎨 Patreon çekiliyor: {creator['name']}...")
        all_articles += fetch_patreon(creator)

    for channel in YOUTUBE_CHANNELS:
        print(f"🎬 YouTube çekiliyor: {channel['name']}...")
        all_articles += fetch_youtube_channel(channel)

    print(f"   Toplam {len(all_articles)} içerik bulundu.")
    html = build_html(all_articles)
    send_email(html, len(all_articles))


if __name__ == "__main__":
    main()
