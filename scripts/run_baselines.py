"""Run baseline factor backtests on the full curated panel (P2 gate).

Usage:
    uv run python scripts/run_baselines.py [--start 2012-08-01] [--capital 2500000]

For each baseline (momentum 12-1, 5d reversal, 63d low-vol) plus the
equal-weight universe: net-of-cost performance at 1x costs, and a cost
sensitivity sweep (0x charges-only, 0.5x, 1x, 2x impact) for the momentum
strategy. Benchmark: NIFTY 500 price index from the index-close zone.
Writes a JSON report to the reports dir.
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.ingest.indices import parse_index_close
from artha.data.universe import pit_universe
from artha.features.baselines import BASELINES
from artha.marketspec.nse import nse_spec

TOP_N = 25


def equal_weight_signal(panel: pl.DataFrame, top_n: int) -> pl.DataFrame:
    """Uniform scores: the backtester's top-N tie-break yields a broad
    equal-weight book; with top_n >> N_universe it holds everything."""
    return panel.select("canon_symbol", "trade_date").with_columns(pl.lit(1.0).alias("score"))


def benchmark_returns(index_raw: Path, start: date) -> dict[str, float]:
    files = sorted(index_raw.rglob("ind_close_all_*.csv"))
    closes: list[tuple[date, float]] = []
    for f in files:
        d = datetime.strptime(f.name[14:22], "%d%m%Y").date()
        if d < start:
            continue
        df = parse_index_close(f.read_bytes(), d)
        row = df.filter(pl.col("index_name").is_in(["Nifty 500", "CNX 500", "S&P CNX 500"]))
        if row.height:
            closes.append((d, float(row["close"][0])))
    closes.sort()
    series = pl.DataFrame(
        {"trade_date": [c[0] for c in closes], "close": [c[1] for c in closes]}
    ).with_columns((pl.col("close") / pl.col("close").shift(1) - 1).alias("net_return"))
    return summarize(series.drop_nulls())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2012, 8, 1))
    parser.add_argument("--capital", type=float, default=2_500_000.0)  # Rs 25L
    args = parser.parse_args()

    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= args.start)
    cal = TradingCalendar.from_frame(px)

    dp_order = args.capital / TOP_N
    results: dict[str, object] = {}

    for name, factor in BASELINES.items():
        signal = factor(panel).filter(pl.col("trade_date") >= args.start)
        spec = nse_spec(cal, dp_order_value=dp_order)
        res = run_backtest(px, signal, spec, top_n=TOP_N, capital=args.capital)
        stats = summarize(res.daily)
        stats["gross_sharpe"] = summarize(res.daily, column="gross_return")["sharpe"]
        results[name] = stats
        print(f"{name}: {json.dumps(stats)}")

    ew = equal_weight_signal(px, 10_000)
    spec = nse_spec(cal, dp_order_value=dp_order)
    res = run_backtest(px, ew.filter(pl.col("trade_date") >= args.start), spec, top_n=10_000)
    results["equal_weight_universe"] = summarize(res.daily)
    print(f"equal_weight_universe: {json.dumps(results['equal_weight_universe'])}")

    # cost sensitivity on momentum
    sweep: dict[str, object] = {}
    mom = BASELINES["momentum_12_1"](panel).filter(pl.col("trade_date") >= args.start)
    for label, mult, cap in [
        ("charges_only", 1.0, 0.0),
        ("impact_0.5x", 0.5, args.capital),
        ("impact_1x", 1.0, args.capital),
        ("impact_2x", 2.0, args.capital),
    ]:
        spec = nse_spec(cal, dp_order_value=dp_order, impact_multiplier=mult)
        res = run_backtest(px, mom, spec, top_n=TOP_N, capital=cap)
        sweep[label] = summarize(res.daily)
        print(f"momentum {label}: {json.dumps(sweep[label])}")
    results["cost_sensitivity_momentum"] = sweep

    bench = benchmark_returns(settings.raw_dir / "indexclose", args.start)
    if bench:
        results["benchmark_nifty500_price"] = bench
        print(f"benchmark: {json.dumps(bench)}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.reports_dir / f"baselines_{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
