"""C4+C6: regime-conditional gross on top of vol targeting.

Usage:
    uv run --no-sync python scripts/run_regime_study.py

Tests the Daniel-Moskowitz momentum-crash mechanism on Indian data: does
an explicit bear/stress gate add net value BEYOND the vol targeting the
strategy already carries? C6 folds a crowding/liquidity input (universe
Amihud percentile) into the same gate rather than stacking overlays.

Regime inputs, all knowable at the rebalance close (PIT):
  bear    - synthetic TRI at or below its level 504 trading days ago
  stress  - 63d TRI vol above its trailing 756d 80th percentile
  illiq   - universe-median Amihud (21d mean) above its trailing 756d
            80th percentile

Configs (identical everything else, Rs 25L, bands, equal weight):
  baseline    - vol targeting only (the shipped P5 construction)
  dm_gate     - x0.5 when bear AND stress; x0.75 when either
  dm_illiq    - dm_gate, further x0.75 when illiq is stressed

Every config appends to the trial ledger; nulls are publishable.
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
from artha.portfolio.construct import Constructor

START = date(2012, 8, 1)
CAPITAL = 2_500_000.0
BEAR_LOOKBACK = 504
VOL_WINDOW = 63
PCT_WINDOW = 756
PCT_LEVEL = 0.80


def regime_frame(settings: object) -> pl.DataFrame:
    """(trade_date, bear, stress, illiq) - each boolean, PIT."""
    from artha.config import Settings

    assert isinstance(settings, Settings)
    n500 = pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty500.parquet").sort(
        "trade_date"
    )
    n500 = n500.with_columns(
        (pl.col("tr_index") <= pl.col("tr_index").shift(BEAR_LOOKBACK)).alias("bear"),
        pl.col("tr_return").rolling_std(window_size=VOL_WINDOW).alias("_vol"),
    ).with_columns(
        (
            pl.col("_vol") >= pl.col("_vol").rolling_quantile(PCT_LEVEL, window_size=PCT_WINDOW)
        ).alias("stress")
    )

    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    uni = pit_universe(panel).filter(pl.col("in_universe"))
    amihud = (
        uni.sort("canon_symbol", "trade_date")
        .with_columns(
            (
                (pl.col("adj_close") / pl.col("adj_close").shift(1).over("canon_symbol") - 1).abs()
                / (pl.col("traded_value") + 1.0)
            ).alias("_a")
        )
        .group_by("trade_date")
        .agg(pl.col("_a").median().alias("_amihud"))
        .sort("trade_date")
        .with_columns(pl.col("_amihud").rolling_mean(window_size=21).alias("_a21"))
        .with_columns(
            (
                pl.col("_a21") >= pl.col("_a21").rolling_quantile(PCT_LEVEL, window_size=PCT_WINDOW)
            ).alias("illiq")
        )
    )
    return (
        n500.select("trade_date", "bear", "stress")
        .join(amihud.select("trade_date", "illiq"), on="trade_date", how="left")
        .fill_null(False)
    )


def build_gate(regimes: pl.DataFrame, *, use_illiq: bool) -> dict[date, float]:
    gate: dict[date, float] = {}
    for r in regimes.iter_rows(named=True):
        g = 1.0
        if r["bear"] and r["stress"]:
            g = 0.5
        elif r["bear"] or r["stress"]:
            g = 0.75
        if use_illiq and r["illiq"]:
            g *= 0.75
        gate[r["trade_date"]] = g
    return gate


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
    regimes = regime_frame(settings)
    regime_days = int(regimes.filter(pl.col("bear") | pl.col("stress") | pl.col("illiq")).height)
    print(f"regime frame: {regimes.height} days, {regime_days} in any stressed state")

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    results: dict[str, object] = {}
    for name, gate in [
        ("baseline_voltarget", None),
        ("dm_gate", build_gate(regimes, use_illiq=False)),
        ("dm_illiq_gate", build_gate(regimes, use_illiq=True)),
    ]:
        constructor = Constructor(capital=CAPITAL, sector_map=sector_map)
        spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
        res = run_backtest(
            px, signal, spec, capital=CAPITAL, constructor=constructor, gross_gate=gate
        )
        stats = summarize(res.daily)
        stats["mar"] = stats["cagr"] / abs(stats["max_drawdown"]) if stats["max_drawdown"] else 0.0
        ledger.append(
            Trial(
                model="regime_gate",
                label="momentum_12_1",
                feature_set=name,
                params={"bear_lb": BEAR_LOOKBACK, "pct": PCT_LEVEL},
                mean_ic=0.0,
                ic_t_stat=0.0,
                net_sharpe=stats["sharpe"],
                notes="C4/C6 study (Daniel-Moskowitz gate + Amihud crowding)",
            )
        )
        results[name] = stats
        print(f"{name}: {json.dumps(stats)}")

    out = settings.reports_dir / f"regime_study_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps({"run_at": datetime.now(UTC).isoformat(), **results}, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
