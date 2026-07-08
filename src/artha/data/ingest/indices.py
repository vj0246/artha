"""Index-level ingest: daily all-index closes and NIFTY 500 constituent snapshots.

``ind_close_all_DDMMYYYY.csv`` (nsearchives) carries OHLC and valuation for
every NSE index; available from roughly July 2012 (404 before). It contains
PRICE indices only -- the NIFTY 500 TRI benchmark needs a separate source
(open verify-list item). The NIFTY 500 price index row is named "CNX 500"
before the 2015 rebrand and "Nifty 500" after.

``ind_nifty500list.csv`` is the CURRENT constituent list; stored as dated
snapshots. Historical membership reconstruction is a separate concern.
"""

import csv
import io
from datetime import date
from pathlib import Path

import httpx
import polars as pl

from artha.data.ingest.nse_http import fetch
from artha.data.store import RawStore

INDEX_CLOSE_START = date(2012, 7, 2)  # earliest confirmed file (probed 2026-07-08)

NIFTY500_LIST_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"

_INDEX_CLOSE_HEADER = [
    "Index Name",
    "Index Date",
    "Open Index Value",
    "High Index Value",
    "Low Index Value",
    "Closing Index Value",
    "Points Change",
    "Change(%)",
    "Volume",
    "Turnover (Rs. Cr.)",
    "P/E",
    "P/B",
    "Div Yield",
]

_NIFTY500_HEADER = ["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]


class IndexParseError(Exception):
    """Raised when an index file does not match its documented format."""


def index_close_filename(d: date) -> str:
    return f"ind_close_all_{d:%d%m%Y}.csv"


def index_close_url(d: date) -> str:
    return f"https://nsearchives.nseindia.com/content/indices/{index_close_filename(d)}"


def index_close_relpath(d: date) -> str:
    return f"indexclose/{d.year}/{index_close_filename(d)}"


def download_index_close(d: date, *, client: httpx.Client, store: RawStore) -> Path:
    content = fetch(index_close_url(d), client=client)
    if not content.lstrip()[:10].startswith(b"Index Name"):
        raise IndexParseError(f"{index_close_filename(d)}: response is not the index close CSV")
    return store.write(index_close_relpath(d), content, source_url=index_close_url(d))


def parse_index_close(content: bytes, expected_date: date) -> pl.DataFrame:
    """Canonical per-index rows for one day; '-' fields become null."""
    text = content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != _INDEX_CLOSE_HEADER:
        raise IndexParseError(f"unexpected header: {rows[0] if rows else 'empty file'}")
    body = [r for r in rows[1:] if r and any(f.strip() for f in r)]
    if not body:
        raise IndexParseError("zero data rows")

    df = pl.DataFrame(
        [dict(zip(_INDEX_CLOSE_HEADER, r, strict=True)) for r in body],
        schema=dict.fromkeys(_INDEX_CLOSE_HEADER, pl.String),
    )
    numeric = _INDEX_CLOSE_HEADER[2:]
    out = (
        df.with_columns(
            pl.col("Index Date").str.to_date("%d-%m-%Y").alias("trade_date"),
            pl.col("Index Name").str.strip_chars().alias("index_name"),
            *(
                pl.col(c).str.strip_chars().replace("-", None).cast(pl.Float64).alias(alias)
                for c, alias in zip(
                    numeric,
                    [
                        "open",
                        "high",
                        "low",
                        "close",
                        "points_change",
                        "pct_change",
                        "volume",
                        "turnover_cr",
                        "pe",
                        "pb",
                        "div_yield",
                    ],
                    strict=True,
                )
            ),
        )
        .drop(_INDEX_CLOSE_HEADER)
        .sort("index_name")
    )
    bad_dates = out.filter(pl.col("trade_date") != expected_date)
    if bad_dates.height:
        raise IndexParseError(
            f"{bad_dates.height} rows dated {bad_dates['trade_date'][0]}, expected {expected_date}"
        )
    return out


def nifty500_snapshot_relpath(as_of: date) -> str:
    return f"constituents/nifty500_{as_of:%Y%m%d}.csv"


def download_nifty500_list(as_of: date, *, client: httpx.Client, store: RawStore) -> Path:
    content = fetch(NIFTY500_LIST_URL, client=client)
    if not content.lstrip()[:12].startswith(b"Company Name"):
        raise IndexParseError("response is not the constituent CSV")
    return store.write(nifty500_snapshot_relpath(as_of), content, source_url=NIFTY500_LIST_URL)


def parse_nifty500_list(content: bytes) -> pl.DataFrame:
    """(company, industry, symbol, series, isin), sorted by symbol."""
    text = content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0] != _NIFTY500_HEADER:
        raise IndexParseError(f"unexpected header: {rows[0] if rows else 'empty file'}")
    body = [r for r in rows[1:] if r and any(f.strip() for f in r)]
    if not body:
        raise IndexParseError("zero data rows")
    return (
        pl.DataFrame(
            [dict(zip(_NIFTY500_HEADER, r, strict=True)) for r in body],
            schema=dict.fromkeys(_NIFTY500_HEADER, pl.String),
        )
        .select(
            pl.col("Company Name").str.strip_chars().alias("company"),
            pl.col("Industry").str.strip_chars().alias("industry"),
            pl.col("Symbol").str.strip_chars().alias("symbol"),
            pl.col("Series").str.strip_chars().alias("series"),
            pl.col("ISIN Code").str.strip_chars().alias("isin"),
        )
        .sort("symbol")
    )
