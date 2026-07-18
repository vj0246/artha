"""Order management with pre-trade checks and idempotent submission
(plan v1 section 13.2).

Client order ids are deterministic (date + symbol + side + qty hash), so a
crashed and re-run daily job cannot double-submit: the adapter's order
history short-circuits duplicates, and the paper adapter enforces the same
contract.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date

from artha.live.adapters.base import BrokerAdapter, BrokerOrderResult

MAX_SINGLE_ORDER_VALUE = 1_000_000.0  # rupees
MAX_DAILY_ORDERS = 80
PRICE_BAND = 0.20


@dataclass(frozen=True)
class PlannedOrder:
    symbol: str
    side: str
    quantity: int


@dataclass
class OmsReport:
    submitted: list[tuple[PlannedOrder, BrokerOrderResult]] = field(default_factory=list)
    rejected_pretrade: list[tuple[PlannedOrder, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected_pretrade and all(r.status == "FILLED" for _, r in self.submitted)


def client_order_id(day: date, order: PlannedOrder) -> str:
    digest = hashlib.sha256(
        f"{day}:{order.symbol}:{order.side}:{order.quantity}".encode()
    ).hexdigest()[:12]
    return f"A{day:%Y%m%d}{digest}"


def plan_orders(
    targets: dict[str, float],
    positions: dict[str, int],
    quotes: dict[str, float],
    equity: float,
) -> list[PlannedOrder]:
    """Target weights -> integer-share market orders vs current positions."""
    orders: list[PlannedOrder] = []
    for symbol in sorted(set(targets) | set(positions)):
        price = quotes.get(symbol, 0.0)
        if price <= 0:
            continue
        target_qty = int(targets.get(symbol, 0.0) * equity / price)
        delta = target_qty - positions.get(symbol, 0)
        if delta:
            orders.append(PlannedOrder(symbol, "BUY" if delta > 0 else "SELL", abs(delta)))
    # sells first: their (T+1) proceeds fund the buys
    return sorted(orders, key=lambda o: o.side, reverse=True)


class Oms:
    def __init__(
        self,
        adapter: BrokerAdapter,
        *,
        max_gross: float = 1.0,
        reference_prices: dict[str, float] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.adapter = adapter
        self.max_gross = max_gross
        self.reference_prices = reference_prices or {}
        self.dry_run = dry_run

    def _pretrade(self, order: PlannedOrder, quote: float, equity: float) -> str | None:
        value = order.quantity * quote
        if value > MAX_SINGLE_ORDER_VALUE:
            return f"order value {value:,.0f} exceeds cap"
        ref = self.reference_prices.get(order.symbol)
        if ref and abs(quote / ref - 1) > PRICE_BAND:
            return f"quote {quote:.2f} outside band vs reference {ref:.2f}"
        if order.side == "BUY" and value > equity * self.max_gross:
            return "buy exceeds max gross"
        return None

    def execute(self, day: date, orders: list[PlannedOrder]) -> OmsReport:
        report = OmsReport()
        if len(orders) > MAX_DAILY_ORDERS:
            for order in orders:
                report.rejected_pretrade.append((order, "daily order count exceeded"))
            return report
        equity = self.adapter.cash() + sum(
            qty * self.adapter.get_quote(sym) for sym, qty in self.adapter.positions().items()
        )
        history = self.adapter.order_history()
        for order in orders:
            quote = self.adapter.get_quote(order.symbol)
            reason = self._pretrade(order, quote, equity)
            if reason:
                report.rejected_pretrade.append((order, reason))
                continue
            coid = client_order_id(day, order)
            if coid in history:  # already submitted by a previous run today
                report.submitted.append((order, history[coid]))
                continue
            if self.dry_run:
                report.submitted.append(
                    (order, BrokerOrderResult(coid, "FILLED", fill_price=quote, reason="dry-run"))
                )
                continue
            report.submitted.append(
                (
                    order,
                    self.adapter.place_market_order(coid, order.symbol, order.side, order.quantity),
                )
            )
        return report
