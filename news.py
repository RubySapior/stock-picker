"""
News fetcher for the stock-picker dashboard.

Pulls live RSS headlines from Yahoo Finance for every held ticker, tags each
story with a ticker, industry, and the related theories (convictions), scores
headline sentiment (positive/negative/neutral), and returns two lists:

  - big_stories: a short "top of feed" lineup (5, diversified by ticker).
  - feed:       detailed live summaries (recency-sorted).

Usage:  from news import build_news; build_news(positions)
"""
import concurrent.futures
import email.utils
import json
import time
import urllib.request
import xml.etree.ElementTree as ET

from vader.vader import SentimentIntensityAnalyzer

RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={s}&region=US&lang=en-US"
USER_AGENT = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Sleeve -> convictions the news is evidence for/against.
# NOTE: keys must match each position's `sleeve` value in portfolio.json.
# build_news() is called from update.py (write_dashboard) every run.
SLEEVE_THEORY = {
    "Tech/AI Growth": ["T1", "T7", "T2", "T14"],
    "AI Power - Nuclear": ["T3"],
    "Broadening / Value": ["T10", "T15"],
    "Contrarian Fear": ["T13"],
    "Crisis Alpha - AI Bust": ["T6", "T17"],
    "Crisis Alpha - Carry Unwind": ["T6", "T18", "T21"],
    "Crisis Alpha - Vol Decay": ["T6", "T17", "T21"],
    "Crisis Alpha - Down-Day Floor": ["T6", "T17"],
    "Crisis Alpha - Real Assets": ["T6", "T9", "T19", "T20", "T21"],
    "Crisis Alpha - Inflation": ["T6", "T20"],
    "Crisis Alpha - Anti-Beta": ["T6", "T17"],
    "Crisis Alpha - Trend": ["T6", "T18", "T19", "T21"],
}

TICKER_INDUSTRY = {
    "TQQQ": "Leveraged Tech", "SOXL": "Semis", "SMH": "Semis",
    "DRAM": "AI Memory/HBM", "PLTR": "AI Software",
    "NLR": "Nuclear/Power", "NUKZ": "Nuclear/Power",
    "IWM": "Small Caps", "IWDL": "Value Factor",
    "XLY": "Consumer Disc.", "EZU": "Europe/Eurozone",
    "ZROZ": "Long Treasuries", "FXY": "Yen FX", "VIXM": "Volatility",
    "QFLR": "Nasdaq Hedged", "GLD": "Gold", "GDX": "Gold Miners",
    "BTAL": "Anti-Beta Factor", "DBMF": "Managed Futures",
    "TIP": "TIPS / Inflation",
}

_ANALYZER = SentimentIntensityAnalyzer()


def _sentiment(title):
    """VADER compound score (-1..1) -> 'positive' / 'negative' / 'neutral'."""
    compound = _ANALYZER.polarity_scores(title)["compound"]
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


def _parse_feed(symbol):
    """Fetch a Yahoo RSS headline feed for symbol -> list of raw items."""
    url = RSS_URL.format(s=symbol)
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=12) as r:
        data = r.read()
    root = ET.fromstring(data)
    out = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = it.findtext("pubDate") or ""
        if not title:
            continue
        ts = 0
        try:
            ts = int(email.utils.parsedate_to_datetime(pub).timestamp())
        except Exception:
            pass
        out.append({"title": title, "link": link, "pubdate": pub, "ts": ts})
    return out


def build_news(positions, max_feed=30, max_big=5):
    """Return {'asof', 'big_stories', 'feed'} for the dashboard."""
    if not positions:
        return {"asof": None, "big_stories": [], "feed": []}

    metas = {}
    by_ticker = {}
    for p in positions:
        sym = p["ticker"]
        sleeve = p.get("sleeve", "")
        metas[sym] = {
            "industry": TICKER_INDUSTRY.get(sym, "Equities"),
            "theory": SLEEVE_THEORY.get(sleeve, []),
        }
        by_ticker.setdefault(sym, []).append(p)

    # Fetch every unique ticker feed concurrently.
    raw = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_parse_feed, sym): sym for sym in metas}
        for fut in concurrent.futures.as_completed(futs):
            sym = futs[fut]
            try:
                raw[sym] = fut.result()
            except Exception as exc:
                print(f"  WARN: news feed failed for {sym}: {exc}")
                raw[sym] = []

    date_fmt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    items = []
    seen = set()
    for sym, rows in raw.items():
        meta = metas[sym]
        for r in rows:
            key = r["title"].lower()
            if key in seen:
                continue
            seen.add(key)
            when = ""
            if r["ts"]:
                when = time.strftime("%b %d, %I:%M %p", time.localtime(r["ts"]))
            items.append({
                "title": r["title"],
                "link": r["link"],
                "ts": r["ts"],
                "when": when,
                "ticker": sym,
                "industry": meta["industry"],
                "theory": meta["theory"],
                "sent": _sentiment(r["title"]),
            })

    items.sort(key=lambda i: i["ts"], reverse=True)

    # Big stories: most recent, one per source ticker for variety.
    big, seen_t = [], set()
    for it in items:
        if len(big) >= max_big:
            break
        if it["ticker"] in seen_t:
            continue
        seen_t.add(it["ticker"])
        big.append(it)

    return {
        "asof": date_fmt,
        "big_stories": big,
        "feed": items[:max_feed],
    }