"""NSE corporate announcements, board meetings, and bulk deals ingest (P1b).

All three come from www.nseindia.com/api endpoints (cookie dance), windowed
by month into immutable raw JSON. Probed 2026-07-12: announcements reach
June 2010+, board meetings 2012+, no per-window result cap (a full month
equals the sum of its weeks). The exchange receipt timestamp (``an_dt``) is
the knowability anchor for every downstream event feature.

Timestamps are naive IST (exchange local time).
"""

import calendar
import json
from datetime import date
from pathlib import Path
from typing import Final

import httpx
import polars as pl

from artha.data.ingest.nse_http import NseDownloadError, fetch
from artha.data.store import RawStore

ANNOUNCEMENTS_START: Final = date(2010, 1, 1)
BOARD_MEETINGS_START: Final = date(2012, 1, 1)
BULK_DEALS_START: Final = date(2010, 1, 1)  # depth verified during backfill

_ANN_URL: Final = "https://www.nseindia.com/api/corporate-announcements"
_BM_URL: Final = "https://www.nseindia.com/api/corporate-board-meetings"
_BULK_URL: Final = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"

_TS_FMT: Final = "%d-%b-%Y %H:%M:%S"


class EventParseError(Exception):
    """Raised when an events payload does not match its documented shape."""


def _month_window(d: date) -> tuple[str, str]:
    last = calendar.monthrange(d.year, d.month)[1]
    return f"{d.replace(day=1):%d-%m-%Y}", f"{d.replace(day=last):%d-%m-%Y}"


def announcements_relpath(d: date) -> str:
    return f"events/announcements/{d.year}/ann_{d:%Y%m}.json"


def board_meetings_relpath(d: date) -> str:
    return f"events/board_meetings/{d.year}/bm_{d:%Y%m}.json"


def bulk_deals_relpath(d: date) -> str:
    return f"events/bulk_deals/{d.year}/bulk_{d:%Y%m}.json"


def _download_json_list(url: str, relpath: str, *, client: httpx.Client, store: RawStore) -> Path:
    content = fetch(url, client=client, retries=4)
    if content.lstrip()[:1] != b"[":
        raise NseDownloadError(url, "response is not a JSON list (blocked or reshaped API)")
    return store.write(relpath, content, source_url=url)


def download_announcements_month(d: date, *, client: httpx.Client, store: RawStore) -> Path:
    frm, to = _month_window(d)
    url = f"{_ANN_URL}?index=equities&from_date={frm}&to_date={to}"
    return _download_json_list(url, announcements_relpath(d), client=client, store=store)


def download_board_meetings_month(d: date, *, client: httpx.Client, store: RawStore) -> Path:
    frm, to = _month_window(d)
    url = f"{_BM_URL}?index=equities&from_date={frm}&to_date={to}"
    return _download_json_list(url, board_meetings_relpath(d), client=client, store=store)


def download_bulk_deals_month(d: date, *, client: httpx.Client, store: RawStore) -> Path:
    frm, to = _month_window(d)
    url = f"{_BULK_URL}?optionType=bulk_deals&from={frm}&to={to}"
    content = fetch(url, client=client, retries=4)
    if content.lstrip()[:1] != b"{":
        raise NseDownloadError(url, "response is not a JSON object (blocked or reshaped API)")
    return store.write(bulk_deals_relpath(d), content, source_url=url)


def parse_announcements(content: bytes) -> pl.DataFrame:
    """(symbol, isin, company, industry, category, subject, announced_at,
    attachment_url, seq_id), sorted by announced_at."""
    records = json.loads(content)
    if not isinstance(records, list):
        raise EventParseError("announcements payload is not a list")
    if not records:
        return pl.DataFrame(
            schema={
                "symbol": pl.String,
                "isin": pl.String,
                "company": pl.String,
                "industry": pl.String,
                "category": pl.String,
                "subject": pl.String,
                "announced_at": pl.Datetime,
                "attachment_url": pl.String,
                "seq_id": pl.String,
            }
        )

    def s(value: object) -> str | None:
        return None if value is None else str(value)

    fields = {
        "symbol": "symbol",
        "isin": "sm_isin",
        "company": "sm_name",
        "industry": "smIndustry",
        "category": "desc",
        "subject": "attchmntText",
        "announced_at": "an_dt",
        "attachment_url": "attchmntFile",
        "seq_id": "seq_id",
    }
    # occasional rows carry numeric values in nominally-string fields:
    # coerce everything and skip schema inference entirely
    df = pl.DataFrame(
        [{col: s(r.get(key)) for col, key in fields.items()} for r in records],
        schema=dict.fromkeys(fields, pl.String),
    )
    out = df.with_columns(
        pl.col("announced_at").str.to_datetime(_TS_FMT),
        pl.col("attachment_url").replace("-", None),
    ).sort("announced_at")
    if out["announced_at"].null_count():
        raise EventParseError(f"{out['announced_at'].null_count()} announcements without an_dt")
    return out


def parse_board_meetings(content: bytes) -> pl.DataFrame:
    """(symbol, isin, meeting_date, purpose, description, intimated_at)."""
    records = json.loads(content)
    if not isinstance(records, list):
        raise EventParseError("board meetings payload is not a list")
    if not records:
        return pl.DataFrame(
            schema={
                "symbol": pl.String,
                "isin": pl.String,
                "meeting_date": pl.Date,
                "purpose": pl.String,
                "description": pl.String,
                "intimated_at": pl.Datetime,
            }
        )
    fields = {
        "symbol": "bm_symbol",
        "isin": "sm_isin",
        "meeting_date": "bm_date",
        "purpose": "bm_purpose",
        "description": "bm_desc",
        "intimated_at": "bm_timestamp",
    }
    df = pl.DataFrame(
        [
            {col: None if r.get(key) is None else str(r.get(key)) for col, key in fields.items()}
            for r in records
        ],
        schema=dict.fromkeys(fields, pl.String),
    )
    return df.with_columns(
        pl.col("meeting_date").str.to_date("%d-%b-%Y"),
        pl.col("intimated_at").str.to_datetime(_TS_FMT, strict=False),
    ).sort("meeting_date", "symbol")


def parse_bulk_deals(content: bytes) -> pl.DataFrame:
    """(trade_date, symbol, client_name, side, quantity, wavg_price, remarks)."""
    payload = json.loads(content)
    if not isinstance(payload, dict) or "data" not in payload:
        raise EventParseError("bulk deals payload has no 'data' key")
    records = payload["data"]
    if not records:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "symbol": pl.String,
                "client_name": pl.String,
                "side": pl.String,
                "quantity": pl.Int64,
                "wavg_price": pl.Float64,
                "remarks": pl.String,
            }
        )
    fields = {
        "trade_date": "BD_DT_DATE",
        "symbol": "BD_SYMBOL",
        "client_name": "BD_CLIENT_NAME",
        "side": "BD_BUY_SELL",
        "quantity": "BD_QTY_TRD",
        "wavg_price": "BD_TP_WATP",
        "remarks": "BD_REMARKS",
    }
    df = pl.DataFrame(
        [
            {col: None if r.get(key) is None else str(r.get(key)) for col, key in fields.items()}
            for r in records
        ],
        schema=dict.fromkeys(fields, pl.String),
    )
    return df.with_columns(
        pl.col("trade_date").str.to_titlecase().str.to_date("%d-%b-%Y"),
        pl.col("quantity").cast(pl.Float64).cast(pl.Int64),
        pl.col("wavg_price").cast(pl.Float64),
        pl.col("remarks").replace("-", None),
    ).sort("trade_date", "symbol")
