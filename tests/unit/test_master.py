"""Security master: latest ISIN, trade-date span, current-sector join."""

from datetime import date

import polars as pl

from artha.data.master import build_security_master


def test_build_security_master() -> None:
    panel = pl.DataFrame(
        {
            "canon_symbol": ["A", "A", "B", "GONE"],
            "trade_date": [
                date(2020, 1, 1),
                date(2024, 1, 2),
                date(2024, 1, 2),
                date(2015, 5, 5),
            ],
            "isin": [None, "INE0A", "INE0B", None],  # A gains an ISIN later
        }
    )
    n500 = pl.DataFrame(
        {
            "symbol": ["A"],
            "company": ["A Ltd"],
            "industry": ["Power"],
            "series": ["EQ"],
            "isin": ["INE0A"],
        }
    )
    master = build_security_master(panel, n500)
    assert master.height == 3
    a = master.filter(pl.col("canon_symbol") == "A").row(0, named=True)
    assert a["isin"] == "INE0A"
    assert a["first_trade_date"] == date(2020, 1, 1)
    assert a["last_trade_date"] == date(2024, 1, 2)
    assert a["industry"] == "Power"
    # delisted name survives with null sector: survivorship-free master
    gone = master.filter(pl.col("canon_symbol") == "GONE").row(0, named=True)
    assert gone["industry"] is None
    assert gone["last_trade_date"] == date(2015, 5, 5)
