"""Guarded Bounds Power whole-work swap and rollback on isolated fixtures."""

import json
from pathlib import Path
import shutil

import pytest

from build.tools.install_lib031_bounds_power_acceptance import (
    RECEIPT_SHA256, STAGE, WORK, install,
)
from build.tools.preflight_lib031_bounds_power_acceptance import FIXTURE_MARKER, ROOT, preflight
from ocd_kernel.tei.install_accepted import _files, _io_path
from tests.frozen_install_preimages import copy_recorded_preimage


@pytest.fixture
def bounds_root(tmp_path: Path) -> Path:
    root = tmp_path / "bounds-fixture"
    root.mkdir()
    (root / FIXTURE_MARKER).write_text("isolated test fixture\n", encoding="utf-8")
    staged = _files(STAGE)
    prefix = WORK.as_posix() + "/"
    for relative in staged:
        if relative == "stage-receipt.json" or relative.startswith(prefix):
            continue
        destination = _io_path(root / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(STAGE / relative), destination)
    copy_recorded_preimage(STAGE, WORK, RECEIPT_SHA256, root)
    assert preflight(STAGE, RECEIPT_SHA256, root_override=root)["status"] == "pass-read-only"
    return root


def _operation(root: Path) -> tuple[Path, dict]:
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    operation = operations[0]
    return operation, json.loads((operation / "operation.json").read_text(encoding="utf-8"))


def test_clean_fixture_install_retains_previous_and_checks_actual_prose(bounds_root: Path) -> None:
    before = _files(bounds_root / WORK)
    after = _files(STAGE / WORK)
    result = install(root_override=bounds_root)
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 1
    assert _files(bounds_root / WORK) == after
    operation, journal = _operation(bounds_root)
    assert journal["phase"] == "complete"
    assert journal["receipt_sha256"] == RECEIPT_SHA256
    assert _files(operation / "previous") == before


@pytest.mark.parametrize("phase", ["after-copy", "after-old-rename", "after-new-rename", "after-postcheck"])
def test_injected_failure_restores_exact_prior_generation(bounds_root: Path, phase: str) -> None:
    before = _files(bounds_root / WORK)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise RuntimeError("injected " + phase)

    with pytest.raises(RuntimeError, match="injected " + phase):
        install(root_override=bounds_root, fail_at=fail_at)
    assert _files(bounds_root / WORK) == before
    operation, journal = _operation(bounds_root)
    assert journal["phase"] == ("failed-before-swap" if phase == "after-copy" else "rolled-back")
    assert journal["before"] == before
    if phase in {"after-new-rename", "after-postcheck"}:
        assert _files(operation / "failed-new") == _files(STAGE / WORK)
    else:
        assert not (operation / "failed-new").exists()
    assert preflight(STAGE, RECEIPT_SHA256, root_override=bounds_root)["status"] == "pass-read-only"
