"""Index close and NIFTY 500 constituent ingest: URLs, parsing, null handling."""

from datetime import date
from pathlib import Path

import pytest

from artha.data.ingest.indices import (
    IndexParseError,
    index_close_relpath,
    index_close_url,
    nifty500_snapshot_relpath,
    parse_index_close,
    parse_nifty500_list,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "indices"


def test_paths_and_urls() -> None:
    d = date(2024, 7, 1)
    assert index_close_url(d) == (
        "https://nsearchives.nseindia.com/content/indices/ind_close_all_01072024.csv"
    )
    assert index_close_relpath(d) == "indexclose/2024/ind_close_all_01072024.csv"
    assert nifty500_snapshot_relpath(date(2026, 7, 8)) == "constituents/nifty500_20260708.csv"


class TestParseIndexClose:
    def test_real_fixture(self) -> None:
        content = (FIXTURES / "ind_close_all_01072024.csv").read_bytes()
        df = parse_index_close(content, date(2024, 7, 1))
        assert df.height == 4
        n500 = df.filter(index_name="Nifty 500").row(0, named=True)
        assert n500["close"] == 22727.6
        assert n500["turnover_cr"] == 97456.03
        # '-' fields become null (Nifty 1D Rate Index has no OHLC/volume)
        rate = df.filter(index_name="Nifty 1D Rate Index").row(0, named=True)
        assert rate["open"] is None
        assert rate["volume"] is None
        assert rate["close"] == 2297.88

    def test_slash_dates_normalized(self) -> None:
        content = (
            b"Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
            b"Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),"
            b"P/E,P/B,Div Yield\n"
            b"Nifty 50,01/09/2014,,8100,7990,8050,50,.62,100,10.5,20,3,1.2\n"
        )
        df = parse_index_close(content, date(2014, 9, 1))
        row = df.row(0, named=True)
        assert row["close"] == 8050.0
        assert row["open"] is None  # empty numeric field -> null

    def test_month_first_dates_disambiguated(self) -> None:
        # some 2023 vintages write MM-DD-YYYY; the filename date decides
        content = (
            b"Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
            b"Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),"
            b"P/E,P/B,Div Yield\n"
            b"Nifty 50,04-06-2023,17550,17600,17500,17580,30,.17,100,10.5,20,3,1.2\n"
        )
        df = parse_index_close(content, date(2023, 4, 6))
        assert df.row(0, named=True)["trade_date"] == date(2023, 4, 6)
        # and the same string is day-first when the filename says June 4th
        df2 = parse_index_close(content, date(2023, 6, 4))
        assert df2.row(0, named=True)["trade_date"] == date(2023, 6, 4)

    def test_wrong_date_rejected(self) -> None:
        content = (FIXTURES / "ind_close_all_01072024.csv").read_bytes()
        with pytest.raises(IndexParseError, match="expected 2024-07-02"):
            parse_index_close(content, date(2024, 7, 2))

    def test_bad_header_rejected(self) -> None:
        with pytest.raises(IndexParseError, match="unexpected header"):
            parse_index_close(b"Symbol,Close\nX,1\n", date(2024, 7, 1))


class TestParseNifty500List:
    def test_real_fixture(self) -> None:
        content = (FIXTURES / "ind_nifty500list.csv").read_bytes()
        df = parse_nifty500_list(content)
        assert df.height == 5
        assert df["symbol"].to_list() == ["360ONE", "3MINDIA", "ABB", "ACC", "ACMESOLAR"]
        row = df.filter(symbol="ABB").row(0, named=True)
        assert row["isin"] == "INE117A01022"
        assert row["series"] == "EQ"

    def test_company_name_with_comma_survives(self) -> None:
        content = (
            b"Company Name,Industry,Symbol,Series,ISIN Code\n"
            b'"Acme, Inc.",Power,ACME,EQ,INE000000001\n'
        )
        df = parse_nifty500_list(content)
        assert df.row(0, named=True)["company"] == "Acme, Inc."

    def test_bad_header_rejected(self) -> None:
        with pytest.raises(IndexParseError, match="unexpected header"):
            parse_nifty500_list(b"Symbol,ISIN\nX,1\n")
