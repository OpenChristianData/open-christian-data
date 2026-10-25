"""The DocSouth image promotion is all-or-nothing through validation."""

from pathlib import Path

import pytest

from build.tools.acquire_docsouth_remaining_images import _commit


def test_validation_failure_restores_existing_files_and_removes_new_file(tmp_path: Path) -> None:
    existing = tmp_path / "acquisition.json"
    incoming = tmp_path / "image.jpg"
    lock = tmp_path / "image.lock"
    existing.write_bytes(b"original acquisition")

    def reject() -> None:
        assert existing.read_bytes() == b"changed acquisition"
        assert incoming.read_bytes() == b"new image"
        raise ValueError("injected acquisition validation failure")

    with pytest.raises(ValueError, match="injected acquisition validation failure"):
        _commit({existing: b"changed acquisition", incoming: b"new image"}, lock, validate=reject)

    assert existing.read_bytes() == b"original acquisition"
    assert not incoming.exists()
    assert not lock.exists()
