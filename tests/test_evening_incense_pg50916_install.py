"""Focused exact-HTML and rollback checks for the Evening Incense PG50916 handoff."""

from __future__ import annotations

from pathlib import Path
from hashlib import sha256
from copy import deepcopy
import json
import sys
import shutil
from tempfile import TemporaryDirectory

import pytest

from build.tools.install_evening_incense_pg50916_acceptance import install, preflight
from build.tools.stage_evening_incense_pg50916_acceptance import ROOT, SOURCE, WORK
from tests.frozen_install_preimages import copy_recorded_preimage
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.current_frozen_install_context import current_frozen_stage
from build.tools import install_evening_incense_pg50916_acceptance as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/ei-s1")
RECEIPT_SHA = "7f749254a98b8c876a0a4d83543c592d0f0448c541c650d13a2e18793c6ca812"
HISTORICAL_STAGE = STAGE
HISTORICAL_RECEIPT_SHA = RECEIPT_SHA
ORIGINAL_MANIFEST = installer.MANIFEST
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/evening-incense-pg50916-current-installer.source-manifest.json")
RUNTIME_SHA = '28679337418088230b1a5c200e9c4a8b97b14520e241845f273b18283ef119ef'


def _fixture(root: Path) -> Path:
    (root / ".ocd-evening-incense-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "build", "ocd_kernel", "tests"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    (root / WORK.parent).mkdir(parents=True, exist_ok=True)
    copy_recorded_preimage(HISTORICAL_STAGE, WORK, HISTORICAL_RECEIPT_SHA, root)
    return root


@pytest.fixture
def short_root():
    with TemporaryDirectory(prefix="ei-", dir="C:/tmp") as folder:
        try:
            yield _fixture(Path(folder))
        finally:
            shutil.rmtree(_io_path(Path(folder)))


def test_exact_receipt_pin_and_read_only_preflight(short_root: Path) -> None:
    result = preflight(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "ready-for-review"
    assert result["native_rows"] == 1
    assert result["source_elements"] == 1067
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=short_root)


def test_extracted_html_mutation_fails_closed(short_root: Path) -> None:
    source = short_root / SOURCE
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|differs"):
        preflight(STAGE, RECEIPT_SHA, root=short_root)


def test_cover_favicon_mutation_fails_closed(short_root: Path) -> None:
    image = short_root / "raw/gutenberg/50916/html/images/cover.jpg"
    original = image.read_bytes()
    image.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="image|authority|sha|digest|differs"):
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


def test_current_accepted_generation_rejects_frozen_preimage() -> None:
    import json
    record = json.loads((STAGE / "stage-receipt.json").read_bytes())
    assert _files(ROOT / WORK) != record["before"]
    before = _files(ROOT / WORK)
    with pytest.raises(PipelineError, match="complete work preimage or stage generation differs"):
        preflight(STAGE, RECEIPT_SHA)
    assert _files(ROOT / WORK) == before


@pytest.fixture(scope="module")
def current_source_candidate(tmp_path_factory):
    assert sha256((ROOT / RUNTIME_MANIFEST).read_bytes()).hexdigest() == RUNTIME_SHA
    original = json.loads((HISTORICAL_STAGE / "stage-receipt.json").read_bytes())
    return current_runtime_baseline(
        root=ROOT, original_manifest=ORIGINAL_MANIFEST, runtime_manifest=RUNTIME_MANIFEST,
        retained_package=HISTORICAL_STAGE / installer.EVIDENCE / "inputs/package",
        retained_sha256=original["candidate_package_sha256"],
        destination=tmp_path_factory.mktemp("ev") / "current-candidate")


@pytest.fixture(autouse=True)
def current_runtime_stage(tmp_path, monkeypatch, current_source_candidate):
    baseline, candidate = current_source_candidate
    original_source = (ROOT / ORIGINAL_MANIFEST).read_bytes()
    original_stage_files = _files(HISTORICAL_STAGE)
    destination = tmp_path / "i"
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


def test_runtime_source_preserves_complete_historical_record():
    original = json.loads((ROOT / ORIGINAL_MANIFEST).read_bytes())
    raw = (ROOT / RUNTIME_MANIFEST).read_bytes()
    assert sha256(raw).hexdigest() == RUNTIME_SHA
    current = json.loads(raw)
    restored = deepcopy(current)
    restored["validator"]["import_closure_sha256"] = original["validator"]["import_closure_sha256"]
    assert restored == original
    assert current["validator"]["import_closure_sha256"] != original["validator"]["import_closure_sha256"]

    from ocd_kernel.reconstruction.closure_verification import check_validator_manifest_closure
    check = check_validator_manifest_closure(ROOT, RUNTIME_MANIFEST)
    assert check.matches
    assert check.live_sha256 == current["validator"]["import_closure_sha256"]
