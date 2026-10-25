"""Guarded held-work preflight and fixture-only install checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")

from build.tools import preflight_openmgh_bsb828_held as guard
from build.tools.install_openmgh_bsb828_held import install
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before


ROOT = Path(__file__).resolve().parents[1]
STAGES = Path("D:/Library/Open Christian Data/candidate-reviews/openmgh-bsb828-held-stages-20260926")
RECEIPTS = ROOT / "plans/2026-09-22-source-preflight"
PROSE = "manegold-to-gebhard"
POETRY = "hugo-verses-against-manegold"


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _write(path: Path, data: bytes) -> None:
    Path(_io_path(path)).write_bytes(data)


def _fixture(tmp_path: Path, work_id: str) -> tuple[Path, Path, dict]:
    root = tmp_path / "root"
    stage = tmp_path / "stage"
    shutil.copytree(_io_path(STAGES / work_id), _io_path(root))
    shutil.copytree(_io_path(STAGES / work_id), _io_path(stage))
    original_receipt = RECEIPTS / f"{work_id}-openmgh-bsb828-held-stage-20260926.json"
    record = json.loads(_bytes(original_receipt))
    work = Path("library/works") / work_id
    shutil.rmtree(_io_path(root / work))
    restore_mgh_journal_before(root, record)
    record["canonical_root"] = root.as_posix()
    record["stage_root"] = stage.as_posix()
    receipt = tmp_path / "fixture-stage-receipt.json"
    receipt.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
                       encoding="utf-8")
    return root, receipt, record


def test_preflight_rejects_stale_source_stage_tamper_and_receipt(tmp_path: Path) -> None:
    root, receipt, record = _fixture(tmp_path, PROSE)
    assert guard.preflight(receipt)["projection_rows"] == 1
    source = root / record["source_path"]
    prior = _bytes(source)
    _write(source, prior + b" ")
    with pytest.raises(Exception, match="source|sidecar"):
        guard.preflight(receipt)
    _write(source, prior)
    state = root / "library/works" / PROSE / "state.json"
    prior = _bytes(state)
    _write(state, prior + b" ")
    with pytest.raises(Exception, match="generation changed"):
        guard.preflight(receipt)
    _write(state, prior)
    stage_master = Path(record["stage_root"]) / "library/works" / PROSE / "forms" / f"{PROSE}-openmgh-retained" / "editions" / f"{PROSE}-openmgh-electronic" / "master.tei.xml"
    prior = _bytes(stage_master)
    try:
        _write(stage_master, prior + b" ")
        with pytest.raises(Exception, match="generation changed"):
            guard.preflight(receipt)
    finally:
        _write(stage_master, prior)
    with pytest.raises(Exception, match="exact reviewed stage receipt hash changed"):
        install(receipt, expected_receipt_sha256="0" * 64)


@pytest.mark.parametrize("work_id", [PROSE, POETRY])
def test_installer_rolls_back_then_projects_fixture_master(tmp_path: Path, work_id: str) -> None:
    root, receipt, record = _fixture(tmp_path, work_id)
    work = root / "library/works" / work_id
    before = _files(work)
    manifest = root / record["manifest_path"]
    profile = root / record["profile_path"]
    before_manifest, before_profile = _bytes(manifest), _bytes(profile)
    pin = sha256(_bytes(receipt)).hexdigest()

    def fail_after_manifest(phase: str) -> None:
        if phase == "after-source-manifest.json-swap":
            raise RuntimeError("injected manifest-swap failure")

    with pytest.raises(RuntimeError, match="injected manifest-swap failure"):
        install(receipt, expected_receipt_sha256=pin, fail_at=fail_after_manifest,
                operation_prefix=f"bsb828-held-{work_id}-fixture")
    assert _files(work) == before
    assert _bytes(manifest) == before_manifest
    assert _bytes(profile) == before_profile
    journals = list((root / "library/.sidecar-operations").glob(
        f"bsb828-held-{work_id}-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(_bytes(journals[0]))["phase"] == "rolled-back"

    result = install(receipt, expected_receipt_sha256=pin,
                     operation_prefix=f"bsb828-held-{work_id}-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(work) == record["after"]
    assert sha256(_bytes(manifest)).hexdigest() == record["source_manifest_after_sha256"]
    assert sha256(_bytes(profile)).hexdigest() == record["profile_after_sha256"]
