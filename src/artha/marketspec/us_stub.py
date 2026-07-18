"""US MarketSpec stub: the portability proof (plan section 15 item 4).

The entire market-specific surface for a US cash-equity backtest is this
file: T+1 settlement (post-May 2024), zero-commission retail with SEC
fee on sells, no STT/stamp/DP, same sqrt impact form. Strategy, universe,
construction, backtester, and engine code run unchanged.
"""

import math
from dataclasses import dataclass
from typing import Final

from artha.data.calendar import TradingCalendar
from artha.marketspec.base import MarketSpec

SEC_FEE_SELL: Final = 0.0000278  # approximate; verify before real use
IMPACT_A_BPS: Final = 1.0
IMPACT_B_BPS: Final = 8.0


@dataclass(frozen=True)
class USCostModel:
    def _impact(self, order_value: float, adv_value: float) -> float:
        if order_value <= 0 or adv_value <= 0:
            return 0.0
        return (IMPACT_A_BPS + IMPACT_B_BPS * math.sqrt(order_value / adv_value)) / 10_000

    def buy_cost(self, order_value: float, adv_value: float) -> float:
        return self._impact(order_value, adv_value)

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        return SEC_FEE_SELL + self._impact(order_value, adv_value)


def us_spec(calendar: TradingCalendar) -> MarketSpec:
    return MarketSpec(
        name="US",
        currency="USD",
        calendar=calendar,
        settlement_lag_days=1,
        cost_model=USCostModel(),
    )
