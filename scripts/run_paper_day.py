"""Daily paper-trading runbook (Track B P8; plan v1 section 13.2 scheduler).

Usage (once per trading day, after refreshing curated data):
    uv run --no-sync python scripts/run_paper_day.py [--dry-run] [--capital 2500000]

Cycle: kill-switch check -> load latest curated closes as quotes -> weekly
signal (momentum 12-1 through the P5 constructor; trades only on the
weekly grid, holds otherwise) -> plan orders -> pre-trade checks -> submit
to the paper broker (idempotent) -> reconcile -> append the daily log that
the 6-week clean-paper gate is judged on.

Two dates, never one (ADR 0014). The book is scored on ``signal_date``
(the previous session) and filled at ``today``'s close, reproducing the
backtester's ``exec_lag=1`` and the feature registry's contract that a
value knowable at t's close is tradeable no earlier than t+1. Everything
read for the DECISION is dated signal_date; only prices and fills are
dated today. Mixing the two is what makes a live log flatter itself.

The 6-week gate clock starts at the first logged day and requires zero
reconciliation breaks throughout.
"""

import argparse
import contextlib
import json
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import polars as pl

from artha.backtest.vectorized import ADV_WINDOW
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.live.adapters.paper import PaperBroker
from artha.live.oms import Oms, plan_orders
from artha.live.safety import KillSwitch, alert, drawdown_action, reconcile
from artha.marketspec.nse import NSECostModel
from artha.portfolio.construct import ConstraintReport, production_constructor
from artha.portfolio.riskmodel import risk_inputs


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


def adv_median(universe: pl.DataFrame, asof: date) -> dict[str, float]:
    """21-day median traded value per name as of ``asof`` — the SAME
    quantity ``vectorized.py`` feeds the participation cap and the impact
    model. The runbook previously passed a single session's raw traded
    value, so the live cap and live costs were driven by a noisier input
    than anything that was ever validated (found 2026-09-07)."""
    window_start = date.fromordinal(asof.toordinal() - 2 * ADV_WINDOW - 30)
    rows = (
        universe.filter(pl.col("trade_date").is_between(window_start, asof))
        .sort("canon_symbol", "trade_date")
        .with_columns(
            pl.col("traded_value")
            .rolling_median(window_size=ADV_WINDOW, min_samples=1)
            .over("canon_symbol")
            .alias("adv_value")
        )
        .filter(pl.col("trade_date") == asof)
    )
    return dict(zip(rows["canon_symbol"], rows["adv_value"], strict=True))


def read_live_log(log_path: Path) -> list[dict[str, Any]]:
    """The non-dry rows of the daily log, oldest first. One read serves the
    rerun guard, the rebalance grid, the drawdown peak and the vol target."""
    if not log_path.exists():
        return []
    rows = []
    with contextlib.suppress(json.JSONDecodeError):
        rows = [
            json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line
        ]
    return [r for r in rows if not r.get("dry_run")]


