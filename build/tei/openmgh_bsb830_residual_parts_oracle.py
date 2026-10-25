"""Independent complete-part oracle for two bsb830 residual full native parts."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "bb97bf6037a31d6a6c37f0e967aa23e9df1933bdd688fe4aaa84e5e034ff67ac"
SELECTIONS = {
    "anonymous-priest-letter-to-innocent-on-secular-and-regular-clergy": (
        1, "bsb00000830_00210_23", "bsb00000830_00247_36",
        ("II.", "EPISTOLA AD INNOCENTIUM PAPAM MISSA QUID DISTET",
         "INTER CLERICOS SECULARES ET REGULARES."), 0,
    ),
    "gerhoh-commentary-on-psalms": (
        9, "bsb00000830_00419_25", "bsb00000830_00510_44",
        ("X.", "EX COMMENTARIO IN PSALMOS."), 17,
    ),
}


def _parse(content: bytes) -> etree._Element:
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True,
                                                      remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("bsb830 source/candidate DOCTYPE is forbidden")
    return root


def _c14n(node: etree._Element) -> bytes:
    detached = deepcopy(node)
    etree.cleanup_namespaces(detached)
    return etree.tostring(detached, method="c14n", with_comments=True)


def check(source_bytes: bytes, candidate_bytes: bytes, work: dict, acquisition: dict) -> dict:
    work_id = work.get("work_id")
    if work_id not in SELECTIONS:
        raise ValueError("work outside two bsb830 residual-part scope")
    index, start_id, end_id, headings, section_count = SELECTIONS[work_id]
    if sha256(source_bytes).hexdigest() != SOURCE_SHA or acquisition.get("source_sha256") != SOURCE_SHA:
        raise ValueError("bsb830 extracted XML/acquisition binding differs")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 29 or any(node.tag != f"{TEI}div" for node in volumes[0]):
        raise ValueError("bsb830 29-division source envelope differs")
    carrier = volumes[0][6]
    if (carrier.get("n") != "Gerhohi praepos. Reichersb. libelli sel." or len(carrier) != 11
            or any(node.tag != f"{TEI}div" or node.get("type") != "part" for node in carrier)):
        raise ValueError("bsb830 eleven-part Gerhoh carrier differs")
    selected = carrier[index]
    if (len(selected) != section_count + 1 or selected[0].tag != f"{TEI}ab"
            or any(node.tag != f"{TEI}div" or node.get("type") != "section" for node in selected[1:])):
        raise ValueError("selected bsb830 part shape differs")
    ids = [node.get(XML_ID) for node in selected.iter()
           if (node.get(XML_ID) or "").startswith("bsb00000830_")]
    if len(ids) != len(set(ids)) or start_id not in ids or ids.index(start_id) > 1 or ids[-1] != end_id:
        raise ValueError("catalog endpoints do not bound complete Gerhoh part")
    first_lines = [node for node in selected.iter() if node.tag == f"{TEI}lb"][:len(headings)]
    if (len(first_lines) != len(headings) or first_lines[0].get(XML_ID) != start_id
            or tuple((node.tail or "").strip() for node in first_lines) != headings):
        raise ValueError("literal bsb830 part heading differs")
    prefix = "raw/openmgh/bsb00000830/tei/bsb00000830.xml#"
    editions = work.get("textual_forms", [{}])[0].get("editions", [])
    if (len(editions) != 1 or editions[0].get("containing_source", {}).get("locator")
            != f"{prefix}{start_id}; {prefix}{end_id}"):
        raise ValueError("Gerhoh catalog locator differs")
    wrappers = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(wrappers) != 1 or wrappers[0].get("n") != work["title"] or len(wrappers[0]) != 1:
        raise ValueError("Gerhoh candidate wrapper differs")
    if _c14n(wrappers[0][0]) != _c14n(selected):
        raise ValueError("complete native Gerhoh source part differs")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("Gerhoh candidate title differs")
    original = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    copied = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original is None or copied is None:
        raise ValueError("Gerhoh source or candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = original.find(suffix), copied.find(suffix)
        if old is None or new is None or _c14n(old) != _c14n(new):
            raise ValueError("Gerhoh publication or bibliography differs")
    return {
        "status": "pass", "work_id": work_id, "source_sha256": SOURCE_SHA,
        "source_work_div_index": 6, "source_part_index": index,
        "source_part_c14n_sha256": sha256(_c14n(selected)).hexdigest(),
        "source_start_id": start_id, "source_end_id": end_id,
        "source_lb_count": len(selected.findall(f".//{TEI}lb")),
        "source_pb_count": len(selected.findall(f".//{TEI}pb")),
        "sibling_part_count": len(carrier) - 1,
        "source_section_count": section_count,
    }
