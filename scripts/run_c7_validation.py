"""C7 validation battery: does the momentum+low-vol blend deserve to ship?

Usage:
    uv run --no-sync python scripts/run_c7_validation.py

ADR 0010 admitted the blend as an UPGRADE CANDIDATE only (Sharpe 1.297
vs 1.018 live) and required this battery before any production change.
Three independent questions, one script:

1. SELECTION OVERFITTING (CPCV/PBO). Sweep the blend weight w in
   {0, 0.25, 0.5, 0.75, 1} (w=0 is pure momentum, w=1 pure low-vol),
   each a full costed backtest under the production construction. Then
   Bailey-LdP PBO on the resulting daily series: across every
   combinatorial train/test split, does the in-sample winner stay good
   out of sample? PBO > 0.5 means the "winner" is selection noise.
2. SUB-PERIOD STABILITY. The same configs scored over three disjoint
   regimes: an edge that only exists in one third is not an edge.
3. FAMILY-LEVEL SNOOPING (SPA) + DSR. The blend weights are added to
   the strategy family and the whole set is re-tested against the
   benchmark (White RC + Hansen SPA), and the blend's own Sharpe is
   deflated against the CURRENT ledger count.

Ship criteria, fixed before the run (pre-registration):
  PBO < 0.5, blend beats momentum-only in >= 2 of 3 sub-periods,
  SPA p < 0.05 for the enlarged family, and DSR improves on the
  incumbent's. Anything else = hold, and the candidate is recorded as
  unproven rather than quietly adopted.
"""

import json
import sys
from datetime import UTC, date, datetime

import numpy as np
import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import low_vol_63d, momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.models.cpcv import cpcv_combinations, probability_of_backtest_overfitting
from artha.models.dsr import deflated_sharpe
from artha.models.ledger import Trial, TrialLedger
from artha.models.spa import spa_test
from artha.portfolio.construct import production_constructor

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0
WEIGHTS = [0.0, 0.25, 0.5, 0.75, 1.0]  # 0 = pure momentum, 1 = pure low-vol
SUB_PERIODS = [
    (date(2012, 8, 1), date(2016, 12, 31)),
    (date(2017, 1, 1), date(2020, 12, 31)),
    (date(2021, 1, 1), date(2026, 12, 31)),
]
PBO_GATE = 0.5
SPA_GATE = 0.05


def blended_signal(panel: pl.DataFrame, w: float) -> pl.DataFrame:
    """(1-w) * rank(momentum) + w * rank(low-vol), cross-sectional per date."""
    mom = momentum_12_1(panel).rename({"score": "m"})
    lv = low_vol_63d(panel).rename({"score": "v"})
    j = mom.join(lv, on=["canon_symbol", "trade_date"], how="inner")
    return j.with_columns(
        (
            (1 - w) * pl.col("m").rank().over("trade_date")
            + w * pl.col("v").rank().over("trade_date")
        ).alias("score")
    ).select("canon_symbol", "trade_date", "score")


