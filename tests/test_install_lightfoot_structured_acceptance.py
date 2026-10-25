"""Focused guarded Lightfoot handoff and rollback checks."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from build.tools import install_lightfoot_structured_acceptance as install
from build.tools import prepare_lightfoot_structured_acceptance as route
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files


STAGE = Path("C:/Scratch/lightfoot-structured-agent-stage-20260926-v3")
PROMOTED = Path("C:/Scratch/lightfoot-structured-promoted-20260926-v3")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    if not STAGE.is_dir() or not PROMOTED.is_dir():
        pytest.skip("exact retained Lightfoot stage and promotion are not on this host")
    live = tmp_path / "live"
    shutil.copytree(PROMOTED, live)
    acceptance = live / route.EDITION / "acceptance.json"
    assert validate_acceptance(acceptance, root=live)["promotion"]["status"] == "promoted"
    candidate = live / route.EVIDENCE / "candidate.tei.xml"
    original = candidate.read_bytes()
    try:
        candidate.write_bytes(original.replace(b"retained PG 50857", b"retained PG 50858", 1))
        with pytest.raises(PipelineError):
            validate_acceptance(acceptance, root=live)
    finally:
        candidate.write_bytes(original)
    work = live / route.WORK
    assert work.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(work)
    shutil.copytree(STAGE / route.WORK, work)
    evidence = live / route.EVIDENCE
    historical_acceptance = (evidence / "inputs/historical-acceptance.json").read_bytes()
    historical_master = (evidence / "inputs/historical-flat-master.tei.xml").read_bytes()
    assert evidence.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(evidence)
    (work / install.ACCEPTANCE).write_bytes(historical_acceptance)
    (work / install.MASTER).write_bytes(historical_master)
    return live, PROMOTED


@pytest.mark.parametrize("checkpoint", ["after-old-rename", "after-new-rename"])
def test_lightfoot_install_rolls_back_after_interrupted_swap(tmp_path: Path, checkpoint: str) -> None:
    live, promoted = _fixture(tmp_path)
    manifest = tmp_path / "install.json"
    record = install.prepare_manifest(live, promoted, manifest)
    assert install.preflight(manifest)[0]["before"] == record["before"]

    def fail_at(name: str) -> None:
        if name == checkpoint:
            raise RuntimeError(f"injected {checkpoint}")

    with pytest.raises(RuntimeError, match="injected"):
        install.install(manifest, fail_at=fail_at)
    assert _files(live / route.WORK) == record["before"]
    assert (live / route.EDITION / "acceptance.json").read_bytes() == (
        STAGE / route.EVIDENCE / "inputs/historical-acceptance.json"
    ).read_bytes()
    assert (live / route.EDITION / "master.tei.xml").read_bytes() == (
        STAGE / route.EVIDENCE / "inputs/historical-flat-master.tei.xml"
    ).read_bytes()


def test_lightfoot_install_rejects_stale_old_generation(tmp_path: Path) -> None:
    live, promoted = _fixture(tmp_path)
    manifest = tmp_path / "install.json"
    install.prepare_manifest(live, promoted, manifest)
    state = live / route.WORK / "state.json"
    state.write_bytes(state.read_bytes() + b" ")
    with pytest.raises(PipelineError, match="stale"):
        install.preflight(manifest)

def test_lightfoot_install_keeps_historical_generation_and_validates_new_one(tmp_path: Path) -> None:
    live, promoted = _fixture(tmp_path)
    manifest = tmp_path / "install.json"
    record = install.prepare_manifest(live, promoted, manifest)
    result = install.install(manifest)
    assert result["status"] == "installed-and-validated"
    assert _files(live / route.WORK) == record["after"]
    assert _files(Path(result["old_generation"])) == record["before"]
    accepted = validate_acceptance(live / route.EDITION / "acceptance.json", root=live)
    assert accepted["promotion"]["status"] == "promoted"
    assert accepted["review"]["coverage"]["unreviewed"] == [
        "complete-retained-electronic-witness/unsampled-source-text-outside-33-risk-loci"
    ]