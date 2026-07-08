"""Corporate-action adjustment from exchange-adjusted previous closes.

NSE adjusts the base price (bhavcopy PREVCLOSE) on the ex-date of every
price-affecting corporate action: splits, bonuses, face-value changes,
rights, special dividends. Regular dividends do not touch it. Therefore

    factor(ex_date) = prev_close(ex_date) / close(previous traded day)

is the exchange's own adjustment factor, available from primary data for the
full history with no separate CA feed. The declared corporate-actions API is
used as a cross-check (P1c), not as the source of truth. See ADR 0003.

Backward adjustment: prices strictly before an ex-date are multiplied by the
product of all later factors; volumes are divided by it.
"""

from typing import Final

import polars as pl

# Continuous cash-equity series: normal, trade-for-trade, surveillance.
EQUITY_SERIES: Final = ("EQ", "BE", "BZ")
_SERIES_PRIORITY: Final = {"EQ": 0, "BE": 1, "BZ": 2}

# An event needs both a relative and an absolute move of prev_close vs the
# prior close, so paise rounding on low-priced names is not flagged.
REL_TOLERANCE: Final = 0.005
ABS_TOLERANCE: Final = 0.02

_MAX_RENAME_CHAIN: Final = 6


def equity_panel(bhav: pl.DataFrame, symbol_changes: pl.DataFrame) -> pl.DataFrame:
    """One row per (canon_symbol, trade_date): equity series only, renames unified.

    ``canon_symbol`` maps every historical ticker to its terminal name by
    replaying symbolchange.csv date-aware (a rename at date d applies to rows
    strictly before d; symbols reused later by other companies are untouched).
    """
    panel = (
        bhav.filter(pl.col("series").is_in(EQUITY_SERIES))
        .with_columns(
            pl.col("series").replace_strict(_SERIES_PRIORITY).alias("_prio"),
            pl.col("symbol").alias("canon_symbol"),
        )
        .sort("symbol", "trade_date", "_prio")
        .unique(subset=["symbol", "trade_date"], keep="first")
    )

    known = set(panel["canon_symbol"].unique().to_list()) | set(
        symbol_changes["new_symbol"].to_list()
    )
    relevant = symbol_changes.filter(pl.col("old_symbol").is_in(sorted(known))).sort("change_date")
    for _ in range(_MAX_RENAME_CHAIN):
        before = panel["canon_symbol"]
        for old, new, change_date in relevant.select(
            "old_symbol", "new_symbol", "change_date"
        ).iter_rows():
            panel = panel.with_columns(
                pl.when((pl.col("canon_symbol") == old) & (pl.col("trade_date") < change_date))
                .then(pl.lit(new))
                .otherwise(pl.col("canon_symbol"))
                .alias("canon_symbol")
            )
        if (panel["canon_symbol"] == before).all():
            break
    else:
        raise ValueError(f"symbol rename chains did not converge in {_MAX_RENAME_CHAIN} passes")
    return panel.drop("_prio").sort("canon_symbol", "trade_date")


def implied_ca_events(panel: pl.DataFrame) -> pl.DataFrame:
    """Detect ex-dates where the exchange adjusted the base price.

    Returns (canon_symbol, ex_date, factor, prior_close, prev_close).
    """
    with_prior = (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(pl.col("close").shift(1).over("canon_symbol").alias("prior_close"))
        .filter(
            pl.col("prior_close").is_not_null()
            & (pl.col("prior_close") > 0)
            & (pl.col("prev_close") > 0)
        )
    )
    diff = (pl.col("prev_close") - pl.col("prior_close")).abs()
    return (
        with_prior.filter((diff > ABS_TOLERANCE) & (diff > REL_TOLERANCE * pl.col("prior_close")))
        .select(
            "canon_symbol",
            pl.col("trade_date").alias("ex_date"),
            (pl.col("prev_close") / pl.col("prior_close")).alias("factor"),
            "prior_close",
            "prev_close",
        )
        .sort("canon_symbol", "ex_date")
    )


def apply_adjustment(panel: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """Add cum_adj_factor and adjusted OHLCV columns (backward adjustment).

    A row's cumulative factor is the product of factors of events strictly
    after its date, so ex-date rows (already in post-CA units) are untouched.
    """
    with_f = panel.join(
        events.select("canon_symbol", pl.col("ex_date").alias("trade_date"), "factor"),
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
