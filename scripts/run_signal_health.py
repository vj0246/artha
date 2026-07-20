"""E2: daily signal-health monitor — IC decay + feature drift + DSR.

Usage (wired into the daily cycle, non-critical):
    uv run --no-sync python scripts/run_signal_health.py

With no fitted parameters in production, the update-worthy object is
the BELIEF that the edge persists. This measures it daily:

- rolling 63d and 252d rank-IC of momentum 12-1 vs realized 5d forward
  returns (the signal actually traded); ALERT when the 63d IC has been
  negative for 21 consecutive sessions while the 252d IC is also < 0
  (sustained decay, not noise);
- PSI (population stability index) of each library feature's current
  21d cross-sectional distribution vs its trailing-year reference;
  ALERT past 0.25 (the standard major-shift threshold);
- monthly deflated-Sharpe refresh: production Sharpe re-deflated
  against the CURRENT ledger trial count (honesty compounds as the
  agent and scheduled studies keep appending).

Appends one row per run to reports/paper/signal_health.jsonl.
"""

import json
import sys
from datetime import UTC, datetime
from typing import cast

import numpy as np
import polars as pl

from artha.config import load_settings
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.features.library import build_features
from artha.live.safety import alert
from artha.models.dsr import deflated_sharpe
from artha.models.ledger import TrialLedger

IC_FAST, IC_SLOW = 63, 252
DECAY_RUN = 21
PSI_ALERT = 0.25
PSI_BINS = 10
PRODUCTION_SHARPE = 1.018  # ADR 0008 post-hardening figure
PRODUCTION_DAYS = 3456


def psi(reference: np.ndarray, current: np.ndarray) -> float:
    """Population stability index over decile bins of the reference."""
    edges = np.quantile(reference, np.linspace(0, 1, PSI_BINS + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    ref_p = np.histogram(reference, bins=edges)[0] / max(len(reference), 1)
    cur_p = np.histogram(current, bins=edges)[0] / max(len(current), 1)
    ref_p = np.clip(ref_p, 1e-6, None)
    cur_p = np.clip(cur_p, 1e-6, None)
    return float(np.sum((cur_p - ref_p) * np.log(cur_p / ref_p)))


def rolling_ic(universe: pl.DataFrame) -> pl.DataFrame:
    """Daily cross-sectional rank-IC of momentum vs 5d forward return."""
    sig = momentum_12_1(universe.filter(pl.col("in_universe")))
    fwd = (
        universe.sort("canon_symbol", "trade_date")
        .with_columns(
            (pl.col("adj_close").shift(-5) / pl.col("adj_close") - 1)
            .over("canon_symbol")
            .alias("fwd5")
        )
        .select("canon_symbol", "trade_date", "fwd5")
    )
    j = sig.join(fwd, on=["canon_symbol", "trade_date"], how="inner").drop_nulls()
    ranked = j.with_columns(
        pl.col("score").rank().over("trade_date").alias("_rs"),
        pl.col("fwd5").rank().over("trade_date").alias("_rf"),
    )
    return (
        ranked.group_by("trade_date")
        .agg(pl.corr("_rs", "_rf").alias("ic"), pl.len().alias("n"))
        .filter(pl.col("n") >= 50)
        .sort("trade_date")
    )


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    today = cast(object, universe["trade_date"].max())

    ics = rolling_ic(universe)
    ic_series = ics["ic"]
    ic63 = float(ic_series.tail(IC_FAST).mean() or 0.0)
    ic252 = float(ic_series.tail(IC_SLOW).mean() or 0.0)
    recent = ic_series.tail(DECAY_RUN).to_list()
    decay_alert = len(recent) == DECAY_RUN and all(x < 0 for x in recent) and ic252 < 0

    features, names = build_features(universe.filter(pl.col("in_universe")))
    dates = sorted(features["trade_date"].unique().to_list())
    cur_dates = set(dates[-21:])
    ref_dates = set(dates[-273:-21])
    drift: dict[str, float] = {}
    for name in names:
        ref = features.filter(pl.col("trade_date").is_in(sorted(ref_dates)))[name].to_numpy()
        cur = features.filter(pl.col("trade_date").is_in(sorted(cur_dates)))[name].to_numpy()
        if len(ref) > 100 and len(cur) > 100:
            drift[name] = round(psi(ref, cur), 4)
    worst_feature, worst_psi = max(drift.items(), key=lambda kv: kv[1]) if drift else ("", 0.0)

    ledger_n = TrialLedger(settings.reports_dir / "ledger.jsonl").count()
    dsr = deflated_sharpe(
        PRODUCTION_SHARPE / 252**0.5,
        PRODUCTION_DAYS,
        n_trials=ledger_n,
        sr_variance=(0.5 / 252**0.5) ** 2,
    )

    row = {
        "run_at": datetime.now(UTC).isoformat(),
        "asof": str(today),
        "ic_63d": round(ic63, 5),
        "ic_252d": round(ic252, 5),
        "ic_decay_alert": decay_alert,
        "psi_worst_feature": worst_feature,
        "psi_worst": worst_psi,
        "psi_alert": worst_psi > PSI_ALERT,
        "ledger_trials": ledger_n,
        "production_dsr": round(dsr, 4),
    }
    out_dir = settings.reports_dir / "paper"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "signal_health.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row, indent=2))

    if decay_alert:
        alert(f"SIGNAL DECAY: momentum 63d IC negative {DECAY_RUN} straight sessions ({ic63:.4f})")
    if row["psi_alert"]:
        alert(f"FEATURE DRIFT: {worst_feature} PSI {worst_psi:.2f} > {PSI_ALERT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
