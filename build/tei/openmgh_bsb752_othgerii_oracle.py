"""Independent retained-source oracle for the complete bsb752 Othgerii prose part."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "620b80ade431a814ebf41296cdf88476d9a39741cdba1925c0cd75fb9772c98a"
HEADING = "bsb00000752_00212_1"
ENDING = "bsb00000752_00214_35"
PAGES = ("bsb00000752_00212", "bsb00000752_00213", "bsb00000752_00214")


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
    if number != 3 or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("bsb752 Othgerii selection or source hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 26:
        raise ValueError("bsb752 source volume changed")
    carrier = volumes[0][8]
    if (carrier.tag != f"{TEI}div" or carrier.get("type") != "work"
            or carrier.get("n") != "Vita Faronis ep. Meldensis"
            or len(carrier) != 4
            or any(part.tag != f"{TEI}div" or part.get("type") != "part"
                   or len(part) != 1 or part[0].tag != f"{TEI}ab" for part in carrier)):
        raise ValueError("Faronis source carrier or four-part structure changed")
    previous, selected = carrier[2], carrier[3]
    if (previous[0][-1].get(XML_ID) != "bsb00000752_00211_30"
            or (previous[0][-1].tail or "").strip()
               != "EXPLICIT VITA SANCTI FARONIS EPISCOPI ET CONFESSORIS."
            or len(selected[0]) != 182 or selected[0].text != "\n"):
        raise ValueError("preceding Faronis or Othgerii part boundary changed")
    nodes = list(selected[0])
    if (nodes[0].tag != f"{TEI}pb" or nodes[0].get(XML_ID) != PAGES[0]
            or nodes[1].tag != f"{TEI}lb" or nodes[1].get(XML_ID) != HEADING
            or (nodes[1].tail or "").strip() != "CONVERSIO OTHGERII MILITIS, QUALITER ABRENUNTIANS"
            or nodes[2].get(XML_ID) != "bsb00000752_00212_2"
            or (nodes[2].tail or "").strip() != "SAECULO, DEO IN MONASTICO HABITU MILITAVIT."
            or nodes[-1].tag != f"{TEI}lb" or nodes[-1].get(XML_ID) != ENDING
            or (nodes[-1].tail or "").strip() != "EXPLICIT."):
        raise ValueError("Othgerii title or endpoint changed")
    profile = {"lb": 115, "w": 56, "hi": 8, "pb": 3}
    if {tag: sum(node.tag == f"{TEI}{tag}" for node in nodes) for tag in profile} != profile:
        raise ValueError("Othgerii native node profile changed")
    if ([(i, node.get(XML_ID), node.get("n")) for i, node in enumerate(nodes)
         if node.tag == f"{TEI}pb"]
            != [(0, PAGES[0], "204"), (70, PAGES[1], "205"),
                (134, PAGES[2], "206")]):
        raise ValueError("Othgerii native pagination changed")
    ids = [node.get(XML_ID) for node in nodes if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Othgerii IDs")
    return selected, {
        "number": number, "source_child_start": 0, "source_child_end": 181,
        "source_heading_id": HEADING, "source_last_line_id": ENDING,
        "source_end_id": ENDING, "following_heading_id": None,
        "following_boundary_page": None, "line_count": 115,
        "internal_page_break": list(PAGES), "source_word_count": 56,
        "source_highlight_count": 8, "source_column_break_count": 0,
        "source_anchor_count": 0, "source_carrier_division_index": 8,
        "source_part_index": 3,
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000752/tei/bsb00000752.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    path = "raw/openmgh/bsb00000752/tei/bsb00000752.xml"
    if declared != f"{path}#{HEADING}; {path}#{ENDING}":
        raise ValueError("catalog Othgerii endpoints differ")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    part = works[0][0]
    if not _equal(selected, part):
        raise ValueError("candidate native Othgerii part changed")
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
            "mapping": "exact fourth native Othgerii prose part, including words, highlights, and pages; preceding Faronis parts excluded"}
