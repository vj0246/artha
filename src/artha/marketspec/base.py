"""MarketSpec base contract (plan section 4, the subset P2 needs).

Fields arrive as later phases need them (price bands, lot sizes, session
times land with the event engine in Track B). Strategy code receives a
MarketSpec and never touches market facts directly.
"""

from dataclasses import dataclass
from typing import Protocol

from artha.data.calendar import TradingCalendar


class CostModel(Protocol):
    """Per-side trading costs, in fractions of traded notional."""

    def buy_cost(self, order_value: float, adv_value: float) -> float:
        """Total buy-side cost fraction (charges + impact) for one order."""
        ...

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        """Total sell-side cost fraction (charges + impact) for one order."""
        ...


@dataclass(frozen=True)
class MarketSpec:
    name: str
    currency: str
    calendar: TradingCalendar
    settlement_lag_days: int
    cost_model: CostModel
