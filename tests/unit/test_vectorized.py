"""Vectorized backtester mechanics on tiny deterministic panels."""

from datetime import date, timedelta

import polars as pl
import pytest

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.data.calendar import TradingCalendar
from artha.marketspec.base import MarketSpec


class FlatCost:
    """1% each side, no impact: makes cost arithmetic trivially checkable."""

    def buy_cost(self, order_value: float, adv_value: float) -> float:
        return 0.01

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        return 0.01


def weekdays_from(start: date, n: int) -> list[date]:
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def mk_panel(prices: dict[str, list[float]], days: list[date]) -> pl.DataFrame:
    rows = []
    for sym, series in prices.items():
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
    return pl.DataFrame(rows)


def spec_for(days: list[date], cost: object | None = None) -> MarketSpec:
    return MarketSpec(
        name="TEST",
        currency="INR",
        calendar=TradingCalendar(days),
        settlement_lag_days=1,
        cost_model=cost or FlatCost(),  # type: ignore[arg-type]
    )


DAYS = weekdays_from(date(2024, 1, 1), 10)  # Mon..Fri, Mon..Fri


def test_execution_lag_and_return_accrual() -> None:
    # A doubles between day 6 and day 7 closes; B is flat.
    a = [100.0] * 6 + [200.0, 200.0, 200.0, 200.0]
    b = [100.0] * 10
    panel = mk_panel({"A": a, "B": b}, DAYS)
    # signal on Friday day index 4 (rebalance day) picks A only
    signal = pl.DataFrame({"canon_symbol": ["A"], "trade_date": [DAYS[4]], "score": [1.0]})
    res = run_backtest(panel, signal, spec_for(DAYS), top_n=1)
    daily = res.daily
    # executed at close of day 5 (Monday); first earned return is day 6->7?
    # A's jump is close(6)->close(7)... indices: buy at close DAYS[5];
    # day 6 return = a[6]/a[5]-1 = 100% earned by the position.
    jump_day = DAYS[6]
    assert daily.filter(pl.col("trade_date") == jump_day)["gross_return"][0] == pytest.approx(1.0)
    # nothing earned before execution
    for d in DAYS[:6]:
        assert daily.filter(pl.col("trade_date") == d)["gross_return"][0] == 0.0


def test_costs_and_turnover_on_entry_and_switch() -> None:
    a = [100.0] * 10
    b = [100.0] * 10
    panel = mk_panel({"A": a, "B": b}, DAYS)
    # Friday 1: pick A; Friday 2: pick B (full switch)
    signal = pl.DataFrame(
        {
            "canon_symbol": ["A", "B"],
            "trade_date": [DAYS[4], DAYS[9]],
            "score": [1.0, 1.0],
        }
    )
    # second rebalance needs an execution day after DAYS[9]: extend calendar
    days11 = weekdays_from(date(2024, 1, 1), 12)
    panel = mk_panel({"A": [*a, 100.0, 100.0], "B": [*b, 100.0, 100.0]}, days11)
    res = run_backtest(panel, signal, spec_for(days11), top_n=1)
    daily = res.daily
    entry = daily.filter(pl.col("trade_date") == days11[5]).row(0, named=True)
    assert entry["turnover"] == pytest.approx(0.5)  # one-way: full buy / 2
    assert entry["cost"] == pytest.approx(0.01)  # 1% on 100% bought
    switch = daily.filter(pl.col("trade_date") == days11[10]).row(0, named=True)
    assert switch["turnover"] == pytest.approx(1.0)  # sell all + buy all
    assert switch["cost"] == pytest.approx(0.02)
    assert switch["net_return"] == pytest.approx(-0.02)


def test_weights_drift_between_rebalances() -> None:
    # equal weight A+B at entry; A doubles on day 6, B flat.
    a = [100.0] * 6 + [200.0] * 4
    b = [100.0] * 10
    panel = mk_panel({"A": a, "B": b}, DAYS)
    signal = pl.DataFrame(
        {"canon_symbol": ["A", "B"], "trade_date": [DAYS[4]] * 2, "score": [1.0, 1.0]}
    )
    res = run_backtest(panel, signal, spec_for(DAYS), top_n=2)
    daily = res.daily
    # day 6: 0.5 * 100% = 50% portfolio return
    assert daily.filter(pl.col("trade_date") == DAYS[6])["gross_return"][0] == pytest.approx(0.5)
    # day 7 onward: A is 2/3 of the book; both flat -> zero return
    assert daily.filter(pl.col("trade_date") == DAYS[7])["gross_return"][0] == pytest.approx(0.0)


def test_summarize_shapes() -> None:
    daily = pl.DataFrame(
        {
            "trade_date": DAYS[:4],
            "net_return": [0.01, -0.005, 0.0, 0.02],
            "turnover": [0.5, 0.0, 0.0, 0.0],
        }
    )
    m = summarize(daily)
    assert m["n_days"] == 4
    assert m["max_drawdown"] <= 0
    assert 0 < m["hit_rate"] <= 1
