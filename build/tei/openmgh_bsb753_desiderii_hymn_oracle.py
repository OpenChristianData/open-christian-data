"""Independent retained-source oracle for the complete bsb753 Desiderii hymn part."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "550c090dad42988c5a8c95adc3328a3b5ef93dcfeaa8f91354fe6a03995f9b27"
HEADING = "bsb00000753_00071_10"
ENDING = "bsb00000753_00071_47"


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


def source_span(source_bytes: bytes, number: int) -> tuple[etree._Element, dict]:
    if number != 1 or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("bsb753 Desiderii selection or source hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 14:
        raise ValueError("bsb753 source volume changed")
    carrier = volumes[0][2]
    if (carrier.tag != f"{TEI}div" or carrier.get("type") != "work"
            or carrier.get("n") != "Pass. Des. ep. et Reginfr. diac. Alsegaudiensium"
            or len(carrier) != 2
            or any(part.tag != f"{TEI}div" or part.get("type") != "part"
                   or len(part) != 1 or part[0].tag != f"{TEI}ab" for part in carrier)):
        raise ValueError("Desiderii source carrier or two-part structure changed")
    previous, selected = carrier[0], carrier[1]
    if (previous[0][-1].get(XML_ID) != "bsb00000753_00071_9"
            or len(selected[0]) != 43 or selected[0].text != "\n"):
        raise ValueError("preceding prose or hymn part boundary changed")
    nodes = list(selected[0])
    if (nodes[0].tag != f"{TEI}lb" or nodes[0].get(XML_ID) != HEADING
            or nodes[1].tag != f"{TEI}hi" or nodes[1].get("rend") != "ITALICS"
            or nodes[1].text != "HYMNUS."
            or nodes[-1].tag != f"{TEI}lb" or nodes[-1].get(XML_ID) != ENDING
            or (nodes[-1].tail or "").strip() != "Amen."):
        raise ValueError("Desiderii hymn title or endpoint changed")
    profile = {"lb": 38, "hi": 1, "cb": 2, "anchor": 2}
    if {tag: sum(node.tag == f"{TEI}{tag}" for node in nodes) for tag in profile} != profile:
        raise ValueError("hymn native node profile changed")
    columns = [node for node in nodes if node.tag == f"{TEI}cb"]
    anchors = [node for node in nodes if node.tag == f"{TEI}anchor"]
    if ([(node.get("type"), node.get("n"), node.get("spanTo")) for node in columns]
            != [("sequential", "1", "#cb1"), ("sequential", "2", "#cb2")]
            or [node.get(XML_ID) for node in anchors] != ["cb1", "cb2"]
            or [nodes.index(node) for node in columns] != [2, 20]
            or [nodes.index(node) for node in anchors] != [19, 37]):
        raise ValueError("hymn column spans or anchors changed")
    ids = [node.get(XML_ID) for node in nodes if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate hymn IDs")
    return selected, {
        "number": number, "source_child_start": 0, "source_child_end": 42,
        "source_heading_id": HEADING, "source_last_line_id": ENDING,
        "source_end_id": ENDING, "following_heading_id": None,
        "following_boundary_page": None, "line_count": 38,
        "internal_page_break": [], "source_word_count": 0,
        "source_highlight_count": 1, "source_column_break_count": 2,
        "source_anchor_count": 2, "source_carrier_division_index": 2,
        "source_part_index": 1,
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000753/tei/bsb00000753.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    path = "raw/openmgh/bsb00000753/tei/bsb00000753.xml"
    if declared != f"{path}#{HEADING}; {path}#{ENDING}":
        raise ValueError("catalog hymn endpoints differ")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    part = works[0][0]
    if not _equal(selected, part):
        raise ValueError("candidate native hymn part changed")
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
            "mapping": "exact second native Desiderii hymn part, including highlight, columns, and anchors; preceding prose part excluded"}
