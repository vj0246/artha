"""Risk analytics (plan section 11), computed on backtest daily returns.

Historical and Cornish-Fisher VaR/CVaR, Sortino/Calmar, rolling Sharpe,
drawdown state against the plan's de-risking rules, worst historical
windows, and days-to-liquidate at capped ADV participation.
"""

import math
from dataclasses import dataclass
from typing import cast

import numpy as np
import polars as pl
from scipy.stats import kurtosis, norm, skew  # type: ignore[import-untyped]

TRADING_DAYS = 252


@dataclass(frozen=True)
class VarReport:
    hist_var_95: float
    hist_var_99: float
    hist_cvar_95: float
    hist_cvar_99: float
    cf_var_95: float
    cf_var_99: float


def var_report(returns: pl.Series) -> VarReport:
    r = returns.to_numpy()
    if len(r) < 60:
        raise ValueError("need at least 60 observations")

    def hist_var(alpha: float) -> float:
        return float(-np.quantile(r, 1 - alpha))

    def hist_cvar(alpha: float) -> float:
        q = np.quantile(r, 1 - alpha)
        return float(-r[r <= q].mean())

    mu, sd = float(r.mean()), float(r.std(ddof=1))
    s, k = float(skew(r)), float(kurtosis(r))  # k = excess kurtosis

    def cf_var(alpha: float) -> float:
        z = norm.ppf(1 - alpha)
        z_cf = z + (z**2 - 1) * s / 6 + (z**3 - 3 * z) * k / 24 - (2 * z**3 - 5 * z) * (s**2) / 36
        return float(-(mu + sd * z_cf))

    return VarReport(
        hist_var_95=hist_var(0.95),
        hist_var_99=hist_var(0.99),
        hist_cvar_95=hist_cvar(0.95),
        hist_cvar_99=hist_cvar(0.99),
        cf_var_95=cf_var(0.95),
        cf_var_99=cf_var(0.99),
    )


def sortino(returns: pl.Series) -> float:
    r = returns.to_numpy()
    downside = r[r < 0]
    if len(downside) == 0:
        return float("inf")
    dd = math.sqrt(float((downside**2).mean()) * TRADING_DAYS)
    return float(r.mean()) * TRADING_DAYS / dd if dd > 0 else 0.0


def calmar(cagr: float, max_drawdown: float) -> float:
    return cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0


def rolling_sharpe(daily: pl.DataFrame, *, window: int = 252) -> pl.DataFrame:
    return daily.select(
        "trade_date",
        (
            pl.col("net_return").rolling_mean(window_size=window)
            / (pl.col("net_return").rolling_std(window_size=window) + 1e-12)
            * math.sqrt(TRADING_DAYS)
        ).alias("rolling_sharpe_1y"),
    ).drop_nulls()


def drawdown_state(daily: pl.DataFrame) -> pl.DataFrame:
    """Equity, running peak, drawdown, and the plan's de-risking action
    (halve gross at -10% from peak, flat at -15%)."""
    eq = daily.select(
        "trade_date", ((1.0 + pl.col("net_return")).cum_prod()).alias("equity")
    ).with_columns(pl.col("equity").cum_max().alias("peak"))
    return eq.with_columns(
        (pl.col("equity") / pl.col("peak") - 1.0).alias("drawdown"),
        pl.when(pl.col("equity") / pl.col("peak") - 1.0 <= -0.15)
        .then(pl.lit("flat"))
        .when(pl.col("equity") / pl.col("peak") - 1.0 <= -0.10)
        .then(pl.lit("half_gross"))
        .otherwise(pl.lit("normal"))
        .alias("derisk_state"),
    )


def worst_windows(daily: pl.DataFrame, *, window: int = 21, n: int = 5) -> pl.DataFrame:
    """The n worst rolling `window`-day net return stretches (stress replay
    on the strategy's own history)."""
    rolled = daily.select(
        "trade_date",
        ((1.0 + pl.col("net_return")).log().rolling_sum(window_size=window).exp() - 1.0).alias(
            "window_return"
        ),
    ).drop_nulls()
    return rolled.sort("window_return").head(n)


def days_to_liquidate(
    holdings: pl.DataFrame, adv: pl.DataFrame, *, capital: float, participation: float = 0.2
) -> pl.DataFrame:
    """Per-name days to exit the latest book at `participation` of ADV."""
    last_date = cast(object, holdings["rebalance_date"].max())
    book = holdings.filter(pl.col("rebalance_date") == last_date)
    joined = book.join(adv, on="canon_symbol", how="left")
    return (
        joined.with_columns(
            ((pl.col("weight") * capital) / (pl.col("adv_value") * participation + 1e-9)).alias(
                "days_to_liquidate"
            )
        )
        .select("canon_symbol", "weight", "days_to_liquidate")
        .sort("days_to_liquidate", descending=True)
    )
