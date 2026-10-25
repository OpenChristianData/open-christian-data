"""Fixture-only NPNF104 work-stage stale, tamper, rollback, and projection checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from tests.npnf_four_install_fixture import (
    four_work_install_fixture, current_npnf_generation_is_preserved, current_generation_receipt,
)

from build.tools import preflight_npnf104_work_acceptance as guard
from build.tools.install_npnf104_work_acceptance import install
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.library._common import PipelineError


ROOT = Path(__file__).resolve().parents[1]
STAGES = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-npnf104-stages-20260927")
RECEIPTS = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-npnf104-stage-receipts-20260927")
WORK_ID = "augustine-morals-catholic-church"


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _write(path: Path, data: bytes) -> None:
    Path(_io_path(path)).write_bytes(data)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict]:
    root, receipt, record, batch_sha = four_work_install_fixture(ROOT, tmp_path, WORK_ID)
    assert guard.family.BATCH == Path("plans/2026-09-22-source-preflight/augustine-npnf104-work-candidates-20260927.json")
    for place in (root, Path(record["stage_root"])):
        assert sha256(_bytes(place / guard.family.BATCH)).hexdigest() == batch_sha
    assert sha256(_bytes(Path(record["package_receipt"]))).hexdigest() == batch_sha
    monkeypatch.setattr(guard, "BATCH_SHA", batch_sha)
    return root, receipt, record


def test_preflight_rejects_stale_source_and_stage_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, receipt, record = _fixture(tmp_path, monkeypatch)
    assert guard.preflight(receipt)["projection_rows"] == 1
    source = root / record["source_path"]
    prior = _bytes(source)
    _write(source, prior + b" ")
    with pytest.raises(Exception, match="source|batch|profile"):
        guard.preflight(receipt)
    _write(source, prior)
    state = root / "library/works" / WORK_ID / "state.json"
    prior = _bytes(state)
    _write(state, prior + b" ")
    with pytest.raises(Exception, match="generation"):
        guard.preflight(receipt)
    _write(state, prior)
    stage_work = Path(record["stage_root"]) / "library/works" / WORK_ID
    stage_state = stage_work / "state.json"
    prior = _bytes(stage_state)
    _write(stage_state, prior + b" ")
    with pytest.raises(Exception, match="generation"):
        guard.preflight(receipt)
    _write(stage_state, prior)
    with pytest.raises(Exception, match="exact reviewed stage receipt hash changed"):
        install(receipt, expected_receipt_sha256="0" * 64)


def test_installer_rolls_back_then_projects_fixture_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, receipt, record = _fixture(tmp_path, monkeypatch)
    work = root / "library/works" / WORK_ID
    before = _files(work)
    manifest, profile = root / record["manifest_path"], root / record["profile_path"]
    before_manifest, before_profile = _bytes(manifest), _bytes(profile)
    pin = sha256(_bytes(receipt)).hexdigest()

    def fail_after_manifest(phase: str) -> None:
        if phase == "after-source-manifest.json-swap":
            raise RuntimeError("injected manifest-swap failure")

    with pytest.raises(RuntimeError, match="injected manifest-swap failure"):
        install(receipt, expected_receipt_sha256=pin, fail_at=fail_after_manifest,
                operation_prefix="npnf104-work-fixture")
    assert _files(work) == before
    assert _bytes(manifest) == before_manifest
    assert _bytes(profile) == before_profile
    journals = list((root / "library/.sidecar-operations").glob("npnf104-work-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_bytes(journals[0]))["phase"] == "rolled-back"

    result = install(receipt, expected_receipt_sha256=pin,
                     operation_prefix="npnf104-work-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(work) == record["after"]
    assert sha256(_bytes(manifest)).hexdigest() == record["source_manifest_after_sha256"]
    assert sha256(_bytes(profile)).hexdigest() == record["profile_after_sha256"]


@pytest.fixture(autouse=True)
def _preserve_current_repository_and_retained_stage():
    with current_npnf_generation_is_preserved(ROOT, WORK_ID):
        yield


def test_current_accepted_generation_is_not_the_original_before(tmp_path: Path) -> None:
    receipt = current_generation_receipt(ROOT, tmp_path / "current-generation.json", WORK_ID)
    with pytest.raises(PipelineError, match="work generation or source sidecar path changed"):
        guard.preflight(receipt)
