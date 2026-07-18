"""Ledgered accounting with T+1 sell-settlement (plan v1 section 9).

Buys consume settled cash immediately; sell proceeds settle the next
session (Indian T+1). Equity marks positions at the day's close plus all
cash (settled and unsettled).
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Ledger:
    cash: float  # settled, spendable
    unsettled: dict[date, float] = field(default_factory=dict)  # settle_date -> amount
    positions: dict[str, float] = field(default_factory=dict)  # symbol -> shares
    realized_pnl: float = 0.0
    charges: float = 0.0
    _avg_cost: dict[str, float] = field(default_factory=dict)

    def settle(self, today: date) -> None:
        for d in sorted(self.unsettled):
            if d <= today:
                self.cash += self.unsettled.pop(d)

    def buy(self, symbol: str, qty: float, price: float, cost: float) -> None:
        value = qty * price
        self.cash -= value + cost
        self.charges += cost
        held = self.positions.get(symbol, 0.0)
        total = held + qty
        self._avg_cost[symbol] = (
            (self._avg_cost.get(symbol, 0.0) * held + value) / total if total > 0 else 0.0
        )
        self.positions[symbol] = total

    def sell(self, symbol: str, qty: float, price: float, cost: float, settle_on: date) -> None:
        value = qty * price
        self.unsettled[settle_on] = self.unsettled.get(settle_on, 0.0) + value - cost
        self.charges += cost
        held = self.positions.get(symbol, 0.0)
        self.realized_pnl += (price - self._avg_cost.get(symbol, price)) * qty
        remaining = held - qty
        if remaining <= 1e-9:
            self.positions.pop(symbol, None)
            self._avg_cost.pop(symbol, None)
        else:
            self.positions[symbol] = remaining

    def equity(self, prices: dict[str, float]) -> float:
        held = sum(
            qty * prices.get(sym, self._avg_cost.get(sym, 0.0))
            for sym, qty in self.positions.items()
        )
        return self.cash + sum(self.unsettled.values()) + held
