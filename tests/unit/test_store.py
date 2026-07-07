"""Raw-zone store: immutability and manifest integrity."""

import hashlib
import json
from pathlib import Path

import pytest

from artha.data.store import ImmutabilityError, RawStore


def test_write_creates_file_and_manifest_record(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    content = b"PK fake zip bytes"
    target = store.write("bhavcopy/2024/x.zip", content, source_url="https://example.com/x.zip")

    assert target.read_bytes() == content
    record = json.loads(store.manifest_path.read_text(encoding="utf-8").splitlines()[0])
    assert record["relpath"] == "bhavcopy/2024/x.zip"
    assert record["sha256"] == hashlib.sha256(content).hexdigest()
    assert record["size"] == len(content)
    assert record["source_url"] == "https://example.com/x.zip"


def test_overwrite_refused(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    store.write("a/b.zip", b"first", source_url="u")
    with pytest.raises(ImmutabilityError):
        store.write("a/b.zip", b"second", source_url="u")
    assert store.path_for("a/b.zip").read_bytes() == b"first"


def test_exists(tmp_path: Path) -> None:
    store = RawStore(tmp_path)
    assert not store.exists("a/b.zip")
    store.write("a/b.zip", b"x", source_url="u")
    assert store.exists("a/b.zip")
