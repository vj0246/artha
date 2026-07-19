"""D4 historical news backfill: GDELT DOC 2.0 for the locked ticker.

Usage:
    uv run --no-sync python scripts/backfill_gdelt.py [2017-01] [2026-07]

Monthly queries against the free GDELT DOC API for "ICICI Bank"
coverage (2017+ is reliable for the DOC API). Raw JSON snapshots per
month in the raw zone; parsed articles append to curated
gdelt_articles.jsonl with VADER sentiment. Coverage of Indian
corporates is shallow — fidelity labeled exploratory (plan v2 already
demoted GDELT), but it is the only free historical archive available.
Idempotent: months with an existing raw snapshot are skipped.
"""

import json
import sys
import time
from datetime import UTC, datetime

import httpx
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

API = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = '"ICICI Bank"'
MAX_RECORDS = 250
SLEEP_S = 6.0  # GDELT free-tier politeness


def month_range(start: str, end: str) -> list[tuple[str, str]]:
    y0, m0 = map(int, start.split("-"))
    y1, m1 = map(int, end.split("-"))
    out = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((f"{y:04d}{m:02d}01000000", f"{ny:04d}{nm:02d}01000000"))
        y, m = ny, nm
    return out


def main() -> int:
    from artha.config import load_settings

    start = sys.argv[1] if len(sys.argv) > 1 else "2017-01"
    end = sys.argv[2] if len(sys.argv) > 2 else datetime.now(UTC).strftime("%Y-%m")
    settings = load_settings()
    raw_dir = settings.raw_dir / "news" / "gdelt"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = settings.curated_dir / "gdelt_articles.jsonl"
    analyzer = SentimentIntensityAnalyzer()

    total = 0
    with httpx.Client(timeout=60.0, headers={"User-Agent": "artha-research/1.0"}) as client:
        for lo, hi in month_range(start, end):
            snap = raw_dir / f"gdelt_{lo[:6]}.json"
            if snap.exists():
                continue
            params = {
                "query": QUERY,
                "mode": "artlist",
                "format": "json",
                "maxrecords": str(MAX_RECORDS),
                "startdatetime": lo,
                "enddatetime": hi,
                "sort": "datedesc",
            }
            try:
                resp = client.get(API, params=params)
                resp.raise_for_status()
                data = resp.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                print(f"WARNING: {lo[:6]} failed: {exc}", file=sys.stderr)
                time.sleep(SLEEP_S)
                continue
            snap.write_text(json.dumps(data), encoding="utf-8")
            articles = data.get("articles", [])
            with out_path.open("a", encoding="utf-8") as f:
                for a in articles:
                    title = a.get("title", "")
                    f.write(
                        json.dumps(
                            {
                                "seen_date": a.get("seendate"),
                                "title": title,
                                "url": a.get("url"),
                                "domain": a.get("domain"),
                                "sentiment": analyzer.polarity_scores(title)["compound"],
                            }
                        )
                        + "\n"
                    )
            total += len(articles)
            print(f"{lo[:6]}: {len(articles)} articles")
            time.sleep(SLEEP_S)
    print(f"gdelt backfill done: {total} articles this run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
