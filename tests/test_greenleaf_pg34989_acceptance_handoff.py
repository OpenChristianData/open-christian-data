"""Focused source and rollback checks for the external Greenleaf handoff."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from build.tools.install_greenleaf_pg34989_acceptance import _swap_work
from build.tools.preflight_greenleaf_pg34989_acceptance import preflight
from build.tools.stage_greenleaf_pg34989_acceptance import (
    ORIGINAL, ORIGINAL_SHA, ROOT, SOURCE, SOURCE_SHA, WORK_ID, read, source_oracle,
)
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.install_accepted import _files


def test_complete_source_walk_rejects_changed_text_attribute_and_glyph() -> None:
    source = read(ROOT / SOURCE, SOURCE_SHA)
    original = read(ROOT / ORIGINAL, ORIGINAL_SHA)
    assert source_oracle(source, original)["source_text_elements"] == 19441
    for old, new in ((b'<text xml:lang="en"', b'<text xml:lang="fr"'),
                     (b'<g ref="#U0x2014">', b'<g ref="#U0x2026">'),
                     (b'<anchor xml:id="Pg', b'<anchor xml:id="Px')):
        assert old in original
        with pytest.raises(PipelineError, match="differ"):
            source_oracle(source, original.replace(old, new, 1))


def test_preflight_requires_exact_receipt_pin(tmp_path: Path) -> None:
    receipt = tmp_path / "greenleaf-stage-receipt.json"
    receipt.write_text("{}\n", encoding="utf-8")
    with pytest.raises(PipelineError, match="exact reviewed"):
        preflight(receipt, expected_sha256="0" * 64)


@pytest.mark.parametrize("phase", ["after-copy", "after-old-rename", "after-new-rename", "after-validation"])
def test_work_swap_restores_old_generation_after_each_failure(tmp_path: Path, phase: str) -> None:
    target = tmp_path / "live"
    source = tmp_path / "staged"
    target.mkdir()
    source.mkdir()
    (target / "old.json").write_text("old\n", encoding="utf-8")
    (source / "new.json").write_text("new\n", encoding="utf-8")
    before, after = _files(target), _files(source)
    receipt = tmp_path / "reviewed-receipt.json"
    receipt.write_text("{}\n", encoding="utf-8")
    receipt_sha = sha256(receipt.read_bytes()).hexdigest()

    def fail_at(current: str) -> None:
        if current == phase:
            raise RuntimeError("injected failure")

    operation = tmp_path / "operation"
    with pytest.raises(RuntimeError, match="injected failure"):
        _swap_work(target, source, operation, before=before, after=after,
                   work_id=WORK_ID, stage_receipt=receipt, stage_receipt_sha256=receipt_sha,
                   validate=lambda: {"rows": 13}, fail_at=fail_at)
    assert _files(target) == before
    journal = json.loads((operation / "operation.json").read_text(encoding="utf-8"))
    assert journal["phase"] == ("failed-before-swap" if phase == "after-copy" else "rolled-back")
    assert journal["before"] == before and journal["after"] == after
    assert journal["work_id"] == WORK_ID
    assert journal["stage_receipt"] == receipt.as_posix()
    assert journal["stage_receipt_sha256"] == receipt_sha


def test_work_swap_keeps_old_generation_for_review(tmp_path: Path) -> None:
    target = tmp_path / "live"
    source = tmp_path / "staged"
    target.mkdir()
    source.mkdir()
    (target / "old.json").write_text("old\n", encoding="utf-8")
    (source / "new.json").write_text("new\n", encoding="utf-8")
    before, after = _files(target), _files(source)
    receipt = tmp_path / "reviewed-receipt.json"
    receipt.write_text("{}\n", encoding="utf-8")
    receipt_sha = sha256(receipt.read_bytes()).hexdigest()
    operation = tmp_path / "operation"
    result = _swap_work(target, source, operation, before=before, after=after,
                        work_id=WORK_ID, stage_receipt=receipt, stage_receipt_sha256=receipt_sha,
                        validate=lambda: {"rows": 13})
    assert result["status"] == "installed-and-validated"
    assert _files(target) == after
    assert _files(operation / "previous") == before
    journal = json.loads((operation / "operation.json").read_text(encoding="utf-8"))
    assert journal["phase"] == "complete"
    assert journal["work_id"] == WORK_ID
    assert journal["stage_receipt"] == receipt.as_posix()
    assert journal["stage_receipt_sha256"] == receipt_sha
