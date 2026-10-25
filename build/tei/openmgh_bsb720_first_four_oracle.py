"""Independent source-line oracle for four numbered bsb720 Lambert poems."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
HEADING = re.compile(r"^〈([1-5])\.〉\s+(.+)$")


def _parse(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    result = etree.fromstring(data, parser)
    if result.getroottree().docinfo.doctype or result.tag != f"{TEI}TEI":
        raise ValueError("entity-free TEI required")
    return result


def _equal(left: etree._Element, right: etree._Element, *, outer: bool = False) -> bool:
    if (left.tag != right.tag or dict(left.attrib) != dict(right.attrib)
            or left.text != right.text or len(left) != len(right)):
        return False
    if not outer and left.tail != right.tail:
        return False
    return all(_equal(a, b) for a, b in zip(left, right, strict=True))


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    """Derive source boundaries from numbered headings, then compare actual lines."""
    if not 1 <= number <= 4:
        raise ValueError("poem outside four-work review")
    source = _parse(source_bytes)
    candidate = _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    volume = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volume) != 1 or len(volume[0]) != 3 or volume[0][2].get("n") != "Carmina":
        raise ValueError("source volume or Carmina ancestry changed")
    carmina = volume[0][2]
    if len(carmina) != 1 or carmina[0].tag != f"{TEI}ab":
        raise ValueError("Carmina is no longer one flat ab")
    children = list(carmina[0])
    if len(children) != 959:
        raise ValueError("complete Carmina child inventory changed")
    if ([node.get(XML_ID) for node in children[1:3]]
            != ["bsb00000720_00267_1", "bsb00000720_00267_2"]):
        raise ValueError("shared Carmina heading changed")
    positions = {}
    section_end = [i for i, node in enumerate(children)
                   if node.tag == f"{TEI}lb" and (node.tail or "").strip() == "〈II.〉"]
    if section_end != [145]:
        raise ValueError("opening Lambert section endpoint changed")
    for index, node in enumerate(children[:section_end[0]]):
        if node.tag == f"{TEI}lb" and node.tail:
            match = HEADING.match(node.tail.strip())
            if match:
                key = int(match.group(1))
                if key in positions:
                    raise ValueError("numbered source heading repeated")
                positions[key] = index
    if set(positions) != set(range(1, 6)) or any(
            positions[n] >= positions[n + 1] for n in range(1, 5)):
        raise ValueError("first five poem headings or order changed")
    selected = children[positions[number]:positions[number + 1]]
    intervening = []
    if selected and selected[-1].tag == f"{TEI}pb":
        intervening = selected[-1:]
        selected = selected[:-1]
    if (not selected or any(node.tag != f"{TEI}lb" for node in selected)
            or any(node.text or len(node) or not (node.tail or "").strip()
                   for node in selected)):
        raise ValueError("numbered poem contains unsupported or empty lines")
    if intervening and ([node.get(XML_ID) for node in intervening]
                        != ["bsb00000720_00268"] or number != 2):
        raise ValueError("unaccounted page marker at poem boundary")
    if source_bytes and sha256(source_bytes).hexdigest() != acquisition["source_sha256"]:
        raise ValueError("extracted source hash differs from acquisition")
    expected_ids = [node.get(XML_ID) for node in selected]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("poem source line identifier repeated")
    declared = [part.split("#", 1)[1] for part in
                work["textual_forms"][0]["editions"][0]["containing_source"]["locator"].split("; ")]
    if Counter(declared) != Counter((expected_ids[0], expected_ids[-1])):
        raise ValueError("catalog boundary locators do not match source-derived span")
    poems = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(poems) != 1 or poems[0].get("n") != work["title"] or len(poems[0]) != 1:
        raise ValueError("candidate is not one source-named work")
    block = poems[0][0]
    if block.tag != f"{TEI}ab" or block.text or len(block) != len(selected):
        raise ValueError("candidate flat source block changed")
    for source_line, candidate_line in zip(selected, block, strict=True):
        if not _equal(source_line, candidate_line):
            raise ValueError(f"source line changed: {source_line.get(XML_ID)}")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate/work title differs")
    source_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    candidate_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if source_file is None or candidate_file is None:
        raise ValueError("electronic source header missing")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = source_file.find(suffix), candidate_file.find(suffix)
        if old is None or new is None or not _equal(old, new, outer=True):
            raise ValueError("electronic rights or print bibliography changed")
    return {"status": "pass", "number": number,
            "source_sha256": sha256(source_bytes).hexdigest(),
            "source_heading_id": expected_ids[0],
            "source_last_line_id": expected_ids[-1],
            "source_child_start": positions[number],
            "source_child_end": positions[number + 1] - 1 - len(intervening),
            "line_count": len(selected) - 1,
            "intervening_page_break": intervening[0].get(XML_ID) if intervening else None,
            "shared_heading_ids": ["bsb00000720_00267_1", "bsb00000720_00267_2"],
            "mapping": "exact native ab line nodes preserved under one work div"}
