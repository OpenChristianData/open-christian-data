"""Independent retained-source oracle for the bsb754 Vita Eucherii."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
HEADING = "bsb00000754_00056_27"
ENDING = "bsb00000754_00063_27"
PAGES = ("bsb00000754_00056", "bsb00000754_00057", "bsb00000754_00058",
         "bsb00000754_00059", "bsb00000754_00060", "bsb00000754_00061",
         "bsb00000754_00062", "bsb00000754_00063")


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
    if number != 1 or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("bsb754 Eucherii selection or source hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 20:
        raise ValueError("bsb754 source volume changed")
    carrier = volumes[0][2]
    if (carrier.tag != f"{TEI}div" or carrier.get("type") != "work"
            or carrier.get("n") != "Vita Eucherii"
            or len(carrier) != 1 or carrier[0].tag != f"{TEI}ab"
            or len(carrier[0]) != 1249):
        raise ValueError("bsb754 Eucherii carrier changed")
    children = list(carrier[0])
    selected = children[:279]
    if (selected[0].tag != f"{TEI}pb" or selected[0].get(XML_ID) != PAGES[0]
            or selected[1].get(XML_ID) != HEADING
            or selected[2].tag != f"{TEI}hi"
            or not (selected[2].text or "").startswith("INCIPIT VITA SANCTI AC BEATISSIMI EUCHERII")
            or selected[4].tag != f"{TEI}hi"
            or selected[-1].get(XML_ID) != ENDING
            or (selected[-1].tail or "").strip()
               != "EXPLICIT VITA SANCTI EUCHERII EPISCOPI ET CONFESSORIS."
            or children[279].get(XML_ID) != "bsb00000754_00068"
            or children[280].get(XML_ID) != "bsb00000754_00068_18"
            or (children[280].tail or "").strip() != "I."
            or children[281].get(XML_ID) != "bsb00000754_00068_19"
            or not (children[281].tail or "").strip().startswith("Capitula hic supponuntur")):
        raise ValueError("Eucherii title, explicit, or following Rigoberti boundary changed")
    profile = {"lb": 189, "w": 80, "pb": 8, "hi": 2}
    if {tag: sum(node.tag == f"{TEI}{tag}" for node in selected) for tag in profile} != profile:
        raise ValueError("Eucherii native node profile changed")
    if ([(node.get(XML_ID), node.get("n")) for node in selected if node.tag == f"{TEI}pb"]
            != list(zip(PAGES, map(str, range(46, 54)), strict=True))):
        raise ValueError("Eucherii native pagination changed")
    ids = [node.get(XML_ID) for node in selected if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Eucherii IDs")
    return selected, {
        "number": number, "source_child_start": 0, "source_child_end": 278,
        "source_heading_id": HEADING, "source_last_line_id": ENDING,
        "source_end_id": ENDING, "following_heading_id": "bsb00000754_00068_19",
        "following_boundary_page": "bsb00000754_00068", "line_count": 189,
        "internal_page_break": list(PAGES), "source_word_count": 80,
        "source_highlight_count": 2, "source_carrier_division_index": 2,
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000754/tei/bsb00000754.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    path = "raw/openmgh/bsb00000754/tei/bsb00000754.xml"
    if declared != f"{path}#{HEADING}; {path}#{ENDING}":
        raise ValueError("catalog Eucherii endpoints differ")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    block = works[0][0]
    if block.tag != f"{TEI}ab" or block.text or len(block) != len(selected):
        raise ValueError("candidate Eucherii block differs")
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
            "mapping": "exact Vita Eucherii nodes, including leading and internal page breaks; following Rigoberti matter excluded"}
