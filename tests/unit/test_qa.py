"""QA suite: structural errors block, statistical anomalies warn."""

from datetime import date

import polars as pl

from artha.data.qa import QaReport, run_qa


def mk_panel(rows: list[dict[str, object]]) -> pl.DataFrame:
    base = {
        "canon_symbol": "A",
        "trade_date": date(2024, 1, 1),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "prev_close": 100.0,
        "volume": 1000,
        "adj_close": 100.0,
    }
    return pl.DataFrame([{**base, **r} for r in rows])


def clean_two_days() -> list[dict[str, object]]:
    return [
        {"trade_date": date(2024, 1, 1)},
        {"trade_date": date(2024, 1, 2), "close": 101.0, "adj_close": 101.0},
    ]


def test_clean_panel_passes() -> None:
    report = run_qa(mk_panel(clean_two_days()))
    assert report.ok
    assert report.warnings == {}


def test_structural_errors_detected() -> None:
    rows: list[dict[str, object]] = [
        *clean_two_days(),
        {"trade_date": date(2024, 1, 3), "close": -5.0, "adj_close": -5.0},
        {"trade_date": date(2024, 1, 4), "high": 90.0},  # high < low
        {"trade_date": date(2024, 1, 5), "close": 200.0, "adj_close": 100.5},  # above high
        {"trade_date": date(2024, 1, 8), "volume": -1},
        {"trade_date": date(2024, 1, 9)},
        {"trade_date": date(2024, 1, 9)},  # duplicate
    ]
    report = run_qa(mk_panel(rows))
    assert not report.ok
    assert report.errors["nonpositive_price"] == 1
    assert report.errors["high_below_low"] == 1
    assert report.errors["close_outside_range"] >= 1
    assert report.errors["negative_volume"] == 1
    assert report.errors["duplicate_symbol_date"] == 1


def test_return_outlier_warns_not_blocks() -> None:
    rows: list[dict[str, object]] = [
        {"trade_date": date(2024, 1, 1)},
        {
            "trade_date": date(2024, 1, 2),
            "open": 40.0,
            "high": 41.0,
            "low": 39.0,
            "close": 40.0,
            "adj_close": 40.0,  # -60% adjusted return: mis-adjusted CA signature
        },
    ]
    report = run_qa(mk_panel(rows))
    assert report.ok
    out = report.warnings["return_outliers"]
    assert out.height == 1
    assert out.row(0, named=True)["adj_return"] == -0.6


def test_thin_date_warns() -> None:
    rows: list[dict[str, object]] = []
    for day in range(1, 6):
        for sym in ("A", "B", "C", "D"):
            rows.append({"canon_symbol": sym, "trade_date": date(2024, 1, day)})
    rows.append({"canon_symbol": "A", "trade_date": date(2024, 1, 8)})  # 1 row vs median 4
    report = run_qa(mk_panel(rows))
    assert report.ok
    thin = report.warnings["thin_dates"]
    assert thin["trade_date"].to_list() == [date(2024, 1, 8)]


def test_summary_shape() -> None:
    report = QaReport(errors={"x": 2}, warnings={"y": pl.DataFrame({"a": [1, 2]})})
    assert report.summary() == {"ok": False, "errors": {"x": 2}, "warnings": {"y": 2}}
