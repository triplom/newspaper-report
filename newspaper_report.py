#!/usr/bin/env python3
"""
Newspaper Front Page Daily Email
Scrapes cover images from frontpages.com and top headlines from RSS feeds,
then sends a rich HTML email with sections per country.
"""

import os
import re
import time
import smtplib
import datetime
import urllib.parse
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup
import feedparser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GMAIL_USER = os.environ.get("GMAIL_USER", "triplom@gmail.com")
GMAIL_SENDER_NAME = "Newspaper Front Pages"
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
RECIPIENT = os.environ.get("RECIPIENT_EMAIL", "triplom@gmail.com")
EXTRA_RECIPIENTS = [
    r.strip()
    for r in os.environ.get("EXTRA_RECIPIENTS", "rocassas@gmail.com").split(",")
    if r.strip()
]
ALL_RECIPIENTS = list(
    dict.fromkeys([RECIPIENT] + EXTRA_RECIPIENTS)
)  # dedup, preserve order

FRONTPAGES_BASE = "https://www.frontpages.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# Newspaper definitions
# each paper: slug (frontpages.com), rss_url, display_name
# ---------------------------------------------------------------------------

COUNTRIES = [
    {
        "name": "Brazil",
        "flag": "🇧🇷",
        "papers": [
            {
                "name": "Folha de S.Paulo",
                "slug": "folha-de-s-paulo",
                "rss": "https://feeds.folha.uol.com.br/emcimadahora/rss091.xml",
            },
            {
                "name": "O Globo",
                "slug": "o-globo",
                "rss": "https://news.google.com/rss/search?q=site:oglobo.globo.com&hl=pt-BR&gl=BR&ceid=BR:pt-419",
                "strip_source": "O Globo",
            },
            {
                "name": "Valor Econômico",
                "slug": "valor-economico",
                "rss": "https://news.google.com/rss/search?q=site:valor.globo.com&hl=pt-BR&gl=BR&ceid=BR:pt-419",
                "strip_source": "Valor Econômico",
            },
            {
                "name": "O Estado de S. Paulo",
                "slug": "o-estado-de-s-paulo",
                "rss": "https://www.estadao.com.br/arc/outboundfeeds/rss/?outputType=xml",
            },
            {
                "name": "Correio Brasiliense",
                "slug": None,  # not on frontpages.com
                "rss": "https://news.google.com/rss/search?q=site:correiobraziliense.com.br&hl=pt-BR&gl=BR&ceid=BR:pt-419",
                "strip_source": "Correio Braziliense",
            },
        ],
    },
    {
        "name": "Portugal",
        "flag": "🇵🇹",
        "papers": [
            {
                "name": "Público",
                "slug": "publico",
                "rss": "https://feeds.feedburner.com/PublicoRSS",
            },
            {
                "name": "Diário de Notícias",
                "slug": "diario-de-noticias",
                "rss": "https://www.dn.pt/feed/",
            },
            {
                "name": "Correio da Manhã",
                "slug": "correio-da-manha",
                "rss": "https://www.cmjornal.pt/rss",
            },
            {
                "name": "Jornal de Notícias",
                "slug": "jornal-de-noticias",
                "rss": "https://news.google.com/rss/search?q=site:jn.pt&hl=pt-PT&gl=PT&ceid=PT:pt",
                "strip_source": "Jornal de Notícias",
            },
        ],
    },
    {
        "name": "Spain",
        "flag": "🇪🇸",
        "papers": [
            {
                "name": "El País",
                "slug": "el-pais",
                "rss": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
            },
            {
                "name": "El Mundo",
                "slug": "el-mundo",
                "rss": "https://e00-elmundo.uecdn.es/elmundo/rss/portada.xml",
            },
        ],
    },
    {
        "name": "United States",
        "flag": "🇺🇸",
        "papers": [
            {
                "name": "The New York Times",
                "slug": "the-new-york-times",
                "rss": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
            },
            {
                "name": "The Washington Post",
                "slug": "the-washington-post",
                "rss": "https://feeds.washingtonpost.com/rss/national",
            },
            {
                "name": "Los Angeles Times",
                "slug": "los-angeles-times",
                "rss": "https://www.latimes.com/rss2.0.xml",
            },
        ],
    },
    {
        "name": "United Kingdom",
        "flag": "🇬🇧",
        "papers": [
            {
                "name": "The Guardian",
                "slug": "the-guardian-usa",
                "rss": "https://www.theguardian.com/uk/rss",
            },
            {
                "name": "Financial Times",
                "slug": "financial-times",
                "rss": "https://www.ft.com/rss/home",
            },
            {
                "name": "City A.M.",
                "slug": "city-am",
                "rss": "https://www.cityam.com/feed/",
            },
            {
                "name": "Daily Mail",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.dailymail.co.uk/articles.rss",
            },
            {
                "name": "Daily Express",
                "slug": None,  # not on frontpages.com
                "cover_cdn": "express",  # cdn.images.express.co.uk
                "rss": "https://www.express.co.uk/posts/rss/77/news",
            },
            {
                "name": "The Mirror",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.mirror.co.uk/news/?service=rss",
            },
        ],
    },
    {
        "name": "France",
        "flag": "🇫🇷",
        "papers": [
            {
                "name": "Le Monde",
                "slug": "le-monde",
                "rss": "https://www.lemonde.fr/rss/une.xml",
            },
            {
                "name": "Le Figaro",
                "slug": "le-figaro",
                "rss": "https://www.lefigaro.fr/rss/figaro_actualites.xml",
            },
        ],
    },
    {
        "name": "Germany",
        "flag": "🇩🇪",
        "papers": [
            {
                "name": "Frankfurter Allgemeine Zeitung",
                "slug": "frankfurter-allgemeine-zeitung",
                "rss": "https://www.faz.net/rss/aktuell/",
                "translate": "de",
            },
            {
                "name": "Süddeutsche Zeitung",
                "slug": "suddeutsche-zeitung",
                "rss": "https://rss.sueddeutsche.de/rss/Topthemen",
                "translate": "de",
            },
            {
                "name": "Die Welt",
                "slug": "die-welt",
                "rss": "https://www.welt.de/feeds/latest.rss",
                "translate": "de",
            },
            {
                "name": "Handelsblatt",
                "slug": "handelsblatt",
                "rss": "https://www.handelsblatt.com/contentexport/feed/top-themen",
                "translate": "de",
            },
        ],
    },
    {
        "name": "Italy",
        "flag": "🇮🇹",
        "papers": [
            {
                "name": "La Repubblica",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.repubblica.it/rss/homepage/rss2.0.xml",
            },
            {
                "name": "Corriere della Sera",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.corriere.it/rss/homepage.xml",
            },
            {
                "name": "La Stampa",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.lastampa.it/rss/copertina.xml",
            },
        ],
    },
    {
        "name": "Japan",
        "flag": "🇯🇵",
        "papers": [
            {
                "name": "The Japan Times",
                "slug": "the-japan-times",
                "rss": "https://www.japantimes.co.jp/feed/",
            },
            {
                "name": "NHK World",
                "slug": None,  # not on frontpages
                "rss": "https://news.google.com/rss/search?q=site:nhk.or.jp/nhkworld&hl=en-US&gl=US&ceid=US:en",
                "strip_source": "NHK WORLD-JAPAN News",
            },
        ],
    },
    {
        "name": "Australia",
        "flag": "🇦🇺",
        "papers": [
            {
                "name": "The Australian",
                "slug": "the-australian",
                "rss": "https://news.google.com/rss/search?q=site:theaustralian.com.au&hl=en-AU&gl=AU&ceid=AU:en",
                "strip_source": "The Australian",
            },
            {
                "name": "Sydney Morning Herald",
                "slug": "the-sydney-morning-herald",
                "rss": "https://www.smh.com.au/rss/feed.xml",
            },
            {
                "name": "ABC News Australia",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.abc.net.au/news/feed/51120/rss.xml",
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_cover_image_url(slug: str, date: datetime.date) -> str | None:
    """Scrape frontpages.com/<slug>/ page and return the cover image URL.

    The main cover is loaded via JavaScript (id="giornale-img" has no src in HTML).
    The og:image meta tag contains the correct paper-specific URL but uses the /g/
    path which returns 404. We convert it to the working /t/ thumbnail path.

    Some papers (e.g. FT, City AM, Le Monde) publish the previous day's edition
    overnight, so we accept covers dated today or yesterday.
    """
    if not slug:
        return None
    url = f"{FRONTPAGES_BASE}/{slug}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [WARN] Could not fetch {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    # Accept up to 7 days back: FT/City AM publish previous edition overnight,
    # and on weekends/holidays some papers skip days (City AM is Mon-Fri only,
    # German/French papers skip public holidays). range(8) covers the worst case:
    # a paper that doesn't publish on a 4-day long weekend (e.g. Easter Thu-Mon)
    # will still have its last edition within 7 days when checked on Tuesday.
    acceptable_dates = {
        (date - datetime.timedelta(days=i)).strftime("%Y/%m/%d") for i in range(8)
    }

    # og:image has the right paper-specific URL but uses /g/ path (404).
    # Convert: /g/YYYY/MM/DD/slug-XXX.webp.jpg  ->  /t/YYYY/MM/DD/slug-XXX.webp
    # Then proxy through images.weserv.nl to convert WebP -> JPEG (Gmail doesn't support WebP).
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        content = og["content"]
        if any(dp in content for dp in acceptable_dates):
            if "/g/" in content:
                webp_url = content.replace("/g/", "/t/").removesuffix(".jpg")
            elif "/t/" in content:
                webp_url = content
            else:
                webp_url = None
            if webp_url:
                # Proxy through wsrv.nl: converts WebP to JPEG which Gmail can display
                # wsrv.nl is the canonical domain for images.weserv.nl (same CDN)
                encoded = urllib.parse.quote(webp_url, safe="")
                proxy_url = f"https://wsrv.nl/?url={encoded}&output=jpg&w=130"
                # Verify the proxy actually returns a valid image before using the URL
                try:
                    check = requests.get(proxy_url, headers=HEADERS, timeout=10)
                    if check.status_code == 200 and check.content[:2] == b"\xff\xd8":
                        return proxy_url
                    else:
                        print(
                            f"  [WARN] wsrv.nl returned {check.status_code} for {slug}"
                        )
                except Exception as e:
                    print(f"  [WARN] wsrv.nl check failed for {slug}: {e}")

    print(
        f"  [WARN] No cover image found for slug '{slug}' on {date.strftime('%Y/%m/%d')}"
    )
    return None


def get_cover_image_url_cdn(cover_cdn: str, date: datetime.date) -> str | None:
    """Fetch a cover image from a known publisher CDN when the paper is not on frontpages.com.

    Supported values for cover_cdn:
      "express" – Daily Express via cdn.images.express.co.uk
                  URL: .../img/covers/70x91/front_YYYY-MM-DD.jpg
                  The 70x91 thumbnail is the only publicly accessible size;
                  wsrv.nl upscales it to w=130 for display consistency.
    """
    if cover_cdn == "express":
        # Try today and up to 7 days back (handles weekends/holidays)
        for i in range(8):
            d = date - datetime.timedelta(days=i)
            raw_url = (
                f"https://cdn.images.express.co.uk/img/covers/70x91/"
                f"front_{d.strftime('%Y-%m-%d')}.jpg"
            )
            try:
                check = requests.get(raw_url, headers=HEADERS, timeout=10)
                if check.status_code == 200 and check.content[:2] == b"\xff\xd8":
                    # Proxy through wsrv.nl to resize to w=130 (consistent with frontpages covers)
                    encoded = urllib.parse.quote(raw_url, safe="")
                    return f"https://wsrv.nl/?url={encoded}&output=jpg&w=130"
            except Exception as e:
                print(f"  [WARN] Express CDN check failed ({d}): {e}")
    print(f"  [WARN] No CDN cover found for cover_cdn='{cover_cdn}' on {date}")
    return None


def _strip_cdata(text: str) -> str:
    """Remove CDATA wrappers that some malformed RSS feeds leave in text fields."""
    text = text.strip()
    if text.startswith("<![CDATA[") and text.endswith("]]>"):
        text = text[9:-3].strip()
    return text


def get_rss_headlines(rss_url: str, limit: int = 5) -> list[dict]:
    """Fetch top N headlines from an RSS feed. Returns list of {title, link}."""
    if not rss_url:
        return []
    try:
        # Pre-fetch with requests so redirects and headers are handled correctly,
        # then pass the raw content to feedparser to avoid redirect/bozo issues.
        resp = requests.get(rss_url, headers=HEADERS, timeout=15)
        feed = feedparser.parse(resp.content)
        results = []
        for entry in feed.entries[:limit]:
            title = _strip_cdata(entry.get("title", "").strip())
            link = entry.get("link", "").strip()
            if title:
                results.append({"title": title, "link": link})
        return results
    except Exception as e:
        print(f"  [WARN] RSS fetch failed for {rss_url}: {e}")
        return []


def translate_to_english(text: str, source_lang: str = "ja") -> str:
    """Translate text to English using the MyMemory free API (no key required)."""
    try:
        encoded = urllib.parse.quote(text[:450])  # API limit ~500 chars
        url = f"https://api.mymemory.translated.net/get?q={encoded}&langpair={source_lang}|en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            import json

            data = json.loads(resp.read())
            translated = data["responseData"]["translatedText"]
            # MyMemory returns the original if it can't translate
            if translated and translated.strip() != text.strip():
                return translated.strip()
    except Exception as e:
        print(f"  [WARN] Translation failed: {e}")
    return ""


def translate_headlines(headlines: list[dict], source_lang: str = "ja") -> list[dict]:
    """Return new list of headlines with an added 'translation' key."""
    translated = []
    for h in headlines:
        en = translate_to_english(h["title"], source_lang)
        time.sleep(0.3)  # be polite to the free API
        translated.append({**h, "translation": en})
    return translated


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

COUNTRY_COLORS = {
    "Brazil": "#009C3B",
    "Portugal": "#006600",
    "Spain": "#AA151B",
    "United States": "#B22234",
    "United Kingdom": "#00247D",
    "France": "#002395",
    "Germany": "#000000",
    "Italy": "#009246",
    "Japan": "#BC002D",
    "Australia": "#00008B",
}

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Newspaper Front Pages – {date}</title>
</head>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#f4f4f4;color:#222;margin:0;padding:0;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f4f4;">
<tr><td align="center">
<table width="700" cellpadding="0" cellspacing="0" border="0" style="background:#fff;max-width:700px;">
  <!-- HEADER -->
  <tr>
    <td style="background:#111;color:#fff;padding:24px 32px;text-align:center;">
      <div style="font-size:24px;font-weight:700;letter-spacing:1px;margin-bottom:4px;">&#128240; Daily Newspaper Front Pages</div>
      <div style="font-size:13px;color:#aaa;">{date_long}</div>
    </td>
  </tr>
  <!-- COUNTRY BLOCKS -->
  {country_blocks}
  <!-- FOOTER -->
  <tr>
    <td style="background:#f8f8f8;text-align:center;padding:16px;font-size:11px;color:#aaa;border-top:1px solid #ddd;">
      Generated automatically &middot; Sources: frontpages.com + RSS feeds &middot; {date}
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def build_paper_block(paper: dict, cover_url: str | None, headlines: list[dict]) -> str:
    if cover_url:
        cover_html = (
            f'<img src="{cover_url}" alt="{paper["name"]} front page" '
            f'width="130" style="display:block;border:1px solid #ccc;border-radius:3px;">'
        )
    else:
        cover_html = (
            '<table width="130" cellpadding="0" cellspacing="0" border="0">'
            '<tr><td width="130" height="175" align="center" valign="middle" '
            'style="background:#e8e8e8;border:1px solid #ccc;border-radius:3px;'
            'color:#999;font-size:11px;text-align:center;font-family:Arial,sans-serif;">'
            "No cover<br>available</td></tr></table>"
        )

    if headlines:
        rows = []
        for h in headlines:
            link_html = f'<a href="{h["link"]}" target="_blank" style="color:#1a1a1a;text-decoration:none;">{h["title"]}</a>'
            if h.get("translation"):
                link_html += f'<div style="font-size:11px;color:#777;font-style:italic;margin-top:2px;">{h["translation"]}</div>'
            rows.append(
                f'<tr><td style="padding:5px 0;border-bottom:1px solid #f0f0f0;'
                f'font-size:13px;line-height:1.5;font-family:Arial,sans-serif;">{link_html}</td></tr>'
            )
        headlines_html = (
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0">'
            f"{''.join(rows)}</table>"
        )
    else:
        headlines_html = '<p style="font-size:12px;color:#aaa;font-style:italic;margin:0;">No headlines available</p>'

    return f"""\
<tr>
  <td style="padding:0 0 20px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      <tr valign="top">
        <td width="130" style="padding-right:16px;">{cover_html}</td>
        <td>
          <div style="font-size:15px;font-weight:700;margin-bottom:8px;color:#333;font-family:Arial,sans-serif;">{paper["name"]}</div>
          {headlines_html}
        </td>
      </tr>
    </table>
  </td>
</tr>"""


def build_country_block(country: dict, papers_data: list[dict], color: str) -> str:
    paper_rows = "\n".join(
        build_paper_block(p["paper"], p["cover_url"], p["headlines"])
        for p in papers_data
    )
    return f"""\
<tr>
  <td style="padding:20px 32px;border-bottom:3px solid #eee;">
    <div style="font-size:19px;font-weight:700;margin-bottom:16px;padding-bottom:8px;
                border-bottom:2px solid {color};color:{color};font-family:Arial,sans-serif;">
      {country["flag"]} {country["name"]}
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" border="0">
      {paper_rows}
    </table>
  </td>
</tr>"""


def build_html(today: datetime.date, all_data: list[dict]) -> str:
    date_str = today.strftime("%Y-%m-%d")
    date_long = today.strftime("%A, %B %d, %Y")
    country_blocks = "\n".join(
        build_country_block(
            item["country"],
            item["papers_data"],
            COUNTRY_COLORS.get(item["country"]["name"], "#444"),
        )
        for item in all_data
    )
    return HTML_TEMPLATE.format(
        date=date_str,
        date_long=date_long,
        country_blocks=country_blocks,
    )


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{GMAIL_SENDER_NAME} <{GMAIL_USER}>"
    msg["To"] = ", ".join(ALL_RECIPIENTS)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, ALL_RECIPIENTS, msg.as_string())
    print(f"Email sent to {', '.join(ALL_RECIPIENTS)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    today = datetime.date.today()
    print(f"Running newspaper report for {today}")

    all_data = []

    for country in COUNTRIES:
        print(f"\n[{country['flag']} {country['name']}]")
        papers_data = []

        for paper in country["papers"]:
            print(f"  {paper['name']}")

            print(f"    -> cover image...")
            cover_url = get_cover_image_url(paper.get("slug"), today)
            if not cover_url and paper.get("cover_cdn"):
                cover_url = get_cover_image_url_cdn(paper["cover_cdn"], today)
            if cover_url:
                print(f"       cover: {cover_url[:80]}...")

            print(f"    -> RSS headlines...")
            headlines = get_rss_headlines(paper.get("rss"), limit=3)
            # Strip source suffix appended by Google News aggregation (e.g. " - Jornal de Notícias")
            if paper.get("strip_source"):
                suffix = f" - {paper['strip_source']}"
                headlines = [
                    {**h, "title": h["title"].removesuffix(suffix)} for h in headlines
                ]
            print(f"       {len(headlines)} headlines fetched")

            if paper.get("translate") and headlines:
                print(f"    -> translating headlines to English...")
                translate_val = paper["translate"]
                lang = translate_val if isinstance(translate_val, str) else "ja"
                headlines = translate_headlines(headlines, source_lang=lang)

            papers_data.append(
                {"paper": paper, "cover_url": cover_url, "headlines": headlines}
            )

        all_data.append({"country": country, "papers_data": papers_data})

    html = build_html(today, all_data)
    print(
        f"HTML size: {len(html.encode('utf-8'))} bytes ({len(html.encode('utf-8')) // 1024} KB)"
    )

    subject = f"📰 Newspaper Front Pages – {today.strftime('%A, %B %d, %Y')}"
    send_email(subject, html)


if __name__ == "__main__":
    main()
