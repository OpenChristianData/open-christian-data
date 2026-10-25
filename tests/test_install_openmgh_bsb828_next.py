"""Isolated guarded transaction checks for the inspected bsb828 stage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools.install_openmgh_bsb830_next import install
from build.tools import install_openmgh_bsb828_next as guarded
from build.tools.preflight_openmgh_bsb830_next import preflight
from build.tools.stage_openmgh_inspected_acceptance import _files, _io_path
from ocd_kernel.library._common import PipelineError
from tests.openmgh_sidecar_historical_fixture import historical_mgh_sidecar_root


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path("C:/Scratch")
WORK_ID = "wido-monk-letter-to-archbishop-of-milan"
SOURCE_RECEIPT = (
    ROOT / "plans/2026-09-22-source-preflight/"
    "wido-monk-letter-openmgh-bsb828-stage-20260926.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _fixture() -> tuple[Path, Path, dict]:
    record = json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    fixture = Path(tempfile.mkdtemp(prefix="b82-", dir=SCRATCH))
    return historical_mgh_sidecar_root(
        ROOT, fixture, SOURCE_RECEIPT, guarded.RECEIPT_DIGESTS[WORK_ID],
    )


def test_exact_canonical_stage_pin_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _sha(SOURCE_RECEIPT) == guarded.RECEIPT_DIGESTS[WORK_ID]
    fixture, receipt, _record = _fixture()
    try:
        assert preflight(receipt)["status"] == "ready-for-review"
    finally:
        assert fixture.resolve().is_relative_to(SCRATCH.resolve())
        shutil.rmtree(_io_path(fixture))
    monkeypatch.setattr(guarded, "_sha", lambda _path: "0" * 64)
    with pytest.raises(PipelineError, match="exact reviewed receipt set"):
        guarded.run(SOURCE_RECEIPT)


def test_exact_828_preflight_tamper_rollback_and_install() -> None:
    fixture, receipt, record = _fixture()
    try:
        assert preflight(receipt)["projection_rows"] == 1
        changed = dict(record, original_inspection_receipt_sha256="0" * 64)
        tampered = fixture / "tampered-stage-receipt.json"
        tampered.write_text(json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="828 next stage is outside"):
            preflight(tampered)

        def interrupt(point: str) -> None:
            if point == "after-source-manifest.json-swap":
                raise RuntimeError("injected after both source-sidecar swaps")

        options = {
            "allowed_ids": frozenset({WORK_ID}),
            "journal_contract": "ocd-openmgh-bsb828-derived-acceptance-install-v1",
            "operation_prefix": "openmgh-bsb828",
            "expected_receipt_sha256": _sha(receipt),
        }
        with pytest.raises(RuntimeError, match="injected"):
            install(receipt, fail_at=interrupt, **options)
        work = fixture / "library/works" / WORK_ID
        assert _files(work) == record["before"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_before_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_before_sha256"]
        journals = list((fixture / "library/.sidecar-operations").glob("openmgh-bsb828-*/operation.json"))
        assert len(journals) == 1
        assert json.loads(journals[0].read_text(encoding="utf-8"))["phase"] == "rolled-back"
        assert preflight(receipt)["status"] == "ready-for-review"

        result = install(receipt, **options)
        assert result["status"] == "installed-and-validated"
        assert result["projection_rows"] == 1
        assert _files(work) == record["after"]
        assert _sha(fixture / record["manifest_path"]) == record["source_manifest_after_sha256"]
        assert _sha(fixture / record["profile_path"]) == record["profile_after_sha256"]
        journal = Path(result["operation"]) / "operation.json"
        assert json.loads(journal.read_text(encoding="utf-8"))["phase"] == "complete"
    finally:
        assert fixture.resolve().is_relative_to(SCRATCH.resolve())
        shutil.rmtree(_io_path(fixture))
