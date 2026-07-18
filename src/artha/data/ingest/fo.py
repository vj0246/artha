"""NIFTY index-futures ingest from F&O bhavcopy archives (Track B B4).

Same dual-format story as the equity bhavcopy (probed 2026-07-18): old
``foDDMMMYYYYbhav.csv.zip`` under content/historical/DERIVATIVES with
INSTRUMENT=FUTIDX rows, UDiFF ``BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000``
under content/fo with FinInstrmTp=IDF. Raw zips are stored whole
(immutable); the parser extracts only NIFTY index futures.
"""

import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Final

import httpx
import polars as pl

from artha.data.ingest.bhavcopy import UDIFF_CUTOVER
from artha.data.ingest.nse_http import NseDownloadError, fetch
from artha.data.store import RawStore

FO_COLUMNS: Final = ["trade_date", "expiry", "close", "settle", "open_interest", "contracts"]


class FoParseError(Exception):
    """Raised when an F&O bhavcopy does not match its documented format."""


def fo_filename(d: date) -> str:
    if d >= UDIFF_CUTOVER:
        return f"BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip"
    return f"fo{d:%d%b%Y}bhav.csv.zip".replace(f"{d:%b}", f"{d:%b}".upper())


def fo_url(d: date) -> str:
    if d >= UDIFF_CUTOVER:
        return f"https://nsearchives.nseindia.com/content/fo/{fo_filename(d)}"
    mon = f"{d:%b}".upper()
    return (
        "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
        f"{d.year}/{mon}/{fo_filename(d)}"
    )


def fo_relpath(d: date) -> str:
    return f"fo/{d.year}/{fo_filename(d)}"


def download_fo_bhavcopy(d: date, *, client: httpx.Client, store: RawStore) -> Path:
    content = fetch(fo_url(d), client=client)
    if content[:2] != b"PK":
        raise NseDownloadError(fo_url(d), "response is not a zip (block page?)")
    return store.write(fo_relpath(d), content, source_url=fo_url(d))


def parse_nifty_futures(zip_path: Path, trade_date: date) -> pl.DataFrame:
    """NIFTY index-futures rows only: (trade_date, expiry, close, settle,
    open_interest, contracts)."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise FoParseError(f"{zip_path}: expected one csv member, got {members}")
        data = zf.read(members[0])
    raw = pl.read_csv(io.BytesIO(data), infer_schema=False)
    if "TradDt" in raw.columns:  # UDiFF
        out = raw.filter((pl.col("FinInstrmTp") == "IDF") & (pl.col("TckrSymb") == "NIFTY")).select(
            pl.col("TradDt").str.to_date("%Y-%m-%d").alias("trade_date"),
            pl.col("XpryDt").str.to_date("%Y-%m-%d").alias("expiry"),
            pl.col("ClsPric").cast(pl.Float64).alias("close"),
            pl.col("SttlmPric").cast(pl.Float64).alias("settle"),
            pl.col("OpnIntrst").cast(pl.Float64).alias("open_interest"),
            pl.col("TtlNbOfTxsExctd").cast(pl.Float64).alias("contracts"),
        )
    elif "INSTRUMENT" in raw.columns:  # old format
        out = raw.filter((pl.col("INSTRUMENT") == "FUTIDX") & (pl.col("SYMBOL") == "NIFTY")).select(
            pl.col("TIMESTAMP")
            .str.strip_chars()
            .str.to_titlecase()
            .str.to_date("%d-%b-%Y")
            .alias("trade_date"),
            pl.col("EXPIRY_DT")
            .str.strip_chars()
            .str.to_titlecase()
            .str.to_date("%d-%b-%Y")
            .alias("expiry"),
            pl.col("CLOSE").cast(pl.Float64).alias("close"),
            pl.col("SETTLE_PR").cast(pl.Float64).alias("settle"),
            pl.col("OPEN_INT").cast(pl.Float64).alias("open_interest"),
            pl.col("CONTRACTS").cast(pl.Float64).alias("contracts"),
        )
    else:
        raise FoParseError(f"{zip_path}: unknown header {raw.columns[:5]}")
    if out.is_empty():
        raise FoParseError(f"{zip_path}: no NIFTY futures rows")
    bad = out.filter(pl.col("trade_date") != trade_date)
    if bad.height:
        raise FoParseError(f"{zip_path}: {bad.height} rows dated other than {trade_date}")
    return out.sort("expiry")


def front_month_series(futures: pl.DataFrame) -> pl.DataFrame:
    """Daily front-month settle with same-contract returns across rolls.

    Per date pick the nearest expiry >= trade_date; the daily return always
    compares a contract's settle to ITS OWN previous settle, so roll days
    show the new contract's true move, not an artificial calendar jump.
    """
    front = (
        futures.filter(pl.col("expiry") >= pl.col("trade_date"))
        .sort("trade_date", "expiry")
        .unique(subset=["trade_date"], keep="first")
    )
    with_lag = futures.sort("expiry", "trade_date").with_columns(
        (pl.col("settle") / pl.col("settle").shift(1).over("expiry") - 1).alias("fut_return")
    )
    return (
        front.join(
            with_lag.select("trade_date", "expiry", "fut_return"),
            on=["trade_date", "expiry"],
            how="left",
        )
        .select("trade_date", "expiry", "settle", "fut_return", "open_interest")
        .sort("trade_date")
    )
