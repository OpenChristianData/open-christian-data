"""Selected-source and isolated swap checks for NPNF2-07 Select Letters."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import shutil
import tempfile

import pytest

from build.tools import install_gregory_select_letters_npnf207_acceptance as route
from ocd_kernel.library._common import PipelineError
from tests.gregory_select_runtime_install_fixture import gregory_select_current_context
from ocd_kernel.tei.install_accepted import _files, _io_path


CURRENT_ROOT, ORIGINAL_STAGE, ORIGINAL_RECEIPT, ORIGINAL_PIN = route.ROOT, route.STAGE, route.RECEIPT, route.RECEIPT_SHA


@pytest.fixture(scope="module", autouse=True)
def current_runtime_historical_context():
    review_area = Path("D:/Library/Open Christian Data/candidate-reviews").resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="gregory-current-", dir=review_area) as temporary:
        area = Path(temporary)
        assert area.resolve().is_relative_to(review_area)
        before = _files(CURRENT_ROOT / route.WORK)
        root, stage, pin, manifest, candidate, oracle = gregory_select_current_context(route, area)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(route, "ROOT", root)
            patch.setattr(route, "STAGE", stage)
            patch.setattr(route, "RECEIPT", stage / "stage-receipt.json")
            patch.setattr(route, "RECEIPT_SHA", pin)
            patch.setattr(route, "MANIFEST", manifest.path.relative_to(CURRENT_ROOT))
            patch.setattr(route, "MANIFEST_SHA", manifest.sha256)
            patch.setattr(route, "PACKAGE", candidate.path)
            patch.setattr(route, "PACKAGE_SHA", candidate.sha256)
            patch.setattr(route, "_oracle", oracle)
            yield
        assert _files(CURRENT_ROOT / route.WORK) == before


def test_original_stage_rejects_managed_current_context():
    metadata = "metadata/source-evidence/catalog/gregory-of-nazianzus-select-letters.json"
    receipt = json.loads(ORIGINAL_RECEIPT.read_bytes())
    assert sha256(ORIGINAL_RECEIPT.read_bytes()).hexdigest() == ORIGINAL_PIN
    assert sha256((CURRENT_ROOT / metadata).read_bytes()).hexdigest() != receipt["dependencies"][metadata]
    receipt_root = Path(receipt["canonical_root"]).resolve(strict=True)
    assert (CURRENT_ROOT / metadata).read_bytes() == (receipt_root / metadata).read_bytes()
    for context_root in dict.fromkeys((CURRENT_ROOT.resolve(), receipt_root)):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(route, "ROOT", context_root)
            patch.setattr(route, "STAGE", ORIGINAL_STAGE)
            patch.setattr(route, "RECEIPT", ORIGINAL_RECEIPT)
            patch.setattr(route, "RECEIPT_SHA", ORIGINAL_PIN)
            error = (
                r"^Gregory Select Letters source or evidence changed: "
                r"metadata/source-evidence/catalog/gregory-of-nazianzus-select-letters\.json$"
                if context_root == receipt_root else
                r"^Gregory Select Letters stage contract or roots differ$"
            )
            with pytest.raises(PipelineError, match=error):
                route.preflight()


def _fixture(tmp_path: Path) -> Path:
    root = Path(tempfile.mkdtemp(prefix="fixture-" + tmp_path.name + "-", dir=route.STAGE.parent))
    _io_path(root / route.FIXTURE_MARKER).write_text(
        "NPNF2-07 Select Letters installer fixture\n", encoding="utf-8")
    for relative in _files(route.ROOT / route.WORK):
        origin = _io_path(route.ROOT / route.WORK / relative)
        destination = _io_path(root / route.WORK / relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination)
    return root


def _journal(root: Path) -> dict:
    operations = list(_io_path(root / "library/.sidecar-operations").iterdir())
    assert len(operations) == 1
    return json.loads(_io_path(operations[0] / "operation.json").read_bytes())


def test_exact_source_title_label_remains_readable_without_body_change() -> None:
    from ocd_kernel.reconstruction import CandidatePackage

    package = CandidatePackage.load(route.PACKAGE)
    original = package.member_bytes("content.tei.xml")
    master = _io_path(route.STAGE / route.WORK / route.MASTER).read_bytes()
    source_header = original.split(b"</teiHeader>", 1)[0]
    accepted_header, accepted_body = master.split(b"</teiHeader>", 1)
    assert b'<title type="retained-electronic-title" n="npnf207">' in source_header
    assert b'<title type="retained-electronic-title" n="npnf207">' not in accepted_header
    assert b'<title type="retained-electronic-title">' in accepted_header
    assert (b'<note type="retained-electronic-title-source-label" n="npnf207">'
            b'Electronic volume title source @n: npnf207</note>') in accepted_header
    assert b"sourced via CCEL.org" in accepted_header
    assert accepted_body == original.split(b"</teiHeader>", 1)[1]


def test_clean_fixture_install_has_complete_journal(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    prior = _files(fixture / route.WORK)
    receipt, _, is_fixture = route.preflight(root_override=fixture)
    assert is_fixture and receipt["work"]["before"] == prior
    assert _files(fixture / route.WORK) == prior
    result = route.install(root_override=fixture)
    assert result["status"] == "installed-and-validated"
    assert _files(fixture / route.WORK) == receipt["work"]["after"]
    assert _journal(fixture)["phase"] == "complete"


@pytest.mark.parametrize("phase", ["after-old-rename", "after-new-rename"])
def test_injected_failure_restores_exact_preimage(tmp_path: Path, phase: str) -> None:
    fixture = _fixture(tmp_path)
    prior = _files(fixture / route.WORK)

    def fail_at(current: str) -> None:
        if current == phase:
            raise RuntimeError(f"injected {phase}")

    with pytest.raises(RuntimeError, match=f"injected {phase}"):
        route.install(root_override=fixture, fail_at=fail_at)
    assert _files(fixture / route.WORK) == prior
    assert _journal(fixture)["phase"] == "rolled-back"


def test_changed_preimage_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    work_json = fixture / route.WORK / "work.json"
    _io_path(work_json).write_bytes(_io_path(work_json).read_bytes() + b" ")
    with pytest.raises(PipelineError, match="receipt or acquired work differs"):
        route.preflight(root_override=fixture)
