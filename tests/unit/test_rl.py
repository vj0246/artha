"""Track H: bandit agents and the research agent's memory."""

import json
from pathlib import Path

import numpy as np
import pytest

from artha.agent.memory import FAMILIES, AgentMemory, classify_family, rebuild_from_ledger
from artha.rl.bandits import FixedPolicy, LinUCB, ThompsonGaussian


class TestLinUCB:
    def test_learns_a_context_dependent_arm(self) -> None:
        # arm 0 pays when the context flag is on, arm 1 when it is off
        rng = np.random.default_rng(3)
        agent = LinUCB(n_actions=2, n_features=2, alpha=0.2)
        for _ in range(400):
            flag = float(rng.integers(0, 2))
            ctx = np.array([1.0, flag])
            a = agent.select(ctx)
            truth = 0 if flag else 1
            agent.update(ctx, a, 1.0 if a == truth else 0.0)
        assert agent.select(np.array([1.0, 1.0])) == 0
        assert agent.select(np.array([1.0, 0.0])) == 1

    def test_decisions_cannot_depend_on_the_future(self) -> None:
        """The contract that makes walk-forward honest: replaying with a
        different FUTURE must leave every earlier action untouched."""
        rng = np.random.default_rng(4)
        contexts = [np.array([1.0, float(rng.integers(0, 2))]) for _ in range(60)]
        rewards_a = rng.normal(0, 1, (60, 2))
        rewards_b = rewards_a.copy()
        rewards_b[30:] += 99.0  # violently change everything after step 30

        def run(rewards: np.ndarray) -> list[int]:
            agent = LinUCB(n_actions=2, n_features=2, alpha=0.2)
            picks = []
            for i, ctx in enumerate(contexts):
                a = agent.select(ctx)
                picks.append(a)
                agent.update(ctx, a, float(rewards[i, a]))
            return picks

        assert run(rewards_a)[:30] == run(rewards_b)[:30]

    def test_cold_start_explores_rather_than_fixating(self) -> None:
        agent = LinUCB(n_actions=3, n_features=2, alpha=1.0)
        ctx = np.array([1.0, 0.5])
        # with no data every arm is equally optimistic -> argmax picks arm 0,
        # but the optimism width must be identical across arms
        scores = agent.scores(ctx)
        assert np.allclose(scores, scores[0])


class TestThompson:
    def test_converges_to_the_better_arm(self) -> None:
        rng = np.random.default_rng(5)
        agent = ThompsonGaussian(n_actions=2, prior_sd=1.0, seed=5)
        for _ in range(300):
            a = agent.select()
            reward = rng.normal(1.0 if a == 1 else 0.0, 0.1)
            agent.update(None, a, reward)
        assert agent.counts[1] > agent.counts[0]
        assert agent.means[1] > agent.means[0]

    def test_running_moments_match_numpy(self) -> None:
        agent = ThompsonGaussian(n_actions=1)
        xs = [0.1, -0.3, 0.7, 0.2, -0.05]
        for x in xs:
            agent.update(None, 0, x)
        assert agent.means[0] == pytest.approx(float(np.mean(xs)))
        var = agent.m2[0] / (agent.counts[0] - 1)
        assert var == pytest.approx(float(np.var(xs, ddof=1)))


class TestFixedPolicy:
    def test_ignores_context_and_updates(self) -> None:
        p = FixedPolicy(action=2, n_actions=3)
        assert p.select(np.array([1.0, 5.0])) == 2
        p.update(np.array([1.0]), 2, 1.0)
        assert p.select(np.array([0.0])) == 2


class TestAgentMemory:
    def test_family_classification(self) -> None:
        assert classify_family("illiq_trend_5_63", "col('traded_value')") == "liquidity"
        assert (
            classify_family("range_pos_21d", "roll_max(col('adj_close'), 21)") == "range_position"
        )
        assert classify_family("vol_ratio_21_63", "roll_std(dret(), 21)") == "vol_structure"
        assert classify_family("month_turn_drift", "month_end") == "seasonality"
        # unknown shapes must never raise
        assert classify_family("mystery", "1 + 1") in FAMILIES

    def test_memory_prefers_families_that_paid_off(self, tmp_path: Path) -> None:
        mem = AgentMemory.load(tmp_path / "m.json", seed=11)
        for _ in range(30):
            mem.record("liquidity", 0.02)
            mem.record("seasonality", -0.02)
        # the winning family should rank ahead of the losing one
        ranks = [mem.rank().index("liquidity") < mem.rank().index("seasonality") for _ in range(20)]
        assert sum(ranks) >= 15  # Thompson keeps exploring, so allow some draws

    def test_memory_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        mem = AgentMemory.load(path)
        mem.record("liquidity", 0.01)
        mem.save()
        again = AgentMemory.load(path)
        i = FAMILIES.index("liquidity")
        assert again.bandit.counts[i] == 1
        assert again.bandit.means[i] == pytest.approx(0.01)

    def test_rebuilds_from_the_ledger(self, tmp_path: Path) -> None:
        ledger = tmp_path / "ledger.jsonl"
        rows = [
            {
                "model": "ridge",
                "feature_set": "library_v1+illiq_trend_5_63",
                "notes": "research-agent screen (seeds); delta_ic=0.00300",
            },
            {
                "model": "ridge",
                "feature_set": "library_v1+month_turn_drift",
                "notes": "research-agent screen (seeds); delta_ic=-0.00100",
            },
            {"model": "ridge", "feature_set": "library_v1_17", "notes": "unrelated row"},
        ]
        ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        mem = rebuild_from_ledger(tmp_path / "m.json", ledger)
        summary = mem.summary()
        assert summary["liquidity"]["screens"] == 1
        assert summary["liquidity"]["mean_delta_ic"] == pytest.approx(0.003)
        assert summary["seasonality"]["mean_delta_ic"] == pytest.approx(-0.001)

    def test_rebuild_tolerates_a_missing_ledger(self, tmp_path: Path) -> None:
        mem = rebuild_from_ledger(tmp_path / "m.json", tmp_path / "nope.jsonl")
        assert all(v["screens"] == 0 for v in mem.summary().values())
