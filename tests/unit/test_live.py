"""Live layer: paper fills, OMS checks + idempotency, reconcile, kill switch."""

from datetime import date
from pathlib import Path

import pytest

from artha.live.adapters.paper import PaperBroker
from artha.live.oms import MAX_SINGLE_ORDER_VALUE, Oms, PlannedOrder, client_order_id, plan_orders
from artha.live.safety import KillSwitch, reconcile


class FlatCost:
    def buy_cost(self, order_value: float, adv_value: float) -> float:
        return 0.01

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        return 0.01


QUOTES = {"A": 100.0, "B": 50.0}
DAY = date(2026, 7, 18)


def broker(tmp_path: Path, cash: float = 100_000.0) -> PaperBroker:
    return PaperBroker(tmp_path / "state.json", QUOTES, FlatCost(), starting_cash=cash)


class TestPaperBroker:
    def test_fill_costs_and_persistence(self, tmp_path: Path) -> None:
        b = broker(tmp_path)
        res = b.place_market_order("C1", "A", "BUY", 100)
        assert res.status == "FILLED"
        assert b.cash() == pytest.approx(100_000 - 10_000 - 100)  # 1% cost
        assert b.positions() == {"A": 100}
        # a fresh instance reloads the same book
        b2 = broker(tmp_path)
        assert b2.positions() == {"A": 100}
        assert b2.order_history()["C1"].status == "FILLED"

    def test_idempotent_resubmission(self, tmp_path: Path) -> None:
        b = broker(tmp_path)
        b.place_market_order("C1", "A", "BUY", 10)
        cash_after = b.cash()
        b.place_market_order("C1", "A", "BUY", 10)  # crash-rerun: no double fill
        assert b.cash() == cash_after
        assert b.positions() == {"A": 10}

    def test_rejects(self, tmp_path: Path) -> None:
        b = broker(tmp_path, cash=500.0)
        assert b.place_market_order("C1", "A", "BUY", 100).status == "REJECTED"
        assert b.place_market_order("C2", "A", "SELL", 5).status == "REJECTED"
        assert b.place_market_order("C3", "ZZZ", "BUY", 1).status == "REJECTED"


class TestOms:
    def test_plan_orders_sells_first(self) -> None:
        orders = plan_orders({"A": 0.5}, {"B": 100}, {"A": 100.0, "B": 50.0}, equity=100_000.0)
        assert [o.side for o in orders] == ["SELL", "BUY"]
        assert orders[1] == PlannedOrder("A", "BUY", 500)

    def test_pretrade_value_cap_and_band(self, tmp_path: Path) -> None:
        b = broker(tmp_path, cash=10_000_000.0)
        oms = Oms(b, reference_prices={"A": 70.0})  # quote 100 vs ref 70: 43% off
        report = oms.execute(
            DAY,
            [
                PlannedOrder("A", "BUY", 10),  # band reject
                PlannedOrder("B", "BUY", int(MAX_SINGLE_ORDER_VALUE / 50) + 10),  # value cap
            ],
        )
        assert len(report.rejected_pretrade) == 2
        assert not report.ok

    def test_dry_run_and_idempotent_ids(self, tmp_path: Path) -> None:
        b = broker(tmp_path)
        oms = Oms(b, reference_prices=QUOTES, dry_run=True)
        report = oms.execute(DAY, [PlannedOrder("A", "BUY", 10)])
        assert report.ok
        assert b.positions() == {}  # nothing actually traded
        assert client_order_id(DAY, PlannedOrder("A", "BUY", 10)) == client_order_id(
            DAY, PlannedOrder("A", "BUY", 10)
        )


class TestSafety:
    def test_reconcile_detects_mismatch(self, tmp_path: Path) -> None:
        b = broker(tmp_path)
        b.place_market_order("C1", "A", "BUY", 10)
        ok = reconcile(b.positions(), b.cash(), b)
        assert ok.ok
        bad = reconcile({"A": 99}, b.cash(), b)
        assert not bad.ok
        assert bad.mismatches[0].kind == "position"

    def test_kill_switch_freeze_and_flatten(self, tmp_path: Path) -> None:
        b = broker(tmp_path)
        b.place_market_order("C1", "A", "BUY", 10)
        kill = KillSwitch(tmp_path / "FREEZE")
        assert not kill.frozen
        kill.flatten(b, DAY)
        assert kill.frozen
        assert b.positions() == {}
        kill.unfreeze()
        assert not kill.frozen


class TestDrawdownAction:
    def test_normal_book_untouched(self) -> None:
        from artha.live.safety import drawdown_action

        scalar, freeze = drawdown_action(100.0, 95.0)
        assert scalar == 1.0
        assert not freeze

    def test_derisk_halves_gross(self) -> None:
        from artha.live.safety import drawdown_action

        scalar, freeze = drawdown_action(100.0, 89.0)
        assert scalar == 0.5
        assert not freeze

    def test_flatten_threshold_freezes(self) -> None:
        from artha.live.safety import drawdown_action

        scalar, freeze = drawdown_action(100.0, 84.0)
        assert scalar == 0.5
        assert freeze

    def test_zero_peak_is_safe(self) -> None:
        from artha.live.safety import drawdown_action

        assert drawdown_action(0.0, 0.0) == (1.0, False)


class TestFlattenBypassesPretrade:
    def test_flatten_exceeding_daily_order_cap_still_sells_all(self, tmp_path: Path) -> None:
        from artha.live.oms import MAX_DAILY_ORDERS

        n = MAX_DAILY_ORDERS + 5
        quotes = {f"S{i:03d}": 100.0 for i in range(n)}
        b = PaperBroker(tmp_path / "s.json", quotes, FlatCost(), starting_cash=n * 200.0)
        for i in range(n):
            b.place_market_order(f"seed{i}", f"S{i:03d}", "BUY", 1)
        assert len(b.positions()) == n

        kill = KillSwitch(tmp_path / "FREEZE")
        kill.flatten(b, DAY)
        assert b.positions() == {}
        assert kill.frozen
