"""D2: does denoising/decomposition preprocessing survive causal
evaluation and costs? (TRACK_D_PLAN, ticker ICICIBANK.)

Usage:
    uv run --no-sync python scripts/run_d2_preprocess.py

Protocol, identical for every variant:
- series: ICICIBANK adjusted-close log returns, 2010 -> today;
- features: lags 1..10 of the (possibly denoised) series; the TARGET is
  always the RAW next-day return — only inputs are transformed;
- model: ridge, expanding walk-forward, retrained monthly, 1-day
  embargo, first 3 years burn-in;
- verdicts: OOS IC (pred vs raw next-day return), sign accuracy, and a
  long/flat strategy (long when prediction > 0) net of full NSE
  delivery costs at Rs 5L — Sharpe/Sortino/Calmar/maxDD.

Variants: raw, wavelet leaky/causal, EMD leaky/causal, CEEMDAN leaky
(causal CEEMDAN computationally prohibitive; EMD is the causal
representative — recorded limitation). Every variant appends to the
trial ledger. The interesting number is each method's LEAKY-minus-
CAUSAL gap: that gap is the look-ahead the literature ships.
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
import polars as pl
from sklearn.linear_model import Ridge

from artha.config import load_settings
from artha.marketspec.nse import NSECostModel
from artha.models.ledger import Trial, TrialLedger
from artha.singlename.preprocess import (
    causal_transform,
    ceemdan_denoise,
    emd_denoise,
    wavelet_denoise,
)

TICKER = "ICICIBANK"
N_LAGS = 10
BURN_IN = 756
RETRAIN_EVERY = 21
CAPITAL = 500_000.0


def walk_forward_predictions(feat_series: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Expanding ridge, monthly retrain, 1-day embargo between train end
    and prediction. feat_series[t] is the (denoised) value at t; features
    for predicting target[t] (the t -> t+1 return) are lags 0..N_LAGS-1
    ending at t."""
    n = len(target)
    x = np.column_stack([np.roll(feat_series, k) for k in range(N_LAGS)])
    x[:N_LAGS, :] = np.nan
    preds = np.full(n, np.nan)
    model: Ridge | None = None
    for t in range(BURN_IN, n):
        if model is None or (t - BURN_IN) % RETRAIN_EVERY == 0:
            # train rows: predict target[s] from features at s; last usable
            # s is t-2 (embargo 1 day before the current prediction)
            rows = np.arange(N_LAGS, t - 1)
            xs, ys = x[rows], target[rows]
            ok = ~np.isnan(xs).any(axis=1) & ~np.isnan(ys)
            if ok.sum() < 252:
                continue
            model = Ridge(alpha=1.0).fit(xs[ok], ys[ok])
        if not np.isnan(x[t]).any():
            preds[t] = float(model.predict(x[t : t + 1])[0])
    return preds


def evaluate(preds: np.ndarray, target: np.ndarray, cost_per_switch: float) -> dict[str, float]:
    ok = ~np.isnan(preds) & ~np.isnan(target)
    p, y = preds[ok], target[ok]
    ic = float(np.corrcoef(p, y)[0, 1]) if len(p) > 2 else 0.0
    sign_acc = float((np.sign(p) == np.sign(y)).mean())
    pos = (p > 0).astype(float)
    switches = np.abs(np.diff(pos, prepend=0.0))
    strat = pos * y - switches * cost_per_switch
    mean, std = strat.mean(), strat.std(ddof=1)
    sharpe = float(mean / std * np.sqrt(252)) if std > 0 else 0.0
    downside = strat[strat < 0]
    sortino = float(mean / downside.std(ddof=1) * np.sqrt(252)) if len(downside) > 2 else 0.0
    eq = np.cumprod(1 + strat)
    peak = np.maximum.accumulate(eq)
    maxdd = float((eq / peak - 1).min())
    cagr = float(eq[-1] ** (252 / len(strat)) - 1)
    return {
        "n_days": len(p),
        "oos_ic": ic,
        "sign_accuracy": sign_acc,
        "net_sharpe": sharpe,
        "net_sortino": sortino,
        "net_cagr": cagr,
        "max_drawdown": maxdd,
        "calmar": cagr / abs(maxdd) if maxdd else 0.0,
        "time_in_market": float(pos.mean()),
        "n_switches_ann": float(switches.sum() / len(p) * 252),
    }


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    series = (
        panel.filter(pl.col("canon_symbol") == TICKER)
        .sort("trade_date")
        .select("trade_date", "adj_close")
    )
    rets = np.diff(np.log(series["adj_close"].to_numpy()))
    span = f"{series['trade_date'][0]} -> {series['trade_date'][-1]}"
    print(f"{TICKER}: {len(rets)} daily returns {span}")

    # round-trip charges for a full switch (sell + buy), plus impact at Rs 5L
    m = NSECostModel(dp_order_value=CAPITAL)
    adv = float(panel.filter(pl.col("canon_symbol") == TICKER)["traded_value"].tail(252).median())
    cost_per_switch = m.sell_cost(CAPITAL, adv) + m.buy_cost(CAPITAL, adv)
    print(f"cost per full switch: {cost_per_switch * 1e4:.1f} bps")

    target = np.roll(rets, -1)  # target[t] = return t -> t+1
    target[-1] = np.nan

    variants: dict[str, np.ndarray] = {"raw": rets}
    variants["wavelet_leaky"] = wavelet_denoise(rets)
    print("wavelet leaky done")
    variants["wavelet_causal"] = causal_transform(rets, wavelet_denoise)
    print("wavelet causal done")
    variants["emd_leaky"] = emd_denoise(rets)
    print("emd leaky done")
    variants["emd_causal"] = causal_transform(rets, emd_denoise)
    print("emd causal done")
    variants["ceemdan_leaky"] = ceemdan_denoise(rets)
    print("ceemdan leaky done")

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    results: dict[str, Any] = {}
    for name, feat in variants.items():
        preds = walk_forward_predictions(feat, target)
        stats = evaluate(preds, target, cost_per_switch)
        results[name] = stats
        ledger.append(
            Trial(
                model="d2_ridge_lags",
                label=f"{TICKER}_next_day",
                feature_set=name,
                params={"lags": N_LAGS, "retrain": RETRAIN_EVERY},
                mean_ic=stats["oos_ic"],
                ic_t_stat=cast(float, stats["oos_ic"]) * float(np.sqrt(stats["n_days"])),
                net_sharpe=stats["net_sharpe"],
                notes="D2 preprocessing study (leaky vs causal)",
            )
        )
        print(f"{name}: {json.dumps(stats)}")

    for fam in ("wavelet", "emd"):
        leaky, causal = results.get(f"{fam}_leaky"), results.get(f"{fam}_causal")
        if leaky and causal:
            results[f"{fam}_lookahead_gap"] = {
                "ic_gap": leaky["oos_ic"] - causal["oos_ic"],
                "sharpe_gap": leaky["net_sharpe"] - causal["net_sharpe"],
            }

    report = {"run_at": datetime.now(UTC).isoformat(), "ticker": TICKER, **results}
    out = settings.reports_dir / f"d2_preprocess_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
