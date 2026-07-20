"""Shared evaluation for single-name long/flat strategies (Track D).

One implementation of the costed strategy metrics, fixing two review
findings at once: transaction costs are charged PER SIDE (a flat->long
toggle pays the buy side only, long->flat the sell side — not a full
round trip per toggle), and Sortino uses the same RMS downside
deviation convention as artha.risk.analytics so ledger columns stay
comparable across tracks.
"""

import numpy as np

TRADING_DAYS = 252


def long_flat_stats(
    preds: np.ndarray,
    target: np.ndarray,
    *,
    buy_rate: float,
    sell_rate: float,
) -> dict[str, float]:
    """Metrics for a long-when-pred>0 / flat strategy on daily returns.

    ``preds``/``target`` may contain NaN (skipped jointly). Costs: each
    0->1 transition pays ``buy_rate``, each 1->0 pays ``sell_rate``,
    both as fractions of capital."""
    ok = ~np.isnan(preds) & ~np.isnan(target)
    p, y = preds[ok], target[ok]
    if len(p) < 3:
        return {"n_days": float(len(p))}
    pos = (p > 0).astype(float)
    delta = np.diff(pos, prepend=0.0)
    costs = np.where(delta > 0, buy_rate, 0.0) + np.where(delta < 0, sell_rate, 0.0)
    strat = pos * y - costs
    mean, std = strat.mean(), strat.std(ddof=1)
    eq = np.cumprod(1 + strat)
    peak = np.maximum.accumulate(eq)
    maxdd = float((eq / peak - 1).min())
    cagr = float(eq[-1] ** (TRADING_DAYS / len(strat)) - 1)
    downside = strat[strat < 0]
    # RMS downside deviation — matches artha.risk.analytics.sortino
    dd_rms = float(np.sqrt((downside**2).mean() * TRADING_DAYS)) if len(downside) else 0.0
    # constant predictions (the always-long floor) have no defined IC
    ic = 0.0 if np.all(p == p[0]) else float(np.corrcoef(p, y)[0, 1])
    return {
        "n_days": float(len(p)),
        "oos_ic": ic,
        "sign_accuracy": float((np.sign(p) == np.sign(y)).mean()),
        "net_sharpe": float(mean / std * np.sqrt(TRADING_DAYS)) if std > 0 else 0.0,
        "net_sortino": float(mean * TRADING_DAYS / dd_rms) if dd_rms > 0 else 0.0,
        "net_cagr": cagr,
        "max_drawdown": maxdd,
        "calmar": cagr / abs(maxdd) if maxdd else 0.0,
        "time_in_market": float(pos.mean()),
        "n_switches_ann": float(np.abs(delta).sum() / len(p) * TRADING_DAYS),
    }
