"""The parity gate (plan v1 section 9): vectorized vs event engine, in CI.

Identical synthetic data, identical signal, identical cost model, both
engines. In fractional-share mode the two must agree to float noise; in
integer-share mode the divergence must stay inside a tight bound and be
attributable to share rounding alone.
"""

import math
from datetime import date, timedelta
from typing import cast

import numpy as np
import polars as pl
import pytest

from artha.backtest.engine import EventEngine
from artha.backtest.vectorized import run_backtest
from artha.data.calendar import TradingCalendar
from artha.marketspec.base import MarketSpec
from artha.marketspec.nse import NSECostModel

N_NAMES = 30
N_DAYS = 260
CAPITAL = 10_000_000.0


def weekdays_from(start: date, n: int) -> list[date]:
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


@pytest.fixture(scope="module")
def world() -> tuple[pl.DataFrame, pl.DataFrame, TradingCalendar]:
    rng = np.random.default_rng(42)
    days = weekdays_from(date(2023, 1, 2), N_DAYS)
    rows = []
    for i in range(N_NAMES):
        price = 100.0 * float(rng.uniform(0.5, 5.0))
        for d in days:
            price *= float(np.exp(rng.normal(0.0003, 0.012)))  # < band, no halts
            rows.append(
                {
                    "canon_symbol": f"S{i:02d}",
                    "trade_date": d,
                    "adj_close": price,
                    "traded_value": float(rng.uniform(5e8, 5e9)),
                    "in_universe": True,
                }
            )
    panel = pl.DataFrame(rows)
    cal = TradingCalendar(days)
    sig_rows = []
    for d in cal.week_last_days():
        scores = rng.normal(size=N_NAMES)
        for i in range(N_NAMES):
            sig_rows.append(
                {"canon_symbol": f"S{i:02d}", "trade_date": d, "score": float(scores[i])}
            )
    return panel, pl.DataFrame(sig_rows), cal


def spec_for(cal: TradingCalendar) -> MarketSpec:
    return MarketSpec("NSE", "INR", cal, 1, NSECostModel())


def run_both(
    world: tuple[pl.DataFrame, pl.DataFrame, TradingCalendar], *, fractional: bool
) -> tuple[pl.DataFrame, pl.DataFrame]:
    panel, signal, cal = world
    spec = spec_for(cal)
    vec = run_backtest(panel, signal, spec, top_n=10, capital=CAPITAL)
    engine = EventEngine(spec, capital=CAPITAL, fractional=fractional)
    ev = engine.run(
        panel.select("canon_symbol", "trade_date", "adj_close", "traded_value"),
        vec.holdings,  # identical targets: same signal, same selection
    )
    v = vec.daily.select("trade_date", "net_return")
    e = ev.daily_returns()
    joined = v.join(e, on="trade_date", how="inner", suffix="_engine").with_columns(
        (pl.col("net_return") - pl.col("net_return_engine")).abs().alias("diff")
    )
    return joined, ev.daily


def test_parity_fractional_shares_is_exact(world) -> None:  # type: ignore[no-untyped-def]
    joined, _ = run_both(world, fractional=True)
    mean_diff = cast(float, joined["diff"].mean())
    max_diff = cast(float, joined["diff"].max())
    assert mean_diff < 2e-5, f"mean daily divergence {mean_diff:.2e}"
    assert max_diff < 5e-4, f"max daily divergence {max_diff:.2e}"


def test_parity_integer_shares_bounded_by_rounding(world) -> None:  # type: ignore[no-untyped-def]
    joined, _daily = run_both(world, fractional=False)
    mean_diff = cast(float, joined["diff"].mean())
    max_diff = cast(float, joined["diff"].max())
    # rounding error scale: one share of a ~Rs 500 name on a Rs 1cr book
    assert mean_diff < 2e-4, f"mean daily divergence {mean_diff:.2e}"
    assert max_diff < 3e-3, f"max daily divergence {max_diff:.2e}"
    # cumulative equity paths stay within 2%
    v_total = float((1 + joined["net_return"]).product())
    e_total = float((1 + joined["net_return_engine"]).product())
    assert abs(math.log(v_total / e_total)) < 0.02


def test_engine_invariants(world) -> None:  # type: ignore[no-untyped-def]
    _, daily = run_both(world, fractional=False)
    assert cast(float, daily["equity"].min()) > 0
    assert cast(float, daily["gross_exposure"].max()) <= 1.02
