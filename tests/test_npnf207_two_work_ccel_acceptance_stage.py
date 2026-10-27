"""Exercise only the pinned NPNF2-07 selected-work stages and guarded swap."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile
from hashlib import sha256

import pytest

from build.tools import install_npnf207_two_work_ccel_acceptance as route
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction import CandidatePackage
from tests.npnf207_pair_runtime_fixture import npnf207_pair_context
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT = route.ROOT
ORIGINAL_STAGE_ROOT = route.STAGE_ROOT
ORIGINAL_PINS = dict(route.RECEIPT_SHA)


@pytest.fixture(scope="module", autouse=True)
def current_runtime_historical_context():
    review_area = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="n207-current-", dir=review_area) as temporary:
        area = Path(temporary)
        assert area.resolve().is_relative_to(review_area)
        before = {work_id: _files(CURRENT_ROOT / "library/works" / work_id) for work_id in route.ROUTES}
        root, stages, pins, routes, replacements, oracle = npnf207_pair_context(route, area)
        real_load = CandidatePackage.load

        def current_package(cls, path):
            selected = replacements.get(Path(path).resolve())
            if selected is not None:
                candidate, old_sha = selected
                assert sha256(_io_path(Path(path) / "manifest.json").read_bytes()).hexdigest() == old_sha
                return real_load(candidate.path)
            return real_load(path)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(route, "ROOT", root)
            patch.setattr(route, "STAGE_ROOT", stages)
            patch.setattr(route, "RECEIPT_SHA", pins)
            patch.setattr(route, "ROUTES", routes)
            patch.setattr(route, "_oracle", oracle)
            patch.setattr(CandidatePackage, "load", classmethod(current_package))
            yield
        assert all(_files(CURRENT_ROOT / "library/works" / work_id) == saved for work_id, saved in before.items())


@pytest.mark.parametrize("work_id", tuple(route.ROUTES))
def test_original_stage_rejects_managed_current_root(work_id):
    metadata = f"metadata/source-evidence/catalog/{work_id}.json"
    receipt_raw = (ORIGINAL_STAGE_ROOT / work_id / "stage-receipt.json").read_bytes()
    receipt = json.loads(receipt_raw)
    assert sha256(receipt_raw).hexdigest() == ORIGINAL_PINS[work_id]
    managed_root = Path(receipt["canonical_root"]).resolve(strict=True)
    assert sha256((managed_root / metadata).read_bytes()).hexdigest() != receipt["dependencies"][metadata]
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(route, "ROOT", managed_root)
        patch.setattr(route, "STAGE_ROOT", ORIGINAL_STAGE_ROOT)
        patch.setattr(route, "RECEIPT_SHA", ORIGINAL_PINS)
        with pytest.raises(PipelineError, match=re.escape("NPNF207 source or evidence changed: " + metadata) + "$"):
            route.preflight(work_id)


def _fixture(tmp_path: Path, work_id: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="fixture-" + tmp_path.name + "-", dir=route.STAGE_ROOT.parent))
    _io_path(root / route.FIXTURE_MARKER).write_text(
        "NPNF2-07 selected-work installer fixture\n", encoding="utf-8")
    work = Path("library/works") / work_id
    for relative in _files(route.ROOT / work):
        origin = _io_path(route.ROOT / work / relative)
        destination = _io_path(root / work / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    return root


def _journal(root: Path) -> dict:
    operations = list(_io_path(root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    return json.loads(_io_path(operations[0] / "operation.json").read_bytes())


@pytest.mark.parametrize("work_id", tuple(route.ROUTES))
def test_selected_work_preflight_and_fixture_install(tmp_path: Path, work_id: str) -> None:
    fixture = _fixture(tmp_path, work_id)
    work = Path("library/works") / work_id
    prior = _files(fixture / work)
    receipt, _, _, is_fixture = route.preflight(work_id, root_override=fixture)
    assert is_fixture and receipt["work"]["before"] == prior
    assert _files(fixture / work) == prior
    result = route.install(work_id, root_override=fixture)
    assert result["status"] == "installed-and-validated"
    assert _files(fixture / work) == receipt["work"]["after"]
    assert _journal(fixture)["phase"] == "complete"


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_swap_failure_restores_cyril_preimage(tmp_path: Path, phase: str) -> None:
    work_id = "cyril-of-jerusalem-catechetical-lectures"
    fixture = _fixture(tmp_path, work_id)
    work = Path("library/works") / work_id
    prior = _files(fixture / work)

    def fail_at(current: str) -> None:
        if current == phase:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match=f"injected {phase}"):
        route.install(work_id, root_override=fixture, fail_at=fail_at)
    assert _files(fixture / work) == prior
    assert _journal(fixture)["phase"] == "rolled-back"


def test_changed_cyril_preimage_fails_closed(tmp_path: Path) -> None:
    work_id = "cyril-of-jerusalem-catechetical-lectures"
    fixture = _fixture(tmp_path, work_id)
    work_json = fixture / "library/works" / work_id / "work.json"
    _io_path(work_json).write_bytes(_io_path(work_json).read_bytes() + b" ")
    with pytest.raises(PipelineError, match="receipt or acquired work differs"):
        route.preflight(work_id, root_override=fixture)
