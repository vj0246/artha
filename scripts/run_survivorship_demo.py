"""Survivorship before/after demonstration (plan v2 section 15 item 2).

Usage:
    uv run --no-sync python scripts/run_survivorship_demo.py

Same naive momentum 12-1 top-25 strategy, two universes:

- PIT: the honest survivorship-free liquidity universe (P1).
- BIASED: the same filters restricted to names still trading at the end of
  the panel - what a yfinance-style current-constituents dataset silently
  gives you. Delisted losers vanish from history.

The performance gap is the measured survivorship bias.
"""

import json
import sys
from datetime import UTC, date, datetime, timedelta
from typing import cast

import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.marketspec.nse import nse_spec

START = date(2012, 8, 1)


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel)
    px = universe.filter(pl.col("trade_date") >= START)
    cal = TradingCalendar.from_frame(px)
    spec = nse_spec(cal, dp_order_value=100_000.0)
    signal = momentum_12_1(panel).filter(pl.col("trade_date") >= START)

    last_day = cast(date, panel["trade_date"].max())
    survivors = set(
        panel.group_by("canon_symbol")
        .agg(pl.col("trade_date").max().alias("last"))
        .filter(pl.col("last") >= last_day - timedelta(days=30))["canon_symbol"]
        .to_list()
    )
    n_all = px["canon_symbol"].n_unique()
    biased_px = px.filter(pl.col("canon_symbol").is_in(sorted(survivors)))
    print(
        f"universe names: {n_all}; survivors at panel end: {biased_px['canon_symbol'].n_unique()}",
        flush=True,
    )

    results: dict[str, object] = {
        "n_universe_names": n_all,
        "n_survivors": biased_px["canon_symbol"].n_unique(),
    }
    for label, frame in (("pit", px), ("survivor_biased", biased_px)):
        res = run_backtest(frame, signal, spec, top_n=25, capital=2_500_000.0)
        results[label] = summarize(res.daily)
        print(f"{label}: {json.dumps(results[label])}", flush=True)

    pit = cast(dict[str, float], results["pit"])
    biased = cast(dict[str, float], results["survivor_biased"])
    results["bias_gap"] = {
        "cagr_pp": (biased["cagr"] - pit["cagr"]) * 100,
        "sharpe": biased["sharpe"] - pit["sharpe"],
    }
    print(f"bias gap: {json.dumps(results['bias_gap'])}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.reports_dir / f"survivorship_demo_{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
