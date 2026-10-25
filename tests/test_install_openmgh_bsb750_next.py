"""Exact-pin and guarded fixture rehearsals for twelve bsb750 prose stages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import pytest

import build.tools.install_openmgh_bsb750_next as bsb750_installer
from build.tools.install_openmgh_bsb750_next import RECEIPT_HASHES, pinned_receipt
from build.tools.install_openmgh_bsb830_next import install as install_transaction
from build.tools.preflight_openmgh_bsb830_next import preflight
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path, _normalize_entry
from tests.openmgh_sidecar_historical_fixture import historical_mgh_sidecar_root
from ocd_kernel.library._common import PipelineError


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


def test_twelve_exact_receipts_pass_independent_preflight() -> None:
    for work_id in RECEIPT_HASHES:
        receipt, digest = pinned_receipt(work_id)
        assert _sha(receipt) == digest
        fixture, historical_receipt, _record = _fixture(work_id)
        try:
            assert preflight(historical_receipt)["status"] == "ready-for-review"
        finally:
            _cleanup(fixture)

def test_pinned_receipt_rejects_byte_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_id = "passio-sancti-memorii"
    source, _digest = pinned_receipt(work_id)
    copy = tmp_path / "plans/2026-09-22-source-preflight" / source.name
    copy.parent.mkdir(parents=True)
    copy.write_bytes(source.read_bytes() + b" ")
    monkeypatch.setattr(bsb750_installer, "ROOT", tmp_path)
    with pytest.raises(PipelineError, match="reviewed stage receipt hash changed"):
        pinned_receipt(work_id)

def test_legacy_receipt_alias_disagreement_fails_closed() -> None:
    batch = json.loads((ROOT / "plans/2026-09-22-source-preflight/"
                        "openmgh-bsb00000750-child-batch-20260926.json").read_bytes())
    item = dict(batch["works"][0])
    assert _normalize_entry(batch, item)["candidate_sha256"] == item["candidate_digest"]
    item["candidate_manifest_sha256"] = "0" * 64
    with pytest.raises(PipelineError, match="aliases disagree"):
        _normalize_entry(batch, item)

def test_memorii_lacuna_fixture_rollback_restores_exact_authorities() -> None:
    work_id = "passio-sancti-memorii"
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

@pytest.mark.parametrize("work_id", ["vita-sancti-dalmatii", "vita-sancti-melanii"])
def test_multipart_and_column_fixture_installs_check_actual_master(work_id: str) -> None:
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
    fixture, receipt, record = _fixture("passio-sancti-memorii")
    try:
        record["canonical_root"] = ROOT.as_posix()
        receipt.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="canonical or staged work generation changed"):
            preflight(receipt)
    finally:
        _cleanup(fixture)
