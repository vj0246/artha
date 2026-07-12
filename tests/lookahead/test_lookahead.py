"""Lookahead suite (plan section 9): structural no-peek guarantees, in CI forever.

1. Planted-jump test: a price jump that happens between signal date and
   execution must NOT be captured. If the backtester ever executes at the
   signal's own close (or earlier), this fails loudly.
2. Scrambled-signal test: random scores on drift-free data earn ~nothing
   gross; any systematic profit means machinery leaks future information.
3. Registry audit: every registered feature must declare close[t]
   knowability; anything else needs an explicit lag review here.
"""

import random
from datetime import date, timedelta
from typing import cast

import polars as pl
import pytest

from artha.backtest.vectorized import run_backtest
from artha.data.calendar import TradingCalendar
from artha.features.baselines import FEATURE_REGISTRY
from artha.marketspec.base import MarketSpec


class ZeroCost:
    def buy_cost(self, order_value: float, adv_value: float) -> float:
        return 0.0

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        return 0.0


def weekdays_from(start: date, n: int) -> list[date]:
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def spec_for(days: list[date]) -> MarketSpec:
    return MarketSpec("TEST", "INR", TradingCalendar(days), 1, ZeroCost())


def test_planted_jump_between_signal_and_execution_is_not_captured() -> None:
    days = weekdays_from(date(2024, 1, 1), 10)
    # JUMP doubles between the Friday signal close (day 4) and the Monday
    # execution close (day 5). A same-close executor would book +100%.
    jump = [100.0] * 5 + [200.0] * 5
    flat = [100.0] * 10
    rows = []
    for sym, series in {"JUMP": jump, "FLAT": flat}.items():
        for d, p in zip(days, series, strict=True):
            rows.append(
                {
                    "canon_symbol": sym,
                    "trade_date": d,
                    "adj_close": p,
                    "traded_value": 1e9,
                    "in_universe": True,
                }
            )
    panel = pl.DataFrame(rows)
    signal = pl.DataFrame({"canon_symbol": ["JUMP"], "trade_date": [days[4]], "score": [1.0]})
    res = run_backtest(panel, signal, spec_for(days), top_n=1)
    total_gross = float(res.daily["gross_return"].sum())
    assert total_gross == pytest.approx(0.0), (
        f"captured {total_gross:+.2%}: execution saw a return earned before it traded"
    )


def test_scrambled_signal_earns_nothing_on_driftless_data() -> None:
    rng = random.Random(7)
    days = weekdays_from(date(2022, 1, 3), 260)
    symbols = [f"S{i}" for i in range(30)]
    rows = []
    for sym in symbols:
        price = 100.0
        sym_rng = random.Random(hash(sym) % 100_000)
        for d in days:
            # zero-drift coin-flip returns
            price *= 1.02 if sym_rng.random() < 0.5 else 1 / 1.02
            rows.append(
                {
                    "canon_symbol": sym,
                    "trade_date": d,
                    "adj_close": price,
                    "traded_value": 1e9,
                    "in_universe": True,
                }
            )
    panel = pl.DataFrame(rows)
    cal = TradingCalendar(days)
    signal_rows = []
    for d in cal.week_last_days():
        for sym in symbols:
            signal_rows.append({"canon_symbol": sym, "trade_date": d, "score": rng.random()})
    signal = pl.DataFrame(signal_rows)
    res = run_backtest(panel, signal, spec_for(days), top_n=10)
    daily_mean = cast(float, res.daily["gross_return"].mean())
    daily_std = cast(float, res.daily["gross_return"].std())
    # mean daily gross within 3 standard errors of zero
    se = daily_std / max(len(res.daily), 1) ** 0.5
    assert abs(daily_mean) < 3 * se, f"random signal earned {daily_mean:+.5f}/day"


def test_registry_knowability_declarations() -> None:
    for spec in FEATURE_REGISTRY.values():
        assert spec.knowable_at == "close[t]", (
            f"{spec.name}: undeclared knowability '{spec.knowable_at}' needs lag review"
        )
        assert spec.lookback_days > 0
