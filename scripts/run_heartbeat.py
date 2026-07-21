"""Operational heartbeat: catch the failures that make NO noise.

Usage (scheduled nightly at 21:00, two hours after the daily cycle):
    uv run --no-sync python scripts/run_heartbeat.py

Every other alarm in this system fires when something DOES the wrong
thing. This one fires when nothing happens at all — the failure mode
that looks exactly like success:

- the scheduled task was refused, disabled, or deleted;
- the machine was asleep/off at 19:00, or rebooted mid-cycle;
- the cycle ran but the paper day silently no-opped;
- the kill switch froze trading days ago and nobody noticed;
- data stopped arriving (curated panel stale vs the calendar).

Because the B1 clock (30 consecutive clean sessions) is the binding
constraint on every remaining milestone, a silently stalled clock is
the most expensive bug in the project: it costs wall-clock weeks and
is discovered late. This script converts that silence into an alert.

Writes reports/paper/health.json (the dashboard reads it) and exits
non-zero when anything is wrong, so the scheduler records a failure.
"""

import contextlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl

from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.live.safety import alert

STALE_SESSIONS_ALERT = 1  # book may lag the calendar by at most this many
CYCLE_LOG_STALE_HOURS = 30  # cycle.log untouched for longer than this = suspicious
EXPECTED_TASKS = ("artha-daily", "artha-weekly", "artha-monthly", "artha-quarterly")


def _rows(path: Any) -> list[dict[str, Any]]:
    from pathlib import Path

    p = Path(str(path))
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def check_scheduled_tasks() -> dict[str, str]:
    """Windows scheduled tasks that must exist and be enabled."""
    states: dict[str, str] = {}
    for name in EXPECTED_TASKS:
        try:
            out = subprocess.run(
                ["schtasks", "/Query", "/TN", name, "/FO", "LIST"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            states[name] = "unknown (schtasks unavailable)"
            continue
        if out.returncode != 0:
            states[name] = "MISSING"
            continue
        status = "unknown"
        for line in (out.stdout or "").splitlines():
            if line.lower().startswith("status:"):
                status = line.split(":", 1)[1].strip()
                break
        states[name] = status
    return states


def main() -> int:
    settings = load_settings()
    live_dir = settings.reports_dir / "paper"
    problems: list[str] = []

    # --- data freshness: what session SHOULD the book know about?
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    cal = TradingCalendar.from_frame(pit_universe(panel))
    latest_session = cal.last
    sessions = sorted(cal.days)

    # --- book freshness: latest non-dry logged session
    log_rows = _rows(live_dir / "paper_log.jsonl")
    live_rows = [r for r in log_rows if not r.get("dry_run")]
    last_live = date.fromisoformat(live_rows[-1]["trade_date"]) if live_rows else None

    if last_live is None:
        lag = None
        clock_state = "not started (no live session logged yet)"
    else:
        after = [s for s in sessions if s > last_live]
        lag = len(after)
        clock_state = f"{len(live_rows)} live sessions logged"
        if lag > STALE_SESSIONS_ALERT:
            problems.append(
                f"paper book is {lag} sessions behind the calendar "
                f"(last live {last_live}, latest session {latest_session}) — "
                "the daily cycle is not running"
            )

    # --- missed sessions since the clock started (B1 gate counts consecutive)
    missed: list[str] = []
    if live_rows:
        first_live = date.fromisoformat(live_rows[0]["trade_date"])
        logged = {date.fromisoformat(r["trade_date"]) for r in live_rows}
        end = last_live or first_live
        missed = [str(s) for s in sessions if first_live <= s <= end and s not in logged]
        if missed:
            problems.append(f"{len(missed)} missed session(s) inside the B1 window: {missed[:5]}")

    # --- kill switch
    freeze_path = live_dir / "FREEZE"
    frozen = freeze_path.exists()
    freeze_reason = ""
    if frozen:
        with contextlib.suppress(Exception):
            freeze_reason = json.loads(freeze_path.read_text(encoding="utf-8")).get("reason", "")
        problems.append(f"KILL SWITCH ACTIVE — trading halted: {freeze_reason}")

    # --- cycle log freshness
    cycle_log = live_dir / "cycle.log"
    cycle_age_h = None
    if cycle_log.exists():
        age = datetime.now(UTC) - datetime.fromtimestamp(cycle_log.stat().st_mtime, tz=UTC)
        cycle_age_h = round(age / timedelta(hours=1), 1)
        if age > timedelta(hours=CYCLE_LOG_STALE_HOURS):
            problems.append(f"cycle.log untouched for {cycle_age_h}h — scheduler may be dead")
    else:
        problems.append("cycle.log missing — the daily cycle has never written output")

    # --- scheduled tasks present and enabled
    tasks = check_scheduled_tasks()
    for name, status in tasks.items():
        if status == "MISSING" or status.lower() == "disabled":
            problems.append(f"scheduled task {name} is {status}")

    # --- unacknowledged critical alerts
    alerts = _rows(live_dir / "alerts.jsonl")
    criticals = [a for a in alerts if a.get("severity") == "critical"]
    recent_criticals = criticals[-5:]

    health = {
        "run_at": datetime.now(UTC).isoformat(),
        "latest_session": str(latest_session),
        "last_live_session": str(last_live) if last_live else None,
        "sessions_behind": lag,
        "b1_clock": clock_state,
        "b1_progress": f"{len(live_rows)}/30",
        "missed_sessions": missed,
        "frozen": frozen,
        "freeze_reason": freeze_reason,
        "cycle_log_age_hours": cycle_age_h,
        "scheduled_tasks": tasks,
        "alerts_total": len(alerts),
        "criticals_total": len(criticals),
        "recent_criticals": recent_criticals,
        "telegram_configured": bool(
            os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")
        ),
        "problems": problems,
        "healthy": not problems,
    }
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    print(json.dumps(health, indent=2))

    if problems:
        alert("HEARTBEAT: " + " | ".join(problems), severity="critical")
        return 1
    print("heartbeat OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
