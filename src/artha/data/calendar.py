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

    def is_live_rebalance_day(self, day: date, last_rebalance: date | None) -> bool:
        """Weekly rebalance decision for the LIVE path, decided at ``day``'s
        close with no knowledge of future sessions.

        ``week_last_days`` cannot answer this: the last session of an ISO week
        is only knowable once the week is over, and the live calendar always
        ends at today — so ``day in week_last_days()`` is true every single
        session and the book rebalances daily (bug found 2026-09-07).

        The knowable equivalent: Friday is the last session of every normal
        NSE week, and a session count caps the cadence at one week so a Friday
        holiday shifts the rebalance to that week's actual last session
        instead of skipping the week entirely.
        """
        if last_rebalance is None:
            return True
        if day <= last_rebalance:
            return False
        elapsed = len(self.sessions(self.next_trading_day(last_rebalance), day))
        return elapsed >= 5 or day.weekday() == 4
