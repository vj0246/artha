"""Research-agent sandbox, proposer, and screen loop."""

from datetime import date, timedelta
from typing import cast

import numpy as np
import polars as pl
import pytest
from pydantic import ValidationError

from artha.agent.loop import candidate_frame, screen_candidate
from artha.agent.proposer import SEED_SPECS, propose
from artha.agent.sandbox import SandboxError, compile_expression
from artha.agent.spec import FeatureProposal
from artha.models.cv import walk_forward_folds


def test_sandbox_accepts_all_seed_expressions() -> None:
    for spec in SEED_SPECS:
        assert isinstance(compile_expression(spec.expression), pl.Expr)


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os').system('x')",
        "col('adj_close').map_elements(print)",  # attribute access
        "open('secrets')",
        "col('adj_close')[0]",  # subscript
        "shift(dret(), n=1)",  # keyword args
        "col('not_a_column')",
        "roll_mean(dret(), 5000)",  # window beyond cap
        "lambda: 1",
        "dret() if 1 else 0",
        "42",  # not a polars expression
    ],
)
def test_sandbox_rejects(bad: str) -> None:
    with pytest.raises(SandboxError):
        compile_expression(bad)


def test_spec_rejects_bad_names() -> None:
    with pytest.raises(ValidationError):
        FeatureProposal(name="Bad Name!", rationale="x", expression="dret()", lookback_days=5)


def test_propose_offline_is_deterministic() -> None:
    a, src_a = propose(2, offline=True)
    b, src_b = propose(2, offline=True)
    assert src_a == src_b == "seeds"
    assert a == b == SEED_SPECS[:2]


def _synthetic_panel(n_days: int = 420, n_symbols: int = 30) -> pl.DataFrame:
    rng = np.random.default_rng(11)
    days = [date(2022, 1, 3) + timedelta(days=i) for i in range(n_days)]
    frames = []
    for s in range(n_symbols):
        px = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, n_days)))
        frames.append(
            pl.DataFrame(
                {
                    "canon_symbol": [f"SYM{s:02d}"] * n_days,
                    "trade_date": days,
                    "adj_close": px,
                    "close": px,
                    "high": px * 1.01,
                    "low": px * 0.99,
                    "traded_value": rng.uniform(1e6, 1e8, n_days),
                }
            )
        )
    return pl.concat(frames)


def test_candidate_frame_is_zscored_per_date() -> None:
    panel = _synthetic_panel()
    frame = candidate_frame(panel, SEED_SPECS[0])
    assert frame.columns == ["canon_symbol", "trade_date", SEED_SPECS[0].name]
    late = frame.filter(pl.col("trade_date") > date(2022, 6, 1))
    per_date = late.group_by("trade_date").agg(pl.col(SEED_SPECS[0].name).mean().alias("m"))
    assert cast(float, per_date["m"].abs().max()) < 1e-6  # cross-sectional mean ~ 0


def test_screen_candidate_end_to_end() -> None:
    panel = _synthetic_panel()
    label = (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(
            (pl.col("adj_close").shift(-5) / pl.col("adj_close") - 1)
            .over("canon_symbol")
            .alias("label")
        )
        .drop_nulls("label")
    )
    base = candidate_frame(panel, SEED_SPECS[1]).rename({SEED_SPECS[1].name: "base_feat"})
    matrix = base.join(
        label.select("canon_symbol", "trade_date", "label"),
        on=["canon_symbol", "trade_date"],
        how="inner",
    ).sort("trade_date", "canon_symbol")
    grid = sorted(matrix["trade_date"].unique().to_list())
    folds = walk_forward_folds(grid, test_days=60, min_train_days=120, horizon_days=5)
    assert folds

    result = screen_candidate(matrix, panel, ["base_feat"], folds, SEED_SPECS[0], baseline_ic=0.0)
    assert result.status == "ok"
    assert result.mean_ic is not None
    assert result.delta_ic is not None

    collision = screen_candidate(
        matrix, panel, [SEED_SPECS[0].name], folds, SEED_SPECS[0], baseline_ic=0.0
    )
    assert collision.status == "rejected"
