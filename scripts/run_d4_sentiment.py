"""D4: does news/announcement sentiment add value on the locked name?

Usage (after backfill_gdelt.py completes):
    uv run --no-sync python scripts/run_d4_sentiment.py

Two sentiment sources for ICICIBANK, each turned into a daily index
(mean VADER compound + article count) with the knowability rule
applied (news seen after 15:30 IST belongs to the next session):

1. GDELT archive (2017+) — broad web news, exploratory fidelity;
2. exchange announcements (2010+) — subject-line VADER on the
   official corpus, the high-fidelity arm.

Tests, per source: IC of the trailing sentiment index vs next-day and
next-5-day returns; a sentiment-gated strategy (long when trailing 5d
sentiment > trailing 1y median, else flat) vs the always-long floor,
net of full NSE costs. Every configuration appends to the trial
ledger. Expectation recorded in TRACK_D_PLAN: incremental value is
expected small; the announcement corpus is the fair test.
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any

import numpy as np
import polars as pl
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from artha.config import load_settings
from artha.marketspec.nse import NSECostModel
from artha.models.ledger import Trial, TrialLedger

TICKER = "ICICIBANK"
CAPITAL = 500_000.0
CUTOFF_HOUR_IST = 15.5


def daily_index_from_gdelt(settings: Any) -> pl.DataFrame:
    path = settings.curated_dir / "gdelt_articles.jsonl"
    if not path.exists():
        return pl.DataFrame(schema={"date": pl.Date, "sentiment": pl.Float64, "n": pl.UInt32})
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    df = pl.DataFrame(rows).filter(pl.col("seen_date").is_not_null())
    # seendate format: YYYYMMDDTHHMMSSZ (UTC). IST = UTC + 5:30; knowability:
    # after 15:30 IST -> next day
    df = (
        df.with_columns(
            pl.col("seen_date").str.strptime(pl.Datetime, "%Y%m%dT%H%M%SZ").alias("_ts")
        )
        .with_columns((pl.col("_ts") + pl.duration(hours=5, minutes=30)).alias("_ist"))
        .with_columns(
            pl.when(pl.col("_ist").dt.hour() + pl.col("_ist").dt.minute() / 60 >= CUTOFF_HOUR_IST)
            .then(pl.col("_ist").dt.date() + pl.duration(days=1))
            .otherwise(pl.col("_ist").dt.date())
            .cast(pl.Date)
            .alias("date")
        )
    )
    return df.group_by("date").agg(pl.col("sentiment").mean(), pl.len().alias("n")).sort("date")


def daily_index_from_announcements(settings: Any) -> pl.DataFrame:
    ann = (
        pl.scan_parquet(settings.curated_dir / "events" / "**/*.parquet")
        .filter(pl.col("symbol") == TICKER)
        .select("subject", "announced_at")
        .collect()
    )
    if ann.is_empty():
        return pl.DataFrame(schema={"date": pl.Date, "sentiment": pl.Float64, "n": pl.UInt32})
    analyzer = SentimentIntensityAnalyzer()
    scored = ann.with_columns(
        pl.col("subject")
        .map_elements(
            lambda s: analyzer.polarity_scores(s or "")["compound"], return_dtype=pl.Float64
        )
        .alias("sentiment")
    ).with_columns(
        pl.when(
            pl.col("announced_at").dt.hour() + pl.col("announced_at").dt.minute() / 60
            >= CUTOFF_HOUR_IST
        )
        .then(pl.col("announced_at").dt.date() + pl.duration(days=1))
        .otherwise(pl.col("announced_at").dt.date())
        .cast(pl.Date)
        .alias("date")
    )
    return scored.group_by("date").agg(pl.col("sentiment").mean(), pl.len().alias("n")).sort("date")


def evaluate_source(
    name: str, index: pl.DataFrame, px: pl.DataFrame, cost_per_switch: float
) -> dict[str, Any]:
    if index.is_empty():
        return {"status": "no data"}
    j = (
        px.join(index, left_on="trade_date", right_on="date", how="left")
        .sort("trade_date")
        .with_columns(
            pl.col("sentiment").fill_null(0.0).rolling_mean(window_size=5).alias("sent_5d")
        )
        .with_columns(
            pl.col("sent_5d").rolling_quantile(0.5, window_size=252).alias("sent_med"),
            pl.col("ret").shift(-1).alias("fwd1"),
            (pl.col("adj_close").shift(-5) / pl.col("adj_close") - 1).alias("fwd5"),
        )
        .drop_nulls(["sent_5d", "sent_med", "fwd1"])
    )
    if j.height < 500:
        return {"status": f"only {j.height} usable days"}
    ic1 = float(np.corrcoef(j["sent_5d"], j["fwd1"])[0, 1])
    j5 = j.drop_nulls("fwd5")
    ic5 = float(np.corrcoef(j5["sent_5d"], j5["fwd5"])[0, 1])
    pos = (j["sent_5d"] > j["sent_med"]).cast(pl.Float64).to_numpy()
    y = j["fwd1"].to_numpy()
    switches = np.abs(np.diff(pos, prepend=0.0))
    strat = pos * y - switches * cost_per_switch
    always = y - np.where(np.arange(len(y)) == 0, cost_per_switch, 0.0)

    def sharpe(x: np.ndarray) -> float:
        sd = x.std(ddof=1)
        return float(x.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0

    return {
        "n_days": int(j.height),
        "coverage_days": int(index.height),
        "ic_next_day": ic1,
        "ic_next_5d": ic5,
        "gated_sharpe": sharpe(strat),
        "always_long_sharpe": sharpe(always),
        "gated_minus_always": sharpe(strat) - sharpe(always),
        "time_in_market": float(pos.mean()),
    }


def main() -> int:
    settings = load_settings()
    panel = pl.read_parquet(settings.curated_dir / "panel.parquet")
    px = (
        panel.filter(pl.col("canon_symbol") == TICKER)
        .sort("trade_date")
        .with_columns((pl.col("adj_close") / pl.col("adj_close").shift(1) - 1).alias("ret"))
        .select("trade_date", "adj_close", "ret")
    )
    m = NSECostModel(dp_order_value=CAPITAL)
    adv = float(panel.filter(pl.col("canon_symbol") == TICKER)["traded_value"].tail(252).median())
    cost_per_switch = m.sell_cost(CAPITAL, adv) + m.buy_cost(CAPITAL, adv)

    ledger = TrialLedger(settings.reports_dir / "ledger.jsonl")
    results: dict[str, Any] = {}
    for name, index in [
        ("gdelt", daily_index_from_gdelt(settings)),
        ("announcements", daily_index_from_announcements(settings)),
    ]:
        stats = evaluate_source(name, index, px, cost_per_switch)
        results[name] = stats
        if "gated_sharpe" in stats:
            ledger.append(
                Trial(
                    model="d4_sentiment_gate",
                    label=f"{TICKER}_next_day",
                    feature_set=f"{name}_vader_5d",
                    params={"gate": "sent_5d > 1y median"},
                    mean_ic=stats["ic_next_day"],
                    ic_t_stat=stats["ic_next_day"] * float(np.sqrt(stats["n_days"])),
                    net_sharpe=stats["gated_sharpe"],
                    notes="D4 sentiment study",
                )
            )
        print(f"{name}: {json.dumps(stats)}")

    report = {"run_at": datetime.now(UTC).isoformat(), "ticker": TICKER, **results}
    out = settings.reports_dir / f"d4_sentiment_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
