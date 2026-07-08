"""Backfill daily all-index close files (ind_close_all) into the raw zone.

Usage:
    uv run python scripts/backfill_indexclose.py 2012-07-02 2026-07-08

Files exist from roughly July 2012; earlier dates 404. Idempotent, polite,
same semantics as backfill_bhavcopy.py.
"""

import argparse
import sys
from datetime import date

from artha.config import load_settings
from artha.data.backfill import calendar_days, run_backfill
from artha.data.ingest.indices import (
    INDEX_CLOSE_START,
    download_index_close,
    index_close_relpath,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=date.fromisoformat)
    parser.add_argument("end", type=date.fromisoformat)
    args = parser.parse_args()

    start = max(args.start, INDEX_CLOSE_START)
    result, _ = run_backfill(
        "indexclose",
        calendar_days(start, args.end),
        index_close_relpath,
        download_index_close,
        load_settings(),
    )
    if not result.ok:
        print("FAILURES PRESENT - rerun after diagnosing; raw zone is idempotent.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
