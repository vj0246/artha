"""Event features for the Model A vs B test (plan v2 section 12.3).

Every feature is anchored on the event's KNOWABLE date (15:30 IST rule,
vectorized here against the trading calendar), so a signal computed at day
t's close sees only events knowable at or before t. Board-meeting proximity
uses only meetings whose intimation was knowable by t.

Features (all per canon_symbol, trade_date on the weekly grid):
- days_since_event / days_since_earnings (log1p, capped)
- last_event_ar: market-adjusted abnormal return on the most recent event's
  day 0 (the surprise proxy of section 12.3)
- event_count_63d, neg_count_63d, pos_count_63d
- pledge_63d, litigation_63d flags
- days_to_board_meeting (known in advance; capped)
"""

from datetime import time
from typing import Final

import polars as pl

from artha.data.calendar import TradingCalendar

MARKET_CLOSE: Final = time(15, 30)
CAP_DAYS: Final = 126.0

EVENT_FEATURES: Final = [
    "days_since_event",
    "days_since_earnings",
    "last_event_ar",
    "event_count_63d",
    "neg_count_63d",
    "pos_count_63d",
    "pledge_63d",
    "litigation_63d",
    "days_to_board_meeting",
]


def knowable_dates(frame: pl.DataFrame, cal: TradingCalendar, ts_col: str) -> pl.DataFrame:
    """Vectorized knowability: adds ``knowable_date`` from a timestamp column.

    Same rule as events.knowability.knowable_date: before 15:30 on a session
    -> that session; otherwise the first session STRICTLY after the
    calendar date. Rows beyond the calendar end drop.
    """
    days = cal.days
    sessions = pl.DataFrame({"_session": days}).sort("_session")
    out = (
        frame.with_columns(
            pl.col(ts_col).dt.date().alias("_d"),
            (pl.col(ts_col).dt.time() < MARKET_CLOSE).alias("_before_close"),
        )
        .with_columns((pl.col("_d") + pl.duration(days=1)).alias("_dplus"))
        .sort("_dplus")
        .join_asof(sessions, left_on="_dplus", right_on="_session", strategy="forward")
    )
    same_day_ok = pl.col("_before_close") & pl.col("_d").is_in(days)
    return (
        out.with_columns(
            pl.when(same_day_ok)
            .then(pl.col("_d"))
            .otherwise(pl.col("_session"))
            .alias("knowable_date")
        )
        .filter(pl.col("knowable_date").is_not_null())
        .drop("_d", "_dplus", "_session", "_before_close")
    )


def _last_event_join(
    grid: pl.DataFrame, events: pl.DataFrame, value_cols: list[str], suffix: str
) -> pl.DataFrame:
    """As-of join: for each grid row, the most recent event at or before t."""
    ev = events.sort("knowable_date").select(
        "canon_symbol", pl.col("knowable_date").alias(f"_ev_date{suffix}"), *value_cols
    )
    return grid.sort("trade_date").join_asof(
        ev,
        left_on="trade_date",
        right_on=f"_ev_date{suffix}",
        by="canon_symbol",
        strategy="backward",
    )


