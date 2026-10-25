"""Focused transaction rehearsals for the four inspected bsb00000830 prose stages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools.install_openmgh_bsb830_next import install
from build.tools.preflight_openmgh_bsb830_next import preflight
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library._common import PipelineError
from tests.openmgh_sidecar_historical_fixture import historical_mgh_sidecar_root


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("C:/Scratch")
RECEIPTS = {
    "burial-of-those-falsely-excommunicated": "burial",
    "dialogue-on-the-pontificate-of-the-roman-church": "dialogue",
    "hesso-report-on-the-council-of-reims": "hesso",
    "letter-on-avoiding-masses-of-married-priests": "letter-masses",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _fixture(work_id: str) -> tuple[Path, Path, dict]:
    name = RECEIPTS[work_id]
    source_receipt = ROOT / "plans/2026-09-22-source-preflight" / f"{name}-openmgh-derived-acceptance-stage-20260926.json"
    pin = None
    fixture = Path(tempfile.mkdtemp(prefix="mgh-historical-", dir=SCRATCH))
    result = historical_mgh_sidecar_root(ROOT, fixture, source_receipt, pin)
    record = result[2]
    return result


def _cleanup(fixture: Path) -> None:
    assert fixture.resolve().is_relative_to(SCRATCH.resolve())
    assert not fixture.is_symlink()
    shutil.rmtree(_io_path(fixture))


def test_injected_failure_restores_work_manifest_and_profile() -> None:
    fixture, receipt, record = _fixture("burial-of-those-falsely-excommunicated")
    try:
        preflight(receipt)
        def interrupt(point: str) -> None:
            if point == "after-source-manifest.json-swap":
                raise RuntimeError("injected after both source-sidecar swaps")
        with pytest.raises(RuntimeError, match="injected"):
            install(receipt, fail_at=interrupt)
        work = fixture / "library/works" / record["work_id"]
        assert _files(work) == record["before"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_before_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_before_sha256"]
        journals = list((fixture / "library/.sidecar-operations").glob("openmgh-bsb830-*/operation.json"))
        assert len(journals) == 1
        assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"
        assert preflight(receipt)["status"] == "ready-for-review"
    finally:
        _cleanup(fixture)

@pytest.mark.parametrize("work_id", sorted(RECEIPTS))
def test_fixture_install_matches_exact_stage_and_checks_rows(work_id: str) -> None:
    fixture, receipt, record = _fixture(work_id)
    try:
        result = install(receipt)
        assert result["status"] == "installed-and-validated"
        assert result["projection_rows"] == 1
        assert _files(fixture / "library/works" / work_id) == record["after"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_after_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_after_sha256"]
        journal = Path(result["operation"]) / "operation.json"
        assert json.loads(journal.read_text(encoding="utf-8"))["phase"] == "complete"
    finally:
        _cleanup(fixture)

def test_current_generation_cannot_satisfy_historical_receipt() -> None:
    fixture, receipt, record = _fixture("burial-of-those-falsely-excommunicated")
    try:
        record["canonical_root"] = ROOT.as_posix()
        receipt.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="canonical or staged work generation changed"):
            preflight(receipt)
    finally:
        _cleanup(fixture)