def trailing_book_vol(rows: list[dict[str, Any]]) -> float | None:
    """Annualized trailing vol of the paper book's FULLY-INVESTED returns,
    from the daily log (max of 21d and 63d windows, same convention as the
    backtester). None until 22 sessions exist."""
    eq = [(r["equity"], r["cash"]) for r in rows]
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
    today = cal.last  # latest session in the curated data — the FILL date
    # Execution lag, matching the backtester's exec_lag=1 and the feature
    # registry's contract ("knowable at t's close, tradeable no earlier than
    # t+1"). The live path used to score AND fill on `today`, buying at the
    # very close that produced the signal — one free day of momentum the
    # research path never gets, in the log that is supposed to be evidence
    # FOR the research path (found 2026-09-07).
    signal_date = cal.prev_trading_day(today)

    log_path = live_dir / "paper_log.jsonl"
    prior_rows = read_live_log(log_path)

    # rerun guard: orders are idempotent, but the session log must hold
    # exactly one non-dry row per trade date (the B1 gate counts sessions)
    if not args.dry_run and any(r["trade_date"] == str(today) for r in prior_rows):
        print(f"session {today} already logged; nothing to do")
        return 0
    latest = universe.filter(pl.col("trade_date") == today)
    quotes = dict(zip(latest["canon_symbol"], latest["adj_close"], strict=True))
    adv = adv_median(universe, signal_date)

    broker = PaperBroker(
        live_dir / "paper_state.json",
        quotes,
        NSECostModel(dp_order_value=args.capital / 25),
        starting_cash=args.capital,
        adv=adv,
    )

    closes = dict(quotes)  # curated closes kept as slippage reference
    quote_source = kite_ltp_override(quotes, sorted(broker.positions()))
    # the weekly grid runs on SIGNAL dates; each one fills a session later
    last_signal = next(
        (
            date.fromisoformat(r.get("signal_date", r["trade_date"]))
            for r in reversed(prior_rows)
            if r.get("rebalance", True)
        ),
        None,
    )
    is_rebalance_day = cal.is_live_rebalance_day(signal_date, last_signal)
    equity = broker.cash() + sum(
        qty * quotes.get(sym, 0.0) for sym, qty in broker.positions().items()
    )

    # drawdown de-risk, enforced not just reported (B3; plan section 11)
    peak = max([equity] + [r["equity"] for r in prior_rows])
    gross_scalar, dd_freeze = drawdown_action(peak, equity)
    if dd_freeze:
        kill.freeze(f"drawdown breach: equity {equity:.0f} vs peak {peak:.0f}")
        return 1
    if gross_scalar < 1.0:
        alert(f"drawdown de-risk active: gross halved (equity {equity:.0f}, peak {peak:.0f})")

    report = None
    scheme_used = "hold"
    if is_rebalance_day:
        master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
        sector_map = {
            r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
        }
        # scored on the SIGNAL date's close, filled at today's — anything
        # read here must be dated signal_date, or the lag is only cosmetic
        signal = momentum_12_1(panel).filter(pl.col("trade_date") == signal_date)
        eligible = universe.filter(pl.col("trade_date") == signal_date)
        scored = (
            signal.join(
                eligible.select("canon_symbol", "in_universe"), on="canon_symbol", how="inner"
            )
            .filter(pl.col("in_universe"))
            .sort("score", descending=True)
            .head(25)
        )
        constructor = production_constructor(args.capital, sector_map)
        creport = ConstraintReport()
        prior = {
            sym: qty * quotes.get(sym, 0.0) / equity for sym, qty in broker.positions().items()
        }
        if quote_source == "kite_ltp":
            kite_ltp_override(quotes, sorted(set(scored["canon_symbol"])))
        vols_in, cov_in = risk_inputs(universe, list(scored["canon_symbol"]), signal_date)
        n_picks = scored.height
        if cov_in is None:
            scheme_used = "equal_fallback"
            alert("risk model unavailable: book falls back to equal weight today")
        elif len(cov_in[0]) < n_picks:
            scheme_used = f"minvar_partial_{len(cov_in[0])}of{n_picks}"
        else:
            scheme_used = constructor.scheme
        targets = constructor.build(
            [(s, adv.get(s, 0.0)) for s in scored["canon_symbol"]],
            prior,
            trailing_book_vol(prior_rows),
            creport,
            adv_map=adv,
            vols=vols_in,
            cov=cov_in,
        )
        if creport.violations:
            kill.freeze(f"constraint violations: {creport.violations[:3]}")
            return 1
        if gross_scalar < 1.0:
            targets = {s: w * gross_scalar for s, w in targets.items()}
        orders = plan_orders(targets, broker.positions(), quotes, equity)
        # reference = the curated closes, NEVER the live quote dict the broker
        # holds: passing `quotes` made reference and quote the same object, so
        # the price-band check compared a number against itself and could never
        # fire (found 2026-09-07; it is the only guard against a bad Kite tick).
        oms = Oms(broker, reference_prices=closes, dry_run=args.dry_run)
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
        "trade_date": str(today),  # the FILL session
        "signal_date": str(signal_date),  # the session the book was scored on
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
        "scheme_used": scheme_used,
    }
    live_dir.mkdir(parents=True, exist_ok=True)
    with (live_dir / "paper_log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_row) + "\n")
    print(json.dumps(log_row, indent=2))

    ok = cast(bool, recon.ok) and (report is None or report.ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
