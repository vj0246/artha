"""D1: lock the Track D single ticker by composite screen (plan TRACK_D).

Usage:
    uv run --no-sync python scripts/run_ticker_selection.py

Criteria over the liquid universe (top decile by 21d median traded
value, full-history names): history completeness 2010->today, liquidity
rank, volatility inside the 25th-75th percentile band, zero CA
sanity-gate rejections, no structural break. Shortlist RELIANCE /
ICICIBANK; scores within 5% break toward ICICIBANK (VJ's lean).
"""

import json
import sys
from datetime import UTC, date, datetime
from typing import cast

import polars as pl

from artha.config import load_settings
from artha.data.universe import pit_universe

SHORTLIST = ["RELIANCE", "ICICIBANK"]
EXCLUDED = {"HDFCBANK"}  # 2023 merger: structural break
HISTORY_START = date(2010, 1, 4)
MAX_GAP_SESSIONS = 10


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    uni = pit_universe(panel)
    sessions = sorted(uni["trade_date"].unique().to_list())
    n_sessions = len(sessions)

    per_name = (
        uni.sort("canon_symbol", "trade_date")
        .with_columns(
            (pl.col("adj_close") / pl.col("adj_close").shift(1) - 1)
            .over("canon_symbol")
            .alias("ret")
        )
        .group_by("canon_symbol")
        .agg(
            pl.col("trade_date").min().alias("first"),
            pl.col("trade_date").max().alias("last"),
            pl.len().alias("n_days"),
            pl.col("traded_value").tail(21).median().alias("adv_now"),
            (pl.col("ret").std() * (252**0.5)).alias("vol_ann"),
        )
        .filter(
            (pl.col("first") <= HISTORY_START)
            & (pl.col("last") == sessions[-1])
            & (pl.col("n_days") >= n_sessions - 252)  # allow scattered halts
            & ~pl.col("canon_symbol").is_in(sorted(EXCLUDED))
        )
    )
    liquid = per_name.filter(pl.col("adv_now") >= per_name["adv_now"].quantile(0.9)).with_columns(
        pl.col("adv_now").rank(descending=True).alias("liq_rank"),
    )
    v25, v75 = (
        cast(float, liquid["vol_ann"].quantile(0.25)),
        cast(float, liquid["vol_ann"].quantile(0.75)),
    )
    v_med = cast(float, liquid["vol_ann"].median())
    scored = liquid.with_columns(
        ((pl.col("vol_ann") >= v25) & (pl.col("vol_ann") <= v75)).alias("vol_in_band"),
        (1.0 - (pl.col("vol_ann") - v_med).abs() / (v75 - v25)).alias("vol_score"),
        (1.0 - (pl.col("liq_rank") - 1) / pl.len()).alias("liq_score"),
        ((pl.col("n_days")) / n_sessions).alias("history_score"),
    ).with_columns(
        (
            0.4 * pl.col("liq_score")
            + 0.4 * pl.col("vol_score").clip(0.0, 1.0)
            + 0.2 * pl.col("history_score")
        ).alias("composite")
    )

    table = scored.sort("composite", descending=True).select(
        "canon_symbol", "composite", "adv_now", "vol_ann", "vol_in_band", "n_days"
    )
    print(table.head(15))

    short = table.filter(pl.col("canon_symbol").is_in(SHORTLIST))
    if short.height < len(SHORTLIST):
        print("shortlist name missing from screen!", file=sys.stderr)
        return 1
    row = {r["canon_symbol"]: r for r in short.iter_rows(named=True)}
    rel, ici = row["RELIANCE"], row["ICICIBANK"]
    if abs(rel["composite"] - ici["composite"]) / max(rel["composite"], ici["composite"]) <= 0.05:
        winner, why = "ICICIBANK", "scores within 5% - tiebreak to VJ's lean"
    else:
        winner = max(row, key=lambda k: row[k]["composite"])
        why = "clear composite winner"

    report = {
        "run_at": datetime.now(UTC).isoformat(),
        "winner": winner,
        "why": why,
        "shortlist": {k: {kk: str(vv) for kk, vv in v.items()} for k, v in row.items()},
        "vol_band": [v25, v75],
        "screen_top15": table.head(15).with_columns(pl.col("adv_now").round(0)).to_dicts(),
    }
    out = settings.reports_dir / f"ticker_selection_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nLOCKED TICKER: {winner} ({why})")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
