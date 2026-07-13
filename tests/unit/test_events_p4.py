"""P4: taxonomy rules and event-study math."""

from datetime import date, timedelta

import polars as pl
import pytest

from artha.events.event_study import (
    car_significance,
    cumulative_abnormal_returns,
    market_model_abnormal,
)
from artha.events.taxonomy import CATEGORIES, classify_rule_based


class TestTaxonomyRules:
    def test_categories(self) -> None:
        cases = {
            "Unaudited Financial Results for the quarter ended June 30": "earnings_result",
            "Bagging of order worth Rs 500 crore from NTPC": "order_win",
            "Intimation of capacity expansion at Dahej plant": "capex_expansion",
            "Disclosure of pledge of promoter shares": "pledge",
            "CRISIL rating upgraded to AA+": "rating_action",
            "Scheme of Arrangement for demerger of hotels business": "m_and_a",
            "Approval of QIP issue of equity shares": "fundraising",
            "SEBI order in the matter of insider trading": "litigation_regulatory",
            "Resignation of Chief Financial Officer": "board_change",
            "Board recommends dividend of Rs 5 per share": "dividend_distribution",
            "Trading window closure": "other",
        }
        for subject, want in cases.items():
            got = classify_rule_based(subject)
            assert got.category == want, f"{subject!r} -> {got.category}, want {want}"
            assert got.category in CATEGORIES

    def test_audit_driven_precedence_guards(self) -> None:
        # systematic false positives found in the 297-subject audit
        cases = {
            "Disclosure under SEBI (Substantial Acquisition of Shares & Takeovers) "
            "Regulations, 2011": "other",
            "GST order received from Assistant Commissioner": "litigation_regulatory",
            "Demand order u/s 73 of the SGST Act for payment of Tax": "litigation_regulatory",
            "Notice of the NCLT Convened Meeting of the Equity Shareholders": "m_and_a",
            "Mphasis pledges to be Carbon neutral by 2030": "other",
            # and the true positives still classify correctly
            "Bagging of order for 2,400 Electric Buses": "order_win",
            "Creation of Pledge on the shares of the promoter": "pledge",
            "Proposed Merger of Sesa Care with Dabur India": "m_and_a",
        }
        for subject, want in cases.items():
            assert classify_rule_based(subject).category == want, subject

    def test_direction_and_materiality(self) -> None:
        assert classify_rule_based("Disclosure of pledge of shares").direction == -1
        assert classify_rule_based("SEBI order passed").materiality == 2
        assert classify_rule_based(None).category == "other"


def weekdays_from(start: date, n: int) -> list[date]:
    days: list[date] = []
    d = start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


DAYS = weekdays_from(date(2022, 1, 3), 200)


def _mk_market() -> pl.DataFrame:
    # flat market: rm = 0 -> abnormal return equals raw return minus alpha
    return pl.DataFrame({"trade_date": DAYS, "tr_return": [0.0] * len(DAYS)})


def _mk_panel(jump_at: int) -> pl.DataFrame:
    rows = []
    price = 100.0
    for i, d in enumerate(DAYS):
        price = price * (1.10 if i == jump_at else 1.0)
        rows.append({"canon_symbol": "E", "trade_date": d, "adj_close": price})
    return pl.DataFrame(rows)


class TestEventStudy:
    def test_abnormal_return_catches_jump(self) -> None:
        ar = market_model_abnormal(_mk_panel(jump_at=150), _mk_market())
        row = ar.filter(pl.col("trade_date") == DAYS[150])
        assert row["ar"][0] == pytest.approx(0.10, abs=0.01)
        # quiet day: ~0
        quiet = ar.filter(pl.col("trade_date") == DAYS[160])
        assert abs(quiet["ar"][0]) < 0.01

    def test_car_window_and_coverage(self) -> None:
        ar = market_model_abnormal(_mk_panel(jump_at=150), _mk_market())
        events = pl.DataFrame({"canon_symbol": ["E"], "event_date": [DAYS[150]]})
        car_0_1 = cumulative_abnormal_returns(ar, events, window=(0, 1))
        assert car_0_1["car"][0] == pytest.approx(0.10, abs=0.02)
        # window starting after the jump excludes it
        car_2_5 = cumulative_abnormal_returns(ar, events, window=(2, 5))
        assert abs(car_2_5["car"][0]) < 0.02
        # event too close to the panel end drops (incomplete window)
        late = pl.DataFrame({"canon_symbol": ["E"], "event_date": [DAYS[-1]]})
        assert cumulative_abnormal_returns(ar, late, window=(0, 5)).is_empty()

    def test_car_significance(self) -> None:
        cars = pl.DataFrame({"car": [0.05, 0.04, 0.06, 0.05, 0.045, 0.055] * 5})
        stats = car_significance(cars)
        assert stats.n_events == 30
        assert stats.mean_car == pytest.approx(0.05, abs=0.005)
        assert stats.t_stat > 10
        assert stats.bootstrap_p < 0.01
