"""symbolchange.csv parsing: right-anchored split, commas in company names."""

from datetime import date

import pytest

from artha.data.ingest.symbolchange import SymbolChangeParseError, parse_symbolchange

SAMPLE = b"""\
 NIPPON INDIA MF - NIPPON INDIA Dual Advantage FTF  Sr. x Plan E -  GO,RDAXEDG,NDAXEDG,30-OCT-2019
HCL Infosystems Limited,HCL-HP,HCL-INSYS,12-APR-2000
Infosys Limited,INFOSYSTCH,INFY,29-JUN-2011

"""


def test_parse_real_shapes() -> None:
    df = parse_symbolchange(SAMPLE)
    assert df.height == 3
    infy = df.filter(df["new_symbol"] == "INFY").row(0, named=True)
    assert infy["company"] == "Infosys Limited"
    assert infy["old_symbol"] == "INFOSYSTCH"
    assert infy["change_date"] == date(2011, 6, 29)
    # Company name containing commas/hyphens survives the right-anchored split.
    nippon = df.filter(df["old_symbol"] == "RDAXEDG").row(0, named=True)
    assert nippon["new_symbol"] == "NDAXEDG"
    assert df["change_date"].is_sorted()


def test_unparseable_row_is_loud() -> None:
    with pytest.raises(SymbolChangeParseError):
        parse_symbolchange(b"garbage line with no commas\n")
