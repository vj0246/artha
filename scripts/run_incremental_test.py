"""P4 incremental-value test (plan v2 section 12.4): Model A vs Model B.

Usage:
    uv run --no-sync python scripts/run_incremental_test.py

A = 19 price/volume features. B = A + 9 knowable-dated event features.
C = event features alone (orthogonality diagnostic). Same weekly grid,
same purged folds, same backtester, same ledger as P3. Models: ridge and
transformer (the two families that survived P3). Reports delta IC, delta
net Sharpe, DSR, and the rank correlation of C's scores with momentum and
reversal (is event information just price information in disguise?).
"""

import json
import sys
from datetime import UTC, datetime
from typing import cast

import polars as pl
from sklearn.linear_model import Ridge

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.adjust import canonicalize_symbols
from artha.data.calendar import TradingCalendar
from artha.data.ingest.symbolchange import parse_symbolchange
from artha.data.universe import pit_universe
from artha.events.event_study import market_model_abnormal
from artha.events.features import EVENT_FEATURES, build_event_features, knowable_dates
from artha.features.library import build_features
from artha.labels.horizon import forward_return_z
from artha.marketspec.nse import nse_spec
from artha.models.cv import walk_forward_folds
from artha.models.dsr import deflated_sharpe
from artha.models.ledger import Trial, TrialLedger
from artha.models.study import rank_ic_per_date, run_study
from artha.models.transformer import TabTransformerRegressor

MODELS = {
    "ridge": lambda: Ridge(alpha=1.0),
    "transformer": lambda: TabTransformerRegressor(),
}


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    in_univ = universe.filter(pl.col("in_universe"))
    cal = TradingCalendar.from_frame(universe)
    weekly = sorted(set(cal.week_last_days()))

    features, price_names = build_features(in_univ)
    labels = forward_return_z(panel, 5)
    matrix_a = (
        features.join(labels, on=["canon_symbol", "trade_date"], how="inner")
        .filter(pl.col("trade_date").is_in(weekly))
        .sort("trade_date", "canon_symbol")
    )

    # event features on the same grid
    events = pl.read_parquet(settings.curated_dir / "events" / "classified.parquet")
    bm = pl.read_parquet(settings.curated_dir / "events" / "board_meetings.parquet")
    snapshot = sorted((settings.raw_dir / "symbolchange").glob("symbolchange_*.csv"))[-1]
    changes = parse_symbolchange(snapshot.read_bytes())
    market = pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty50.parquet")
    abnormal = market_model_abnormal(
        in_univ.select("canon_symbol", "trade_date", "adj_close"), market
    )
    meetings = (
        knowable_dates(bm.filter(pl.col("intimated_at").is_not_null()), cal, "intimated_at")
        .rename({"knowable_date": "intimation_knowable_date", "symbol": "canon_symbol"})
        .pipe(canonicalize_symbols, changes, date_col="meeting_date")
        .select("canon_symbol", "meeting_date", "intimation_knowable_date")
    )
    grid = matrix_a.select("canon_symbol", "trade_date")
    ev_feats = build_event_features(grid, events, meetings, abnormal)
    z = [
        (
            (pl.col(n) - pl.col(n).mean().over("trade_date"))
            / (pl.col(n).std().over("trade_date") + 1e-12)
        )
        .fill_null(0.0)
        .fill_nan(0.0)
        .alias(n)
        for n in EVENT_FEATURES
    ]
    matrix_b = matrix_a.join(
        ev_feats.with_columns(*z), on=["canon_symbol", "trade_date"], how="left"
    ).with_columns(*(pl.col(n).fill_null(0.0) for n in EVENT_FEATURES))

    grid_dates = sorted(matrix_a["trade_date"].unique().to_list())
    folds = walk_forward_folds(
        grid_dates, test_days=13, min_train_days=156, horizon_days=1, embargo_days=4
    )
    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    oos_px = universe.filter(pl.col("trade_date") >= folds[0].test_start)
    spec = nse_spec(TradingCalendar.from_frame(oos_px), dp_order_value=100_000.0)

    results: dict[str, object] = {}
    for model_name, factory in MODELS.items():
        per_model: dict[str, object] = {}
        for variant, matrix, names in (
            ("A_price", matrix_a, price_names),
            ("B_price_plus_events", matrix_b, price_names + EVENT_FEATURES),
            ("C_events_only", matrix_b, list(EVENT_FEATURES)),
        ):
            res = run_study(matrix, names, folds, factory, model_name=model_name)
            bt = run_backtest(oos_px, res.predictions, spec, top_n=25, capital=2_500_000.0)
            stats = summarize(bt.daily)
            ledger.append(
                Trial(
                    model=model_name,
                    label="fwd_5d_z",
                    feature_set=variant,
                    params={},
                    mean_ic=res.mean_ic,
                    ic_t_stat=res.ic_t_stat,
                    net_sharpe=stats["sharpe"],
                )
            )
            dsr = deflated_sharpe(
                stats["sharpe"] / (252**0.5),
                int(stats["n_days"]),
                n_trials=ledger.count(),
                sr_variance=(0.5 / 252**0.5) ** 2,
            )
            per_model[variant] = {
                "mean_ic": res.mean_ic,
                "ic_t": res.ic_t_stat,
                "net_sharpe": stats["sharpe"],
                "net_cagr": stats["cagr"],
                "turnover": stats["turnover_oneway_ann"],
                "dsr": dsr,
            }
            if variant == "C_events_only":
                # orthogonality: are C's scores just momentum/reversal?
                diag = res.predictions.join(
                    matrix_a.select("canon_symbol", "trade_date", "mom_12_1", "rev_5d"),
                    on=["canon_symbol", "trade_date"],
                    how="inner",
                )
                per_model["c_vs_momentum_rank_corr"] = cast(
                    float,
                    rank_ic_per_date(
                        diag.select(
                            "canon_symbol", "trade_date", "score", pl.col("mom_12_1").alias("label")
                        )
                    )["ic"].mean(),
                )
                per_model["c_vs_reversal_rank_corr"] = cast(
                    float,
                    rank_ic_per_date(
                        diag.select(
                            "canon_symbol", "trade_date", "score", pl.col("rev_5d").alias("label")
                        )
                    )["ic"].mean(),
                )
            print(f"{model_name}/{variant}: {json.dumps(per_model[variant])}", flush=True)
        a = cast(dict[str, float], per_model["A_price"])
        b = cast(dict[str, float], per_model["B_price_plus_events"])
        per_model["delta_ic"] = b["mean_ic"] - a["mean_ic"]
        per_model["delta_net_sharpe"] = b["net_sharpe"] - a["net_sharpe"]
        results[model_name] = per_model
        print(
            f"{model_name}: delta IC {per_model['delta_ic']:+.4f}, "
            f"delta net Sharpe {per_model['delta_net_sharpe']:+.3f}",
            flush=True,
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.reports_dir / f"incremental_test_{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
