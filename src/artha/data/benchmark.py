"""Benchmark series from the daily index-close zone.

NIFTY 500 TRI has no free scriptable source (P1 audit item 7), but
ind_close_all carries a trailing dividend yield column, so a SYNTHETIC
total-return series is available: TR return_t = PR return_t + yield_t/252.
The approximation smears lumpy dividends across days; over years it tracks
the true TRI closely and is clearly labeled synthetic wherever reported.

Index names change across vintages ("S&P CNX 500" -> "CNX 500" ->
"Nifty 500"); the aliases below unify them.
"""

from datetime import datetime
from pathlib import Path
from typing import Final

import polars as pl

from artha.data.ingest.indices import parse_index_close

INDEX_ALIASES: Final = {
    "nifty500": ("Nifty 500", "CNX 500", "S&P CNX 500"),
    "nifty50": ("Nifty 50", "CNX Nifty", "S&P CNX Nifty"),
}

TRADING_DAYS: Final = 252


def load_index_series(index_raw: Path, aliases: tuple[str, ...]) -> pl.DataFrame:
    """(trade_date, close, div_yield) for one index across name eras."""
    rows: list[pl.DataFrame] = []
    for f in sorted(index_raw.rglob("ind_close_all_*.csv")):
        d = datetime.strptime(f.name[14:22], "%d%m%Y").date()
        df = parse_index_close(f.read_bytes(), d)
        hit = df.filter(pl.col("index_name").is_in(list(aliases)))
        if hit.height:
            rows.append(hit.select("trade_date", "close", "div_yield").head(1))
    if not rows:
        raise FileNotFoundError(f"no rows for aliases {aliases} under {index_raw}")
    return pl.concat(rows).sort("trade_date").unique(subset=["trade_date"], keep="first")


def synthetic_total_return(series: pl.DataFrame) -> pl.DataFrame:
    """Add pr_return, tr_return and a synthetic TR index level (base 1000)."""
    out = (
        series.sort("trade_date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("pr_return"))
        .with_columns(
            (pl.col("pr_return") + pl.col("div_yield").fill_null(0.0) / 100.0 / TRADING_DAYS).alias(
                "tr_return"
            )
        )
    )
    return out.with_columns(
        (1000.0 * (1.0 + pl.col("tr_return").fill_null(0.0)).cum_prod()).alias("tr_index")
    )
