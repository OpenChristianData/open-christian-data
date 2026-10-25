"""Independent source oracle for the exact bsb754 Vita Rigoberti selection."""

from __future__ import annotations

from hashlib import sha256

from lxml import etree


SOURCE_PATH = "raw/openmgh/bsb00000754/tei/bsb00000754.xml"
SOURCE_SHA256 = "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
FIRST_CHILD = 279
LAST_CHILD = 1150
NEXT_CHILD = 1151
SOURCE_CHILD_COUNT = 1249
PRINTED_CONTENTS_URL = "https://d-nb.info/790379252/04"


def _parse(data: bytes, label: str) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        huge_tree=True,
    )
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError(f"DOCTYPE is forbidden in {label}")
    return root


def _signature(node: etree._Element) -> tuple[object, ...]:
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text,
        node.tail,
        tuple(_signature(child) for child in node),
    )


def _text(node: etree._Element) -> str:
    return "".join(node.itertext())


def check_candidate(source_bytes: bytes, candidate_bytes: bytes) -> dict[str, object]:
    """Check the candidate against independently pinned source boundaries."""

    source_hash = sha256(source_bytes).hexdigest()
    if source_hash != SOURCE_SHA256:
        raise ValueError("retained extracted XML hash differs")

    source = _parse(source_bytes, "retained extracted XML")
    candidate = _parse(candidate_bytes, "candidate TEI")
    source_ns = {"t": TEI_NS}
    carriers = source.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='volume']"
        "/t:div[@n='Vita Eucherii']/t:ab",
        namespaces=source_ns,
    )
    if len(carriers) != 1:
        raise ValueError("the single flat bsb754 carrier is missing or ambiguous")
    children = list(carriers[0])
    if len(children) != SOURCE_CHILD_COUNT:
        raise ValueError("flat bsb754 carrier child count changed")

    start = children[FIRST_CHILD]
    numeral_i = children[FIRST_CHILD + 1]
    capitula = children[FIRST_CHILD + 2]
    vita_heading = children[447]
    last = children[LAST_CHILD]
    numeral_ii = children[NEXT_CHILD]
    translation_opening = children[NEXT_CHILD + 1]
    numeral_iii = children[1222]
    if (
        start.tag != f"{{{TEI_NS}}}pb"
        or start.get(XML_ID) != "bsb00000754_00068"
        or numeral_i.tag != f"{{{TEI_NS}}}lb"
        or numeral_i.get(XML_ID) != "bsb00000754_00068_18"
        or (numeral_i.tail or "").strip() != "I."
        or capitula.get(XML_ID) != "bsb00000754_00068_19"
        or "sequentis opusculi de vita et" not in (capitula.tail or "")
        or vita_heading.get(XML_ID) != "bsb00000754_00071_28"
        or "INCIPIT VITA SANCTI RIGOBERTI" not in (vita_heading.tail or "")
        or last.tag != f"{{{TEI_NS}}}lb"
        or last.get(XML_ID) != "bsb00000754_00088_12"
        or (last.tail or "").strip() != "saeculorum. Amen."
        or numeral_ii.get(XML_ID) != "bsb00000754_00088_13"
        or (numeral_ii.tail or "").strip() != "II."
        or "DCCCXCIIII" not in (translation_opening.tail or "")
        or numeral_iii.get(XML_ID) != "bsb00000754_00090_1"
        or (numeral_iii.tail or "").strip() != "III."
    ):
        raise ValueError("pinned Vita, translation, or neighboring boundaries changed")

    candidate_ns = {"t": TEI_NS}
    candidate_bodies = candidate.xpath(
        "/t:TEI/t:text/t:body/t:div[@type='work']/t:ab",
        namespaces=candidate_ns,
    )
    if len(candidate_bodies) != 1:
        raise ValueError("candidate must contain one source-native work division")
    represented = list(candidate_bodies[0])
    expected = children[FIRST_CHILD : LAST_CHILD + 1]
    if len(represented) != len(expected) or any(
        _signature(actual) != _signature(wanted)
        for actual, wanted in zip(represented, expected, strict=True)
    ):
        raise ValueError("candidate content differs from the complete source Vita span")

    source_header = source.find(f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc")
    candidate_header = candidate.find(f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc")
    if source_header is None or candidate_header is None:
        raise ValueError("source or candidate file description is missing")
    source_publication = source_header.find(f"{{{TEI_NS}}}publicationStmt")
    candidate_publication = candidate_header.find(f"{{{TEI_NS}}}publicationStmt")
    source_bibliography = source_header.find(
        f"{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}biblFull"
    )
    candidate_bibliography = candidate_header.find(
        f"{{{TEI_NS}}}sourceDesc/{{{TEI_NS}}}biblFull"
    )
    if any(
        node is None
        for node in (
            source_publication,
            candidate_publication,
            source_bibliography,
            candidate_bibliography,
        )
    ):
        raise ValueError("source publication statement or print bibliography is missing")
    if (
        _signature(source_publication) != _signature(candidate_publication)
        or _signature(source_bibliography) != _signature(candidate_bibliography)
    ):
        raise ValueError("candidate does not preserve source publication and bibliography")

    selected = expected
    page_break_ids = [
        node.get(XML_ID)
        for node in selected
        if node.tag == f"{{{TEI_NS}}}pb"
    ]
    return {
        "checker": "ocd-openmgh-bsb754-rigoberti-source-oracle-v1",
        "source_path": SOURCE_PATH,
        "source_sha256": source_hash,
        "source_carrier": "volume/Vita Eucherii/ab",
        "source_child_count": len(children),
        "selection": {
            "first_child_index": FIRST_CHILD,
            "last_child_index_inclusive": LAST_CHILD,
            "child_count": len(selected),
            "first_id": start.get(XML_ID),
            "last_id": last.get(XML_ID),
            "last_source_text": (last.tail or "").strip(),
        },
        "boundary_evidence": {
            "vita_numeral_id": numeral_i.get(XML_ID),
            "capitula_locator_id": capitula.get(XML_ID),
            "vita_heading_id": vita_heading.get(XML_ID),
            "vita_final_line_id": last.get(XML_ID),
            "next_section_id": numeral_ii.get(XML_ID),
            "next_section_marker": (numeral_ii.tail or "").strip(),
            "next_section_opening_id": translation_opening.get(XML_ID),
            "following_translation_id": numeral_iii.get(XML_ID),
            "printed_contents_url": PRINTED_CONTENTS_URL,
            "printed_contents_summary": (
                "The MGH contents distinguish Vita (pp. 58-78), "
                "Translatio a. 894 (pp. 78-79), and Translatio brachii (p. 80)."
            ),
        },
        "structure": {
            "line_markers": sum(
                node.tag == f"{{{TEI_NS}}}lb" for node in selected
            ),
            "page_breaks": page_break_ids,
            "page_break_count": len(page_break_ids),
            "word_nodes": sum(
                node.tag == f"{{{TEI_NS}}}w" for node in selected
            ),
            "highlights": sum(
                node.tag == f"{{{TEI_NS}}}hi" for node in selected
            ),
        },
        "candidate_sha256": sha256(candidate_bytes).hexdigest(),
        "candidate_source_tree_match": "pass",
        "source_header_license_and_bibliography_match": "pass",
    }
