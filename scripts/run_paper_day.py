"""Daily paper-trading runbook (Track B P8; plan v1 section 13.2 scheduler).

Usage (once per trading day, after refreshing curated data):
    uv run --no-sync python scripts/run_paper_day.py [--dry-run] [--capital 2500000]

Cycle: kill-switch check -> load latest curated closes as quotes -> weekly
signal (momentum 12-1 through the P5 constructor; trades only on the
weekly grid, holds otherwise) -> plan orders -> pre-trade checks -> submit
to the paper broker (idempotent) -> reconcile -> append the daily log that
the 6-week clean-paper gate is judged on.

The 6-week gate clock starts at the first logged day and requires zero
reconciliation breaks throughout.
"""

import argparse
import contextlib
import json
import os
import sys
from datetime import UTC, datetime
from typing import cast

import polars as pl

from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.live.adapters.paper import PaperBroker
from artha.live.oms import Oms, plan_orders
from artha.live.safety import KillSwitch, alert, drawdown_action, reconcile
from artha.marketspec.nse import NSECostModel
from artha.portfolio.construct import ConstraintReport, Constructor


def kite_ltp_override(quotes: dict[str, float], symbols: list[str]) -> str:
    """Overlay Kite last-traded prices onto curated closes, in place.

    Key-gated on KITE_API_KEY/KITE_ACCESS_TOKEN; any failure leaves the
    curated closes untouched (B2: real intraday prices make realized
    slippage measurable, but the runbook must never depend on them)."""
    if not (os.environ.get("KITE_API_KEY") and os.environ.get("KITE_ACCESS_TOKEN")):
        return "curated_close"
    try:
        from artha.live.adapters.zerodha import KiteAdapter

        quotes.update(KiteAdapter().ltp_many(symbols))
        return "kite_ltp"
    except Exception as exc:
        alert(f"kite ltp unavailable, using curated closes: {exc}")
        return "curated_close"


