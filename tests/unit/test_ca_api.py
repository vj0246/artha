"""CA API ingest: parsing and subject-to-factor mapping."""

import json
from datetime import date

import pytest

from artha.data.ingest.ca_api import (
    ca_month_relpath,
    ca_month_url,
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

    def test_combined_bonus_and_split_subject_multiplies(self) -> None:
        assert expected_factor(
            "Bonus 1:1 / Face Value Split From Rs.10/- To Re.1/-"
        ) == pytest.approx(0.05)
        assert expected_factor(
            " Bonus 1:1/Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/-"
        ) == pytest.approx(0.1)

    def test_older_subject_styles(self) -> None:
        # 2010-era feed wording
        assert expected_factor("Fv Split Rs.10 To Re.1") == pytest.approx(0.1)
        assert expected_factor(
            "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share"
        ) == pytest.approx(0.2)
        assert expected_factor("Bonus-1:2") == pytest.approx(2 / 3)

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


def test_declared_gap_events_selects_unparseable_discontinuities() -> None:
    from artha.data.ingest.ca_api import declared_gap_events

    records = [
        {**SAMPLE[0], "subject": "Demerger"},
        {**SAMPLE[1], "subject": " Rights 1:14 @ Premium Rs 530/-"},
        {**SAMPLE[1], "subject": "Interim Dividend - Rs 12 Per Share", "exDate": "30-Oct-2024"},
    ]
    gaps = declared_gap_events(parse_ca_records(json.dumps(records).encode()))
    assert gaps.height == 2
    assert set(gaps["symbol"].to_list()) == {"RELIANCE", "DIVI"}


def test_same_symbol_two_subjects_same_day_both_survive() -> None:
    records = [
        {**SAMPLE[0], "subject": "Bonus 1:1"},
        {**SAMPLE[0], "subject": "Face Value Split From Rs 10 To Re 1"},
    ]
    events = declared_factor_events(parse_ca_records(json.dumps(records).encode()))
    assert events.height == 2
    assert sorted(events["factor"].to_list()) == [0.1, 0.5]
