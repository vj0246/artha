"""Event engine mechanics: settlement, halts, bands, integer shares."""

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

import polars as pl
import pytest

from artha.backtest.engine import EventEngine, OrderStatus
from artha.backtest.engine.accounting import Ledger
from artha.data.calendar import TradingCalendar
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


DAYS = weekdays_from(date(2024, 1, 1), 10)


def mk_panel(series: Mapping[str, Sequence[float | None]]) -> pl.DataFrame:
    rows = []
    for sym, prices in series.items():
        for d, p in zip(DAYS, prices, strict=True):
            if p is not None:
                rows.append(
                    {
                        "canon_symbol": sym,
                        "trade_date": d,
                        "adj_close": p,
                        "traded_value": 1e9,
                    }
                )
    return pl.DataFrame(rows)


def spec() -> MarketSpec:
    return MarketSpec("T", "INR", TradingCalendar(DAYS), 1, ZeroCost())


def targets(day: date, weights: dict[str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "rebalance_date": [day] * len(weights),
            "canon_symbol": list(weights),
            "weight": list(weights.values()),
        }
    )


class TestLedger:
    def test_t_plus_1_settlement(self) -> None:
        led = Ledger(cash=1000.0)
        led.buy("A", 10, 50.0, cost=5.0)
        assert led.cash == pytest.approx(495.0)
        led.sell("A", 10, 60.0, cost=6.0, settle_on=date(2024, 1, 3))
        assert led.cash == pytest.approx(495.0)  # proceeds unsettled
        assert led.equity({"A": 60.0}) == pytest.approx(495.0 + 594.0)
        led.settle(date(2024, 1, 3))
        assert led.cash == pytest.approx(1089.0)
        assert led.realized_pnl == pytest.approx(100.0)
        assert led.charges == pytest.approx(11.0)


class TestEngine:
    def test_integer_share_fill_and_equity(self) -> None:
        panel = mk_panel({"A": [100.0] * 10})
        engine = EventEngine(spec(), capital=10_050.0)
        res = engine.run(panel, targets(DAYS[0], {"A": 1.0}))
        fills = [o for o in res.orders if o.status == OrderStatus.FILLED]
        assert len(fills) == 1
        assert fills[0].quantity == 100  # floor(10050/100)
        assert res.daily["equity"][-1] == pytest.approx(10_050.0)

    def test_halt_carries_then_expires(self) -> None:
        # B trades day 0-1 then halts for the rest of the window
        panel = mk_panel({"A": [100.0] * 10, "B": [50.0, 50.0] + [None] * 8})
        engine = EventEngine(spec(), capital=10_000.0)
        res = engine.run(panel, targets(DAYS[1], {"B": 0.5, "A": 0.5}))
        b_orders = [o for o in res.orders if o.symbol == "B"]
        assert b_orders[0].status == OrderStatus.EXPIRED
        a_orders = [o for o in res.orders if o.symbol == "A"]
        assert a_orders[0].status == OrderStatus.FILLED

    def test_price_band_rejects_circuit_move(self) -> None:
        # A jumps +30% between rebalance close and execution close
        panel = mk_panel({"A": [100.0, 130.0] + [130.0] * 8})
        engine = EventEngine(spec(), capital=10_000.0)
        res = engine.run(panel, targets(DAYS[0], {"A": 1.0}))
        assert res.orders[0].status == OrderStatus.REJECTED
        assert "band" in res.orders[0].reason

    def test_sell_settles_next_session(self) -> None:
        panel = mk_panel({"A": [100.0] * 10})
        engine = EventEngine(spec(), capital=10_000.0)
        tgt = pl.concat([targets(DAYS[0], {"A": 1.0}), targets(DAYS[4], {"A": 0.0})])
        res = engine.run(panel, tgt)
        sells = [o for o in res.orders if o.side == "SELL"]
        assert sells
        assert sells[0].status == OrderStatus.FILLED
        # equity conserved through the round trip (zero costs, flat price)
        assert res.daily["equity"][-1] == pytest.approx(10_000.0)
