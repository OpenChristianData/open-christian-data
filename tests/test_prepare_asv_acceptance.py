"""Preparation-only ASV acceptance handoff regression."""

import hashlib
from copy import deepcopy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from build.tools.prepare_asv_acceptance import ORIGINAL_SHA, ROOT, _verify_visual_screenshots, prepare
from build.tools import prepare_asv_acceptance as route
from tests.runtime_candidate_baselines import current_runtime_baseline
from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import promote_accepted_master, validate_acceptance


def test_asv_handoff_promotes_scoped_agent_acceptance_in_fixture(tmp_path, monkeypatch):
    original_review_bytes = current_review_context(tmp_path, monkeypatch)
    stage = tmp_path / "asv-stage"
    canonical = ROOT / "library/works/asv"
    before = {name: (canonical / name).read_bytes() for name in ("work.json", "state.json")}
    started = datetime.now(timezone.utc)
    acceptance = prepare(ROOT, stage)
    finished = datetime.now(timezone.utc)
    record = validate_acceptance(acceptance, root=stage)
    evidence = stage / "library/works/asv/integration/asv-header-handoff-v1"
    original = (evidence / "original-package/content.tei.xml").read_bytes()
    derived = (evidence / "candidate.tei.xml").read_bytes()
    report = json.loads((evidence / "header-derivation.json").read_bytes())

    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    assert original.split(b"</teiHeader>", 1)[1] == derived.split(b"</teiHeader>", 1)[1]
    assert report["original_text_sha256"] == report["derived_text_sha256"]
    assert record["promotion"]["status"] == "pending"
    assert record["decision"]["agent_assessment"]["status"] == "accepted"
    assert record["decision"]["agent_assessment"]["supported_scope"] == record["scope"]["declared"]
    assert record["decision"]["human_decision"]["status"] == "not-recorded"
    assessed_at = datetime.fromisoformat(record["decision"]["agent_assessment"]["assessed_at"].replace("Z", "+00:00"))
    assert assessed_at.tzinfo is not None
    assert started <= assessed_at <= finished
    assert record["review"]["coverage"]["status"] == "partial"
    assert len(record["review"]["coverage"]["inspected"]) == 7
    assert not (stage / "library/works/asv/forms/english-asv/editions/retained-json/master.tei.xml").exists()
    assert all((canonical / name).read_bytes() == content for name, content in before.items())
    assert (ROOT / route.RECEIPT).read_bytes() == original_review_bytes

    promoted = promote_accepted_master(
        stage,
        acceptance_path=acceptance,
        destination=tmp_path / "promoted",
    )
    promoted_record = validate_acceptance(promoted.acceptance_path, root=promoted.destination_root)
    assert promoted_record["promotion"]["status"] == "promoted"
    assert promoted_record["decision"]["agent_assessment"]["status"] == "accepted"
    assert promoted_record["decision"]["human_decision"]["status"] == "not-recorded"
    assert promoted.master_path.is_file()
    promoted_state = json.loads(promoted.state_path.read_bytes())
    assert promoted_state["targets"][0]["stage"] == "accepted"


