"""P1 gate regression checks against the real curated panel.

Runs only where the curated zone exists (skipped in CI); `scripts/build_curated.py`
must have completed. These anchors are known corporate actions verified against
NSE's declared CA records on 2026-07-09 (ADR 0005).
"""

from datetime import date

import polars as pl
import pytest

from artha.config import load_settings

SETTINGS = load_settings()
PANEL_PATH = SETTINGS.curated_dir / "panel.parquet"
EVENTS_PATH = SETTINGS.curated_dir / "ca_events.parquet"

pytestmark = pytest.mark.skipif(
    not (PANEL_PATH.exists() and EVENTS_PATH.exists()),
    reason="curated zone not built on this machine",
)

# (canon_symbol, ex_date, expected factor): NSE-declared bonuses
ANCHORS = [
    ("RELIANCE", date(2024, 10, 28), 0.5),  # Bonus 1:1, UDiFF era
    ("INFY", date(2015, 6, 15), 0.5),  # Bonus 1:1, old era
    ("WIPRO", date(2017, 6, 13), 0.5),  # Bonus 1:1
]


@pytest.fixture(scope="module")
def panel() -> pl.DataFrame:
    return pl.read_parquet(PANEL_PATH)


@pytest.fixture(scope="module")
def events() -> pl.DataFrame:
    return pl.read_parquet(EVENTS_PATH)


@pytest.mark.parametrize(("symbol", "ex_date", "factor"), ANCHORS)
def test_anchor_event_present(
    events: pl.DataFrame, symbol: str, ex_date: date, factor: float
) -> None:
    ev = events.filter((pl.col("canon_symbol") == symbol) & (pl.col("ex_date") == ex_date))
    assert ev.height == 1
    assert ev["factor"][0] == pytest.approx(factor, abs=0.01)


@pytest.mark.parametrize(("symbol", "ex_date", "factor"), ANCHORS)
def test_adjusted_series_continuous_across_anchor(
    panel: pl.DataFrame, symbol: str, ex_date: date, factor: float
) -> None:
    r = (
        panel.filter(pl.col("canon_symbol") == symbol)
        .sort("trade_date")
        .with_columns((pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).alias("r"))
        .filter(pl.col("trade_date") == ex_date)
    )["r"][0]
    assert abs(r) < 0.12  # a bonus day must not look like a -50% return


def test_infy_rename_unified(panel: pl.DataFrame) -> None:
    infy = panel.filter(pl.col("canon_symbol") == "INFY")
    assert infy.filter(pl.col("trade_date") < date(2011, 6, 29)).height > 300
    assert panel.filter(pl.col("canon_symbol") == "INFOSYSTCH").is_empty()
    assert infy.height == infy["trade_date"].n_unique()


def test_all_factors_in_range(events: pl.DataFrame) -> None:
    assert events.filter((pl.col("factor") <= 0) | (pl.col("factor") >= 1)).is_empty()


def test_panel_shape_floor(panel: pl.DataFrame) -> None:
    # survivorship-free: far more instruments than currently listed
    assert panel["canon_symbol"].n_unique() > 3000
    assert panel["trade_date"].n_unique() > 4000
    assert panel["trade_date"].min() == date(2010, 1, 4)
