"""Curated zone: raw bhavcopy zips -> one Parquet per year.

Curated files are derived and rebuildable (unlike the raw zone, they may be
overwritten by a rebuild). Any single unreadable raw file aborts the build
loudly: silent gaps are how survivorship bias sneaks in.
"""

from pathlib import Path

import polars as pl

from artha.data.ingest.bhavcopy import bhavcopy_date_from_filename, read_bhavcopy_zip


def _year_is_current(year_dir: Path, parquet: Path) -> bool:
    """True when the year's parquet already covers every raw zip in the dir.

    Cheap filename-level check: the parquet is current iff it exists and the
    set of trade dates it was built from (recorded row count is not enough -
    a re-downloaded day replaces content) matches by newest date and count.
    We compare max raw date and file count against parquet metadata columns.
    """
    if not parquet.exists():
        return False
    zips = list(year_dir.glob("*.zip"))
    if not zips:
        return True
    newest_raw = max(bhavcopy_date_from_filename(z.name) for z in zips)
    stats = (
        pl.scan_parquet(parquet)
        .select(
            pl.col("trade_date").max().alias("max_d"),
            pl.col("trade_date").n_unique().alias("n_days"),
        )
        .collect()
    )
    return bool(stats["max_d"][0] == newest_raw and stats["n_days"][0] == len(zips))


def build_curated_bhavcopy(
    raw_root: Path,
    curated_root: Path,
    *,
    years: list[int] | None = None,
    incremental: bool = False,
) -> pl.DataFrame:
    """Parse raw bhavcopy zips into curated/bhavcopy/{year}.parquet.

    ``incremental=True`` skips years whose parquet already covers every raw
    file (max date and session count match), so a daily run re-parses only
    the current year. Returns a summary frame (year, files, rows).
    """
    src = raw_root / "bhavcopy"
    year_dirs = sorted(p for p in src.iterdir() if p.is_dir())
    if years is not None:
        year_dirs = [p for p in year_dirs if int(p.name) in years]
    out_dir = curated_root / "bhavcopy"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, int]] = []
    for year_dir in year_dirs:
        parquet = out_dir / f"{year_dir.name}.parquet"
        if incremental and _year_is_current(year_dir, parquet):
            continue
        frames = [
            read_bhavcopy_zip(zp, trade_date=bhavcopy_date_from_filename(zp.name))
            for zp in sorted(year_dir.glob("*.zip"))
        ]
        if not frames:
            continue
        year_df = pl.concat(frames).sort("trade_date", "symbol", "series")
        year_df.write_parquet(parquet)
        summary.append({"year": int(year_dir.name), "files": len(frames), "rows": year_df.height})
    return pl.DataFrame(summary, schema={"year": pl.Int64, "files": pl.Int64, "rows": pl.Int64})


def load_curated_bhavcopy(curated_root: Path) -> pl.LazyFrame:
    return pl.scan_parquet(curated_root / "bhavcopy" / "*.parquet")
