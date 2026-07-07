"""NSE daily equity bhavcopy: URL scheme, raw-zone download, format parsers.

Format map, verified empirically 2026-07-08 against nsearchives.nseindia.com
(ADR 0002):

- Old format ``cmDDMMMYYYYbhav.csv.zip`` — available 2010 through mid-2024,
  gone by Dec 2024. Two column variants: pre-2011 files lack TOTALTRADES and
  ISIN; both have a trailing comma producing a phantom column.
- UDiFF format ``BhavCopy_NSE_CM_0_0_0_YYYYMMDD_F_0000.csv.zip`` — available
  from at least 2024-01-02, NOT backfilled to earlier years.

Cutover here is 2024-07-01: both formats confirmed live during that week,
which the parity test in tests/unit exploits. Amounts are rupees in both
formats (verified qty x price on real rows).

Parsers return one canonical schema; all series (EQ, BE, GS, ...) are kept —
universe construction filters later.
"""

import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Final

import httpx
import polars as pl

from artha.data.ingest.nse_http import NseDownloadError, fetch
from artha.data.store import RawStore

UDIFF_CUTOVER: Final = date(2024, 7, 1)

_ARCHIVE_HOST: Final = "https://nsearchives.nseindia.com"

CANONICAL_COLUMNS: Final = [
    "trade_date",
    "symbol",
    "series",
    "isin",
    "open",
    "high",
    "low",
    "close",
    "last",
    "prev_close",
    "volume",
    "traded_value",
    "trades",
]


class BhavcopyParseError(Exception):
    pass


def bhavcopy_filename(trade_date: date) -> str:
    if trade_date >= UDIFF_CUTOVER:
        return f"BhavCopy_NSE_CM_0_0_0_{trade_date:%Y%m%d}_F_0000.csv.zip"
    month = f"{trade_date:%b}".upper()
    return f"cm{trade_date:%d}{month}{trade_date:%Y}bhav.csv.zip"


def bhavcopy_url(trade_date: date) -> str:
    name = bhavcopy_filename(trade_date)
    if trade_date >= UDIFF_CUTOVER:
        return f"{_ARCHIVE_HOST}/content/cm/{name}"
    month = f"{trade_date:%b}".upper()
    return f"{_ARCHIVE_HOST}/content/historical/EQUITIES/{trade_date:%Y}/{month}/{name}"


def bhavcopy_relpath(trade_date: date) -> str:
    return f"bhavcopy/{trade_date:%Y}/{bhavcopy_filename(trade_date)}"


def download_bhavcopy(trade_date: date, *, client: httpx.Client, store: RawStore) -> Path:
    """Fetch one day's bhavcopy into the raw zone. Raises NseNotFoundError on 404."""
    url = bhavcopy_url(trade_date)
    content = fetch(url, client=client)
    if not content.startswith(b"PK"):
        raise NseDownloadError(url, "response is not a zip (likely a block page)")
    return store.write(bhavcopy_relpath(trade_date), content, source_url=url)


def read_bhavcopy_zip(path: Path, *, trade_date: date) -> pl.DataFrame:
    with zipfile.ZipFile(path) as zf:
        csv_members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        if len(csv_members) != 1:
            raise BhavcopyParseError(f"{path}: expected exactly one csv member, got {csv_members}")
        data = zf.read(csv_members[0])
    return parse_bhavcopy(data, trade_date=trade_date)


def parse_bhavcopy(csv_data: bytes, *, trade_date: date) -> pl.DataFrame:
    csv_data = csv_data.removeprefix(b"\xef\xbb\xbf")  # defensive: BOM would break detection
    header = csv_data.split(b"\n", 1)[0]
    df = _parse_udiff(csv_data) if header.startswith(b"TradDt") else _parse_old(csv_data)
    if df.is_empty():
        raise BhavcopyParseError(f"bhavcopy for {trade_date} parsed to zero rows")
    bad_dates = df.filter(pl.col("trade_date") != trade_date)
    if not bad_dates.is_empty():
        raise BhavcopyParseError(
            f"bhavcopy dated {trade_date} contains {bad_dates.height} rows with other dates"
        )
    return df.select(CANONICAL_COLUMNS).sort("symbol", "series")


