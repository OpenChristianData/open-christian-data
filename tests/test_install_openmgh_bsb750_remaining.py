"""Guarded remaining-bsb750 acceptance fixtures; never alter canonical works."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime  # noqa: F401

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")

from build.tools import install_openmgh_bsb830_next as transaction
from build.tools.install_openmgh_bsb750_remaining import (
    PIN_INDEX, PIN_INDEX_SHA, pinned_receipt, preflight_receipt,
)
from build.tools.stage_openmgh_bsb750_remaining import BATCH, CLAUSES, ROOT, SOURCE, receipt_path
from build.tools.stage_openmgh_inspected_acceptance import _files
from ocd_kernel.library._common import PipelineError
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before
from ocd_kernel.tei.install_accepted import _io_path


WORK_ID = "vita-sancti-betharii"


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _copy(source: Path, target: Path) -> None:
    target = _io_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), target)


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    original = json.loads(_io_path(receipt_path(WORK_ID)).read_bytes())
    root = tmp_path / "r"
    stage = Path(original["stage_root"])
    work = Path("library/works") / WORK_ID
    manifest = json.loads(_io_path(stage / original["manifest_path"]).read_bytes())
    policy = json.loads(_io_path(stage / "sources/openmgh-exclusive/validation-policy.json").read_bytes())
    dependencies = {BATCH, SOURCE, SOURCE.parent.parent / "acquisition-receipt.json",
                    SOURCE.parent.parent / "bsb00000750.zip",
                    Path(original["manifest_path"]), Path(original["profile_path"]),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd"),
                    Path("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd")}
    dependencies.update(Path(item["path"]) for item in manifest["authorities"])
    dependencies.update(Path(manifest[key]["implementation_path"])
                        for key in ("converter", "validator"))
    dependencies.add(Path(manifest["package_schema"]["path"]))
    dependencies.update(Path(path) for path in policy["closure_inputs"])
    for relative in sorted(dependencies):
        if relative.is_relative_to(work):
            continue
        source = ROOT if relative.as_posix() in {
            original["manifest_path"], original["profile_path"], BATCH.as_posix()} else stage
        _copy(source / relative, root / relative)
    restore_mgh_journal_before(root, original)
    amended = {**original, "canonical_root": root.as_posix()}
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(amended, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return root, receipt, original


def test_exact_pins_and_representative_native_preflight(tmp_path: Path) -> None:
    assert _sha(PIN_INDEX) == PIN_INDEX_SHA
    pins = json.loads(PIN_INDEX.read_bytes())
    assert set(pins["works"]) == set(CLAUSES)
    for work_id in CLAUSES:
        receipt, digest = pinned_receipt(work_id)
        assert _sha(receipt) == digest
    _root, receipt, _original = _fixture(tmp_path)
    result = preflight_receipt(receipt)
    assert result["status"] == "ready-for-review"
    assert result["projection_rows"] == 1


def test_stale_tampered_and_journaled_rollback_fixture(tmp_path: Path, monkeypatch) -> None:
    root, receipt, original = _fixture(tmp_path)
    work = Path("library/works") / WORK_ID
    before = _files(root / work)
    profile = Path(original["profile_path"])
    manifest = Path(original["manifest_path"])
    prior = (_sha(root / profile), _sha(root / manifest))
    assert preflight_receipt(receipt)["status"] == "ready-for-review"

    work_json = root / work / "work.json"
    old = _io_path(work_json).read_bytes()
    _io_path(work_json).write_bytes(old + b" ")
    with pytest.raises(PipelineError, match="before or staged after"):
        preflight_receipt(receipt)
    _io_path(work_json).write_bytes(old)

    record = json.loads(receipt.read_bytes())
    record["accepted_master_sha256"] = "0" * 64
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="accepted master differs"):
        preflight_receipt(tampered)

    monkeypatch.setattr(transaction, "receipt_preflight", preflight_receipt)
    digest = _sha(receipt)

    def fail_at(phase: str) -> None:
        if phase == "after-source-manifest.json-swap":
            raise RuntimeError("injected after both source-sidecar swaps")

    with pytest.raises(RuntimeError, match="injected"):
        transaction.install(receipt, allowed_ids=frozenset({WORK_ID}),
                            journal_contract="ocd-openmgh-bsb750-remaining-fixture-v1",
                            operation_prefix="bsb750-fixture", expected_receipt_sha256=digest,
                            fail_at=fail_at)
    assert _files(root / work) == before
    assert (_sha(root / profile), _sha(root / manifest)) == prior
    operations = list((root / "library/.sidecar-operations").glob("bsb750-fixture-*/operation.json"))
    assert len(operations) == 1
    assert json.loads(operations[0].read_bytes())["phase"] == "rolled-back"
    assert preflight_receipt(receipt)["status"] == "ready-for-review"

    installed = transaction.install(receipt, allowed_ids=frozenset({WORK_ID}),
                                    journal_contract="ocd-openmgh-bsb750-remaining-fixture-v1",
                                    operation_prefix="bsb750-fixture", expected_receipt_sha256=digest)
    assert installed["status"] == "installed-and-validated"
    assert installed["projection_rows"] == 1
    assert json.loads((Path(installed["operation"]) / "operation.json").read_bytes())["phase"] == "complete"
