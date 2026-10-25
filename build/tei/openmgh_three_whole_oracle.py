"""Independent exact-source oracle for three single-work openMGH volumes."""

from __future__ import annotations

from hashlib import sha256
import json

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
PROFILES = {
    "alexander-minorita-expositio-in-apocalypsim": {
        "bsb": "bsb00000626", "source_sha256": "f596d9710a838a09005292f2304d7658614a2e9432e8ed15635c8f9c538e0aa4",
        "title": "Alexander Minorita, Expositio in Apocalypsim", "native_label": "Alex. Minorita",
        "children": 24, "heading_id": "bsb00000626_00061_1", "heading_text": "CAPITULA EXPOSITIONIS IN APOCALYPSIM.",
        "end_id": "bsb00000626_00570_28", "ending": "bona tibi.",
        "counts": {"div": 25, "ab": 24, "pb": 510, "lb": 14970, "w": 6218, "hi": 6673},
        "page_first": "bsb00000626_00061", "page_last": "bsb00000626_00570",
        "edge_sha256": "da8445ff917e68555431daf92a9cf3022106037f06a712feaf9898a68e9620f7",
        "pages_sha256": "a0d0f1a104cdd9d8e852fa9774ddc130537618c16d8b7a5fd7d4643e18deb8b5",
    },
    "gregory-of-tours-libri-historiarum-x": {
        "bsb": "bsb00000747", "source_sha256": "75036def8d9e57260daf2bbc7b1d51b73e2f5d20d3a580db402eb39a090086f0",
        "title": "Gregorii Turonensis Opera. Teil 1: Libri historiarum X", "native_label": "Greg. Tur. hist.",
        "children": 11, "heading_id": "bsb00000747_00043_1", "heading_text": "GREGORII PRAEFATIO PRIMA INCIPIT.",
        "end_id": "bsb00000747_00579_10", "ending": "EXPLICIT IN CHRISTI NOMINE LIBER HISTORIARUM DECIMUS.",
        "counts": {"div": 32, "ab": 21, "pb": 536, "lb": 11151, "w": 4660, "hi": 1162},
        "page_first": "bsb00000747_00043", "page_last": "bsb00000747_00579",
        "edge_sha256": "41d41c9c75ac25a56c3949a8c6a2467e8c937b1b1563bdcc3e74c59f67dcc54c",
        "pages_sha256": "565b7552a5a0bbd079f14d784fbcb14b7616d42fbd57870daf311db31898ddef",
    },
    "vita-anskarii-auctore-rimberto": {
        "bsb": "bsb00000703", "source_sha256": "44517a090c08145812fb06f6bfc9d693363acaefa667e9c4857380bdb4b08f7c",
        "title": "Vita Anskarii auctore Rimberto", "native_label": "Vita Anskarii",
        "children": 2, "heading_id": "bsb00000703_00013_1", "heading_text": "INCIPIUNT CAPITULA LIBRI SEQUENTIS.",
        "end_id": "bsb00000703_00100_17", "ending": "regnat in aeternum.",
        "counts": {"div": 3, "ab": 2, "pb": 87, "lb": 3322, "w": 1886, "hi": 424},
        "page_first": "bsb00000703_00013", "page_last": "bsb00000703_00100",
        "edge_sha256": "de50fb25d75793b1f5d1e561d905035796d762c05da0f0a65ad50d9f01dc6a98",
        "pages_sha256": "ea7ad6cb6b4aabf4e894712eedfac94b0d47f676e75fc10f13d619a9804a9f97",
    },
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


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def source_span(source_bytes: bytes, work_id: str) -> tuple[etree._Element, dict]:
    profile = PROFILES[work_id]
    if sha256(source_bytes).hexdigest() != profile["source_sha256"]:
        raise ValueError(f"retained source hash changed: {work_id}")
    root = _parse(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = root.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 1:
        raise ValueError(f"single-work volume changed: {work_id}")
    selected = volumes[0][0]
    if (selected.tag != f"{TEI}div" or selected.get("type") != "work"
            or selected.get("n") != profile["native_label"]
            or len(selected) != profile["children"]
            or any(child.tag != f"{TEI}div" or child.get("type") != "part"
                   for child in selected)):
        raise ValueError(f"native whole-work structure changed: {work_id}")
    nodes = list(selected.iter())
    counts = {tag: sum(node.tag == f"{TEI}{tag}" for node in nodes)
              for tag in profile["counts"]}
    if counts != profile["counts"]:
        raise ValueError(f"native node profile changed: {work_id}")
    ids = [node.get(XML_ID) for node in nodes if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate source IDs: {work_id}")
    edges = []
    for child in selected:
        child_ids = [node.get(XML_ID) for node in child.iter() if node.get(XML_ID)]
        edges.append([child.tag.split("}")[-1], child.get("type"), len(child),
                      child_ids[0], child_ids[-1]])
    if _digest(edges) != profile["edge_sha256"]:
        raise ValueError(f"native child edges changed: {work_id}")
    pages = [[node.get(XML_ID), node.get("n")] for node in nodes if node.tag == f"{TEI}pb"]
    if (_digest(pages) != profile["pages_sha256"]
            or pages[0][0] != profile["page_first"]
            or pages[-1][0] != profile["page_last"]):
        raise ValueError(f"source page sequence changed: {work_id}")
    lines = [node for node in nodes if node.tag == f"{TEI}lb"]
    if (lines[0].get(XML_ID) != profile["heading_id"]
            or (lines[0].tail or "").strip() != profile["heading_text"]
            or lines[-1].get(XML_ID) != profile["end_id"]
            or not "".join(selected.itertext()).rstrip().endswith(profile["ending"])):
        raise ValueError(f"work heading or ending changed: {work_id}")
    return selected, {
        "work_id": work_id, "source_sha256": profile["source_sha256"],
        "source_child_start": 0, "source_child_end": profile["children"] - 1,
        "source_heading_id": profile["heading_id"],
        "source_last_line_id": profile["end_id"], "source_end_id": profile["end_id"],
        "source_native_label": profile["native_label"], "source_part_count": profile["children"],
        "line_count": profile["counts"]["lb"], "source_word_count": profile["counts"]["w"],
        "source_highlight_count": profile["counts"]["hi"],
        "internal_page_break": [page[0] for page in pages],
        "source_page_count": len(pages), "child_edges_sha256": profile["edge_sha256"],
        "page_sequence_sha256": profile["pages_sha256"],
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes,
                    work: dict, acquisition: dict, *, work_id: str) -> dict:
    profile = PROFILES[work_id]
    selected, details = source_span(source_bytes, work_id)
    path = f"raw/openmgh/{profile['bsb']}/tei/{profile['bsb']}.xml"
    if (acquisition.get("source_path") != path
            or acquisition.get("source_sha256") != profile["source_sha256"]
            or work.get("work_id") != work_id or work.get("title") != profile["title"]):
        raise ValueError(f"catalog/acquisition identity changed: {work_id}")
    locator = work["textual_forms"][0]["editions"][0]["containing_source"]["locator"]
    expected = f"{path}#teiHeader/fileDesc/sourceDesc/biblFull/titleStmt/title"
    if work_id == "vita-anskarii-auctore-rimberto":
        expected = f"{path}#{profile['heading_id']}; {path}#{profile['end_id']}; {expected}"
    if locator != expected:
        raise ValueError(f"catalog locator changed: {work_id}")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or not _equal(selected, works[0]):
        raise ValueError(f"candidate native whole work changed: {work_id}")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError(f"candidate title changed: {work_id}")
    old_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_file is None or new_file is None:
        raise ValueError("source/candidate header missing")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = old_file.find(suffix), new_file.find(suffix)
        if old is None or new is None or not _equal(old, new, outer=True):
            raise ValueError(f"publication or bibliography changed: {work_id}")
    return {"status": "pass", **details,
            "mapping": "complete sole native work division with all source parts and markers"}
