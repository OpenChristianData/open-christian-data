"""Exact-pin, tamper, rollback, and completion checks for bsb829 staging."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools import install_openmgh_bsb829_next as guarded
from build.tools import preflight_openmgh_bsb829_next as source_guard
from build.tools import install_openmgh_bsb830_next as journaled
from build.tools.preflight_openmgh_bsb829_next import preflight
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library._common import PipelineError
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("C:/Scratch")
WORK_ID = "altercatio-between-urban-and-clement"
RECEIPT = ROOT / "plans/2026-09-22-source-preflight/altercatio-between-urban-and-clement-openmgh-bsb829-stage-20260926.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _fixture() -> tuple[Path, Path, dict]:
    record = json.loads(RECEIPT.read_text(encoding="utf-8"))
    fixture = Path(tempfile.mkdtemp(prefix="b29-", dir=SCRATCH))
    shutil.copytree(_io_path(Path(record["stage_root"])), _io_path(fixture), dirs_exist_ok=True)
    work = Path("library/works") / WORK_ID
    shutil.rmtree(_io_path(fixture / work))
    restore_mgh_journal_before(fixture, record)
    inspection = Path(record["original_inspection_receipt"])
    assert inspection == source_guard.BATCH
    payload = (ROOT / inspection).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == record["original_inspection_receipt_sha256"] == source_guard.BATCH_SHA
    target = _io_path(fixture / inspection)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists() or target.read_bytes() == payload
    target.write_bytes(payload)
    assert _sha(target) == source_guard.BATCH_SHA
    record["canonical_root"] = fixture.as_posix()
    receipt = fixture / "fixture-stage-receipt.json"
    receipt.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return fixture, receipt, record


def test_exact_receipt_pin_and_tamper(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _sha(guarded.PINS) == guarded.PINS_SHA
    frozen = json.loads(guarded.PINS.read_bytes())
    assert _sha(RECEIPT) == frozen["stage_receipts"][WORK_ID]
    fixture, receipt, _record = _fixture()
    try:
        assert preflight(receipt)["status"] == "ready-for-review"
    finally:
        assert fixture.resolve().is_relative_to(SCRATCH.resolve())
        shutil.rmtree(_io_path(fixture))
    original = guarded._sha
    monkeypatch.setattr(guarded, "_sha", lambda path: "0" * 64 if path == RECEIPT else original(path))
    with pytest.raises(PipelineError, match="exact reviewed receipt set"):
        guarded.run(RECEIPT)


def test_fixture_tamper_rollback_then_install(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, receipt, record = _fixture()
    try:
        assert preflight(receipt)["projection_rows"] == 1
        source = fixture / record["source_path"]
        original_source = _io_path(source).read_bytes()
        _io_path(source).write_bytes(original_source + b" ")
        with pytest.raises(PipelineError, match="pinned extracted XML"):
            preflight(receipt)
        _io_path(source).write_bytes(original_source)
        changed = dict(record, source_sha256="0" * 64)
        tampered = fixture / "tampered-stage-receipt.json"
        tampered.write_text(json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="pinned extracted XML"):
            preflight(tampered)

        def interrupt(point: str) -> None:
            if point == "after-source-manifest.json-swap":
                raise RuntimeError("injected after source-sidecar swaps")

        monkeypatch.setattr(journaled, "receipt_preflight", preflight)
        options = {
            "allowed_ids": frozenset({WORK_ID}),
            "journal_contract": "ocd-openmgh-bsb829-acceptance-install-v1",
            "operation_prefix": "openmgh-bsb829",
            "expected_receipt_sha256": _sha(receipt),
        }
        with pytest.raises(RuntimeError, match="injected"):
            journaled.install(receipt, fail_at=interrupt, **options)
        assert _files(fixture / "library/works" / WORK_ID) == record["before"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_before_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_before_sha256"]
        journals = list((fixture / "library/.sidecar-operations").glob("openmgh-bsb829-*/operation.json"))
        assert len(journals) == 1
        assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"
        assert preflight(receipt)["status"] == "ready-for-review"

        result = journaled.install(receipt, **options)
        assert result["status"] == "installed-and-validated"
        assert result["projection_rows"] == 1
        assert _files(fixture / "library/works" / WORK_ID) == record["after"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_after_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_after_sha256"]
        journal = Path(result["operation"]) / "operation.json"
        assert json.loads(journal.read_text(encoding="utf-8"))["phase"] == "complete"
    finally:
        assert fixture.resolve().is_relative_to(SCRATCH.resolve())
        shutil.rmtree(_io_path(fixture))
