"""Guarded NPNF109 exact-pin, rollback, and live projection fixture checks."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from lxml import etree
import pytest

from tests.npnf_four_install_fixture import (
    four_work_install_fixture, current_npnf_generation_is_preserved, current_generation_receipt,
)
from build.tools import preflight_npnf109_rome_corpus_acceptance as guard

from build.tei.npnf109_rome_corpus_oracle import _oracle
from build.tools import install_npnf109_rome_corpus_acceptance as installer
from build.tools.preflight_npnf109_rome_corpus_acceptance import preflight
from build.tools.stage_npnf109_rome_corpus_acceptance import BATCH_SHA
from ocd_kernel.library._common import PipelineError
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _files, _io_path


ROOT = Path(__file__).resolve().parents[1]
STAGES = Path(r"D:\Library\Open Christian Data\candidate-reviews")
STAGE = STAGES / "npnf109-rome-four-letter-acceptance-stage-20260927-v2"
WORK_ID = "chrysostom-correspondence-with-rome"
CANDIDATE = STAGES / "npnf109-rome-four-letter-corpus-20260927-v1" / "package"
MANIFEST = ROOT / "sources/structured-text/chrysostom-npnf109-16/rome-corpus/source-manifest.json"
TEI = "http://www.tei-c.org/ns/1.0"


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def test_frozen_rome_stage_pin_index_matches_exact_receipt() -> None:
    pins_bytes = installer.PINS.read_bytes()
    assert sha256(pins_bytes).hexdigest() == installer.PINS_SHA
    pins = json.loads(pins_bytes)
    assert pins["contract"] == "ocd-npnf109-rome-corpus-stage-pins-v1"
    assert pins["candidate_receipt_sha256"] == BATCH_SHA
    assert len(pins["entries"]) == 1
    for item in pins["entries"]:
        receipt = Path(pins["stage_root"]) / item["receipt"]
        content = receipt.read_bytes()
        record = json.loads(content)
        assert sha256(content).hexdigest() == item["receipt_sha256"]
        assert record["work_id"] == item["work_id"]
        assert record["accepted_master_sha256"] == item["accepted_master_sha256"]
        assert record["installation"] == "not-performed"


def test_installer_requires_pin_then_rolls_back_and_projects_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen_receipt = STAGES / "npnf109-rome-four-letter-acceptance-stage-20260927-v2-receipt.json"
    with pytest.raises(PipelineError, match="exact reviewed stage receipt hash changed"):
        installer.install(frozen_receipt, expected_receipt_sha256="0" * 64)

    root, receipt, record, batch_sha = four_work_install_fixture(ROOT, tmp_path / "context", WORK_ID)
    for module in (guard, installer):
        monkeypatch.setattr(module, "BATCH", Path(record["package_receipt"]))
        monkeypatch.setattr(module, "BATCH_SHA", batch_sha)
    work = Path("library/works") / WORK_ID
    pin = sha256(receipt.read_bytes()).hexdigest()

    fixture_pins = json.loads(installer.PINS.read_bytes())
    original_pins = json.loads(installer.PINS.read_bytes())
    fixture_pins["stage_root"] = receipt.parent.as_posix()
    fixture_pins["candidate_receipt"] = record["package_receipt"]
    fixture_pins["candidate_receipt_sha256"] = batch_sha
    assert fixture_pins["entries"][0]["work_id"] == WORK_ID
    assert fixture_pins["entries"][0]["receipt"] == receipt.name
    fixture_pins["entries"][0]["receipt_sha256"] = pin
    restored_pins = json.loads(_json(fixture_pins))
    for key in ("stage_root", "candidate_receipt", "candidate_receipt_sha256"):
        restored_pins[key] = original_pins[key]
    restored_pins["entries"][0]["receipt_sha256"] = original_pins["entries"][0]["receipt_sha256"]
    assert restored_pins == original_pins
    pins_path = tmp_path / "pins.json"
    pins_path.write_bytes(_json(fixture_pins))
    monkeypatch.setattr(installer, "PINS", pins_path)
    monkeypatch.setattr(installer, "PINS_SHA", sha256(pins_path.read_bytes()).hexdigest())
    assert preflight(receipt)["status"] == "ready-for-review"

    before = _files(root / work)
    manifest, profile = root / record["manifest_path"], root / record["profile_path"]
    before_manifest = _io_path(manifest).read_bytes()
    before_profile = _io_path(profile).read_bytes()

    def fail_after_manifest(phase: str) -> None:
        if phase == "after-source-manifest.json-swap":
            raise RuntimeError("injected manifest-swap failure")

    with pytest.raises(RuntimeError, match="injected manifest-swap failure"):
        installer.install(receipt, expected_receipt_sha256=pin, fail_at=fail_after_manifest,
                          operation_prefix="npnf109-rome-fixture")
    assert _files(root / work) == before
    assert _io_path(manifest).read_bytes() == before_manifest
    assert _io_path(profile).read_bytes() == before_profile
    journals = list((root / "library/.sidecar-operations").glob("npnf109-rome-fixture-*/operation.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_bytes())["phase"] == "rolled-back"

    result = installer.install(receipt, expected_receipt_sha256=pin,
                               operation_prefix="npnf109-rome-fixture")
    assert result["status"] == "installed-and-validated"
    assert result["projection_rows"] == 7
    assert _files(root / work) == record["after"]


@pytest.mark.parametrize("mutation", ["omit-introduction", "wrong-sender", "repeat-banner"])
def test_source_oracle_rejects_repacked_constituent_or_context_mutation(
    tmp_path: Path, mutation: str,
) -> None:
    package_path = tmp_path / "package"
    shutil.copytree(_io_path(CANDIDATE), package_path)
    tei_path = package_path / "content.tei.xml"
    tree = etree.parse(str(tei_path))
    corpus = tree.getroot()
    members = list(corpus)[1:]
    if mutation == "omit-introduction":
        front = members[0].find(f"{{{TEI}}}text/{{{TEI}}}front")
        assert front is not None
        front.remove(front[1])
    elif mutation == "wrong-sender":
        author = members[2].find(f"{{{TEI}}}teiHeader/{{{TEI}}}fileDesc/{{{TEI}}}titleStmt/{{{TEI}}}author")
        assert author is not None
        author.text = "John Chrysostom"
    else:
        first = members[0].find(f"{{{TEI}}}text")
        assert first is not None
        front = first.find(f"{{{TEI}}}front")
        body = first.find(f"{{{TEI}}}body")
        assert front is not None and body is not None
        repeated = etree.fromstring(etree.tostring(front[2][0]))
        for element in repeated.iter():
            element.attrib.pop("{http://www.w3.org/XML/1998/namespace}id", None)
        body[0].insert(1, repeated)
    content = etree.tostring(tree, encoding="UTF-8", xml_declaration=True)
    tei_path.write_bytes(content)
    package_manifest = package_path / "manifest.json"
    package_record = json.loads(package_manifest.read_bytes())
    member = next(item for item in package_record["members"] if item["name"] == "content.tei.xml")
    member.update(bytes=len(content), sha256=sha256(content).hexdigest())
    package_manifest.write_bytes(_json(package_record))
    source_manifest = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = CandidatePackage.load(package_path)
    with pytest.raises(ValueError, match="Rome|source feature"):
        _oracle(source_manifest, candidate)


@pytest.fixture(autouse=True)
def _preserve_current_repository_and_retained_stage():
    with current_npnf_generation_is_preserved(ROOT, WORK_ID):
        yield


def test_current_accepted_generation_is_not_the_original_before(tmp_path: Path) -> None:
    receipt = current_generation_receipt(ROOT, tmp_path / "current-generation.json", WORK_ID)
    with pytest.raises(PipelineError, match="work generation or source sidecar path changed"):
        guard.preflight(receipt)
