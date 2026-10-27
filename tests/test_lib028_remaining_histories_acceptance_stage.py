"""Focused exact-root and guarded-swap tests for remaining LIB-028 histories."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools import install_lib028_remaining_histories_acceptance as route
from build.tools.stage_lib028_remaining_histories_acceptance import _selected_candidate
from ocd_kernel.library._common import PipelineError
from tests.lib028_runtime_install_fixture import lib028_current_context
from ocd_kernel.reconstruction import CandidatePackage
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT = route.ROOT
ORIGINAL_STAGE_ROOT = route.STAGE_ROOT
ORIGINAL_RECEIPT_PINS = dict(route.RECEIPT_SHA)


@pytest.fixture(scope="module", autouse=True)
def current_runtime_historical_context():
    # The production override guard requires a marked external review-area root.
    review_area = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="l28-runtime-", dir=review_area) as temporary:
        area = Path(temporary)
        assert area.resolve().is_relative_to(review_area)
        before = {work_id: _files(CURRENT_ROOT / "library/works" / work_id) for work_id in route.ROUTES}
        root, stages, pins, manifest, candidate, oracle = lib028_current_context(route, area)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(route, "ROOT", root)
            patch.setattr(route, "STAGE_ROOT", stages)
            patch.setattr(route, "RECEIPT_SHA", pins)
            patch.setattr(route, "MANIFEST", manifest.path.relative_to(CURRENT_ROOT))
            patch.setattr(route, "MANIFEST_SHA", manifest.sha256)
            patch.setattr(route, "PACKAGE", candidate.path)
            patch.setattr(route, "PACKAGE_SHA", candidate.sha256)
            patch.setattr(route, "_oracle", oracle)
            yield
        assert all(_files(CURRENT_ROOT / "library/works" / work_id) == saved for work_id, saved in before.items())


@pytest.mark.parametrize("work_id", tuple(route.ROUTES))
def test_original_stage_rejects_managed_current_context(work_id):
    metadata = f"metadata/source-evidence/catalog/{work_id}.json"
    receipt_raw = (ORIGINAL_STAGE_ROOT / work_id / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    assert sha256(receipt_raw).hexdigest() == ORIGINAL_RECEIPT_PINS[work_id]
    assert sha256((CURRENT_ROOT / metadata).read_bytes()).hexdigest() != receipt["dependencies"][metadata]
    receipt_root = Path(receipt["canonical_root"]).resolve(strict=True)
    assert (CURRENT_ROOT / metadata).read_bytes() == (receipt_root / metadata).read_bytes()
    for context_root in dict.fromkeys((CURRENT_ROOT.resolve(), receipt_root)):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(route, "ROOT", context_root)
            patch.setattr(route, "STAGE_ROOT", ORIGINAL_STAGE_ROOT)
            patch.setattr(route, "RECEIPT_SHA", ORIGINAL_RECEIPT_PINS)
            error = (
                "LIB028 source or evidence changed: " + metadata
                if context_root == receipt_root else
                f"LIB028 {work_id} stage contract differs"
            )
            with pytest.raises(PipelineError, match="^" + re.escape(error) + "$"):
                route.preflight(work_id)


@pytest.mark.parametrize("work_id", tuple(route.ROUTES))
def test_frozen_selected_root_matches_source_crosswalk(work_id: str) -> None:
    stage = route.STAGE_ROOT / work_id
    receipt = json.loads(_io_path(stage / "stage-receipt.json").read_bytes())
    package = CandidatePackage.load(route.PACKAGE)
    candidate, node_sha = _selected_candidate(
        package.member_bytes("content.tei.xml"), work_id, route.ROUTES[work_id],
        json.loads(package.member_bytes("source-accountability.json")))
    assert node_sha == receipt["work"]["selected_tei_node_sha256"]
    assert route.ROUTES[work_id]["title"].encode() in candidate
    assert len(receipt["work"]["before"]) == 3
    assert len(receipt["work"]["after"]) == 21


def test_wrong_root_title_is_rejected() -> None:
    package = CandidatePackage.load(route.PACKAGE)
    work_id = "eusebius-ecclesiastical-history"
    wrong = dict(route.ROUTES[work_id], title="Invented Eusebius title")
    with pytest.raises(ValueError, match="selection differs"):
        _selected_candidate(package.member_bytes("content.tei.xml"), work_id, wrong,
                            json.loads(package.member_bytes("source-accountability.json")))


def test_guarded_fixture_rollback_then_install() -> None:
    work_id = "eusebius-ecclesiastical-history"
    work = Path("library/works") / work_id
    stage = route.STAGE_ROOT / work_id
    receipt = json.loads(_io_path(stage / "stage-receipt.json").read_bytes())
    fixture = Path(tempfile.mkdtemp(prefix="l28f-", dir=route.STAGE_ROOT.parent))
    try:
        _io_path(fixture / route.FIXTURE_MARKER).write_text("LIB-028 selected fixture\n", encoding="utf-8")
        for relative in receipt["work"]["before"]:
            destination = _io_path(fixture / work / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_io_path(route.ROOT / work / relative), destination)
        assert route.preflight(work_id, root_override=fixture)[0]["work"]["before"] == _files(fixture / work)

        def fail_at(phase: str) -> None:
            if phase == "after-new-rename":
                raise RuntimeError("fixture rollback checkpoint")

        with pytest.raises(RuntimeError, match="fixture rollback checkpoint"):
            route.install(work_id, root_override=fixture, fail_at=fail_at)
        assert _files(fixture / work) == receipt["work"]["before"]
        operations = list(_io_path(fixture / "library/.sidecar-operations").glob("l28-*/operation.json"))
        assert len(operations) == 1
        assert json.loads(operations[0].read_bytes())["phase"] == "rolled-back"
        result = route.install(work_id, root_override=fixture)
        assert result["status"] == "installed-and-validated"
        assert _files(fixture / work) == receipt["work"]["after"]
    finally:
        shutil.rmtree(_io_path(fixture))


def test_changed_receipt_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    work_id = "eusebius-ecclesiastical-history"
    monkeypatch.setitem(route.RECEIPT_SHA, work_id, "0" * 64)
    with pytest.raises(PipelineError, match="frozen receipt differs"):
        route.preflight(work_id)
