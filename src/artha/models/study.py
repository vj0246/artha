"""Model-comparison study engine (plan v2 section 7.3).

One protocol for every model family: fit on purged expanding train folds,
predict scores on test folds, evaluate daily rank IC and decile spread, and
hand the stitched OOS predictions to the vectorized backtester for net
performance. Data is sampled on the weekly rebalance grid (signals are
weekly; training on ~330k weekly rows instead of ~1.7M daily rows changes
nothing downstream and keeps every model family tractable on this machine).
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

import numpy as np
import polars as pl

from artha.models.cv import Fold


class SupervisedModel(Protocol):
    def fit(self, X: np.ndarray, y: np.ndarray) -> object: ...
    def predict(self, X: np.ndarray) -> np.ndarray: ...


ModelFactory = Callable[[], SupervisedModel]


@dataclass(frozen=True)
class StudyResult:
    model: str
    fold_ics: list[float]
    mean_ic: float
    ic_t_stat: float
    decile_spread: float  # top-minus-bottom mean label (z units) per date
    predictions: pl.DataFrame  # canon_symbol, trade_date, score (OOS only)


def rank_ic_per_date(scored: pl.DataFrame) -> pl.DataFrame:
    """Spearman IC per trade_date between score and label."""
    ranked = scored.with_columns(
        pl.col("score").rank().over("trade_date").alias("_rs"),
        pl.col("label").rank().over("trade_date").alias("_rl"),
    )
    return (
        ranked.group_by("trade_date")
        .agg(pl.corr("_rs", "_rl").alias("ic"), pl.len().alias("n"))
        .filter(pl.col("n") >= 20)
        .sort("trade_date")
    )


def run_study(
    matrix: pl.DataFrame,
    feature_names: list[str],
    folds: list[Fold],
    factory: ModelFactory,
    *,
    model_name: str,
) -> StudyResult:
    """``matrix``: (canon_symbol, trade_date, features..., label), weekly grid."""
    preds: list[pl.DataFrame] = []
    fold_ics: list[float] = []
    for fold in folds:
        train = matrix.filter(pl.col("trade_date") <= fold.train_end)
        test = matrix.filter(pl.col("trade_date").is_between(fold.test_start, fold.test_end))
        if train.is_empty() or test.is_empty():
            continue
        model = factory()
        model.fit(
            train.select(feature_names).to_numpy(),
            train["label"].to_numpy(),
        )
        scores = model.predict(test.select(feature_names).to_numpy())
        scored = test.select("canon_symbol", "trade_date", "label").with_columns(
            pl.Series("score", scores.astype(np.float64))
        )
        preds.append(scored)
        ics = rank_ic_per_date(scored)
        if ics.height:
            fold_ics.append(cast(float, ics["ic"].mean()))

    all_preds = pl.concat(preds)
    daily_ics = rank_ic_per_date(all_preds)
    ic_series = daily_ics["ic"]
    mean_ic = cast(float, ic_series.mean())
    ic_std = cast(float, ic_series.std())
    t_stat = mean_ic / (ic_std / len(ic_series) ** 0.5) if ic_std else 0.0

    deciled = all_preds.with_columns(
        (
            (pl.col("score").rank("ordinal").over("trade_date") - 1)
            * 10
            // pl.len().over("trade_date")
        ).alias("_dec")
    )
    top = deciled.filter(pl.col("_dec") == 9)["label"].mean()
    bot = deciled.filter(pl.col("_dec") == 0)["label"].mean()
    spread = cast(float, top) - cast(float, bot)

    return StudyResult(
        model=model_name,
        fold_ics=fold_ics,
        mean_ic=mean_ic,
        ic_t_stat=t_stat,
        decile_spread=spread,
        predictions=all_preds.select("canon_symbol", "trade_date", "score"),
    )
