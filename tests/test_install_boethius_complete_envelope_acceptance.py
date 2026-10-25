"""Focused rollback checks for the frozen Boethius one-work swap."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools import install_boethius_complete_envelope_acceptance as route
from ocd_kernel.tei.install_accepted import _files, _io_path


REVIEW_AREA = Path("D:/Library/Open Christian Data/candidate-reviews")


def test_read_only_preflight() -> None:
    record, root, stage, fixture = route.preflight()
    assert not fixture
    assert root == route.ROOT.resolve(strict=True)
    assert stage == route.STAGE.resolve(strict=True)
    assert len(record["before"]) == 3
    assert len(record["after"]) == 35


@pytest.mark.parametrize("failure_point", ["after-old-rename", "after-new-rename"])
def test_marked_fixture_rolls_back_exact_preimage(failure_point: str) -> None:
    area = REVIEW_AREA.resolve(strict=True)
    canonical_before = _files(route.ROOT / route.WORK)
    fixture = Path(tempfile.mkdtemp(prefix="boethius-complete-install-test-", dir=area)).resolve(strict=True)
    assert area in fixture.parents and fixture.name.startswith("boethius-complete-install-test-")
    try:
        (_io_path(fixture / route.FIXTURE_MARKER)).write_text("fixture\n", encoding="utf-8")
        destination = fixture / route.WORK
        _io_path(destination).parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_io_path(route.ROOT / route.WORK), _io_path(destination))
        assert _files(destination) == canonical_before

        def fail(phase: str) -> None:
            if phase == failure_point:
                raise RuntimeError(f"injected {phase}")

        with pytest.raises(RuntimeError, match=failure_point):
            route.install(root_override=fixture, fail_at=fail)
        assert _files(destination) == canonical_before
        operations = list(_io_path(fixture / "library/.sidecar-operations").iterdir())
        assert len(operations) == 1
        journal = json.loads(_io_path(operations[0] / "operation.json").read_bytes())
        assert journal["phase"] == "rolled-back"
    finally:
        assert area in fixture.parents and fixture.name.startswith("boethius-complete-install-test-")
        shutil.rmtree(_io_path(fixture))
    assert _files(route.ROOT / route.WORK) == canonical_before


HISTORICAL_STAGE = route.STAGE
HISTORICAL_RECEIPT_SHA = route.RECEIPT_SHA
SOURCE_ROOT = route.ROOT
FROZEN_BEFORE = {'forms/boethius-theological-tractates-english/editions/boethius-theological-tractates-retained-electronic-witness/acquisitions/boethius-theological-tractates-retained-source.json': 'tests/fixtures/reconstruction-runtime/authorities/boethius-complete-before.acquisition.json', 'state.json': 'tests/fixtures/reconstruction-runtime/authorities/boethius-complete-before.state.json', 'work.json': 'tests/fixtures/reconstruction-runtime/authorities/boethius-complete-before.work.json'}


@pytest.fixture(autouse=True)
def exact_historical_install_context(tmp_path, monkeypatch):
    original_receipt = _io_path(HISTORICAL_STAGE / "boethius-complete-stage-receipt.json").read_bytes()
    assert sha256(original_receipt).hexdigest() == HISTORICAL_RECEIPT_SHA
    original = json.loads(original_receipt)
    assert _files(HISTORICAL_STAGE / route.WORK) == original["after"]
    actual_source_before = _files(SOURCE_ROOT / route.WORK)
    original_stage_files = _files(HISTORICAL_STAGE)
    root = tmp_path / "before-root"
    root.mkdir()
    for relative, expected in original_stage_files.items():
        if relative == "boethius-complete-stage-receipt.json" or relative.startswith(route.WORK.as_posix() + "/"):
            continue
        raw = _io_path(HISTORICAL_STAGE / relative).read_bytes()
        assert sha256(raw).hexdigest() == expected
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    for relative, fixture in FROZEN_BEFORE.items():
        raw = (SOURCE_ROOT / fixture).read_bytes()
        assert sha256(raw).hexdigest() == original["before"][relative]
        target = _io_path(root / route.WORK / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert _files(root / route.WORK) == original["before"]
    stage = tmp_path / "stage"
    shutil.copytree(_io_path(HISTORICAL_STAGE), _io_path(stage))
    current = deepcopy(original)
    current.update(canonical_root=root.resolve(strict=True).as_posix(), stage_root=stage.resolve(strict=True).as_posix())
    restored = deepcopy(current)
    restored["canonical_root"] = original["canonical_root"]
    restored["stage_root"] = original["stage_root"]
    assert restored == original
    assert _files(stage / route.WORK) == original["after"]
    raw = (json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    receipt = stage / "boethius-complete-stage-receipt.json"
    receipt.write_bytes(raw)
    monkeypatch.setattr(route, "ROOT", root)
    monkeypatch.setattr(route, "STAGE", stage)
    monkeypatch.setattr(route, "RECEIPT", receipt)
    monkeypatch.setattr(route, "RECEIPT_SHA", sha256(raw).hexdigest())
    yield
    assert _files(SOURCE_ROOT / route.WORK) == actual_source_before
    assert _files(HISTORICAL_STAGE) == original_stage_files
    assert (HISTORICAL_STAGE / "boethius-complete-stage-receipt.json").read_bytes() == original_receipt
