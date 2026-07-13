"""Model-study infrastructure: CV purge, ledger, DSR, rank IC, study loop."""

from datetime import date, timedelta
from pathlib import Path
from typing import cast

import numpy as np
import polars as pl
import pytest

from artha.features.library import build_features, feature_registry
from artha.labels.horizon import forward_return_z
from artha.models.cv import walk_forward_folds
from artha.models.dsr import deflated_sharpe, expected_max_sharpe
from artha.models.ledger import Trial, TrialLedger
from artha.models.study import rank_ic_per_date, run_study

DATES = [date(2020, 1, 1) + timedelta(days=i) for i in range(400)]


class TestWalkForward:
    def test_fold_structure_and_purge_gap(self) -> None:
        folds = walk_forward_folds(
            DATES, test_days=50, min_train_days=200, horizon_days=5, embargo_days=10
        )
        assert len(folds) == 4  # (400 - 215) / 50 rounded up
        first = folds[0]
        assert first.test_start == DATES[215]
        # purge + embargo: last train date is horizon+embargo before test
        assert (first.test_start - first.train_end).days == 16
        # expanding and contiguous
        assert folds[1].test_start == DATES[265]
        assert folds[1].train_end == DATES[249]

    def test_unsorted_rejected(self) -> None:
        with pytest.raises(ValueError, match="sorted"):
            walk_forward_folds(list(reversed(DATES)), test_days=10, min_train_days=10)


class TestLedgerAndDsr:
    def test_ledger_roundtrip(self, tmp_path: Path) -> None:
        ledger = TrialLedger(tmp_path / "ledger.jsonl")
        assert ledger.count() == 0
        ledger.append(
            Trial("ridge", "fwd_5d_z", "lib_v1", {"alpha": 1.0}, 0.03, 4.2, net_sharpe=0.9)
        )
        ledger.append(Trial("lgbm", "fwd_5d_z", "lib_v1", {}, 0.05, 6.0))
        assert ledger.count() == 2

    def test_dsr_penalizes_trials(self) -> None:
        base = deflated_sharpe(0.05, 1000, n_trials=1)
        many = deflated_sharpe(0.05, 1000, n_trials=50, sr_variance=0.03**2)
        assert base > many
        assert expected_max_sharpe(1, 0.1) == 0.0
        assert expected_max_sharpe(100, 0.03**2) > 0

    def test_dsr_zero_sharpe_is_coin_flip(self) -> None:
        assert deflated_sharpe(0.0, 1000, n_trials=1) == pytest.approx(0.5, abs=0.01)


class TestStudy:
    def test_rank_ic_perfect_signal(self) -> None:
        scored = pl.DataFrame(
            {
                "trade_date": [date(2024, 1, 5)] * 25,
                "score": list(range(25)),
                "label": [float(i) for i in range(25)],
            }
        )
        ics = rank_ic_per_date(scored.with_columns(pl.col("score").cast(pl.Float64)))
        assert ics["ic"][0] == pytest.approx(1.0)

    def test_run_study_recovers_planted_signal(self) -> None:
        rng = np.random.default_rng(3)
        days = [date(2022, 1, 3) + timedelta(days=7 * i) for i in range(120)]
        rows = []
        for d in days:
            x = rng.normal(size=40)
            noise = rng.normal(scale=0.5, size=40)
            for i in range(40):
                rows.append(
                    {
                        "canon_symbol": f"S{i}",
                        "trade_date": d,
                        "f1": float(x[i]),
                        "f2": float(rng.normal()),
                        "label": float(x[i] + noise[i]),
                    }
                )
        matrix = pl.DataFrame(rows)
        folds = walk_forward_folds(
            days, test_days=10, min_train_days=60, horizon_days=1, embargo_days=2
        )
        from sklearn.linear_model import Ridge  # type: ignore[import-untyped]

        res = run_study(matrix, ["f1", "f2"], folds, lambda: Ridge(alpha=1.0), model_name="ridge")
        assert res.mean_ic > 0.5
        assert res.decile_spread > 1.0
        # OOS only: no prediction may predate the first test block
        first_pred = cast(date, res.predictions["trade_date"].min())
        assert first_pred >= folds[0].test_start


