"""Weekly realized-vs-modeled slippage report (Track B B3 feedback loop).

Usage:
    uv run --no-sync python scripts/run_slippage_report.py

Reads reports/paper/orders_log.jsonl (written by run_paper_day per
fill): realized slippage = fill price vs same-day curated close, signed
so that paying up on buys and giving up on sells are both positive.
Modeled = the cost model's impact term for the order's size and ADV.
With close-fill paper quotes realized is 0 by construction; the report
becomes meaningful once quote_source=kite_ltp rows appear (B2), and in
B3 it feeds recalibration of IMPACT_A_BPS/IMPACT_B_BPS. Gate B3 tracks:
realized within 2x modeled.
"""

import json
import math
import sys
from datetime import UTC, datetime

from artha.config import load_settings
from artha.marketspec.nse import IMPACT_A_BPS, IMPACT_B_BPS


def main() -> int:
    settings = load_settings()
    log = settings.reports_dir / "paper" / "orders_log.jsonl"
    if not log.exists():
        print("no orders_log.jsonl yet; nothing to report", file=sys.stderr)
        return 1

    # rerun-idempotent: same broker_order_id keeps the last row
    rows = {
        r["broker_order_id"]: r
        for r in map(json.loads, log.read_text(encoding="utf-8").splitlines())
        if r.get("status") == "FILLED" and r.get("fill_price") and r.get("ref_close")
    }
    fills = []
    for r in rows.values():
        sign = 1.0 if r["side"] == "BUY" else -1.0
        realized_bps = sign * (r["fill_price"] / r["ref_close"] - 1) * 10_000
        value = r["quantity"] * r["fill_price"]
        adv = r.get("adv_value") or 0.0
        modeled_bps = (
            IMPACT_A_BPS + IMPACT_B_BPS * math.sqrt(value / adv) if adv > 0 else IMPACT_A_BPS
        )
        fills.append(
            {
                "trade_date": r["trade_date"],
                "symbol": r["symbol"],
                "side": r["side"],
                "realized_bps": realized_bps,
                "modeled_bps": modeled_bps,
                "within_2x": abs(realized_bps) <= 2 * modeled_bps,
                "quote_source": r.get("quote_source", "curated_close"),
            }
        )
    if not fills:
        print("no filled orders with prices yet")
        return 0

    live = [f for f in fills if f["quote_source"] == "kite_ltp"]
    scored = live or fills
    n_within = sum(f["within_2x"] for f in scored)
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "n_fills": len(fills),
        "n_live_quoted": len(live),
        "mean_realized_bps": sum(f["realized_bps"] for f in scored) / len(scored),
        "mean_modeled_bps": sum(f["modeled_bps"] for f in scored) / len(scored),
        "share_within_2x_model": n_within / len(scored),
        "degenerate": not live,  # close-fill paper: realized 0 by construction
        "worst": sorted(scored, key=lambda f: -abs(f["realized_bps"]))[:10],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = settings.reports_dir / f"slippage_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "worst"}, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
