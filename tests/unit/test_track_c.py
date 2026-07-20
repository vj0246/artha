"""Track C: risk model, SPA test, construction v2 mechanics."""

import numpy as np
import pytest

from artha.models.spa import spa_test, stationary_bootstrap_indices
from artha.portfolio.construct import ConstraintReport, Constructor
from artha.portfolio.riskmodel import inverse_vol_weights, lw_shrunk_cov, min_var_weights


class TestRiskModel:
    def test_lw_shrinks_toward_identity(self) -> None:
        rng = np.random.default_rng(1)
        true_cov = np.array([[1.0, 0.6], [0.6, 1.0]]) * 1e-4
        chol = np.linalg.cholesky(true_cov)
        x = rng.standard_normal((60, 2)) @ chol.T  # short sample -> noisy
        shrunk = lw_shrunk_cov(x)
        sample = np.cov(x.T, bias=True)
        # off-diagonal moves toward zero (identity target), diagonal preserved in scale
        assert abs(shrunk[0, 1]) < abs(sample[0, 1])
        assert shrunk[0, 0] == pytest.approx(sample[0, 0], rel=0.5)

    def test_lw_handles_nans(self) -> None:
        x = np.random.default_rng(2).standard_normal((100, 3)) * 0.01
        x[:40, 1] = np.nan
        cov = lw_shrunk_cov(x)
        assert np.all(np.isfinite(cov))

    def test_inverse_vol_known_answer(self) -> None:
        w = inverse_vol_weights(["a", "b"], {"a": 0.1, "b": 0.2})
        assert w["a"] == pytest.approx(2 / 3)
        assert w["b"] == pytest.approx(1 / 3)

    def test_min_var_uncorrelated_known_answer(self) -> None:
        # uncorrelated: w propto 1/sigma^2 -> (0.04, 0.01) vols 0.1/0.2 -> 0.8/0.2
        cov = np.diag([0.1**2, 0.2**2])
        w = min_var_weights(["a", "b"], cov)
        assert w["a"] == pytest.approx(0.8)
        assert w["b"] == pytest.approx(0.2)

    def test_min_var_long_only_clip(self) -> None:
        # strong correlation makes raw min-var short one asset; clip keeps it long-only
        cov = np.array([[0.01, 0.0198], [0.0198, 0.04]])
        w = min_var_weights(["a", "b"], cov)
        assert min(w.values()) >= 0
        assert sum(w.values()) == pytest.approx(1.0)


class TestSpa:
    def test_bootstrap_indices_shape_and_range(self) -> None:
        idx = stationary_bootstrap_indices(100, 50)
        assert idx.shape == (50, 100)
        assert idx.min() >= 0
        assert idx.max() < 100

    def test_null_family_not_rejected(self) -> None:
        rng = np.random.default_rng(3)
        d = rng.normal(0.0, 0.01, size=(750, 8))  # zero-mean family
        res = spa_test(d, n_boot=400, seed=3)
        assert res.spa_p_value > 0.05
        assert res.rc_p_value > 0.05

    def test_strong_alternative_rejected(self) -> None:
        rng = np.random.default_rng(4)
        d = rng.normal(0.0, 0.01, size=(750, 8))
        d[:, 2] += 0.002  # ~50% ann. edge at 16% vol: unmistakable
        res = spa_test(d, n_boot=400, seed=4)
        assert res.spa_p_value < 0.05
        assert res.best_strategy == 2

    def test_spa_less_conservative_than_rc_with_bad_padding(self) -> None:
        rng = np.random.default_rng(5)
        d = rng.normal(0.0, 0.01, size=(750, 6))
        d[:, 0] += 0.0008  # modest real edge
        d[:, 3:] -= 0.003  # deeply losing padding strategies
        res = spa_test(d, n_boot=400, seed=5)
        assert res.spa_p_value <= res.rc_p_value + 0.05


