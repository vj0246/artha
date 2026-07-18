"""B4 hedge study: constructed momentum with a NIFTY-futures beta hedge.

Usage:
    uv run --no-sync python scripts/run_hedge_study.py

Rebuilds the P5 constructed-momentum daily series, builds the front-month
NIFTY futures series from every F&O bhavcopy in the raw zone (2021+),
applies the rolling-beta hedge overlay, and reports hedged vs unhedged
over the overlap window. Gate: residual beta of the hedged series below
0.1 in absolute value.
"""

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import polars as pl

from artha.backtest.metrics import summarize
from artha.backtest.vectorized import run_backtest
from artha.config import load_settings
from artha.data.calendar import TradingCalendar
from artha.data.ingest.fo import FoParseError, front_month_series, parse_nifty_futures
from artha.data.universe import pit_universe
from artha.features.baselines import momentum_12_1
from artha.marketspec.nse import nse_spec
from artha.portfolio.construct import Constructor
from artha.portfolio.hedge import hedged_returns, rolling_beta

START = date(2012, 8, 1)  # strategy start; hedge window is the futures overlap
CAPITAL = 2_500_000.0
RESIDUAL_BETA_GATE = 0.1


def load_futures(raw_fo: Path) -> pl.DataFrame:
    frames = []
    skipped = 0
    for zip_path in sorted(raw_fo.rglob("*.zip")):
        d = _date_from_name(zip_path.name)
        try:
            frames.append(parse_nifty_futures(zip_path, d))
        except FoParseError:
            skipped += 1
    print(f"futures files parsed: {len(frames)}, skipped: {skipped}")
    return pl.concat(frames)


def _date_from_name(name: str) -> date:
    if name.startswith("BhavCopy_NSE_FO"):
        return datetime.strptime(name.split("_")[6], "%Y%m%d").date()
    return datetime.strptime(name[2:11].title(), "%d%b%Y").date()


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
    constructor = Constructor(capital=CAPITAL, sector_map=sector_map)
    spec = nse_spec(cal, dp_order_value=CAPITAL / constructor.top_n)
    res = run_backtest(px, signal, spec, capital=CAPITAL, constructor=constructor)
    strategy = res.daily.select("trade_date", "net_return")

    futures = load_futures(settings.raw_dir / "fo")
    front = front_month_series(futures)
    print(
        f"front-month series: {front.height} days "
        f"({front['trade_date'].min()} -> {front['trade_date'].max()})"
    )

    hedged = hedged_returns(strategy, front)
    window = strategy.filter(pl.col("trade_date").is_in(hedged["trade_date"].implode()))
    resid = rolling_beta(
        hedged.select("trade_date", pl.col("hedged_return").alias("net_return")), front
    )
    resid_beta = cast(float, resid["beta"].tail(resid.height // 2).mean())
    unhedged_stats = summarize(window)
    hedged_stats = summarize(
        hedged.select("trade_date", pl.col("hedged_return").alias("net_return"))
    )
    cost_drag_ann = cast(float, hedged["hedge_cost"].mean()) * 252

    gate_pass = abs(resid_beta) < RESIDUAL_BETA_GATE
    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "window": [str(hedged["trade_date"].min()), str(hedged["trade_date"].max())],
        "n_days": hedged.height,
        "unhedged": unhedged_stats,
        "hedged": hedged_stats,
        "mean_beta": cast(float, hedged["beta"].mean()),
        "residual_beta": resid_beta,
        "hedge_cost_drag_ann": cost_drag_ann,
        "gate_residual_beta_lt": RESIDUAL_BETA_GATE,
        "gate_pass": gate_pass,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = settings.reports_dir / f"hedge_study_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"report: {out}")
    print(
        f"GATE {'PASS' if gate_pass else 'FAIL'}: |residual beta| "
        f"{abs(resid_beta):.3f} vs {RESIDUAL_BETA_GATE}"
    )
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
