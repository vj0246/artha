"""Contextual bandits for sequential control (Track H).

Why bandits and not deep RL, stated where the code lives (ADR 0013):

- **No market impact.** At Rs 2-5L our orders do not move prices, so our
  action does not change the next context. That makes this a contextual
  bandit, not a Markov decision process; an MDP would model an influence
  we do not have.
- **~700 weekly decisions exist in the whole history.** PPO/DQN need
  10^5-10^6 interactions. Linear/tabular learners are what this sample
  size supports honestly.

Every agent here obeys one contract, enforced by tests: ``select`` may
use only what ``update`` has already been told. Nothing about the future
can reach a past decision.

Sources: Sutton & Barto ch. 2; Li et al. (2010) LinUCB; Thompson (1933).
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass
class FixedPolicy:
    """The baseline every learner must beat: always the same action."""

    action: int
    n_actions: int

    def select(self, context: np.ndarray) -> int:
        return self.action

    def update(self, context: np.ndarray, action: int, reward: float) -> None:
        return None


@dataclass
class LinUCB:
    """Disjoint LinUCB (Li et al. 2010): per-action ridge regression of
    reward on context, choosing the arm with the highest optimistic
    estimate. ``alpha`` is the exploration width in standard errors."""

    n_actions: int
    n_features: int
    alpha: float = 0.5
    ridge: float = 1.0
    _A: list[np.ndarray] = field(default_factory=list, repr=False)
    _b: list[np.ndarray] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._A = [self.ridge * np.eye(self.n_features) for _ in range(self.n_actions)]
        self._b = [np.zeros(self.n_features) for _ in range(self.n_actions)]

    def _theta(self, a: int) -> np.ndarray:
        return np.asarray(np.linalg.solve(self._A[a], self._b[a]))

    def scores(self, context: np.ndarray) -> np.ndarray:
        x = np.asarray(context, dtype=float)
        out = np.empty(self.n_actions)
        for a in range(self.n_actions):
            theta = self._theta(a)
            width = float(np.sqrt(x @ np.linalg.solve(self._A[a], x)))
            out[a] = float(theta @ x) + self.alpha * width
        return out

    def select(self, context: np.ndarray) -> int:
        return int(np.argmax(self.scores(context)))

    def update(self, context: np.ndarray, action: int, reward: float) -> None:
        x = np.asarray(context, dtype=float)
        self._A[action] += np.outer(x, x)
        self._b[action] += reward * x


@dataclass
class ThompsonGaussian:
    """Thompson sampling with a Gaussian reward model per arm (no
    context). Used where the decision has no useful features — e.g.
    choosing which FAMILY of research ideas to propose next (H2).

    Posterior over each arm's mean reward is Normal-Inverse-Gamma
    reduced to its practical form: track count, mean, and M2 (Welford),
    then sample from the implied Normal.
    """

    n_actions: int
    prior_mean: float = 0.0
    prior_sd: float = 1.0
    seed: int = 7
    counts: list[int] = field(default_factory=list)
    means: list[float] = field(default_factory=list)
    m2: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0] * self.n_actions
            self.means = [self.prior_mean] * self.n_actions
            self.m2 = [0.0] * self.n_actions
        self._rng = np.random.default_rng(self.seed)

    def _sd(self, a: int) -> float:
        n = self.counts[a]
        if n < 2:
            return self.prior_sd
        var = self.m2[a] / (n - 1)
        return float(np.sqrt(max(var, 1e-12) / n))  # standard error of the mean

    def sample(self) -> np.ndarray:
        return np.array(
            [self._rng.normal(self.means[a], max(self._sd(a), 1e-9)) for a in range(self.n_actions)]
        )

    def select(self, context: np.ndarray | None = None) -> int:
        return int(np.argmax(self.sample()))

    def update(self, context: np.ndarray | None, action: int, reward: float) -> None:
        self.counts[action] += 1
        n = self.counts[action]
        delta = reward - self.means[action]
        self.means[action] += delta / n
        self.m2[action] += delta * (reward - self.means[action])

    def state(self) -> dict[str, list[float] | list[int]]:
        return {"counts": self.counts, "means": self.means, "m2": self.m2}
