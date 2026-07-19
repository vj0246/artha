"""PSR, MinTRL, and Kupiec POF for the live readiness evaluation."""

import numpy as np
import pytest

from artha.risk.live_eval import (
    kupiec_pof,
    min_track_record_length,
    probabilistic_sharpe,
    sharpe_daily,
)


def _series(sr_daily: float, n: int, seed: int = 5) -> list[float]:
    rng = np.random.default_rng(seed)
    vol = 0.01
    return list(rng.normal(sr_daily * vol, vol, n))


def test_psr_monotone_in_sample_length() -> None:
    short = probabilistic_sharpe(_series(0.1, 60))
    long = probabilistic_sharpe(_series(0.1, 1000))
    assert long > short  # same true SR, more evidence -> more confidence
    assert long > 0.9


def test_psr_neutral_on_tiny_samples() -> None:
    assert probabilistic_sharpe([0.01, -0.01]) == 0.5


def test_psr_against_higher_benchmark_is_lower() -> None:
    rets = _series(0.05, 250)
    assert probabilistic_sharpe(rets, benchmark_sr=0.1) < probabilistic_sharpe(rets)


def test_mintrl_none_when_sr_below_benchmark() -> None:
    rets = _series(-0.05, 250)
    assert min_track_record_length(rets) is None


def test_mintrl_is_the_psr_95_crossing() -> None:
    # identity: at n = MinTRL with the same SR/skew/kurt, the PSR z-score
    # equals the 95% normal quantile
    from scipy.stats import norm

    from artha.risk.live_eval import _moments

    rets = _series(0.1, 2000, seed=3)
    mtrl = min_track_record_length(rets)
    assert mtrl is not None
    sr = sharpe_daily(rets)
    _, _, skew, kurt = _moments(rets)
    denom = (1 - skew * sr + (kurt - 1) / 4 * sr**2) ** 0.5
    z = sr * ((mtrl - 1) ** 0.5) / denom
    assert z == pytest.approx(float(norm.ppf(0.95)), abs=1e-9)


def test_kupiec_accepts_correct_rate() -> None:
    # 250 days, 5% VaR -> ~12.5 expected exceptions
    res = kupiec_pof(250, 13, 0.95)
    assert res["p_value"] > 0.5


def test_kupiec_rejects_too_many_exceptions() -> None:
    res = kupiec_pof(250, 30, 0.95)
    assert res["p_value"] < 0.01


def test_kupiec_rejects_too_few_exceptions() -> None:
    res = kupiec_pof(500, 2, 0.95)
    assert res["p_value"] < 0.05


def test_kupiec_boundary_zero_exceptions() -> None:
    res = kupiec_pof(100, 0, 0.95)
    assert res["lr"] > 0
    assert 0 <= res["p_value"] <= 1


def test_sharpe_daily_zero_vol() -> None:
    assert sharpe_daily([0.01, 0.01, 0.01]) == 0.0
