"""Prove the A47235 frozen-stage guard and marked-fixture rollback."""

from pathlib import Path
import json

import pytest

from build.tools.install_prayers_baths_for_cure_acceptance import (
    FIXTURE_MARKER,
    ROOT,
    WORK,
    STAGE,
    RECEIPT,
    install,
    preflight,
)
from ocd_kernel.tei.install_accepted import _files, _io_path
from ocd_kernel.library._common import PipelineError
from build.tools import install_prayers_baths_for_cure_acceptance as installer
from tests.guarded_installer_historical_fixture import historical_guarded_install_context


def _preimage() -> Path:
    original = ROOT / "tests/fixtures/guarded-install-before/baths"
    record = json.loads(_io_path(RECEIPT).read_bytes())
    assert _files(original) == record["before"]
    return original


def test_frozen_stage_read_only_preflight() -> None:
    frozen = json.loads(_io_path(RECEIPT).read_bytes())
    if Path(frozen["canonical_root"]).resolve(strict=True) != ROOT.resolve(strict=True):
        with pytest.raises(PipelineError, match="stage receipt contract or pins differ"):
            preflight()
        assert _files(STAGE / WORK) == frozen["after"]
        return
    if _files(ROOT / WORK) != frozen["before"]:
        # A completed installation is single-use: subsequent work evidence
        # additions also leave the frozen complete-generation receipt stale.
        with pytest.raises(PipelineError, match="complete-generation receipt is stale"):
            preflight()
        assert _files(STAGE / WORK) == frozen["after"]
        return
    record, root, stage, fixture = preflight()
    assert root == ROOT.resolve()
    assert not fixture
    assert record["projection_rows"] == 3
    assert record["source_sha256"] == "741b3c5faf5c90d1735563fc793fdc5cd7eebc9118d2707a731742f82f8e0117"
    assert len(_files(stage / WORK)) == 21
    assert _files(ROOT / WORK) == record["before"]


@pytest.mark.parametrize("failpoint", ["after-copy", "after-old-rename", "after-new-rename", "after-validation"])
def test_guarded_install_rolls_back_marked_fixture(tmp_path: Path, failpoint: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture_root = tmp_path / "fixture"
    fixture_root.mkdir()
    (fixture_root / FIXTURE_MARKER).write_text("test fixture\n", encoding="utf-8")
    root, receipt, digest = historical_guarded_install_context(
        installer, fixture_root, preserved_before=_preimage(),
    )
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "RECEIPT", receipt)
    monkeypatch.setattr(installer, "RECEIPT_SHA", digest)
    target = fixture_root / WORK
    before = _files(target)

    def fail(phase: str) -> None:
        if phase == failpoint:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match="injected"):
        install(fail_at=fail)
    assert _files(target) == before
