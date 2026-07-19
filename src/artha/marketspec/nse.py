"""NSE cash-equity MarketSpec: India-calibrated delivery costs (plan section 6).

Rates are the plan's working numbers for a Zerodha-style discount broker and
sit on the verify-list (Appendix B) until confirmed against current
schedules; treat absolute levels as approximate, relative economics as
sound. All rates are fractions of traded notional.

- Brokerage: 0 (delivery).
- STT 0.1% both sides. Stamp duty 0.015% buy side only.
- Exchange transaction charge ~0.00297%, SEBI fee 0.0001%; GST 18% applies
  to those two (brokerage is zero).
- DP charge: ~Rs 15.34 flat per scrip per day on sells. Flat, so its bps
  impact depends on order size: modeled with a configurable typical order
  value (capital / positions), the plan's small-capital friction.
- Impact: cost_bps = a + b * sqrt(order_value / ADV_value), a=3, b=10,
  recalibrated against realized fills in Track B.
"""

import math
from dataclasses import dataclass
from typing import Final

from artha.data.calendar import TradingCalendar
from artha.marketspec.base import MarketSpec

STT: Final = 0.001
STAMP_BUY: Final = 0.00015
EXCHANGE_TXN: Final = 0.0000307  # NSE, verified zerodha.com/charges 2026-07-19
SEBI_FEE: Final = 0.000001
GST: Final = 0.18
DP_CHARGE_RS: Final = 15.34  # verified 2026-07-19 (3.5 CDSL + 9.5 Zerodha + GST)

IMPACT_A_BPS: Final = 3.0
IMPACT_B_BPS: Final = 10.0


@dataclass(frozen=True)
class NSECostModel:
    """Delivery-equity costs. ``dp_order_value`` is the typical sell order
    size in rupees used to convert the flat DP charge into a fraction; zero
    disables the DP term (paper accounting at scale)."""

    dp_order_value: float = 0.0
    impact_multiplier: float = 1.0

    def _charges(self, *, is_buy: bool) -> float:
        levies = EXCHANGE_TXN + SEBI_FEE
        base = STT + levies + GST * levies
        return base + (STAMP_BUY if is_buy else 0.0)

    def _impact(self, order_value: float, adv_value: float) -> float:
        if order_value <= 0 or adv_value <= 0:
            return 0.0
        bps = IMPACT_A_BPS + IMPACT_B_BPS * math.sqrt(order_value / adv_value)
        return self.impact_multiplier * bps / 10_000

    def buy_cost(self, order_value: float, adv_value: float) -> float:
        return self._charges(is_buy=True) + self._impact(order_value, adv_value)

    def sell_cost(self, order_value: float, adv_value: float) -> float:
        dp = DP_CHARGE_RS / self.dp_order_value if self.dp_order_value > 0 else 0.0
        return self._charges(is_buy=False) + dp + self._impact(order_value, adv_value)


def nse_spec(
    calendar: TradingCalendar, *, dp_order_value: float = 0.0, impact_multiplier: float = 1.0
) -> MarketSpec:
    return MarketSpec(
        name="NSE",
        currency="INR",
        calendar=calendar,
        settlement_lag_days=1,
        cost_model=NSECostModel(dp_order_value=dp_order_value, impact_multiplier=impact_multiplier),
    )
