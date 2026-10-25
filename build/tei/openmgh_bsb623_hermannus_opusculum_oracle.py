"""Independent retained-source oracle for the complete bsb623 Hermannus opusculum part."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "58d0cc06b721ca3f9374fdb96ab120eceedf968e442eea341e8c6c24883c7e13"
HEADING = "bsb00000623_00077_13"
LAST_LINE = "bsb00000623_00134_7"
PRECEDING_EPISLE_END = "bsb00000623_00077_12"


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
        raise ValueError("bsb623 Hermannus selection or source hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 1:
        raise ValueError("bsb623 source volume changed")
    carrier = volumes[0][0]
    if (carrier.tag != f"{TEI}div" or carrier.get("type") != "work"
            or carrier.get("n") != "Herm. Jud. opusc." or len(carrier) != 3
            or carrier[0].tag != f"{TEI}ab" or len(carrier[0]) != 3
            or carrier[1].tag != f"{TEI}div" or carrier[1].get("type") != "part"
            or carrier[2].tag != f"{TEI}div" or carrier[2].get("type") != "part"):
        raise ValueError("Hermannus shared carrier structure changed")
    shared = list(carrier[0])
    if ([node.get(XML_ID) for node in shared]
            != ["bsb00000623_00076", "bsb00000623_00076_1", "bsb00000623_00076_2"]
            or (shared[1].tail or "").strip() != "HERMANNUS QUONDAM JUDAEUS"
            or (shared[2].tail or "").strip() != "OPUSCULUM DE CONVERSIONE SUA"):
        raise ValueError("Hermannus shared title changed")
    preceding = carrier[1]
    if (len(preceding) != 1 or preceding[0].tag != f"{TEI}ab"
            or preceding[0][-1].get(XML_ID) != PRECEDING_EPISLE_END
            or (preceding[0][-1].tail or "").strip() != "Explicit epistola."):
        raise ValueError("preceding epistle boundary changed")
    selected = carrier[2]
    if (len(selected) != 22 or selected[0].tag != f"{TEI}ab"
            or len(selected[0]) != 4 or selected[0][0].get(XML_ID) != HEADING
            or (selected[0][0].tail or "").strip()
               != "In nomine Domini incipit bone memorie fratris"
            or any(section.tag != f"{TEI}div" or section.get("type") != "section"
                   or len(section) != 1 or section[0].tag != f"{TEI}ab"
                   for section in selected[1:])):
        raise ValueError("Hermannus opusculum section boundary changed")
    ending = selected[-1][0]
    if (ending[-2].tag != f"{TEI}w" or ending[-2].get(XML_ID) != "w644"
            or ending[-1].tag != f"{TEI}hi"
            or (ending[-1].tail or "").strip()
               != "qui vivit et regnat in secula seculorum. Amen."):
        raise ValueError("Hermannus opusculum ending changed")
    nodes = list(selected.iter())
    profile = {"lb": 1453, "w": 634, "hi": 360, "pb": 57, "div": 22, "ab": 22}
    if {tag: sum(node.tag == f"{TEI}{tag}" for node in nodes) for tag in profile} != profile:
        raise ValueError("Hermannus opusculum node profile changed")
    pages = [node for node in nodes if node.tag == f"{TEI}pb"]
    expected_pages = [f"bsb00000623_{page:05d}" for page in range(78, 135)]
    if ([node.get(XML_ID) for node in pages] != expected_pages
            or [node.get("n") for node in pages] != [str(page) for page in range(71, 128)]
            or [node.get(XML_ID) for node in nodes if node.tag == f"{TEI}lb"][-1]
               != LAST_LINE):
        raise ValueError("Hermannus opusculum pagination or last line changed")
    ids = [node.get(XML_ID) for node in nodes if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate Hermannus opusculum IDs")
    return selected, {
        "number": number, "source_child_start": 0, "source_child_end": 21,
        "source_heading_id": HEADING, "source_last_line_id": LAST_LINE,
        "source_end_id": LAST_LINE, "preceding_epistle_end_id": PRECEDING_EPISLE_END,
        "following_heading_id": None, "following_boundary_page": None,
        "section_count": 21, "line_count": 1453,
        "internal_page_break": expected_pages, "source_word_count": 634,
        "source_highlight_count": 360, "source_carrier_division_index": 0,
        "source_part_index": 2,
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000623/tei/bsb00000623.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    path = "raw/openmgh/bsb00000623/tei/bsb00000623.xml"
    if (work.get("title") != "Hermannus quondam Iudaeus, Opusculum de conversione sua"
            or declared != f"{path}#teiHeader/fileDesc/sourceDesc/biblFull/titleStmt/title"):
        raise ValueError("catalog opusculum identity differs")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    part = works[0][0]
    if not _equal(selected, part):
        raise ValueError("candidate native Hermannus opusculum changed")
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
            "mapping": "complete second native Hermannus part, including opening and 21 sections; preceding epistle excluded"}
