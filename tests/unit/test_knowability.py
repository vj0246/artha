"""Knowability rule: 15:30 IST cutoff, weekends, holidays, calendar bounds."""

from datetime import date, datetime

import pytest

from artha.data.calendar import CalendarError, TradingCalendar
from artha.events.knowability import knowable_date

# Mon 2024-01-01 .. Fri 2024-01-05 with Wed 2024-01-03 a holiday
CAL = TradingCalendar(
    [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 5), date(2024, 1, 8)]
)


def test_before_close_is_same_day() -> None:
    assert knowable_date(datetime(2024, 1, 2, 9, 0), CAL) == date(2024, 1, 2)
    assert knowable_date(datetime(2024, 1, 2, 15, 29, 59), CAL) == date(2024, 1, 2)


def test_at_or_after_close_rolls_forward() -> None:
    # exactly 15:30 is NOT actionable at that close
    assert knowable_date(datetime(2024, 1, 2, 15, 30), CAL) == date(2024, 1, 4)
    assert knowable_date(datetime(2024, 1, 2, 22, 48), CAL) == date(2024, 1, 4)


def test_holiday_and_weekend_roll_forward() -> None:
    assert knowable_date(datetime(2024, 1, 3, 10, 0), CAL) == date(2024, 1, 4)  # holiday
    assert knowable_date(datetime(2024, 1, 6, 11, 0), CAL) == date(2024, 1, 8)  # Saturday
    assert knowable_date(datetime(2024, 1, 5, 18, 0), CAL) == date(2024, 1, 8)  # Fri evening


def test_beyond_calendar_raises() -> None:
    with pytest.raises(CalendarError):
        knowable_date(datetime(2024, 1, 8, 16, 0), CAL)
