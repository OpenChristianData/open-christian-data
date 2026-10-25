"""Independent retained-source oracle for the two numbered Heribert hymns."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256

from lxml import etree

from build.tei.openmgh_bsb720_first_four_oracle import TEI, XML_ID, _equal, _parse


HEADINGS = {
    3: ("〈3.〉 IN NATALI SANCTI HERIBERTI ARCHIEPISCOPI YMNUS", "bsb00000720_00288_13"),
    4: ("〈4.〉 ITEM YMNUS IAMBICI METRI", "bsb00000720_00289_10"),
    5: ("〈5.〉 CHRISTI HODIERNA DE SANCTO HERIBERTO", "bsb00000720_00291_1"),
}
END_IDS = {3: "bsb00000720_00289_9", 4: "bsb00000720_00290_17"}
PAGE_IDS = {3: "bsb00000720_00289", 4: "bsb00000720_00290"}


def source_span(source_bytes: bytes, number: int) -> tuple[list[etree._Element], dict]:
    if number not in END_IDS:
        raise ValueError("number outside Heribert hymn pair")
    source = _parse(source_bytes)
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces={"t": TEI[1:-1]})
    if len(volumes) != 1 or len(volumes[0]) != 3 or volumes[0][2].get("n") != "Carmina":
        raise ValueError("source volume or Carmina ancestry changed")
    carmina = volumes[0][2]
    if len(carmina) != 1 or carmina[0].tag != f"{TEI}ab":
        raise ValueError("flat Carmina block changed")
    children = list(carmina[0])
    if len(children) != 959:
        raise ValueError("complete Carmina child inventory changed")
    positions = {}
    for key, (text, xml_id) in HEADINGS.items():
        matches = [i for i, node in enumerate(children)
                   if node.tag == f"{TEI}lb" and node.get(XML_ID) == xml_id and (node.tail or "").strip() == text]
        if len(matches) != 1:
            raise ValueError(f"Heribert heading {key} changed")
        positions[key] = matches[0]
    if not positions[3] < positions[4] < positions[5]:
        raise ValueError("Heribert hymn order changed")
    selected = children[positions[number]:positions[number + 1]]
    expected_boundary = "bsb00000720_00291" if number == 4 else None
    if number == 4:
        if not selected or selected[-1].tag != f"{TEI}pb" or selected[-1].get(XML_ID) != expected_boundary:
            raise ValueError("following hymn boundary page changed")
        selected.pop()
    ids = [node.get(XML_ID) for node in selected]
    if (ids[0] != HEADINGS[number][1] or ids[-1] != END_IDS[number]
            or len(ids) != len(set(ids)) or None in ids):
        raise ValueError("Heribert hymn endpoint or IDs changed")
    pages = [node.get(XML_ID) for node in selected if node.tag == f"{TEI}pb"]
    if pages != [PAGE_IDS[number]]:
        raise ValueError("internal hymn pagination changed")
    if any(node.tag not in (f"{TEI}lb", f"{TEI}pb") or node.text or len(node)
           or (node.tag == f"{TEI}lb" and not (node.tail or "").strip()) for node in selected):
        raise ValueError("unsupported or empty hymn source child")
    return selected, {
        "source_child_start": positions[number],
        "source_child_end": positions[number + 1] - 1 - int(number == 4),
        "source_heading_id": ids[0],
        "source_last_line_id": ids[-1],
        "line_count": len(selected) - 1,
        "internal_page_break": PAGE_IDS[number],
        "following_heading_id": HEADINGS[number + 1][1],
        "following_boundary_page": expected_boundary,
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
        raise ValueError("candidate native source node changed")
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
            raise ValueError("source publication or bibliography changed")
    return {"status": "pass", "number": number,
            "source_sha256": sha256(source_bytes).hexdigest(), **details,
            "mapping": "exact native ab line and internal page nodes under one work div"}