class TestConstructionV2:
    def test_partial_adjustment_moves_fraction(self) -> None:
        c = Constructor(top_n=2, trade_speed=0.5, position_cap=1.0)
        target = c.build([("a", 1e9), ("b", 1e9)], {"a": 0.0, "b": 0.0}, None, ConstraintReport())
        # from zero toward 0.5 each at tau=0.5 -> 0.25 each
        assert target["a"] == pytest.approx(0.25)
        assert target["b"] == pytest.approx(0.25)

    def test_ivol_scheme_tilts_to_low_vol(self) -> None:
        c = Constructor(top_n=2, scheme="ivol", position_cap=1.0)
        target = c.build(
            [("calm", 1e9), ("wild", 1e9)],
            {},
            None,
            ConstraintReport(),
            vols={"calm": 0.10, "wild": 0.40},
        )
        assert target["calm"] > target["wild"]

    def test_schemes_fall_back_to_equal_without_inputs(self) -> None:
        for scheme in ("ivol", "minvar"):
            c = Constructor(top_n=2, scheme=scheme, position_cap=1.0)
            target = c.build([("a", 1e9), ("b", 1e9)], {}, None, ConstraintReport())
            assert target["a"] == pytest.approx(target["b"])


class TestReviewHardening:
    def test_partial_adjustment_full_exit_below_epsilon(self) -> None:
        c = Constructor(top_n=1, trade_speed=0.5, position_cap=1.0)
        # dropped name below the exit epsilon liquidates fully, no zombie tail
        target = c.build([("a", 1e9)], {"a": 1.0, "gone": 0.004}, None, ConstraintReport())
        assert "gone" not in target
        # above the epsilon it still decays gradually (GP behavior kept)
        target = c.build([("a", 1e9)], {"a": 0.94, "big": 0.04}, None, ConstraintReport())
        assert target["big"] == pytest.approx(0.02)

    def test_position_cap_excess_redistributes(self) -> None:
        c = Constructor(top_n=3, scheme="minvar", position_cap=0.10)
        cov = np.diag([0.01**2, 0.3**2, 0.3**2])  # min-var loads name a heavily
        t = c.build(
            [("a", 1e9), ("b", 1e9), ("c", 1e9)],
            {},
            None,
            ConstraintReport(),
            cov=(["a", "b", "c"], cov),
        )
        assert t["a"] == pytest.approx(0.10)  # capped
        # clipped excess went to b/c instead of leaking to cash
        assert sum(t.values()) == pytest.approx(0.30)

    def test_minvar_partial_coverage_degrades_per_name(self) -> None:
        c = Constructor(top_n=3, scheme="minvar", position_cap=1.0)
        cov = np.diag([0.1**2, 0.2**2])  # only a and b covered
        t = c.build(
            [("a", 1e9), ("b", 1e9), ("newlisting", 1e9)],
            {},
            None,
            ConstraintReport(),
            cov=(["a", "b"], cov),
        )
        # covered subset gets min-var (a > b), newcomer gets the 1/N share
        assert t["a"] > t["b"]
        assert t["newlisting"] == pytest.approx(1 / 3)


class TestTrackE:
    def test_ewma_cov_weights_recent_days_more(self) -> None:
        from artha.portfolio.riskmodel import ewma_cov

        rng = np.random.default_rng(6)
        calm = rng.normal(0, 0.005, (200, 2))
        stormy = rng.normal(0, 0.05, (20, 2))
        x = np.vstack([calm, stormy])  # recent regime is violent
        e = ewma_cov(x)
        flat = np.cov(x.T, bias=True)
        # EWMA variance responds to the recent storm far more than the flat window
        assert e[0, 0] > 2 * flat[0, 0]

    def test_ewma_cov_symmetric_finite(self) -> None:
        from artha.portfolio.riskmodel import ewma_cov

        x = np.random.default_rng(7).normal(0, 0.01, (252, 5))
        x[:30, 2] = np.nan
        e = ewma_cov(x)
        assert np.allclose(e, e.T)
        assert np.all(np.isfinite(e))

    def test_psi_zero_for_same_distribution_large_for_shift(self) -> None:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "run_signal_health", Path("scripts/run_signal_health.py")
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        rng = np.random.default_rng(8)
        ref = rng.normal(0, 1, 5000)
        same = rng.normal(0, 1, 5000)
        shifted = rng.normal(1.5, 1, 5000)
        assert mod.psi(ref, same) < 0.05
        assert mod.psi(ref, shifted) > 0.25
