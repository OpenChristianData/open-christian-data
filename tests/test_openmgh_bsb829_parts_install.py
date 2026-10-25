"""Focused guarded native-part preflight and fixture-only installation checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest
from tests.historical_python_report_fixture import frozen_python_report_runtime

pytestmark = pytest.mark.usefixtures("frozen_python_report_runtime")

from build.tools import prepare_openmgh_bsb829_parts as parts
from build.tools import preflight_openmgh_bsb829_parts as guard
from build.tools.install_openmgh_bsb829_parts import install
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.openmgh_journal_historical_fixture import restore_mgh_journal_before


ROOT = Path(__file__).resolve().parents[1]
STAGE = Path(r"C:\Scratch\b829p\p01b")
RECEIPT = Path(r"C:\Scratch\b829p\p01b-receipt.json")


def _bytes(path: Path) -> bytes:
    return Path(_io_path(path)).read_bytes()


def _write(path: Path, data: bytes) -> None:
    Path(_io_path(path)).write_bytes(data)


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "root"
    shutil.copytree(_io_path(STAGE), _io_path(root))
    record = json.loads(_bytes(RECEIPT))
    work = Path("library/works") / record["work_id"]
    shutil.rmtree(_io_path(root / work))
    restore_mgh_journal_before(root, record)
    record["canonical_root"] = root.as_posix()
    receipt = tmp_path / "fixture-stage-receipt.json"
    receipt.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
                       encoding="utf-8")
    return root, receipt, record


def test_parts_preflight_rejects_source_package_receipt_and_stale_work(tmp_path: Path) -> None:
    root, receipt, record = _fixture(tmp_path)
    assert guard.preflight(receipt)["projection_rows"] == 1
    source = root / parts.SOURCE
    original = _bytes(source)
    _write(source, original + b" ")
    with pytest.raises(Exception, match="retained XML|source sidecar|source"):
        guard.preflight(receipt)
    _write(source, original)
    package_copy = tmp_path / "package-receipt.json"
    package_copy.write_bytes(_bytes(Path(record["package_receipt"])) + b" ")
    altered = dict(record, package_receipt=package_copy.as_posix())
    receipt.write_text(json.dumps(altered, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(Exception, match="package receipt changed"):
        guard.preflight(receipt)
    receipt.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    work_state = root / "library/works" / record["work_id"] / "state.json"
    prior_state = _bytes(work_state)
    _write(work_state, prior_state + b" ")
    with pytest.raises(Exception, match="generation changed"):
        guard.preflight(receipt)


def test_parts_installer_rolls_back_then_installs_only_fixture(tmp_path: Path) -> None:
    root, receipt, record = _fixture(tmp_path)
    work = root / "library/works" / record["work_id"]
    before = _files(work)
    manifest = root / record["manifest_path"]
    profile = root / record["profile_path"]
    before_manifest = _bytes(manifest)
    before_profile = _bytes(profile)
    frozen_sha = sha256(_bytes(receipt)).hexdigest()
    with pytest.raises(Exception, match="exact reviewed stage receipt hash changed"):
        install(receipt, expected_receipt_sha256="0" * 64)

    def fail_after_profile(phase: str) -> None:
        if phase == "after-reconstruction-profile.json-swap":
            raise RuntimeError("injected profile-swap failure")

    with pytest.raises(RuntimeError, match="injected profile-swap failure"):
        install(receipt, expected_receipt_sha256=frozen_sha,
                fail_at=fail_after_profile, operation_prefix="bsb829-parts-test")
    assert _files(work) == before
    assert _bytes(manifest) == before_manifest
    assert _bytes(profile) == before_profile
    journals = list((root / "library/.sidecar-operations").glob("bsb829-parts-test-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["phase"] == "rolled-back"

    result = install(receipt, expected_receipt_sha256=frozen_sha,
                     operation_prefix="bsb829-parts-test")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(work) == record["after"]
    assert sha256(_bytes(manifest)).hexdigest() == record["source_manifest_after_sha256"]
    assert sha256(_bytes(profile)).hexdigest() == record["profile_after_sha256"]


def test_actual_current_generation_rejects_historical_before(tmp_path: Path) -> None:
    raw = Path(r"C:\Scratch\b829p\p01b-receipt.json").read_bytes()
    assert sha256(raw).hexdigest() == "3f03a1d6c9684095a4caa2e0f9cb907ebd330c03cc26762b87774d2a516ac3dd"
    original = json.loads(raw)
    changed = dict(original, canonical_root=ROOT.as_posix())
    assert dict(changed, canonical_root=original["canonical_root"]) == original
    receipt = tmp_path / "current-generation.json"
    receipt.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(Exception, match="work identity or generation changed"):
        guard.preflight(receipt)
