"""Focused rehearsals for exact Gesta and flat-ab stage transactions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools.install_openmgh_bsb830_next import install as install_transaction
from build.tools.install_openmgh_gesta_flat_ab import PINS, pinned_receipt
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
    if record["category"] == "poetry":
        for verse_id in PINS:
            if verse_id == "gesta-domni-lantberti":
                continue
            relative = Path("sources/openmgh-exclusive") / verse_id / "boundary-review.json"
            target = _io_path(fixture / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_io_path(ROOT / relative), target)
    return result


def _cleanup(fixture: Path) -> None:
    assert fixture.resolve().is_relative_to(SCRATCH.resolve())
    assert not fixture.is_symlink()
    shutil.rmtree(_io_path(fixture))


@pytest.mark.parametrize("work_id", ["gesta-domni-lantberti",
                                      "exiled-monk-calamities-of-the-church-of-liege"])
def test_failure_after_source_swaps_restores_exact_authorities(work_id: str) -> None:
    fixture, receipt, record = _fixture(work_id)
    try:
        assert preflight(receipt)["status"] == "ready-for-review"

        def interrupt(point: str) -> None:
            if point == "after-source-manifest.json-swap":
                raise RuntimeError("injected after both source sidecars")

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

@pytest.mark.parametrize("work_id", sorted(PINS))
def test_fixture_install_checks_master_category_and_source_sidecars(work_id: str) -> None:
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
    fixture, receipt, record = _fixture("gesta-domni-lantberti")
    try:
        record["canonical_root"] = ROOT.as_posix()
        receipt.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        with pytest.raises(PipelineError, match="canonical or staged work generation changed"):
            preflight(receipt)
    finally:
        _cleanup(fixture)
