"""Test-wide isolation of the data root.

Found 2026-09-07: a plain `uv run pytest` appended 13 rows to the LIVE
`reports/paper/alerts.jsonl`, five of them "KILL SWITCH: trading frozen",
because `alert()` and `KillSwitch` resolve their paths through
`load_settings()` and most tests never repointed `ARTHA_DATA_DIR`. Running
the suite must not write into the operational ledger the heartbeat reads.

Integration modules bind their paths to the real data root at import time
(module-level `SETTINGS`), so their skip conditions are unaffected; tests
that need a specific root still override the variable themselves.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTHA_DATA_DIR", str(tmp_path / "artha-data"))
