"""The unattended daily cycle (Track B B1): one entrypoint for the scheduler.

Usage:
    uv run --no-sync python scripts/run_daily_cycle.py [--dry-run]

Sequence (each step idempotent; holidays no-op naturally):
1. incremental bhavcopy + index-close backfill (last curated day -> today)
2. monthly CA / announcements / board-meeting top-ups (no-op mid-month)
3. incremental curated rebuild (only years with new raw files re-parse)
4. raw-zone integrity scan
5. paper runbook (signal -> orders -> reconcile -> log)
6. Telegram/console summary

Any step failure aborts the cycle with an alert; the next run is safe to
retry because every stage is idempotent.
"""

import argparse
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.live.safety import alert

REPO = Path(__file__).resolve().parents[1]


def run_step(name: str, cmd: list[str]) -> bool:
    print(f"=== {name}: {' '.join(cmd[3:])}", flush=True)
    # children print polars tables (box-drawing chars): force UTF-8 both ways
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-4:])
    print(tail, flush=True)
    if proc.returncode != 0:
        alert(f"daily cycle FAILED at {name}: {tail[-300:]}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    py = [sys.executable, "-u"]
    today = date.today()

    # incremental start: last session already in the curated zone
    import polars as pl

    panel_path = settings.curated_dir / "panel.parquet"
    if panel_path.exists():
        cal = TradingCalendar.from_frame(
            pl.scan_parquet(panel_path).select("trade_date").unique().collect()
        )
        start = cal.last - timedelta(days=3)  # small overlap; backfills skip existing
    else:
        start = date(2010, 1, 1)

    steps: list[tuple[str, list[str]]] = [
        (
            "bhavcopy backfill",
            [*py, "scripts/backfill_bhavcopy.py", str(start), str(today)],
        ),
        (
            "indexclose backfill",
            [*py, "scripts/backfill_indexclose.py", str(start), str(today)],
        ),
        ("ca backfill", [*py, "scripts/backfill_ca.py"]),
        ("events backfill", [*py, "scripts/backfill_events.py"]),
        ("news collector", [*py, "scripts/collect_news.py"]),  # D4; non-critical
        ("curated rebuild", [*py, "scripts/build_curated.py", "--incremental"]),
        ("integrity scan", [*py, "scripts/scan_raw_integrity.py"]),
        (
            "paper day",
            [*py, "scripts/run_paper_day.py", *(["--dry-run"] if args.dry_run else [])],
        ),
    ]
    non_critical = {"news collector"}  # D4 archive: a feed outage must not stop trading
    for name, cmd in steps:
        if not run_step(name, cmd) and name not in non_critical:
            return 1
    alert(f"daily cycle OK for {today}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
