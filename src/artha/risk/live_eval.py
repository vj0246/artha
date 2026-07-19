"""Live-evidence statistics for the go-live evaluation (Track B B3).

Small live samples lie. These are the standard tools for saying exactly
how much a short live track record can and cannot support:

- Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012): probability
  that the true Sharpe exceeds a benchmark, adjusting for sample length,
  skew, and kurtosis of the return series.
- Minimum Track Record Length: sessions needed before PSR clears a
  confidence bar — the honest answer to "how long until the live numbers
  mean anything?"
- Kupiec (1995) proportion-of-failures test: are VaR exceptions arriving
  at the modeled rate? Both too many (risk understated) and too few
  (model too loose to bind) are findings.

All Sharpe inputs are per-period (daily); annualization is presentation.
"""

import math

from scipy.stats import chi2, norm


def _moments(returns: list[float]) -> tuple[float, float, float, float]:
    n = len(returns)
    mean = sum(returns) / n
    var = sum((x - mean) ** 2 for x in returns) / (n - 1)
    std = math.sqrt(var)
    if std == 0:
        return mean, 0.0, 0.0, 3.0
    skew = sum(((x - mean) / std) ** 3 for x in returns) / n
    kurt = sum(((x - mean) / std) ** 4 for x in returns) / n
    return mean, std, skew, kurt


def sharpe_daily(returns: list[float]) -> float:
    mean, std, _, _ = _moments(returns)
    return mean / std if std > 0 else 0.0


def probabilistic_sharpe(returns: list[float], *, benchmark_sr: float = 0.0) -> float:
    """P(true SR > benchmark_sr) given the observed series (daily SR units)."""
    n = len(returns)
    if n < 3:
        return 0.5
    sr = sharpe_daily(returns)
    _, _, skew, kurt = _moments(returns)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr**2))
    z = (sr - benchmark_sr) * math.sqrt(n - 1) / denom
    return float(norm.cdf(z))


def min_track_record_length(
    returns: list[float], *, benchmark_sr: float = 0.0, confidence: float = 0.95
) -> float | None:
    """Sessions needed for PSR >= confidence at the OBSERVED SR/skew/kurt.

    None when the observed SR does not exceed the benchmark (no sample
    length can ever clear the bar in that direction)."""
    if len(returns) < 3:
        return None
    sr = sharpe_daily(returns)
    if sr <= benchmark_sr:
        return None
    _, _, skew, kurt = _moments(returns)
    z = float(norm.ppf(confidence))
    return 1 + (1 - skew * sr + (kurt - 1) / 4 * sr**2) * (z / (sr - benchmark_sr)) ** 2


def kupiec_pof(n_obs: int, n_exceptions: int, var_level: float = 0.95) -> dict[str, float]:
    """Kupiec proportion-of-failures likelihood ratio for VaR exceptions.

    Returns the LR statistic and p-value (chi-squared, 1 dof); p < 0.05
    rejects the VaR model. Degenerate inputs return p=1 (no evidence)."""
    p = 1 - var_level
    if n_obs == 0:
        return {"lr": 0.0, "p_value": 1.0, "expected": 0.0, "observed": 0}
    x = n_exceptions
    rate = x / n_obs
    if x in (0, n_obs):
        # boundary: the observed-rate likelihood term is exactly 0
        lr = -2 * ((n_obs - x) * math.log(1 - p) + x * math.log(p))
    else:
        lr = -2 * ((n_obs - x) * math.log((1 - p) / (1 - rate)) + x * math.log(p / rate))
    lr = max(0.0, lr)
    return {
        "lr": lr,
        "p_value": float(chi2.sf(lr, df=1)),
        "expected": p * n_obs,
        "observed": x,
    }
