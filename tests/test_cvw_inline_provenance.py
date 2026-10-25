"""Opt-in inline construction retains contributors before text coalescence."""
from copy import deepcopy
import hashlib
from xml.etree import ElementTree as ET

import pytest

from cvw_app.bounded_tei_provenance import ProvenanceBuilder, emit_inline_provenance
from cvw_app.bounded_xml_index import parse_indexed_master
from cvw_app.renderer_nodes import RendererError
from cvw_app.tei_inline import inline_node


def render(tmp_path, xml):
    path = tmp_path / "inline.xml"
    path.write_text(xml, encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    tree = parse_indexed_master(path, expected_sha256=sha, renderer_version="test")
    builder = ProvenanceBuilder(tree, master_member="master.xml", expected_sha256=sha,
                                expected_renderer_version="test")
    element = tree.root.find(".//p")
    traced = emit_inline_provenance(builder, "paragraph", element)
    assert traced.document_node() == inline_node("paragraph", element)
    elements = {ref.locator.ordinal for ref in traced.provenance.sources}
    contributing = [node for node, locator in tree.source_elements.items()
                    if locator.ordinal in elements]
    return tree, builder, element, traced, contributing


@pytest.mark.parametrize("content", [
    'A<hi rend="italic"><seg>B</seg></hi>C',
    'A<seg> </seg><hi> </hi>B',
    'A<lb/>B<pb n="2"/><gap reason="lost"/><ptr target="#x"/><seg type="json-null"/>',
    '<seg>A</seg><seg>A</seg>',
    '',
])
def test_contributing_identity_and_ordinary_output(tmp_path, content):
    tree, _, element, _, contributors = render(tmp_path, f"<TEI><p>{content}</p></TEI>")
    assert set(contributors) == set(element.iter())
    assert tree.root not in contributors


def test_trimmed_whitespace_and_join_break_are_not_contributors(tmp_path):
    _, _, element, _, contributors = render(
        tmp_path, '<TEI><p>A<lb break="no"/><seg> </seg></p></TEI>')
    assert contributors == [element]


def test_reconstructed_or_foreign_handles_fail_closed(tmp_path):
    _, builder, element, _, _ = render(tmp_path, '<TEI><p>A</p></TEI>')
    for foreign in (deepcopy(element), ET.fromstring('<p>A</p>')):
        with pytest.raises(RendererError, match="parser identity"):
            emit_inline_provenance(builder, "paragraph", foreign)


def test_snapshot_survives_later_list_mutation(tmp_path):
    _, builder, element, _, _ = render(tmp_path, '<TEI><p>A</p></TEI>')
    traced = emit_inline_provenance(builder, "list-item", element)
    ordinary = traced.document_node()
    ordinary["type"] = "paragraph"
    assert traced.document_node()["type"] == "list-item"
    replacement = builder.emit(ordinary, derived_from=[traced])
    assert replacement.provenance.derived_from == (traced.provenance.occurrence,)
