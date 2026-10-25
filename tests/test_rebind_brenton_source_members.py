from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil

import pytest

from build.tools import rebind_brenton_source_members as route
from ocd_kernel.library._common import (
    PipelineError,
    canonical_bytes,
    io_path,
    sha256_file,
)
from ocd_kernel.library.acquisitions import source_member_set_bytes, validate_acquisition


ROOT = Path(__file__).resolve().parents[1]


def _lexical_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    io_path(root).mkdir()
    shutil.copy2(io_path(ROOT / ".ocd-storage.json"), io_path(root / ".ocd-storage.json"))
    source = ROOT / route.WORK_REL
    destination = root / route.WORK_REL
    io_path(destination.parent).mkdir(parents=True)
    shutil.copytree(io_path(source), io_path(destination))
    for relative in (
        "plans/2026-09-22-source-preflight/five-bible-member-evidence-20260926.json",
        "sources/structured-text/brenton-septuagint/config.json",
        "plans/2026-09-23-acquisition-manifest-source-to-tei/evidence/"
        "L876_BRENTON_CURRENT_TECHNICAL_CLOSEOUT_20260930.json",
    ):
        target = root / relative
        io_path(target.parent).mkdir(parents=True, exist_ok=True)
        shutil.copy2(io_path(ROOT / relative), io_path(target))

    acquisition_path = root / route.ACQUISITION_REL
    acquisition = json.loads(io_path(acquisition_path).read_bytes())
    retained = sorted(copy.deepcopy(acquisition["retained_files"]), key=lambda item: item["path"])
    acquisition["retained_files"] = retained
    member_set = source_member_set_bytes(acquisition)
    acquisition["source_bytes"] = len(member_set)
    acquisition["source_sha256"] = route._sha_bytes(member_set)
    io_path(acquisition_path).write_bytes(canonical_bytes(acquisition))
    io_path(root / route.MEMBER_SET_REL).write_bytes(member_set)
    assert {
        relative: sha256_file(root / relative)
        for relative in route.EXPECTED_PREIMAGES
    } == route.EXPECTED_PREIMAGES
    return root


def test_stage_is_read_only_and_uses_registered_member_set_writer(tmp_path: Path) -> None:
    root = _lexical_fixture(tmp_path)
    before = route._tree(root / route.WORK_REL)
    stage = tmp_path / "stage"
    manifest = route.stage(root, stage)

    assert route._tree(root / route.WORK_REL) == before
    assert manifest["writer"] == {
        "identity": route.WRITER_IDENTITY,
        "implementation": "build/tools/rebind_brenton_source_members.py",
        "generated_member_set_writer": {
            "module": "ocd_kernel.library.acquisitions",
            "callable": "source_member_set_bytes",
            "contract": "ocd-retained-source-member-set-v1",
        },
    }
    proposed = json.loads(io_path(stage / route.ACQUISITION_REL).read_bytes())
    assert [route._member_order(item)[0] for item in proposed["retained_files"]] == sorted(
        route._member_order(item)[0] for item in proposed["retained_files"]
    )
    member_set = io_path(stage / route.MEMBER_SET_REL).read_bytes()
    assert member_set == source_member_set_bytes(proposed)
    descriptor = json.loads(member_set)
    assert [item["position"] for item in descriptor["members"]] == list(range(1, 61))
    assert proposed["source_bytes"] == len(member_set)
    assert proposed["source_sha256"] == route._sha_bytes(member_set)


def test_stage_rejects_changed_retained_member_binding(tmp_path: Path) -> None:
    root = _lexical_fixture(tmp_path)
    acquisition_path = root / route.ACQUISITION_REL
    acquisition = json.loads(io_path(acquisition_path).read_bytes())
    acquisition["retained_files"][0]["sha256"] = "0" * 64
    member_set = source_member_set_bytes(acquisition)
    acquisition["source_bytes"] = len(member_set)
    acquisition["source_sha256"] = route._sha_bytes(member_set)
    io_path(acquisition_path).write_bytes(canonical_bytes(acquisition))
    io_path(root / route.MEMBER_SET_REL).write_bytes(member_set)

    with pytest.raises(PipelineError, match="preimages differ"):
        route.stage(root, tmp_path / "stage")


def test_apply_changes_only_acquisition_pair_and_validates(tmp_path: Path) -> None:
    root = _lexical_fixture(tmp_path)
    before = route._tree(root / route.WORK_REL)
    stage = tmp_path / "stage"
    manifest = route.stage(root, stage)
    result = route.apply_staged(root, stage)

    after = route._tree(root / route.WORK_REL)
    assert after == manifest["after"]
    changed = {path for path in before | after if before.get(path) != after.get(path)}
    assert changed == {
        route.ACQUISITION_REL.relative_to(route.WORK_REL).as_posix(),
        route.MEMBER_SET_REL.relative_to(route.WORK_REL).as_posix(),
    }
    assert result["status"] == "installed-and-validated"
    validate_acquisition(root / route.ACQUISITION_REL, root=root)
    assert json.loads(io_path(Path(result["operation"]) / "operation.json").read_bytes())["phase"] == "complete"


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename", "after-validation"])
def test_apply_rolls_back_exact_preimage(tmp_path: Path, phase: str) -> None:
    root = _lexical_fixture(tmp_path)
    before = route._tree(root / route.WORK_REL)
    stage = tmp_path / "stage"
    route.stage(root, stage)

    def fail_at(reached: str) -> None:
        if reached == phase:
            raise PipelineError("injected Brenton rebind failure")

    with pytest.raises(PipelineError, match="injected Brenton rebind failure"):
        route.apply_staged(root, stage, fail_at=fail_at)
    assert route._tree(root / route.WORK_REL) == before
    journals = list((root / "library/.sidecar-operations").glob("brenton-source-rebind-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(io_path(journals[0]).read_bytes())["phase"] == "rolled-back"


def test_apply_rejects_stale_canonical_generation(tmp_path: Path) -> None:
    root = _lexical_fixture(tmp_path)
    stage = tmp_path / "stage"
    route.stage(root, stage)
    state = root / route.WORK_REL / "state.json"
    io_path(state).write_bytes(io_path(state).read_bytes() + b" ")

    with pytest.raises(PipelineError, match="stage manifest is stale or differs"):
        route.apply_staged(root, stage)
    assert not list((root / "library/.sidecar-operations").glob("brenton-source-rebind-*"))