def _parse_old(csv_data: bytes) -> pl.DataFrame:
    raw = pl.read_csv(io.BytesIO(csv_data), infer_schema=False)
    required = [
        "SYMBOL",
        "SERIES",
        "OPEN",
        "HIGH",
        "LOW",
        "CLOSE",
        "LAST",
        "PREVCLOSE",
        "TOTTRDQTY",
        "TOTTRDVAL",
        "TIMESTAMP",
    ]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise BhavcopyParseError(f"old-format bhavcopy missing columns: {missing}")
    # Pre-2011 files lack TOTALTRADES and ISIN.
    trades = (
        pl.col("TOTALTRADES").cast(pl.Int64, strict=False)
        if "TOTALTRADES" in raw.columns
        else pl.lit(None, dtype=pl.Int64)
    )
    isin = (
        pl.col("ISIN").str.strip_chars() if "ISIN" in raw.columns else pl.lit(None, dtype=pl.String)
    )
    return raw.select(
        # Day-of-month is not always zero-padded ("4-JAN-2010"): zfill to
        # "04-Jan-2010" width; already-padded values are unaffected.
        pl.col("TIMESTAMP")
        .str.strip_chars()
        .str.to_titlecase()
        .str.zfill(11)
        .str.to_date("%d-%b-%Y")
        .alias("trade_date"),
        pl.col("SYMBOL").str.strip_chars().alias("symbol"),
        pl.col("SERIES").str.strip_chars().alias("series"),
        isin.alias("isin"),
        pl.col("OPEN").cast(pl.Float64).alias("open"),
        pl.col("HIGH").cast(pl.Float64).alias("high"),
        pl.col("LOW").cast(pl.Float64).alias("low"),
        pl.col("CLOSE").cast(pl.Float64).alias("close"),
        pl.col("LAST").cast(pl.Float64).alias("last"),
        pl.col("PREVCLOSE").cast(pl.Float64).alias("prev_close"),
        pl.col("TOTTRDQTY").cast(pl.Int64).alias("volume"),
        pl.col("TOTTRDVAL").cast(pl.Float64).alias("traded_value"),
        trades.alias("trades"),
    )


def _parse_udiff(csv_data: bytes) -> pl.DataFrame:
    raw = pl.read_csv(io.BytesIO(csv_data), infer_schema=False)
    required = [
        "TradDt",
        "TckrSymb",
        "SctySrs",
        "ISIN",
        "OpnPric",
        "HghPric",
        "LwPric",
        "ClsPric",
        "LastPric",
        "PrvsClsgPric",
        "TtlTradgVol",
        "TtlTrfVal",
        "TtlNbOfTxsExctd",
    ]
    missing = [c for c in required if c not in raw.columns]
    if missing:
        raise BhavcopyParseError(f"UDiFF bhavcopy missing columns: {missing}")
    return raw.select(
        pl.col("TradDt").str.to_date("%Y-%m-%d").alias("trade_date"),
        pl.col("TckrSymb").str.strip_chars().alias("symbol"),
        # Empty series (some non-equity instruments) becomes null.
        pl.col("SctySrs").str.strip_chars().replace("", None).alias("series"),
        pl.col("ISIN").str.strip_chars().replace("", None).alias("isin"),
        pl.col("OpnPric").cast(pl.Float64, strict=False).alias("open"),
        pl.col("HghPric").cast(pl.Float64, strict=False).alias("high"),
        pl.col("LwPric").cast(pl.Float64, strict=False).alias("low"),
        pl.col("ClsPric").cast(pl.Float64, strict=False).alias("close"),
        pl.col("LastPric").cast(pl.Float64, strict=False).alias("last"),
        pl.col("PrvsClsgPric").cast(pl.Float64, strict=False).alias("prev_close"),
        pl.col("TtlTradgVol").cast(pl.Int64, strict=False).alias("volume"),
        pl.col("TtlTrfVal").cast(pl.Float64, strict=False).alias("traded_value"),
        pl.col("TtlNbOfTxsExctd").cast(pl.Int64, strict=False).alias("trades"),
    )
