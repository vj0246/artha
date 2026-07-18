"""Order model: NEW -> FILLED / REJECTED / EXPIRED (plan v1 section 9)."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class OrderStatus(Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str  # BUY / SELL
    quantity: float  # shares; fractional allowed in research mode
    created: date
    status: OrderStatus = OrderStatus.NEW
    fill_price: float | None = None
    fill_date: date | None = None
    cost: float = 0.0  # charges + impact, rupees
    reason: str = field(default="")

    def fill(self, price: float, day: date, cost: float) -> None:
        self.status = OrderStatus.FILLED
        self.fill_price = price
        self.fill_date = day
        self.cost = cost

    def reject(self, reason: str) -> None:
        self.status = OrderStatus.REJECTED
        self.reason = reason

    def expire(self, reason: str) -> None:
        self.status = OrderStatus.EXPIRED
        self.reason = reason
