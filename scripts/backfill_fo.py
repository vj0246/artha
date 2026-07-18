"""Backfill F&O bhavcopy zips (NIFTY futures study window).

Usage:
    uv run --no-sync python scripts/backfill_fo.py 2021-01-01 2026-07-18

Same idempotent, polite, all-calendar-days semantics as the other
backfills; the hedge study only needs 2021+ but the range is free to
extend.
"""

import argparse
import sys
from datetime import date

from artha.config import load_settings
from artha.data.backfill import calendar_days, run_backfill
from artha.data.ingest.fo import download_fo_bhavcopy, fo_relpath


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=date.fromisoformat)
    parser.add_argument("end", type=date.fromisoformat)
    args = parser.parse_args()

    result, _ = run_backfill(
        "fo_bhavcopy",
        calendar_days(args.start, args.end),
        fo_relpath,
        download_fo_bhavcopy,
        load_settings(),
    )
    if not result.ok:
        print("FAILURES PRESENT - rerun after diagnosing; raw zone is idempotent.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
