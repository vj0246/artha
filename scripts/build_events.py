"""Build curated event tables from the raw events zone (P1b).

Usage:
    uv run python scripts/build_events.py

Outputs under $ARTHA_DATA_DIR/curated/events: announcements.parquet,
board_meetings.parquet, bulk_deals.parquet, plus a corpus QA report in the
reports dir (coverage per year, timestamp sanity, null rates). QA failures
exit 1.
"""

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from artha.config import load_settings
from artha.events.ingest import parse_announcements, parse_board_meetings


def build_table(files: list[Path], parser: Callable[[bytes], pl.DataFrame]) -> pl.DataFrame:
    frames = [parser(f.read_bytes()) for f in files]
    return pl.concat([f for f in frames if not f.is_empty()])


def main() -> int:
    settings = load_settings()
    out_dir = settings.curated_dir / "events"
    out_dir.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    summary: dict[str, object] = {}

    ann_files = sorted(settings.raw_dir.glob("events/announcements/*/ann_*.json"))
    ann = build_table(ann_files, parse_announcements)
    ann.write_parquet(out_dir / "announcements.parquet")
    per_year = dict(
        ann.group_by(pl.col("announced_at").dt.year().alias("y")).len().sort("y").iter_rows()
    )
    null_symbol = ann["symbol"].null_count() / ann.height
    after_close = (
        ann.filter(pl.col("announced_at").dt.time() >= pl.time(15, 30)).height / ann.height
    )
    summary["announcements"] = {
        "rows": ann.height,
        "files": len(ann_files),
        "per_year": per_year,
        "null_symbol_pct": round(100 * null_symbol, 2),
        "after_close_pct": round(100 * after_close, 1),
        "ts_range": [str(ann["announced_at"].min()), str(ann["announced_at"].max())],
    }
    # every backfilled year must be present with a sane floor
    for y, n in per_year.items():
        if n < 1000:
            errors.append(f"announcements {y}: only {n} records")
    if null_symbol > 0.10:
        errors.append(f"announcements: {null_symbol:.1%} rows without symbol")

    bm_files = sorted(settings.raw_dir.glob("events/board_meetings/*/bm_*.json"))
    bm = build_table(bm_files, parse_board_meetings)
    bm.write_parquet(out_dir / "board_meetings.parquet")
    bm_year = dict(
        bm.group_by(pl.col("meeting_date").dt.year().alias("y")).len().sort("y").iter_rows()
    )
    summary["board_meetings"] = {"rows": bm.height, "files": len(bm_files), "per_year": bm_year}
    if bm.height < 10_000:
        errors.append(f"board meetings: only {bm.height} rows total")

    # Bulk deals: the historicalOR endpoint caps every window at 70 rows
    # (found 2026-07-13: exactly 70 x 198 monthly files), so the raw zone is
    # truncated. No curated table is built; complete re-ingest needs daily
    # windows (~4,100 requests) and is deferred until P4 decides it wants
    # bulk-deal features at all.
    bulk_files = sorted(settings.raw_dir.glob("events/bulk_deals/*/bulk_*.json"))
    summary["bulk_deals"] = {
        "files": len(bulk_files),
        "status": "DEFERRED - API truncates windows at 70 rows; no curated table",
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {"ok": not errors, "errors": errors, "summary": summary}
    path = settings.reports_dir / f"events_qa_{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"report: {path}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
