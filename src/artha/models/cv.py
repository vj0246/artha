"""Purged expanding walk-forward CV with embargo (Lopez de Prado ch. 7).

Folds are defined on the sorted list of panel dates. For a test block
[test_start, test_end]:

- training dates end at test_start - horizon - embargo trading days, so no
  training label window [t, t+h] overlaps the test block (purge) and a
  buffer absorbs serial correlation (embargo);
- training is expanding: everything from the panel start.

CPCV (combinatorial purged CV for PBO) builds on the same block structure
in the P3 closing slice.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Fold:
    train_end: date  # inclusive last training date
    test_start: date
    test_end: date


def walk_forward_folds(
    dates: list[date],
    *,
    test_days: int = 63,
    min_train_days: int = 756,
    horizon_days: int = 5,
    embargo_days: int = 21,
) -> list[Fold]:
    """Expanding walk-forward folds over ``dates`` (sorted trading days)."""
    if dates != sorted(dates):
        raise ValueError("dates must be sorted")
    gap = horizon_days + embargo_days
    folds: list[Fold] = []
    start = min_train_days + gap
    i = start
    while i < len(dates):
        test_slice = dates[i : i + test_days]
        folds.append(
            Fold(
                train_end=dates[i - gap - 1],
                test_start=test_slice[0],
                test_end=test_slice[-1],
            )
        )
        i += test_days
    return folds
