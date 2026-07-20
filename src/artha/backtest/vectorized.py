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

import math
from dataclasses import dataclass
from datetime import date
from typing import cast

import numpy as np
import polars as pl

from artha.marketspec.base import MarketSpec
from artha.portfolio.construct import ConstraintReport, Constructor
from artha.portfolio.riskmodel import MIN_OBS, ewma_cov, lw_shrunk_cov

RISK_WINDOW = 252  # trailing daily returns feeding the C2 risk model

ADV_WINDOW = 21
# vol targeting uses the LARGER of a fast and slow estimate: the fast window
# de-risks quickly in a crash, the slow one stops gross snapping back to 1.0
# the moment 21 calm days pass (which left long-run vol far above target)
VOL_LOOKBACK = 21
VOL_LOOKBACK_SLOW = 63


def _ann_vol(returns: list[float]) -> float:
    n = len(returns)
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return math.sqrt(var * 252)


@dataclass(frozen=True)
class BacktestResult:
    daily: pl.DataFrame  # trade_date, gross_return, cost, net_return, turnover
    holdings: pl.DataFrame  # rebalance_date, canon_symbol, weight
    rebalances: pl.DataFrame  # rebalance_date, realized_vol, gross_target

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
    constructor: Constructor | None = None,
    report: ConstraintReport | None = None,
    gross_gate: dict[date, float] | None = None,
    cov_estimator: str = "lw",
) -> BacktestResult:
    """``panel`` needs canon_symbol, trade_date, adj_close, traded_value,
    in_universe. ``signal``: (canon_symbol, trade_date, score). ``capital``
    in rupees activates impact costs (0 = charges only).

    With a ``constructor``, targets come from the constrained construction
    (caps, bands, vol targeting; possibly gross < 1 with the rest in cash)
    instead of naive top-N equal weight; pass a ConstraintReport to collect
    per-rebalance verification results. ``gross_gate`` (C4) maps rebalance
    dates to a multiplier applied to the built target's gross — values must
    be computed from information knowable at that date's close.
    ``cov_estimator``: "lw" (Ledoit-Wolf on the flat window) or "ewma"
    (RiskMetrics exponential weighting, Track E E1)."""
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

    # wide returns matrix for the C2 risk model (built once, sliced per
    # rebalance; every slice ends at the rebalance close - knowable at t)
    need_risk = constructor is not None and constructor.scheme in ("ivol", "minvar")
    wide_np = np.empty((0, 0))
    wide_row: dict[date, int] = {}
    wide_col: dict[str, int] = {}
    if need_risk:
        wide = px.pivot(on="canon_symbol", index="trade_date", values="ret").sort("trade_date")
        wide_row = {d: i for i, d in enumerate(wide["trade_date"].to_list())}
        wide_col = {s: i for i, s in enumerate(wide.columns[1:])}
        wide_np = wide.drop("trade_date").to_numpy()

    weights: dict[str, float] = {}
    adv: dict[str, float] = {}
    pending: tuple[int, dict[str, float]] | None = None  # (exec day index, target)
    daily_rows: list[dict[str, object]] = []
    # fully-invested book returns (portfolio return / gross exposure): the
    # vol-targeting input. Using the scaled portfolio's own vol would be a
    # feedback loop - once vol hits target, gross snaps back to 1.
    book_returns: list[float] = []
    holding_rows: list[dict[str, object]] = []
    rebalance_rows: list[dict[str, object]] = []
    rebalance_set = set(rebalance_days)
    cost_model = spec.cost_model

    for i, day in enumerate(all_days):
        # 1) accrue this day's close-to-close return on holdings acquired at
        #    an EARLIER close, and drift weights. This must precede execution:
        #    a position bought at today's close earns nothing today.
        gross = 0.0
        exposure = sum(weights.values())
        if weights:
            rets = by_date.get(day)
            if rets is not None:
                ret_map = dict(zip(rets["canon_symbol"], rets["ret"], strict=True))
                gross = sum(w * ret_map.get(n, 0.0) for n, w in weights.items())
                book_returns.append(gross / exposure if exposure > 1e-9 else 0.0)
                # cash-aware drift: portfolio grows by `gross` (cash earns 0),
                # each position by its own return
                if 1 + gross > 0:
                    weights = {
                        n: w * (1 + ret_map.get(n, 0.0)) / (1 + gross) for n, w in weights.items()
                    }

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
                .head(constructor.top_n if constructor else top_n)
            )
            if picks.height:
                # adv keeps the LAST KNOWN value for every name ever picked:
                # departing names need an ADV for their exit participation cap
                # (fail-open needs a stale value over a missing one)
                adv.update(zip(picks["canon_symbol"], picks["adv_value"], strict=True))
                realized: float | None = None
                if constructor is None:
                    w = 1.0 / picks.height
                    target = dict.fromkeys(picks["canon_symbol"], w)
                else:
                    fast = book_returns[-VOL_LOOKBACK:]
                    slow = book_returns[-VOL_LOOKBACK_SLOW:]
                    if len(fast) >= VOL_LOOKBACK:
                        realized = _ann_vol(fast)
                        if len(slow) >= VOL_LOOKBACK_SLOW:
                            realized = max(realized, _ann_vol(slow))
                    vols_in: dict[str, float] | None = None
                    cov_in: tuple[list[str], np.ndarray] | None = None
                    if need_risk and day in wide_row:
                        r = wide_row[day]
                        pick_names = list(picks["canon_symbol"])
                        cols = [wide_col[s] for s in pick_names]
                        window = wide_np[max(0, r - RISK_WINDOW + 1) : r + 1][:, cols]
                        obs = (~np.isnan(window)).sum(axis=0)
                        # per-name coverage, mirroring riskmodel.risk_inputs:
                        # a short-history name drops out of the risk model
                        # alone instead of disabling it for the whole book
                        covered = [
                            n for n, o in zip(pick_names, obs.tolist(), strict=True) if o >= MIN_OBS
                        ]
                        if covered:
                            keep = [pick_names.index(n) for n in covered]
                            sub = window[:, keep]
                            sd = np.nanstd(sub, axis=0, ddof=1) * math.sqrt(252)
                            vols_in = dict(zip(covered, sd.tolist(), strict=True))
                            if constructor.scheme == "minvar":
                                est = ewma_cov if cov_estimator == "ewma" else lw_shrunk_cov
                                cov_in = (covered, est(sub))
                    target = constructor.build(
                        list(zip(picks["canon_symbol"], picks["adv_value"], strict=True)),
                        dict(weights),
                        realized,
                        report if report is not None else ConstraintReport(),
                        adv_map=dict(adv),
                        vols=vols_in,
                        cov=cov_in,
                    )
                if gross_gate is not None:
                    gate = gross_gate.get(day, 1.0)
                    if gate < 1.0:
                        target = {s: w * gate for s, w in target.items()}
                pending = (i + exec_lag, target)
                rebalance_rows.append(
                    {
                        "rebalance_date": day,
                        "realized_vol": realized,
                        "gross_target": sum(target.values()),
                    }
                )
                holding_rows.extend(
                    {"rebalance_date": day, "canon_symbol": s, "weight": tw}
                    for s, tw in target.items()
                )

    return BacktestResult(
        daily=pl.DataFrame(daily_rows),
        holdings=pl.DataFrame(
            holding_rows,
            schema={"rebalance_date": pl.Date, "canon_symbol": pl.String, "weight": pl.Float64},
        ),
        rebalances=pl.DataFrame(
            rebalance_rows,
            schema={
                "rebalance_date": pl.Date,
                "realized_vol": pl.Float64,
                "gross_target": pl.Float64,
            },
        ),
    )
