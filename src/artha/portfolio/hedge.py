"""NIFTY-futures beta hedge overlay (Track B B4; plan section 15 item 1).

Daily: short futures notional equal to the strategy's rolling beta times
equity. The hedge ratio applied to day t uses returns THROUGH t-1 only
(shifted rolling regression - no lookahead). Costs: a per-side rate on
hedge-notional changes plus the monthly roll (close old, open new).

Margin financing is not modeled (cash covers span comfortably at these
gross levels); stated as a limitation in the study note.
"""

from typing import Final

import polars as pl

BETA_WINDOW: Final = 60
FUT_COST_PER_SIDE: Final = 0.0002  # ~2bps: exchange+stamp+impact on index futures
ROLL_DAYS_PER_YEAR: Final = 12


def rolling_beta(
    strategy: pl.DataFrame, futures: pl.DataFrame, *, window: int = BETA_WINDOW
) -> pl.DataFrame:
    """(trade_date, beta): rolling OLS beta of strategy net returns on
    front-month futures returns, lagged one day (usable at t)."""
    j = strategy.select("trade_date", "net_return").join(
        futures.select("trade_date", "fut_return"), on="trade_date", how="inner"
    )

    def roll(e: pl.Expr) -> pl.Expr:
        return e.rolling_mean(window_size=window, min_samples=window)

    j = j.with_columns(
        roll(pl.col("net_return")).alias("_ms"),
        roll(pl.col("fut_return")).alias("_mf"),
        roll(pl.col("net_return") * pl.col("fut_return")).alias("_msf"),
        roll(pl.col("fut_return") * pl.col("fut_return")).alias("_mff"),
    )
    beta = (pl.col("_msf") - pl.col("_ms") * pl.col("_mf")) / (
        pl.col("_mff") - pl.col("_mf") ** 2 + 1e-12
    )
    return (
        j.with_columns(beta.shift(1).alias("beta"))  # knowable at t
        .filter(pl.col("beta").is_not_null())
        .select("trade_date", "beta")
    )


def hedged_returns(strategy: pl.DataFrame, futures: pl.DataFrame) -> pl.DataFrame:
    """Daily hedged net returns and the hedge's own cost drag.

    hedged_t = net_t - beta_t * fut_t - costs; costs = per-side rate on the
    day-over-day change in hedge notional (as a fraction of equity) plus a
    flat monthly-roll charge amortized daily.
    """
    betas = rolling_beta(strategy, futures)
    j = (
        strategy.select("trade_date", "net_return")
        .join(futures.select("trade_date", "fut_return"), on="trade_date", how="inner")
        .join(betas, on="trade_date", how="inner")
        .sort("trade_date")
    )
    daily_roll_cost = 2 * FUT_COST_PER_SIDE * ROLL_DAYS_PER_YEAR / 252
    return j.with_columns(
        (
            (pl.col("beta") - pl.col("beta").shift(1)).abs().fill_null(pl.col("beta").abs())
            * FUT_COST_PER_SIDE
            + pl.col("beta").abs() * daily_roll_cost
        ).alias("hedge_cost"),
    ).with_columns(
        (pl.col("net_return") - pl.col("beta") * pl.col("fut_return") - pl.col("hedge_cost")).alias(
            "hedged_return"
        )
    )
