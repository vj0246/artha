"""Build benchmark parquets (price + synthetic TRI) from the index-close zone.

Usage:
    uv run python scripts/build_benchmarks.py

Writes curated/benchmarks/{nifty500,nifty50}.parquet with columns
trade_date, close, div_yield, pr_return, tr_return, tr_index. The TR series
is SYNTHETIC (PR + trailing yield / 252); label it as such in any report.
"""

import sys

from artha.config import load_settings
from artha.data.benchmark import INDEX_ALIASES, load_index_series, synthetic_total_return


def main() -> int:
    settings = load_settings()
    out_dir = settings.curated_dir / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, aliases in INDEX_ALIASES.items():
        series = synthetic_total_return(load_index_series(settings.raw_dir / "indexclose", aliases))
        series.write_parquet(out_dir / f"{name}.parquet")
        yrs = (series["trade_date"].max() - series["trade_date"].min()).days / 365.25  # type: ignore[operator]
        pr_cagr = (series["close"][-1] / series["close"][0]) ** (1 / yrs) - 1
        tr_cagr = (series["tr_index"][-1] / 1000.0) ** (1 / yrs) - 1
        print(
            f"{name}: {series.height} days {series['trade_date'].min()} -> "
            f"{series['trade_date'].max()}  PR CAGR {pr_cagr:.2%}  synthetic TR CAGR {tr_cagr:.2%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
