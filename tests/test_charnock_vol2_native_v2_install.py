"""Focused selected-line and rollback checks for Charnock Volume 2 PG53527."""

from __future__ import annotations

from pathlib import Path
import json
import sys
import shutil
from tempfile import TemporaryDirectory

import pytest

from build.tools.install_charnock_vol2_native_v2_acceptance import install, preflight
from build.tools.stage_charnock_vol2_native_v2_acceptance import ROOT, SOURCE, WORK
from tests.frozen_install_preimages import copy_recorded_preimage
from tests.current_frozen_install_context import current_frozen_stage, current_native_source_baseline
from build.tools import install_charnock_vol2_native_v2_acceptance as installer
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files, _io_path


STAGE = Path("D:/Library/Open Christian Data/candidate-reviews/c2-s4")
RECEIPT_SHA = "5179359637711976e1797425252d952166478525b009e63376dac6abdfcb5ed0"

HISTORICAL_STAGE = STAGE
HISTORICAL_RECEIPT_SHA = RECEIPT_SHA
RUNTIME_CASE = next(row for row in json.loads((ROOT / "tests/fixtures/reconstruction-runtime/native-v2-install-runtime-cases.json").read_bytes())
                    if row["name"] == "charnock_vol2_native_v2")


def _fixture(root: Path) -> Path:
    (root / ".ocd-charnock-vol2-native-v2-install-fixture").write_text("fixture-only\n", encoding="utf-8")
    for name in ("raw", "sources", "build", "ocd_kernel", "tests"):
        if (STAGE / name).is_dir():
            shutil.copytree(STAGE / name, root / name)
    (root / WORK.parent).mkdir(parents=True, exist_ok=True)
    copy_recorded_preimage(HISTORICAL_STAGE, WORK, HISTORICAL_RECEIPT_SHA, root)
    return root


@pytest.fixture
def short_root():
    with TemporaryDirectory(prefix="cv-", dir="C:/tmp") as folder:
        try:
            yield _fixture(Path(folder))
        finally:
            shutil.rmtree(_io_path(Path(folder)))


def test_exact_receipt_pin_and_read_only_preflight(short_root: Path) -> None:
    result = preflight(STAGE, RECEIPT_SHA, root=short_root)
    assert result["status"] == "ready-for-review"
    assert result["native_rows"] == 2
    assert result["source_lines"] == 62798
    assert result["represented_source_lines"] == 32140
    assert result["scope_kind"] == "selection"
    with pytest.raises(PipelineError, match="receipt differs"):
        preflight(STAGE, "0" * 64, root=short_root)


def test_retained_text_mutation_fails_closed(short_root: Path) -> None:
    source = short_root / SOURCE
    original = source.read_bytes()
    source.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="source|authority|sha|digest|differs"):
        preflight(STAGE, RECEIPT_SHA, root=short_root)


def test_profile_mutation_fails_closed(short_root: Path) -> None:
    profile = short_root / RUNTIME_CASE["profile"]
    original = profile.read_bytes()
    profile.write_bytes(b"X" + original[1:])
    with pytest.raises((PipelineError, ValueError), match="authority|sha|digest|differs"):
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
    assert result["projection_rows"] == 2


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
    return current_native_source_baseline(
        ROOT, RUNTIME_CASE, HISTORICAL_STAGE / installer.EVIDENCE / "inputs/package",
        tmp_path_factory.mktemp("nv") / "current-candidate")


@pytest.fixture(autouse=True)
def current_runtime_stage(tmp_path, monkeypatch, current_source_candidate):
    baseline, candidate = current_source_candidate
    original_source = (ROOT / RUNTIME_CASE["original"]).read_bytes()
    original_stage_files = _files(HISTORICAL_STAGE)
    destination = tmp_path / "i"
    stage, pin = current_frozen_stage(installer, HISTORICAL_STAGE, HISTORICAL_RECEIPT_SHA,
                                      baseline, candidate, destination)
    monkeypatch.setattr(sys.modules[__name__], "STAGE", stage)
    monkeypatch.setattr(sys.modules[__name__], "RECEIPT_SHA", pin)
    monkeypatch.setattr(installer, "LIBRARY", destination)
    monkeypatch.setattr(installer, "MANIFEST", Path(RUNTIME_CASE["manifest"]))
    monkeypatch.setattr(installer, "CANDIDATE", candidate.path)
    yield
    assert (ROOT / RUNTIME_CASE["original"]).read_bytes() == original_source
    assert _files(HISTORICAL_STAGE) == original_stage_files
