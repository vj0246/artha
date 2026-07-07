"""Settings: env override and derived paths."""

from pathlib import Path

import pytest

from artha.config import DATA_DIR_ENV, load_settings


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, r"C:\quant-data")
    s = load_settings()
    assert s.data_dir == Path(r"C:\quant-data")
    assert s.raw_dir == Path(r"C:\quant-data") / "raw"
    assert s.curated_dir == Path(r"C:\quant-data") / "curated"
    assert s.reports_dir == Path(r"C:\quant-data") / "reports"


def test_default_is_home_quant_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    assert load_settings().data_dir == Path.home() / "quant-data"
