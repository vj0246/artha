"""Corporate-action adjustment from the declared CA feed (ADR 0005).

Full-history validation falsified ADR 0003: the bhavcopy PREVCLOSE is the
raw prior close in BOTH formats (INFY bonus 2015, WIPRO bonus 2017, RELIANCE
bonus 2024 all show unadjusted base prices), so no implied factor exists in
primary price data. Factors come from the declared corporate-actions feed:
parsed ratios for bonuses and face-value splits, observed ex-date price gaps
for demergers/rights/capital reductions (dates gated by the feed, so no
phantom events). The QA return-outlier scan remains the catch-all.

Backward adjustment: prices strictly before an ex-date are multiplied by the
product of all later factors; volumes are divided by it.
"""

from typing import Final

import polars as pl

# Continuous cash-equity series: normal, trade-for-trade, surveillance.
EQUITY_SERIES: Final = ("EQ", "BE", "BZ")
_SERIES_PRIORITY: Final = {"EQ": 0, "BE": 1, "BZ": 2}

_MAX_RENAME_CHAIN: Final = 6


def canonicalize_symbols(
    frame: pl.DataFrame, symbol_changes: pl.DataFrame, *, date_col: str
) -> pl.DataFrame:
    """Rewrite ``canon_symbol`` to each row's terminal ticker, date-aware.

    A rename at date d applies to rows strictly before d, so symbols later
    reused by other companies are untouched. Handles chains (A -> B -> C).
    """
    known = set(frame["canon_symbol"].unique().to_list()) | set(
        symbol_changes["new_symbol"].to_list()
    )
    relevant = symbol_changes.filter(pl.col("old_symbol").is_in(sorted(known))).sort("change_date")
    for _ in range(_MAX_RENAME_CHAIN):
        before = frame["canon_symbol"]
        for old, new, change_date in relevant.select(
            "old_symbol", "new_symbol", "change_date"
        ).iter_rows():
            frame = frame.with_columns(
                pl.when((pl.col("canon_symbol") == old) & (pl.col(date_col) < change_date))
                .then(pl.lit(new))
                .otherwise(pl.col("canon_symbol"))
                .alias("canon_symbol")
            )
        if (frame["canon_symbol"] == before).all():
            return frame
    raise ValueError(f"symbol rename chains did not converge in {_MAX_RENAME_CHAIN} passes")


def equity_panel(bhav: pl.DataFrame, symbol_changes: pl.DataFrame) -> pl.DataFrame:
    """One row per (canon_symbol, trade_date): equity series only, renames unified."""
    panel = (
        bhav.filter(pl.col("series").is_in(EQUITY_SERIES))
        .with_columns(
            pl.col("series").replace_strict(_SERIES_PRIORITY).alias("_prio"),
            pl.col("symbol").alias("canon_symbol"),
        )
        .sort("symbol", "trade_date", "_prio")
        .unique(subset=["symbol", "trade_date"], keep="first")
    )
    panel = canonicalize_symbols(panel, symbol_changes, date_col="trade_date")
    return panel.drop("_prio").sort("canon_symbol", "trade_date")


def adjustment_events(declared: pl.DataFrame, symbol_changes: pl.DataFrame) -> pl.DataFrame:
    """Canonicalize declared factor events for the adjuster.

    Input: (symbol, ex_date, factor[, subject]) from the CA feed. Symbols are
    rewritten to their terminal ticker date-aware, then deduplicated per
    (canon_symbol, ex_date) by multiplying factors (a bonus and a split can
    share an ex-date).
    """
    return (
        canonicalize_symbols(
            declared.rename({"symbol": "canon_symbol"}), symbol_changes, date_col="ex_date"
        )
        .group_by("canon_symbol", "ex_date")
        .agg(pl.col("factor").product())
        .sort("canon_symbol", "ex_date")
    )