def build_event_features(
    grid: pl.DataFrame,
    events: pl.DataFrame,
    meetings: pl.DataFrame,
    abnormal: pl.DataFrame,
) -> pl.DataFrame:
    """``grid``: (canon_symbol, trade_date) rows to featurize.
    ``events``: classified announcements with knowable_date, category,
    direction, materiality. ``meetings``: (canon_symbol, meeting_date,
    intimation_knowable_date). ``abnormal``: (canon_symbol, trade_date, ar).
    """
    ev = events.join(
        abnormal.select("canon_symbol", pl.col("trade_date").alias("knowable_date"), pl.col("ar")),
        on=["canon_symbol", "knowable_date"],
        how="left",
    )

    out = _last_event_join(grid, ev.select("canon_symbol", "knowable_date", "ar"), ["ar"], "_any")
    out = out.rename({"ar": "_last_ar"}).with_columns(
        (pl.col("trade_date") - pl.col("_ev_date_any")).dt.total_days().alias("_dse")
    )
    earnings = ev.filter(pl.col("category") == "earnings_result")
    out = _last_event_join(
        out, earnings.select("canon_symbol", "knowable_date"), [], "_earn"
    ).with_columns(
        (pl.col("trade_date") - pl.col("_ev_date_earn")).dt.total_days().alias("_dse_earn")
    )

    # rolling 63-calendar-day counts: cumulative event count as-of t minus
    # as-of t-63d (two backward as-of joins; no row explosion)
    def _count(events_subset: pl.DataFrame, name: str) -> pl.DataFrame:
        cum = (
            events_subset.group_by("canon_symbol", "knowable_date")
            .len()
            .sort("canon_symbol", "knowable_date")
            .with_columns(pl.col("len").cum_sum().over("canon_symbol").alias("_cum"))
            .select("canon_symbol", pl.col("knowable_date").alias("_kd"), "_cum")
            .sort("_kd")
        )
        base = out.select(
            "canon_symbol",
            "trade_date",
            (pl.col("trade_date") - pl.duration(days=63)).alias("_t63"),
        )
        at_t = base.sort("trade_date").join_asof(
            cum, left_on="trade_date", right_on="_kd", by="canon_symbol", strategy="backward"
        )
        at_t63 = (
            base.sort("_t63")
            .join_asof(
                cum.rename({"_cum": "_cum63"}),
                left_on="_t63",
                right_on="_kd",
                by="canon_symbol",
                strategy="backward",
            )
            .select("canon_symbol", "trade_date", "_cum63")
        )
        return (
            at_t.join(at_t63, on=["canon_symbol", "trade_date"], how="left")
            .with_columns((pl.col("_cum").fill_null(0) - pl.col("_cum63").fill_null(0)).alias(name))
            .select("canon_symbol", "trade_date", name)
        )

    for subset, name in [
        (ev, "event_count_63d"),
        (ev.filter(pl.col("direction") == -1), "neg_count_63d"),
        (ev.filter(pl.col("direction") == 1), "pos_count_63d"),
        (ev.filter(pl.col("category") == "pledge"), "pledge_63d"),
        (ev.filter(pl.col("category") == "litigation_regulatory"), "litigation_63d"),
    ]:
        out = out.join(_count(subset, name), on=["canon_symbol", "trade_date"], how="left")

    # next board meeting known by t: smallest meeting_date >= t with
    # intimation knowable <= t. As-of forward join on meeting_date after
    # filtering intimations is not expressible directly; approximate with a
    # forward as-of on meeting_date, then null out not-yet-intimated rows.
    mt = meetings.sort("meeting_date").select(
        "canon_symbol",
        pl.col("meeting_date").alias("_mt_date"),
        pl.col("intimation_knowable_date").alias("_mt_known"),
    )
    out = out.sort("trade_date").join_asof(
        mt,
        left_on="trade_date",
        right_on="_mt_date",
        by="canon_symbol",
        strategy="forward",
    )
    dtb = (
        pl.when(pl.col("_mt_known") <= pl.col("trade_date"))
        .then((pl.col("_mt_date") - pl.col("trade_date")).dt.total_days())
        .otherwise(None)
    )

    return out.with_columns(
        pl.col("_dse").clip(0, CAP_DAYS).fill_null(CAP_DAYS).log1p().alias("days_since_event"),
        pl.col("_dse_earn")
        .clip(0, CAP_DAYS)
        .fill_null(CAP_DAYS)
        .log1p()
        .alias("days_since_earnings"),
        pl.col("_last_ar").fill_null(0.0).alias("last_event_ar"),
        *(
            pl.col(c).fill_null(0).cast(pl.Float64).alias(c)
            for c in (
                "event_count_63d",
                "neg_count_63d",
                "pos_count_63d",
                "pledge_63d",
                "litigation_63d",
            )
        ),
        dtb.clip(0, CAP_DAYS).fill_null(CAP_DAYS).log1p().alias("days_to_board_meeting"),
    ).select("canon_symbol", "trade_date", *EVENT_FEATURES)
