"""D4 forward news collector: free Indian RSS -> raw zone + sentiment.

Usage (daily, wired into run_daily_cycle):
    uv run --no-sync python scripts/collect_news.py

Sources (free, no keys): Google News India search RSS for the locked
ticker's company, Economic Times markets RSS. Raw XML snapshots are
stored immutably; parsed items append to curated news_items.jsonl,
deduplicated by link hash, each scored with VADER compound sentiment.
The archive that backtests will need in a year can only be built by
collecting it forward from today — that is this script's whole job.
"""

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

COMPANY_QUERY = "%22ICICI%20Bank%22"
FEEDS = {
    "google_news": (
        f"https://news.google.com/rss/search?q={COMPANY_QUERY}&hl=en-IN&gl=IN&ceid=IN:en"
    ),
    "et_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
}
TIMEOUT = 30.0


def parse_rss(xml_text: str, source: str) -> list[dict[str, str]]:
    items = []
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title and link:
            items.append({"source": source, "title": title, "link": link, "pub_date": pub})
    return items


def main() -> int:
    from artha.config import load_settings

    settings = load_settings()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = settings.raw_dir / "news" / stamp[:4]
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.curated_dir / "news_items.jsonl"
    seen: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(json.loads(line)["link_hash"])

    analyzer = SentimentIntensityAnalyzer()
    added = 0
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": "artha-research/1.0"}) as client:
        for source, url in FEEDS.items():
            try:
                resp = client.get(url, follow_redirects=True)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"WARNING: {source} fetch failed: {exc}", file=sys.stderr)
                continue
            (raw_dir / f"{source}_{stamp}.xml").write_bytes(resp.content)
            try:
                items = parse_rss(resp.text, source)
            except ET.ParseError as exc:
                print(f"WARNING: {source} parse failed: {exc}", file=sys.stderr)
                continue
            with out_path.open("a", encoding="utf-8") as f:
                for item in items:
                    h = hashlib.sha256(item["link"].encode()).hexdigest()[:16]
                    if h in seen:
                        continue
                    seen.add(h)
                    row = {
                        **item,
                        "link_hash": h,
                        "collected_at": datetime.now(UTC).isoformat(),
                        "sentiment": analyzer.polarity_scores(item["title"])["compound"],
                    }
                    f.write(json.dumps(row) + "\n")
                    added += 1
    print(f"news collector: {added} new items ({len(seen)} total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
