"""C2+C3 construction v2 study: risk-model weights and trading speed.

Usage:
    uv run --no-sync python scripts/run_construction_v2.py

Eight configurations under the identical protocol (selection, costs,
caps, vol targeting, T+1-close execution, Rs 25L):

  weighting scheme x trading rule
  - equal / ivol / minvar  (C2: Ledoit-Wolf risk model)
  - bands (baseline) / partial adjustment tau in {0.25, 0.5, 0.75} (C3)

Every configuration is appended to the trial ledger. Daily net series
are saved to reports/construction_v2_daily.parquet for the C1 SPA test.
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
from artha.portfolio.construct import ConstraintReport, Constructor

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0

CONFIGS: list[tuple[str, str, float | None]] = [
    ("equal_bands", "equal", None),  # shipped P5 baseline
    ("ivol_bands", "ivol", None),
    ("minvar_bands", "minvar", None),
    ("equal_tau25", "equal", 0.25),
    ("equal_tau50", "equal", 0.50),
    ("equal_tau75", "equal", 0.75),
    ("ivol_tau50", "ivol", 0.50),
    ("minvar_tau50", "minvar", 0.50),
]


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
    daily_frames: list[pl.DataFrame] = []
    for name, scheme, tau in CONFIGS:
        constructor = Constructor(
            capital=CAPITAL, sector_map=sector_map, scheme=scheme, trade_speed=tau
        )
        spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
        report = ConstraintReport()
        res = run_backtest(
            px, signal, spec, capital=CAPITAL, constructor=constructor, report=report
        )
        stats = summarize(res.daily)
        ledger.append(
            Trial(
                model="construction_v2",
                label="momentum_12_1",
                feature_set=name,
                params={"scheme": scheme, "trade_speed": tau},
                mean_ic=0.0,
                ic_t_stat=0.0,
                net_sharpe=stats["sharpe"],
                notes="C2/C3 study (LW risk model, GP partial adjustment)",
            )
        )
        results[name] = {**stats, "constraint_violations": len(report.violations)}
        daily_frames.append(
            res.daily.select("trade_date", "net_return").with_columns(pl.lit(name).alias("config"))
        )
        print(f"{name}: {json.dumps(results[name])}")

    pl.concat(daily_frames).write_parquet(settings.reports_dir / "construction_v2_daily.parquet")
    out = settings.reports_dir / (f"construction_v2_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json")
    out.write_text(json.dumps({"run_at": datetime.now(UTC).isoformat(), **results}, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
