"""Fixture-only NPNF103 work-stage stale, tamper, rollback, and projection checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from build.tools import preflight_npnf103_work_acceptance as guard
from build.tools.install_npnf103_work_acceptance import install
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.npnf_install_runtime_fixture import current_npnf_work_install_context


ROOT = Path(__file__).resolve().parents[1]
STAGES = Path("D:/Library/Open Christian Data/candidate-reviews/augustine-npnf103-acceptance-stages-20260926")
RECEIPTS = ROOT / "plans/2026-09-22-source-preflight"
WORK_ID = "augustine-faith-things-not-seen"


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _write(path: Path, data: bytes) -> None:
    Path(_io_path(path)).write_bytes(data)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, dict]:
    cases = json.loads((ROOT / "tests/fixtures/npnf-install-before/cases.json").read_bytes())
    case = next(row for row in cases if row["work_id"] == WORK_ID)
    root, receipt, record, batch_sha = current_npnf_work_install_context(
        ROOT, tmp_path, receipt_path=Path(case["receipt_path"]),
        receipt_sha256=case["receipt_sha256"], preserved_before=case["preserved_before"],
        runtime_fields=case["runtime_fields"])
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
                operation_prefix="npnf103-work-fixture")
    assert _files(work) == before
    assert _bytes(manifest) == before_manifest
    assert _bytes(profile) == before_profile
    journals = list((root / "library/.sidecar-operations").glob("npnf103-work-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_bytes(journals[0]))["phase"] == "rolled-back"

    result = install(receipt, expected_receipt_sha256=pin,
                     operation_prefix="npnf103-work-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(work) == record["after"]
    assert sha256(_bytes(manifest)).hexdigest() == record["source_manifest_after_sha256"]
    assert sha256(_bytes(profile)).hexdigest() == record["profile_after_sha256"]


def test_current_generation_is_not_the_historical_preimage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, receipt, record = _fixture(tmp_path, monkeypatch)
    target = root / "library/works" / WORK_ID
    assert target.resolve(strict=True).is_relative_to(root.resolve(strict=True))
    assert not target.is_symlink() and not target.is_junction()
    shutil.rmtree(_io_path(target))
    shutil.copytree(_io_path(ROOT / "library/works" / WORK_ID), _io_path(target))
    assert _files(target) != record["before"]
    with pytest.raises(Exception, match="generation"):
        guard.preflight(receipt)


def test_current_kernel_dependency_tamper_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, receipt, _record = _fixture(tmp_path, monkeypatch)
    dependency = root / "ocd_kernel/reconstruction/contract.py"
    original = dependency.read_bytes()
    assert original == (ROOT / "ocd_kernel/reconstruction/contract.py").read_bytes()
    dependency.write_bytes(original + b"\n")
    with pytest.raises(Exception, match="closure|source oracle|import|binding"):
        guard.preflight(receipt)


def test_original_runtime_record_rejects_current_dependencies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, validate
    root, _receipt, record = _fixture(tmp_path, monkeypatch)
    case = next(row for row in json.loads((ROOT / "tests/fixtures/npnf-install-before/cases.json").read_bytes())
                if row["work_id"] == WORK_ID)
    original_receipt = json.loads(_bytes(Path(case["receipt_path"])))
    original_batch = json.loads(_bytes(Path(original_receipt["package_receipt"])))
    item = next(row for row in original_batch["works"] if row["work_id"] == WORK_ID)
    package = CandidatePackage.load(Path(item["candidate_root"]) / "package")
    assert package.sha256 == item["candidate_sha256"]
    original_raw = _bytes(ROOT / case["preserved_before"] / "manifest-before.json")
    assert sha256(original_raw).hexdigest() == original_receipt["source_manifest_before_sha256"]
    target = root / record["manifest_path"]
    current_raw = _bytes(target)
    try:
        target.write_bytes(original_raw)
        with pytest.raises(ValueError, match="implementation|closure|binding"):
            manifest = SourceManifest.load(target, repository_root=root)
            validate(manifest, package, guard._oracle(root, manifest))
    finally:
        target.write_bytes(current_raw)
