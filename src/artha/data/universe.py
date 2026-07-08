"""Point-in-time investable universe from liquidity, price, and age filters.

The bhavcopy panel already contains every security that traded on each day,
including later-delisted names, so a universe defined purely by PIT filters
is survivorship-free by construction (ADR 0004). On date t a name is
investable when, using only data up to and including t:

- it has traded at least ``min_listed_days`` sessions,
- its 63-day median daily traded value is at least ``min_traded_value``,
- its raw close (the actual tradeable price) is at least ``min_price``,
- it ranks in the top ``top_n`` by that median traded value.

Index-membership replay (plan 5.2) becomes an optional AND-refinement once a
scriptable constituent-change source is secured.
"""

from typing import Final

import polars as pl

MIN_TRADED_VALUE: Final = 5e7  # Rs 5 cr/day (plan 5.2)
MIN_PRICE: Final = 20.0
MIN_LISTED_DAYS: Final = 126
LIQUIDITY_WINDOW: Final = 63
TOP_N: Final = 500


def pit_universe(
    panel: pl.DataFrame,
    *,
    min_traded_value: float = MIN_TRADED_VALUE,
    min_price: float = MIN_PRICE,
    min_listed_days: int = MIN_LISTED_DAYS,
    liquidity_window: int = LIQUIDITY_WINDOW,
    top_n: int = TOP_N,
) -> pl.DataFrame:
    """Add PIT universe columns to the panel.

    Returns the panel with ``median_traded_value``, ``listed_days``,
    ``liquidity_rank`` (per date, among names passing the base filters) and
    ``in_universe``. Rolling statistics use only rows up to each date.
    """
    with_stats = panel.sort("canon_symbol", "trade_date").with_columns(
        pl.col("traded_value")
        .rolling_median(window_size=liquidity_window)
        .over("canon_symbol")
        .alias("median_traded_value"),
        pl.col("trade_date").cum_count().over("canon_symbol").alias("listed_days"),
    )
    passes = (
        pl.col("median_traded_value").is_not_null()
        & (pl.col("median_traded_value") >= min_traded_value)
        & (pl.col("listed_days") >= min_listed_days)
        & (pl.col("close") >= min_price)
    )
    return (
        with_stats.with_columns(
            pl.when(passes).then(pl.col("median_traded_value")).alias("_eligible_tv")
        )
        .with_columns(
            # rank propagates nulls, so only names passing the base filters compete
            pl.col("_eligible_tv")
            .rank(method="ordinal", descending=True)
            .over("trade_date")
            .alias("liquidity_rank")
        )
        .drop("_eligible_tv")
        .with_columns(
            (pl.col("liquidity_rank").is_not_null() & (pl.col("liquidity_rank") <= top_n)).alias(
                "in_universe"
            )
        )
        .sort("canon_symbol", "trade_date")
    )