class TestCpcv:
    def test_combination_structure_and_purge(self) -> None:
        from artha.models.cpcv import cpcv_combinations

        combos = cpcv_combinations(DATES, n_blocks=8, k_test=2, horizon_days=2, embargo_days=3)
        assert len(combos) == 28  # C(8,2)
        c = combos[0]  # test blocks 0 and 1
        assert c.test_blocks == (0, 1)
        # no train date inside a test block or its 5-position purge halo
        test_set = set(c.test_dates)
        assert not test_set & set(c.train_dates)
        last_test = max(c.test_dates)
        after = [d for d in c.train_dates if d > last_test]
        assert min(after) == last_test + timedelta(days=6)  # gap of 5 dates

    def test_pbo_extremes(self) -> None:
        from artha.models.cpcv import probability_of_backtest_overfitting

        # best IS config always best OOS -> PBO 0
        consistent_is = [{"a": 1.0, "b": 0.1, "c": 0.0}] * 10
        consistent_oos = [{"a": 0.9, "b": 0.2, "c": 0.1}] * 10
        assert probability_of_backtest_overfitting(consistent_is, consistent_oos) == 0.0
        # best IS config always worst OOS -> PBO 1
        flipped_oos = [{"a": -1.0, "b": 0.2, "c": 0.1}] * 10
        assert probability_of_backtest_overfitting(consistent_is, flipped_oos) == 1.0


def test_transformer_wrapper_learns_linear_signal() -> None:
    from artha.models.transformer import TabTransformerRegressor

    rng = np.random.default_rng(5)
    X = rng.normal(size=(2000, 4)).astype("float32")
    y = X[:, 0] * 1.0 + rng.normal(scale=0.1, size=2000)
    model = TabTransformerRegressor(epochs=8, batch_size=512)
    model.fit(X, y)
    pred = model.predict(X)
    corr = float(np.corrcoef(pred, y)[0, 1])
    assert corr > 0.7


class TestFeatureLibrary:
    def test_build_and_zscore(self) -> None:
        rng = np.random.default_rng(1)
        days: list[date] = []
        d = date(2020, 1, 1)
        while len(days) < 300:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(days=1)
        rows = []
        for sym in ("A", "B", "C", "D", "E"):
            price = 100.0
            for day in days:
                price *= float(np.exp(rng.normal(0, 0.02)))
                rows.append(
                    {
                        "canon_symbol": sym,
                        "trade_date": day,
                        "adj_close": price,
                        "close": price,
                        "high": price * 1.01,
                        "low": price * 0.99,
                        "traded_value": float(rng.uniform(1e6, 1e8)),
                    }
                )
        feats, names = build_features(pl.DataFrame(rows))
        assert len(names) == 19
        assert feats.height == 5 * (300 - 252)
        # z-scored per date: means ~0 (5 names -> exact within float noise)
        means = feats.group_by("trade_date").agg(pl.col("mom_12_1").mean())
        assert abs(max(means["mom_12_1"].to_list(), key=abs)) < 1e-9
        registry = feature_registry(names)
        assert registry["rev_1d"].lookback_days == 1
        assert all(s.knowable_at == "close[t]" for s in registry.values())


def test_forward_return_z_label() -> None:
    days = [date(2024, 1, i) for i in range(1, 11)]
    rows = []
    for sym, drift in (("UP", 1.01), ("DN", 0.99), ("FL", 1.0)):
        price = 100.0
        for d in days:
            rows.append({"canon_symbol": sym, "trade_date": d, "adj_close": price})
            price *= drift
    labels = forward_return_z(pl.DataFrame(rows), 5)
    first = labels.filter(pl.col("trade_date") == days[0]).sort("label", descending=True)
    assert first["canon_symbol"].to_list()[0] == "UP"
    assert first["canon_symbol"].to_list()[-1] == "DN"
    # z-scored: per-date mean 0
    assert abs(cast(float, labels.filter(pl.col("trade_date") == days[0])["label"].sum())) < 1e-9
    # no labels where the forward window runs off the panel
    assert labels["trade_date"].max() == days[4]
