"""Exercise only the pinned Satyrus title v3 acceptance stage/installer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tools.install_npnf210_satyrus_v3_acceptance import FIXTURE_MARKER, LIBRARY, PINS, install, preflight
from build.tools.stage_npnf210_satyrus_v3_acceptance import CONFIG, ROOT
from ocd_kernel.library._common import PipelineError
from tests.npnf210_historical_fixture import historical_ambrose_root
from build.tools import install_npnf210_satyrus_v3_acceptance as installer
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT = ROOT


@pytest.fixture(scope="module", autouse=True)
def historical_acquired_context(tmp_path_factory):
    root = historical_ambrose_root(tmp_path_factory.mktemp("ambrose-before"), installer.PINS)
    before = {work_id: _files(CURRENT_ROOT / "library/works" / work_id) for work_id in installer.PINS}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "ROOT", root)
        patch.setitem(globals(), "ROOT", root)
        yield root
    assert all(_files(CURRENT_ROOT / "library/works" / work_id) == saved for work_id, saved in before.items())


@pytest.mark.parametrize("work_id", tuple(sorted(installer.PINS)))
def test_current_installed_generation_rejects_historical_initial_install(work_id):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(installer, "ROOT", CURRENT_ROOT)
        with pytest.raises(PipelineError, match="preimage|undeclared|changed"):
            installer.preflight(work_id)


IDS = tuple(sorted(PINS))


def _sha(path: Path) -> str:
    return hashlib.sha256(_io_path(path).read_bytes()).hexdigest()


def _stage(work_id: str) -> Path:
    return LIBRARY / CONFIG[work_id]["stage_name"]


def _fixture(tmp_path: Path, work_id: str) -> Path:
    root = Path("\\\\?\\" + str(tmp_path / "repo"))
    _io_path(root).mkdir(parents=True)
    _io_path(root / FIXTURE_MARKER).write_text("isolated fixture\n", encoding="utf-8")
    work = Path("library/works") / work_id
    for relative in _files(_stage(work_id)):
        if relative == "stage-receipt.json" or relative.startswith(work.as_posix() + "/"):
            continue
        target = _io_path(root / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(_stage(work_id) / relative), target)
    for relative in _files(ROOT / work):
        target = _io_path(root / work / relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(ROOT / work / relative), target)
    return root


@pytest.mark.parametrize("work_id", IDS)
def test_exact_stage_and_read_only_canonical_preflight(work_id: str) -> None:
    stage = _stage(work_id)
    receipt_path = stage / "stage-receipt.json"
    assert _sha(receipt_path) == PINS[work_id]["receipt"]
    receipt = json.loads(_io_path(receipt_path).read_bytes())
    assert receipt["status"] == "staged-only" and receipt["canonical_install"] is False
    for relative, preimage in receipt["preimages"].items():
        target = ROOT / relative
        assert _io_path(target).is_file() == preimage["exists"]
        assert (_sha(target) if preimage["exists"] else None) == preimage["sha256"]
    for relative, digest in receipt["after"].items():
        assert _sha(stage / relative) == digest
    work = Path("library/works") / work_id
    form = json.loads(_io_path(stage / work / "work.json").read_bytes())["textual_forms"][0]
    edition = work / "forms" / form["textual_form_id"] / "editions" / form["editions"][0]["edition_id"]
    acceptance = stage / edition / "acceptance.json"
    validate_acceptance(_io_path(acceptance), root=_io_path(stage))
    validate_state(_io_path(stage / work / "state.json"), root=_io_path(stage))
    projection = project_accepted_prose(stage, acceptance_path=_io_path(acceptance))
    assert len(projection["rows"]) == 1 and projection["receipt"]["unsupported"] == []
    assert verify_accepted_prose(stage, acceptance_path=_io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"]) == []
    projection["rows"][0]["text"] += " invented"
    assert verify_accepted_prose(stage, acceptance_path=_io_path(acceptance), rows=projection["rows"], receipt=projection["receipt"])
    check = preflight(work_id)
    assert check["status"] == "pass-read-only" and check["canonical_action"] == "none"
    assert check["before_count"] == 3 and check["after_count"] == 32


def test_clean_fixture_install(tmp_path: Path) -> None:
    work_id = "ambrose-of-milan-on-satyrus"
    root = _fixture(tmp_path, work_id)
    check = preflight(work_id, root_override=root)
    result = install(work_id, root_override=root)
    assert result["status"] == "installed-and-validated"
    assert _files(root / "library/works" / work_id) == check["after"]
    journal = json.loads(_io_path(Path(result["operation"]) / "operation.json").read_bytes())
    assert journal["phase"] == "complete"


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_exact_satyrus_preimage(tmp_path: Path, phase: str) -> None:
    work_id = "ambrose-of-milan-on-satyrus"
    root = _fixture(tmp_path, work_id)
    before = preflight(work_id, root_override=root)["before"]

    def fail_at(point: str) -> None:
        if point == phase:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match="injected"):
        install(work_id, root_override=root, fail_at=fail_at)
    assert _files(root / "library/works" / work_id) == before
    operations = list(_io_path(root / "library/.sidecar-operations").glob("npnf210-*/operation.json"))
    assert len(operations) == 1
    assert json.loads(_io_path(operations[0]).read_bytes())["phase"] == "rolled-back"


def test_stale_fixture_preimage_rejected(tmp_path: Path) -> None:
    work_id = "ambrose-of-milan-on-satyrus"
    root = _fixture(tmp_path, work_id)
    target = _io_path(root / "library/works" / work_id / "work.json")
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="preimage"):
        preflight(work_id, root_override=root)
