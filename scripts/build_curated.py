"""Build the curated zone from the raw zone.

Usage:
    uv run python scripts/build_curated.py [--years 2010 2011 ...]

Steps: raw bhavcopy zips -> per-year Parquet; symbolchange snapshot (newest
in raw zone, downloaded if absent) -> equity panel with canonical symbols ->
declared CA factor events (ADR 0005) -> adjusted panel -> QA. Outputs under
$ARTHA_DATA_DIR/curated: bhavcopy/{year}.parquet, panel.parquet,
ca_events.parquet. QA report JSON goes to the reports dir; structural QA
errors exit 1 so downstream builds do not run.
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from artha.config import load_settings
from artha.data.adjust import (
    adjustment_events,
    apply_adjustment,
    canonicalize_symbols,
    combine_events,
    equity_panel,
    gap_factor_events,
)
from artha.data.curated import build_curated_bhavcopy, load_curated_bhavcopy
from artha.data.ingest.ca_api import (
    declared_factor_events,
    declared_gap_events,
    parse_ca_records,
)
from artha.data.ingest.indices import parse_nifty500_list
from artha.data.ingest.nse_http import nse_client
from artha.data.ingest.symbolchange import download_symbolchange, parse_symbolchange
from artha.data.master import build_security_master
from artha.data.qa import run_qa
from artha.data.store import RawStore


def load_declared_ca(raw_dir: Path) -> pl.DataFrame:
    """Concatenate all monthly CA API files from the raw zone."""
    files = sorted(raw_dir.glob("ca_api/*/ca_*.json"))
    if not files:
        raise FileNotFoundError(f"no CA API files under {raw_dir / 'ca_api'}; run backfill_ca.py")
    return pl.concat([parse_ca_records(f.read_bytes()) for f in files])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="*", default=None)
    args = parser.parse_args()

    settings = load_settings()
    store = RawStore(settings.raw_dir)

    summary = build_curated_bhavcopy(settings.raw_dir, settings.curated_dir, years=args.years)
    print(summary)

    snapshots = sorted((settings.raw_dir / "symbolchange").glob("symbolchange_*.csv"))
    if snapshots:
        snapshot = snapshots[-1]
    else:
        with nse_client() as client:
            snapshot = download_symbolchange(date.today(), client=client, store=store)
        print(f"downloaded symbolchange snapshot: {snapshot}")
    changes = parse_symbolchange(snapshot.read_bytes())
    print(f"symbol changes: {changes.height}")

    bhav = load_curated_bhavcopy(settings.curated_dir).collect()
    panel = equity_panel(bhav, changes)
    ca = load_declared_ca(settings.raw_dir)
    parsed = adjustment_events(declared_factor_events(ca), changes)
    gap_dates = (
        canonicalize_symbols(
            declared_gap_events(ca).rename({"symbol": "canon_symbol"}), changes, date_col="ex_date"
        )
        .select("canon_symbol", "ex_date")
        .unique()
    )
    gaps = gap_factor_events(panel, gap_dates)
    events = combine_events(parsed, gaps)
    adjusted = apply_adjustment(panel, events)

    adjusted.write_parquet(settings.curated_dir / "panel.parquet")
    events.write_parquet(settings.curated_dir / "ca_events.parquet")
    print(
        f"panel: {adjusted.height} rows, {adjusted['canon_symbol'].n_unique()} instruments, "
        f"{adjusted['trade_date'].n_unique()} days\n"
        f"CA events: {events.height} (parsed {parsed.height}, observed-gap {gaps.height})"
    )

    snapshots_n500 = sorted((settings.raw_dir / "constituents").glob("nifty500_*.csv"))
    if snapshots_n500:
        n500 = parse_nifty500_list(snapshots_n500[-1].read_bytes())
        master = build_security_master(adjusted, n500)
        master.write_parquet(settings.curated_dir / "security_master.parquet")
        print(
            f"security master: {master.height} symbols, "
            f"{master['industry'].is_not_null().sum()} with sector"
        )
    else:
        print("WARNING: no NIFTY 500 snapshot in raw zone; security master not built")

    qa = run_qa(adjusted)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    qa_path = settings.reports_dir / f"qa_panel_{stamp}.json"
    qa_path.write_text(json.dumps(qa.summary(), indent=2, default=str))
    for name, frame in qa.warnings.items():
        frame.write_parquet(settings.reports_dir / f"qa_{name}_{stamp}.parquet")
    print(f"QA: {qa.summary()} -> {qa_path}")
    if not qa.ok:
        print("QA structural errors: curated build is NOT fit for downstream use", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
