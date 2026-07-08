"""Adjustment engine: rename unification, implied CA detection, backward factors."""

from datetime import date

import polars as pl

from artha.data.adjust import (
    apply_adjustment,
    combined_ca_events,
    equity_panel,
    implied_ca_events,
)

NO_CHANGES = pl.DataFrame(
    {
        "company": pl.Series([], dtype=pl.String),
        "old_symbol": pl.Series([], dtype=pl.String),
        "new_symbol": pl.Series([], dtype=pl.String),
        "change_date": pl.Series([], dtype=pl.Date),
    }
)


def mk_bhav(rows: list[tuple[date, str, str, float, float, int]]) -> pl.DataFrame:
    """(trade_date, symbol, series, close, prev_close, volume) -> bhav-like frame."""
    df = pl.DataFrame(
        [
            {
                "trade_date": r[0],
                "symbol": r[1],
                "series": r[2],
                "close": r[3],
                "prev_close": r[4],
                "volume": r[5],
            }
            for r in rows
        ]
    )
    return df.with_columns(
        pl.col("close").alias("open"),
        pl.col("close").alias("high"),
        pl.col("close").alias("low"),
    )


def mk_changes(rows: list[tuple[str, str, date]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"company": "X Ltd", "old_symbol": o, "new_symbol": n, "change_date": d}
            for o, n, d in rows
        ]
    )


class TestEquityPanel:
    def test_rename_chain_unifies_to_terminal_symbol(self) -> None:
        bhav = mk_bhav(
            [
                (date(2011, 1, 3), "A", "EQ", 100.0, 100.0, 10),
                (date(2013, 1, 3), "B", "EQ", 110.0, 110.0, 10),
                (date(2016, 1, 4), "C", "EQ", 120.0, 120.0, 10),
            ]
        )
        changes = mk_changes([("A", "B", date(2012, 1, 5)), ("B", "C", date(2015, 1, 5))])
        panel = equity_panel(bhav, changes)
        assert panel["canon_symbol"].unique().to_list() == ["C"]

    def test_reused_symbol_not_backmapped(self) -> None:
        bhav = mk_bhav(
            [
                (date(2011, 1, 3), "X", "EQ", 100.0, 100.0, 10),  # old company, pre-rename
                (date(2013, 1, 3), "X", "EQ", 55.0, 55.0, 10),  # different company, later
            ]
        )
        changes = mk_changes([("X", "Y", date(2012, 1, 5))])
        panel = equity_panel(bhav, changes).sort("trade_date")
        assert panel["canon_symbol"].to_list() == ["Y", "X"]

    def test_series_dedupe_prefers_eq(self) -> None:
        bhav = mk_bhav(
            [
                (date(2020, 1, 6), "S", "BE", 99.0, 99.0, 1),
                (date(2020, 1, 6), "S", "EQ", 100.0, 100.0, 10),
                (date(2020, 1, 6), "S", "GS", 1.0, 1.0, 1),  # non-equity dropped
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        assert panel.height == 1
        assert panel.row(0, named=True)["series"] == "EQ"


class TestImpliedEvents:
    def test_bonus_detected_with_exact_factor(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 10, 24), "R", "EQ", 100.0, 99.0, 10),
                (date(2024, 10, 25), "R", "EQ", 102.0, 100.0, 10),
                (date(2024, 10, 28), "R", "EQ", 50.5, 51.0, 20),  # 1:1 bonus ex-date
            ]
        )
        events = implied_ca_events(equity_panel(bhav, NO_CHANGES))
        assert events.height == 1
        ev = events.row(0, named=True)
        assert ev["ex_date"] == date(2024, 10, 28)
        assert ev["factor"] == 0.5
        assert ev["prior_close"] == 102.0

    def test_no_event_on_clean_days_and_ipo_first_row(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "N", "EQ", 100.0, 500.0, 10),  # listing day: no prior
                (date(2024, 1, 2), "N", "EQ", 101.0, 100.0, 10),
            ]
        )
        assert implied_ca_events(equity_panel(bhav, NO_CHANGES)).is_empty()

    def test_tolerances_suppress_noise(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "T", "EQ", 100.0, 99.0, 10),
                (date(2024, 1, 2), "T", "EQ", 100.0, 100.3, 10),  # 0.3% < rel tol
                (date(2024, 1, 3), "L", "EQ", 1.00, 0.99, 10),
                (date(2024, 1, 4), "L", "EQ", 1.00, 1.015, 10),  # 1.5% but abs < 0.02
            ]
        )
        assert implied_ca_events(equity_panel(bhav, NO_CHANGES)).is_empty()

    def test_consolidation_and_gap(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "G", "EQ", 20.0, 20.0, 10),
                # suspended for a week, returns consolidated 1:10
                (date(2024, 1, 8), "G", "EQ", 201.0, 200.0, 1),
            ]
        )
        events = implied_ca_events(equity_panel(bhav, NO_CHANGES))
        assert events.height == 1
        assert events.row(0, named=True)["factor"] == 10.0


