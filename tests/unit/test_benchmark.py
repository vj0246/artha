"""Synthetic total-return benchmark math."""

from datetime import date

import polars as pl
import pytest

from artha.data.benchmark import TRADING_DAYS, synthetic_total_return


def test_synthetic_tr_adds_yield_drip() -> None:
    series = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
            "close": [1000.0, 1010.0, 1000.9],
            "div_yield": [1.26, 1.26, 1.26],  # percent, trailing
        }
    )
    out = synthetic_total_return(series)
    drip = 1.26 / 100 / TRADING_DAYS
    assert out["pr_return"][1] == pytest.approx(0.01)
    assert out["tr_return"][1] == pytest.approx(0.01 + drip)
    # TR index compounds from 1000 and beats PR when yield > 0
    assert out["tr_index"][2] > 1000.0 * (1000.9 / 1000.0)


def test_null_yield_treated_as_zero() -> None:
    series = pl.DataFrame(
        {
            "trade_date": [date(2024, 1, 1), date(2024, 1, 2)],
            "close": [100.0, 101.0],
            "div_yield": [None, None],
        },
        schema_overrides={"div_yield": pl.Float64},
    )
    out = synthetic_total_return(series)
    assert out["tr_return"][1] == pytest.approx(0.01)
