"""Forward-return labels, cross-sectionally z-scored per date (plan 7.3 v1).

A label at date t uses closes through t+h: it is NOT knowable at t. That is
fine for a training target; the purged CV (models.cv) guarantees no training
label's window overlaps a test window.
"""

import polars as pl

_EPS = 1e-12


def forward_return_z(panel: pl.DataFrame, horizon_days: int) -> pl.DataFrame:
    """(canon_symbol, trade_date, label): h-day forward return z-scored per date."""
    fwd = (pl.col("adj_close").shift(-horizon_days) / pl.col("adj_close") - 1).over("canon_symbol")
    return (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(fwd.alias("_fwd"))
        .filter(pl.col("_fwd").is_not_null() & pl.col("_fwd").is_finite())
        .with_columns(
            (
                (pl.col("_fwd") - pl.col("_fwd").mean().over("trade_date"))
                / (pl.col("_fwd").std().over("trade_date") + _EPS)
            ).alias("label")
        )
        .select("canon_symbol", "trade_date", "label")
    )
