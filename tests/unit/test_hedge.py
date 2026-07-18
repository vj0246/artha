"""Futures ingest helpers and the beta hedge overlay."""

from datetime import date, timedelta
from typing import cast

import numpy as np
import polars as pl
import pytest

from artha.data.ingest.fo import fo_filename, fo_url, front_month_series
from artha.portfolio.hedge import hedged_returns, rolling_beta


def test_fo_naming_across_cutover() -> None:
    assert fo_filename(date(2023, 1, 2)) == "fo02JAN2023bhav.csv.zip"
    assert "DERIVATIVES/2023/JAN/" in fo_url(date(2023, 1, 2))
    assert fo_filename(date(2024, 7, 5)) == "BhavCopy_NSE_FO_0_0_0_20240705_F_0000.csv.zip"
    assert "/content/fo/" in fo_url(date(2024, 7, 5))


def test_front_month_rolls_without_jump() -> None:
    d = [date(2024, 1, 22), date(2024, 1, 23), date(2024, 1, 24), date(2024, 1, 25)]
    jan_exp, feb_exp = date(2024, 1, 25), date(2024, 2, 29)
    futures = pl.DataFrame(
        {
            "trade_date": d + d,
            "expiry": [jan_exp] * 4 + [feb_exp] * 4,
            "settle": [100.0, 101.0, 102.0, 103.0, 110.0, 111.0, 112.0, 113.0],
            "open_interest": [1.0] * 8,
        }
    )
    fm = front_month_series(futures)
    # front month is Jan through the 25th (expiry >= date), Feb after
    assert fm.filter(pl.col("trade_date") == d[3])["expiry"][0] == jan_exp
    # every return is same-contract: no +7% roll artifact anywhere
    assert cast(float, fm["fut_return"].abs().max()) < 0.02


def test_rolling_beta_recovers_planted_beta() -> None:
    rng = np.random.default_rng(2)
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(200)]
    fut = rng.normal(0, 0.01, 200)
    strat = 0.6 * fut + rng.normal(0, 0.002, 200)
    strategy = pl.DataFrame({"trade_date": days, "net_return": strat})
    futures = pl.DataFrame({"trade_date": days, "fut_return": fut})
    betas = rolling_beta(strategy, futures)
    assert betas["beta"].tail(50).mean() == pytest.approx(0.6, abs=0.05)

    hedged = hedged_returns(strategy, futures)
    # hedging a 0.6-beta book against its own factor kills most variance
    raw_vol = float(np.std(strat))
    hedged_vol = cast(float, hedged["hedged_return"].std())
    assert hedged_vol < 0.5 * raw_vol
    # residual beta of the hedged series ~ 0
    resid = rolling_beta(
        hedged.select("trade_date", pl.col("hedged_return").alias("net_return")), futures
    )
    assert abs(cast(float, resid["beta"].tail(50).mean())) < 0.1
