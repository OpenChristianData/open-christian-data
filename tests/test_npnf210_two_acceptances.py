"""Exercise only the pinned Holy Spirit and Virgins acceptance stages/installers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tools.install_npnf210_two_acceptances import FIXTURE_MARKER, LIBRARY, PINS, install, preflight
from build.tools.stage_npnf210_two_acceptances import CONFIG, ROOT
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files, _io_path


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
    receipt_path = _stage(work_id) / "stage-receipt.json"
    assert _sha(receipt_path) == PINS[work_id]["receipt"]
    receipt = json.loads(_io_path(receipt_path).read_bytes())
    expected_before = {}
    for relative, preimage in receipt["preimages"].items():
        target = _io_path(root / relative)
        if not preimage["exists"]:
            assert not target.exists()
            continue
        local = Path(relative).relative_to(work)
        label = local.name
        if local.as_posix() not in {"state.json", "work.json"}:
            assert "/acquisitions/" in local.as_posix() and local.suffix == ".json"
            label = "acquisition.json"
        origin = ROOT / "tests/fixtures/reconstruction-runtime/authorities" / f"npnf210-two-before-{work_id}.{label}"
        assert _sha(origin) == preimage["sha256"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_io_path(origin), target)
        expected_before[local.as_posix()] = preimage["sha256"]
    assert len(expected_before) == 3 and _files(root / work) == expected_before
    return root


@pytest.mark.parametrize("work_id", IDS)
def test_exact_stage_and_read_only_canonical_preflight(tmp_path: Path, work_id: str) -> None:
    root = _fixture(tmp_path, work_id)
    stage = _stage(work_id)
    receipt_path = stage / "stage-receipt.json"
    assert _sha(receipt_path) == PINS[work_id]["receipt"]
    receipt = json.loads(_io_path(receipt_path).read_bytes())
    assert receipt["status"] == "staged-only" and receipt["canonical_install"] is False
    for relative, preimage in receipt["preimages"].items():
        target = root / relative
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
    check = preflight(work_id, root_override=root)
    assert check["status"] == "pass-read-only" and check["canonical_action"] == "none"
    assert check["before_count"] == 3 and check["after_count"] == 35


def test_clean_fixture_install(tmp_path: Path) -> None:
    work_id = "ambrose-of-milan-on-holy-spirit"
    root = _fixture(tmp_path, work_id)
    check = preflight(work_id, root_override=root)
    result = install(work_id, root_override=root)
    assert result["status"] == "installed-and-validated"
    assert _files(root / "library/works" / work_id) == check["after"]
    journal = json.loads(_io_path(Path(result["operation"]) / "operation.json").read_bytes())
    assert journal["phase"] == "complete"


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_exact_virgins_preimage(tmp_path: Path, phase: str) -> None:
    work_id = "ambrose-of-milan-concerning-virgins"
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
    work_id = "ambrose-of-milan-on-holy-spirit"
    root = _fixture(tmp_path, work_id)
    target = _io_path(root / "library/works" / work_id / "work.json")
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="preimage"):
        preflight(work_id, root_override=root)


@pytest.mark.parametrize("work_id", IDS)
def test_current_accepted_generation_is_not_the_recorded_acquired_preimage(work_id: str) -> None:
    work = ROOT / "library/works" / work_id
    before = _files(work)
    with pytest.raises(PipelineError, match="preimage"):
        preflight(work_id)
    assert _files(work) == before
