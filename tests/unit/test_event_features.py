"""Event features: vectorized knowability, as-of anchoring, rolling counts."""

import math
from datetime import date, datetime

import polars as pl
import pytest

from artha.data.calendar import TradingCalendar
from artha.events.features import EVENT_FEATURES, build_event_features, knowable_dates
from artha.events.taxonomy import classify_frame

# Mon 2024-01-01 .. Fri 2024-01-12, Wed 03 holiday
DAYS = [
    date(2024, 1, 1),
    date(2024, 1, 2),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8),
    date(2024, 1, 9),
    date(2024, 1, 10),
    date(2024, 1, 11),
    date(2024, 1, 12),
]
CAL = TradingCalendar(DAYS)


def test_classify_frame_matches_scalar_rules() -> None:
    df = pl.DataFrame(
        {
            "subject": [
                "Unaudited Financial Results for the quarter",
                "Disclosure of pledge of shares",
                "Trading window closure",
                None,
            ]
        }
    )
    out = classify_frame(df)
    assert out["category"].to_list() == ["earnings_result", "pledge", "other", "other"]
    assert out["direction"].to_list() == [0, -1, 0, 0]
    assert out["materiality"].to_list() == [2, 1, 0, 0]


def test_knowable_dates_vectorized() -> None:
    frame = pl.DataFrame(
        {
            "announced_at": [
                datetime(2024, 1, 2, 9, 0),  # session, before close -> same day
                datetime(2024, 1, 2, 16, 0),  # after close -> next session (4th)
                datetime(2024, 1, 3, 10, 0),  # holiday -> next session (4th)
                datetime(2024, 1, 6, 11, 0),  # Saturday -> Monday 8th
                datetime(2024, 1, 12, 16, 0),  # beyond calendar -> dropped
            ]
        }
    )
    out = knowable_dates(frame, CAL, "announced_at").sort("announced_at")
    assert out.height == 4
    assert out["knowable_date"].to_list() == [
        date(2024, 1, 2),
        date(2024, 1, 4),
        date(2024, 1, 4),
        date(2024, 1, 8),
    ]


def test_build_event_features_anchors_and_counts() -> None:
    grid = pl.DataFrame(
        {
            "canon_symbol": ["A"] * 3,
            "trade_date": [date(2024, 1, 5), date(2024, 1, 10), date(2024, 1, 12)],
        }
    )
    events = pl.DataFrame(
        {
            "canon_symbol": ["A", "A"],
            "knowable_date": [date(2024, 1, 4), date(2024, 1, 9)],
            "category": ["earnings_result", "pledge"],
            "direction": [0, -1],
            "materiality": [2, 1],
        }
    )
    meetings = pl.DataFrame(
        {
            "canon_symbol": ["A"],
            "meeting_date": [date(2024, 1, 11)],
            "intimation_knowable_date": [date(2024, 1, 8)],
        }
    )
    abnormal = pl.DataFrame(
        {
            "canon_symbol": ["A", "A"],
            "trade_date": [date(2024, 1, 4), date(2024, 1, 9)],
            "ar": [0.05, -0.02],
        }
    )
    out = build_event_features(grid, events, meetings, abnormal).sort("trade_date")
    assert out.columns == ["canon_symbol", "trade_date", *EVENT_FEATURES]

    jan5 = out.row(0, named=True)
    # last event Jan 4 earnings: 1 day since, AR +5%
    assert jan5["days_since_event"] == pytest.approx(math.log1p(1.0))
    assert jan5["last_event_ar"] == pytest.approx(0.05)
    assert jan5["event_count_63d"] == 1.0
    assert jan5["neg_count_63d"] == 0.0
    # meeting intimated Jan 8 -> not knowable on Jan 5 -> capped
    assert jan5["days_to_board_meeting"] == pytest.approx(math.log1p(126.0))

    jan10 = out.row(1, named=True)
    assert jan10["last_event_ar"] == pytest.approx(-0.02)  # pledge day AR
    assert jan10["event_count_63d"] == 2.0
    assert jan10["neg_count_63d"] == 1.0
    assert jan10["pledge_63d"] == 1.0
    # meeting on the 11th, knowable since the 8th: 1 day away
    assert jan10["days_to_board_meeting"] == pytest.approx(math.log1p(1.0))

    jan12 = out.row(2, named=True)
    # meeting passed: forward as-of finds nothing -> capped
    assert jan12["days_to_board_meeting"] == pytest.approx(math.log1p(126.0))
    # earnings older than the pledge: Jan 4 vs Jan 9 anchors
    assert jan12["days_since_earnings"] > jan12["days_since_event"]
