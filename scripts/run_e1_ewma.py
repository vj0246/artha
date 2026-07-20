"""E1: EWMA vs Ledoit-Wolf covariance for the production construction.

Usage:
    uv run --no-sync python scripts/run_e1_ewma.py

The one place daily "partial retraining" has a live target: the risk
model. Identical protocol to the construction study (minvar + tau 0.5,
momentum 12-1, full costs, Rs 25L, 2012-2026), covariance estimated
two ways. Gate: EWMA ships only on a clear net Sharpe or drawdown
improvement; otherwise the null publishes and LW stays.
"""

import json
import sys
from datetime import UTC, date, datetime

import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.models.ledger import Trial, TrialLedger
from artha.portfolio.construct import production_constructor

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= START)
    cal = TradingCalendar.from_frame(px)
    master = pl.read_parquet(settings.curated_dir / "security_master.parquet")
    sector_map = {
        r["canon_symbol"]: r["industry"] for r in master.iter_rows(named=True) if r["industry"]
    }
    signal = momentum_12_1(panel).filter(pl.col("trade_date") >= START)
    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")

    results: dict[str, object] = {}
    for name in ("lw", "ewma"):
        constructor = production_constructor(CAPITAL, sector_map)
        spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
        res = run_backtest(
            px, signal, spec, capital=CAPITAL, constructor=constructor, cov_estimator=name
        )
        stats = summarize(res.daily)
        ledger.append(
            Trial(
                model="e1_cov_estimator",
                label="momentum_12_1",
                feature_set=f"minvar_tau50_{name}",
                params={"cov_estimator": name},
                mean_ic=0.0,
                ic_t_stat=0.0,
                net_sharpe=stats["sharpe"],
                notes="E1 EWMA vs LW covariance study",
            )
        )
        results[name] = stats
        print(f"{name}: {json.dumps(stats)}")

    report = {"run_at": datetime.now(UTC).isoformat(), **results}
    out = settings.reports_dir / f"e1_ewma_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
