"""Post-tax lens: what the strategy earns after Indian capital-gains tax.

Usage:
    uv run --no-sync python scripts/run_posttax.py

Nobody models this and everybody pays it. At ~4x one-way annual
turnover the average holding period is ~3 months, so effectively all
realized gains are short-term. Model (disclosed approximation):

- each financial year's positive net strategy P&L is taxed at the STCG
  rate 20% + 4% cess = 20.8% (FY2025 slab for equity delivery held
  < 12 months);
- losses carry forward and offset future gains (8-year limit ignored —
  never binds here);
- dividends ignored (the panel uses price returns; synthetic-TRI
  benchmark comparisons are unaffected in relative terms).

Input: the production configuration's daily net returns, regenerated
under the standard protocol. Output: pre-tax vs post-tax CAGR/Sharpe
and the effective tax drag.
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
from artha.portfolio.construct import production_constructor

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0
STCG = 0.208  # 20% + 4% cess


def fiscal_year(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


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
    constructor = production_constructor(CAPITAL, sector_map)
    spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
    signal = momentum_12_1(panel).filter(pl.col("trade_date") >= START)
    res = run_backtest(px, signal, spec, capital=CAPITAL, constructor=constructor)
    daily = res.daily.with_columns(
        pl.col("trade_date").map_elements(fiscal_year, return_dtype=pl.Int32).alias("fy")
    )

    pre = summarize(res.daily)

    # walk the equity year by year, taxing each FY's positive net P&L
    equity = 1.0
    carried_loss = 0.0
    post_returns: list[float] = []
    for (_fy,), frame in sorted(daily.partition_by("fy", as_dict=True).items()):
        start_eq = equity
        for r in frame["net_return"]:
            equity *= 1 + r
            post_returns.append(r)
        pnl = equity - start_eq
        taxable = pnl - carried_loss if pnl > 0 else 0.0
        if pnl > 0 and taxable > 0:
            tax = taxable * STCG
            # tax paid out of the account at FY end: scale equity down and
            # record it as a year-end return adjustment
            post_returns[-1] = (1 + post_returns[-1]) * (1 - tax / equity) - 1
            equity -= tax
            carried_loss = 0.0
        elif pnl > 0:
            carried_loss -= pnl  # gains absorbed by carried loss
        else:
            carried_loss += -pnl

    post = summarize(
        res.daily.with_columns(pl.Series("net_return", post_returns)).select(
            "trade_date", "gross_return", "cost", "net_return", "turnover"
        )
    )
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "assumptions": "all gains STCG 20.8%, FY netting, loss carryforward, price returns only",
        "pre_tax": pre,
        "post_tax": post,
        "cagr_drag_pp": round((pre["cagr"] - post["cagr"]) * 100, 2),
        "sharpe_drag": round(pre["sharpe"] - post["sharpe"], 3),
        "effective_tax_on_cagr": round(1 - post["cagr"] / pre["cagr"], 3)
        if pre["cagr"] > 0
        else None,
    }
    out = settings.reports_dir / f"posttax_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps({k: v for k, v in report.items() if k not in ("pre_tax", "post_tax")}, indent=2)
    )
    print(f"pre  : {json.dumps(pre)}")
    print(f"post : {json.dumps(post)}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
