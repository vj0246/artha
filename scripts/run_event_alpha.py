"""P4 event-alpha study: classify corpus, CARs per category, PEAD.

Usage:
    uv run --no-sync python scripts/run_event_alpha.py

Steps: classify the announcements corpus (rule-based v0), canonicalize
symbols, stamp knowable dates, restrict to in-universe names; compute
market-model abnormal returns vs the synthetic NIFTY 50 TR; CARs with
significance per category and window; PEAD by day-0 abnormal-return
quintile for earnings events. Writes curated/events/classified.parquet, a
stratified 300-subject taxonomy audit sample, and a JSON report.
"""

import json
import sys
from datetime import UTC, datetime

import polars as pl

from artha.config import load_settings
from artha.data.adjust import canonicalize_symbols
from artha.data.calendar import TradingCalendar
from artha.data.ingest.symbolchange import parse_symbolchange
from artha.data.universe import pit_universe
from artha.events.event_study import (
    car_significance,
    cumulative_abnormal_returns,
    market_model_abnormal,
)
from artha.events.features import knowable_dates
from artha.events.taxonomy import classify_frame

WINDOWS = [(0, 1), (0, 5), (2, 20), (2, 60)]
MIN_EVENTS = 30


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    universe = pit_universe(panel).filter(pl.col("in_universe"))
    cal = TradingCalendar.from_frame(panel)
    market = pl.read_parquet(settings.curated_dir / "benchmarks" / "nifty50.parquet")

    ann = pl.read_parquet(settings.curated_dir / "events" / "announcements.parquet")
    snapshot = sorted((settings.raw_dir / "symbolchange").glob("symbolchange_*.csv"))[-1]
    changes = parse_symbolchange(snapshot.read_bytes())

    events = classify_frame(ann)
    events = knowable_dates(events, cal, "announced_at")
    events = canonicalize_symbols(
        events.rename({"symbol": "canon_symbol"}), changes, date_col="knowable_date"
    )
    # one event per (name, day, category); in-universe names only
    events = events.unique(subset=["canon_symbol", "knowable_date", "category"]).join(
        universe.select("canon_symbol", pl.col("trade_date").alias("knowable_date")),
        on=["canon_symbol", "knowable_date"],
        how="semi",
    )
    out_dir = settings.curated_dir / "events"
    events.select(
        "canon_symbol", "knowable_date", "category", "direction", "materiality", "subject"
    ).write_parquet(out_dir / "classified.parquet")
    by_cat = dict(events.group_by("category").len().sort("len", descending=True).iter_rows())
    print(f"classified in-universe events: {events.height:,} {json.dumps(by_cat)}", flush=True)

    # taxonomy audit sample: up to ~27 per category, 300 total
    sample = (
        events.filter(pl.col("subject").is_not_null())
        .with_columns(pl.col("subject").str.slice(0, 200))
        .group_by("category", maintain_order=True)
        .head(27)
        .head(300)
        .select("category", "direction", "materiality", "subject")
    )
    sample.write_csv(settings.reports_dir / "taxonomy_audit_sample.csv")

    print("computing abnormal returns...", flush=True)
    abnormal = market_model_abnormal(
        universe.select("canon_symbol", "trade_date", "adj_close"), market
    )

    results: dict[str, object] = {"corpus": {"events": events.height, "by_category": by_cat}}
    car_table: dict[str, dict[str, object]] = {}
    for category in by_cat:
        ev_c = events.filter(
            (pl.col("category") == category) & (pl.col("materiality") >= 1)
        ).select("canon_symbol", pl.col("knowable_date").alias("event_date"))
        if category == "other" or ev_c.height < MIN_EVENTS:
            continue
        row: dict[str, object] = {"n": ev_c.height}
        for window in WINDOWS:
            cars = cumulative_abnormal_returns(abnormal, ev_c, window=window)
            if cars.height < MIN_EVENTS:
                continue
            stats = car_significance(cars)
            row[f"car_{window[0]}_{window[1]}"] = {
                "mean_bps": round(stats.mean_car * 10_000, 1),
                "t": round(stats.t_stat, 2),
                "p_boot": round(stats.bootstrap_p, 4),
                "n": stats.n_events,
            }
        car_table[category] = row
        print(f"{category}: {json.dumps(row)}", flush=True)
    results["car_by_category"] = car_table

    # PEAD: earnings events bucketed by day-0 abnormal return (surprise proxy)
    earn = events.filter(pl.col("category") == "earnings_result").select(
        "canon_symbol", pl.col("knowable_date").alias("event_date")
    )
    day0 = cumulative_abnormal_returns(abnormal, earn, window=(0, 0)).rename({"car": "ar0"})
    drift = cumulative_abnormal_returns(abnormal, earn, window=(2, 60))
    pead = day0.join(drift, on=["canon_symbol", "event_date"], how="inner").with_columns(
        (pl.col("ar0").rank("ordinal") * 5 // (pl.len() + 1)).alias("q")
    )
    pead_table = {}
    for q in range(5):
        sub = pead.filter(pl.col("q") == q)
        if sub.height >= MIN_EVENTS:
            stats = car_significance(sub.select(pl.col("car")))
            pead_table[f"q{q + 1}"] = {
                "n": stats.n_events,
                "mean_ar0_bps": round(float(sub["ar0"].mean() or 0) * 10_000, 1),
                "drift_2_60_bps": round(stats.mean_car * 10_000, 1),
                "t": round(stats.t_stat, 2),
            }
    results["pead_earnings"] = pead_table
    print(f"PEAD: {json.dumps(pead_table)}", flush=True)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = settings.reports_dir / f"event_alpha_{stamp}.json"
    path.write_text(json.dumps(results, indent=2))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