def ann_sharpe(returns: np.ndarray) -> float:
    if len(returns) < 20:
        return 0.0
    sd = returns.std(ddof=1)
    return float(returns.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= START)
    cal = TradingCalendar.from_frame(px)
    master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
    sector_map = {
        r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
    }
    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")

    # --- 1. the weight sweep, one full costed backtest per config
    daily: dict[str, pl.DataFrame] = {}
    stats: dict[str, dict[str, float]] = {}
    for w in WEIGHTS:
        name = f"blend_w{int(w * 100):03d}"
        constructor = production_constructor(CAPITAL, sector_map)
        spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
        signal = blended_signal(panel, w).filter(pl.col("trade_date") >= START)
        res = run_backtest(px, signal, spec, capital=CAPITAL, constructor=constructor)
        daily[name] = res.daily.select("trade_date", "net_return")
        stats[name] = summarize(res.daily)
        ledger.append(
            Trial(
                model="c7_validation",
                label="production_construction",
                feature_set=name,
                params={"blend_weight_lowvol": w},
                mean_ic=0.0,
                ic_t_stat=0.0,
                net_sharpe=stats[name]["sharpe"],
                notes="C7 validation battery weight sweep",
            )
        )
        print(f"{name}: sharpe {stats[name]['sharpe']:.3f} cagr {stats[name]['cagr']:.1%}")

    wide = daily[f"blend_w{int(WEIGHTS[0] * 100):03d}"].rename(
        {"net_return": f"blend_w{int(WEIGHTS[0] * 100):03d}"}
    )
    for w in WEIGHTS[1:]:
        name = f"blend_w{int(w * 100):03d}"
        wide = wide.join(daily[name].rename({"net_return": name}), on="trade_date", how="inner")
    wide = wide.sort("trade_date")
    names = [f"blend_w{int(w * 100):03d}" for w in WEIGHTS]
    dates = wide["trade_date"].to_list()

    # --- 2. PBO across the configs (Bailey-LdP on the performance series)
    combos = cpcv_combinations(dates, n_blocks=8, k_test=2, horizon_days=1, embargo_days=5)
    is_scores: list[dict[str, float]] = []
    oos_scores: list[dict[str, float]] = []
    for combo in combos:
        train = set(combo.train_dates)
        test = set(combo.test_dates)
        tr_mask = np.array([d in train for d in dates])
        te_mask = np.array([d in test for d in dates])
        is_scores.append({n: ann_sharpe(wide[n].to_numpy()[tr_mask]) for n in names})
        oos_scores.append({n: ann_sharpe(wide[n].to_numpy()[te_mask]) for n in names})
    pbo = probability_of_backtest_overfitting(is_scores, oos_scores)
    print(f"PBO across {len(combos)} combinations: {pbo:.3f}")

    # --- 3. sub-period stability
    periods: dict[str, dict[str, float]] = {}
    for lo, hi in SUB_PERIODS:
        seg = wide.filter(pl.col("trade_date").is_between(lo, hi))
        if seg.height < 100:
            continue
        periods[f"{lo}..{hi}"] = {n: ann_sharpe(seg[n].to_numpy()) for n in names}
        print(
            f"{lo}..{hi}: "
            + json.dumps({k: round(v, 3) for k, v in periods[f"{lo}..{hi}"].items()})
        )

    # --- 4. SPA with the blend family added to everything tried before
    cv_path = settings.reports_dir / "construction_v2_daily.parquet"
    family = wide.clone()
    if cv_path.exists():
        cv = pl.read_parquet(cv_path)
        cv_wide = cv.pivot(on="config", index="trade_date", values="net_return")
        family = family.join(cv_wide, on="trade_date", how="inner")
    bench = (
        pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty500.parquet")
        .filter(pl.col("trade_date") >= START)
        .select("trade_date", "tr_return")
    )
    fam = family.join(bench, on="trade_date", how="inner").drop_nulls().sort("trade_date")
    fam_cols = [c for c in fam.columns if c not in ("trade_date", "tr_return")]
    diffs = fam.select(fam_cols).to_numpy() - fam.select("tr_return").to_numpy()
    spa = spa_test(diffs, n_boot=2000)
    print(
        f"SPA over {len(fam_cols)} configs: rc_p {spa.rc_p_value:.4f} spa_p {spa.spa_p_value:.4f}"
    )

    # --- 5. DSR at the current ledger count
    n_trials = ledger.count()
    best_blend = "blend_w050"
    blend_sharpe = stats[best_blend]["sharpe"]
    mom_sharpe = stats["blend_w000"]["sharpe"]
    n_days = int(stats[best_blend]["n_days"])
    dsr_blend = deflated_sharpe(
        blend_sharpe / 252**0.5, n_days, n_trials=n_trials, sr_variance=(0.5 / 252**0.5) ** 2
    )
    dsr_mom = deflated_sharpe(
        mom_sharpe / 252**0.5, n_days, n_trials=n_trials, sr_variance=(0.5 / 252**0.5) ** 2
    )

    # --- verdict against the pre-registered criteria
    beats_in_periods = sum(1 for p in periods.values() if p[best_blend] > p["blend_w000"])
    criteria = {
        "pbo_below_gate": bool(pbo < PBO_GATE),
        "stable_across_periods": beats_in_periods >= 2,
        "spa_significant": bool(spa.spa_p_value < SPA_GATE),
        "dsr_improves": bool(dsr_blend > dsr_mom),
    }
    verdict = "SHIP CANDIDATE" if all(criteria.values()) else "HOLD — unproven"

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "weight_sweep": stats,
        "pbo": pbo,
        "pbo_combinations": len(combos),
        "sub_periods": periods,
        "sub_period_wins_vs_momentum": beats_in_periods,
        "spa": {
            "family_size": len(fam_cols),
            "rc_p_value": spa.rc_p_value,
            "spa_p_value": spa.spa_p_value,
            "best_strategy": fam_cols[spa.best_strategy],
        },
        "dsr": {
            "ledger_trials": n_trials,
            "blend_w050": dsr_blend,
            "momentum_only": dsr_mom,
        },
        "criteria": criteria,
        "verdict": verdict,
    }
    out = settings.reports_dir / f"c7_validation_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "weight_sweep"}, indent=2))
    print(f"VERDICT: {verdict}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
