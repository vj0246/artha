"""Price/volume feature library for the model study (plan v2 section 7.2).

Every feature uses data up to and including day t's close only (close[t]
knowability, audited by the lookahead suite via the registry). Features are
cross-sectionally z-scored per date at the end, GKX-style, so models see
comparable scales; the raw panel columns they derive from are adjusted
prices and RAW traded value.
"""

from typing import Final

import polars as pl

from artha.features.baselines import FeatureSpec

_EPS: Final = 1e-12


def _r(n: int) -> pl.Expr:
    """n-day return up to t."""
    return (pl.col("adj_close") / pl.col("adj_close").shift(n) - 1).over("canon_symbol")


def _daily() -> pl.Expr:
    return (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).over("canon_symbol")


def _roll_std(expr: pl.Expr, n: int) -> pl.Expr:
    return expr.rolling_std(window_size=n).over("canon_symbol")


_LOOKBACKS: Final = (5, 21, 63, 126, 252)


def build_features(panel: pl.DataFrame) -> tuple[pl.DataFrame, list[str]]:
    """Return (frame with canon_symbol, trade_date + z-scored feature columns,
    feature name list). Rows keep only dates where the name has the maximum
    lookback available (252d), so the matrix is dense."""
    df = panel.sort("canon_symbol", "trade_date").with_columns(_daily().alias("_d1"))

    exprs: dict[str, pl.Expr] = {}
    for n in _LOOKBACKS:
        exprs[f"ret_{n}d"] = _r(n)
    exprs["mom_12_1"] = (pl.col("adj_close").shift(21) / pl.col("adj_close").shift(252) - 1).over(
        "canon_symbol"
    )
    exprs["rev_1d"] = -_r(1)
    exprs["rev_5d"] = -_r(5)
    for n in (21, 63):
        exprs[f"vol_{n}d"] = _roll_std(pl.col("_d1"), n)
        exprs[f"downside_vol_{n}d"] = _roll_std(
            pl.when(pl.col("_d1") < 0).then(pl.col("_d1")).otherwise(0.0), n
        )
    high_252 = pl.col("adj_close").rolling_max(window_size=252).over("canon_symbol")
    low_252 = pl.col("adj_close").rolling_min(window_size=252).over("canon_symbol")
    exprs["dist_52w_high"] = pl.col("adj_close") / (high_252 + _EPS) - 1
    exprs["dist_52w_low"] = pl.col("adj_close") / (low_252 + _EPS) - 1
    # Amihud illiquidity: |ret| / traded value, 21d mean (raw value, rupees)
    exprs["amihud_21d"] = (
        (pl.col("_d1").abs() / (pl.col("traded_value") + 1.0))
        .rolling_mean(window_size=21)
        .over("canon_symbol")
    )
    exprs["turnover_z_21d"] = (
        pl.col("traded_value")
        - pl.col("traded_value").rolling_mean(window_size=21).over("canon_symbol")
    ) / (pl.col("traded_value").rolling_std(window_size=21).over("canon_symbol") + _EPS)
    tr = (pl.col("high") - pl.col("low")) / (pl.col("close") + _EPS)
    exprs["atr_range_21d"] = tr.rolling_mean(window_size=21).over("canon_symbol")
    roll_max_63 = pl.col("adj_close").rolling_max(window_size=63).over("canon_symbol")
    exprs["maxdd_63d"] = pl.col("adj_close") / (roll_max_63 + _EPS) - 1
    exprs["month_end"] = pl.col("trade_date").dt.day().ge(25).cast(pl.Float64)

    names = sorted(exprs)
    df = df.with_columns(*(e.alias(k) for k, e in exprs.items()))
    dense = df.filter(pl.col("ret_252d").is_not_null()).select("canon_symbol", "trade_date", *names)
    # cross-sectional z-score per date; null/inf -> 0 after scoring
    zscored = dense.with_columns(
        *(
            (
                (pl.col(n) - pl.col(n).mean().over("trade_date"))
                / (pl.col(n).std().over("trade_date") + _EPS)
            )
            .fill_null(0.0)
            .fill_nan(0.0)
            .alias(n)
            for n in names
        )
    )
    return zscored, names


_LOOKBACK_BY_NAME: Final = {
    "ret_5d": 5,
    "ret_21d": 21,
    "ret_63d": 63,
    "ret_126d": 126,
    "rev_1d": 1,
    "rev_5d": 5,
    "vol_21d": 21,
    "downside_vol_21d": 21,
    "amihud_21d": 22,
    "turnover_z_21d": 21,
    "atr_range_21d": 21,
    "maxdd_63d": 63,
    "vol_63d": 63,
    "downside_vol_63d": 63,
    "month_end": 1,
}


def feature_registry(names: list[str]) -> dict[str, FeatureSpec]:
    """Registry entries for the library (all close[t] knowable; default
    lookback 252 for full-year windows)."""
    return {
        n: FeatureSpec(n, _LOOKBACK_BY_NAME.get(n, 252), "close[t]", "model-study feature")
        for n in names
    }
