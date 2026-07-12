"""Baseline factors (plan v2 section 7.1) and the feature registry.

Every feature declares its lookback and the timestamp at which it is
knowable; the lookahead suite audits signals against these declarations.
All baselines use only adjusted closes up to and including day t, so they
are knowable at t's close and tradeable no earlier than t+1 (the
backtester's execution lag enforces that side).

Scores are cross-sectionally comparable per date; higher = more attractive.
"""

from dataclasses import dataclass
from typing import Final

import polars as pl


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    lookback_days: int  # trading days of history consumed
    knowable_at: str  # when the value exists; audited by the lookahead suite
    description: str


FEATURE_REGISTRY: Final[dict[str, FeatureSpec]] = {
    "momentum_12_1": FeatureSpec(
        "momentum_12_1", 252, "close[t]", "12-month return skipping the most recent month"
    ),
    "reversal_5d": FeatureSpec("reversal_5d", 5, "close[t]", "negative 5-day return"),
    "low_vol_63d": FeatureSpec(
        "low_vol_63d", 63, "close[t]", "negative 63-day realized volatility"
    ),
}


def _ret(shift_from: int, shift_to: int) -> pl.Expr:
    """Return from t-shift_from to t-shift_to (trading-day offsets)."""
    return (pl.col("adj_close").shift(shift_to) / pl.col("adj_close").shift(shift_from) - 1).over(
        "canon_symbol"
    )


def momentum_12_1(panel: pl.DataFrame) -> pl.DataFrame:
    return _score(panel, _ret(252, 21))


def reversal_5d(panel: pl.DataFrame) -> pl.DataFrame:
    return _score(panel, -_ret(5, 0))


def low_vol_63d(panel: pl.DataFrame) -> pl.DataFrame:
    with_daily = panel.sort("canon_symbol", "trade_date").with_columns(
        (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1)
        .over("canon_symbol")
        .alias("_daily")
    )
    return _score(with_daily, -pl.col("_daily").rolling_std(window_size=63).over("canon_symbol"))


def _score(panel: pl.DataFrame, expr: pl.Expr) -> pl.DataFrame:
    """(canon_symbol, trade_date, score); rows without a full window drop."""
    return (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(expr.alias("score"))
        .filter(pl.col("score").is_not_null() & pl.col("score").is_finite())
        .select("canon_symbol", "trade_date", "score")
    )


BASELINES: Final = {
    "momentum_12_1": momentum_12_1,
    "reversal_5d": reversal_5d,
    "low_vol_63d": low_vol_63d,
}
