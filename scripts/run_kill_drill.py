"""Kill-switch drill on a COPY of the paper book (Track B B3 rehearsal).

Usage:
    uv run --no-sync python scripts/run_kill_drill.py

Copies the current paper state into a scratch drill directory, executes
freeze -> flatten -> verify-zero-positions there, and appends the
evidence row to reports/paper/kill_drills.jsonl. The real paper book is
never touched; the live one-share drill in B3 week one follows this
same sequence against the broker.

--synthetic: no persisted paper state yet (all runs dry so far) — build
a three-name scratch book at today's real prices and drill on that. The
flatten mechanics exercised are identical.
"""

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime

import polars as pl

from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.live.adapters.paper import PaperBroker
from artha.live.safety import KillSwitch
from artha.marketspec.nse import NSECostModel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    live_dir = settings.reports_dir / "paper"
    drill_dir = live_dir / "drill"
    drill_dir.mkdir(parents=True, exist_ok=True)
    drill_state = drill_dir / "paper_state.json"
    drill_state.unlink(missing_ok=True)

    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    cal = TradingCalendar.from_frame(universe)
    latest = universe.filter(pl.col("trade_date") == cal.last)
    quotes = dict(zip(latest["canon_symbol"], latest["adj_close"], strict=True))

    state = live_dir / "paper_state.json"
    if state.exists():
        shutil.copy(state, drill_state)
        broker = PaperBroker(drill_state, quotes, NSECostModel(), starting_cash=0.0)
    elif args.synthetic:
        broker = PaperBroker(drill_state, quotes, NSECostModel(), starting_cash=500_000.0)
        for i, sym in enumerate(sorted(quotes)[:3]):
            broker.place_market_order(f"DRILL{i}", sym, "BUY", max(1, int(50_000 / quotes[sym])))
    else:
        print("no paper state to drill on (use --synthetic)", file=sys.stderr)
        return 1
    positions_before = dict(broker.positions())
    kill = KillSwitch(drill_dir / "FREEZE")
    kill.freeze("drill: deliberate kill-switch rehearsal")
    kill.flatten(broker, cal.last)
    positions_after = dict(broker.positions())

    row = {
        "run_at": datetime.now(UTC).isoformat(),
        "trade_date": str(cal.last),
        "positions_before": len(positions_before),
        "positions_after": len(positions_after),
        "cash_after": broker.cash(),
        "frozen": kill.frozen,
        "pass": kill.frozen and not positions_after,
    }
    with (live_dir / "kill_drills.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2))
    print(f"DRILL {'PASS' if row['pass'] else 'FAIL'} (scratch book only; real state untouched)")
    return 0 if row["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
