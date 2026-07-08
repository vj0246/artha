"""Declared corporate actions from the NSE CA API (cross-check source, ADR 0003).

The API (www.nseindia.com, cookie dance) returns declared actions filtered by
ex-date window; coverage reaches back to ~2011. Stored as monthly JSON files
in the raw zone. The adjustment engine derives factors from prices; this feed
only cross-checks that price-affecting declared events (bonus/split) have a
matching implied event and vice versa.
"""

import calendar
import json
import re
from datetime import date
from pathlib import Path
from typing import Final

import httpx
import polars as pl

from artha.data.ingest.nse_http import NseDownloadError, fetch
from artha.data.store import RawStore

CA_API_URL: Final = "https://www.nseindia.com/api/corporates-corporateActions"
CA_API_START: Final = date(2011, 1, 1)  # earliest records observed (probed 2026-07-08)

_BONUS_RE: Final = re.compile(r"\bbonus\s+(\d+)\s*:\s*(\d+)", re.IGNORECASE)
_SPLIT_RE: Final = re.compile(
    r"\bsplit.*?rs?\.?\s*(\d+(?:\.\d+)?)\s*(?:/-)?\s*to\s*.*?re?s?\.?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def ca_month_relpath(d: date) -> str:
    return f"ca_api/{d.year}/ca_{d:%Y%m}.json"


def ca_month_url(d: date) -> str:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return (
        f"{CA_API_URL}?index=equities"
        f"&from_date={d.replace(day=1):%d-%m-%Y}"
        f"&to_date={d.replace(day=last_day):%d-%m-%Y}"
    )


def download_ca_month(d: date, *, client: httpx.Client, store: RawStore) -> Path:
    """Fetch one ex-date month of declared actions. ``client`` must come from
    ``nse_api_client()`` so the session cookies are present."""
    url = ca_month_url(d)
    content = fetch(url, client=client)
    if not content.lstrip()[:1] == b"[":
        raise NseDownloadError(url, "response is not a JSON list (blocked or reshaped API)")
    return store.write(ca_month_relpath(d), content, source_url=url)


def parse_ca_records(content: bytes) -> pl.DataFrame:
    """(symbol, series, isin, company, subject, ex_date, record_date, face_value)."""
    records = json.loads(content)
    if not isinstance(records, list):
        raise ValueError("CA API payload is not a list")
    if not records:
        return pl.DataFrame(
            schema={
                "symbol": pl.String,
                "series": pl.String,
                "isin": pl.String,
                "company": pl.String,
                "subject": pl.String,
                "ex_date": pl.Date,
                "record_date": pl.Date,
                "face_value": pl.String,
            }
        )
    df = pl.DataFrame(
        [
            {
                "symbol": r.get("symbol"),
                "series": r.get("series"),
                "isin": r.get("isin"),
                "company": r.get("comp"),
                "subject": r.get("subject"),
                "ex_date": r.get("exDate"),
                "record_date": r.get("recDate"),
                "face_value": r.get("faceVal"),
            }
            for r in records
        ]
    )
    return df.with_columns(
        pl.col("ex_date").replace("-", None).str.to_date("%d-%b-%Y"),
        pl.col("record_date").replace("-", None).str.to_date("%d-%b-%Y", strict=False),
    ).sort("symbol", "ex_date")


def expected_factor(subject: str) -> float | None:
    """Adjustment factor implied by a declared subject, where derivable.

    Bonus a:b (a new per b held): factor = b / (a + b).
    Face-value split Rs x -> Rs y: factor = y / x.
    Rights/dividends/others: None (factor depends on price or is nil).
    """
    m = _BONUS_RE.search(subject)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            return b / (a + b)
    m = _SPLIT_RE.search(subject)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        if x > 0 and 0 < y < x:
            return y / x
    return None


def declared_factor_events(ca: pl.DataFrame) -> pl.DataFrame:
    """Declared events with a derivable factor: (symbol, ex_date, subject, factor)."""
    factors = [expected_factor(s) if s else None for s in ca["subject"].to_list()]
    return (
        ca.with_columns(pl.Series("factor", factors, dtype=pl.Float64))
        .filter(pl.col("factor").is_not_null() & pl.col("ex_date").is_not_null())
        .select("symbol", "ex_date", "subject", "factor")
        .unique(subset=["symbol", "ex_date"])
        .sort("symbol", "ex_date")
    )


def cross_check(
    implied: pl.DataFrame, declared: pl.DataFrame, *, rel_tolerance: float = 0.02
) -> dict[str, pl.DataFrame]:
    """Compare implied (canon_symbol, ex_date, factor) vs declared factor events.

    Returns review frames: ``factor_mismatch`` (both sides present, factors
    differ beyond tolerance) and ``declared_missing_implied`` (declared
    bonus/split with no implied event: adjustment engine may have missed it).
    Implied-without-declared is expected (rights, special dividends, pre-2011)
    and not reported here.

    Caveat: declared symbols are as of the ex-date while implied symbols are
    canonical (post-rename); companies renamed after a CA appear as false
    positives in ``declared_missing_implied``. Review frames, not a gate.
    """
    joined = implied.join(
        declared.rename({"symbol": "canon_symbol", "factor": "declared_factor"}),
        on=["canon_symbol", "ex_date"],
        how="full",
        coalesce=True,
    )
    both = joined.filter(pl.col("factor").is_not_null() & pl.col("declared_factor").is_not_null())
    mismatch = both.filter((pl.col("factor") / pl.col("declared_factor") - 1).abs() > rel_tolerance)
    missing = joined.filter(pl.col("factor").is_null()).select(
        "canon_symbol", "ex_date", "subject", "declared_factor"
    )
    return {
        "factor_mismatch": mismatch.sort("canon_symbol", "ex_date"),
        "declared_missing_implied": missing.sort("canon_symbol", "ex_date"),
    }
