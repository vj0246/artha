"""Risk analytics: VaR/CVaR, Sortino/Calmar, drawdown states, liquidity."""

from datetime import date, timedelta
from typing import cast

import numpy as np
import polars as pl
import pytest

from artha.risk.analytics import (
    calmar,
    days_to_liquidate,
    drawdown_state,
    rolling_sharpe,
    sortino,
    var_report,
    worst_windows,
)


def mk_daily(returns: list[float]) -> pl.DataFrame:
    d0 = date(2024, 1, 1)
    return pl.DataFrame(
        {
            "trade_date": [d0 + timedelta(days=i) for i in range(len(returns))],
            "net_return": returns,
        }
    )


def test_var_normal_sanity() -> None:
    rng = np.random.default_rng(4)
    r = pl.Series(rng.normal(0.0, 0.01, 5000))
    rep = var_report(r)
    # ~N(0, 1%): VaR95 ~ 1.65%, VaR99 ~ 2.33%; CF close to historical
    assert rep.hist_var_95 == pytest.approx(0.0165, abs=0.002)
    assert rep.hist_var_99 == pytest.approx(0.0233, abs=0.003)
    assert rep.hist_cvar_95 > rep.hist_var_95
    assert rep.cf_var_95 == pytest.approx(rep.hist_var_95, abs=0.002)


def test_sortino_and_calmar() -> None:
    r = pl.Series([0.01, -0.01, 0.01, -0.01] * 50)
    assert sortino(r) == pytest.approx(0.0, abs=0.15)
    assert calmar(0.15, -0.30) == pytest.approx(0.5)


def test_drawdown_states() -> None:
    # crash 20% then flat
    returns = [0.0] * 5 + [-0.05, -0.05, -0.05, -0.05] + [0.0] * 5
    states = drawdown_state(mk_daily(returns))
    assert states["derisk_state"][0] == "normal"
    assert "half_gross" in states["derisk_state"].to_list()
    assert states["derisk_state"][-1] == "flat"
    assert float(cast(float, states["drawdown"].min())) == pytest.approx(0.95**4 - 1, abs=1e-9)


def test_worst_windows_and_rolling_sharpe() -> None:
    returns = [0.001] * 300
    returns[100:105] = [-0.03] * 5
    daily = mk_daily(returns)
    worst = worst_windows(daily, window=21, n=1)
    assert worst["window_return"][0] < -0.10
    rs = rolling_sharpe(daily, window=252)
    assert rs.height == 300 - 251


def test_days_to_liquidate() -> None:
    holdings = pl.DataFrame(
        {
            "rebalance_date": [date(2024, 1, 5)] * 2,
            "canon_symbol": ["BIG", "SMALL"],
            "weight": [0.05, 0.05],
        }
    )
    adv = pl.DataFrame({"canon_symbol": ["BIG", "SMALL"], "adv_value": [1e9, 1e6]})
    out = days_to_liquidate(holdings, adv, capital=1e8, participation=0.2)
    small = out.filter(pl.col("canon_symbol") == "SMALL")["days_to_liquidate"][0]
    big = out.filter(pl.col("canon_symbol") == "BIG")["days_to_liquidate"][0]
    assert small == pytest.approx(25.0)  # 5e6 position / (1e6 * 0.2)
    assert big == pytest.approx(0.025)
