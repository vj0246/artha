"""Build the curated zone from the raw zone.

Usage:
    uv run python scripts/build_curated.py [--years 2010 2011 ...]

Steps: raw bhavcopy zips -> per-year Parquet; symbolchange snapshot (newest
in raw zone, downloaded if absent) -> equity panel with canonical symbols ->
implied CA events -> adjusted panel. Outputs under $ARTHA_DATA_DIR/curated:
bhavcopy/{year}.parquet, panel.parquet, ca_events.parquet.
"""

import argparse
import sys
from datetime import date

from artha.config import load_settings
from artha.data.adjust import apply_adjustment, equity_panel, implied_ca_events
from artha.data.curated import build_curated_bhavcopy, load_curated_bhavcopy
from artha.data.ingest.nse_http import nse_client
from artha.data.ingest.symbolchange import download_symbolchange, parse_symbolchange
from artha.data.store import RawStore


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
    events = implied_ca_events(panel)
    adjusted = apply_adjustment(panel, events)

    adjusted.write_parquet(settings.curated_dir / "panel.parquet")
    events.write_parquet(settings.curated_dir / "ca_events.parquet")
    print(
        f"panel: {adjusted.height} rows, {adjusted['canon_symbol'].n_unique()} instruments, "
        f"{adjusted['trade_date'].n_unique()} days\n"
        f"implied CA events: {events.height}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
