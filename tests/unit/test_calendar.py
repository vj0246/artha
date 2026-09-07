"""Trading calendar: navigation, sessions, weekly rebalance grid."""

from datetime import date

import polars as pl
import pytest

from artha.data.calendar import CalendarError, TradingCalendar

# Mon 2024-01-01 .. Fri 2024-01-12 with Wed 2024-01-03 a holiday
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


@pytest.fixture
def cal() -> TradingCalendar:
    return TradingCalendar(DAYS)


def test_membership_and_bounds(cal: TradingCalendar) -> None:
    assert cal.is_trading_day(date(2024, 1, 2))
    assert not cal.is_trading_day(date(2024, 1, 3))  # holiday
    assert not cal.is_trading_day(date(2024, 1, 6))  # Saturday
    assert cal.first == date(2024, 1, 1)
    assert cal.last == date(2024, 1, 12)


def test_navigation_skips_holiday(cal: TradingCalendar) -> None:
    assert cal.next_trading_day(date(2024, 1, 2)) == date(2024, 1, 4)
    assert cal.prev_trading_day(date(2024, 1, 4)) == date(2024, 1, 2)
    # non-trading anchor dates work too
    assert cal.next_trading_day(date(2024, 1, 6)) == date(2024, 1, 8)
    assert cal.prev_trading_day(date(2024, 1, 3)) == date(2024, 1, 2)


def test_navigation_out_of_range(cal: TradingCalendar) -> None:
    with pytest.raises(CalendarError):
        cal.next_trading_day(date(2024, 1, 12))
    with pytest.raises(CalendarError):
        cal.prev_trading_day(date(2024, 1, 1))


def test_sessions_inclusive(cal: TradingCalendar) -> None:
    assert cal.sessions(date(2024, 1, 2), date(2024, 1, 8)) == [
        date(2024, 1, 2),
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 8),
    ]


def test_week_last_days(cal: TradingCalendar) -> None:
    assert cal.week_last_days() == [date(2024, 1, 5), date(2024, 1, 12)]


def test_live_rebalance_grid_is_weekly_not_daily(cal: TradingCalendar) -> None:
    """Regression (2026-09-07): the live runbook asked ``today in
    week_last_days()``, but the live calendar always ENDS at today, so the
    last day of the trailing partial week is always today — the paper book
    rebalanced every session at ~5x the researched turnover."""
    fired = []
    last = None
    for day in cal.days:
        # each session sees only history up to itself, as the runbook does
        live = TradingCalendar(cal.sessions(cal.first, day))
        if live.is_live_rebalance_day(day, last):
            fired.append(day)
            last = day
    assert fired == [date(2024, 1, 1), date(2024, 1, 5), date(2024, 1, 12)]


def test_live_rebalance_survives_a_friday_holiday() -> None:
    """Fri 2024-01-05 closed: the week's last session is Thu 2024-01-04.
    A bare weekday==4 rule would skip the week; the session-count fallback
    rebalances on the next session instead of waiting two weeks."""
    days = [date(2023, 12, 29), date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]
    days += [date(2024, 1, 4), date(2024, 1, 8), date(2024, 1, 9)]
    cal = TradingCalendar(days)
    assert not cal.is_live_rebalance_day(date(2024, 1, 4), date(2023, 12, 29))
    assert cal.is_live_rebalance_day(date(2024, 1, 8), date(2023, 12, 29))


def test_live_rebalance_first_ever_session_trades(cal: TradingCalendar) -> None:
    assert cal.is_live_rebalance_day(date(2024, 1, 2), None)
    # and a same-day rerun never re-fires
    assert not cal.is_live_rebalance_day(date(2024, 1, 2), date(2024, 1, 2))


def test_from_frame_dedupes() -> None:
    frame = pl.DataFrame({"trade_date": [date(2024, 1, 2), date(2024, 1, 2), date(2024, 1, 1)]})
    cal = TradingCalendar.from_frame(frame)
    assert cal.days == [date(2024, 1, 1), date(2024, 1, 2)]


def test_empty_rejected() -> None:
    with pytest.raises(CalendarError):
        TradingCalendar([])
