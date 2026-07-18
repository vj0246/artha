"""Research agent runner (Track B B6): propose -> sandbox -> screen -> ledger.

Usage:
    uv run --no-sync python scripts/run_research_agent.py [--n 3] [--offline]

Offline (default when GROQ_API_KEY is absent) the proposals come from the
deterministic seed list. Each screened candidate is appended to the trial
ledger and the run is written to reports/research_agent_<ts>.json.
"""

import argparse
import json
import sys
from datetime import UTC, datetime

import polars as pl
from sklearn.linear_model import Ridge

from artha.agent.loop import screen_candidate
from artha.agent.proposer import propose
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.library import build_features
from artha.labels.horizon import forward_return_z
from artha.models.cv import walk_forward_folds
from artha.models.ledger import Trial, TrialLedger
from artha.models.study import run_study

LABEL_HORIZON_DAYS = 5
# Quick protocol: same purged walk-forward geometry as the model study but
# half-year test blocks, so the screen is ~4x cheaper per candidate.
TEST_DAYS = 26


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel).filter(pl.col("in_universe"))
    cal = TradingCalendar.from_frame(universe)
    weekly = sorted(set(cal.week_last_days()))

    features, names = build_features(universe)
    labels = forward_return_z(panel, LABEL_HORIZON_DAYS)
    matrix = (
        features.join(labels, on=["canon_symbol", "trade_date"], how="inner")
        .filter(pl.col("trade_date").is_in(weekly))
        .sort("trade_date", "canon_symbol")
    )
    grid = sorted(matrix["trade_date"].unique().to_list())
    folds = walk_forward_folds(
        grid, test_days=TEST_DAYS, min_train_days=156, horizon_days=1, embargo_days=4
    )
    print(f"matrix {matrix.height:,} rows, {len(folds)} folds (quick protocol)")

    baseline = run_study(matrix, names, folds, lambda: Ridge(alpha=1.0), model_name="ridge")
    print(f"library baseline: IC {baseline.mean_ic:.4f} (t={baseline.ic_t_stat:.1f})")

    proposals, source = propose(args.n, offline=args.offline)
    print(f"{len(proposals)} proposals from {source}")

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    screens = []
    for prop in proposals:
        result = screen_candidate(
            matrix, universe, names, folds, prop, baseline_ic=baseline.mean_ic
        )
        if result.status == "ok":
            ledger.append(
                Trial(
                    model="ridge",
                    label=f"fwd_{LABEL_HORIZON_DAYS}d_z",
                    feature_set=f"library_v1+{prop.name}",
                    params={"alpha": 1.0, "protocol": "agent_quick_screen"},
                    mean_ic=result.mean_ic or 0.0,
                    ic_t_stat=result.ic_t_stat or 0.0,
                    notes=f"research-agent screen ({source}); delta_ic={result.delta_ic:.5f}",
                )
            )
        screens.append(
            {
                "name": prop.name,
                "expression": prop.expression,
                "rationale": prop.rationale,
                "status": result.status,
                "detail": result.detail,
                "mean_ic": result.mean_ic,
                "ic_t_stat": result.ic_t_stat,
                "delta_ic": result.delta_ic,
            }
        )
        print(f"{prop.name}: {result.status} " + json.dumps(screens[-1], default=str))

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "source": source,
        "baseline_ic": baseline.mean_ic,
        "baseline_t": baseline.ic_t_stat,
        "n_folds": len(folds),
        "screens": screens,
        "ledger_trials": ledger.count(),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = settings.reports_dir / f"research_agent_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
