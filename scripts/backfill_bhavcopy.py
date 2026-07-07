"""Backfill the NSE bhavcopy raw zone over a date range.

Usage:
    uv run python scripts/backfill_bhavcopy.py 2010-01-01 2026-07-08

Idempotent: already-stored days are skipped, so the script can be re-run
after any interruption. Weekends are not attempted. 404s are expected on
holidays and recorded for later reconciliation against the trading calendar
(P1c); any other failure is recorded and makes the exit code non-zero.
Politeness: one request per ~0.6s against nsearchives.nseindia.com.
"""

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime, timedelta

from artha.config import load_settings
from artha.data.ingest.bhavcopy import bhavcopy_relpath, download_bhavcopy
from artha.data.ingest.nse_http import NseDownloadError, NseNotFoundError, nse_client
from artha.data.store import RawStore

POLITE_DELAY_S = 0.6
PROGRESS_EVERY = 100


def weekdays(start: date, end: date) -> list[date]:
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", type=date.fromisoformat)
    parser.add_argument("end", type=date.fromisoformat)
    args = parser.parse_args()

    settings = load_settings()
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    store = RawStore(settings.raw_dir)

    todo = weekdays(args.start, args.end)
    downloaded: list[str] = []
    skipped = 0
    not_found: list[str] = []
    failed: list[dict[str, str]] = []

    print(f"backfill {args.start} -> {args.end}: {len(todo)} weekdays, raw zone {settings.raw_dir}")
    with nse_client() as client:
        for i, d in enumerate(todo, 1):
            if store.exists(bhavcopy_relpath(d)):
                skipped += 1
            else:
                try:
                    download_bhavcopy(d, client=client, store=store)
                    downloaded.append(d.isoformat())
                except NseNotFoundError:
                    not_found.append(d.isoformat())
                except NseDownloadError as exc:
                    failed.append({"date": d.isoformat(), "error": str(exc)})
                    print(f"  FAIL {d}: {exc}", flush=True)
                time.sleep(POLITE_DELAY_S)
            if i % PROGRESS_EVERY == 0:
                print(
                    f"  [{i}/{len(todo)}] downloaded={len(downloaded)} skipped={skipped} "
                    f"404={len(not_found)} failed={len(failed)}",
                    flush=True,
                )

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "downloaded": len(downloaded),
        "skipped_existing": skipped,
        "not_found_dates": not_found,
        "failed": failed,
    }
    report_path = (
        settings.reports_dir / f"bhavcopy_backfill_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(
        f"done: downloaded={len(downloaded)} skipped={skipped} 404={len(not_found)} "
        f"failed={len(failed)}\nreport: {report_path}"
    )
    if failed:
        print("FAILURES PRESENT — rerun after diagnosing; raw zone is idempotent.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
