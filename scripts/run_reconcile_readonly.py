"""B2 read-only reconciliation: paper book vs the real Kite account.

Usage (daily, for at least a week before any live order is ever sent):
    uv run --no-sync python scripts/run_reconcile_readonly.py

Never places orders. Compares the paper book's positions and cash
against the live account's holdings and available cash, appends the
result to reports/paper/reconcile_readonly.jsonl, and alerts on any
mismatch. Gate B2: one week of these rows with zero mismatches.

Requires KITE_API_KEY/KITE_ACCESS_TOKEN. Note: until real capital is
funded and mirrored, position mismatches are EXPECTED (paper holds
names the empty account does not); the week that counts starts when the
account mirrors the paper book.
"""

import json
import sys
from datetime import UTC, datetime

from artha.config import load_settings
from artha.live.adapters.paper import PaperBroker
from artha.live.safety import alert, reconcile
from artha.marketspec.nse import NSECostModel


def main() -> int:
    settings = load_settings()
    live_dir = settings.reports_dir / "paper"
    try:
        from artha.live.adapters.zerodha import KiteAdapter

        kite = KiteAdapter()
    except RuntimeError as exc:
        print(f"not runnable yet: {exc}", file=sys.stderr)
        return 1

    paper = PaperBroker(live_dir / "paper_state.json", {}, NSECostModel(), starting_cash=0.0)
    result = reconcile(paper.positions(), paper.cash(), kite)
    row = {
        "run_at": datetime.now(UTC).isoformat(),
        "ok": result.ok,
        "mismatches": [
            {"kind": m.kind, "symbol": m.symbol, "expected": m.expected, "actual": m.actual}
            for m in result.mismatches
        ],
    }
    live_dir.mkdir(parents=True, exist_ok=True)
    with (live_dir / "reconcile_readonly.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2))
    if not result.ok:
        alert(f"read-only reconcile: {len(result.mismatches)} mismatches")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
