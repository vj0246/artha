"""Backfill declared corporate actions (NSE CA API) as monthly JSON files.

Usage:
    uv run python scripts/backfill_ca.py [--start 2011-01] [--end 2026-06]

Months are keyed by ex-date. The current month is never fetched: the raw zone
is immutable and a partial month must not be frozen. Idempotent and polite,
same semantics as the other backfill scripts.
"""

import argparse
import sys
from datetime import date, datetime

from artha.config import load_settings
from artha.data.backfill import last_complete_month, month_range, run_backfill
from artha.data.ingest.ca_api import CA_API_START, ca_month_relpath, download_ca_month
from artha.data.ingest.nse_http import nse_api_client


def month_arg(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=month_arg, default=CA_API_START)
    parser.add_argument("--end", type=month_arg, default=None)
    args = parser.parse_args()

    last_complete = last_complete_month(date.today())
    end = min(args.end, last_complete) if args.end else last_complete

    result, _ = run_backfill(
        "ca_api",
        month_range(args.start, end),
        ca_month_relpath,
        download_ca_month,
        load_settings(),
        client_factory=nse_api_client,
    )
    if not result.ok:
        print("FAILURES PRESENT — rerun after diagnosing; raw zone is idempotent.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
