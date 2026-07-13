"""Deflated Sharpe ratio (Bailey & Lopez de Prado, 2014).

DSR = P[true SR > 0] after correcting the observed Sharpe for
non-normality and for the expected maximum Sharpe among N tried
strategies. Sharpe inputs here are per-period (daily); T is the sample
length in the same periods.
"""

import math

from scipy.stats import norm  # type: ignore[import-untyped]

_EULER_GAMMA = 0.5772156649015329


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """E[max SR] across ``n_trials`` under the null (SR=0), given the
    cross-trial variance of estimated Sharpes."""
    if n_trials <= 1:
        return 0.0
    z1 = norm.ppf(1 - 1.0 / n_trials)
    z2 = norm.ppf(1 - 1.0 / (n_trials * math.e))
    return float(math.sqrt(sr_variance) * ((1 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2))


def deflated_sharpe(
    sharpe: float,
    n_obs: int,
    *,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    n_trials: int = 1,
    sr_variance: float = 0.0,
) -> float:
    """Probability the true Sharpe exceeds the trials-adjusted benchmark."""
    sr0 = expected_max_sharpe(n_trials, sr_variance)
    denom = math.sqrt(1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2)
    if denom <= 0 or n_obs < 2:
        return 0.0
    z = (sharpe - sr0) * math.sqrt(n_obs - 1) / denom
    return float(norm.cdf(z))
