"""Focused exact-source and rollback checks for the Luther PG1722 handoff."""

from __future__ import annotations

from pathlib import Path
from hashlib import sha256
from copy import deepcopy
import json
import sys
import shutil
from tempfile import TemporaryDirectory

import pytest

from build.tools.install_luther_pg1722_acceptance import install, preflight
from build.tools.stage_luther_pg1722_acceptance import ROOT, SOURCE, WORK
from tests.frozen_install_preimages import copy_recorded_preimage
from tests.runtime_candidate_baselines import current_runtime_baseline
from tests.current_frozen_install_context import current_frozen_stage
from build.tools import install_luther_pg1722_acceptance as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/luther-pg1722-accepted-stage-20260927-s5")
RECEIPT_SHA = "9134260f6f3265e8b083a5bc705bcc391557b9d3f54c3f1f400ca26526a668b4"
HISTORICAL_STAGE = STAGE
HISTORICAL_RECEIPT_SHA = RECEIPT_SHA
ORIGINAL_MANIFEST = installer.MANIFEST
RUNTIME_MANIFEST = Path("tests/fixtures/reconstruction-runtime/luthers_large_catechism_oracle.source-manifest.json")
RUNTIME_SHA = '5ebe24664f17bfdf21b5caeaf5bf59fd468f7a1262003bdbb13febcd5707ff26'


def _fixture(root: Path) -> Path:
    (root / ".ocd-luther-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "metadata", "build", "ocd_kernel", "tests"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    (root / WORK.parent).mkdir(parents=True, exist_ok=True)
    copy_recorded_preimage(HISTORICAL_STAGE, WORK, HISTORICAL_RECEIPT_SHA, root)
    return root


@pytest.fixture
def short_root():
    with TemporaryDirectory(prefix="tl-", dir="C:/tmp") as folder:
        yield _fixture(Path(folder))


def test_exact_receipt_pin_and_read_only_preflight(short_root: Path) -> None:
    result = preflight(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "ready-for-review"
    assert result["native_rows"] == 1
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=short_root)


def test_source_mutation_fails_closed(short_root: Path) -> None:
    root = short_root
    source = root / SOURCE
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|differs"):
        preflight(STAGE, RECEIPT_SHA, root=root)


def test_failed_swap_rolls_back_then_fixture_install_succeeds(short_root: Path) -> None:
    root = short_root
    before = _files(root / WORK)

    def fail_after_swap(point: str) -> None:
        if point == "after-new-live":
            raise RuntimeError("injected swap failure")

    with pytest.raises(RuntimeError, match="injected swap failure"):
        install(STAGE, RECEIPT_SHA, root=root, fail_at=fail_after_swap)
    assert _files(root / WORK) == before
    result = install(STAGE, RECEIPT_SHA, root=root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1


def test_current_accepted_generation_rejects_frozen_preimage() -> None:
    import json
    record = json.loads((STAGE / "stage-receipt.json").read_bytes())
    before = _files(ROOT / WORK)
    assert before != record["before"]
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
        destination=tmp_path_factory.mktemp("lu") / "current-candidate")


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
