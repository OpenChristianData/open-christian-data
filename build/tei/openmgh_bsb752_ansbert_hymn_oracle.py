"""Independent exact-part oracle for the bsb752 Ansbert hymn."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "620b80ade431a814ebf41296cdf88476d9a39741cdba1925c0cd75fb9772c98a"
START_ID = "bsb00000752_00649_15"
END_ID = "bsb00000752_00651_30"


def _tree(data: bytes) -> etree._Element:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                    remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("bsb752 source/candidate DOCTYPE is forbidden")
    return root


def _canonical(node: etree._Element) -> bytes:
    detached = deepcopy(node)
    etree.cleanup_namespaces(detached)
    return etree.tostring(detached, method="c14n", with_comments=True)


def check(source_bytes: bytes, candidate_bytes: bytes, work: dict, acquisition: dict) -> dict:
    if sha256(source_bytes).hexdigest() != SOURCE_SHA or acquisition.get("source_sha256") != SOURCE_SHA:
        raise ValueError("Ansbert extracted XML binding differs")
    source, candidate = _tree(source_bytes), _tree(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    volume = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volume) != 1 or len(volume[0]) != 26 or any(child.tag != f"{TEI}div" for child in volume[0]):
        raise ValueError("bsb752 volume division envelope differs")
    carrier = volume[0][19]
    if carrier.get("n") != "Vita Ansberti ep. Rotomagensis" or len(carrier) != 3:
        raise ValueError("Ansbert carrier or three-part inventory differs")
    if any(child.tag != f"{TEI}div" or child.get("type") != "part" for child in carrier):
        raise ValueError("Ansbert native part types differ")
    selected = carrier[2]
    text = "".join(selected.itertext())
    if not text.lstrip().startswith("YMNUS DE SANCTO ANSBERTO EPISCOPO."):
        raise ValueError("Ansbert hymn heading differs")
    tags = [etree.QName(node).localname for node in selected.iter()]
    if tags.count("lb") != 70 or tags.count("pb") != 2 or tags.count("ab") != 1:
        raise ValueError("Ansbert hymn source feature inventory differs")
    source_ids = [node.get(XML_ID) for node in selected.iter() if node.get(XML_ID)]
    if len(source_ids) != len(set(source_ids)) or source_ids[0] != START_ID or source_ids[-1] != END_ID:
        raise ValueError("Ansbert hymn endpoint IDs differ")
    if any(node.get(XML_ID) in source_ids for sibling in carrier[:2] for node in sibling.iter()):
        raise ValueError("Ansbert hymn overlaps prose siblings")
    expected_locator = (
        f"raw/openmgh/bsb00000752/tei/bsb00000752.xml#{START_ID}; "
        f"raw/openmgh/bsb00000752/tei/bsb00000752.xml#{END_ID}"
    )
    editions = work.get("textual_forms", [{}])[0].get("editions", [])
    if (work.get("work_id") != "ymnus-de-sancto-ansberto" or len(editions) != 1
            or editions[0].get("containing_source", {}).get("locator") != expected_locator):
        raise ValueError("Ansbert catalog identity or locator differs")
    wrappers = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(wrappers) != 1 or wrappers[0].get("n") != work["title"] or len(wrappers[0]) != 1:
        raise ValueError("Ansbert candidate work wrapper differs")
    candidate_part = wrappers[0][0]
    if _canonical(candidate_part) != _canonical(selected):
        raise ValueError("Ansbert complete native part differs")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("Ansbert candidate title differs")
    original_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    candidate_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if original_file is None or candidate_file is None:
        raise ValueError("Ansbert source or candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = original_file.find(suffix), candidate_file.find(suffix)
        if old is None or new is None or _canonical(old) != _canonical(new):
            raise ValueError("Ansbert source publication or bibliography differs")
    return {
        "status": "pass", "source_sha256": SOURCE_SHA, "source_work_div_index": 19,
        "source_part_index": 2, "source_part_c14n_sha256": sha256(_canonical(selected)).hexdigest(),
        "source_part_bytes": len(etree.tostring(selected)), "source_lb_count": 70,
        "source_pb_count": 2, "source_start_id": START_ID, "source_end_id": END_ID,
        "excluded_sibling_part_c14n_sha256": [sha256(_canonical(part)).hexdigest() for part in carrier[:2]],
    }
