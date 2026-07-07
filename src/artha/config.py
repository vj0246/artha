"""Runtime configuration.

Data lives outside the repository (and outside OneDrive — see ADR 0001).
Location comes from the ARTHA_DATA_DIR environment variable, defaulting to
~/quant-data.
"""

import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "ARTHA_DATA_DIR"


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def curated_dir(self) -> Path:
        return self.data_dir / "curated"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


def load_settings() -> Settings:
    raw = os.environ.get(DATA_DIR_ENV)
    data_dir = Path(raw) if raw else Path.home() / "quant-data"
    return Settings(data_dir=data_dir)
