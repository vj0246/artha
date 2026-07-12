"""Vectorized cross-sectional backtester (plan v2 section 9, Track A).

Mechanics, chosen to make lookahead structurally impossible:

- Signals are scored as of rebalance date t (weekly grid: last trading day
  of each ISO week) using data knowable at t's close.
- Execution happens at the close of t+1 (``exec_lag=1``): the plan's
  near-close fill assumption. The first return a new position earns is
  close(t+1) -> close(t+2). Nothing dated t or earlier can buy t's return.
- Between rebalances, weights drift with returns; turnover is measured
  against the drifted weights.
- Costs: per-side fractions from the MarketSpec cost model, with impact
  driven by each name's 21-day median traded value (raw, unadjusted) and
  the portfolio's capital.

Portfolio: top N by score among names in the PIT universe at t, equal
weight, long-only, fully invested (cash earns zero, plan section 8 v1).
"""

from dataclasses import dataclass
from datetime import date
from typing import cast

import polars as pl

from artha.marketspec.base import MarketSpec

ADV_WINDOW = 21


@dataclass(frozen=True)
class BacktestResult:
    daily: pl.DataFrame  # trade_date, gross_return, cost, net_return, turnover
    holdings: pl.DataFrame  # rebalance_date, canon_symbol, weight

    def net_curve(self) -> pl.DataFrame:
        return self.daily.with_columns(((1.0 + pl.col("net_return")).cum_prod()).alias("equity"))


def run_backtest(
    panel: pl.DataFrame,
    signal: pl.DataFrame,
    spec: MarketSpec,
    *,
    top_n: int = 25,
    exec_lag: int = 1,
    capital: float = 0.0,
) -> BacktestResult:
    """``panel`` needs canon_symbol, trade_date, adj_close, traded_value,
    in_universe. ``signal``: (canon_symbol, trade_date, score). ``capital``
    in rupees activates impact costs (0 = charges only)."""
    px = panel.select(
        "canon_symbol", "trade_date", "adj_close", "traded_value", "in_universe"
    ).sort("canon_symbol", "trade_date")
    px = px.with_columns(
        (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).over("canon_symbol").alias("ret"),
        pl.col("traded_value")
        .rolling_median(window_size=ADV_WINDOW, min_samples=1)
        .over("canon_symbol")
        .alias("adv_value"),
    )

    cal = spec.calendar
    first_day = cast(date, px["trade_date"].min())
    rebalance_days = [d for d in cal.week_last_days() if d >= first_day]
    scored = signal.join(
        px.select("canon_symbol", "trade_date", "in_universe", "adv_value"),
        on=["canon_symbol", "trade_date"],
        how="inner",
    ).filter(pl.col("in_universe"))

    # returns matrix keyed by date for fast slicing
    by_date = {
        d: frame
        for (d,), frame in px.filter(pl.col("ret").is_not_null())
        .select("trade_date", "canon_symbol", "ret")
        .partition_by("trade_date", as_dict=True)
        .items()
    }
    all_days = cal.days

    weights: dict[str, float] = {}
    adv: dict[str, float] = {}
    pending: tuple[int, dict[str, float]] | None = None  # (exec day index, target)
    daily_rows: list[dict[str, object]] = []
    holding_rows: list[dict[str, object]] = []
    rebalance_set = set(rebalance_days)
    cost_model = spec.cost_model

    for i, day in enumerate(all_days):
        # 1) accrue this day's close-to-close return on holdings acquired at
        #    an EARLIER close, and drift weights. This must precede execution:
        #    a position bought at today's close earns nothing today.
        gross = 0.0
        if weights:
            rets = by_date.get(day)
            if rets is not None:
                ret_map = dict(zip(rets["canon_symbol"], rets["ret"], strict=True))
                gross = sum(w * ret_map.get(n, 0.0) for n, w in weights.items())
                drifted = {n: w * (1 + ret_map.get(n, 0.0)) for n, w in weights.items()}
                total = sum(drifted.values())
                if total > 0:
                    weights = {n: w / total for n, w in drifted.items()}

        # 2) execute a due rebalance at this day's close
        turnover = 0.0
        cost = 0.0
        if pending is not None and pending[0] == i:
            target = pending[1]
            pending = None
            names = set(weights) | set(target)
            for name in names:
                delta = target.get(name, 0.0) - weights.get(name, 0.0)
                if abs(delta) < 1e-12:
                    continue
                order_value = abs(delta) * capital
                adv_value = adv.get(name, 0.0)
                rate = (
                    cost_model.buy_cost(order_value, adv_value)
                    if delta > 0
                    else cost_model.sell_cost(order_value, adv_value)
                )
                cost += abs(delta) * rate
                turnover += abs(delta)
            weights = dict(target)

        daily_rows.append(
            {
                "trade_date": day,
                "gross_return": gross,
                "cost": cost,
                "net_return": gross - cost,
                "turnover": turnover / 2.0,  # one-way
            }
        )

        # 3) form a new target at a rebalance close, to execute exec_lag later
        if day in rebalance_set and i + exec_lag < len(all_days):
            picks = (
                scored.filter(pl.col("trade_date") == day)
                .sort("score", descending=True)
                .head(top_n)
            )
            if picks.height:
                w = 1.0 / picks.height
                pending = (i + exec_lag, dict.fromkeys(picks["canon_symbol"], w))
                adv.update(zip(picks["canon_symbol"], picks["adv_value"], strict=True))
                holding_rows.extend(
                    {"rebalance_date": day, "canon_symbol": s, "weight": w}
                    for s in picks["canon_symbol"]
                )

    return BacktestResult(
        daily=pl.DataFrame(daily_rows),
        holdings=pl.DataFrame(
            holding_rows,
            schema={"rebalance_date": pl.Date, "canon_symbol": pl.String, "weight": pl.Float64},
        ),
    )
