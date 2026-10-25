"""Independent line-slice oracle for three bsb720 Carmina poems."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256

from lxml import etree

from build.tei.openmgh_bsb720_first_four_oracle import TEI, XML_ID, _equal, _parse

SPECS = {
    16: ("bsb00000720_00270_18", "bsb00000720_00270_27", "〈16.〉 IN AMBONE",
         "bsb00000720_00271_1", (), "bsb00000720_00271"),
    5: ("bsb00000720_00291_1", "bsb00000720_00293_9",
        "〈5.〉 CHRISTI HODIERNA DE SANCTO HERIBERTO", "bsb00000720_00294_1",
        ("bsb00000720_00292", "bsb00000720_00293"), "bsb00000720_00294"),
    4: ("bsb00000720_00302_5", "bsb00000720_00304_5",
           "〈IV.〉 Sequentia de Sancto Lamberto", None,
           ("bsb00000720_00303", "bsb00000720_00304"), None),
}
SOURCE_SHA256 = "2a096d80ae17e4f701fdce91585d77afb5d69e385167a46f45173e887dc38ce5"


def source_span(source_bytes: bytes, number: int) -> tuple[list[etree._Element], dict]:
    if number not in SPECS or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("Carmina selection or retained source hash changed")
    root = _parse(source_bytes)
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces={"t": TEI[1:-1]})
    if len(volumes) != 1 or len(volumes[0]) != 3 or volumes[0][2].get("n") != "Carmina":
        raise ValueError("bsb720 Carmina source ancestry changed")
    carrier = volumes[0][2]
    if len(carrier) != 1 or carrier[0].tag != f"{TEI}ab" or len(carrier[0]) != 959:
        raise ValueError("bsb720 flat Carmina inventory changed")
    children = list(carrier[0])
    start_id, end_id, heading, next_id, pages, boundary_page = SPECS[number]
    by_id = {node.get(XML_ID): i for i, node in enumerate(children) if node.get(XML_ID)}
    if len(by_id) != sum(bool(node.get(XML_ID)) for node in children):
        raise ValueError("duplicate Carmina XML IDs")
    start, end = by_id[start_id], by_id[end_id]
    if start >= end or (children[start].tail or "").strip() != heading:
        raise ValueError("Carmina heading or order changed")
    selected = children[start:end + 1]
    following = children[end + 1:]
    if boundary_page is not None:
        if (len(following) < 2 or following[0].tag != f"{TEI}pb"
                or following[0].get(XML_ID) != boundary_page
                or following[1].get(XML_ID) != next_id):
            raise ValueError("source-owned following page or heading changed")
    elif following or next_id is not None:
        raise ValueError("terminal poem is no longer terminal")
    actual_pages = tuple(node.get(XML_ID) for node in selected if node.tag == f"{TEI}pb")
    if actual_pages != pages:
        raise ValueError("internal Carmina pagination changed")
    if any(node.tag not in {f"{TEI}lb", f"{TEI}pb", f"{TEI}cb", f"{TEI}anchor"}
           or node.text or len(node) for node in selected):
        raise ValueError("unsupported Carmina child shape")
    return selected, {
        "number": number, "source_child_start": start, "source_child_end": end,
        "source_heading_id": start_id, "source_last_line_id": end_id,
        "line_count": sum(node.tag == f"{TEI}lb" for node in selected),
        "internal_page_break": list(pages), "following_heading_id": next_id,
        "following_boundary_page": boundary_page,
        "source_column_break_count": sum(node.tag == f"{TEI}cb" for node in selected),
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if acquisition.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("acquisition source binding changed")
    declared = [item.split("#", 1)[1] for item in
                work["textual_forms"][0]["editions"][0]["containing_source"]["locator"].split("; ")]
    if number == 16:
        expected_ids = (details["source_heading_id"], details["source_last_line_id"])
    else:
        expected_ids = (details["source_heading_id"], details["source_last_line_id"])
    if Counter(declared) != Counter(expected_ids):
        raise ValueError("catalog endpoint set differs from native poem")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    block = works[0][0]
    if block.tag != f"{TEI}ab" or block.text or len(block) != len(selected):
        raise ValueError("candidate poem block differs")
    if any(not _equal(left, right) for left, right in zip(selected, block, strict=True)):
        raise ValueError("candidate native node changed")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate title differs")
    source_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    candidate_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if source_file is None or candidate_file is None:
        raise ValueError("source/candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = source_file.find(suffix), candidate_file.find(suffix)
        if old is None or new is None or not _equal(old, new, outer=True):
            raise ValueError("source publication or bibliography changed")
    return {"status": "pass", **details, "source_sha256": SOURCE_SHA256,
            "mapping": "exact native Carmina line, column, and page nodes under one work div"}
