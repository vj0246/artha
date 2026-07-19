"""Adjustment engine: rename unification, declared events, backward factors."""

from datetime import date

import polars as pl

from artha.data.adjust import (
    adjustment_events,
    apply_adjustment,
    combine_events,
    equity_panel,
    gap_factor_events,
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


def mk_declared(rows: list[tuple[str, date, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        [{"symbol": s, "ex_date": d, "factor": f, "subject": "Bonus 1:1"} for s, d, f in rows],
        schema={
            "symbol": pl.String,
            "ex_date": pl.Date,
            "factor": pl.Float64,
            "subject": pl.String,
        },
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


class TestAdjustmentEvents:
    def test_declared_symbol_canonicalized_date_aware(self) -> None:
        # OLDCO renamed to NEWCO in 2020: its 2015 event belongs to NEWCO,
        # but a different company using OLDCO in 2022 keeps its own event.
        declared = mk_declared(
            [
                ("OLDCO", date(2015, 3, 2), 0.5),
                ("OLDCO", date(2022, 5, 2), 0.1),
            ]
        )
        changes = mk_changes([("OLDCO", "NEWCO", date(2020, 1, 1))])
        events = adjustment_events(declared, changes)
        assert events.to_dicts() == [
            {"canon_symbol": "NEWCO", "ex_date": date(2015, 3, 2), "factor": 0.5},
            {"canon_symbol": "OLDCO", "ex_date": date(2022, 5, 2), "factor": 0.1},
        ]

    def test_same_day_events_multiply(self) -> None:
        declared = pl.DataFrame(
            {
                "symbol": ["M", "M"],
                "ex_date": [date(2024, 1, 2)] * 2,
                "factor": [0.5, 0.1],  # bonus and split on one ex-date
                "subject": ["Bonus 1:1", "Face Value Split From Rs 10 To Re 1"],
            }
        )
        events = adjustment_events(declared, NO_CHANGES)
        assert events.height == 1
        assert events.row(0, named=True)["factor"] == 0.05


class TestGapFactorEvents:
    def test_observed_gap_and_precedence(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "G", "EQ", 100.0, 100.0, 10),
                (date(2024, 1, 2), "G", "EQ", 96.5, 100.0, 10),  # demerger ex-date
                (date(2024, 1, 3), "G", "EQ", 97.0, 96.5, 10),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        # mk_bhav sets open = close, so the observed gap is 96.5 / 100
        gap_dates = pl.DataFrame({"canon_symbol": ["G"], "ex_date": [date(2024, 1, 2)]})
        gaps = gap_factor_events(panel, gap_dates)
        assert gaps.height == 1
        assert gaps.row(0, named=True)["factor"] == 0.965

        # a parsed event on the same date is superseded by the gap factor
        parsed = adjustment_events(mk_declared([("G", date(2024, 1, 2), 0.5)]), NO_CHANGES)
        events = combine_events(parsed, gaps)
        assert events.height == 1
        assert events.row(0, named=True)["factor"] == 0.965

    def test_gap_up_is_not_an_event(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "U", "EQ", 100.0, 100.0, 10),
                (date(2024, 1, 2), "U", "EQ", 101.0, 100.0, 10),  # market drift only
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        gap_dates = pl.DataFrame({"canon_symbol": ["U"], "ex_date": [date(2024, 1, 2)]})
        assert gap_factor_events(panel, gap_dates).is_empty()

    def test_weekend_ex_date_snaps_to_next_session(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 5), "W", "EQ", 100.0, 100.0, 10),  # Friday
                (date(2024, 1, 8), "W", "EQ", 90.0, 100.0, 10),  # Monday
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        gap_dates = pl.DataFrame({"canon_symbol": ["W"], "ex_date": [date(2024, 1, 6)]})
        gaps = gap_factor_events(panel, gap_dates)
        assert gaps.row(0, named=True)["ex_date"] == date(2024, 1, 8)
        assert gaps.row(0, named=True)["factor"] == 0.9


class TestApplyAdjustment:
    def test_backward_factors_and_volume(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "R", "EQ", 100.0, 100.0, 100),
                (date(2024, 1, 2), "R", "EQ", 102.0, 100.0, 100),
                (date(2024, 1, 3), "R", "EQ", 52.0, 52.0, 200),  # 1:1 bonus ex-date
                (date(2024, 1, 4), "R", "EQ", 53.0, 52.0, 200),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        events = adjustment_events(mk_declared([("R", date(2024, 1, 3), 0.5)]), NO_CHANGES)
        adjusted = apply_adjustment(panel, events).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.5, 0.5, 1.0, 1.0]
        assert adjusted["adj_close"].to_list() == [50.0, 51.0, 52.0, 53.0]
        assert adjusted["adj_volume"].to_list() == [200.0, 200.0, 200.0, 200.0]

    def test_multiple_events_compound(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "M", "EQ", 400.0, 400.0, 10),
                (date(2024, 1, 2), "M", "EQ", 200.0, 200.0, 10),  # 1:1 -> 0.5
                (date(2024, 1, 3), "M", "EQ", 100.0, 100.0, 10),  # 1:1 again -> 0.5
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        events = adjustment_events(
            mk_declared([("M", date(2024, 1, 2), 0.5), ("M", date(2024, 1, 3), 0.5)]),
            NO_CHANGES,
        )
        adjusted = apply_adjustment(panel, events).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.25, 0.5, 1.0]
        assert adjusted["adj_close"].to_list() == [100.0, 100.0, 100.0]

    def test_ex_date_on_non_trading_day_snaps_forward(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 5), "S", "EQ", 100.0, 100.0, 10),  # Friday
                (date(2024, 1, 8), "S", "EQ", 50.0, 50.0, 20),  # Monday, post-CA units
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        # declared ex-date lands on Saturday
        events = adjustment_events(mk_declared([("S", date(2024, 1, 6), 0.5)]), NO_CHANGES)
        adjusted = apply_adjustment(panel, events).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.5, 1.0]
        assert adjusted["adj_close"].to_list() == [50.0, 50.0]

    def test_event_after_delisting_is_dropped(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "D", "EQ", 10.0, 10.0, 5),
                (date(2024, 1, 2), "D", "EQ", 11.0, 10.0, 5),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        events = adjustment_events(mk_declared([("D", date(2024, 6, 1), 0.5)]), NO_CHANGES)
        adjusted = apply_adjustment(panel, events)
        assert adjusted["cum_adj_factor"].to_list() == [1.0, 1.0]

    def test_no_events_is_identity(self) -> None:
        bhav = mk_bhav(
            [
                (date(2024, 1, 1), "I", "EQ", 10.0, 10.0, 5),
                (date(2024, 1, 2), "I", "EQ", 11.0, 10.0, 5),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        events = adjustment_events(mk_declared([]), NO_CHANGES)
        adjusted = apply_adjustment(panel, events)
        assert adjusted["cum_adj_factor"].to_list() == [1.0, 1.0]
        assert adjusted["adj_close"].to_list() == adjusted["close"].to_list()


class TestDeclaredFeedSanityGate:
    def test_phantom_declared_split_is_rejected(self) -> None:
        # the TVSMOTOR case: feed declares a 1:5 split but the price never splits
        bhav = mk_bhav(
            [
                (date(2025, 8, 22), "T", "EQ", 3294.6, 3280.9, 10),
                (date(2025, 8, 25), "T", "EQ", 3284.7, 3294.6, 10),  # no 5x drop
                (date(2025, 8, 26), "T", "EQ", 3272.3, 3284.7, 10),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        events = adjustment_events(mk_declared([("T", date(2025, 8, 25), 0.2)]), NO_CHANGES)
        adjusted = apply_adjustment(panel, events).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [1.0, 1.0, 1.0]

    def test_genuine_split_passes_the_gate(self) -> None:
        bhav = mk_bhav(
            [
                (date(2025, 8, 22), "G", "EQ", 1000.0, 990.0, 10),
                (date(2025, 8, 25), "G", "EQ", 201.0, 1000.0, 50),  # real 1:5
                (date(2025, 8, 26), "G", "EQ", 205.0, 201.0, 50),
            ]
        )
        panel = equity_panel(bhav, NO_CHANGES)
        events = adjustment_events(mk_declared([("G", date(2025, 8, 25), 0.2)]), NO_CHANGES)
        adjusted = apply_adjustment(panel, events).sort("trade_date")
        assert adjusted["cum_adj_factor"].to_list() == [0.2, 1.0, 1.0]
