"""C1: White Reality Check + Hansen SPA over the strategy family.

Usage (after run_construction_v2.py):
    uv run --no-sync python scripts/run_spa.py

Family = the construction-v2 configurations plus the naive P2 baselines
(momentum, low-vol), tested jointly against the synthetic NIFTY 500 TRI.
The null: NO member of the family beats the benchmark — the sharp
data-snooping question the deflated Sharpe approximates. Stationary
bootstrap (21d mean block) preserves vol clustering.
"""

import json
import sys
from datetime import UTC, date, datetime

import polars as pl

from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import low_vol_63d, momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.models.spa import spa_test

START = date(2012, 8, 1)
N_BOOT = 2000


def main() -> int:
    settings = load_settings()
    cv_daily = settings.reports_dir / "construction_v2_daily.parquet"
    if not cv_daily.exists():
        print("run scripts/run_construction_v2.py first", file=sys.stderr)
        return 1
    daily = pl.read_parquet(cv_daily)

    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= START)
    cal = TradingCalendar.from_frame(px)
    spec = nse_spec(cal)  # charges only for the naive baselines (as in P2)
    frames = [daily]
    for name, signal_fn in [("naive_momentum", momentum_12_1), ("naive_low_vol", low_vol_63d)]:
        res = run_backtest(px, signal_fn(panel).filter(pl.col("trade_date") >= START), spec)
        frames.append(
            res.daily.select("trade_date", "net_return").with_columns(pl.lit(name).alias("config"))
        )
    daily = pl.concat(frames)

    bench = (
        pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty500.parquet")
        .filter(pl.col("trade_date") >= START)
        .select("trade_date", "tr_return")
    )
    wide = (
        daily.pivot(on="config", index="trade_date", values="net_return")
        .join(bench, on="trade_date", how="inner")
        .drop_nulls()
        .sort("trade_date")
    )
    configs = [c for c in wide.columns if c not in ("trade_date", "tr_return")]
    d = wide.select(configs).to_numpy() - wide.select("tr_return").to_numpy()
    res = spa_test(d, n_boot=N_BOOT)

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "family": configs,
        "n_obs": res.n_obs,
        "n_boot": res.n_boot,
        "benchmark": "synthetic NIFTY 500 TRI",
        "rc_p_value": res.rc_p_value,
        "spa_p_value": res.spa_p_value,
        "best_strategy": configs[res.best_strategy],
        "best_mean_excess_ann": res.best_mean_ann,
        "reading": (
            "p < 0.05 rejects 'nothing in the family beats the benchmark' "
            "after accounting for having tried the whole family; p above "
            "means the excess over the index is not distinguishable from "
            "data snooping at this sample size"
        ),
    }
    out = settings.reports_dir / f"spa_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
