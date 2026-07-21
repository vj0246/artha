"""MarketSpec: the portability contract (plan section 4). All market-specific
facts live here; strategy and backtest code never hardcode them.
"""

from artha.marketspec.base import CostModel, MarketSpec
from artha.marketspec.nse import NSECostModel, nse_spec

__all__ = ["CostModel", "MarketSpec", "NSECostModel", "nse_spec"]
