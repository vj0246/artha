"""H1: can a learned policy beat the fixed trading speed? (Track H)

Usage:
    uv run --no-sync python scripts/run_h1_rl_control.py

The system currently trades at a FIXED tau = 0.5 (Garleanu-Pedersen
partial adjustment). This asks whether a state-dependent policy does
better: at each weekly rebalance the agent picks tau from
{0.25, 0.50, 0.75} given a knowable-at-t context, and is rewarded with
the realised net return over the following week.

Why a contextual bandit rather than deep RL is argued in ADR 0013: at
our size there is no market impact (so actions do not change the next
state) and only ~700 weekly decisions exist in the whole history.

Honesty mechanics:
- Counterfactual rewards come from running the standard backtest once
  per fixed tau and recording each rebalance's forward net return.
  That is legitimate ONLY because we have no market impact, so the
  counterfactual is well defined; the assumption is stated, not hidden.
- The agent learns strictly online walk-forward: its choice at
  rebalance t uses only rewards observed before t.
- Context is built from the benchmark and the book's own trailing
  state, all knowable at t's close.

Pre-registered gates (fixed before the first run):
  1. learned policy net Sharpe > fixed tau=0.5 over the FULL sample;
  2. and over a held-out FINAL THIRD it never trained on freely;
  3. PBO < 0.5 across the action set.
Miss any -> publish the null, ship nothing.
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
from artha.features.baselines import momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.models.cpcv import cpcv_combinations, probability_of_backtest_overfitting
from artha.models.ledger import Trial, TrialLedger
from artha.portfolio.construct import Constructor
from artha.rl.bandits import LinUCB

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0
TAUS = [0.25, 0.50, 0.75]
BASELINE_ACTION = 1  # tau = 0.50, the shipped constant
ALPHA = 0.3  # LinUCB exploration width
PBO_GATE = 0.5


def build_contexts(settings: object, rebalance_dates: list[date]) -> dict[date, np.ndarray]:
    """Knowable-at-t context per rebalance: benchmark drawdown, trailing
    vol percentile, momentum dispersion, plus a bias term. Every input
    uses data through the rebalance close only."""
    from artha.config import Settings

    assert isinstance(settings, Settings)
    n500 = (
        pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty500.parquet")
        .sort("trade_date")
        .with_columns(
            (pl.col("tr_index") / pl.col("tr_index").cum_max() - 1).alias("dd"),
            pl.col("tr_return").rolling_std(window_size=63).alias("vol63"),
        )
        .with_columns(
            pl.col("vol63").rolling_quantile(0.5, window_size=756).alias("vol_med"),
        )
        .select("trade_date", "dd", "vol63", "vol_med")
    )
    rows = {r["trade_date"]: r for r in n500.iter_rows(named=True)}
    out: dict[date, np.ndarray] = {}
    for d in rebalance_dates:
        r = rows.get(d)
        if r is None or r["vol63"] is None or r["vol_med"] is None:
            out[d] = np.array([1.0, 0.0, 0.0])
            continue
        stress = 1.0 if r["vol63"] >= (r["vol_med"] or 0.0) else 0.0
        out[d] = np.array([1.0, float(r["dd"] or 0.0), stress])
    return out


def action_rewards(
    px: pl.DataFrame,
    signal: pl.DataFrame,
    cal: TradingCalendar,
    sector_map: dict[str, str],
) -> tuple[list[date], np.ndarray, dict[int, pl.DataFrame]]:
    """Forward one-week net return per (rebalance, action).

    Runs the standard backtest once per fixed tau. Valid because our
    size has no market impact: the alternative action's path is a real
    counterfactual, not an approximation of one."""
    dailies: dict[int, pl.DataFrame] = {}
    per_action: list[dict[date, float]] = []
    for a, tau in enumerate(TAUS):
        constructor = Constructor(
            capital=CAPITAL, sector_map=sector_map, scheme="minvar", trade_speed=tau
        )
        spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
        res = run_backtest(px, signal, spec, capital=CAPITAL, constructor=constructor)
        dailies[a] = res.daily
        daily = res.daily.sort("trade_date")
        dates = daily["trade_date"].to_list()
        rets = daily["net_return"].to_numpy()
        idx = {d: i for i, d in enumerate(dates)}
        rebals = res.rebalances["rebalance_date"].to_list()
        fwd: dict[date, float] = {}
        for d in rebals:
            i = idx.get(d)
            if i is None:
                continue
            window = rets[i + 1 : i + 6]  # the week the decision buys
            if len(window):
                fwd[d] = float(np.prod(1 + window) - 1)
        per_action.append(fwd)

    common = sorted(set.intersection(*(set(f) for f in per_action)))
    matrix = np.array([[per_action[a][d] for a in range(len(TAUS))] for d in common])
    return common, matrix, dailies


def walk_forward_policy(
    dates: list[date], rewards: np.ndarray, contexts: dict[date, np.ndarray]
) -> list[int]:
    """Online LinUCB: the action at t is chosen from what was observed
    strictly BEFORE t, then t's outcome is used to update."""
    agent = LinUCB(n_actions=len(TAUS), n_features=3, alpha=ALPHA)
    chosen: list[int] = []
    for i, d in enumerate(dates):
        ctx = contexts[d]
        a = agent.select(ctx)
        chosen.append(a)
        agent.update(ctx, a, float(rewards[i, a]))
    return chosen


