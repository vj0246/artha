"""Trading calendar derived from observed bhavcopy trading days.

The set of dates for which NSE published a bhavcopy IS the primary-source
trading calendar: it reflects holidays, ad hoc closures, and special sessions
without maintaining a separate holiday list. Point-in-time safe by
construction (a day is known to be a session only once its file exists).
"""

from bisect import bisect_left, bisect_right
from datetime import date

import polars as pl


class CalendarError(Exception):
    """Raised for queries outside the calendar's known range."""


class TradingCalendar:
    """Immutable, sorted set of trading days with navigation helpers."""

    def __init__(self, days: list[date]) -> None:
        if not days:
            raise CalendarError("empty calendar")
        self._days = sorted(set(days))

    @classmethod
    def from_frame(cls, frame: pl.DataFrame | pl.LazyFrame) -> "TradingCalendar":
        """Build from any frame with a ``trade_date`` column."""
        lf = frame.lazy() if isinstance(frame, pl.DataFrame) else frame
        days = lf.select(pl.col("trade_date").unique()).collect()["trade_date"].to_list()
        return cls(days)

    @property
    def days(self) -> list[date]:
        return list(self._days)

    @property
    def first(self) -> date:
        return self._days[0]

    @property
    def last(self) -> date:
        return self._days[-1]

    def is_trading_day(self, d: date) -> bool:
        i = bisect_left(self._days, d)
        return i < len(self._days) and self._days[i] == d

    def next_trading_day(self, d: date) -> date:
        """Smallest trading day strictly after ``d``."""
        i = bisect_right(self._days, d)
        if i == len(self._days):
            raise CalendarError(f"no trading day after {d} (calendar ends {self.last})")
        return self._days[i]

    def prev_trading_day(self, d: date) -> date:
        """Largest trading day strictly before ``d``."""
        i = bisect_left(self._days, d)
        if i == 0:
            raise CalendarError(f"no trading day before {d} (calendar starts {self.first})")
        return self._days[i - 1]

    def sessions(self, start: date, end: date) -> list[date]:
        """Trading days in [start, end], inclusive."""
        return self._days[bisect_left(self._days, start) : bisect_right(self._days, end)]

    def week_last_days(self) -> list[date]:
        """Last trading day of each ISO week: the weekly rebalance grid."""
        out: list[date] = []
        for d in self._days:
            key = d.isocalendar()[:2]
            if out and out[-1].isocalendar()[:2] == key:
                out[-1] = d
            else:
                out.append(d)
        return out
