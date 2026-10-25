"""Guard the noncanonical LIB-044 On the Mysteries acceptance stage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from build.tools.stage_npnf210_mysteries_acceptance import EDITION, ROOT, SOURCE, WORK
from ocd_kernel.library._common import PipelineError
from tests.npnf210_mysteries_historical_fixture import mysteries_historical_root
from ocd_kernel.library.state import validate_state
from ocd_kernel.projection.categories.prose import project_accepted_prose, verify_accepted_prose
from ocd_kernel.tei.acceptance import validate_acceptance
from ocd_kernel.tei.install_accepted import _files


STAGE = Path("\\\\?\\D:\\Library\\Open Christian Data\\am26-mysteries-v5")
ACCEPTANCE = EDITION / "acceptance.json"
MASTER = EDITION / "master.tei.xml"


CURRENT_ROOT = ROOT


@pytest.fixture(scope="module", autouse=True)
def historical_acquired_context(tmp_path_factory):
    before = _files(CURRENT_ROOT / WORK)
    root = mysteries_historical_root(STAGE, tmp_path_factory.mktemp("mysteries-stage-before"))
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(globals(), "ROOT", root)
        yield
    assert _files(CURRENT_ROOT / WORK) == before


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def test_exact_stage_public_acceptance_and_projection() -> None:
    receipt = json.loads((STAGE / "stage-receipt.json").read_bytes())
    assert receipt["status"] == "staged-only" and receipt["canonical_install"] is False
    for relative, preimage in receipt["preimages"].items():
        path = ROOT / relative
        assert path.is_file() == preimage["exists"]
        assert (_sha(path.read_bytes()) if path.is_file() else None) == preimage["sha256"]
    for relative, digest in receipt["after"].items():
        assert _sha((STAGE / relative).read_bytes()) == digest
    validate_acceptance(STAGE / ACCEPTANCE, root=STAGE)
    validate_state(STAGE / WORK / "state.json", root=STAGE)
    result = project_accepted_prose(STAGE, acceptance_path=STAGE / ACCEPTANCE)
    assert len(result["rows"]) == 1 and result["receipt"]["unsupported"] == []
    assert verify_accepted_prose(STAGE, acceptance_path=STAGE / ACCEPTANCE, rows=result["rows"], receipt=result["receipt"]) == []
    result["rows"][0]["text"] += " invented"
    assert verify_accepted_prose(STAGE, acceptance_path=STAGE / ACCEPTANCE, rows=result["rows"], receipt=result["receipt"])


def test_acceptance_rejects_changed_source_and_master(tmp_path: Path) -> None:
    fixture = Path("\\\\?\\" + str(tmp_path / "stage"))
    shutil.copytree(STAGE, fixture)
    source = fixture / SOURCE
    original_source = source.read_bytes()
    source.write_bytes(original_source + b"\n")
    with pytest.raises(PipelineError, match="retained file bytes mismatch"):
        validate_acceptance(fixture / ACCEPTANCE, root=fixture)
    source.write_bytes(original_source)
    master = fixture / MASTER
    master.write_bytes(master.read_bytes() + b"\n")
    with pytest.raises(PipelineError, match="sha256 mismatch|master"):
        validate_acceptance(fixture / ACCEPTANCE, root=fixture)
