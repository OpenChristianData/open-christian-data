"""Focused frozen-pin and guarded transaction fixtures for four bsb830 works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime  # noqa: F401

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")

from build.tools import install_openmgh_bsb830_first_four as guarded
from build.tools.install_openmgh_bsb830_next import install as install_transaction
from build.tools.preflight_openmgh_bsb830_next import preflight
from ocd_kernel.library._common import PipelineError
from tests.openmgh_sidecar_historical_fixture import historical_mgh_sidecar_root
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def test_four_frozen_receipts_and_masters(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _sha(guarded.PINS) == guarded.PINS_SHA
    pins = json.loads(guarded.PINS.read_bytes())
    assert len(pins["entries"]) == 4
    assert {e["work_id"] for e in pins["entries"]} == guarded.IDS
    for item in pins["entries"]:
        receipt, digest = guarded.pinned_receipt(item["work_id"])
        record = json.loads(receipt.read_bytes())
        assert _sha(receipt) == digest == item["receipt_sha256"]
        assert record["accepted_master_sha256"] == item["accepted_master_sha256"]
        assert record["installation"] == "not-performed"
    monkeypatch.setattr(guarded, "PINS_SHA", "0" * 64)
    with pytest.raises(PipelineError, match="pin index changed"):
        guarded.pinned_receipt("question-on-the-sacraments-of-heretics")


def test_guarded_fixture_rollback_and_live_projection(tmp_path: Path) -> None:
    source_receipt, _digest = guarded.pinned_receipt(
        "question-on-the-sacraments-of-heretics"
    )
    record = json.loads(source_receipt.read_bytes())
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    fixture, _context_receipt, _context = historical_mgh_sidecar_root(
        ROOT, fixture, source_receipt, _sha(source_receipt),
    )
    work = Path("library/works") / record["work_id"]
    target = fixture / work
    record["canonical_root"] = fixture.as_posix()
    receipt = tmp_path / "fixture-receipt.json"
    receipt.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    pin = _sha(receipt)
    assert preflight(receipt)["status"] == "ready-for-review"

    before = _files(target)
    manifest = fixture / record["manifest_path"]
    profile = fixture / record["profile_path"]
    before_manifest, before_profile = _io_path(manifest).read_bytes(), _io_path(profile).read_bytes()

    def interrupt(point: str) -> None:
        if point == "after-source-manifest.json-swap":
            raise RuntimeError("injected after sidecar swap")

    with pytest.raises(RuntimeError, match="injected after sidecar swap"):
        install_transaction(
            receipt, allowed_ids=frozenset({record["work_id"]}), fail_at=interrupt,
            operation_prefix="bsb830-four-fixture", expected_receipt_sha256=pin,
        )
    assert _files(target) == before
    assert _io_path(manifest).read_bytes() == before_manifest
    assert _io_path(profile).read_bytes() == before_profile
    journals = list((fixture / "library/.sidecar-operations").glob("bsb830-four-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["phase"] == "rolled-back"

    result = install_transaction(
        receipt, allowed_ids=frozenset({record["work_id"]}),
        operation_prefix="bsb830-four-fixture", expected_receipt_sha256=pin,
    )
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(target) == record["after"]
    assert _sha(manifest) == record["source_manifest_after_sha256"]
    assert _sha(profile) == record["profile_after_sha256"]