class TestApplyAdjustment:
    def test_backward_factors_and_volume(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "R", "EQ", 100.0, 100.0, 100),
                (date(2024, 1, 2), "R", "EQ", 102.0, 100.0, 100),
                (date(2024, 1, 3), "R", "EQ", 52.0, 51.0, 200),  # factor 0.5
                (date(2024, 1, 4), "R", "EQ", 53.0, 52.0, 200),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        adjusted = apply_adjustment(panel, implied_ca_events(panel)).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.5, 0.5, 1.0, 1.0]
        assert adjusted["adj_close"].to_list() == [50.0, 51.0, 52.0, 53.0]
        assert adjusted["adj_volume"].to_list() == [200.0, 200.0, 200.0, 200.0]
        # Adjusted return across the ex-date equals the true economic return.
        assert adjusted["adj_close"][2] / adjusted["adj_close"][1] == 52.0 / 51.0

    def test_multiple_events_compound(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "M", "EQ", 400.0, 400.0, 10),
                (date(2024, 1, 2), "M", "EQ", 200.0, 200.0, 10),  # 1:1 -> 0.5
                (date(2024, 1, 3), "M", "EQ", 100.0, 100.0, 10),  # 1:1 again -> 0.5
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        adjusted = apply_adjustment(panel, implied_ca_events(panel)).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.25, 0.5, 1.0]
        assert adjusted["adj_close"].to_list() == [100.0, 100.0, 100.0]

    def test_no_events_is_identity(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "I", "EQ", 10.0, 10.0, 5),
                (date(2024, 1, 2), "I", "EQ", 11.0, 10.0, 5),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        adjusted = apply_adjustment(panel, implied_ca_events(panel))
        assert adjusted["cum_adj_factor"].to_list() == [1.0, 1.0]
        assert adjusted["adj_close"].to_list() == adjusted["close"].to_list()


class TestCombinedEvents:
    CUTOVER = date(2024, 7, 1)

    def test_era_split_and_declared_canonicalization(self) -> None:
        implied = pl.DataFrame(
            {
                "canon_symbol": ["A", "A"],
                "ex_date": [date(2015, 3, 2), date(2024, 10, 28)],  # post-cutover: phantom
                "factor": [0.5, 0.98],
            }
        )
        declared = pl.DataFrame(
            {
                # OLDCO renamed to A in 2020, so this 2015 event belongs to A;
                # both declared events are pre-cutover except the bonus
                "symbol": ["OLDCO", "A", "A"],
                "ex_date": [date(2015, 3, 2), date(2015, 3, 2), date(2024, 10, 28)],
                "factor": [0.5, 0.5, 0.5],
            }
        )
        changes = mk_changes([("OLDCO", "A", date(2020, 1, 1))])
        events = combined_ca_events(implied, declared, changes, implied_until=self.CUTOVER)
        # pre-cutover: only the implied event; post-cutover: only the declared one
        assert events.select("canon_symbol", "ex_date", "factor", "source").to_dicts() == [
            {
                "canon_symbol": "A",
                "ex_date": date(2015, 3, 2),
                "factor": 0.5,
                "source": "implied",
            },
            {
                "canon_symbol": "A",
                "ex_date": date(2024, 10, 28),
                "factor": 0.5,
                "source": "declared",
            },
        ]

    def test_adjustment_uses_declared_after_cutover(self) -> None:
        # UDiFF era: prev_close is NOT base-adjusted, so implied finds nothing
        bhav = mk_bhav(
            [
                (date(2024, 10, 24), "R", "EQ", 102.0, 100.0, 100),
                (date(2024, 10, 28), "R", "EQ", 51.0, 102.0, 200),  # bonus, raw prev_close
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        implied = implied_ca_events(panel).filter(pl.col("ex_date") < self.CUTOVER)
        declared = pl.DataFrame({"symbol": ["R"], "ex_date": [date(2024, 10, 28)], "factor": [0.5]})
        events = combined_ca_events(implied, declared, NO_CHANGES, implied_until=self.CUTOVER)
        adjusted = apply_adjustment(panel, events).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.5, 1.0]
        assert adjusted["adj_close"].to_list() == [51.0, 51.0]
