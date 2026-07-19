"""Risk model for covariance-aware construction (Track C C2).

Ledoit-Wolf shrinkage toward the scaled identity ("Honey, I Shrunk the
Sample Covariance Matrix", JPM 2004): the 25-name sample covariance from
~1 year of daily returns is noise-dominated, and LW gives the optimal
(under Frobenius loss) convex combination with a structured target, in
closed form. Long-only minimum variance uses the standard closed form
w ∝ Σ⁻¹1 with negative weights clipped to zero and renormalized — a
disclosed heuristic that avoids a QP dependency and, per Jagannathan &
Ma (2003), the clip itself acts as additional shrinkage.
"""

import numpy as np

MIN_OBS = 63  # fall back to equal weight below one quarter of history


def lw_shrunk_cov(returns: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf identity-target shrunk covariance from a T x N matrix
    of daily returns (rows = days). NaNs are column-mean imputed."""
    x = np.array(returns, dtype=float)
    col_mean = np.nanmean(x, axis=0)
    inds = np.where(np.isnan(x))
    x[inds] = np.take(col_mean, inds[1])
    t, n = x.shape
    x = x - x.mean(axis=0)
    sample = x.T @ x / t
    mu = np.trace(sample) / n
    target = mu * np.eye(n)
    d2 = float(np.sum((sample - target) ** 2))
    if d2 <= 0:
        return np.asarray(sample)
    b2 = 0.0
    for row in x:
        b2 += float(np.sum((np.outer(row, row) - sample) ** 2))
    b2 = min(b2 / t**2, d2)
    shrinkage = b2 / d2
    return np.asarray(shrinkage * target + (1 - shrinkage) * sample)


def inverse_vol_weights(names: list[str], vols: dict[str, float]) -> dict[str, float]:
    """w ∝ 1/vol (naive risk parity). Names without a positive vol get the
    average inverse vol (neutral, not excluded)."""
    invs = {n: 1.0 / vols[n] for n in names if vols.get(n, 0.0) > 0}
    if not invs:
        return {n: 1.0 / len(names) for n in names}
    mean_inv = sum(invs.values()) / len(invs)
    full = {n: invs.get(n, mean_inv) for n in names}
    total = sum(full.values())
    return {n: v / total for n, v in full.items()}


def min_var_weights(names: list[str], cov: np.ndarray) -> dict[str, float]:
    """Long-only minimum variance: w ∝ Σ⁻¹1, clip negatives, renormalize.
    Falls back to equal weight if the solve fails or everything clips."""
    n = len(names)
    try:
        raw = np.linalg.solve(cov + 1e-10 * np.eye(n), np.ones(n))
    except np.linalg.LinAlgError:
        return dict.fromkeys(names, 1.0 / n)
    raw = np.clip(raw, 0.0, None)
    total = float(raw.sum())
    if total <= 0:
        return dict.fromkeys(names, 1.0 / n)
    return {s: float(w) / total for s, w in zip(names, raw, strict=True)}
