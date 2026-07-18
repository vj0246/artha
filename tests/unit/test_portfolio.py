"""Portfolio construction: caps, bands, vol targeting, verification."""

from datetime import date, timedelta

import polars as pl
import pytest

from artha.backtest.vectorized import run_backtest
from artha.data.calendar import TradingCalendar
from artha.marketspec.base import MarketSpec
from artha.portfolio.construct import ConstraintReport, Constructor


class ZeroCost:
    def buy_cost(self, order_value: float, adv_value: float) -> float:
        return 0.0

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        return 0.0


def ranked(n: int, adv: float = 1e12) -> list[tuple[str, float]]:
    return [(f"S{i}", adv) for i in range(n)]


class TestConstructor:
    def test_position_cap_binds(self) -> None:
        c = Constructor(top_n=10, position_cap=0.06)
        report = ConstraintReport()
        w = c.build(ranked(10), {}, None, report)
        # base weight 10% clipped to 6%; gross 60%, rest cash
        assert all(x == pytest.approx(0.06) for x in w.values())
        assert sum(w.values()) == pytest.approx(0.6)
        assert report.violations == []

    def test_sector_cap_binds(self) -> None:
        sectors = {f"S{i}": ("FIN" if i < 20 else "IT") for i in range(25)}
        c = Constructor(top_n=25, position_cap=0.06, sector_cap=0.25, sector_map=sectors)
        report = ConstraintReport()
        w = c.build(ranked(25), {}, None, report)
        fin = sum(x for s, x in w.items() if sectors[s] == "FIN")
        assert fin == pytest.approx(0.25, abs=1e-6)
        assert report.violations == []

    def test_no_trade_band_holds_small_deltas(self) -> None:
        c = Constructor(top_n=2, position_cap=0.5, no_trade_band=0.25)
        report = ConstraintReport()
        prior = {"S0": 0.45, "S1": 0.55}  # both within 25% of the 0.5 target
        w = c.build(ranked(2), prior, None, report)
        assert w["S0"] == pytest.approx(0.45)
        assert w["S1"] == pytest.approx(0.55)
        # a large deviation trades back to target (S1 held exactly at target)
        w2 = c.build(ranked(2), {"S0": 0.10, "S1": 0.5}, None, report)
        assert w2["S0"] == pytest.approx(0.5)
        assert w2["S1"] == pytest.approx(0.5)

    def test_vol_targeting_scales_gross(self) -> None:
        c = Constructor(top_n=4, position_cap=0.30, target_vol=0.12)
        report = ConstraintReport()
        w = c.build(ranked(4), {}, 0.24, report)  # running hot: halve gross
        assert sum(w.values()) == pytest.approx(0.5)
        w_cold = c.build(ranked(4), {}, 0.06, report)  # cold: clamp at 1, no leverage
        assert sum(w_cold.values()) == pytest.approx(1.0)

    def test_adv_participation_caps_move(self) -> None:
        # capital 1cr, ADV 1cr, participation 2% -> max move 2% of book
        c = Constructor(top_n=1, position_cap=1.0, capital=1e7, no_trade_band=0.0)
        report = ConstraintReport()
        w = c.build([("S0", 1e7)], {}, None, report)
        assert w["S0"] == pytest.approx(0.02)
        w2 = c.build([("S0", 1e7)], {"S0": 0.02}, None, report)
        assert w2["S0"] == pytest.approx(0.04)

    def test_verification_flags_violation(self) -> None:
        report = ConstraintReport()
        c = Constructor(position_cap=0.06)
        c._verify({"X": 0.20}, report)
        assert any("position cap" in v for v in report.violations)


def weekdays_from(start: date, n: int) -> list[date]:
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def test_backtest_with_constructor_keeps_cash() -> None:
    days = weekdays_from(date(2024, 1, 1), 10)
    rows = []
    for sym, series in {"A": [100.0] * 6 + [110.0] * 4, "B": [100.0] * 10}.items():
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
    signal = pl.DataFrame(
        {"canon_symbol": ["A", "B"], "trade_date": [days[4]] * 2, "score": [2.0, 1.0]}
    )
    spec = MarketSpec("T", "INR", TradingCalendar(days), 1, ZeroCost())
    report = ConstraintReport()
    constructor = Constructor(top_n=2, position_cap=0.10)
    res = run_backtest(panel, signal, spec, constructor=constructor, report=report)
    # 2 names x 10% cap = 20% gross; A jumps 10% between day 5 and 6 closes
    jump = res.daily.filter(pl.col("trade_date") == days[6])["gross_return"][0]
    assert jump == pytest.approx(0.10 * 0.10)  # 10% weight x 10% move
    assert report.violations == []
    # target book is 20% gross with 80% cash, not renormalized to 100%
    target = res.holdings.filter(pl.col("rebalance_date") == days[4])
    assert target["weight"].sum() == pytest.approx(0.2)
