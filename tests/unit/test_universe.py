"""PIT universe: age, liquidity, price filters and per-date liquidity ranking."""

from datetime import date, timedelta

import polars as pl

from artha.data.universe import pit_universe


def mk_panel(symbols: dict[str, dict[str, float]], n_days: int) -> pl.DataFrame:
    """Constant-per-symbol panel over consecutive weekdays.

    symbols: name -> {"close": .., "tv": .., "start": day offset}.
    """
    days: list[date] = []
    d = date(2024, 1, 1)
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    rows = []
    for sym, spec in symbols.items():
        for i, day in enumerate(days):
            if i < int(spec.get("start", 0)):
                continue
            rows.append(
                {
                    "canon_symbol": sym,
                    "trade_date": day,
                    "close": spec["close"],
                    "traded_value": spec["tv"],
                }
            )
    return pl.DataFrame(rows)


def small_universe(panel: pl.DataFrame) -> pl.DataFrame:
    return pit_universe(
        panel, min_traded_value=100.0, min_listed_days=5, liquidity_window=3, top_n=2
    )


def test_filters_and_ranking() -> None:
    panel = mk_panel(
        {
            "BIG": {"close": 500.0, "tv": 1000.0},
            "MID": {"close": 100.0, "tv": 500.0},
            "SMALL": {"close": 50.0, "tv": 200.0},  # passes filters, loses on rank
            "ILLIQ": {"close": 50.0, "tv": 10.0},  # below traded-value floor
            "PENNY": {"close": 5.0, "tv": 900.0},  # below price floor
        },
        n_days=8,
    )
    out = small_universe(panel)
    last = out.filter(pl.col("trade_date") == out["trade_date"].max())
    in_names = sorted(last.filter(pl.col("in_universe"))["canon_symbol"].to_list())
    assert in_names == ["BIG", "MID"]
    ranks = {r["canon_symbol"]: r["liquidity_rank"] for r in last.iter_rows(named=True)}
    assert ranks["BIG"] == 1
    assert ranks["MID"] == 2
    assert ranks["SMALL"] == 3
    assert ranks["ILLIQ"] is None
    assert ranks["PENNY"] is None


def test_age_gate_is_point_in_time() -> None:
    panel = mk_panel(
        {
            "OLD": {"close": 100.0, "tv": 1000.0},
            "IPO": {"close": 100.0, "tv": 2000.0, "start": 4},  # lists on day 5
        },
        n_days=10,
    )
    out = small_universe(panel)
    ipo = out.filter(pl.col("canon_symbol") == "IPO").sort("trade_date")
    # needs min_listed_days=5 sessions AND a full 3-day liquidity window
    assert ipo["in_universe"].to_list() == [False, False, False, False, True, True]
    # OLD is in from the day its own gates clear, regardless of IPO
    old = out.filter(pl.col("canon_symbol") == "OLD").sort("trade_date")
    assert old["in_universe"].to_list() == [False] * 4 + [True] * 6


def test_liquidity_window_requires_full_history() -> None:
    panel = mk_panel({"A": {"close": 100.0, "tv": 1000.0}}, n_days=4)
    out = small_universe(panel)
    assert out["median_traded_value"].null_count() == 2  # first window-1 rows
    assert not out["in_universe"].any()  # age gate (5) never satisfied in 4 days
