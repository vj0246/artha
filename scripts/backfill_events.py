"""Backfill NSE event data (P1b): announcements, board meetings, bulk deals.

Usage:
    uv run python scripts/backfill_events.py [--start 2010-01] [--end 2026-06]
    uv run python scripts/backfill_events.py --datasets announcements

Monthly JSON files into the immutable raw zone; the current month is never
fetched. Idempotent and polite, same semantics as the other backfills.
"""

import argparse
import sys
from datetime import date, datetime

from artha.config import load_settings
from artha.data.backfill import last_complete_month, month_range, run_backfill
from artha.data.ingest.nse_http import nse_api_client
from artha.events.ingest import (
    ANNOUNCEMENTS_START,
    BOARD_MEETINGS_START,
    BULK_DEALS_START,
    announcements_relpath,
    board_meetings_relpath,
    bulk_deals_relpath,
    download_announcements_month,
    download_board_meetings_month,
    download_bulk_deals_month,
)

DATASETS = {
    "announcements": (ANNOUNCEMENTS_START, announcements_relpath, download_announcements_month),
    "board_meetings": (BOARD_MEETINGS_START, board_meetings_relpath, download_board_meetings_month),
    "bulk_deals": (BULK_DEALS_START, bulk_deals_relpath, download_bulk_deals_month),
}


def month_arg(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=month_arg, default=None)
    parser.add_argument("--end", type=month_arg, default=None)
    parser.add_argument("--datasets", nargs="*", choices=sorted(DATASETS), default=sorted(DATASETS))
    args = parser.parse_args()

    last_complete = last_complete_month(date.today())
    end = min(args.end, last_complete) if args.end else last_complete

    ok = True
    for name in args.datasets:
        default_start, relpath_fn, download_fn = DATASETS[name]
        start = args.start or default_start
        result, _ = run_backfill(
            f"events_{name}",
            month_range(start, end),
            relpath_fn,
            download_fn,
            load_settings(),
            client_factory=nse_api_client,
        )
        ok = ok and result.ok
    if not ok:
        print("FAILURES PRESENT - rerun after diagnosing; raw zone is idempotent.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
