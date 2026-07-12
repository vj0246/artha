"""Baseline factors on synthetic panels: values, windows, registry."""

from datetime import date, timedelta

import polars as pl
import pytest

from artha.features.baselines import (
    BASELINES,
    FEATURE_REGISTRY,
    low_vol_63d,
    momentum_12_1,
    reversal_5d,
)


def mk_panel(prices: dict[str, list[float]]) -> pl.DataFrame:
    rows = []
    for sym, series in prices.items():
        d = date(2020, 1, 1)
        for p in series:
            while d.weekday() >= 5:
                d += timedelta(days=1)
            rows.append({"canon_symbol": sym, "trade_date": d, "adj_close": p})
            d += timedelta(days=1)
    return pl.DataFrame(rows)


def test_registry_covers_baselines() -> None:
    assert set(BASELINES) == set(FEATURE_REGISTRY)
    assert all(s.knowable_at == "close[t]" for s in FEATURE_REGISTRY.values())


def test_reversal_value_and_window() -> None:
    # 6 days: return over the last 5 = 110/100 - 1 = 10%; reversal = -10%
    panel = mk_panel({"A": [100.0, 101.0, 102.0, 103.0, 104.0, 110.0]})
    scores = reversal_5d(panel)
    assert scores.height == 1  # only the last row has a full 5-day window
    assert scores["score"][0] == pytest.approx(-0.10)


def test_momentum_skips_last_month() -> None:
    # 253 days: 100 for 10 days, 200 for 222 days, crash to 50 in the last 21
    series = [100.0] * 10 + [200.0] * 222 + [50.0] * 21
    panel = mk_panel({"A": series})
    scores = momentum_12_1(panel)
    last = scores.row(scores.height - 1, named=True)
    # t-252 close is 100, t-21 close is 200; the recent crash is skipped
    assert last["score"] == pytest.approx(1.0)

    # a move entirely inside the last month scores zero
    inside = [100.0] * 232 + [400.0] * 21
    scores2 = momentum_12_1(mk_panel({"B": inside}))
    assert scores2.row(scores2.height - 1, named=True)["score"] == pytest.approx(0.0)


def test_low_vol_prefers_quiet_names() -> None:
    quiet = [100.0 + 0.01 * i for i in range(70)]
    wild = [100.0 * (1.05 if i % 2 else 0.95) ** 1 for i in range(70)]
    panel = mk_panel({"Q": quiet, "W": wild})
    scores = low_vol_63d(panel)
    last_day = scores["trade_date"].max()
    row = scores.filter(pl.col("trade_date") == last_day).sort("score", descending=True)
    assert row["canon_symbol"][0] == "Q"  # higher score = lower vol = preferred
