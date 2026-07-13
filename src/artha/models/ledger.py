"""Multiple-testing ledger (plan 7.5): every experiment is a trial, forever.

Append-only JSONL in the reports dir. The deflated Sharpe ratio reads the
trial count from here; nothing is reported without its ledger context.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True)
class Trial:
    model: str
    label: str
    feature_set: str
    params: dict[str, object]
    mean_ic: float
    ic_t_stat: float
    net_sharpe: float | None = None
    notes: str = ""
    run_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class TrialLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, trial: Trial) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trial)) + "\n")

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with self.path.open(encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
