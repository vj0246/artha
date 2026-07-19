"""NSE cost model: hand-computed charge fractions and impact scaling."""

from datetime import date

import pytest

from artha.data.calendar import TradingCalendar
from artha.marketspec import NSECostModel, nse_spec

# hand computation (rates verified 2026-07-19): levies = NSE txn 0.0000307
# + SEBI 0.000001 = 0.0000317; GST 18% applies to the levies
# buy = 0.001 + 0.0000317*1.18 + 0.00015; sell drops the stamp duty
BUY_CHARGES = 0.001 + 0.0000317 * 1.18 + 0.00015
SELL_CHARGES = 0.001 + 0.0000317 * 1.18


def test_charges_without_impact() -> None:
    m = NSECostModel()
    assert m.buy_cost(0.0, 0.0) == pytest.approx(BUY_CHARGES)
    assert m.sell_cost(0.0, 0.0) == pytest.approx(SELL_CHARGES)
    # plan section 6 sanity: ~0.12% buy, ~0.10% sell before slippage
    assert 0.0011 < m.buy_cost(0.0, 0.0) < 0.0013
    assert 0.0010 < m.sell_cost(0.0, 0.0) < 0.0011


def test_impact_sqrt_scaling() -> None:
    m = NSECostModel()
    # order = 1% of ADV: 3 + 10*0.1 = 4 bps
    assert m.buy_cost(1e5, 1e7) == pytest.approx(BUY_CHARGES + 4 / 10_000)
    # order = 4% of ADV: 3 + 10*0.2 = 5 bps
    assert m.buy_cost(4e5, 1e7) == pytest.approx(BUY_CHARGES + 5 / 10_000)
    half = NSECostModel(impact_multiplier=0.5)
    assert half.buy_cost(1e5, 1e7) == pytest.approx(BUY_CHARGES + 2 / 10_000)


def test_dp_charge_only_on_sells_and_scales_inversely() -> None:
    m = NSECostModel(dp_order_value=100_000.0)
    assert m.sell_cost(0.0, 0.0) == pytest.approx(SELL_CHARGES + 15.34 / 100_000)
    assert m.buy_cost(0.0, 0.0) == pytest.approx(BUY_CHARGES)
    # small capital: flat DP bites harder (plan's minimum-capital argument)
    small = NSECostModel(dp_order_value=20_000.0)
    assert small.sell_cost(0.0, 0.0) > m.sell_cost(0.0, 0.0)


def test_spec_construction() -> None:
    cal = TradingCalendar([date(2024, 1, 1)])
    spec = nse_spec(cal, dp_order_value=50_000.0)
    assert spec.name == "NSE"
    assert spec.settlement_lag_days == 1
    assert spec.cost_model.sell_cost(0.0, 0.0) > spec.cost_model.buy_cost(0.0, 0.0) - 0.0002
