"""Declared corporate actions from the NSE CA API: THE adjustment source (ADR 0005).

The API (www.nseindia.com, cookie dance) returns declared actions filtered by
ex-date window; coverage reaches back to at least 2005. Stored as monthly
JSON files in the raw zone. Bonus and face-value-split subjects parse into
adjustment factors; the bhavcopy itself carries no adjustment information
(its previous close is always the raw prior close).
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
# Feed reaches at least 2005 (probed 2026-07-08); panel starts 2010.
CA_API_START: Final = date(2010, 1, 1)

# Subject styles vary across eras: "Bonus 1:1", "Bonus-1:2",
# "Face Value Split From Rs 10/- Per Share To Rs 2/- Per Share",
# "Fv Split Rs.10 To Re.1". First number after the keyword, first after "to".
_BONUS_RE: Final = re.compile(r"\bbonus\b\D{0,8}?(\d+)\s*:\s*(\d+)", re.IGNORECASE)
_SPLIT_RE: Final = re.compile(
    r"\bsplit\b\D*?(\d+(?:\.\d+)?)\D*?\bto\b\D*?(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
# Events with a real price discontinuity but no ratio in the subject; their
# factor is observed from the ex-date price gap (ADR 0005 audit addendum).
_GAP_RE: Final = re.compile(
    r"\b(demerger|rights|capital reduction|scheme of arrangement)\b", re.IGNORECASE
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
    One subject can carry both ("Bonus 1:1/Face Value Split From Rs 10 To
    Rs 2"): the legs multiply. Rights/dividends/others: None.
    """
    factor = 1.0
    m = _BONUS_RE.search(subject)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > 0 and b > 0:
            factor *= b / (a + b)
    m = _SPLIT_RE.search(subject)
    if m:
        x, y = float(m.group(1)), float(m.group(2))
        if x > 0 and 0 < y < x:
            factor *= y / x
    return factor if factor < 1.0 else None


def declared_gap_events(ca: pl.DataFrame) -> pl.DataFrame:
    """Declared events whose factor must be observed from the price gap:
    (symbol, ex_date, subject) for demergers, rights, capital reductions."""
    subjects = ca["subject"].to_list()
    mask = pl.Series("m", [bool(_GAP_RE.search(s)) if s else False for s in subjects])
    return (
        ca.filter(mask & pl.col("ex_date").is_not_null())
        .select("symbol", "ex_date", "subject")
        .unique(subset=["symbol", "ex_date"])
        .sort("symbol", "ex_date")
    )


def declared_factor_events(ca: pl.DataFrame) -> pl.DataFrame:
    """Declared events with a derivable factor: (symbol, ex_date, subject, factor).

    Exact duplicates collapse (the feed repeats records across series); a
    bonus and a split on the same ex-date both survive - the adjuster
    multiplies them.
    """
    factors = [expected_factor(s) if s else None for s in ca["subject"].to_list()]
    return (
        ca.with_columns(pl.Series("factor", factors, dtype=pl.Float64))
        .filter(pl.col("factor").is_not_null() & pl.col("ex_date").is_not_null())
        .select("symbol", "ex_date", "subject", "factor")
        .unique(subset=["symbol", "ex_date", "subject"])
        .sort("symbol", "ex_date")
    )
