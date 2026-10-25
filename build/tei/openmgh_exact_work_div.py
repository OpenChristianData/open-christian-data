"""Independent retained-source oracle for manifest-selected openMGH work divs."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256

from lxml import etree


TEI = "{http://www.tei-c.org/ns/1.0}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def parse_tei(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype or root.tag != f"{TEI}TEI":
        raise ValueError("entity-free TEI root required")
    return root


def same_node(left: etree._Element, right: etree._Element, *, outer: bool = False) -> bool:
    if (left.tag != right.tag or dict(left.attrib) != dict(right.attrib)
            or left.text != right.text or len(left) != len(right)):
        return False
    if not outer and left.tail != right.tail:
        return False
    return all(same_node(a, b) for a, b in zip(left, right, strict=True))


def source_work_div(source_bytes: bytes, manifest: dict,
                    entry: dict, work: dict, acquisition: dict) -> tuple[etree._Element, dict]:
    """Derive the selected direct work div from catalog IDs and source order."""
    if manifest.get("contract") != "ocd-openmgh-exact-work-div-batch-v1":
        raise ValueError("unsupported exact-source batch manifest")
    if (sha256(source_bytes).hexdigest() != manifest["source"]["sha256"]
            or acquisition["source_sha256"] != manifest["source"]["sha256"]
            or acquisition["source_path"] != manifest["source"]["path"]):
        raise ValueError("source bytes or acquisition binding changed")
    source = parse_tei(source_bytes)
    ns = {"t": TEI[1:-1]}
    volumes = source.xpath("/t:TEI/t:text/t:body/t:div[@type='volume']", namespaces=ns)
    if len(volumes) != 1:
        raise ValueError("exactly one source volume required")
    children = list(volumes[0])
    if len(children) != manifest["source"]["volume_child_count"]:
        raise ValueError("source volume child count changed")
    if (manifest["marker_ownership"]["top_level_interstitial_nodes"]
            or manifest["marker_ownership"]["shared_heading_nodes"]):
        raise ValueError("this route does not support shared top-level markers")
    if any(node.tag != f"{TEI}div" or node.get("type") != "work" for node in children):
        raise ValueError("source has unaccounted top-level or non-work nodes")
    selections = [item["source_work_div_index"] for item in manifest["works"]]
    exclusions = manifest["excluded_work_div_indexes"]
    if (len(selections) != len(set(selections)) or len(exclusions) != len(set(exclusions))
            or set(selections) & set(exclusions)
            or set(selections + exclusions) != set(range(len(children)))
            or selections != manifest["selected_work_div_indexes"]):
        raise ValueError("source work-div or exclusion accounting changed")
    if len({item["work_id"] for item in manifest["works"]}) != len(selections):
        raise ValueError("manifest work identity repeated")
    matches = [item for item in manifest["works"] if item["work_id"] == work["work_id"]]
    if len(matches) != 1 or matches[0] != entry:
        raise ValueError("work absent or repeated in manifest")
    if entry["source_work_div_index"] < 0 or entry["source_work_div_index"] >= len(children):
        raise ValueError("work-div index outside source")
    owner: dict[str, int] = {}
    for index, child in enumerate(children):
        for node in child.iter():
            identity = node.get(XML_ID)
            if identity:
                if identity in owner:
                    raise ValueError("repeated source XML ID")
                owner[identity] = index
    declared = [part.split("#", 1)[1] for part in
                work["textual_forms"][0]["editions"][0]["containing_source"]["locator"].split("; ")]
    if Counter(declared) != Counter(entry["catalog_locator_ids"]):
        raise ValueError("work/catalog locator set changed")
    catalog_owners = {owner.get(identity) for identity in declared}
    if catalog_owners != {entry["source_work_div_index"]}:
        raise ValueError("catalog locators do not independently identify this source work div")
    selected = children[entry["source_work_div_index"]]
    if selected.get("n") != entry["source_work_div_n"]:
        raise ValueError("source work-div title changed")
    tags = Counter(etree.QName(node).localname for node in selected.iter()
                   if isinstance(node.tag, str))
    return selected, {
        "status": "pass", "source_sha256": sha256(source_bytes).hexdigest(),
        "source_work_div_index": entry["source_work_div_index"],
        "source_work_div_n": selected.get("n"),
        "source_node_count": sum(tags.values()),
        "source_line_breaks": tags["lb"], "source_page_breaks": tags["pb"],
        "catalog_locator_ids": declared,
        "source_marker_policy": "all nested markers preserved inside the complete selected work div",
    }


def check_candidate(source_bytes: bytes, candidate_bytes: bytes, manifest: dict,
                    entry: dict, work: dict, acquisition: dict) -> dict:
    selected, details = source_work_div(source_bytes, manifest, entry, work, acquisition)
    source, candidate = parse_tei(source_bytes), parse_tei(candidate_bytes)
    ns = {"t": TEI[1:-1]}
    works = candidate.xpath("/t:TEI/t:text/t:body/t:div[@type='work']", namespaces=ns)
    if len(works) != 1 or not same_node(selected, works[0], outer=True):
        raise ValueError("candidate differs from complete source work div")
    body = candidate.xpath("/t:TEI/t:text/t:body", namespaces=ns)[0]
    if len(body) != 1:
        raise ValueError("candidate contains extra work nodes")
    titles = candidate.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title", namespaces=ns)
    if len(titles) != 1 or titles[0].text != work["title"]:
        raise ValueError("candidate title differs from work identity")
    source_file = source.find(f"{TEI}teiHeader/{TEI}fileDesc")
    candidate_file = candidate.find(f"{TEI}teiHeader/{TEI}fileDesc")
    if source_file is None or candidate_file is None:
        raise ValueError("source or candidate header absent")
    for suffix in (f"{TEI}publicationStmt", f"{TEI}sourceDesc/{TEI}biblFull"):
        old, new = source_file.find(suffix), candidate_file.find(suffix)
        if old is None or new is None or not same_node(old, new, outer=True):
            raise ValueError("electronic rights or print bibliography changed")
    return details | {"candidate_sha256": sha256(candidate_bytes).hexdigest(),
                      "mapping": "entire native source work div copied without text or node changes"}
