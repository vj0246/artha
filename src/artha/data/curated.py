"""Curated zone: raw bhavcopy zips -> one Parquet per year.

Curated files are derived and rebuildable (unlike the raw zone, they may be
overwritten by a rebuild). Any single unreadable raw file aborts the build
loudly: silent gaps are how survivorship bias sneaks in.
"""

from pathlib import Path

import polars as pl

from artha.data.ingest.bhavcopy import bhavcopy_date_from_filename, read_bhavcopy_zip


def build_curated_bhavcopy(
    raw_root: Path, curated_root: Path, *, years: list[int] | None = None
) -> pl.DataFrame:
    """Parse every raw bhavcopy zip into curated/bhavcopy/{year}.parquet.

    Returns a summary frame (year, files, rows).
    """
    src = raw_root / "bhavcopy"
    year_dirs = sorted(p for p in src.iterdir() if p.is_dir())
    if years is not None:
        year_dirs = [p for p in year_dirs if int(p.name) in years]
    out_dir = curated_root / "bhavcopy"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, int]] = []
    for year_dir in year_dirs:
        frames = [
            read_bhavcopy_zip(zp, trade_date=bhavcopy_date_from_filename(zp.name))
            for zp in sorted(year_dir.glob("*.zip"))
        ]
        if not frames:
            continue
        year_df = pl.concat(frames).sort("trade_date", "symbol", "series")
        year_df.write_parquet(out_dir / f"{year_dir.name}.parquet")
        summary.append({"year": int(year_dir.name), "files": len(frames), "rows": year_df.height})
    return pl.DataFrame(summary, schema={"year": pl.Int64, "files": pl.Int64, "rows": pl.Int64})


def load_curated_bhavcopy(curated_root: Path) -> pl.LazyFrame:
    return pl.scan_parquet(curated_root / "bhavcopy" / "*.parquet")
