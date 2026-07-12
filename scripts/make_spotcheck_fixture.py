"""Snapshot Yahoo Finance reference data for the 20-name adjustment spot-check.

Run with:  uv run --with yfinance python scripts/make_spotcheck_fixture.py

Writes tests/fixtures/reference/yahoo_prices.csv (Close, split-adjusted, no
dividends, on fixed sample dates) and yahoo_splits.csv (full split/bonus
history per name). The regression test compares the curated panel against
these snapshots, so the test itself needs no network and no yfinance.
"""

import csv
from datetime import date
from pathlib import Path

import yfinance as yf

SYMBOLS = [
    "RELIANCE",
    "INFY",
    "TCS",
    "WIPRO",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "ITC",
    "LT",
    "HINDUNILVR",
    "BHARTIARTL",
    "ASIANPAINT",
    "MARUTI",
    "BAJFINANCE",
    "TITAN",
    "NESTLEIND",
    "ULTRACEMCO",
    "TATAMOTORS",
    "TATASTEEL",
    "AXISBANK",
]

SAMPLE_DATES = [
    date(2012, 1, 4),
    date(2015, 6, 1),
    date(2018, 9, 3),
    date(2021, 3, 1),
    date(2024, 2, 1),
    date(2026, 7, 1),
]

OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "reference"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    price_rows: list[tuple[str, str, float]] = []
    split_rows: list[tuple[str, str, float]] = []

    for sym in SYMBOLS:
        t = yf.Ticker(f"{sym}.NS")
        hist = t.history(start="2011-12-01", auto_adjust=False)
        if hist.empty:
            print(f"{sym}: EMPTY history from Yahoo, skipped")
            continue
        closes = hist["Close"]
        closes.index = closes.index.tz_localize(None)
        for d in SAMPLE_DATES:
            window = closes.loc[str(d) : str(date(d.year, d.month, d.day + 7))]
            if len(window):
                actual = window.index[0].date()
                price_rows.append((sym, actual.isoformat(), round(float(window.iloc[0]), 4)))
        for ts, ratio in t.splits.items():
            split_rows.append((sym, ts.date().isoformat(), float(ratio)))
        print(
            f"{sym}: {sum(1 for r in price_rows if r[0] == sym)} prices, "
            f"{sum(1 for r in split_rows if r[0] == sym)} splits"
        )

    with (OUT_DIR / "yahoo_prices.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "trade_date", "yahoo_close"])
        w.writerows(price_rows)
    with (OUT_DIR / "yahoo_splits.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "ex_date", "yahoo_ratio"])
        w.writerows(split_rows)
    print(f"wrote {len(price_rows)} prices, {len(split_rows)} splits -> {OUT_DIR}")


if __name__ == "__main__":
    main()
