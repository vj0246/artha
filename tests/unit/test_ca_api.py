"""CA API ingest: parsing, subject-to-factor mapping, implied-vs-declared cross-check."""

import json
from datetime import date

import polars as pl
import pytest

from artha.data.ingest.ca_api import (
    ca_month_relpath,
    ca_month_url,
    cross_check,
    declared_factor_events,
    expected_factor,
    parse_ca_records,
)

SAMPLE = [
    {
        "symbol": "RELIANCE",
        "series": "EQ",
        "isin": "INE002A01018",
        "comp": "Reliance Industries Limited",
        "subject": "Bonus 1:1",
        "exDate": "28-Oct-2024",
        "recDate": "28-Oct-2024",
        "faceVal": "10",
    },
    {
        "symbol": "DIVI",
        "series": "EQ",
        "isin": "INE361B01024",
        "comp": "Divi's Laboratories Limited",
        "subject": "Interim Dividend - Rs 12 Per Share",
        "exDate": "25-Oct-2024",
        "recDate": "-",
        "faceVal": "2",
    },
]


def test_url_and_relpath() -> None:
    d = date(2024, 10, 15)
    assert ca_month_relpath(d) == "ca_api/2024/ca_202410.json"
    url = ca_month_url(d)
    assert "from_date=01-10-2024" in url
    assert "to_date=31-10-2024" in url
    assert "index=equities" in url


def test_parse_records() -> None:
    df = parse_ca_records(json.dumps(SAMPLE).encode())
    assert df.height == 2
    rel = df.filter(symbol="RELIANCE").row(0, named=True)
    assert rel["ex_date"] == date(2024, 10, 28)
    assert rel["subject"] == "Bonus 1:1"
    # '-' record date becomes null
    assert df.filter(symbol="DIVI").row(0, named=True)["record_date"] is None


def test_parse_empty_list() -> None:
    df = parse_ca_records(b"[]")
    assert df.is_empty()
    assert "ex_date" in df.columns


def test_parse_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="not a list"):
        parse_ca_records(b'{"blocked": true}')


class TestExpectedFactor:
    def test_bonus(self) -> None:
        assert expected_factor("Bonus 1:1") == 0.5
        assert expected_factor("Bonus 3:2") == pytest.approx(0.4)
        assert expected_factor("Bonus 1:4") == pytest.approx(0.8)

    def test_split(self) -> None:
        assert expected_factor("Face Value Split From Rs 10/- To Re 1/-") == pytest.approx(0.1)
        assert expected_factor("Face Value Split From Rs 2/- To Re 1/-") == pytest.approx(0.5)

    def test_not_derivable(self) -> None:
        assert expected_factor("Interim Dividend - Rs 12 Per Share") is None
        assert expected_factor("Rights 119:758 @ Premium Rs 218/-") is None
        assert expected_factor("Annual General Meeting") is None
        # consolidation (y > x) is not a split factor
        assert expected_factor("Face Value Split From Re 1/- To Rs 10/-") is None


def test_declared_factor_events_filters_and_dedupes() -> None:
    ca = parse_ca_records(json.dumps([*SAMPLE, SAMPLE[0]]).encode())
    events = declared_factor_events(ca)
    assert events.height == 1
    ev = events.row(0, named=True)
    assert ev["symbol"] == "RELIANCE"
    assert ev["factor"] == 0.5


def test_cross_check() -> None:
    implied = pl.DataFrame(
        {
            "canon_symbol": ["RELIANCE", "GHOST"],
            "ex_date": [date(2024, 10, 28), date(2024, 5, 2)],
            "factor": [0.501, 0.25],
        }
    )
    declared = pl.DataFrame(
        {
            "symbol": ["RELIANCE", "MISSED"],
            "ex_date": [date(2024, 10, 28), date(2024, 6, 3)],
            "subject": ["Bonus 1:1", "Bonus 1:1"],
            "factor": [0.5, 0.5],
        }
    )
    out = cross_check(implied, declared)
    # 0.501 vs 0.5 is inside 2% tolerance
    assert out["factor_mismatch"].is_empty()
    # declared MISSED has no implied event; implied-only GHOST is not reported
    assert out["declared_missing_implied"]["canon_symbol"].to_list() == ["MISSED"]

    tight = cross_check(implied, declared, rel_tolerance=0.001)
    assert tight["factor_mismatch"]["canon_symbol"].to_list() == ["RELIANCE"]
