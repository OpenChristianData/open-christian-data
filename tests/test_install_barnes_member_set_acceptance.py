"""Focused Barnes extracted-source installation and rollback checks."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from build.tools import install_barnes_member_set_acceptance as install
from build.tools import prepare_barnes_member_set_acceptance as route
from ocd_kernel.library._common import PipelineError
from ocd_kernel.library.state import validate_state
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files


STAGE = Path("C:/Scratch/barnes-member-set-agent-acceptance-stage-20260926-v4")
PROMOTED = Path("C:/Scratch/barnes-member-set-agent-promoted-20260926-v2")


def _fixture(tmp_path: Path) -> Path:
    if not STAGE.is_dir() or not PROMOTED.is_dir():
        pytest.skip("exact Barnes stage and promoted fixture are unavailable")
    live = tmp_path / "live"
    shutil.copytree(PROMOTED, live)
    work = live / route.WORK
    if not work.resolve().is_relative_to(tmp_path.resolve()):
        raise AssertionError("test cleanup target escaped its scratch root")
    # Synthetic acquired baseline from the exact promoted tree, isolated under tmp_path.
    (work / install.MASTER).unlink()
    (work / install.ACCEPTANCE).unlink()
    evidence = work / install.EVIDENCE
    assert evidence.resolve().is_relative_to(work.resolve())
    shutil.rmtree(evidence)
    state_path = work / "state.json"
    state = json.loads(state_path.read_bytes())
    target = next(row for row in state["targets"] if row["target_id"] == route.IDENTITY["edition_id"])
    assert target["target_type"] == "edition" and target["stage"] == "accepted"
    target["stage"] = "acquired"
    target["reason"] = "Synthetic acquired baseline for guarded-install tests."
    excluded = {install.MASTER.as_posix(), install.ACCEPTANCE.as_posix()}
    prefix = install.EVIDENCE.as_posix() + "/"
    target["evidence"] = [
        reference for reference in target["evidence"]
        if reference.removeprefix(route.WORK.as_posix() + "/") not in excluded
        and not reference.removeprefix(route.WORK.as_posix() + "/").startswith(prefix)
    ]
    state_path.write_text(json.dumps(state), encoding="utf-8")
    validate_state(state_path, root=live)
    assert not (work / install.MASTER).exists()
    assert not (work / install.ACCEPTANCE).exists()
    return live


def test_barnes_install_preflight_rejects_work_and_source_drift(tmp_path: Path) -> None:
    live = _fixture(tmp_path)
    manifest = tmp_path / "install.json"
    install.prepare_manifest(live, PROMOTED, manifest)
    state = live / route.WORK / "state.json"
    original = state.read_bytes()
    state.write_bytes(original + b" ")
    with pytest.raises(PipelineError, match="stale"):
        install.preflight(manifest)
    state.write_bytes(original)
    source = live / "raw/sword_modules/Barnes/modules/comments/zcom/barnes/nt.czv"
    original = source.read_bytes()
    source.write_bytes(bytes((original[0] ^ 1,)) + original[1:])
    with pytest.raises(PipelineError, match="dependency differs"):
        install.preflight(manifest)


@pytest.mark.parametrize("checkpoint", ["after-old-rename", "after-new-rename"])
def test_barnes_install_rolls_back_both_swap_interruptions(tmp_path: Path, checkpoint: str) -> None:
    live = _fixture(tmp_path)
    manifest = tmp_path / "install.json"
    record = install.prepare_manifest(live, PROMOTED, manifest)

    def fail_at(name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(f"injected {checkpoint}")

    with pytest.raises(RuntimeError, match="injected"):
        install.install(manifest, fail_at=fail_at)
    assert _files(live / route.WORK) == record["before"]
    assert not (live / route.WORK / install.MASTER).exists()
    assert not (live / route.WORK / install.ACCEPTANCE).exists()


def test_barnes_install_retains_old_generation_and_validates_new_one(tmp_path: Path) -> None:
    live = _fixture(tmp_path)
    manifest = tmp_path / "install.json"
    record = install.prepare_manifest(live, PROMOTED, manifest)
    result = install.install(manifest)
    assert result["status"] == "installed-and-validated"
    assert _files(live / route.WORK) == record["after"]
    assert _files(Path(result["old_generation"])) == record["before"]
    acceptance = validate_acceptance(live / route.WORK / install.ACCEPTANCE, root=live)
    state = validate_state(live / route.WORK / "state.json", root=live)
    assert acceptance["promotion"]["status"] == "promoted"
    edition = next(item for item in state["targets"] if item["target_id"] == route.IDENTITY["edition_id"])
    assert "166 unrepresentable source bytes" in edition["reason"]


def test_current_accepted_generation_cannot_be_overwritten(tmp_path: Path) -> None:
    output = tmp_path / "install.json"
    before = _files(route.ROOT / route.WORK)
    with pytest.raises(PipelineError, match="canonical master or acceptance already exists"):
        install.prepare_manifest(route.ROOT, PROMOTED, output)
    assert _files(route.ROOT / route.WORK) == before
    assert not output.exists()
