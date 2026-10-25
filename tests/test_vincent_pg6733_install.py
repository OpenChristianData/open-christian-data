"""Focused exact-HTML and rollback checks for the Vincent PG6733 handoff."""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from hashlib import sha256
import json
import sys
import shutil
from tempfile import TemporaryDirectory

import pytest

from build.tools.install_vincent_pg6733_acceptance import install, preflight
from build.tools.stage_vincent_pg6733_acceptance import ROOT, SOURCE, WORK
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path
from build.tools import install_vincent_pg6733_acceptance as installer
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.current_frozen_install_context import current_frozen_stage


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/vincent-pg6733-s5")
RECEIPT_SHA = "aa8dd31217618fca9506e8f1de4a67544975c75ef89b9d65b5e3c5721f8a12f3"
HISTORICAL_STAGE = STAGE
HISTORICAL_RECEIPT_SHA = RECEIPT_SHA
ORIGINAL_MANIFEST = installer.MANIFEST
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/vincent-pg6733-current-installer.source-manifest.json")
RUNTIME_SHA = "88d4ec401e0be2c1742fd846a58806db291a9058219ba489c332436ff48c80cc"
FROZEN_BEFORE = {'forms/memoir-of-father-vincent-de-paul-gutenberg-retained/editions/memoir-of-father-vincent-de-paul-gutenberg-electronic/acquisitions/memoir-of-father-vincent-de-paul-gutenberg-acquired.json': 'tests/fixtures/reconstruction-runtime/authorities/vincent-pg6733-before.acquisition.json', 'state.json': 'tests/fixtures/reconstruction-runtime/authorities/vincent-pg6733-before.state.json', 'work.json': 'tests/fixtures/reconstruction-runtime/authorities/vincent-pg6733-before.work.json'}


def _fixture(root: Path) -> Path:
    (root / ".ocd-vincent-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "build", "ocd_kernel", "tests"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    (root / WORK.parent).mkdir(parents=True, exist_ok=True)
    record = json.loads((HISTORICAL_STAGE / "stage-receipt.json").read_bytes())
    assert sha256((HISTORICAL_STAGE / "stage-receipt.json").read_bytes()).hexdigest() == HISTORICAL_RECEIPT_SHA
    assert set(FROZEN_BEFORE) == set(record["before"])
    for relative, fixture in FROZEN_BEFORE.items():
        raw = (ROOT / fixture).read_bytes()
        assert sha256(raw).hexdigest() == record["before"][relative]
        target = root / WORK / relative
        _io_path(target.parent).mkdir(parents=True, exist_ok=True)
        _io_path(target).write_bytes(raw)
    assert _files(root / WORK) == record["before"]
    return root


@pytest.fixture
def short_root():
    with TemporaryDirectory(prefix="tv-", dir="C:/tmp") as folder:
        try:
            yield _fixture(Path(folder))
        finally:
            shutil.rmtree(_io_path(Path(folder)))


def test_exact_receipt_pin_and_read_only_preflight(short_root: Path) -> None:
    result = preflight(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "ready-for-review"
    assert result["native_rows"] == 1
    assert result["source_elements"] == 202
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=short_root)


def test_extracted_html_mutation_fails_closed(short_root: Path) -> None:
    source = short_root / SOURCE
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|differs"):
        preflight(STAGE, RECEIPT_SHA, root=short_root)


def test_failed_swap_rolls_back_then_fixture_install_succeeds(short_root: Path) -> None:
    before = _files(short_root / WORK)

    def fail_after_swap(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected swap failure")

    with pytest.raises(RuntimeError, match="injected swap failure"):
        install(STAGE, RECEIPT_SHA, root=short_root, fail_at=fail_after_swap)
    assert _files(short_root / WORK) == before
    result = install(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1


@pytest.fixture(scope="module")
def current_source_candidate(tmp_path_factory):
    assert sha256((ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    original = json.loads((HISTORICAL_STAGE / "stage-receipt.json").read_bytes())
    return current_runtime_baseline(
        root=ROOT, original_manifest=ORIGINAL_MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=HISTORICAL_STAGE / installer.EVIDENCE / "inputs/package",
        retained_sha256=original["candidate_package_sha256"],
        destination=tmp_path_factory.mktemp("vincent-baseline") / "current")


@pytest.fixture(autouse=True)
def current_runtime_stage(tmp_path_factory, monkeypatch, current_source_candidate):
    baseline, candidate = current_source_candidate
    original_source = (ROOT / ORIGINAL_MANIFEST).read_bytes()
    original_stage_files = _files(HISTORICAL_STAGE)
    destination = tmp_path_factory.mktemp("vincent-stage")
    stage, pin = current_frozen_stage(installer, HISTORICAL_STAGE, HISTORICAL_RECEIPT_SHA,
                                      baseline, candidate, destination)
    monkeypatch.setattr(sys.modules[__name__], "STAGE", stage)
    monkeypatch.setattr(sys.modules[__name__], "RECEIPT_SHA", pin)
    monkeypatch.setattr(installer, "LIBRARY", destination)
    monkeypatch.setattr(installer, "MANIFEST", RUNTIME_MANIFEST)
    monkeypatch.setattr(installer, "CANDIDATE", candidate.path)
    yield
    assert (ROOT / ORIGINAL_MANIFEST).read_bytes() == original_source
    assert _files(HISTORICAL_STAGE) == original_stage_files


def test_current_accepted_generation_rejects_original_acquired_preimage():
    original = json.loads((HISTORICAL_STAGE / "stage-receipt.json").read_bytes())
    current = _files(ROOT / WORK)
    assert current != original["before"]
    with pytest.raises(PipelineError, match="complete work preimage or stage generation differs"):
        preflight(STAGE, RECEIPT_SHA)
    assert _files(ROOT / WORK) == current


def test_runtime_manifest_preserves_complete_original_vincent_record():
    original = json.loads((ROOT / ORIGINAL_MANIFEST).read_bytes())
    raw = (ROOT / RUNTIME_MANIFEST).read_bytes()
    assert sha256(raw).hexdigest() == RUNTIME_SHA
    current = json.loads(raw)
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    assert current["validator"]["import_closure_sha256"] != original["validator"]["import_closure_sha256"]
