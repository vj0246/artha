"""NSE symbol-change history (``symbolchange.csv``).

A living, header-less file listing every ticker rename since ~2000, e.g.
``Infosys Limited,INFOSYSTCH,INFY,29-JUN-2011``. Company names may contain
commas, so rows are split from the right. Stored in the raw zone as dated
snapshots (the file mutates over time; the raw zone is immutable).
"""

from datetime import date
from pathlib import Path

import httpx
import polars as pl

from artha.data.ingest.nse_http import fetch
from artha.data.store import RawStore

SYMBOLCHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"

_ROW_RE = r"^\s*(.*?)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\s*$"


class SymbolChangeParseError(Exception):
    pass


def symbolchange_relpath(as_of: date) -> str:
    return f"symbolchange/symbolchange_{as_of:%Y-%m-%d}.csv"


def download_symbolchange(as_of: date, *, client: httpx.Client, store: RawStore) -> Path:
    content = fetch(SYMBOLCHANGE_URL, client=client)
    return store.write(symbolchange_relpath(as_of), content, source_url=SYMBOLCHANGE_URL)


def parse_symbolchange(csv_data: bytes) -> pl.DataFrame:
    """Return columns: company, old_symbol, new_symbol, change_date."""
    lines = pl.DataFrame({"line": csv_data.decode("utf-8", errors="replace").splitlines()}).filter(
        pl.col("line").str.strip_chars() != ""
    )
    parsed = lines.select(
        pl.col("line").str.extract(_ROW_RE, 1).alias("company"),
        pl.col("line").str.extract(_ROW_RE, 2).alias("old_symbol"),
        pl.col("line").str.extract(_ROW_RE, 3).alias("new_symbol"),
        pl.col("line")
        .str.extract(_ROW_RE, 4)
        .str.to_titlecase()
        .str.zfill(11)
        .str.to_date("%d-%b-%Y")
        .alias("change_date"),
    )
    bad = parsed.filter(
        pl.col("old_symbol").is_null()
        | pl.col("new_symbol").is_null()
        | pl.col("change_date").is_null()
    )
    if not bad.is_empty():
        raise SymbolChangeParseError(f"{bad.height} unparseable symbolchange rows")
    return parsed.sort("change_date")