def trailing_book_vol(log_path: object) -> float | None:
    """Annualized trailing vol of the paper book's FULLY-INVESTED returns,
    from the daily log (max of 21d and 63d windows, same convention as the
    backtester). None until 22 sessions exist."""
    from pathlib import Path

    path = Path(str(log_path))
    if not path.exists():
        return None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    eq = [(r["equity"], r["cash"]) for r in rows if not r.get("dry_run")]
    if len(eq) < 22:
        return None
    from itertools import pairwise

    book: list[float] = []
    for (e0, _), (e1, c1) in pairwise(eq):
        exposure = (e1 - c1) / e1 if e1 > 0 else 0.0
        if e0 > 0 and exposure > 0.05:
            book.append((e1 / e0 - 1) / exposure)

    def _vol(xs: list[float]) -> float:
        n = len(xs)
        m = sum(xs) / n
        return (sum((x - m) ** 2 for x in xs) / (n - 1) * 252) ** 0.5

    if len(book) < 21:
        return None
    vol = _vol(book[-21:])
    if len(book) >= 63:
        vol = max(vol, _vol(book[-63:]))
    return vol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--capital", type=float, default=2_500_000.0)
    args = parser.parse_args()

    settings = load_settings()
    live_dir = settings.reports_dir / "paper"
    kill = KillSwitch(live_dir / "FREEZE")
    if kill.frozen:
        alert("runbook aborted: kill switch is frozen")
        return 1

    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    cal = TradingCalendar.from_frame(universe)
    today = cal.last  # latest session in the curated data
    latest = universe.filter(pl.col("trade_date") == today)
    quotes = dict(zip(latest["canon_symbol"], latest["adj_close"], strict=True))
    adv = dict(zip(latest["canon_symbol"], latest["traded_value"], strict=True))

    broker = PaperBroker(
        live_dir / "paper_state.json",
        quotes,
        NSECostModel(dp_order_value=args.capital / 25),
        starting_cash=args.capital,
        adv=adv,
    )

    closes = dict(quotes)  # curated closes kept as slippage reference
    quote_source = kite_ltp_override(quotes, sorted(broker.positions()))
    is_rebalance_day = today in set(cal.week_last_days())
    equity = broker.cash() + sum(
        qty * quotes.get(sym, 0.0) for sym, qty in broker.positions().items()
    )

    # drawdown de-risk, enforced not just reported (B3; plan section 11)
    log_path = live_dir / "paper_log.jsonl"
    peak = equity
    if log_path.exists():
        with contextlib.suppress(json.JSONDecodeError):
            rows = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            peak = max([equity] + [r["equity"] for r in rows if not r.get("dry_run")])
    gross_scalar, dd_freeze = drawdown_action(peak, equity)
    if dd_freeze:
        kill.freeze(f"drawdown breach: equity {equity:.0f} vs peak {peak:.0f}")
        return 1
    if gross_scalar < 1.0:
        alert(f"drawdown de-risk active: gross halved (equity {equity:.0f}, peak {peak:.0f})")

    report = None
    if is_rebalance_day:
        master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
        sector_map = {
            r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
        }
        signal = momentum_12_1(panel).filter(pl.col("trade_date") == today)
        scored = (
            signal.join(
                latest.select("canon_symbol", "in_universe"), on="canon_symbol", how="inner"
            )
            .filter(pl.col("in_universe"))
            .sort("score", descending=True)
            .head(25)
        )
        constructor = Constructor(capital=args.capital, sector_map=sector_map)
        creport = ConstraintReport()
        prior = {
            sym: qty * quotes.get(sym, 0.0) / equity for sym, qty in broker.positions().items()
        }
        if quote_source == "kite_ltp":
            kite_ltp_override(quotes, sorted(set(scored["canon_symbol"])))
        targets = constructor.build(
            [(s, adv.get(s, 0.0)) for s in scored["canon_symbol"]],
            prior,
            trailing_book_vol(live_dir / "paper_log.jsonl"),
            creport,
            adv_map=adv,
        )
        if creport.violations:
            kill.freeze(f"constraint violations: {creport.violations[:3]}")
            return 1
        if gross_scalar < 1.0:
            targets = {s: w * gross_scalar for s, w in targets.items()}
        orders = plan_orders(targets, broker.positions(), quotes, equity)
        oms = Oms(broker, reference_prices=quotes, dry_run=args.dry_run)
        report = oms.execute(today, orders)
        for order, reason in report.rejected_pretrade:
            alert(f"pretrade reject {order.symbol} {order.side} {order.quantity}: {reason}")
        live_dir.mkdir(parents=True, exist_ok=True)
        with (live_dir / "orders_log.jsonl").open("a", encoding="utf-8") as f:
            for order, result in report.submitted:
                f.write(
                    json.dumps(
                        {
                            "trade_date": str(today),
                            "broker_order_id": result.broker_order_id,
                            "symbol": order.symbol,
                            "side": order.side,
                            "quantity": order.quantity,
                            "ref_close": closes.get(order.symbol),
                            "fill_price": result.fill_price,
                            "adv_value": adv.get(order.symbol),
                            "status": result.status,
                            "quote_source": quote_source,
                        }
                    )
                    + "\n"
                )

    # reconcile the paper book against itself (structure check; with the
    # Kite adapter this compares OMS expectations vs the real account)
    recon = reconcile(broker.positions(), broker.cash(), broker)
    if not recon.ok:
        kill.freeze(f"reconciliation mismatch: {recon.mismatches[:3]}")
        return 1

    log_row = {
        "run_at": datetime.now(UTC).isoformat(),
        "trade_date": str(today),
        "rebalance": is_rebalance_day,
        "equity": equity,
        "cash": broker.cash(),
        "n_positions": len(broker.positions()),
        "orders_submitted": len(report.submitted) if report else 0,
        "orders_rejected": len(report.rejected_pretrade) if report else 0,
        "reconcile_ok": recon.ok,
        "dry_run": args.dry_run,
        "quote_source": quote_source,
        "gross_scalar": gross_scalar,
    }
    live_dir.mkdir(parents=True, exist_ok=True)
    with (live_dir / "paper_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_row) + "\n")
    print(json.dumps(log_row, indent=2))

    ok = cast(bool, recon.ok) and (report is None or report.ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
