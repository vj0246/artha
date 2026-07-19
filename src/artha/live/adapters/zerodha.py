"""Zerodha Kite Connect adapter (plan v1 section 13.1-13.2).

Key-gated: requires KITE_API_KEY and KITE_ACCESS_TOKEN in the environment
(access tokens expire daily; the runbook's manual login step refreshes
them - automation is a ToS question, deliberately not attempted here).
The kiteconnect import is deferred so the rest of the live layer works
without the dependency installed.

UNTESTED against a real account until credentials exist; the paper
adapter carries the 6-week gate.
"""

import os
from typing import Any

from artha.live.adapters.base import BrokerOrderResult


class KiteAdapter:
    def __init__(self) -> None:
        api_key = os.environ.get("KITE_API_KEY", "")
        access_token = os.environ.get("KITE_ACCESS_TOKEN", "")
        if not api_key or not access_token:
            raise RuntimeError("KITE_API_KEY / KITE_ACCESS_TOKEN not set; use PaperBroker instead")
        try:
            from kiteconnect import KiteConnect  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install kiteconnect to use the Zerodha adapter") from exc
        self._kite: Any = KiteConnect(api_key=api_key)
        self._kite.set_access_token(access_token)

    def get_quote(self, symbol: str) -> float:
        data = self._kite.ltp(f"NSE:{symbol}")
        return float(data[f"NSE:{symbol}"]["last_price"])

    def ltp_many(self, symbols: list[str]) -> dict[str, float]:
        """Batch last-traded prices; missing/suspended symbols are absent."""
        out: dict[str, float] = {}
        for i in range(0, len(symbols), 400):  # kite quote API batch limit
            keys = [f"NSE:{s}" for s in symbols[i : i + 400]]
            data = self._kite.ltp(keys)
            for key, value in data.items():
                out[key.split(":", 1)[1]] = float(value["last_price"])
        return out

    def place_market_order(
        self, client_order_id: str, symbol: str, side: str, quantity: int
    ) -> BrokerOrderResult:
        order_id = self._kite.place_order(
            variety="regular",
            exchange="NSE",
            tradingsymbol=symbol,
            transaction_type=side,
            quantity=quantity,
            product="CNC",
            order_type="MARKET",
            tag=client_order_id[:20],  # kite tag limit
        )
        return BrokerOrderResult(str(order_id), "FILLED")  # reconcile verifies

    def positions(self) -> dict[str, int]:
        holdings = self._kite.holdings()
        return {h["tradingsymbol"]: int(h["quantity"]) for h in holdings if h["quantity"]}

    def cash(self) -> float:
        margins = self._kite.margins()
        return float(margins["equity"]["available"]["cash"])

    def order_history(self) -> dict[str, BrokerOrderResult]:
        out: dict[str, BrokerOrderResult] = {}
        for order in self._kite.orders():
            tag = order.get("tag") or ""
            if tag:
                out[tag] = BrokerOrderResult(
                    str(order["order_id"]),
                    "FILLED" if order["status"] == "COMPLETE" else order["status"],
                    fill_price=float(order.get("average_price") or 0) or None,
                )
        return out