def current_review_context(tmp_path, monkeypatch):
    """Keep the seven-locus review body fixed while recording current runtime IDs."""
    original_bytes = (ROOT / route.RECEIPT).read_bytes()
    original = json.loads(original_bytes)
    canonical = lambda value: (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert hashlib.sha256(canonical(original)).hexdigest() == "3f3b42f6c4d6b7c258bd153bfb325e31b26cb87ad17c1692042b97ce821b1b4c"
    case = next(row for row in json.loads((ROOT / "tests/fixtures/reconstruction-runtime/next-binding-asv-lib072.json").read_bytes())
                if row["original"] == route.MANIFEST.as_posix())
    _, candidate = current_runtime_baseline(
        root=ROOT, original_manifest=case["original"], runtime_manifest=case["manifest"],
        retained_package=Path("D:/Library/Open Christian Data/candidate-reviews/37c-006-asv-20260912-c3/package"),
        retained_sha256=original["candidate"]["manifest_sha256"], destination=tmp_path / "asv-runtime")
    validation_bytes = (candidate.path.parent / "validation.json").read_bytes()
    validation = json.loads(validation_bytes)
    current = deepcopy(original)
    current["candidate"].update(path=candidate.path.parent.as_posix(), manifest_sha256=candidate.sha256,
                                validation_sha256=hashlib.sha256(validation_bytes).hexdigest(),
                                validation_report_sha256=validation["report_sha256"])
    restored = deepcopy(current)
    for field in ("path", "manifest_sha256", "validation_sha256", "validation_report_sha256"):
        restored["candidate"][field] = original["candidate"][field]
    assert restored == original
    real_receipt, real_copy = route._receipt, route._copy

    def current_receipt(root, source_sha):
        assert real_receipt(root, source_sha) == original
        return deepcopy(current)

    def current_copy(root, stage, relative):
        if relative == route.RECEIPT:
            assert (root / relative).read_bytes() == original_bytes
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(canonical(current))
            return target
        return real_copy(root, stage, relative)

    monkeypatch.setattr(route, "MANIFEST", Path(case["manifest"]))
    monkeypatch.setattr(route, "_receipt", current_receipt)
    monkeypatch.setattr(route, "_copy", current_copy)
    return original_bytes


def test_original_asv_handoff_rejects_current_kernel_closure(tmp_path):
    with pytest.raises(ValueError, match="oracle import-closure binding mismatch"):
        prepare(ROOT, tmp_path / "historical-closure")


def _screenshot(path: str, content: bytes) -> dict:
    return {"label": path, "path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def test_visual_evidence_rejects_missing_screenshot(tmp_path):
    with pytest.raises(PipelineError, match="missing or outside"):
        _verify_visual_screenshots(tmp_path, [_screenshot("missing.png", b"\x89PNG\r\n\x1a\nvalid")])


def test_visual_evidence_rejects_modified_screenshot(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nwrong")
    receipt = _screenshot("image.png", b"\x89PNG\r\n\x1a\nright")
    with pytest.raises(PipelineError, match="does not match"):
        _verify_visual_screenshots(tmp_path, [receipt])


def test_visual_evidence_rejects_duplicate_screenshot_paths(tmp_path):
    path = tmp_path / "image.png"
    content = b"\x89PNG\r\n\x1a\nidentical"
    path.write_bytes(content)
    receipt = _screenshot("image.png", content)
    with pytest.raises(PipelineError, match="duplicated"):
        _verify_visual_screenshots(tmp_path, [receipt, receipt.copy()])



def _asv_layout_pair(layout):
    from ocd_kernel.tei.reviewed_integration import bind_reviewed_header

    original = (b'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:id="asv"><teiHeader><fileDesc>'
                b'<titleStmt><title>ASV fixture</title></titleStmt><publicationStmt><p>Internal.</p></publicationStmt>'
                b'<sourceDesc><p>Retained source description.</p></sourceDesc></fileDesc></teiHeader>'
                b'<text><body><p>Exact retained text.</p></body></text></TEI>\n')
    bound = bind_reviewed_header(
        original, expected_sha256=hashlib.sha256(original).hexdigest(), identity=route.IDENTITY,
        source=dict(source_sha256="a" * 64, source_bytes=17, source_path="retained/asv.json"),
        source_url="https://example.org/asv", declared_scope="one retained fixture member", revision=route.REVISION)
    namespace = b' xmlns="http://www.tei-c.org/ns/1.0"'
    marked = b"<bibl" + namespace + b' type="ocd-acceptance-binding">'
    if layout == "legacy":
        bound = bound.replace(b"<p" + namespace + b">" + marked, b"<bibl" + namespace + b">", 1)
        bound = bound.replace(b"</bibl></p></sourceDesc>", b"</bibl></sourceDesc>", 1)
    return original, bound


@pytest.mark.parametrize("layout", ("legacy", "current"))
def test_asv_header_layout_preserves_binding_text_and_exact_inverse(tmp_path, layout):
    from lxml import etree
    from ocd_kernel.tei.acceptance import _tei_facts
    from ocd_kernel.tei.validate import validate_file

    original, bound = _asv_layout_pair(layout)
    derived = route._asv_header_layout(original, bound)
    assert derived.split(b"</teiHeader>", 1)[1] == original.split(b"</teiHeader>", 1)[1]
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    tree = etree.fromstring(derived)
    source = tree.find("tei:teiHeader/tei:fileDesc/tei:sourceDesc", ns)
    assert len(source) == 1 and source[0].tag == "{http://www.tei-c.org/ns/1.0}bibl"
    assert source[0].find("tei:note[@type='historical-source-description']", ns).text == "Retained source description."
    before_tree = etree.fromstring(bound)
    assert [(node.attrib, node.text) for node in before_tree.findall(".//tei:idno", ns)] == [
        (node.attrib, node.text) for node in tree.findall(".//tei:idno", ns)]
    candidate = tmp_path / "candidate.tei.xml"
    candidate.write_bytes(derived)
    assert validate_file(candidate) == []
    facts = _tei_facts(candidate)[1]
    assert {key: facts[key] for key in route.IDENTITY} == route.IDENTITY
    assert facts["source_sha256"] == facts["sha256"] == "a" * 64
    assert facts["source_url"] == "https://example.org/asv"
    namespace = b' xmlns="http://www.tei-c.org/ns/1.0"'
    bibl = b"<bibl" + namespace + (b' type="ocd-acceptance-binding">' if layout == "current" else b">")
    wrapper = b"<p" + namespace + b">" if layout == "current" else b""
    ending = b"</bibl></p></sourceDesc>" if layout == "current" else b"</bibl></sourceDesc>"
    note = b'<note type="historical-source-description">Retained source description.</note>'
    restored = derived.replace(b"<sourceDesc>" + bibl + note,
                               b"<sourceDesc><p>Retained source description.</p>" + wrapper + bibl, 1)
    restored = restored.replace(b"</bibl></sourceDesc>", ending, 1)
    assert restored == bound


@pytest.mark.parametrize("layout", ("legacy", "current"))
@pytest.mark.parametrize("mutation", ("changed-paragraph", "duplicate-binding", "missing-binding", "mixed-content"))
def test_asv_header_layout_rejects_unrecognized_or_mixed_source_description(layout, mutation):
    original, bound = _asv_layout_pair(layout)
    if mutation == "changed-paragraph":
        bound = bound.replace(b"Retained source description.", b"Changed source description.", 1)
    elif mutation == "duplicate-binding":
        opening = b'<bibl xmlns="http://www.tei-c.org/ns/1.0"'
        bound = bound.replace(opening, opening + b">extra</bibl>" + opening, 1)
    elif mutation == "missing-binding":
        bound = bound.replace(b"<bibl", b"<unknown", 1)
    else:
        original = original.replace(b"Retained source description.", b"Source &amp; detail.", 1)
    with pytest.raises(PipelineError, match="source description"):
        route._asv_header_layout(original, bound)
