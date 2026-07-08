"""Bhavcopy URL scheme and parser tests against real trimmed NSE files.

Fixture values were read off the actual archive files (see ADR 0002); they
double as regression anchors for both format parsers.
"""

import zipfile
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from artha.data.ingest.bhavcopy import (
    CANONICAL_COLUMNS,
    BhavcopyParseError,
    bhavcopy_relpath,
    bhavcopy_url,
    parse_bhavcopy,
    read_bhavcopy_zip,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "bhavcopy"


def _load(name: str, trade_date: date) -> pl.DataFrame:
    return parse_bhavcopy((FIXTURES / name).read_bytes(), trade_date=trade_date)


def _reliance(df: pl.DataFrame) -> dict[str, object]:
    return df.filter(pl.col("symbol") == "RELIANCE").row(0, named=True)


class TestUrlScheme:
    def test_old_format_before_cutover(self) -> None:
        assert bhavcopy_url(date(2010, 1, 4)) == (
            "https://nsearchives.nseindia.com/content/historical/EQUITIES/2010/JAN/"
            "cm04JAN2010bhav.csv.zip"
        )
        assert bhavcopy_url(date(2024, 6, 28)).endswith("/2024/JUN/cm28JUN2024bhav.csv.zip")

    def test_udiff_from_cutover(self) -> None:
        assert bhavcopy_url(date(2024, 7, 1)) == (
            "https://nsearchives.nseindia.com/content/cm/"
            "BhavCopy_NSE_CM_0_0_0_20240701_F_0000.csv.zip"
        )

    def test_relpath_partitioned_by_year(self) -> None:
        assert bhavcopy_relpath(date(2010, 1, 4)) == "bhavcopy/2010/cm04JAN2010bhav.csv.zip"
        assert (
            bhavcopy_relpath(date(2026, 7, 3))
            == "bhavcopy/2026/BhavCopy_NSE_CM_0_0_0_20260703_F_0000.csv.zip"
        )


class TestOldFormat:
    def test_2010_variant_without_isin_and_trades(self) -> None:
        df = _load("cm04JAN2010bhav.csv", date(2010, 1, 4))
        assert df.columns == CANONICAL_COLUMNS
        assert df.height == 5
        row = _reliance(df)
        assert row["trade_date"] == date(2010, 1, 4)  # unpadded "4-JAN-2010" handled
        assert row["close"] == 1075.5
        assert row["volume"] == 17520006
        assert row["traded_value"] == 18298628322.9
        assert row["isin"] is None
        assert row["trades"] is None

    def test_2020_variant_with_two_digit_year(self) -> None:
        # NSE shipped "13-Jul-20" instead of "13-JUL-2020" in some files
        df = _load("cm13JUL2020bhav.csv", date(2020, 7, 13))
        assert df.height == 4
        row = _reliance(df)
        assert row["trade_date"] == date(2020, 7, 13)
        assert row["close"] == 1935.0

    def test_2023_variant_with_isin_and_trades(self) -> None:
        df = _load("cm02JAN2023bhav.csv", date(2023, 1, 2))
        assert df.height == 6
        row = _reliance(df)
        assert row["close"] == 2575.9
        assert row["trades"] == 97175
        assert row["isin"] == "INE002A01018"
        assert df.filter(pl.col("series") != "EQ").height == 1  # non-equity series kept


class TestUdiffFormat:
    def test_parse(self) -> None:
        df = _load("BhavCopy_NSE_CM_0_0_0_20240705_F_0000.csv", date(2024, 7, 5))
        assert df.columns == CANONICAL_COLUMNS
        assert df.height == 6
        row = _reliance(df)
        assert row["close"] == 3177.25
        assert row["volume"] == 6134855
        assert row["trades"] == 261494
        assert row["isin"] == "INE002A01018"
        assert df.filter(pl.col("series") != "EQ").height == 1

    def test_current_2026_file_still_parses(self) -> None:
        df = _load("BhavCopy_NSE_CM_0_0_0_20260703_F_0000.csv", date(2026, 7, 3))
        assert _reliance(df)["close"] == 1304.0

    def test_wrong_date_rejected(self) -> None:
        with pytest.raises(BhavcopyParseError, match="other dates"):
            _load("BhavCopy_NSE_CM_0_0_0_20240705_F_0000.csv", date(2024, 7, 4))


class TestCrossFormatParity:
    def test_same_day_identical_across_formats(self) -> None:
        """2024-07-05 was published in BOTH formats; equity rows must agree."""
        d = date(2024, 7, 5)
        old = _load("cm05JUL2024bhav.csv", d).filter(pl.col("series") == "EQ")
        new = _load("BhavCopy_NSE_CM_0_0_0_20240705_F_0000.csv", d).filter(pl.col("series") == "EQ")
        joined = old.join(new, on=["symbol", "series"], suffix="_udiff")
        assert joined.height == old.height == new.height
        for col in [
            "open",
            "high",
            "low",
            "close",
            "prev_close",
            "volume",
            "traded_value",
            "trades",
            "isin",
        ]:
            mismatch = joined.filter(pl.col(col) != pl.col(f"{col}_udiff"))
            assert mismatch.is_empty(), f"{col} differs between formats:\n{mismatch}"


class TestZipReading:
    def _zip_of(self, tmp_path: Path, *members: str) -> Path:
        zpath = tmp_path / "bhav.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for m in members:
                zf.writestr(m, (FIXTURES / m).read_bytes())
        return zpath

    def test_reads_single_csv_member(self, tmp_path: Path) -> None:
        zpath = self._zip_of(tmp_path, "BhavCopy_NSE_CM_0_0_0_20240705_F_0000.csv")
        df = read_bhavcopy_zip(zpath, trade_date=date(2024, 7, 5))
        assert df.height == 6

    def test_rejects_multi_member_zip(self, tmp_path: Path) -> None:
        zpath = self._zip_of(
            tmp_path, "cm04JAN2010bhav.csv", "BhavCopy_NSE_CM_0_0_0_20240705_F_0000.csv"
        )
        with pytest.raises(BhavcopyParseError, match="exactly one csv member"):
            read_bhavcopy_zip(zpath, trade_date=date(2024, 7, 5))
