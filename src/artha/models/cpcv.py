"""Combinatorial purged CV and the probability of backtest overfitting.

CPCV (Lopez de Prado ch. 12): split the date grid into N contiguous blocks;
for every combination of k test blocks, train on the remaining blocks with a
purge+embargo gap around each test block.

PBO (Bailey, Borwein, Lopez de Prado, Zhu 2017): across model configs, for
each combination rank configs by in-sample score, take the best-IS config,
and look at its out-of-sample rank; PBO is the fraction of combinations
where that config lands in the bottom half OOS.
"""

from dataclasses import dataclass
from datetime import date
from itertools import combinations
from math import log


@dataclass(frozen=True)
class Combination:
    test_blocks: tuple[int, ...]
    train_dates: list[date]
    test_dates: list[date]


def cpcv_combinations(
    dates: list[date],
    *,
    n_blocks: int = 8,
    k_test: int = 2,
    horizon_days: int = 1,
    embargo_days: int = 4,
) -> list[Combination]:
    """All C(n_blocks, k_test) purged train/test splits over ``dates``."""
    if dates != sorted(dates):
        raise ValueError("dates must be sorted")
    size = len(dates) // n_blocks
    bounds = [
        (i * size, ((i + 1) * size if i < n_blocks - 1 else len(dates)) - 1)
        for i in range(n_blocks)
    ]
    gap = horizon_days + embargo_days
    out: list[Combination] = []
    for combo in combinations(range(n_blocks), k_test):
        banned: set[date] = set()
        test_dates: list[date] = []
        for b in combo:
            start, end = bounds[b]
            test_dates.extend(dates[start : end + 1])
            # purge + embargo: gap positions on either side of the block
            banned.update(dates[max(0, start - gap) : min(len(dates), end + gap + 1)])
        test_set = set(test_dates)
        train_dates = [d for d in dates if d not in banned and d not in test_set]
        out.append(Combination(combo, train_dates, sorted(test_dates)))
    return out


def probability_of_backtest_overfitting(
    is_scores: list[dict[str, float]], oos_scores: list[dict[str, float]]
) -> float:
    """PBO from per-combination config scores (same keys in both lists).

    For each combination: best in-sample config -> its OOS rank among all
    configs -> logit; PBO = fraction of logits <= 0 (OOS rank at or below
    median).
    """
    if len(is_scores) != len(oos_scores) or not is_scores:
        raise ValueError("need matching, non-empty score lists")
    logits: list[float] = []
    for is_s, oos_s in zip(is_scores, oos_scores, strict=True):
        best = max(is_s, key=lambda k: is_s[k])
        ranked = sorted(oos_s, key=lambda k: oos_s[k])
        n = len(ranked)
        rank = ranked.index(best) + 1  # 1 = worst OOS
        omega = rank / (n + 1)
        logits.append(log(omega / (1 - omega)))
    return sum(1 for x in logits if x <= 0) / len(logits)
