"""Event-study framework (plan v2 section 12.2, MacKinlay 1997).

Market-model abnormal returns: for each name, alpha/beta estimated on a
trailing window of daily returns against the market; abnormal return
AR_t = r_t - (alpha + beta * r_m,t). CARs accumulate ARs over event windows
measured in trading days relative to the event's knowable date (day 0 =
first close that could react, from events.knowability).

Significance: cross-sectional t-test over events per category, plus a
circular block bootstrap of the CAR mean.
"""

import math
from dataclasses import dataclass

import numpy as np
import polars as pl

ESTIMATION_DAYS = 120
MIN_ESTIMATION_OBS = 60


def market_model_abnormal(panel: pl.DataFrame, market: pl.DataFrame) -> pl.DataFrame:
    """(canon_symbol, trade_date, ar): daily abnormal returns.

    ``panel``: canon_symbol, trade_date, adj_close. ``market``: trade_date,
    tr_return (or pr_return). Rolling alpha/beta over ESTIMATION_DAYS ending
    at t-1, so day-t abnormal return uses only prior information.
    """
    mkt = market.select("trade_date", pl.col("tr_return").alias("rm"))
    df = (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(
            (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).over("canon_symbol").alias("r")
        )
        .join(mkt, on="trade_date", how="inner")
        .filter(pl.col("r").is_finite() & pl.col("rm").is_finite())
    )

    # rolling moments ending at t-1 (shifted), per name
    def _roll(e: pl.Expr) -> pl.Expr:
        return e.rolling_mean(window_size=ESTIMATION_DAYS, min_samples=MIN_ESTIMATION_OBS)

    df = df.with_columns(
        _roll(pl.col("r")).shift(1).over("canon_symbol").alias("_mr"),
        _roll(pl.col("rm")).shift(1).over("canon_symbol").alias("_mm"),
        _roll(pl.col("r") * pl.col("rm")).shift(1).over("canon_symbol").alias("_mrm"),
        _roll(pl.col("rm") * pl.col("rm")).shift(1).over("canon_symbol").alias("_mmm"),
    )
    var_m = pl.col("_mmm") - pl.col("_mm") ** 2
    beta = (pl.col("_mrm") - pl.col("_mr") * pl.col("_mm")) / (var_m + 1e-12)
    alpha = pl.col("_mr") - beta * pl.col("_mm")
    return (
        df.with_columns((pl.col("r") - (alpha + beta * pl.col("rm"))).alias("ar"))
        .filter(pl.col("_mmm").is_not_null())
        .select("canon_symbol", "trade_date", "ar")
    )


def cumulative_abnormal_returns(
    abnormal: pl.DataFrame,
    events: pl.DataFrame,
    *,
    window: tuple[int, int],
) -> pl.DataFrame:
    """CAR over [start, end] trading days relative to each event's day 0.

    ``events``: (canon_symbol, event_date) with event_date = knowable date.
    Events without full window coverage drop.
    """
    start, end = window
    need = end - start + 1
    indexed = abnormal.sort("canon_symbol", "trade_date").with_columns(
        pl.int_range(pl.len()).over("canon_symbol").alias("_idx"),
    )
    ev = events.join(
        indexed.select("canon_symbol", pl.col("trade_date").alias("event_date"), "_idx"),
        on=["canon_symbol", "event_date"],
        how="inner",
    ).rename({"_idx": "_event_idx"})
    joined = ev.join(indexed, on="canon_symbol", how="inner").filter(
        (pl.col("_idx") >= pl.col("_event_idx") + start)
        & (pl.col("_idx") <= pl.col("_event_idx") + end)
    )
    return (
        joined.group_by("canon_symbol", "event_date")
        .agg(pl.col("ar").sum().alias("car"), pl.len().alias("_n"))
        .filter(pl.col("_n") == need)
        .drop("_n")
        .sort("canon_symbol", "event_date")
    )


@dataclass(frozen=True)
class CarStats:
    n_events: int
    mean_car: float
    t_stat: float
    bootstrap_p: float  # two-sided, H0: mean CAR = 0


def car_significance(cars: pl.DataFrame, *, n_boot: int = 2000, seed: int = 11) -> CarStats:
    values = cars["car"].to_numpy()
    n = len(values)
    if n < 2:
        raise ValueError("need at least 2 events")
    mean = float(values.mean())
    t = mean / (float(values.std(ddof=1)) / math.sqrt(n))
    rng = np.random.default_rng(seed)
    centered = values - mean
    boots = np.array([centered[rng.integers(0, n, size=n)].mean() for _ in range(n_boot)])
    p = float((np.abs(boots) >= abs(mean)).mean())
    return CarStats(n_events=n, mean_car=mean, t_stat=t, bootstrap_p=p)
