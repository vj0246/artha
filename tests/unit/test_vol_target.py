"""Vol-target inputs shared by the backtester and the live runbook (ADR 0015)."""

import math

import numpy as np
import pytest

from artha.portfolio.riskmodel import cold_start_vol, proforma_book_returns, realized_book_vol


def _inline_estimator(book: list[float]) -> float | None:
    """The formula the backtester carried inline before ADR 0015. The shared
    function must reproduce it bit for bit, or every published backtest moves."""

    def ann(xs: list[float]) -> float:
        mean = sum(xs) / len(xs)
        return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1) * 252)

    if len(book) < 21:
        return None
    vol = ann(book[-21:])
    return max(vol, ann(book[-63:])) if len(book) >= 63 else vol


@pytest.mark.parametrize("n", [5, 20, 21, 40, 63, 200])
def test_shared_estimator_matches_the_inline_formula_exactly(n: int) -> None:
    book = np.random.default_rng(n).normal(0, 0.012, n).tolist()
    assert realized_book_vol(book) == _inline_estimator(book)


def test_proforma_renormalises_over_names_that_printed() -> None:
    returns = np.array([[0.02, np.nan], [0.01, 0.03], [np.nan, np.nan]])
    out = proforma_book_returns(returns, np.array([0.5, 0.5]))
    # day 1: only the first name printed, so the book earned ITS return, not
    # half of it; day 3: nothing printed, so the day is dropped, not a zero
    assert out == [pytest.approx(0.02), pytest.approx(0.02)]


def test_cold_start_vol_is_the_equal_weight_proforma() -> None:
    returns = np.random.default_rng(3).normal(0, 0.015, (63, 4))
    assert cold_start_vol(returns) == pytest.approx(
        realized_book_vol(returns.mean(axis=1).tolist())
    )


def test_cold_start_needs_names_and_history() -> None:
    assert cold_start_vol(np.empty((63, 0))) is None
    assert cold_start_vol(np.zeros((10, 3))) is None  # under 21 days of returns
