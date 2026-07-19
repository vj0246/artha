"""Kill switch, reconciliation, and alerts (plan v1 section 13.2).

- KillSwitch: a freeze file halts all trading; ``flatten`` sells every
  position. Auto-triggers on reconciliation mismatch or a daily PnL
  breach.
- reconcile: OMS book vs broker positions/cash; ANY mismatch halts.
- alert: Telegram when TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are set,
  stderr otherwise - alerting must never crash the runbook.
"""

import contextlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from artha.live.adapters.base import BrokerAdapter
from artha.live.oms import PlannedOrder, client_order_id

PNL_BREACH = -0.05  # daily loss that freezes trading
DERISK_DD = 0.10  # drawdown from peak that halves gross (plan section 11)
FLATTEN_DD = 0.15  # drawdown from peak that freezes trading


def drawdown_action(peak_equity: float, equity: float) -> tuple[float, bool]:
    """(gross scalar, freeze?) for the current drawdown from peak equity.

    Enforced by the runbook, not just reported: past DERISK_DD the target
    gross is halved; past FLATTEN_DD trading freezes (flatten stays a
    deliberate manual decision via the kill switch)."""
    dd = 0.0 if peak_equity <= 0 else equity / peak_equity - 1
    return (0.5 if dd <= -DERISK_DD else 1.0), dd <= -FLATTEN_DD


def alert(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    print(f"ALERT: {message}", file=sys.stderr)
    if token and chat:
        with contextlib.suppress(httpx.HTTPError):  # alerts must not kill the runbook
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": f"[artha] {message}"},
                timeout=10,
            )


@dataclass
class Mismatch:
    kind: str  # position / cash
    symbol: str
    expected: float
    actual: float


@dataclass
class ReconcileResult:
    mismatches: list[Mismatch] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def reconcile(
    expected_positions: dict[str, int],
    expected_cash: float,
    adapter: BrokerAdapter,
    *,
    cash_tolerance: float = 1.0,
) -> ReconcileResult:
    result = ReconcileResult()
    actual = adapter.positions()
    for symbol in set(expected_positions) | set(actual):
        e, a = expected_positions.get(symbol, 0), actual.get(symbol, 0)
        if e != a:
            result.mismatches.append(Mismatch("position", symbol, e, a))
    cash = adapter.cash()
    if abs(cash - expected_cash) > cash_tolerance:
        result.mismatches.append(Mismatch("cash", "", expected_cash, cash))
    return result


class KillSwitch:
    def __init__(self, freeze_path: Path) -> None:
        self.freeze_path = freeze_path

    @property
    def frozen(self) -> bool:
        return self.freeze_path.exists()

    def freeze(self, reason: str) -> None:
        self.freeze_path.parent.mkdir(parents=True, exist_ok=True)
        self.freeze_path.write_text(
            json.dumps({"reason": reason, "at": datetime.now(UTC).isoformat()}),
            encoding="utf-8",
        )
        alert(f"KILL SWITCH: trading frozen - {reason}")

    def unfreeze(self) -> None:
        self.freeze_path.unlink(missing_ok=True)

    def flatten(self, adapter: BrokerAdapter, day: object) -> None:
        """Sell everything, then freeze.

        Deliberately bypasses OMS pre-trade checks: the emergency exit must
        not be rejectable by the daily order-count cap, order-value cap, or
        a price band against a stale reference. Sells only, idempotent ids."""
        from datetime import date as _date

        assert isinstance(day, _date)
        for sym, qty in sorted(adapter.positions().items()):
            if qty > 0:
                order = PlannedOrder(sym, "SELL", qty)
                adapter.place_market_order(client_order_id(day, order), sym, "SELL", qty)
        self.freeze("flattened")
