"""C7: momentum + low-vol blend under the production construction.

Usage:
    uv run --no-sync python scripts/run_c7_blend.py

The honest gap in the record: P2 measured low-vol at Sharpe 1.08 net —
above momentum's 0.96 — but production trades momentum only (P5 chose
it before construction v2 existed). Two configurations, one prior each,
under the identical protocol (production constructor, full costs,
Rs 25L, 2012-2026): pure low-vol, and a 50/50 cross-sectional
rank-blend. Momentum-only reference = the construction-v2 report's
minvar_tau50 row. Gate: a winner is flagged as the upgrade candidate
for the NEXT clock restart — no production change now (ADR 0010).
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
from artha.features.baselines import low_vol_63d, momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.models.ledger import Trial, TrialLedger
from artha.portfolio.construct import production_constructor

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0


def blend_signal(panel: pl.DataFrame) -> pl.DataFrame:
    """Mean of per-date cross-sectional ranks of momentum and low-vol."""
    mom = momentum_12_1(panel).rename({"score": "m"})
    lv = low_vol_63d(panel).rename({"score": "v"})
    j = mom.join(lv, on=["canon_symbol", "trade_date"], how="inner")
    return j.with_columns(
        ((pl.col("m").rank().over("trade_date") + pl.col("v").rank().over("trade_date")) / 2).alias(
            "score"
        )
    ).select("canon_symbol", "trade_date", "score")


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
    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")

    signals = {
        "lowvol_minvar_tau50": low_vol_63d(panel).filter(pl.col("trade_date") >= START),
        "blend50_minvar_tau50": blend_signal(panel).filter(pl.col("trade_date") >= START),
    }
    results: dict[str, object] = {}
    for name, signal in signals.items():
        constructor = production_constructor(CAPITAL, sector_map)
        spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
        res = run_backtest(px, signal, spec, capital=CAPITAL, constructor=constructor)
        stats = summarize(res.daily)
        ledger.append(
            Trial(
                model="c7_signal_blend",
                label="production_construction",
                feature_set=name,
                params={"blend": "rank_mean" if "blend" in name else "pure"},
                mean_ic=0.0,
                ic_t_stat=0.0,
                net_sharpe=stats["sharpe"],
                notes="C7 momentum+lowvol blend study",
            )
        )
        results[name] = stats
        print(f"{name}: {json.dumps(stats)}")

    report = {"run_at": datetime.now(UTC).isoformat(), **results}
    out = settings.reports_dir / f"c7_blend_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
