"""Independent retained-source oracle for the bsb754 Vita abbatum edition."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
WORK_ID = "vita-sanctorum-abbatum-acaunensium"
SOURCE = "raw/openmgh/bsb00000754/tei/bsb00000754.xml"
SOURCE_SHA = "3349fbef5e7e957e964433d097e94a4a35d84addcbd6a314a88819e6a53039ff"
FIRST = "bsb00000754_00339_35"
LAST = "bsb00000754_00346_5"
SELECTED_C14N = "43abb822c60b21b6265f1666ca8b3f99b0158e42cc9a7242024dc0d8416e32c7"
OTHER_EDITION = f"{WORK_ID}-bsb00000750-electronic"
SELECTED_EDITION = f"{WORK_ID}-bsb00000754-electronic"


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


def _sha_json(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def source_work(source_bytes: bytes) -> tuple[etree._Element, dict]:
    if sha256(source_bytes).hexdigest() != SOURCE_SHA:
        raise ValueError("bsb754 retained XML hash changed")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 20:
        raise ValueError("bsb754 volume work inventory changed")
    selected = volumes[0][11]
    if (selected.tag != f"{TEI}div" or selected.get("type") != "work"
            or selected.get("n") != "Vita abbatum Acaunensium"
            or len(selected) != 1 or selected[0].tag != f"{TEI}ab"
            or volumes[0][10].get("n") != "Vita Sollemnis"
            or volumes[0][12].get("n") != "Vita Germani"):
        raise ValueError("bsb754 selected work or neighboring work changed")
    c14n = sha256(etree.tostring(selected, method="c14n", with_comments=True)).hexdigest()
    if c14n != SELECTED_C14N:
        raise ValueError("selected complete native work changed")
    ids = [node.get(XML_ID) for node in selected.iter() if node.get(XML_ID)]
    lines = selected.xpath(".//t:lb", namespaces=ns)
    pages = [(node.get(XML_ID), node.get("n")) for node in selected.xpath(".//t:pb", namespaces=ns)]
    if (not ids or len(ids) != len(set(ids)) or lines[0].get(XML_ID) != FIRST
            or lines[-1].get(XML_ID) != LAST
            or not " ".join(" ".join(selected.itertext()).split()).endswith("Amen.")
            or selected.xpath(".//t:gap|.//t:unclear", namespaces=ns)):
        raise ValueError("bsb754 native endpoints, ending, or clarity changed")
    occurrences = Counter(node.get(XML_ID) for node in root.iter() if node.get(XML_ID))
    if occurrences[FIRST] != 1 or occurrences[LAST] != 1:
        raise ValueError("catalog endpoints are not unique in retained XML")
    tags = {name: len(selected.xpath(f".//t:{name}", namespaces=ns))
            for name in ("ab", "pb", "lb", "w", "hi", "note", "gap", "unclear")}
    if tags != {"ab": 1, "pb": 8, "lb": 181, "w": 96, "hi": 3, "note": 0,
                "gap": 0, "unclear": 0}:
        raise ValueError("bsb754 Vita native feature profile changed")
    targets = [node.get("target") for node in selected.iter() if node.get("target")]
    if any(not target.startswith("#") or target[1:] not in ids for target in targets):
        raise ValueError("source fragment target escapes selected work")
    return selected, {
        "source_work_index": 11, "source_volume_works": 20,
        "source_child_start": 0, "source_child_end": 0,
        "source_heading_id": FIRST, "source_last_line_id": LAST, "source_end_id": LAST,
        "preceding_work_label": "Vita Sollemnis", "following_work_label": "Vita Germani",
        "source_page_count": len(pages), "internal_page_break": [id for id, _ in pages],
        "page_sequence_sha256": _sha_json(pages), "line_count": tags["lb"],
        "source_word_count": tags["w"], "source_highlight_count": tags["hi"],
        "selected_c14n_sha256": c14n, "source_xml_id_count": len(ids),
        "source_element_count": sum(isinstance(node.tag, str) for node in selected.iter()),
        "source_end_text": "Amen.",
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict) -> dict:
    selected, details = source_work(source_bytes)
    if work.get("work_id") != WORK_ID or len(work.get("textual_forms", [])) != 1:
        raise ValueError("Vita abbatum work identity changed")
    form = work["textual_forms"][0]
    editions = form.get("editions", [])
    if len(editions) != 2 or [item["edition_id"] for item in editions] != [OTHER_EDITION, SELECTED_EDITION]:
        raise ValueError("two-edition ordering or identity changed")
    edition = editions[1]
    if (edition["containing_source"]["locator"] != f"{SOURCE}#{FIRST}; {SOURCE}#{LAST}"
            or edition["acquisition_ids"] != [acquisition.get("acquisition_id")]
            or acquisition.get("edition_id") != SELECTED_EDITION
            or acquisition.get("source_path") != SOURCE
            or acquisition.get("source_sha256") != SOURCE_SHA):
        raise ValueError("bsb754 catalog locator or acquisition changed")
    source = _parse(source_bytes)
    candidate = _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    body = candidate.xpath("/t:TEI/t:text/t:body", namespaces=ns)
    if (len(body) != 1 or len(body[0]) != 1
            or candidate.get(XML_ID) != f"ocd-{WORK_ID}-bsb754-electronic-v1"
            or not _equal(selected, body[0][0], outer=True)):
        raise ValueError("candidate native whole work changed")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate title changed")
    old_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_file is None or new_file is None:
        raise ValueError("source/candidate header missing")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        original, copied = old_file.find(suffix), new_file.find(suffix)
        if original is None or copied is None or not _equal(original, copied, outer=True):
            raise ValueError("electronic publication or print bibliography changed")
    return {"status": "pass", "source_sha256": SOURCE_SHA, **details,
            "mapping": "complete bsb754 native work; bsb750 remains a separate unaccepted edition"}