def policy_returns(
    chosen: list[int], dates: list[date], dailies: dict[int, pl.DataFrame]
) -> pl.DataFrame:
    """Stitch the daily series the policy actually experienced: between
    rebalance t and t+1 the book follows the action chosen at t."""
    base = dailies[0].sort("trade_date").select("trade_date")
    all_dates = base["trade_date"].to_list()
    series = {a: dailies[a].sort("trade_date")["net_return"].to_numpy() for a in dailies}
    out = np.zeros(len(all_dates))
    idx = {d: i for i, d in enumerate(all_dates)}
    bounds = [idx[d] for d in dates]
    for k, start in enumerate(bounds):
        end = bounds[k + 1] if k + 1 < len(bounds) else len(all_dates) - 1
        a = chosen[k]
        out[start + 1 : end + 1] = series[a][start + 1 : end + 1]
    return pl.DataFrame({"trade_date": all_dates, "net_return": out})


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
    signal = momentum_12_1(panel).filter(pl.col("trade_date") >= START)

    print("running one backtest per action (counterfactual rewards)...")
    dates, rewards, dailies = action_rewards(px, signal, cal, sector_map)
    contexts = build_contexts(settings, dates)
    print(f"{len(dates)} weekly decisions, {len(TAUS)} actions")

    chosen = walk_forward_policy(dates, rewards, contexts)
    learned = policy_returns(chosen, dates, dailies)
    learned_stats = summarize(learned)
    fixed_stats = {a: summarize(dailies[a]) for a in dailies}

    # held-out final third: the agent has learned throughout, but this
    # segment is never revisited, so it is the honest out-of-sample view
    cut = dates[int(len(dates) * 2 / 3)]
    tail_learned = summarize(learned.filter(pl.col("trade_date") >= cut))
    tail_fixed = summarize(dailies[BASELINE_ACTION].filter(pl.col("trade_date") >= cut))

    # PBO across the action set (is picking the best tau a coin flip?)
    all_dates = dailies[0].sort("trade_date")["trade_date"].to_list()
    combos = cpcv_combinations(all_dates, n_blocks=8, k_test=2, horizon_days=1, embargo_days=5)
    names = [f"tau_{t:.2f}" for t in TAUS]
    series = {names[a]: dailies[a].sort("trade_date")["net_return"].to_numpy() for a in dailies}

    def sharpe(x: np.ndarray) -> float:
        sd = x.std(ddof=1)
        return float(x.mean() / sd * np.sqrt(252)) if len(x) > 20 and sd > 0 else 0.0

    is_scores, oos_scores = [], []
    for combo in combos:
        tr = np.array([d in set(combo.train_dates) for d in all_dates])
        te = np.array([d in set(combo.test_dates) for d in all_dates])
        is_scores.append({n: sharpe(series[n][tr]) for n in names})
        oos_scores.append({n: sharpe(series[n][te]) for n in names})
    pbo = probability_of_backtest_overfitting(is_scores, oos_scores)

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    for a, tau in enumerate(TAUS):
        ledger.append(
            Trial(
                model="h1_fixed_tau",
                label="production_construction",
                feature_set=f"tau_{tau:.2f}",
                params={"tau": tau},
                mean_ic=0.0,
                ic_t_stat=0.0,
                net_sharpe=fixed_stats[a]["sharpe"],
                notes="H1 bandit control study (fixed baseline)",
            )
        )
    ledger.append(
        Trial(
            model="h1_linucb",
            label="production_construction",
            feature_set="linucb_tau_control",
            params={"alpha": ALPHA, "actions": TAUS},
            mean_ic=0.0,
            ic_t_stat=0.0,
            net_sharpe=learned_stats["sharpe"],
            notes="H1 bandit control study (learned policy)",
        )
    )

    criteria = {
        "beats_fixed_full_sample": bool(
            learned_stats["sharpe"] > fixed_stats[BASELINE_ACTION]["sharpe"]
        ),
        "beats_fixed_final_third": bool(tail_learned["sharpe"] > tail_fixed["sharpe"]),
        "pbo_below_gate": bool(pbo < PBO_GATE),
    }
    verdict = "SHIP CANDIDATE" if all(criteria.values()) else "HOLD — null published"

    counts = {f"tau_{TAUS[a]:.2f}": chosen.count(a) for a in range(len(TAUS))}
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "decisions": len(dates),
        "action_counts": counts,
        "learned_policy": learned_stats,
        "fixed_baselines": {f"tau_{TAUS[a]:.2f}": fixed_stats[a] for a in fixed_stats},
        "final_third": {
            "cut_date": str(cut),
            "learned_sharpe": tail_learned["sharpe"],
            "fixed_sharpe": tail_fixed["sharpe"],
        },
        "pbo_over_actions": pbo,
        "criteria": criteria,
        "verdict": verdict,
    }
    out = settings.reports_dir / f"h1_rl_control_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"VERDICT: {verdict}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
