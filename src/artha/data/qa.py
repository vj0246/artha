"""Data QA on the adjusted equity panel (plan section 5.4).

Structural checks are hard errors and block downstream builds. Statistical
checks produce warning frames for eyeball review; they flag but do not block,
because legitimate market events (circuit-to-circuit moves, thin special
sessions) would otherwise halt every backfill.
"""

from dataclasses import dataclass, field
from typing import Final

import polars as pl

# |1-day adjusted return| above this is flagged: normal price bands are
# 5/10/20%, so anything here is either a mis-adjusted CA or a genuine shock.
RETURN_OUTLIER_THRESHOLD: Final = 0.30

# A trading day whose row count is below this fraction of the yearly median
# suggests a truncated file rather than a thin session.
THIN_DATE_FRACTION: Final = 0.5

_EPS: Final = 1e-6


@dataclass
class QaReport:
    """errors: structural violations (check -> offending row count).
    warnings: named frames of suspicious rows for review."""

    errors: dict[str, int] = field(default_factory=dict)
    warnings: dict[str, pl.DataFrame] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": {k: v.height for k, v in self.warnings.items()},
        }


def run_qa(panel: pl.DataFrame) -> QaReport:
    """Panel must carry canon_symbol, trade_date, OHLC, volume, adj_close."""
    report = QaReport()

    checks = {
        "nonpositive_price": (
            pl.any_horizontal(pl.col(c) <= 0 for c in ("open", "high", "low", "close"))
        ),
        "high_below_low": pl.col("high") < pl.col("low") - _EPS,
        "close_outside_range": (pl.col("close") > pl.col("high") + _EPS)
        | (pl.col("close") < pl.col("low") - _EPS),
        "negative_volume": pl.col("volume") < 0,
    }
    for name, cond in checks.items():
        n = panel.filter(cond).height
        if n:
            report.errors[name] = n

    n_dup = panel.height - panel.select("canon_symbol", "trade_date").unique().height
    if n_dup:
        report.errors["duplicate_symbol_date"] = n_dup

    outliers = (
        panel.sort("canon_symbol", "trade_date")
        .with_columns(
            (pl.col("adj_close") / pl.col("adj_close").shift(1).over("canon_symbol") - 1).alias(
                "adj_return"
            )
        )
        .filter(pl.col("adj_return").abs() > RETURN_OUTLIER_THRESHOLD)
        .select("canon_symbol", "trade_date", "adj_return", "close", "prev_close")
        .sort("adj_return")
    )
    if outliers.height:
        report.warnings["return_outliers"] = outliers

    by_date = panel.group_by("trade_date").len().sort("trade_date")
    thin = (
        by_date.with_columns(pl.col("trade_date").dt.year().alias("year"))
        .with_columns(pl.col("len").median().over("year").alias("year_median"))
        .filter(pl.col("len") < THIN_DATE_FRACTION * pl.col("year_median"))
        .drop("year")
    )
    if thin.height:
        report.warnings["thin_dates"] = thin

    return report
