"""Independent retained-source oracle for the bsb830 Marbod poem."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree

TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA256 = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
PAGES = ("bsb00000830_00704", "bsb00000830_00705")
HEADING = "bsb00000830_00704_1"
ENDING = "bsb00000830_00705_10"


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
    if number != 2 or sha256(source_bytes).hexdigest() != SOURCE_SHA256:
        raise ValueError("bsb830 Marbod poem selection or source hash changed")
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
    if (children[169].get(XML_ID) != "bsb00000830_00703_38"
            or not (children[169].tail or "").strip().endswith("vestram exaudiat!")):
        raise ValueError("preceding letter endpoint changed")
    selected = children[170:224]
    if (len(selected) != 54 or selected[0].tag != f"{TEI}pb"
            or selected[0].get(XML_ID) != PAGES[0]
            or selected[1].tag != f"{TEI}lb" or selected[1].get(XML_ID) != HEADING
            or (selected[1].tail or "").strip() != "II."
            or (selected[2].tail or "").strip() != "Roma beata nimis, quae sic excrevit ab imis,"
            or selected[-1].get(XML_ID) != ENDING
            or (selected[-1].tail or "").strip() != "Nostros oratus audi solvendo reatus!"
            or tuple(node.get(XML_ID) for node in selected if node.tag == f"{TEI}pb") != PAGES
            or any(node.tag not in {f"{TEI}lb", f"{TEI}pb"} for node in selected)):
        raise ValueError("poem heading, body, page breaks, or endpoint changed")
    ids = [node.get(XML_ID) for node in selected]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("poem node IDs absent or duplicate")
    return selected, {
        "number": number, "source_child_start": 170, "source_child_end": 223,
        "source_heading_id": HEADING, "source_last_line_id": ENDING,
        "source_end_id": ENDING, "following_heading_id": None,
        "following_boundary_page": None, "line_count": 52,
        "internal_page_break": list(PAGES), "source_word_count": 0,
        "source_highlight_count": 0,
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, number: int) -> dict:
    selected, details = source_span(source_bytes, number)
    if (acquisition.get("source_sha256") != SOURCE_SHA256
            or acquisition.get("source_path") != "raw/openmgh/bsb00000830/tei/bsb00000830.xml"):
        raise ValueError("acquisition/source binding changed")
    declared = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    path = "raw/openmgh/bsb00000830/tei/bsb00000830.xml"
    if declared != f"{path}#{HEADING}; {path}#{ENDING}":
        raise ValueError("catalog poem endpoints differ")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or works[0].get("n") != work["title"] or len(works[0]) != 1:
        raise ValueError("candidate work wrapper differs")
    block = works[0][0]
    if block.tag != f"{TEI}ab" or block.text or len(block) != len(selected):
        raise ValueError("candidate poem block differs")
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
            "mapping": "exact native Marbod poem nodes, including its leading page break; letters and shared heading excluded"}
