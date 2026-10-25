"""Independent exact native-part oracle for three bsb753 prose works."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
SOURCE_SHA = "550c090dad42988c5a8c95adc3328a3b5ef93dcfeaa8f91354fe6a03995f9b27"
SELECTIONS = {
    "passio-desiderii-et-reginfridi": (2, 0, "bsb00000753_00063_19", "bsb00000753_00071_9"),
    "vita-sancti-ursmari": (11, 0, "bsb00000753_00461_1", "bsb00000753_00469_7"),
    "vita-sancti-erminonis": (11, 1, "bsb00000753_00469_8", "bsb00000753_00478_14"),
}


def _parse(data: bytes) -> etree._Element:
    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True,
                                                    remove_comments=False, huge_tree=True))
    if root.getroottree().docinfo.doctype:
        raise ValueError("bsb753 source/candidate DOCTYPE is forbidden")
    return root


def _c14n(node: etree._Element) -> bytes:
    detached = deepcopy(node)
    etree.cleanup_namespaces(detached)
    return etree.tostring(detached, method="c14n", with_comments=True)


def check(source_bytes: bytes, candidate_bytes: bytes, work: dict, acquisition: dict) -> dict:
    work_id = work.get("work_id")
    if work_id not in SELECTIONS:
        raise ValueError("work outside bsb753 three-prose scope")
    index, part_index, start_id, end_id = SELECTIONS[work_id]
    if sha256(source_bytes).hexdigest() != SOURCE_SHA or acquisition.get("source_sha256") != SOURCE_SHA:
        raise ValueError("bsb753 extracted XML/acquisition binding differs")
    source, candidate = _parse(source_bytes), _parse(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1 or len(volumes[0]) != 14 or any(node.tag != f"{TEI}div" for node in volumes[0]):
        raise ValueError("bsb753 14-division volume envelope differs")
    carriers = [volumes[0][2], volumes[0][11]]
    if ([carrier.get("n") for carrier in carriers] != [
            "Pass. Des. ep. et Reginfr. diac. Alsegaudiensium",
            "Vitae Ursmari et Erminonis epp. et abb. Lobb.",
        ] or [len(carrier) for carrier in carriers] != [2, 2]
            or any(child.tag != f"{TEI}div" or child.get("type") != "part"
                   for carrier in carriers for child in carrier)):
        raise ValueError("bsb753 two-carrier part census differs")
    carrier = volumes[0][index]
    selected = carrier[part_index]
    source_ids = [node.get(XML_ID) for node in selected.iter()
                  if (node.get(XML_ID) or "").startswith("bsb00000753_")]
    if (len(source_ids) != len(set(source_ids)) or start_id not in source_ids
            or source_ids.index(start_id) > 1 or source_ids[-1] != end_id):
        raise ValueError("bsb753 catalog endpoints do not bound the complete native part")
    for ordinal, sibling in enumerate(carrier):
        if ordinal != part_index and any(node.get(XML_ID) in source_ids for node in sibling.iter()):
            raise ValueError("bsb753 source parts overlap")
    editions = work.get("textual_forms", [{}])[0].get("editions", [])
    prefix = "raw/openmgh/bsb00000753/tei/bsb00000753.xml#"
    if (len(editions) != 1 or editions[0].get("containing_source", {}).get("locator")
            != f"{prefix}{start_id}; {prefix}{end_id}"):
        raise ValueError("bsb753 catalog locator differs")
    wrappers = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(wrappers) != 1 or wrappers[0].get("n") != work["title"] or len(wrappers[0]) != 1:
        raise ValueError("bsb753 candidate work wrapper differs")
    if _c14n(wrappers[0][0]) != _c14n(selected):
        raise ValueError("bsb753 complete native source part differs")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("bsb753 candidate title differs")
    old_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    new_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if old_file is None or new_file is None:
        raise ValueError("bsb753 source or candidate header missing")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = old_file.find(suffix), new_file.find(suffix)
        if old is None or new is None or _c14n(old) != _c14n(new):
            raise ValueError("bsb753 publication or print bibliography differs")
    return {
        "status": "pass", "work_id": work_id, "source_sha256": SOURCE_SHA,
        "source_work_div_index": index, "source_part_index": part_index,
        "source_part_c14n_sha256": sha256(_c14n(selected)).hexdigest(),
        "source_start_id": start_id, "source_end_id": end_id,
        "source_lb_count": len(selected.findall(f".//{TEI}lb")),
        "source_pb_count": len(selected.findall(f".//{TEI}pb")),
        "sibling_part_c14n_sha256": [sha256(_c14n(part)).hexdigest()
                                    for ordinal, part in enumerate(carrier) if ordinal != part_index],
    }
