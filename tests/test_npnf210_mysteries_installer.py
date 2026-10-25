"""Exercise the pinned Ambrose installer only in isolated fixture roots."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from build.tools import install_npnf210_mysteries_acceptance as route
from ocd_kernel.library._common import PipelineError
from tests.npnf210_mysteries_historical_fixture import mysteries_historical_root
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT = route.ROOT


@pytest.fixture(scope="module", autouse=True)
def historical_acquired_context(tmp_path_factory):
    before = _files(CURRENT_ROOT / route.WORK)
    root = mysteries_historical_root(route.STAGE, tmp_path_factory.mktemp("mysteries-before"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(route, "ROOT", root)
        yield
    assert _files(CURRENT_ROOT / route.WORK) == before


def test_current_installed_generation_rejects_original_initial_install():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(route, "ROOT", CURRENT_ROOT)
        with pytest.raises(PipelineError, match="preimage|generation"):
            route.preflight()


def _copy(source: Path, target: Path) -> None:
    _io_path(target).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_io_path(source), _io_path(target))


def _fixture(tmp_path: Path) -> Path:
    root = Path("\\\\?\\" + str(tmp_path / "root"))
    _io_path(root).mkdir(parents=True)
    (root / route.FIXTURE_MARKER).write_text("pinned Ambrose installer fixture\n", encoding="utf-8")
    stage_files = _files(route.STAGE)
    work_prefix = route.WORK.as_posix() + "/"
    for relative in stage_files:
        if relative != "stage-receipt.json" and not relative.startswith(work_prefix):
            _copy(route.STAGE / relative, root / relative)
    for relative in _files(route.ROOT / route.WORK):
        _copy(route.ROOT / route.WORK / relative, root / route.WORK / relative)
    return root


def _journal(root: Path) -> dict[str, object]:
    operations = list((root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    return json.loads((operations[0] / "operation.json").read_bytes())


def test_read_only_preflight_and_clean_fixture_install(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    before = _files(fixture / route.WORK)
    check = route.preflight(root_override=fixture)
    assert check["status"] == "pass-read-only" and check["canonical_action"] == "none"
    assert _files(fixture / route.WORK) == before
    result = route.install(root_override=fixture)
    assert result["status"] == "installed-and-validated" and result["projection_rows"] == 1
    assert _files(fixture / route.WORK) == check["after"]
    assert _journal(fixture)["phase"] == "complete"


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_swap_failure_restores_exact_before(tmp_path: Path, phase: str) -> None:
    fixture = _fixture(tmp_path)
    before = _files(fixture / route.WORK)

    def fail_at(current: str) -> None:
        if current == phase:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match=f"injected {phase}"):
        route.install(root_override=fixture, fail_at=fail_at)
    assert _files(fixture / route.WORK) == before
    assert _journal(fixture)["phase"] == "rolled-back"


def test_fixture_preimage_drift_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    work = fixture / route.WORK / "work.json"
    work.write_bytes(work.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="preimage|generation"):
        route.preflight(root_override=fixture)
