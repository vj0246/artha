"""Weekly paper review (Track B B1): live path vs research path.

Usage:
    uv run --no-sync python scripts/run_weekly_review.py

Replays the research pipeline (same signal, constructor, costs) over the
paper log's date window and compares the two equity paths. Divergence
beyond tolerance is the B1 red flag: it means production and research have
drifted apart - the whole point of the parity discipline. Also summarizes
reconciliation and rejection history.
"""

import json
import sys
from datetime import date

import polars as pl

from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.live.safety import alert
from artha.marketspec.nse import nse_spec
from artha.portfolio.construct import ConstraintReport, production_constructor

DIVERGENCE_TOL_WEEKLY = 0.0025  # 25 bps/week unattributed = investigate


def research_premarks(daily: pl.DataFrame, lo: date, hi: date, capital: float) -> pl.DataFrame:
    """Research equity marked exactly the way the live log marks its book.

    A live row for session t is cash + positions at t's close, taken BEFORE
    t's orders: it includes t's return and excludes the costs of t's trades,
    which land in the next row. The backtester's net_return[t] already has
    t's costs deducted, so the comparable research mark is
    E[t-1] * (1 + gross_return[t]), with E the post-cost equity.

    ``daily`` must come from a replay whose book cold-starts at the first
    live signal (``run_backtest(trade_from=...)``), so the research book is
    empty before ``lo`` exactly as the live one was. Earlier versions set
    the live book against a replay invested for two years: week one of a
    restart then charged the live book 0.73pp for a day it held only cash,
    plus the exposure ramp-in it had not yet made (found 2026-09-12)."""
    window = daily.filter(pl.col("trade_date").is_between(lo, hi)).sort("trade_date")
    post_cost = (1.0 + pl.col("net_return")).cum_prod().shift(1, fill_value=1.0)
    return window.select(
        "trade_date",
        (post_cost * (1.0 + pl.col("gross_return")) * capital).alias("research_equity"),
    )


def main() -> int:
    settings = load_settings()
    log_path = settings.reports_dir / "paper" / "paper_log.jsonl"
    if not log_path.exists():
        print("no paper log yet")
        return 0
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    live = pl.DataFrame(
        [
            {"trade_date": date.fromisoformat(r["trade_date"]), "equity": r["equity"]}
            for r in rows
            if not r.get("dry_run")
        ]
    )
    recon_breaks = sum(1 for r in rows if not r.get("reconcile_ok", True))
    rejections = sum(int(r.get("orders_rejected", 0)) for r in rows)

    # ops hygiene (Track G): a stalled clock must not survive a week unnoticed
    import subprocess as _sp

    hb = _sp.run(
        [sys.executable, "scripts/run_heartbeat.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if hb.returncode != 0:
        alert("weekly review: heartbeat reports operational problems (see health.json)")

    if live.is_empty() or live.height < 2:
        print(
            f"log rows: {len(rows)} (live {live.height}); "
            f"recon breaks {recon_breaks}, rejects {rejections} - too early for divergence"
        )
        return 0
    live = live.unique(subset=["trade_date"], keep="last").sort("trade_date")
    lo = live["trade_date"].min()
    hi = live["trade_date"].max()

    # research replay: DATA warms up ~2y before the live window (the min-var
    # risk model needs >=63 obs per name, the cold-start vol 63 sessions),
    # but the BOOK cold-starts at the first live signal, entered from cash on
    # the same day the live book was (ADR 0015). A replay whose book had been
    # invested for two years measured the live ramp-in, not the live
    # implementation.
    warmup_start = date(lo.year - 2, lo.month, 1)
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= warmup_start)
    cal = TradingCalendar.from_frame(px)
    master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
    sector_map = {
        r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
    }
    capital = float(rows[0].get("equity", 2_500_000.0))
    constructor = production_constructor(capital, sector_map)
    first = next(r for r in rows if not r.get("dry_run"))
    first_signal = (
        date.fromisoformat(first["signal_date"])
        if "signal_date" in first
        else cal.prev_trading_day(lo)
    )
    res = run_backtest(
        px,
        momentum_12_1(panel).filter(pl.col("trade_date") >= warmup_start),
        nse_spec(cal, dp_order_value=capital / constructor.top_n),
        capital=capital,
        constructor=constructor,
        report=ConstraintReport(),
        trade_from=first_signal,
    )
    research = research_premarks(res.daily, lo, hi, capital)
    joined = live.join(research, on="trade_date", how="inner").with_columns(
        (pl.col("equity") / pl.col("research_equity") - 1).alias("divergence")
    )
    last_div = float(joined["divergence"][-1]) if joined.height else 0.0
    # weeks of EXPOSURE, from the calendar — not from the number of logged
    # rows. Missed sessions shrink the row count while the book stays
    # invested, and dividing by rows inflated divergence/week (found
    # 2026-09-07: 16 rows over a 33-session window read as 3.2 weeks).
    # Returns are earned AFTER the anchor session, so lo itself is excluded.
    weeks = max((len(cal.sessions(lo, hi)) - 1) / 5.0, 1.0)
    weekly_div = abs(last_div) / weeks

    summary = {
        "window": f"{lo} -> {hi}",
        "live_days": live.height,
        "sessions_in_window": len(cal.sessions(lo, hi)),
        "recon_breaks": recon_breaks,
        "pretrade_rejections": rejections,
        "cumulative_divergence": round(last_div, 6),
        "divergence_per_week": round(weekly_div, 6),
        "within_tolerance": bool(weekly_div <= DIVERGENCE_TOL_WEEKLY),
    }
    print(json.dumps(summary, indent=2))
    (settings.reports_dir / "paper" / "weekly_review.json").write_text(
        json.dumps(summary, indent=2)
    )
    if not summary["within_tolerance"] or recon_breaks:
        alert(f"weekly review FLAG: {summary}")
        return 1
    alert(f"weekly review clean: {summary['window']}, div/wk {weekly_div:.4%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
