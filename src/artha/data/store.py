"""Raw-zone storage: immutable as-downloaded files with a hash manifest.

Every stored file gets a line in ``manifest.jsonl`` recording its sha256,
size, source URL, and download timestamp. Files are never overwritten;
attempting to do so raises. Single-writer assumption (one backfill process
at a time).
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class ImmutabilityError(Exception):
    """Raised when a write would overwrite an existing raw file."""


class RawStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.jsonl"

    def path_for(self, relpath: str) -> Path:
        return self.root / relpath

    def exists(self, relpath: str) -> bool:
        return self.path_for(relpath).is_file()

    def write(self, relpath: str, content: bytes, *, source_url: str) -> Path:
        target = self.path_for(relpath)
        if target.exists():
            raise ImmutabilityError(f"raw file already exists, refusing overwrite: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        record = {
            "relpath": relpath,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
            "source_url": source_url,
            "downloaded_at": datetime.now(UTC).isoformat(),
        }
        with self.manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        return target
