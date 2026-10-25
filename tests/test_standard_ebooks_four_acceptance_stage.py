"""Focused frozen-stage invariants for four Standard Ebooks electronic works."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools import install_standard_ebooks_four_acceptance as installer
from build.tools.stage_standard_ebooks_four_acceptance import CASES, ROOT, _read, _spine
from ocd_kernel.library._common import PipelineError
from tests.se_four_runtime_install_fixture import orthodoxy_runtime_context
from ocd_kernel.tei.install_accepted import _files, _io_path


@pytest.mark.parametrize("work_id", list(CASES))
def test_frozen_spine_and_text_preservation(work_id: str) -> None:
    source_name, short, count = CASES[work_id]
    stage = installer.STAGES[work_id]
    receipt = json.loads(_io_path(stage / "stage-receipt.json").read_bytes())
    assert receipt["work"]["opf_spine_count"] == count
    assert receipt["work"]["native_rows"] == count
    work = _io_path(stage / "library/works" / work_id)
    acceptance = next(work.rglob("acceptance.json"))
    master = next(work.rglob("master.tei.xml"))
    acquisition = next(work.rglob(f"acquisitions/{work_id}-retained-source-set.json"))
    source = json.loads(acquisition.read_bytes())
    assert [item["path"] for item in source["retained_files"]] == _spine(f"raw/standard_ebooks/{source_name}")
    accepted = json.loads(acceptance.read_bytes())
    assert len(accepted["scope"]["included_members"]) == count
    original = _read(installer.BASE / f"{short}-current-20260928-v1/package/content.tei.xml")
    derived = master.read_bytes()
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert b'<note type="source-credit">Standard Ebooks electronic edition</note>' in derived


def test_guard_rejects_unlisted_work() -> None:
    with pytest.raises(PipelineError, match="unlisted"):
        installer.preflight("unlisted-standard-ebook")


def test_guard_rejects_wrong_frozen_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(installer.RECEIPT_SHA, "orthodoxy", "0" * 64)
    with pytest.raises(PipelineError, match="receipt changed"):
        installer.preflight("orthodoxy")


@pytest.fixture
def orthodoxy_current_runtime(monkeypatch):
    current_root = installer.ROOT
    current_stage = installer.STAGES["orthodoxy"]
    current_pin = installer.RECEIPT_SHA["orthodoxy"]
    before = _files(current_root / "library/works/orthodoxy")
    review_area = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="se4-current-", dir=review_area) as temporary:
        area = Path(temporary)
        assert area.resolve().is_relative_to(review_area)
        root, stage, base, pin, oracle = orthodoxy_runtime_context(installer, area)
        monkeypatch.setattr(installer, "ROOT", root)
        monkeypatch.setitem(globals(), "ROOT", root)
        monkeypatch.setitem(installer.STAGES, "orthodoxy", stage)
        monkeypatch.setitem(installer.RECEIPT_SHA, "orthodoxy", pin)
        monkeypatch.setattr(installer, "BASE", base)
        monkeypatch.setattr(installer, "_oracle", oracle)
        yield root
    assert _files(current_root / "library/works/orthodoxy") == before
    assert current_stage != stage and current_pin != pin


def test_original_stage_rejects_managed_root_identity():
    with pytest.raises(PipelineError, match="stage contract or roots differ|work generation changed"):
        installer.preflight("orthodoxy")


def test_guarded_fixture_install_preserves_exact_generation(orthodoxy_current_runtime) -> None:
    work_id = "orthodoxy"
    stage = installer.STAGES[work_id]
    receipt = json.loads(_io_path(stage / "stage-receipt.json").read_bytes())
    with tempfile.TemporaryDirectory(prefix="se4f-", dir=installer.BASE.parent) as temporary:
        fixture = Path(temporary)
        (fixture / installer.FIXTURE_MARKER).write_text("source-bound fixture\n", encoding="utf-8")
        for relative in receipt["dependencies"]:
            target = _io_path(fixture / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_io_path(ROOT / relative), target)
        work_rel = Path(receipt["work"]["work_path"])
        for relative in receipt["work"]["before"]:
            target = _io_path(fixture / work_rel / relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_io_path(ROOT / work_rel / relative), target)
        assert installer.preflight(work_id, root_override=fixture)["status"] == "ready-for-review"
        def abort_after_swap(phase: str) -> None:
            if phase == "after-new-rename":
                raise RuntimeError("fixture rollback checkpoint")

        with pytest.raises(RuntimeError, match="fixture rollback checkpoint"):
            installer.install(work_id, root_override=fixture, fail_at=abort_after_swap)
        assert _files(fixture / work_rel) == receipt["work"]["before"]
        operations = list(_io_path(fixture / "library/.sidecar-operations").glob("se4-orthodoxy-*/operation.json"))
        assert len(operations) == 1
        assert json.loads(operations[0].read_bytes())["phase"] == "rolled-back"
        result = installer.install(work_id, root_override=fixture)
        assert result["status"] == "installed-and-validated"
        assert _files(fixture / work_rel) == receipt["work"]["after"]
