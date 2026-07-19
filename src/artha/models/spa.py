"""Reality Check and Superior Predictive Ability tests (Track C C1).

Tests the sharp null "no strategy in the tried family beats the
benchmark" on the JOINT bootstrap distribution of benchmark-relative
performance, capturing cross-strategy dependence that the deflated
Sharpe's expected-max correction cannot.

- White (2000): Reality Check p-value - bootstrap the max mean relative
  performance, uncentered null.
- Hansen (2005): SPA - studentized statistic with consistent
  recentering, removing the RC's conservatism when poor strategies pad
  the family.
- Politis & Romano (1994): stationary bootstrap - geometric block
  lengths preserve serial dependence of daily returns.

Inputs are a T x K matrix of daily RELATIVE returns d[t, k] =
strategy_k[t] - benchmark[t]. All statistics are computed on means of d.
"""

from dataclasses import dataclass

import numpy as np

AVG_BLOCK_DAYS = 21  # ~one trading month preserves vol clustering


def stationary_bootstrap_indices(
    n: int, n_boot: int, *, avg_block: float = AVG_BLOCK_DAYS, seed: int = 7
) -> np.ndarray:
    """(n_boot, n) index matrix from the Politis-Romano stationary
    bootstrap: blocks restart with probability 1/avg_block each step."""
    rng = np.random.default_rng(seed)
    p = 1.0 / avg_block
    starts = rng.integers(0, n, size=(n_boot, n))
    restart = rng.random(size=(n_boot, n)) < p
    restart[:, 0] = True
    idx = np.zeros((n_boot, n), dtype=np.int64)
    for t in range(n):
        if t == 0:
            idx[:, 0] = starts[:, 0]
            continue
        cont = (idx[:, t - 1] + 1) % n
        idx[:, t] = np.where(restart[:, t], starts[:, t], cont)
    return idx


@dataclass(frozen=True)
class SpaResult:
    rc_p_value: float
    spa_p_value: float
    best_strategy: int  # column index of the best mean relative performance
    best_mean_ann: float  # annualized mean relative return of the best
    n_strategies: int
    n_obs: int
    n_boot: int


def spa_test(diffs: np.ndarray, *, n_boot: int = 1000, seed: int = 7) -> SpaResult:
    """White RC + Hansen SPA p-values for a T x K relative-return matrix."""
    d = np.asarray(diffs, dtype=float)
    t, k = d.shape
    means = d.mean(axis=0)
    idx = stationary_bootstrap_indices(t, n_boot, seed=seed)
    boot_means = d[idx].mean(axis=1)  # (n_boot, k)

    # RC (White): max_k sqrt(T) dbar_k vs bootstrap of max_k sqrt(T)(dbar*_k - dbar_k)
    rc_stat = np.sqrt(t) * means.max()
    rc_boot = np.sqrt(t) * (boot_means - means).max(axis=1)
    rc_p = float((rc_boot >= rc_stat).mean())

    # SPA (Hansen): studentized by the bootstrap std of sqrt(T) dbar*_k,
    # with the consistent recentering threshold
    omega = np.sqrt(t) * boot_means.std(axis=0, ddof=1)
    omega = np.where(omega <= 0, 1e-12, omega)
    spa_stat = max(0.0, float((np.sqrt(t) * means / omega).max()))
    threshold = -omega / np.sqrt(t) * np.sqrt(2 * np.log(np.log(max(t, 3))))
    recenter = np.where(means >= threshold, means, 0.0)
    spa_boot = (np.sqrt(t) * (boot_means - recenter) / omega).max(axis=1)
    spa_boot = np.maximum(spa_boot, 0.0)
    spa_p = float((spa_boot >= spa_stat).mean())

    best = int(means.argmax())
    return SpaResult(
        rc_p_value=rc_p,
        spa_p_value=spa_p,
        best_strategy=best,
        best_mean_ann=float(means[best]) * 252,
        n_strategies=k,
        n_obs=t,
        n_boot=n_boot,
    )
