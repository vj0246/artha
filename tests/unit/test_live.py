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


class TestAlertDurability:
    def test_alert_persists_to_jsonl_without_telegram(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        from artha.live.safety import alert

        monkeypatch.setenv("ARTHA_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        alert("book is on fire", severity="critical")
        alert("mild concern")

        path = tmp_path / "reports" / "paper" / "alerts.jsonl"
        rows = [_json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
        assert [r["severity"] for r in rows] == ["critical", "warning"]
        assert rows[0]["message"] == "book is on fire"
        assert rows[0]["at"].startswith("20")

    def test_alert_never_raises_when_data_dir_is_unwritable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from artha.live.safety import alert

        # data dir rooted under a FILE: mkdir cannot succeed, on any platform
        # (a NUL-byte path is not portable — POSIX setenv rejects it outright).
        # Alerting must degrade, never crash the runbook.
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv("ARTHA_DATA_DIR", str(blocker / "data"))
        alert("still must not raise")

    def test_freeze_records_a_critical_alert(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json as _json

        monkeypatch.setenv("ARTHA_DATA_DIR", str(tmp_path))
        KillSwitch(tmp_path / "FREEZE").freeze("reconcile mismatch")
        rows = [
            _json.loads(x)
            for x in (tmp_path / "reports" / "paper" / "alerts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if x
        ]
        assert rows[-1]["severity"] == "critical"
        assert "KILL SWITCH" in rows[-1]["message"]


class TestHeartbeatB1Clock:
    """The B1 gate is "30 CONSECUTIVE logged sessions". Reporting the raw
    row count instead let a clock with 18 holes advertise "16/30"."""

    @staticmethod
    def _heartbeat() -> object:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_heartbeat", Path("scripts/run_heartbeat.py")
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_streak_resets_at_every_gap(self) -> None:
        from datetime import date as _date

        mod = self._heartbeat()
        sessions = [_date(2026, 1, d) for d in (5, 6, 7, 8, 9, 12, 13)]
        logged = {_date(2026, 1, d) for d in (5, 6, 9, 12, 13)}
        # 5 rows logged, but the 7th/8th are holes: the gate sees 9-12-13
        assert mod.consecutive_streak(sessions, logged) == 3  # type: ignore[attr-defined]

    def test_streak_is_zero_when_the_latest_session_is_missed(self) -> None:
        from datetime import date as _date

        mod = self._heartbeat()
        sessions = [_date(2026, 1, d) for d in (5, 6, 7)]
        logged = {_date(2026, 1, 5), _date(2026, 1, 6)}
        assert mod.consecutive_streak(sessions, logged) == 0  # type: ignore[attr-defined]

    def test_streak_equals_length_when_nothing_is_missed(self) -> None:
        from datetime import date as _date

        mod = self._heartbeat()
        sessions = [_date(2026, 1, d) for d in (5, 6, 7)]
        assert mod.consecutive_streak(sessions, set(sessions)) == 3  # type: ignore[attr-defined]


class TestWeeklyReviewAnchor:
    """Regression (2026-09-12): the research replay was compounded from the
    first live date INCLUSIVE, charging a cash-only live book for a day of
    return it never earned — 0.73pp of the first week's -1.09% flag."""

    @staticmethod
    def _review() -> object:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_weekly_review", Path("scripts/run_weekly_review.py")
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_anchor_day_return_is_excluded(self) -> None:
        from datetime import date as _date

        import polars as pl

        daily = pl.DataFrame(
            {
                "trade_date": [_date(2026, 9, d) for d in (3, 4, 7, 8)],
                "net_return": [0.05, 0.10, 0.02, -0.01],
            }
        )
        fn = self._review().anchored_research_equity  # type: ignore[attr-defined]
        out = fn(daily, _date(2026, 9, 4), _date(2026, 9, 8), 100.0)
        equity = out["research_equity"].to_list()
        assert out.height == 3  # the day before lo is outside the window
        assert equity[0] == pytest.approx(100.0)  # lo's +10% is NOT credited
        assert equity[1] == pytest.approx(102.0)
        assert equity[2] == pytest.approx(102.0 * 0.99)
