"""Nested text sections retain every ordered match without overlapping walks."""
from lxml import etree
import pytest

from build.tei import calvins_institutes_oracle as oracle


@pytest.mark.parametrize("depth", [1, 2, 4])
def test_text_queries_match_independent_ancestry_walk_and_original_queries(depth):
    ns = {"tei": oracle._TEI}
    root = etree.Element(f"{{{oracle._TEI}}}TEI", nsmap={None: oracle._TEI})
    header = etree.SubElement(root, f"{{{oracle._TEI}}}teiHeader")
    etree.SubElement(header, f"{{{oracle._TEI}}}lb", {oracle._XML_ID: "outside"})
    parent = root
    for level in range(depth):
        parent = etree.SubElement(parent, f"{{{oracle._TEI}}}text", {oracle._XML_ID: f"text-{level}"})
    for index in range(100):
        paragraph = etree.SubElement(parent, f"{{{oracle._TEI}}}p", {oracle._XML_ID: f"block-{index}"})
        etree.SubElement(paragraph, f"{{{oracle._TEI}}}lb", {oracle._XML_ID: f"line-{index}"})
        etree.SubElement(paragraph, f"{{{oracle._TEI}}}lb")
    identified = [node for node in root.iter() if node.get(oracle._XML_ID) is not None
                  and any(ancestor.tag == f"{{{oracle._TEI}}}text" for ancestor in node.iterancestors())]
    lines = [node.get(oracle._XML_ID) for node in identified if node.tag == f"{{{oracle._TEI}}}lb"]
    assert oracle._TEXT_IDENTIFIED_NODES(root) == identified
    assert list(oracle._TEXT_LINE_IDS(root)) == lines
    assert identified == root.xpath("//tei:text//*[@xml:id]", namespaces=ns)
    assert lines == root.xpath("//tei:text//tei:lb/@xml:id", namespaces=ns)
