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
                "rss": "https://www.dailymail.co.uk/news/index.rss",
            },
            {
                "name": "Daily Express",
                "slug": None,  # not on frontpages.com
                "rss": "https://feeds.feedburner.com/daily-express-news-showbiz",
            },
            {
                "name": "The Mirror",
                "slug": None,  # not on frontpages.com
                "rss": "https://www.mirror.co.uk/rss.xml",
            },
        ],
    },
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
                "name": "G1 — O Globo",
                "slug": "o-globo",
                "rss": "https://g1.globo.com/rss/g1/",
            },
            {
                "name": "Valor Econômico",
                "slug": "valor-economico",
                "rss": "https://www.infomoney.com.br/feed/",
            },
            {
                "name": "O Estado de S. Paulo",
                "slug": "o-estado-de-s-paulo",
                "rss": "https://www.estadao.com.br/arc/outboundfeeds/rss/?outputType=xml",
            },
            {
                "name": "Correio Brasiliense",
                "slug": None,  # domain unreachable from this network; cover unavailable
                "rss": None,
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
                "slug": None,  # not on frontpages, RSS only
                "rss": "https://www3.nhk.or.jp/rss/news/cat0.xml",
                "translate": True,  # headlines are in Japanese
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
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_cover_image_url(slug: str, date: datetime.date) -> str | None:
    """Scrape frontpages.com/<slug>/ page and return the cover image URL for today.

    The main cover is loaded via JavaScript (id="giornale-img" has no src in HTML).
    The og:image meta tag contains the correct paper-specific URL but uses the /g/
    path which returns 404. We convert it to the working /t/ thumbnail path.
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
    date_prefix = date.strftime("%Y/%m/%d")

    # og:image has the right paper-specific URL but uses /g/ path (404).
    # Convert: /g/YYYY/MM/DD/slug-XXX.webp.jpg  ->  /t/YYYY/MM/DD/slug-XXX.webp
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        content = og["content"]
        if date_prefix in content and "/g/" in content:
            t_url = content.replace("/g/", "/t/").removesuffix(".jpg")
            return t_url
        # If already a /t/ URL with today's date, use as-is
        if date_prefix in content and "/t/" in content:
            return content

    print(f"  [WARN] No cover image found for slug '{slug}' on {date_prefix}")
    return None


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
            title = entry.get("title", "").strip()
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
    "United States": "#B22234",
    "United Kingdom": "#00247D",
    "Brazil": "#009C3B",
    "Portugal": "#006600",
    "Japan": "#BC002D",
    "Spain": "#AA151B",
    "France": "#002395",
}

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Daily Newspaper Front Pages – {date}</title>
<style>
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #f4f4f4;
    color: #222;
    margin: 0;
    padding: 0;
  }}
  .wrapper {{
    max-width: 900px;
    margin: 0 auto;
    background: #fff;
  }}
  .header {{
    background: #111;
    color: #fff;
    padding: 28px 32px 20px;
    text-align: center;
  }}
  .header h1 {{
    margin: 0 0 4px;
    font-size: 26px;
    letter-spacing: 1px;
  }}
  .header p {{
    margin: 0;
    color: #aaa;
    font-size: 13px;
  }}
  .country-section {{
    padding: 24px 32px;
    border-bottom: 3px solid #eee;
  }}
  .country-title {{
    font-size: 20px;
    font-weight: 700;
    margin: 0 0 18px;
    padding-bottom: 8px;
    border-bottom: 2px solid;
  }}
  .paper-block {{
    display: flex;
    gap: 20px;
    margin-bottom: 28px;
    align-items: flex-start;
  }}
  .paper-cover {{
    flex: 0 0 130px;
  }}
  .paper-cover img {{
    width: 130px;
    border: 1px solid #ccc;
    border-radius: 3px;
    display: block;
  }}
  .paper-cover .no-cover {{
    width: 130px;
    height: 175px;
    background: #e8e8e8;
    border: 1px solid #ccc;
    border-radius: 3px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #999;
    font-size: 11px;
    text-align: center;
  }}
  .paper-headlines {{
    flex: 1;
  }}
  .paper-name {{
    font-size: 15px;
    font-weight: 700;
    margin: 0 0 10px;
    color: #333;
  }}
  .headlines-list {{
    list-style: none;
    margin: 0;
    padding: 0;
  }}
  .headlines-list li {{
    padding: 5px 0;
    border-bottom: 1px solid #f0f0f0;
    font-size: 13px;
    line-height: 1.5;
  }}
  .headlines-list li:last-child {{
    border-bottom: none;
  }}
  .headlines-list a {{
    color: #1a1a1a;
    text-decoration: none;
  }}
  .headlines-list a:hover {{
    text-decoration: underline;
  }}
  .headline-translation {{
    font-size: 11px;
    color: #777;
    font-style: italic;
    margin-top: 2px;
  }}
  .no-headlines {{
    font-size: 12px;
    color: #aaa;
    font-style: italic;
  }}
  .footer {{
    background: #f8f8f8;
    text-align: center;
    padding: 18px;
    font-size: 11px;
    color: #aaa;
    border-top: 1px solid #ddd;
  }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>📰 Daily Newspaper Front Pages</h1>
    <p>{date_long}</p>
  </div>
  {country_blocks}
  <div class="footer">
    Generated automatically · Sources: frontpages.com + RSS feeds · {date}
  </div>
</div>
</body>
</html>
"""


def build_paper_block(paper: dict, cover_url: str | None, headlines: list[dict]) -> str:
    if cover_url:
        cover_html = f'<img src="{cover_url}" alt="{paper["name"]} front page">'
    else:
        cover_html = '<div class="no-cover">No cover<br>available</div>'

    if headlines:
        items = []
        for h in headlines:
            line = f'<a href="{h["link"]}" target="_blank">{h["title"]}</a>'
            if h.get("translation"):
                line += f'<div class="headline-translation">{h["translation"]}</div>'
            items.append(f"<li>{line}</li>")
        headlines_html = f'<ul class="headlines-list">{"".join(items)}</ul>'
    else:
        headlines_html = '<p class="no-headlines">No headlines available</p>'

    return f"""\
<div class="paper-block">
  <div class="paper-cover">{cover_html}</div>
  <div class="paper-headlines">
    <div class="paper-name">{paper["name"]}</div>
    {headlines_html}
  </div>
</div>"""


def build_country_block(country: dict, papers_data: list[dict], color: str) -> str:
    paper_blocks = "\n".join(
        build_paper_block(p["paper"], p["cover_url"], p["headlines"])
        for p in papers_data
    )
    return f"""\
<div class="country-section">
  <div class="country-title" style="border-color:{color}; color:{color};">
    {country["flag"]} {country["name"]}
  </div>
  {paper_blocks}
</div>"""


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

            print(f"    -> RSS headlines...")
            headlines = get_rss_headlines(paper.get("rss"), limit=5)
            # Strip source suffix appended by Google News aggregation (e.g. " - Jornal de Notícias")
            if paper.get("strip_source"):
                suffix = f" - {paper['strip_source']}"
                headlines = [
                    {**h, "title": h["title"].removesuffix(suffix)} for h in headlines
                ]
            print(f"       {len(headlines)} headlines fetched")

            if paper.get("translate") and headlines:
                print(f"    -> translating headlines to English...")
                headlines = translate_headlines(headlines)

            papers_data.append(
                {"paper": paper, "cover_url": cover_url, "headlines": headlines}
            )

        all_data.append({"country": country, "papers_data": papers_data})

    html = build_html(today, all_data)

    subject = f"📰 Newspaper Front Pages – {today.strftime('%A, %B %d, %Y')}"
    send_email(subject, html)


if __name__ == "__main__":
    main()
