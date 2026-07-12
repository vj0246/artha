"""Events ingest: relpaths, parsers on probe-shaped payloads."""

import json
from datetime import date, datetime

import pytest

from artha.events.ingest import (
    EventParseError,
    announcements_relpath,
    board_meetings_relpath,
    bulk_deals_relpath,
    parse_announcements,
    parse_board_meetings,
    parse_bulk_deals,
)

ANN = [
    {
        "an_dt": "05-Jul-2026 22:48:03",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/FEDERALBNK_x.pdf",
        "attchmntText": "Allotment of Equity Shares pursuant to ESOS",
        "desc": "General",
        "smIndustry": "Private Sector Bank",
        "sm_isin": "INE171A01029",
        "sm_name": "The Federal Bank Limited",
        "seq_id": 8811452,
        "symbol": "FEDERALBNK",
    },
    {
        "an_dt": "07-Jun-2010 18:20:00",
        "attchmntFile": "-",
        "attchmntText": "AGM on July 15, 2010",
        "desc": "AGM",
        "smIndustry": None,
        "sm_isin": "INE511C01022",
        "sm_name": "Magma Fincorp Limited",
        "seq_id": None,
        "symbol": "MAGMA",
    },
]

BM = [
    {
        "bm_symbol": "APARINDS",
        "bm_date": "30-Jun-2026",
        "bm_purpose": "Board Meeting Intimation",
        "bm_desc": "Board Meeting to consider Fund raising.",
        "sm_isin": "INE372A01015",
        "bm_timestamp": "24-Jun-2026 17:28:02",
    },
    {
        "bm_symbol": "ALICON",
        "bm_date": "30-Jun-2012",
        "bm_purpose": "Bonus",
        "bm_desc": "To consider the issue of bonus shares.",
        "sm_isin": "INE062D01024",
        "bm_timestamp": None,
    },
]

BULK = {
    "data": [
        {
            "BD_DT_DATE": "01-JUN-2026",
            "BD_SYMBOL": "AERONEU",
            "BD_CLIENT_NAME": "JAINAM BROKING LIMITED",
            "BD_BUY_SELL": "SELL",
            "BD_QTY_TRD": 157000,
            "BD_TP_WATP": 90.5,
            "BD_REMARKS": "-",
        }
    ]
}


def test_relpaths() -> None:
    d = date(2024, 7, 15)
    assert announcements_relpath(d) == "events/announcements/2024/ann_202407.json"
    assert board_meetings_relpath(d) == "events/board_meetings/2024/bm_202407.json"
    assert bulk_deals_relpath(d) == "events/bulk_deals/2024/bulk_202407.json"


def test_parse_announcements() -> None:
    df = parse_announcements(json.dumps(ANN).encode())
    assert df.height == 2
    first = df.row(0, named=True)  # sorted by announced_at
    assert first["symbol"] == "MAGMA"
    assert first["announced_at"] == datetime(2010, 6, 7, 18, 20)
    assert first["attachment_url"] is None  # '-' normalized
    assert first["seq_id"] is None
    fed = df.row(1, named=True)
    assert fed["announced_at"] == datetime(2026, 7, 5, 22, 48, 3)
    assert fed["seq_id"] == "8811452"
    assert fed["category"] == "General"


def test_parse_announcements_empty_and_invalid() -> None:
    assert parse_announcements(b"[]").is_empty()
    with pytest.raises(EventParseError, match="not a list"):
        parse_announcements(b'{"blocked": true}')


def test_parse_board_meetings() -> None:
    df = parse_board_meetings(json.dumps(BM).encode())
    assert df.height == 2
    old = df.row(0, named=True)
    assert old["meeting_date"] == date(2012, 6, 30)
    assert old["purpose"] == "Bonus"
    assert old["intimated_at"] is None
    assert df.row(1, named=True)["intimated_at"] == datetime(2026, 6, 24, 17, 28, 2)


def test_parse_bulk_deals() -> None:
    df = parse_bulk_deals(json.dumps(BULK).encode())
    row = df.row(0, named=True)
    assert row["trade_date"] == date(2026, 6, 1)
    assert row["side"] == "SELL"
    assert row["quantity"] == 157000
    assert row["wavg_price"] == 90.5
    assert row["remarks"] is None
    with pytest.raises(EventParseError, match="no 'data' key"):
        parse_bulk_deals(b"[]")
