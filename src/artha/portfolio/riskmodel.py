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

from datetime import date

import numpy as np
import polars as pl

MIN_OBS = 63  # fall back to equal weight below one quarter of history
RISK_WINDOW = 252


def risk_inputs(
    panel: pl.DataFrame, names: list[str], asof: date, *, window: int = RISK_WINDOW
) -> tuple[dict[str, float] | None, tuple[list[str], np.ndarray] | None]:
    """(vols, cov) for the picks from panel history THROUGH ``asof`` —
    the live-path twin of the backtester's wide-matrix slice.

    Degrades PER NAME, never all-or-nothing (review finding 2026-07-20):
    names lacking MIN_OBS observations are excluded from vols/cov, and
    the constructor gives them an equal-weight share while the covered
    subset still gets the risk model. (None, None) only when NO name has
    enough history."""
    hist = (
        panel.filter(pl.col("canon_symbol").is_in(names) & (pl.col("trade_date") <= asof))
        .sort("canon_symbol", "trade_date")
        .with_columns(
            (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1)
            .over("canon_symbol")
            .alias("ret")
        )
    )
    wide = hist.pivot(on="canon_symbol", index="trade_date", values="ret").sort("trade_date")
    present = [n for n in names if n in wide.columns]
    if not present:
        return None, None
    arr = wide.tail(window).select(present).to_numpy()
    if arr.shape[0] == 0:
        return None, None
    obs = (~np.isnan(arr)).sum(axis=0)
    covered = [n for n, o in zip(present, obs.tolist(), strict=True) if o >= MIN_OBS]
    if not covered:
        return None, None
    keep = [present.index(n) for n in covered]
    sub = arr[:, keep]
    vols = np.nanstd(sub, axis=0, ddof=1) * np.sqrt(252)
    return dict(zip(covered, vols.tolist(), strict=True)), (covered, lw_shrunk_cov(sub))


EWMA_LAMBDA = 0.94  # RiskMetrics (1996) daily decay


def ewma_cov(returns: np.ndarray, *, lam: float = EWMA_LAMBDA) -> np.ndarray:
    """Exponentially weighted covariance (RiskMetrics) from a T x N daily
    return matrix — the incremental 'each new day partially updates the
    estimate' risk model (Track E E1). NaNs are column-mean imputed;
    weights decay backward from the last row."""
    x = np.array(returns, dtype=float)
    col_mean = np.nanmean(x, axis=0)
    inds = np.where(np.isnan(x))
    x[inds] = np.take(col_mean, inds[1])
    t = x.shape[0]
    x = x - x.mean(axis=0)
    w = lam ** np.arange(t - 1, -1, -1)
    w /= w.sum()
    return np.asarray((x * w[:, None]).T @ x)


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
