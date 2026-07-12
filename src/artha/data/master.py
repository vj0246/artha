"""Security master: one row per canonical symbol with sector mapping.

Sector/industry comes from the latest NIFTY 500 constituent snapshot, so it
covers the investable top-500 set and is CURRENT-state only -- a static
mapping applied across history (plan v2 section 5.0 accepts this and flags
it as a known limitation; free point-in-time sector history does not exist).
Names outside the current NIFTY 500 carry a null industry.
"""

import polars as pl


def build_security_master(panel: pl.DataFrame, nifty500: pl.DataFrame) -> pl.DataFrame:
    """(canon_symbol, isin, first_trade_date, last_trade_date, company, industry).

    ``panel`` is the curated equity panel; ``nifty500`` a parsed constituent
    list. ISIN is taken from each symbol's latest row (null pre-2011 era
    names that never traded after ISINs appeared). Industry joins on symbol.
    """
    latest = (
        panel.sort("canon_symbol", "trade_date")
        .group_by("canon_symbol", maintain_order=True)
        .agg(
            pl.col("isin").last(),
            pl.col("trade_date").first().alias("first_trade_date"),
            pl.col("trade_date").last().alias("last_trade_date"),
        )
    )
    return (
        latest.join(
            nifty500.select("symbol", "company", "industry"),
            left_on="canon_symbol",
            right_on="symbol",
            how="left",
        )
        .select(
            "canon_symbol",
            "isin",
            "first_trade_date",
            "last_trade_date",
            "company",
            "industry",
        )
        .sort("canon_symbol")
    )
