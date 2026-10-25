"""The TEI P5 corpus container permits one ordered TEI member."""

from pathlib import Path

from lxml import etree
import pytest

from ocd_kernel.library._common import PipelineError
from ocd_kernel.tei.acceptance import _tei_facts


CANDIDATE = Path(
    "D:/Library/Open Christian Data/candidate-reviews/"
    "37c-234-john-owen-worship-20260918-route-v4-paragraph-locations/"
    "package/content.tei.xml"
)
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _revision_bound_copy(tmp_path: Path) -> Path:
    tree = etree.parse(str(CANDIDATE))
    root = tree.getroot()
    assert [etree.QName(child).localname for child in root] == ["teiHeader", "TEI"]
    header = root[0]
    source_desc = header.find(f"{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}sourceDesc")
    assert source_desc is not None
    bibl = etree.SubElement(source_desc, f"{{{TEI_NS}}}bibl")
    etree.SubElement(bibl, f"{{{TEI_NS}}}idno", type="representation_revision").text = (
        "owen-worship-corpus-parser-fixture-v1"
    )
    revision = etree.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    change = etree.SubElement(revision, f"{{{TEI_NS}}}change")
    change.set(XML_ID, "owen-worship-corpus-parser-fixture-v1")
    change.set("when", "2026-09-24")
    change.text = "Test the one-member corpus acceptance shape."
    path = tmp_path / "one-member.tei.xml"
    tree.write(str(path), encoding="utf-8", xml_declaration=True)
    return path


def test_one_member_corpus_shape_passes_with_revision_binding(tmp_path):
    path = _revision_bound_copy(tmp_path)
    tree, facts = _tei_facts(path)
    root = tree.getroot()
    assert etree.QName(root).localname == "teiCorpus"
    assert [etree.QName(child).localname for child in root] == ["teiHeader", "TEI"]
    assert [etree.QName(child).localname for child in root[1]] == ["teiHeader", "text"]
    assert facts["representation_revision"] == "owen-worship-corpus-parser-fixture-v1"


def test_one_member_corpus_still_requires_nested_header_and_text(tmp_path):
    path = _revision_bound_copy(tmp_path)
    tree = etree.parse(str(path))
    tree.getroot()[1].remove(tree.getroot()[1][1])
    tree.write(str(path), encoding="utf-8", xml_declaration=True)
    with pytest.raises(PipelineError, match="member must retain its own header and text"):
        _tei_facts(path)
