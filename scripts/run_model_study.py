"""P3 model comparison study runner: ridge and LightGBM legs.

Usage:
    uv run python scripts/run_model_study.py [--label-horizon 5]

Weekly-grid matrix from the PIT universe, purged expanding walk-forward CV
(3y minimum train, ~quarterly test blocks, 1-week horizon + 4-week embargo
in grid units), rank IC + decile spread + backtester net Sharpe per model,
every run appended to the trial ledger, DSR against the ledger count.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import cast

import polars as pl
from lightgbm import LGBMRegressor
from sklearn.linear_model import Ridge

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.library import build_features
from artha.labels.horizon import forward_return_z
from artha.marketspec.nse import nse_spec
from artha.models.cv import walk_forward_folds
from artha.models.dsr import deflated_sharpe
from artha.models.ledger import Trial, TrialLedger
from artha.models.study import StudyResult, run_study

MODELS = {
    "ridge": (lambda: Ridge(alpha=1.0), {"alpha": 1.0}),
    "lightgbm": (
        lambda: LGBMRegressor(
            n_estimators=400,
            learning_rate=0.05,
            num_leaves=63,
            min_child_samples=100,
            subsample=0.8,
            subsample_freq=1,
            colsample_bytree=0.8,
            n_jobs=-1,
            verbose=-1,
        ),
        {"n_estimators": 400, "learning_rate": 0.05, "num_leaves": 63},
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-horizon", type=int, default=5)
    args = parser.parse_args()

    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    cal = TradingCalendar.from_frame(universe)
    weekly = set(cal.week_last_days())

    features, names = build_features(universe.filter(pl.col("in_universe")))
    labels = forward_return_z(panel, args.label_horizon)
    matrix = (
        features.join(labels, on=["canon_symbol", "trade_date"], how="inner")
        .filter(pl.col("trade_date").is_in(sorted(weekly)))
        .sort("trade_date", "canon_symbol")
    )
    grid = sorted(matrix["trade_date"].unique().to_list())
    print(f"matrix: {matrix.height:,} rows, {len(names)} features, {len(grid)} weeks")

    folds = walk_forward_folds(
        grid, test_days=13, min_train_days=156, horizon_days=1, embargo_days=4
    )
    print(f"folds: {len(folds)} (OOS {folds[0].test_start} -> {folds[-1].test_end})")

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    results: dict[str, object] = {}
    for name, (factory, params) in MODELS.items():
        res: StudyResult = run_study(matrix, names, folds, factory, model_name=name)
        signal = res.predictions
        oos_px = universe.filter(pl.col("trade_date") >= folds[0].test_start)
        bt = run_backtest(
            oos_px,
            signal,
            nse_spec(TradingCalendar.from_frame(oos_px), dp_order_value=100_000.0),
            top_n=25,
            capital=2_500_000.0,
        )
        stats = summarize(bt.daily)
        ledger.append(
            Trial(
                model=name,
                label=f"fwd_{args.label_horizon}d_z",
                feature_set=f"library_v1_{len(names)}",
                params=cast(dict[str, object], params),
                mean_ic=res.mean_ic,
                ic_t_stat=res.ic_t_stat,
                net_sharpe=stats["sharpe"],
            )
        )
        n_trials = ledger.count()
        daily_sharpe = stats["sharpe"] / (252**0.5)
        dsr = deflated_sharpe(
            daily_sharpe,
            int(stats["n_days"]),
            n_trials=n_trials,
            sr_variance=(0.5 / 252**0.5) ** 2,
        )
        results[name] = {
            "mean_ic": res.mean_ic,
            "ic_t_stat": res.ic_t_stat,
            "ic_fold_range": [min(res.fold_ics), max(res.fold_ics)],
            "decile_spread_z": res.decile_spread,
            "net": stats,
            "dsr": dsr,
            "ledger_trials": n_trials,
        }
        print(f"{name}: {json.dumps(results[name])}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.reports_dir / f"model_study_{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
