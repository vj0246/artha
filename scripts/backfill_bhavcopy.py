"""Backfill the NSE bhavcopy raw zone over a date range.

Usage:
    uv run python scripts/backfill_bhavcopy.py 2010-01-01 2026-07-08

Idempotent: already-stored days are skipped, so the script can be re-run
after any interruption. All calendar days are attempted because NSE holds
occasional weekend sessions (budget days, muhurat, DR drills); 404s are
expected on holidays and recorded for later reconciliation against the
trading calendar. Any other failure makes the exit code non-zero.
Politeness: one request per ~0.6s against nsearchives.nseindia.com.
"""

import argparse
import sys
from datetime import date

from artha.config import load_settings
from artha.data.backfill import calendar_days, run_backfill
from artha.data.ingest.bhavcopy import bhavcopy_relpath, download_bhavcopy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=date.fromisoformat)
    parser.add_argument("end", type=date.fromisoformat)
    args = parser.parse_args()

    result, _ = run_backfill(
        "bhavcopy",
        calendar_days(args.start, args.end),
        bhavcopy_relpath,
        download_bhavcopy,
        load_settings(),
    )
    if not result.ok:
        print("FAILURES PRESENT - rerun after diagnosing; raw zone is idempotent.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
