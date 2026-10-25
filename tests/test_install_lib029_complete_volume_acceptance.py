"""Guarded Schaff work-swap rollback on a marked external fixture."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil
import uuid

import pytest

from build.tools import install_lib029_complete_volume_acceptance as installer
from ocd_kernel.library._common import PipelineError
from build.tools.install_lib029_complete_volume_acceptance import (
    FIXTURE_MARKER, FIXTURE_PARENT, ROOT, WORK, _copy_generation, _files, _io_path, install, preflight,
)


@pytest.fixture
def fixture_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fixture_parent = tmp_path
    monkeypatch.setattr(installer, "FIXTURE_PARENT", fixture_parent)
    fixture = fixture_parent / f"sf-{uuid.uuid4().hex[:8]}"
    fixture.mkdir()
    (fixture / FIXTURE_MARKER).write_bytes(b"Schaff work-swap fixture\n")
    try:
        yield fixture
    finally:
        if (fixture.resolve(strict=True).parent != fixture_parent.resolve(strict=True)
                or fixture.is_symlink() or not (fixture / FIXTURE_MARKER).is_file()):
            raise ValueError("Schaff fixture cleanup target escaped the candidate-review parent")
        shutil.rmtree(_io_path(fixture))


@pytest.mark.parametrize("failure_phase", ["after-old-rename", "after-new-rename"])
def test_marked_fixture_rolls_back_entire_work_generation(fixture_root: Path, failure_phase: str, historical_root: Path) -> None:
    fixture = fixture_root
    target = fixture / WORK
    target.parent.mkdir(parents=True)
    _copy_generation(historical_root / WORK, target, _files(historical_root / WORK))
    record, _, _, is_fixture = preflight(root_override=fixture)
    assert is_fixture
    assert _files(target) == record["before"]

    def fail_at(phase: str) -> None:
        if phase == failure_phase:
            raise RuntimeError(f"injected {phase} failure")

    with pytest.raises(RuntimeError, match=failure_phase):
        install(root_override=fixture, fail_at=fail_at)
    assert _files(target) == record["before"]
    journals = list((fixture / "library/.sidecar-operations").glob("*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["phase"] == "rolled-back"


@pytest.fixture(scope="module", autouse=True)
def historical_root(tmp_path_factory: pytest.TempPathFactory):
    raw = _io_path(installer.RECEIPT).read_bytes()
    assert sha256(raw).hexdigest() == installer.RECEIPT_SHA
    record = json.loads(raw)
    assert _files(installer.STAGE / WORK) == record["after"]
    root = tmp_path_factory.mktemp("schaff-historical")
    for relative, expected in record["before"].items():
        payload = _io_path(installer.STAGE / WORK / relative).read_bytes()
        assert sha256(payload).hexdigest() == record["after"][relative]
        if sha256(payload).hexdigest() != expected:
            value = json.loads(payload)
            if relative == "work.json":
                assert value["textual_forms"][0]["editions"][0].pop("category") == "prose"
            elif relative == "state.json":
                edition = next(t for t in value["targets"] if t["target_type"] == "edition")
                acquisition = next(t for t in value["targets"] if t["target_type"] == "acquisition")
                assert edition["stage"] == "accepted"
                edition["stage"] = "acquired"
                edition.pop("reason")
                edition["updated_at"] = acquisition["updated_at"]
                assert edition["evidence"][-2].endswith("/master.tei.xml")
                assert edition["evidence"][-1].endswith("/acceptance.json")
                edition["evidence"] = edition["evidence"][:-2]
            else:
                raise AssertionError("Acquisition must retain its original bytes")
            payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert sha256(payload).hexdigest() == expected
        target = _io_path(root / WORK / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    assert _files(root / WORK) == record["before"]
    prefix = WORK.as_posix() + "/"
    for relative in _files(installer.STAGE):
        if relative == installer.RECEIPT.name or relative.startswith(prefix):
            continue
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_io_path(installer.STAGE / relative).read_bytes())
    current = dict(record, canonical_root=root.as_posix())
    assert dict(current, canonical_root=record["canonical_root"]) == record
    payload = (json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt = root / installer.RECEIPT.name
    receipt.write_bytes(payload)
    with pytest.MonkeyPatch.context() as context:
        context.setattr(installer, "ROOT", root)
        context.setattr(installer, "RECEIPT", receipt)
        context.setattr(installer, "RECEIPT_SHA", sha256(payload).hexdigest())
        yield root


def test_original_root_guard_rejects_wrong_context(historical_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "wrong-root"
    wrong.mkdir()
    monkeypatch.setattr(installer, "ROOT", wrong)
    with pytest.raises(PipelineError, match="contract or roots differ"):
        preflight(root_override=historical_root)


def test_marked_fixture_guard_rejects_unmarked_root(historical_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    wrong = tmp_path / "unmarked"
    wrong.mkdir()
    monkeypatch.setattr(installer, "FIXTURE_PARENT", tmp_path)
    with pytest.raises(PipelineError, match="marked candidate-review fixture"):
        preflight(root_override=wrong)
