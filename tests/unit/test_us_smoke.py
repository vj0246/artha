"""US portability smoke test (plan section 15 item 4): the same momentum
pipeline end to end on synthetic US data - only the MarketSpec changes."""

from datetime import date, timedelta

import numpy as np
import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.data.calendar import TradingCalendar
from artha.features.baselines import momentum_12_1
from artha.marketspec.us_stub import us_spec


def test_us_momentum_end_to_end() -> None:
    rng = np.random.default_rng(9)
    days: list[date] = []
    d = date(2022, 1, 3)
    while len(days) < 400:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    rows = []
    for i in range(20):
        drift = rng.normal(0.0002, 0.0004)  # cross-sectional drift dispersion
        price = 50.0 * float(rng.uniform(1, 8))
        for day in days:
            price *= float(np.exp(rng.normal(drift, 0.015)))
            rows.append(
                {
                    "canon_symbol": f"US{i:02d}",
                    "trade_date": day,
                    "adj_close": price,
                    "traded_value": float(rng.uniform(1e7, 1e9)),
                    "in_universe": True,
                }
            )
    panel = pl.DataFrame(rows)
    spec = us_spec(TradingCalendar(days))

    signal = momentum_12_1(panel)
    res = run_backtest(panel, signal, spec, top_n=5, capital=1_000_000.0)
    stats = summarize(res.daily)
    # smoke: it runs, trades, and produces sane numbers on a US spec
    assert stats["n_days"] == 400
    assert stats["turnover_oneway_ann"] > 0
    assert -1.0 < stats["cagr"] < 5.0
    assert spec.name == "US"
