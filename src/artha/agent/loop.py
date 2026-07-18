"""Research-agent evaluation loop (Track B B6).

Quick screen, one candidate at a time: build the proposed feature in the
sandbox, z-score it cross-sectionally like the library, append it to the
library matrix, and re-run the ridge walk-forward study. The verdict is
the IC delta versus the library-only baseline under the identical fold
protocol. No backtest at this stage — survivors graduate to the full
model-study protocol by hand. Every screen is appended to the trial
ledger, keeping the deflated-Sharpe trial count honest.
"""

from dataclasses import dataclass

import polars as pl
from sklearn.linear_model import Ridge

from artha.agent.sandbox import SandboxError, compile_expression
from artha.agent.spec import FeatureProposal
from artha.models.cv import Fold
from artha.models.study import run_study

_EPS = 1e-12


def candidate_frame(panel: pl.DataFrame, proposal: FeatureProposal) -> pl.DataFrame:
    """(canon_symbol, trade_date, <name>): the proposed feature computed
    per symbol, z-scored per date, nulls/inf -> 0 (library convention)."""
    expr = compile_expression(proposal.expression)
    name = proposal.name
    df = (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(expr.over("canon_symbol").alias(name))
        .select("canon_symbol", "trade_date", name)
    )
    return df.with_columns(
        (
            (pl.col(name) - pl.col(name).mean().over("trade_date"))
            / (pl.col(name).std().over("trade_date") + _EPS)
        )
        .fill_null(0.0)
        .fill_nan(0.0)
        .alias(name)
    )


@dataclass(frozen=True)
class ScreenResult:
    proposal: FeatureProposal
    status: str  # "ok" | "rejected"
    detail: str
    mean_ic: float | None = None
    ic_t_stat: float | None = None
    delta_ic: float | None = None


def screen_candidate(
    matrix: pl.DataFrame,
    panel: pl.DataFrame,
    library_names: list[str],
    folds: list[Fold],
    proposal: FeatureProposal,
    *,
    baseline_ic: float,
) -> ScreenResult:
    """Ridge study on library + candidate; delta vs the library baseline."""
    if proposal.name in library_names or proposal.name in matrix.columns:
        return ScreenResult(proposal, "rejected", "name collides with existing feature")
    try:
        feature = candidate_frame(panel, proposal)
    except SandboxError as exc:
        return ScreenResult(proposal, "rejected", f"sandbox: {exc}")
    except pl.exceptions.PolarsError as exc:
        return ScreenResult(proposal, "rejected", f"polars: {exc}")
    augmented = matrix.join(feature, on=["canon_symbol", "trade_date"], how="left").with_columns(
        pl.col(proposal.name).fill_null(0.0)
    )
    res = run_study(
        augmented,
        [*library_names, proposal.name],
        folds,
        lambda: Ridge(alpha=1.0),
        model_name=f"ridge+{proposal.name}",
    )
    return ScreenResult(
        proposal,
        "ok",
        "screened",
        mean_ic=res.mean_ic,
        ic_t_stat=res.ic_t_stat,
        delta_ic=res.mean_ic - baseline_ic,
    )
