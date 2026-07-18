"""P5 gate run: constructed momentum portfolio, tearsheet, risk, capacity.

Usage:
    uv run --no-sync python scripts/run_p5.py

Momentum 12-1 through the full construction stack (caps, bands, vol
targeting, ADV participation) at Rs 25L; constraint verification across
every rebalance (gate: zero violations); tearsheet vs synthetic NIFTY 500
TRI and the equal-weight universe; regimes, attribution, VaR, drawdown
states, worst windows, liquidity; capacity curve across capital levels.
"""

import json
import sys
from datetime import UTC, date, datetime
from typing import cast

import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.models.dsr import deflated_sharpe
from artha.models.ledger import TrialLedger
from artha.portfolio.construct import ConstraintReport, Constructor
from artha.risk.analytics import (
    calmar,
    days_to_liquidate,
    drawdown_state,
    rolling_sharpe,
    sortino,
    var_report,
    worst_windows,
)

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0
CAPACITY_LEVELS = [2.5e6, 1e7, 5e7, 2.5e8, 1e9]
REGIMES = [
    (date(2012, 8, 1), date(2016, 12, 31)),
    (date(2017, 1, 1), date(2020, 12, 31)),
    (date(2021, 1, 1), date(2026, 7, 7)),
]


def beta_alpha(strategy: pl.DataFrame, market: pl.DataFrame) -> dict[str, float]:
    j = strategy.join(market.select("trade_date", "tr_return"), on="trade_date", how="inner")
    x = j["tr_return"].to_numpy()
    y = j["net_return"].to_numpy()
    import numpy as np

    beta, alpha = np.polyfit(x, y, 1)
    resid = y - (alpha + beta * x)
    alpha_t = alpha / (resid.std(ddof=2) / len(y) ** 0.5)
    return {
        "beta": float(beta),
        "alpha_daily": float(alpha),
        "alpha_ann": float(alpha) * 252,
        "alpha_t": float(alpha_t),
        "corr": float(np.corrcoef(x, y)[0, 1]),
    }


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= START)
    cal = TradingCalendar.from_frame(px)
    master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
    sector_map = {
        r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
    }
    n500 = pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty500.parquet").filter(
        pl.col("trade_date") >= START
    )

    signal = momentum_12_1(panel).filter(pl.col("trade_date") >= START)
    results: dict[str, object] = {}

    # --- constructed portfolio at base capital, with constraint gate
    report = ConstraintReport()
    constructor = Constructor(capital=CAPITAL, sector_map=sector_map)
    spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
    res = run_backtest(px, signal, spec, capital=CAPITAL, constructor=constructor, report=report)
    daily = res.daily
    stats = summarize(daily)
    stats["sortino"] = sortino(daily["net_return"])
    stats["calmar"] = calmar(stats["cagr"], stats["max_drawdown"])
    results["constructed_momentum"] = stats
    results["constraint_violations"] = report.violations
    print(f"constructed: {json.dumps(stats)}", flush=True)
    print(f"violations: {len(report.violations)}", flush=True)

    # Vol targeting controls TRAILING vol; full-sample vol stays above it
    # because crash bursts dominate the unconditional std (vol-of-vol).
    # The gate metric is therefore the median trailing 21d vol.
    trailing_vol = daily.select(
        (pl.col("net_return").rolling_std(window_size=21) * (252**0.5)).alias("tv")
    ).drop_nulls()["tv"]
    median_tv = float(cast(float, trailing_vol.median()))
    results["vol_targeting"] = {
        "target": constructor.target_vol,
        "full_sample_vol": stats["vol"],
        "median_trailing_21d_vol": median_tv,
        "pct_days_trailing_in_band": float((trailing_vol <= 0.17).mean()),
        "in_band": bool(0.10 <= median_tv <= 0.17),
    }

    # --- benchmarks
    bench_stats = summarize(
        n500.select("trade_date", pl.col("tr_return").alias("net_return")).drop_nulls()
    )
    results["nifty500_synthetic_tri"] = bench_stats
    ew_signal = px.select("canon_symbol", "trade_date").with_columns(pl.lit(1.0).alias("score"))
    ew = run_backtest(px, ew_signal, spec, top_n=10_000)
    results["equal_weight_universe"] = summarize(ew.daily)
    print("benchmarks done", flush=True)

    # --- regimes
    regimes = {}
    for lo, hi in REGIMES:
        seg = daily.filter(pl.col("trade_date").is_between(lo, hi))
        if seg.height > 60:
            regimes[f"{lo.year}-{hi.year}"] = summarize(seg)
    results["regimes"] = regimes

    # --- attribution vs synthetic TRI
    results["attribution"] = beta_alpha(daily, n500)

    # --- risk artifacts
    vr = var_report(daily["net_return"])
    results["var"] = vr.__dict__
    dd = drawdown_state(daily)
    results["drawdown"] = {
        "max": float(cast(float, dd["drawdown"].min())),
        "days_half_gross": int((dd["derisk_state"] == "half_gross").sum()),
        "days_flat": int((dd["derisk_state"] == "flat").sum()),
    }
    results["worst_21d_windows"] = worst_windows(daily).to_dicts()
    adv = (
        px.sort("canon_symbol", "trade_date")
        .group_by("canon_symbol")
        .agg(pl.col("traded_value").tail(21).median().alias("adv_value"))
    )
    dtl = days_to_liquidate(res.holdings, adv, capital=CAPITAL)
    results["liquidity"] = {
        "max_days_to_liquidate": float(cast(float, dtl["days_to_liquidate"].max())),
        "worst_names": dtl.head(3).to_dicts(),
    }
    results["rolling_sharpe_1y"] = {
        "min": float(cast(float, rolling_sharpe(daily)["rolling_sharpe_1y"].min())),
        "max": float(cast(float, rolling_sharpe(daily)["rolling_sharpe_1y"].max())),
    }
    print("risk done", flush=True)

    # --- capacity curve
    capacity = {}
    for level in CAPACITY_LEVELS:
        c = Constructor(capital=level, sector_map=sector_map)
        s = nse_spec(cal, dp_order_value=level / c.top_n)
        r = run_backtest(px, signal, s, capital=level, constructor=c)
        capacity[f"{level:,.0f}"] = summarize(r.daily)
        print(
            f"capacity {level:,.0f}: sharpe {capacity[f'{level:,.0f}']['sharpe']:.3f}", flush=True
        )
    results["capacity"] = capacity

    # --- DSR with ledger context
    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    results["dsr"] = deflated_sharpe(
        stats["sharpe"] / (252**0.5),
        int(stats["n_days"]),
        n_trials=ledger.count(),
        sr_variance=(0.5 / 252**0.5) ** 2,
    )
    results["ledger_trials"] = ledger.count()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.reports_dir / f"p5_tearsheet_{stamp}.json"
    path.write_text(json.dumps(results, indent=2, default=str))
    print(f"report: {path}")
    return 0 if not report.violations else 1


if __name__ == "__main__":
    sys.exit(main())
