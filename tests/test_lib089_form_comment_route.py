"""Exact retained-comment and native mapping checks for Form's HTML witness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lxml import etree
import pytest

from build.tei.lib089_form_church_comments_oracle import _oracle
from build.tei.lib089_form_church_comments_reconstruction import _convert
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest, reconstruct, validate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'tests/fixtures/reconstruction-runtime/lib089_form_church_comments_oracle.source-manifest.json'
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"t": TEI}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory):
    source = SourceManifest.load(MANIFEST, repository_root=ROOT)
    candidate = reconstruct(source, tmp_path_factory.mktemp("form-comment") / "package", _convert)
    report = validate(source, candidate, _oracle)
    assert report.status == "pass" and not report.findings
    return source, candidate


def test_two_comments_remain_visible_at_exact_paragraph_positions(built) -> None:
    _source, candidate = built
    root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    notes = root.xpath("/t:TEI/t:text/t:body//t:note[@type='source-html-comment']", namespaces=NS)
    assert len(notes) == 2
    assert [node.text for node in notes] == [" .entry-content "] * 2
    assert all(node.getparent().tag == f"{{{TEI}}}p" for node in notes)
    assert all(len(node.getparent()) == 1 and node.getparent().text is None and node.tail is None for node in notes)
    accounting = json.loads(candidate.member_bytes("source-accountability.json"))
    events = [row for row in accounting["source_events"] if row["source_tag"] == "#comment"]
    assert len(events) == 2
    assert [row["tei_xml_id"] for row in events] == [
        "form-of-church-government-comment-001", "form-of-church-government-comment-002"
    ]
    assert all(row["tei_text_sha256"] == _sha(b" .entry-content ") for row in events)


@pytest.mark.parametrize(("mutation", "reason"), [
    ("drop", "LIB-089 TEI direct text or child cardinality drifted"),
    ("edit", "Form TEI comment note text, type, or position drifted"),
    ("move", "LIB-089 TEI direct text or child cardinality drifted"),
])
def test_independent_oracle_rejects_comment_loss_or_drift(
    built, tmp_path: Path, mutation: str, reason: str
) -> None:
    source, candidate = built
    destination = tmp_path / mutation
    destination.mkdir()
    for name in candidate.member_names:
        (destination / name).write_bytes(candidate.member_bytes(name))
    root = etree.fromstring((destination / "content.tei.xml").read_bytes())
    notes = root.xpath("/t:TEI/t:text/t:body//t:note[@type='source-html-comment']", namespaces=NS)
    if mutation == "drop":
        notes[0].getparent().remove(notes[0])
    elif mutation == "edit":
        notes[0].text = " .changed-content "
    else:
        source_parent = notes[0].getparent()
        source_parent.remove(notes[0])
        notes[1].getparent().append(notes[0])
    content = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    (destination / "content.tei.xml").write_bytes(content)
    package = json.loads((candidate.path / "manifest.json").read_bytes())
    member = next(row for row in package["members"] if row["name"] == "content.tei.xml")
    member.update(bytes=len(content), sha256=_sha(content))
    (destination / "manifest.json").write_text(
        json.dumps(package, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=reason):
        validate(source, CandidatePackage.load(destination), _oracle)
