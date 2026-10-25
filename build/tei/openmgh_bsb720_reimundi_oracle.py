"""Independent exact-source oracle for bsb720 Lambert Reimundi poem 21."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re

from lxml import etree

from build.tei.openmgh_bsb720_first_four_oracle import TEI, XML_ID, _equal, _parse


HEADING = re.compile(r"^〈([1-9]|1[0-9]|2[0-3])\.〉\s+(.+)$")
NUMBERS = frozenset({21})
BOUNDARY_PAGES = {}
INTERNAL_PAGE = "bsb00000720_00273"


def source_span(source_bytes: bytes, number: int) -> tuple[list[etree._Element], dict]:
    """Derive all section-I headings before choosing one complete poem."""
    if number not in NUMBERS:
        raise ValueError("poem outside Reimundi review")
    source = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 3 or volumes[0][2].get("n") != "Carmina":
        raise ValueError("source volume or Carmina ancestry changed")
    carmina = volumes[0][2]
    if len(carmina) != 1 or carmina[0].tag != f"{TEI}ab":
        raise ValueError("flat Carmina source block changed")
    children = list(carmina[0])
    if len(children) != 959:
        raise ValueError("complete Carmina child inventory changed")
    if [node.get(XML_ID) for node in children[1:3]] != [
        "bsb00000720_00267_1", "bsb00000720_00267_2"
    ]:
        raise ValueError("shared collection heading changed")
    endpoints = [i for i, node in enumerate(children)
                 if node.tag == f"{TEI}lb" and (node.tail or "").strip() == "〈II.〉"]
    if endpoints != [145]:
        raise ValueError("Lambert section endpoint changed")
    positions = {}
    for index, node in enumerate(children[:145]):
        if node.tag != f"{TEI}lb" or not node.tail:
            continue
        match = HEADING.match(node.tail.strip())
        if match:
            key = int(match.group(1))
            if key in positions:
                raise ValueError("repeated numbered heading")
            positions[key] = index
    if set(positions) != set(range(1, 24)) or any(
        positions[n] >= positions[n + 1] for n in range(1, 23)
    ):
        raise ValueError("Lambert numbered headings or order changed")
    next_heading = positions[number + 1] if number < 23 else endpoints[0]
    selected = children[positions[number]:next_heading]
    page = None
    if selected and selected[-1].tag == f"{TEI}pb":
        page = selected.pop()
    expected_page = BOUNDARY_PAGES.get(number)
    if (page.get(XML_ID) if page is not None else None) != expected_page:
        raise ValueError("boundary pagination changed or unaccounted")
    if (not selected or [(i, node.tag, node.get(XML_ID)) for i, node in enumerate(selected, positions[number])
                         if node.tag != f"{TEI}lb"] != [(126, f"{TEI}pb", INTERNAL_PAGE)]
            or any(node.text or len(node) or (node.tag == f"{TEI}lb" and not (node.tail or "").strip())
                   for node in selected)):
        raise ValueError("poem contains unsupported or empty source nodes")
    ids = [node.get(XML_ID) for node in selected]
    if None in ids or len(ids) != len(set(ids)):
        raise ValueError("missing or repeated native line ID")
    return selected, {
        "source_child_start": positions[number],
        "source_child_end": next_heading - 1 - int(page is not None),
        "source_heading_id": ids[0],
        "source_last_line_id": ids[-1],
        "line_count": len(selected) - 2,
        "internal_page_break": INTERNAL_PAGE,
        "boundary_page_break": expected_page,
        "shared_collection_heading": ["bsb00000720_00267_1", "bsb00000720_00267_2"],
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if sha256(source_bytes).hexdigest() != acquisition["source_sha256"]:
        raise ValueError("extracted source differs from acquisition")
    declared = [part.split("#", 1)[1] for part in
                work["textual_forms"][0]["editions"][0]["containing_source"]["locator"].split("; ")]
    if Counter(declared) != Counter((details["source_heading_id"], details["source_last_line_id"])):
        raise ValueError("catalog endpoint set differs from source span")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    poems = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(poems) != 1 or poems[0].get("n") != work["title"] or len(poems[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    block = poems[0][0]
    if block.tag != f"{TEI}ab" or block.text or len(block) != len(selected):
        raise ValueError("candidate source block differs")
    if any(not _equal(left, right) for left, right in zip(selected, block, strict=True)):
        raise ValueError("candidate native source line changed")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate title differs")
    source_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    candidate_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if source_file is None or candidate_file is None:
        raise ValueError("source or candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = source_file.find(suffix), candidate_file.find(suffix)
        if old is None or new is None or not _equal(old, new, outer=True):
            raise ValueError("source publication or print bibliography changed")
    return {"status": "pass", "number": number,
            "source_sha256": sha256(source_bytes).hexdigest(), **details,
            "mapping": "exact native ab line and internal page nodes preserved under one work div"}
