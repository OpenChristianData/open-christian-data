"""Independent retained-source oracle for two bsb830 Marbod letters."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
SPECS = {
    1: ("bsb00000830_00701_31", "bsb00000830_00703_3", "bsb00000830_00703_3",
        "1. Marbodus minimus episcoporum Ingilgerio servo Dei solitario",
        "bsb00000830_00703_4", ("bsb00000830_00702", "bsb00000830_00703")),
    2: ("bsb00000830_00703_4", "bsb00000830_00703_38", "bsb00000830_00703_38",
        "2. Minimus episcoporum Ingungerio venerabili sacerdoti et",
        "bsb00000830_00704_1", ()),
}


def _parse(data: bytes) -> etree._Element:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                  remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype or root.tag != f"{TEI}TEI":
        raise ValueError("entity-free TEI root required")
    return root


def _equal(left: etree._Element, right: etree._Element, *, outer: bool = False) -> bool:
    if (left.tag != right.tag or dict(left.attrib) != dict(right.attrib)
            or left.text != right.text or len(left) != len(right)):
        return False
    if not outer and left.tail != right.tail:
        return False
    return all(_equal(a, b) for a, b in zip(left, right, strict=True))


def source_span(source_bytes: bytes, number: int) -> tuple[list[etree._Element], dict]:
    if number not in SPECS or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("bsb830 Marbod selection or source hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 29:
        raise ValueError("bsb830 source volume changed")
    carrier = volumes[0][23]
    if (carrier.tag != f"{TEI}div" or carrier.get("type") != "work"
            or carrier.get("n") != "Marbodi episcopi Redonensis opuscula aliquot"
            or len(carrier) != 1 or carrier[0].tag != f"{TEI}ab" or len(carrier[0]) != 224):
        raise ValueError("bsb830 Marbod carrier changed")
    children = list(carrier[0])
    if ([node.get(XML_ID) for node in children[:5]]
            != ["bsb00000830_00700", "bsb00000830_00700_1",
                "bsb00000830_00700_2", "bsb00000830_00701", "bsb00000830_00701_30"]
            or (children[1].tail or "").strip() != "MARBODI EPISCOPI REDONENSIS"
            or (children[2].tail or "").strip() != "OPUSCULA ALIQUOT."
            or (children[4].tail or "").strip() != "I."):
        raise ValueError("shared collection heading changed")
    by_id = {node.get(XML_ID): i for i, node in enumerate(children) if node.get(XML_ID)}
    if len(by_id) != sum(bool(node.get(XML_ID)) for node in children):
        raise ValueError("duplicate correspondence XML ID")
    start_id, last_line_id, end_id, opening, next_id, pages = SPECS[number]
    start, end = by_id[start_id], by_id[end_id]
    if (not start < end or children[start].tag != f"{TEI}lb"
            or (children[start].tail or "").strip() != opening
            or by_id[last_line_id] > end):
        raise ValueError("letter opening or endpoint changed")
    selected = children[start:end + 1]
    next_index = end + 1
    if number == 2:
        if (children[next_index].tag != f"{TEI}pb"
                or children[next_index].get(XML_ID) != "bsb00000830_00704"):
            raise ValueError("following poem boundary page changed")
        next_index += 1
    if next_index >= len(children) or children[next_index].get(XML_ID) != next_id:
        raise ValueError("following letter or poem heading changed")
    if number == 2 and (children[next_index].tail or "").strip() != "II.":
        raise ValueError("following poem label changed")
    if (number == 1 and not (children[end].tail or "").strip().endswith("pro nobis!")):
        raise ValueError("first letter closing changed")
    if (number == 2 and not (children[end].tail or "").strip().endswith("vestram exaudiat!")):
        raise ValueError("second source ending changed")
    if tuple(node.get(XML_ID) for node in selected if node.tag == f"{TEI}pb") != pages:
        raise ValueError("internal letter pagination changed")
    if any(node.tag not in {f"{TEI}lb", f"{TEI}pb", f"{TEI}w", f"{TEI}hi"} for node in selected):
        raise ValueError("unsupported source child in letter")
    return selected, {
        "number": number, "source_child_start": start, "source_child_end": end,
        "source_heading_id": start_id, "source_last_line_id": last_line_id,
        "source_end_id": end_id, "following_heading_id": next_id,
        "following_boundary_page": "bsb00000830_00704" if number == 2 else None,
        "line_count": sum(node.tag == f"{TEI}lb" for node in selected),
        "internal_page_break": list(pages),
        "source_word_count": sum(node.tag == f"{TEI}w" for node in selected),
        "source_highlight_count": sum(node.tag == f"{TEI}hi" for node in selected),
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000830/tei/bsb00000830.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    expected_locator = f"raw/openmgh/bsb00000830/tei/bsb00000830.xml#{details['source_heading_id']}"
    if declared != expected_locator:
        raise ValueError("single catalog salutation locator differs")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    block = works[0][0]
    if block.tag != f"{TEI}ab" or block.text or len(block) != len(selected):
        raise ValueError("candidate letter block differs")
    if any(not _equal(a, b) for a, b in zip(selected, block, strict=True)):
        raise ValueError("candidate native source node changed")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate title differs")
    old_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_file is None or new_file is None:
        raise ValueError("source/candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = old_file.find(suffix), new_file.find(suffix)
        if old is None or new is None or not _equal(old, new, outer=True):
            raise ValueError("source publication or bibliography changed")
    return {"status": "pass", **details, "source_sha256": SOURCE_SHA256,
            "mapping": "exact native Marbod letter nodes, with shared collection heading and poem excluded"}
