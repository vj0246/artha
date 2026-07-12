"""Summary statistics for backtest daily return series."""

import math
from typing import cast

import polars as pl

TRADING_DAYS = 252


def summarize(daily: pl.DataFrame, *, column: str = "net_return") -> dict[str, float]:
    """CAGR, annualized vol, Sharpe (0% rf), max drawdown, hit rate, and
    average annualized one-way turnover from a backtester daily frame."""
    r = daily[column]
    n = len(r)
    if n == 0:
        raise ValueError("empty return series")
    equity = (1.0 + r).cum_prod()
    years = n / TRADING_DAYS
    cagr = float(equity[-1]) ** (1 / years) - 1 if years > 0 else 0.0
    vol = cast(float, r.std() or 0.0) * math.sqrt(TRADING_DAYS)
    mean_ann = cast(float, r.mean() or 0.0) * TRADING_DAYS
    sharpe = mean_ann / vol if vol > 0 else 0.0
    peak = equity.cum_max()
    max_dd = cast(float, (equity / peak - 1.0).min() or 0.0)
    nonzero = r.filter(r != 0)
    hit = cast(float, (nonzero > 0).mean()) if len(nonzero) else 0.0
    out = {
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "hit_rate": hit,
        "n_days": float(n),
    }
    if "turnover" in daily.columns:
        out["turnover_oneway_ann"] = float(daily["turnover"].sum()) / years
    return out
