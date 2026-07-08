"""Generic polite backfill loop over per-day NSE archive files.

Idempotent: already-stored days are skipped. 404s are expected on holidays
and recorded for reconciliation against the trading calendar; any other
failure is recorded and reported via a non-zero exit path by the caller.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from artha.config import Settings
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


@dataclass
class BackfillResult:
    downloaded: list[str] = field(default_factory=list)
    skipped: int = 0
    not_found: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def run_backfill(
    name: str,
    days: list[date],
    relpath_fn: Callable[[date], str],
    download_fn: Callable[..., Path],
    settings: Settings,
) -> tuple[BackfillResult, Path]:
    """Download ``days`` via ``download_fn(d, client=..., store=...)``; write a JSON report.

    Returns the result and the report path.
    """
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    store = RawStore(settings.raw_dir)
    result = BackfillResult()

    print(f"{name} backfill: {len(days)} days, raw zone {settings.raw_dir}", flush=True)
    with nse_client() as client:
        for i, d in enumerate(days, 1):
            if store.exists(relpath_fn(d)):
                result.skipped += 1
            else:
                _download_one(d, download_fn, client, store, result)
                time.sleep(POLITE_DELAY_S)
            if i % PROGRESS_EVERY == 0:
                print(
                    f"  [{i}/{len(days)}] downloaded={len(result.downloaded)} "
                    f"skipped={result.skipped} 404={len(result.not_found)} "
                    f"failed={len(result.failed)}",
                    flush=True,
                )

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "days": len(days),
        "downloaded": len(result.downloaded),
        "skipped_existing": result.skipped,
        "not_found_dates": result.not_found,
        "failed": result.failed,
    }
    report_path = settings.reports_dir / f"{name}_backfill_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"done: downloaded={len(result.downloaded)} skipped={result.skipped} "
        f"404={len(result.not_found)} failed={len(result.failed)}\nreport: {report_path}",
        flush=True,
    )
    return result, report_path


def _download_one(
    d: date,
    download_fn: Callable[..., Path],
    client: httpx.Client,
    store: RawStore,
    result: BackfillResult,
) -> None:
    try:
        download_fn(d, client=client, store=store)
        result.downloaded.append(d.isoformat())
    except NseNotFoundError:
        result.not_found.append(d.isoformat())
    except NseDownloadError as exc:
        result.failed.append({"date": d.isoformat(), "error": str(exc)})
        print(f"  FAIL {d}: {exc}", flush=True)
