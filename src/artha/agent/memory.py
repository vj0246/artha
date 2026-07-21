"""H2: the research agent's memory — learning which ideas are worth trying.

The B6 agent proposes candidate features, screens them, and ledgers
every screen — but it had no memory: it proposed the same seeds forever
and never learned which KINDS of idea had paid off. This module gives
it one.

Each proposal belongs to a FAMILY (volatility structure, liquidity,
range/position, reversal, seasonality). A Thompson-sampling bandit
keeps a posterior over each family's mean IC improvement, rebuilt from
the trial ledger itself — the system's own recorded history — so each
scheduled run proposes more from families that have historically helped
and fewer from those that have not.

Why this is the safe form of self-improvement: the loop compounds
KNOWLEDGE without compounding RISK. The agent never edits the live
book; a candidate still graduates only through a full model study by
hand, and every screen it runs is still ledgered, so the
multiple-testing accounting stays honest as the loop iterates.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from artha.rl.bandits import ThompsonGaussian

FAMILIES: Final[list[str]] = [
    "vol_structure",
    "liquidity",
    "range_position",
    "reversal",
    "seasonality",
]

# substrings that identify a family from a proposal's expression/name;
# first match wins, unmatched proposals fall back to vol_structure
_FAMILY_HINTS: Final[list[tuple[str, tuple[str, ...]]]] = [
    ("liquidity", ("traded_value", "illiq", "amihud", "turnover")),
    ("range_position", ("roll_max", "roll_min", "range", "52w", "dist_")),
    ("reversal", ("rev_", "reversal", "-dret", "- dret")),
    ("seasonality", ("month", "day_of", "seasonal")),
    ("vol_structure", ("roll_std", "vol", "atr", "downside")),
]


def classify_family(name: str, expression: str) -> str:
    """Best-effort family label for a proposal (never raises)."""
    blob = f"{name} {expression}".lower()
    for family, hints in _FAMILY_HINTS:
        if any(h in blob for h in hints):
            return family
    return "vol_structure"


@dataclass
class AgentMemory:
    """Persistent Thompson bandit over proposal families."""

    path: Path
    bandit: ThompsonGaussian

    @classmethod
    def load(cls, path: Path, *, seed: int = 7) -> "AgentMemory":
        bandit = ThompsonGaussian(n_actions=len(FAMILIES), prior_sd=0.01, seed=seed)
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            counts = state.get("counts", [])
            if len(counts) == len(FAMILIES):
                bandit.counts = counts
                bandit.means = state.get("means", bandit.means)
                bandit.m2 = state.get("m2", bandit.m2)
        return cls(path=path, bandit=bandit)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "families": FAMILIES,
            **{k: list(v) for k, v in self.bandit.state().items()},
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def record(self, family: str, delta_ic: float) -> None:
        """Update the posterior with a screen's realised IC improvement."""
        if family in FAMILIES:
            self.bandit.update(None, FAMILIES.index(family), delta_ic)

    def rank(self) -> list[str]:
        """Families in the order the agent would try them next (one
        Thompson draw, so exploration survives)."""
        draws = self.bandit.sample()
        return [FAMILIES[i] for i in sorted(range(len(FAMILIES)), key=lambda i: -draws[i])]

    def summary(self) -> dict[str, dict[str, float]]:
        return {
            fam: {
                "screens": float(self.bandit.counts[i]),
                "mean_delta_ic": float(self.bandit.means[i]),
            }
            for i, fam in enumerate(FAMILIES)
        }


def rebuild_from_ledger(path: Path, ledger_path: Path, *, seed: int = 7) -> AgentMemory:
    """Reconstruct memory from the ledger's own screen history.

    The ledger is the system's record of every experiment ever run, so
    the agent's memory is derived from evidence rather than kept as a
    separate mutable belief that could drift from what actually
    happened. Screens are identified by their feature_set naming
    (``library_v1+<name>``) and their recorded delta_ic note.
    """
    memory = AgentMemory.load(path, seed=seed)
    memory.bandit.counts = [0] * len(FAMILIES)
    memory.bandit.means = [0.0] * len(FAMILIES)
    memory.bandit.m2 = [0.0] * len(FAMILIES)
    if not ledger_path.exists():
        return memory
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        feature_set = str(row.get("feature_set", ""))
        notes = str(row.get("notes", ""))
        if "library_v1+" not in feature_set or "delta_ic=" not in notes:
            continue
        name = feature_set.split("library_v1+", 1)[1]
        try:
            delta = float(notes.split("delta_ic=", 1)[1].split()[0].rstrip(";,"))
        except (IndexError, ValueError):
            continue
        memory.record(classify_family(name, name), delta)
    return memory
