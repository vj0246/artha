"""Daily-bar event engine (Track B P7).

Timeline per session, mirroring the vectorized loop's assumptions exactly:

1. settle T+1 sell proceeds;
2. fill orders created at the PREVIOUS rebalance close at today's close
   (the T+1-close execution assumption), with halt and price-band
   handling: no bar today -> order carried, expiring after
   ``max_order_age`` sessions; fill price beyond +/-band vs previous
   close -> REJECTED (circuit);
3. mark equity at today's closes;
4. at a rebalance close, turn target weights into integer-share (or
   fractional, for parity testing) orders against current equity.

Same MarketSpec cost model as the research loop. The parity suite pins
the two engines against each other.
"""

import math
from dataclasses import dataclass
from datetime import date

import polars as pl

from artha.backtest.engine.accounting import Ledger
from artha.backtest.engine.orders import Order
from artha.marketspec.base import MarketSpec

ADV_WINDOW = 21
MAX_ORDER_AGE = 5  # sessions an unfilled (halted) order survives
PRICE_BAND = 0.20  # cash-equity circuit approximation


@dataclass(frozen=True)
class EngineResult:
    daily: pl.DataFrame  # trade_date, equity, cash, gross_exposure
    orders: list[Order]
    ledger: Ledger

    def daily_returns(self) -> pl.DataFrame:
        return self.daily.select(
            "trade_date",
            (pl.col("equity") / pl.col("equity").shift(1) - 1).alias("net_return"),
        ).drop_nulls()


class EventEngine:
    def __init__(
        self,
        spec: MarketSpec,
        *,
        capital: float,
        fractional: bool = False,
        exec_lag: int = 1,
    ) -> None:
        self.spec = spec
        self.capital = capital
        self.fractional = fractional
        self.exec_lag = exec_lag

    def run(self, panel: pl.DataFrame, targets: pl.DataFrame) -> EngineResult:
        """``panel``: canon_symbol, trade_date, adj_close, traded_value.
        ``targets``: rebalance_date, canon_symbol, weight (from the same
        signal/constructor pipeline the vectorized loop uses)."""
        px = panel.sort("canon_symbol", "trade_date").with_columns(
            pl.col("traded_value")
            .rolling_median(window_size=ADV_WINDOW, min_samples=1)
            .over("canon_symbol")
            .alias("adv_value")
        )
        bars = {
            d: dict(
                zip(
                    f["canon_symbol"], zip(f["adj_close"], f["adv_value"], strict=True), strict=True
                )
            )
            for (d,), f in px.partition_by("trade_date", as_dict=True).items()
        }
        target_map: dict[date, dict[str, float]] = {}
        for (d,), f in targets.partition_by("rebalance_date", as_dict=True).items():
            target_map[d] = dict(zip(f["canon_symbol"], f["weight"], strict=True))

        days = self.spec.calendar.days
        ledger = Ledger(cash=self.capital)
        all_orders: list[Order] = []
        pending: list[Order] = []
        queue: list[tuple[int, dict[str, float]]] = []  # (exec day index, weights)
        prev_close: dict[str, float] = {}
        daily_rows: list[dict[str, object]] = []
        order_seq = 0

        for i, day in enumerate(days):
            ledger.settle(day)
            bar = bars.get(day, {})

            # activate queued rebalances due today: create orders vs equity
            due = [q for q in queue if q[0] == i]
            queue = [q for q in queue if q[0] != i]
            for _, weights in due:
                marks = {s: bar.get(s, (prev_close.get(s, 0.0), 0.0))[0] for s in ledger.positions}
                equity = ledger.equity(marks)
                current_value = {s: q * marks.get(s, 0.0) for s, q in ledger.positions.items()}
                symbols = set(weights) | set(ledger.positions)
                orders: list[Order] = []
                for sym in symbols:
                    target_value = weights.get(sym, 0.0) * equity
                    delta = target_value - current_value.get(sym, 0.0)
                    price = bar.get(sym, (prev_close.get(sym, 0.0), 0.0))[0]
                    if price <= 0:
                        continue
                    qty = abs(delta) / price
                    if not self.fractional:
                        qty = float(math.floor(qty))
                    if qty <= 0:
                        continue
                    order_seq += 1
                    orders.append(
                        Order(
                            order_id=f"O{order_seq:06d}",
                            symbol=sym,
                            side="BUY" if delta > 0 else "SELL",
                            quantity=qty,
                            created=day,
                        )
                    )
                # sells first so settled cash exists for buys next session
                pending.extend(sorted(orders, key=lambda o: o.side, reverse=True))
                all_orders.extend(orders)

            # fill pending orders at today's close
            still_pending: list[Order] = []
            for order in pending:
                if order.symbol not in bar:
                    if (day - order.created).days > MAX_ORDER_AGE * 2:
                        order.expire("halted beyond max order age")
                    else:
                        still_pending.append(order)  # halt: carry
                    continue
                price, adv_value = bar[order.symbol]
                ref = prev_close.get(order.symbol)
                if ref and abs(price / ref - 1) > PRICE_BAND:
                    order.reject(f"price band: {price:.2f} vs prev {ref:.2f}")
                    continue
                value = order.quantity * price
                rate = (
                    self.spec.cost_model.buy_cost(value, adv_value)
                    if order.side == "BUY"
                    else self.spec.cost_model.sell_cost(value, adv_value)
                )
                cost = value * rate
                if order.side == "BUY":
                    ledger.buy(order.symbol, order.quantity, price, cost)
                else:
                    sell_qty = min(order.quantity, ledger.positions.get(order.symbol, 0.0))
                    if sell_qty <= 0:
                        order.reject("no position to sell")
                        continue
                    settle_idx = min(i + self.spec.settlement_lag_days, len(days) - 1)
                    ledger.sell(order.symbol, sell_qty, price, cost, days[settle_idx])
                order.fill(price, day, cost)
            pending = still_pending

            # mark, record, then queue any rebalance formed at today's close
            for sym, (price, _) in bar.items():
                prev_close[sym] = price
            marks = {s: prev_close.get(s, 0.0) for s in ledger.positions}
            equity = ledger.equity(marks)
            gross = sum(q * marks.get(s, 0.0) for s, q in ledger.positions.items())
            daily_rows.append(
                {
                    "trade_date": day,
                    "equity": equity,
                    "cash": ledger.cash + sum(ledger.unsettled.values()),
                    "gross_exposure": gross / equity if equity > 0 else 0.0,
                }
            )
            if day in target_map and i + self.exec_lag < len(days):
                queue.append((i + self.exec_lag, target_map[day]))

        for order in pending:  # anything never fillable expires with the run
            order.expire("unfilled at end of run")
        return EngineResult(daily=pl.DataFrame(daily_rows), orders=all_orders, ledger=ledger)
