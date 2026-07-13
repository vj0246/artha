"""Raw-zone integrity scan (P1 audit backlog item).

Usage:
    uv run python scripts/scan_raw_integrity.py

Catches files corrupted by killed processes (NUL blocks) and empty files:
- *.csv must not start with a NUL byte and must be non-empty
- *.zip must start with the PK magic
- *.json must start with '[' or '{'

Exit 1 with a listing when anything fails; delete the listed files and
re-run the matching backfill (all backfills are idempotent).
"""

import sys

from artha.config import load_settings

CHECKS = {
    ".csv": lambda head: len(head) > 0 and head[0] != 0,
    ".zip": lambda head: head[:2] == b"PK",
    ".json": lambda head: head[:1] in (b"[", b"{"),
}


def main() -> int:
    settings = load_settings()
    bad: list[str] = []
    n = 0
    for f in settings.raw_dir.rglob("*"):
        if not f.is_file():
            continue
        check = CHECKS.get(f.suffix.lower())
        if check is None:
            continue
        n += 1
        with f.open("rb") as fh:
            head = fh.read(8)
        if not check(head):
            bad.append(str(f.relative_to(settings.raw_dir)))
    print(f"scanned {n} files; corrupt: {len(bad)}")
    for b in bad:
        print(f"  CORRUPT {b}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
