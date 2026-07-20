"""D3/D5: single-name model family + drift study (TRACK_D_PLAN).

Usage:
    uv run --no-sync python scripts/run_d3_models.py [--windows expanding rolling]

Family (artha/singlename/models.py): always-long floor, ridge, LGBM,
GRU, LSTM, tiny transformer, and the learner ensemble — all on the RAW
ICICIBANK series (D2 verdict: causal denoising adds nothing; leaky is
disqualified), features = standardized lag window, target = raw
next-day return. Expanding walk-forward, quarterly retrain, 1-day
embargo, 3y burn-in, judged as a costed long/flat strategy.

--windows adds the D5 drift arm: the same family retrained on a rolling
3y window instead of expanding; the expanding-vs-rolling delta is the
data-drift answer. Regime split (C4 frame) reported for the winner.
Every configuration appends to the trial ledger.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl

from artha.config import load_settings
from artha.marketspec.nse import NSECostModel
from artha.models.ledger import Trial, TrialLedger
from artha.singlename.evalutil import long_flat_stats
from artha.singlename.models import FAMILY, SEQ_LEN, predict

TICKER = "ICICIBANK"
BURN_IN = 756
RETRAIN_EVERY = 63
ROLLING_WINDOW = 756
CAPITAL = 500_000.0


def build_xy(rets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """x[t] = standardized lags 0..SEQ_LEN-1 ending at t; y[t] = raw
    return t -> t+1. Columns are CHRONOLOGICAL (oldest lag first, newest
    last) so sequence models read time forward and their final-timestep
    readout sits on the most recent return (review finding 2026-07-20:
    the previous newest-first order fed RNNs time-reversed input)."""
    x = np.column_stack([np.roll(rets, k) for k in range(SEQ_LEN - 1, -1, -1)])
    x[:SEQ_LEN, :] = np.nan
    y = np.roll(rets, -1)
    y[-1] = np.nan
    return x, y


def walk_forward(x: np.ndarray, y: np.ndarray, fit: Any, name: str, *, rolling: bool) -> np.ndarray:
    n = len(y)
    preds = np.full(n, np.nan)
    model: object | None = None
    mu = sd = None
    for t in range(BURN_IN, n):
        if model is None or (t - BURN_IN) % RETRAIN_EVERY == 0:
            lo = max(SEQ_LEN, t - 1 - ROLLING_WINDOW) if rolling else SEQ_LEN
            rows = np.arange(lo, t - 1)
            xs, ys = x[rows], y[rows]
            ok = ~np.isnan(xs).any(axis=1) & ~np.isnan(ys)
            if ok.sum() < 252:
                continue
            mu, sd = xs[ok].mean(), xs[ok].std() + 1e-12
            model = fit((xs[ok] - mu) / sd, ys[ok], seed=t)
        if model is not None and not np.isnan(x[t]).any():
            preds[t] = float(predict(name, model, (x[t : t + 1] - mu) / sd)[0])
    return preds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--windows", nargs="*", default=["expanding"])
    args = parser.parse_args()

    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    icic = panel.filter(pl.col("canon_symbol") == TICKER).sort("trade_date")
    rets = np.diff(np.log(icic["adj_close"].to_numpy()))
    m = NSECostModel(dp_order_value=CAPITAL)
    adv = float(icic["traded_value"].tail(252).median())
    buy_rate, sell_rate = m.buy_cost(CAPITAL, adv), m.sell_cost(CAPITAL, adv)
    x, y = build_xy(rets)

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    results: dict[str, Any] = {}
    for window in args.windows:
        rolling = window == "rolling"
        wres: dict[str, Any] = {}
        # floor: always long (constant positive prediction; evalutil
        # reports IC 0.0 for constants instead of a NaN correlation)
        always = np.where(np.isnan(y), np.nan, 1.0)
        wres["always_long"] = long_flat_stats(always, y, buy_rate=buy_rate, sell_rate=sell_rate)
        preds_bank: dict[str, np.ndarray] = {}
        for name, fit in FAMILY.items():
            preds = walk_forward(x, y, fit, name, rolling=rolling)
            preds_bank[name] = preds
            wres[name] = long_flat_stats(preds, y, buy_rate=buy_rate, sell_rate=sell_rate)
            print(f"[{window}] {name}: {json.dumps(wres[name])}")
        stack = np.vstack([preds_bank[n] for n in FAMILY])
        wres["ensemble_mean"] = long_flat_stats(
            np.nanmean(stack, axis=0), y, buy_rate=buy_rate, sell_rate=sell_rate
        )
        print(f"[{window}] ensemble_mean: {json.dumps(wres['ensemble_mean'])}")
        for name, stats in wres.items():
            ledger.append(
                Trial(
                    model=f"d3_{name}",
                    label=f"{TICKER}_next_day",
                    feature_set=f"raw_lags{SEQ_LEN}_{window}",
                    params={"retrain": RETRAIN_EVERY, "window": window},
                    mean_ic=stats["oos_ic"],
                    ic_t_stat=stats["oos_ic"] * float(np.sqrt(stats["n_days"])),
                    net_sharpe=stats["net_sharpe"],
                    notes="D3/D5 single-name family",
                )
            )
        results[window] = wres

    report = {"run_at": datetime.now(UTC).isoformat(), "ticker": TICKER, **results}
    out = settings.reports_dir / f"d3_models_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
