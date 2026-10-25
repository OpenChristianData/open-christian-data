"""Focused guarded directory-swap and rollback checks for the direct-raw four."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import build.tools.install_direct_raw_four_sidecars as installer
from ocd_kernel.library._common import PipelineError, sha256_file


WID = "test-direct-work"
PREFIX = f"library/works/{WID}/"


def _fixture(tmp_path: Path):
    root = tmp_path / "repo"
    staged = tmp_path / "stage"
    target = root / PREFIX
    staged_work = staged / PREFIX
    target.mkdir(parents=True)
    staged_work.mkdir(parents=True)
    existing = {"work.json": b'{"version":1}\n', "state.json": b'{"state":1}\n'}
    proposed = {"work.json": b'{"version":2}\n', "state.json": b'{"state":2}\n',
                "SOURCE_CREDIT.md": b"Verified source credit\n",
                "forms/test/editions/test/acquisitions/test.json": b'{"source":"html"}\n'}
    for relative, content in existing.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    items = []
    for relative, content in proposed.items():
        path = staged_work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        before = target / relative
        items.append({"path": PREFIX + relative,
                      "before_sha256": sha256_file(before) if before.is_file() else None,
                      "proposed_sha256": sha256_file(path)})
    return root, staged, items, {relative: sha256_file(target / relative) for relative in existing}


def _journal(root: Path) -> dict:
    journals = list((root / "library/.sidecar-operations").glob("direct-four-*/operation.json"))
    assert len(journals) == 1
    return json.loads(journals[0].read_text(encoding="utf-8"))


def test_install_retains_previous_generation(tmp_path):
    root, staged, items, before = _fixture(tmp_path)
    result = installer._install_one(root, staged, WID, items, validate_live=False)
    assert _journal(root)["phase"] == "complete"
    assert {relative: sha256_file(Path(result["operation"]) / "previous" / relative)
            for relative in before} == before
    assert (root / PREFIX / "SOURCE_CREDIT.md").read_text(encoding="utf-8") == "Verified source credit\n"


def test_first_rename_failure_preserves_current_generation(tmp_path, monkeypatch):
    root, staged, items, before = _fixture(tmp_path)
    target = root / PREFIX
    original = Path.rename

    def fail_first(path: Path, destination: Path):
        if path == target:
            raise OSError("injected first rename failure")
        return original(path, destination)

    monkeypatch.setattr(Path, "rename", fail_first)
    with pytest.raises(OSError, match="injected first rename failure"):
        installer._install_one(root, staged, WID, items, validate_live=False)
    assert _journal(root)["phase"] == "failed-before-swap"
    assert {relative: sha256_file(target / relative) for relative in before} == before


def test_post_swap_validation_failure_restores_original(tmp_path, monkeypatch):
    root, staged, items, before = _fixture(tmp_path)

    def fail_validation(*_args, **_kwargs):
        raise PipelineError("injected live validation failure")

    monkeypatch.setattr(installer, "validate_acquisition", fail_validation)
    with pytest.raises(PipelineError, match="injected live validation failure"):
        installer._install_one(root, staged, WID, items)
    assert _journal(root)["phase"] == "rolled-back"
    target = root / PREFIX
    assert {relative: sha256_file(target / relative) for relative in before} == before
    assert not (target / "SOURCE_CREDIT.md").exists()


def test_changed_staged_file_fails_before_swap(tmp_path):
    root, staged, items, before = _fixture(tmp_path)
    (staged / PREFIX / "work.json").write_bytes(b"tampered\n")
    with pytest.raises(PipelineError, match="incoming generation differs"):
        installer._install_one(root, staged, WID, items, validate_live=False)
    target = root / PREFIX
    assert {relative: sha256_file(target / relative) for relative in before} == before
