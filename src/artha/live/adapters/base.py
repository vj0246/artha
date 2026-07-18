"""Broker adapter contract (plan v1 section 13.2).

Every implementation - paper or real - exposes the same five operations;
the OMS never knows which one it is talking to. Quantities are integer
shares, prices rupees.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BrokerOrderResult:
    broker_order_id: str
    status: str  # FILLED / REJECTED (EOD flow: no resting orders in v1)
    fill_price: float | None = None
    reason: str = ""


class BrokerAdapter(Protocol):
    def get_quote(self, symbol: str) -> float:
        """Last traded / reference price."""
        ...

    def place_market_order(
        self, client_order_id: str, symbol: str, side: str, quantity: int
    ) -> BrokerOrderResult: ...

    def positions(self) -> dict[str, int]:
        """symbol -> net quantity held at the broker."""
        ...

    def cash(self) -> float:
        """Available cash/margin."""
        ...

    def order_history(self) -> dict[str, BrokerOrderResult]:
        """client_order_id -> result, for idempotency checks."""
        ...
