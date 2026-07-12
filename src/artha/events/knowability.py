"""The knowability rule (plan v2 section 5.1).

An announcement is knowable for trading day D when a signal computed at D's
close could have seen it: exchange receipt strictly before the 15:30 IST
close on a trading day belongs to that day; anything later, or anything on
a non-trading day, belongs to the next trading day. Every event feature must
date events by ``knowable_date``, never by the raw timestamp's calendar day.
The lookahead suite (P2+) tests this boundary.
"""

from datetime import date, datetime, time
from typing import Final

from artha.data.calendar import TradingCalendar

MARKET_CLOSE: Final = time(15, 30)


def knowable_date(announced_at: datetime, cal: TradingCalendar) -> date:
    """First trading day whose close could react to this announcement.

    Raises CalendarError when the announcement falls beyond the calendar's
    last known session (extend the calendar before building features).
    """
    d = announced_at.date()
    if cal.is_trading_day(d) and announced_at.time() < MARKET_CLOSE:
        return d
    return cal.next_trading_day(d)
