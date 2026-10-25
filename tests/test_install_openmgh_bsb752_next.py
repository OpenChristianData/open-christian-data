"""Focused exact-pin and transaction rehearsals for bsb752 narrative stages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools.install_openmgh_bsb752_next import RECEIPT_HASHES, pinned_receipt
from build.tools.install_openmgh_bsb830_next import install as install_transaction
from build.tools.preflight_openmgh_bsb830_next import preflight
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library._common import PipelineError
from tests.openmgh_sidecar_historical_fixture import historical_mgh_sidecar_root


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("C:/Scratch")


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _fixture(work_id: str) -> tuple[Path, Path, dict]:
    source_receipt, pin = pinned_receipt(work_id)
    fixture = Path(tempfile.mkdtemp(prefix="mgh-historical-", dir=SCRATCH))
    result = historical_mgh_sidecar_root(ROOT, fixture, source_receipt, pin)
    record = result[2]
    return result


def _cleanup(fixture: Path) -> None:
    assert fixture.resolve().is_relative_to(SCRATCH.resolve())
    assert not fixture.is_symlink()
    shutil.rmtree(_io_path(fixture))


def test_exact_family_receipts_are_pinned_and_read_only_ready() -> None:
    for work_id in RECEIPT_HASHES:
        receipt, digest = pinned_receipt(work_id)
        assert _sha(receipt) == digest
        fixture, historical_receipt, _record = _fixture(work_id)
        try:
            assert preflight(historical_receipt)["status"] == "ready-for-review"
        finally:
            _cleanup(fixture)

def test_lacuna_fixture_failure_restores_work_and_source_sidecars() -> None:
    work_id = "vita-sancti-memmii"
    fixture, receipt, record = _fixture(work_id)
    try:
        assert preflight(receipt)["status"] == "ready-for-review"

        def interrupt(point: str) -> None:
            if point == "after-source-manifest.json-swap":
                raise RuntimeError("injected after source sidecar swaps")

        with pytest.raises(RuntimeError, match="injected"):
            install_transaction(receipt, fail_at=interrupt,
                                allowed_ids=frozenset({work_id}))
        assert _files(fixture / "library/works" / work_id) == record["before"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_before_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_before_sha256"]
        journals = list((fixture / "library/.sidecar-operations").glob("*/operation.json"))
        assert len(journals) == 1
        assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"
        assert preflight(receipt)["status"] == "ready-for-review"
    finally:
        _cleanup(fixture)

@pytest.mark.parametrize("work_id", ["passio-sancti-praeiecti", "vita-sancti-frodoberti"])
def test_multipart_and_mixed_prologue_fixture_install_checks_actual_master(work_id: str) -> None:
    fixture, receipt, record = _fixture(work_id)
    try:
        result = install_transaction(receipt, allowed_ids=frozenset({work_id}))
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
    fixture, receipt, record = _fixture("vita-sancti-memmii")
    try:
        record["canonical_root"] = ROOT.as_posix()
        receipt.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="canonical or staged work generation changed"):
            preflight(receipt)
    finally:
        _cleanup(fixture)
