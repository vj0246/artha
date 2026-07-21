"""Event-driven engine (plan v1 section 9, Track B P7).  The same engine
consumes historical bars in backtests and live events in paper/real
trading; the parity suite pins its agreement with the vectorized research
loop.
"""

from artha.backtest.engine.engine import EngineResult, EventEngine
from artha.backtest.engine.orders import Order, OrderStatus

__all__ = ["EngineResult", "EventEngine", "Order", "OrderStatus"]
