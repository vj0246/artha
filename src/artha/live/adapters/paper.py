"""Paper broker: simulates fills against supplied quotes with the same
slippage assumptions as the engine (plan v1 section 13.2).

Quotes come from a dict the daily runbook loads (EOD closes in v1; the
Kite websocket later). State persists to a JSON file so consecutive daily
runs share one book.
"""

import json
from pathlib import Path

from artha.live.adapters.base import BrokerOrderResult
from artha.marketspec.base import CostModel


class PaperBroker:
    def __init__(
        self,
        state_path: Path,
        quotes: dict[str, float],
        cost_model: CostModel,
        *,
        starting_cash: float,
        adv: dict[str, float] | None = None,
    ) -> None:
        self.state_path = state_path
        self.quotes = quotes
        self.cost_model = cost_model
        self.adv = adv or {}
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self._cash: float = state["cash"]
            self._positions: dict[str, int] = {k: int(v) for k, v in state["positions"].items()}
            self._orders: dict[str, BrokerOrderResult] = {
                k: BrokerOrderResult(**v) for k, v in state["orders"].items()
            }
        else:
            self._cash = starting_cash
            self._positions = {}
            self._orders = {}

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "cash": self._cash,
                    "positions": self._positions,
                    "orders": {k: v.__dict__ for k, v in self._orders.items()},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def get_quote(self, symbol: str) -> float:
        if symbol not in self.quotes:
            raise KeyError(f"no quote for {symbol}")
        return self.quotes[symbol]

    def place_market_order(
        self, client_order_id: str, symbol: str, side: str, quantity: int
    ) -> BrokerOrderResult:
        if client_order_id in self._orders:  # idempotent resubmission
            return self._orders[client_order_id]
        try:
            price = self.get_quote(symbol)
        except KeyError:
            result = BrokerOrderResult(client_order_id, "REJECTED", reason="no quote")
            self._orders[client_order_id] = result
            self._save()
            return result
        value = quantity * price
        rate = (
            self.cost_model.buy_cost(value, self.adv.get(symbol, 0.0))
            if side == "BUY"
            else self.cost_model.sell_cost(value, self.adv.get(symbol, 0.0))
        )
        cost = value * rate
        if side == "BUY":
            if value + cost > self._cash:
                result = BrokerOrderResult(client_order_id, "REJECTED", reason="insufficient cash")
                self._orders[client_order_id] = result
                self._save()
                return result
            self._cash -= value + cost
            self._positions[symbol] = self._positions.get(symbol, 0) + quantity
        else:
            held = self._positions.get(symbol, 0)
            if quantity > held:
                result = BrokerOrderResult(
                    client_order_id, "REJECTED", reason=f"holding {held} < {quantity}"
                )
                self._orders[client_order_id] = result
                self._save()
                return result
            self._cash += value - cost
            remaining = held - quantity
            if remaining:
                self._positions[symbol] = remaining
            else:
                self._positions.pop(symbol)
        result = BrokerOrderResult(client_order_id, "FILLED", fill_price=price)
        self._orders[client_order_id] = result
        self._save()
        return result

    def positions(self) -> dict[str, int]:
        return dict(self._positions)

    def cash(self) -> float:
        return self._cash

    def order_history(self) -> dict[str, BrokerOrderResult]:
        return dict(self._orders)