def gap_factor_events(panel: pl.DataFrame, gap_events: pl.DataFrame) -> pl.DataFrame:
    """Observed-gap factors for declared events without a parseable ratio.

    ``gap_events``: (canon_symbol, ex_date) for demergers/rights/etc. The
    factor is the overnight gap open(ex) / close(previous session), which
    captures the value transfer plus any same-day ratio event (so on these
    dates the gap factor REPLACES parsed factors -- see combine_events).
    Gaps >= 1 (market noise swamped the adjustment) and micro-gaps are
    dropped; extreme gaps are kept and surface in the QA outlier review.
    """
    with_prior = (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(pl.col("close").shift(1).over("canon_symbol").alias("_prior_close"))
        .select("canon_symbol", pl.col("trade_date").alias("_session_date"), "open", "_prior_close")
        .sort("_session_date")
    )
    return (
        gap_events.sort("ex_date")
        .join_asof(
            with_prior,
            left_on="ex_date",
            right_on="_session_date",
            by="canon_symbol",
            strategy="forward",
        )
        .filter(pl.col("_session_date").is_not_null() & (pl.col("_prior_close") > 0))
        .with_columns(pl.col("_session_date").alias("ex_date"))
        .with_columns((pl.col("open") / pl.col("_prior_close")).alias("factor"))
        .filter(pl.col("factor") < 0.995)  # >=1 or ~1: nothing observable to adjust
        .unique(subset=["canon_symbol", "ex_date"])
        .select("canon_symbol", "ex_date", "factor")
        .sort("canon_symbol", "ex_date")
    )


def combine_events(parsed: pl.DataFrame, gap: pl.DataFrame) -> pl.DataFrame:
    """Union parsed-ratio and observed-gap factor events.

    On a date carrying both, the observed gap already contains the ratio
    event's effect, so the gap factor wins and the parsed one is dropped.
    """
    parsed_only = parsed.join(
        gap.select("canon_symbol", "ex_date"), on=["canon_symbol", "ex_date"], how="anti"
    )
    return pl.concat(
        [
            parsed_only.select("canon_symbol", "ex_date", "factor"),
            gap.select("canon_symbol", "ex_date", "factor"),
        ]
    ).sort("canon_symbol", "ex_date")


def apply_adjustment(panel: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """Add cum_adj_factor and adjusted OHLCV columns (backward adjustment).

    A row's cumulative factor is the product of factors of events strictly
    after its date, so ex-date rows (already in post-CA units) are untouched.
    Ex-dates that are not trading days snap forward to the next session of
    that symbol; events with no later session (delisted before ex-date) drop.
    """
    sessions = panel.select("canon_symbol", pl.col("trade_date").alias("_session_date")).sort(
        "_session_date"
    )
    snapped = (
        events.sort("ex_date")
        .join_asof(
            sessions,
            left_on="ex_date",
            right_on="_session_date",
            by="canon_symbol",
            strategy="forward",
        )
        .filter(pl.col("_session_date").is_not_null())
        .group_by("canon_symbol", pl.col("_session_date").alias("trade_date"))
        .agg(pl.col("factor").product())
    )
    with_f = panel.join(
        snapped,
        on=["canon_symbol", "trade_date"],
        how="left",
    ).with_columns(pl.col("factor").fill_null(1.0))

    adjusted = (
        with_f.sort("canon_symbol", "trade_date", descending=[False, True])
        .with_columns(
            pl.col("factor")
            .cum_prod()
            .shift(1)
            .fill_null(1.0)
            .over("canon_symbol")
            .alias("cum_adj_factor")
        )
        .drop("factor")
        .sort("canon_symbol", "trade_date")
    )
    return adjusted.with_columns(
        (pl.col(c) * pl.col("cum_adj_factor")).alias(f"adj_{c}")
        for c in ("open", "high", "low", "close")
    ).with_columns((pl.col("volume") / pl.col("cum_adj_factor")).alias("adj_volume"))
