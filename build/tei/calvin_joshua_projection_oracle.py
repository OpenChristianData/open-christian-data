"""Independent observer for the Joshua projection draft.

This module does not import or call the draft producer. It reconstructs the
source mapping and checks the candidate, proxy, and reversible support ledger.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"
RAW_SHA256 = "98657e5ee3b1564e7d16729a8fd4fc73b1f46439f02e750fdbe700488fc33879"
MASTER_SHA256 = "506b87644600c490d94c88f8012ab19243bdbc73d61dbdb09bfeb59b54245545"
CHAPTER_IDS = (
    "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii",
    "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi", "xxii",
    "xxiii", "xxiv", "xxv", "xxvi", "xxvii",
)
ALLOWED = {
    "div": {"type", "subtype", "n", XML_ID, "corresp", "scope", "target", "osisRef", "cRef"},
    "head": {"type", XML_ID}, "p": {"type", "n", XML_ID, XML_LANG},
    "ab": {"type", "n", XML_ID, XML_LANG}, "seg": {"type", "n", XML_ID, XML_LANG},
    "hi": {"rend", XML_ID, XML_LANG}, "foreign": {XML_ID, XML_LANG},
    "ref": {"type", "target", "cRef", XML_ID},
    "note": {"type", "place", "n", XML_ID}, "lb": {"break", XML_ID},
    "pb": {"n", XML_ID}, "anchor": {XML_ID}, "ptr": {"type", "target", XML_ID},
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse(path: Path) -> tuple[etree._Element, bytes]:
    data = path.read_bytes()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True, remove_comments=False, remove_pis=False)
    return etree.fromstring(data, parser), data


def name(node: etree._Element) -> str:
    return etree.QName(node).localname


def path_of(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{name(node)}[1]"
    elements = [child for child in parent if isinstance(child.tag, str)]
    return f"{path_of(parent)}/{name(node)}[{elements.index(node) + 1}]"


def source_uri(path: str) -> str:
    return "urn:source-member:calcom07.xml:urn:source-xpath:" + quote(path, safe="")


def decode_source_uri(value: str | None) -> str:
    prefix = "urn:source-member:calcom07.xml:urn:source-xpath:"
    if value is None or not value.startswith(prefix):
        raise AssertionError("missing exact member source URI")
    return unquote(value[len(prefix):])


def attrs(node: etree._Element) -> dict[str, str]:
    return {
        ("xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else etree.QName(key).localname if key.startswith("{") else key): value
        for key, value in sorted(node.attrib.items())
    }


def text_hash(node: etree._Element) -> str:
    return digest("".join(node.itertext()).encode("utf-8"))


def normalized_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def expected_node(source: etree._Element) -> etree._Element:
    kind = name(source)
    raw_attrs = attrs(source)
    target = source.get("target") or source.get("cRef") or ""
    multi = kind == "ref" and len(target.split()) > 1
    missing = kind == "ref" and not target
    output_kind = "seg" if multi or missing else kind
    result = etree.Element(f"{{{TEI}}}{output_kind}")
    if multi or missing:
        if source.get(XML_ID):
            result.set(XML_ID, source.get(XML_ID))
            result.set("type", "source-link-unprojected" if multi else "source-link-without-target")
    else:
        for key, value in raw_attrs.items():
            xml_key = XML_ID if key == "xml:id" else XML_LANG if key == "xml:lang" else key
            if kind == "hi" and key == "rend" and value in {"superscript", "subscript"}:
                continue
            if kind == "foreign" and key == "lang":
                result.set(XML_LANG, value)
            elif xml_key in ALLOWED[kind] and xml_key != "corresp":
                result.set(xml_key, value)
    result.text = source.text
    for child in source:
        if not isinstance(child.tag, str):
            raise AssertionError("selected proxy source contains non-element content")
        new_child = expected_node(child)
        new_child.tail = child.tail
        result.append(new_child)
    return result


def subtree_bytes(node: etree._Element) -> bytes:
    return etree.tostring(node, encoding="UTF-8", with_tail=False)


def tree_signature(node: etree._Element) -> object:
    return (
        node.tag,
        dict(node.attrib),
        node.text,
        tuple((tree_signature(child), child.tail) for child in node),
    )


def observe(source_path: Path, master_path: Path, proxy_path: Path, support_path: Path) -> dict[str, object]:
    raw, raw_bytes = parse(source_path)
    master, master_bytes = parse(master_path)
    proxy, proxy_bytes = parse(proxy_path)
    support_bytes = support_path.read_bytes()
    support = json.loads(support_bytes.decode("utf-8"))
    if digest(raw_bytes) != RAW_SHA256 or digest(master_bytes) != MASTER_SHA256:
        raise AssertionError("reviewed raw/member or master candidate digest drifted")
    if support.get("contract") != "ocd-calvin-joshua-projection-support-v1":
        raise AssertionError("support ledger has wrong contract")
    if support.get("faithful_master", {}).get("sha256") != MASTER_SHA256:
        raise AssertionError("support ledger does not pin reviewed full master")
    if support.get("projection", {}).get("proxy_sha256") != digest(proxy_bytes):
        raise AssertionError("support ledger does not pin exact proxy bytes")
    if support.get("projection", {}).get("proxy_bytes") != len(proxy_bytes):
        raise AssertionError("support ledger proxy length differs")

    candidate_by_uri: dict[str, list[etree._Element]] = defaultdict(list)
    for node in master.iter():
        if isinstance(node.tag, str) and node.get("corresp"):
            candidate_by_uri[node.get("corresp")].append(node)
    source_body = next(node for node in raw if isinstance(node.tag, str) and name(node) == "ThML.body")
    raw_body_nodes = [node for node in source_body.iter() if isinstance(node.tag, str)]
    raw_by_selector = {path_of(node): node for node in raw_body_nodes}
    computed_body_crosswalk = []
    source_mapped_nodes: list[etree._Element] = []
    for node in raw_body_nodes:
        selector = path_of(node)
        uri = source_uri(selector)
        hits = candidate_by_uri.get(uri, [])
        if len(hits) != 1:
            raise AssertionError(f"source element ownership cardinality {len(hits)} at {selector}")
        match = hits[0]
        if "".join(node.itertext()) != "".join(match.itertext()):
            raise AssertionError(f"source/master subtree text differs at {selector}")
        source_mapped_nodes.append(match)
        computed_body_crosswalk.append({
            "source_selector": selector,
            "source_tag": name(node),
            "source_attributes": attrs(node),
            "source_text_sha256": text_hash(node),
            "candidate_corresp": match.get("corresp"),
            "candidate_tag": name(match),
            "candidate_xml_id": match.get(XML_ID),
            "candidate_attributes": attrs(match),
            "candidate_text_sha256": text_hash(match),
        })
    owned = {row["candidate_corresp"] for row in computed_body_crosswalk}
    master_body_order = [node for node in master.iter() if isinstance(node.tag, str) and node.get("corresp") in owned]
    if master_body_order != source_mapped_nodes:
        raise AssertionError("master body source correspondence order differs")
    if support.get("body_node_crosswalk") != computed_body_crosswalk:
        raise AssertionError("persisted body crosswalk differs from independent source traversal")
    source_master_body = next(node for node in master.iter() if isinstance(node.tag, str) and node.get("corresp") == source_uri(path_of(source_body)))
    if "".join(source_body.itertext()) != "".join(source_master_body.itertext()):
        raise AssertionError("whole body text changed")

    proxy_text = proxy.find(f"{{{TEI}}}text")
    if proxy.tag != f"{{{TEI}}}TEI" or proxy_text is None:
        raise AssertionError("proxy is not TEI P5")
    body = proxy_text.find(f"{{{TEI}}}body")
    if body is None or list(proxy_text) != [body]:
        raise AssertionError("draft proxy must contain only its explicitly scoped commentary body")
    chapters = [node for node in body if isinstance(node.tag, str) and name(node) == "div"]
    if len(chapters) != 24:
        raise AssertionError("proxy does not contain exactly 24 chapter wrappers")
    source_units = [node for node in raw_body_nodes if name(node) == "div" and node.get("class") == "Commentary"]
    expected_unit_rows = []
    expected_chapter_rows = []
    expected_chapter_marker_rows = []
    expected_range_rows = []
    candidate_unit_nodes: list[etree._Element] = []
    proxy_unit_nodes = [node for node in body.iter() if isinstance(node.tag, str) and name(node) == "div" and node.get("type") == "commentary-unit"]
    if len(proxy_unit_nodes) != 173 or len(source_units) != 173:
        raise AssertionError("raw/proxy commentary unit counts are not 173")
    proxy_targets = []
    for chapter_number, chapter_id in enumerate(CHAPTER_IDS, 1):
        source_chapters = raw.xpath(f"//*[local-name()='div1' and @id='{chapter_id}']")
        if len(source_chapters) != 1:
            raise AssertionError(f"ambiguous source chapter id {chapter_id}")
        chapter_source = source_chapters[0]
        elements_before_ranges = []
        for node in chapter_source.iter():
            if name(node) == "div2":
                break
            if isinstance(node.tag, str):
                elements_before_ranges.append(node)
        headings = [node for node in elements_before_ranges if re.fullmatch(r"CHAPTER\s+\d+", normalized_text(node), re.IGNORECASE)]
        if len(headings) != 1 or int(re.search(r"\d+", normalized_text(headings[0])).group()) != chapter_number:
            raise AssertionError(f"printed chapter heading mismatch for {chapter_id}")
        outer_markers = [node for node in chapter_source if isinstance(node.tag, str) and name(node) == "scripCom"]
        if len(outer_markers) != 1 or not outer_markers[0].get("osisRef"):
            raise AssertionError(f"outer chapter scripCom marker missing or ambiguous: {chapter_id}")
        outer_marker = outer_markers[0]
        outer_target = outer_marker.get("osisRef")
        parsed_marker = re.fullmatch(r"Bible:Josh\.(\d+)", outer_target)
        marker_chapter = int(parsed_marker.group(1)) if parsed_marker else None
        expected_chapter_marker_rows.append({
            "chapter_id": chapter_id,
            "chapter_selector": path_of(chapter_source),
            "printed_heading_selector": path_of(headings[0]),
            "printed_heading": normalized_text(headings[0]),
            "marker_selector": path_of(outer_marker),
            "marker_attributes": attrs(outer_marker),
            "exact_osisRef": outer_target,
            "target_chapter_if_explicit": marker_chapter,
            "heading_marker_relation": "matches" if marker_chapter == chapter_number else "contradicts" if marker_chapter is not None else "unparsed",
            "projection_use": "context only; per-unit target comes from the nearest range-local scripCom marker",
        })
        pchapter = chapters[chapter_number - 1]
        direct_heads = [child for child in pchapter if isinstance(child.tag, str) and name(child) == "head"]
        if pchapter.get("type") != "commentary-chapter" or pchapter.get("n") != chapter_id or len(direct_heads) != 1 or normalized_text(direct_heads[0]) != normalized_text(headings[0]):
            raise AssertionError(f"proxy chapter label/group mismatch {chapter_id}")
        expected_chapter_rows.append({"source_id": chapter_id, "source_selector": path_of(chapter_source), "source_wrapper_label": chapter_source.get("id"), "heading_selector": path_of(headings[0]), "heading_text": normalized_text(headings[0]), "chapter_number": chapter_number, "proxy_xml_id": pchapter.get(XML_ID)})
        ranges = [node for node in chapter_source if isinstance(node.tag, str) and name(node) == "div2"]
        proxy_ranges = [node for node in pchapter if isinstance(node.tag, str) and name(node) == "div"]
        if len(proxy_ranges) != len(ranges):
            raise AssertionError(f"range wrapper count differs in chapter {chapter_id}")
        for range_number, source_range in enumerate(ranges, 1):
            range_selector = path_of(source_range)
            tabs = [node for node in source_range if isinstance(node.tag, str) and name(node) == "table"]
            if len(tabs) != 1:
                raise AssertionError(f"range does not have one source table {range_selector}")
            labels = [node for node in tabs[0].iter() if isinstance(node.tag, str) and name(node) == "scripRef"]
            if not labels:
                raise AssertionError(f"range has no scripture label {range_selector}")
            label = labels[0]
            passage = normalized_text(label)
            interval = label.get("osisRef")
            if not passage or label.get("passage") != passage or not interval:
                raise AssertionError(f"range label or exact osisRef invalid {range_selector}")
            prange = proxy_ranges[range_number - 1]
            heads = [child for child in prange if isinstance(child.tag, str) and name(child) == "head"]
            hrefs = heads[0].xpath("./tei:ref", namespaces={"tei": TEI}) if len(heads) == 1 else []
            if prange.get("type") != "commentary-range" or prange.get("n") != source_range.get("id") or len(hrefs) != 1 or hrefs[0].get("cRef") != interval or normalized_text(hrefs[0]) != passage:
                raise AssertionError(f"proxy range label/link differs at {range_selector}")
            expected_range_rows.append({"source_id": source_range.get("id"), "source_selector": range_selector, "parent_chapter_id": chapter_id, "label_selector": path_of(label), "label": passage, "passage": label.get("passage"), "osisRef": interval, "candidate_label_corresp": source_uri(path_of(label)), "proxy_xml_id": prange.get(XML_ID)})
            units = [node for node in source_range.iter() if isinstance(node.tag, str) and name(node) == "div" and node.get("class") == "Commentary"]
            proxy_range_units = [node for node in prange if isinstance(node.tag, str) and name(node) == "div" and node.get("type") == "commentary-unit"]
            if len(units) != len(proxy_range_units):
                raise AssertionError(f"unit membership count differs in range {source_range.get('id')}")
            range_nodes = list(source_range.iter())
            markers = [node for node in range_nodes if isinstance(node.tag, str) and name(node) == "scripCom"]
            for unit_index, source_unit in enumerate(units, 1):
                source_selector = path_of(source_unit)
                hits = candidate_by_uri.get(source_uri(source_selector), [])
                if len(hits) != 1:
                    raise AssertionError(f"candidate unit mapping not unique: {source_selector}")
                candidate_unit = hits[0]
                candidate_unit_nodes.append(candidate_unit)
                source_pos = range_nodes.index(source_unit)
                previous = [node for node in markers if range_nodes.index(node) < source_pos]
                if not previous:
                    raise AssertionError(f"no preceding source scripCom at {source_selector}")
                marker = previous[-1]
                target = marker.get("osisRef")
                punit = proxy_range_units[unit_index - 1]
                if not target or punit.get("scope") != target or punit.get("corresp") is not None:
                    raise AssertionError(f"proxy scope does not copy exact marker at {source_selector}")
                if "".join(source_unit.itertext()) != "".join(candidate_unit.itertext()):
                    raise AssertionError(f"unit text differs in faithful master: {source_selector}")
                expected_copy = expected_node(candidate_unit)
                expected_copy.set("type", "commentary-unit")
                expected_copy.set("scope", target)
                if tree_signature(expected_copy) != tree_signature(punit):
                    raise AssertionError(f"proxy selected subtree differs beyond declared adaptation: {source_selector}")
                if "".join(candidate_unit.itertext()) != "".join(punit.itertext()):
                    raise AssertionError(f"proxy unit visible text differs: {source_selector}")
                target_items = [node for node in candidate_unit.iter() if isinstance(node.tag, str) and name(node) == "ref" and (len((node.get("target") or node.get("cRef") or "").split()) != 1)]
                expected_unit_rows.append({
                    "sequence": len(expected_unit_rows) + 1,
                    "source_selector": source_selector,
                    "source_id": source_unit.get("id"),
                    "source_uri": source_uri(source_selector),
                    "master_xml_id": candidate_unit.get(XML_ID),
                    "master_candidate_attrs": attrs(candidate_unit),
                    "source_text_sha256": text_hash(source_unit),
                    "master_text_sha256": text_hash(candidate_unit),
                    "marker_selector": path_of(marker),
                    "marker_attributes": attrs(marker),
                    "exact_scope": target,
                    "chapter_id": chapter_id,
                    "range_id": source_range.get("id"),
                    "proxy_xml_id": punit.get(XML_ID),
                    "proxy_selector": f"/TEI[1]/text[1]/body[1]/div[{chapter_number}]/div[{range_number}]/div[{unit_index}]",
                    "descendant_element_count": sum(1 for node in source_unit.iter() if isinstance(node.tag, str)),
                })
                proxy_targets.append(target)
    if support.get("chapter_crosswalk") != expected_chapter_rows:
        raise AssertionError("saved chapter map differs from independent source selectors")
    if support.get("chapter_marker_crosswalk") != expected_chapter_marker_rows:
        raise AssertionError("saved outer chapter markers differ from independent source traversal")
    if support.get("range_crosswalk") != expected_range_rows:
        raise AssertionError("saved range map differs from independent source selectors")
    if support.get("unit_crosswalk") != expected_unit_rows:
        raise AssertionError("saved unit/marker map differs from independent source selectors")

    expected_node_records = []
    for candidate_unit in candidate_unit_nodes:
        unit_mapping = next(row for row in expected_unit_rows if row["master_xml_id"] == candidate_unit.get(XML_ID))
        for node in candidate_unit.iter():
            if not isinstance(node.tag, str):
                continue
            uri = node.get("corresp")
            if uri is None:
                raise AssertionError("selected candidate descendant missing source URI")
            raw_path = decode_source_uri(uri)
            raw_node = raw_by_selector.get(raw_path)
            if raw_node is None:
                raise AssertionError(f"selected candidate descendant source selector missing: {raw_path}")
            projected_node = expected_node(node)
            if node is candidate_unit:
                projected_node.set("type", "commentary-unit")
                projected_node.set("scope", unit_mapping["exact_scope"])
            projection_tags = name(projected_node)
            expected_node_records.append({
                "source_selector": raw_path,
                "source_uri": uri,
                "candidate_xml_id": node.get(XML_ID),
                "candidate_tag": name(node),
                "proxy_tag": projection_tags,
                "candidate_attributes": attrs(node),
                "proxy_attributes": attrs(projected_node),
                "text_sha256": text_hash(node),
                "projection_notes": [
                    *(["source multi-target link retained exactly in master/support; label remains visible; link is not emitted as a public reference"] if name(node) == "ref" and len((node.get("target") or node.get("cRef") or "").split()) > 1 else []),
                    *(["targetless source link marker retained exactly in master/support; no public reference is emitted"] if name(node) == "ref" and not (node.get("target") or node.get("cRef")) else []),
                    *(["source rendition retained in master/support; literal text kept because current script renderer rejects this source content"] if name(node) == "hi" and node.get("rend") in {"superscript", "subscript"} else []),
                ],
            })
    # Producer attributes are recorded in depth-first source unit order.
    if support.get("projected_node_attribute_crosswalk") != expected_node_records:
        raise AssertionError("per-node reversible source attribute ledger differs")

    proxy_multis = [node for node in proxy.iter() if isinstance(node.tag, str) and name(node) == "seg" and node.get("type") == "source-link-unprojected"]
    proxy_targetless = [node for node in proxy.iter() if isinstance(node.tag, str) and name(node) == "seg" and node.get("type") == "source-link-without-target"]
    proxy_flattened_styles = [record for record in expected_node_records if any("rendition retained" in note for note in record["projection_notes"])]
    context_groups = support.get("context_groups", [])
    if sum(item.get("element_count", 0) for item in context_groups) + sum(item["descendant_element_count"] for item in expected_unit_rows) != len(raw_body_nodes) - 1:
        raise AssertionError("whole-body context and selected-unit ownership do not partition source body nodes")
    front = next((node for node in master.iter() if isinstance(node.tag, str) and name(node) == "front"), None)
    faithful = support.get("faithful_master", {})
    if front is None or text_hash(front) != faithful.get("candidate_front_text_sha256"):
        raise AssertionError("shared catalogue front-matter binding changed")
    front_members = [node for node in front.iter() if isinstance(node.tag, str) and node.get("type") == "source-member"]
    expected_front_members = [{"member": node.get("n"), "selector": path_of(node), "xml_id": node.get(XML_ID), "corresp": node.get("corresp"), "element_count": sum(1 for child in node.iter() if isinstance(child.tag, str)), "text_sha256": text_hash(node)} for node in front_members]
    front_links = [
        {"candidate_selector": path_of(node), "candidate_xml_id": node.get(XML_ID), "candidate_corresp": node.get("corresp"), "attributes": attrs(node), "label": "".join(node.itertext()), "label_sha256": text_hash(node)}
        for node in front.iter()
        if isinstance(node.tag, str) and name(node) in {"ref", "ptr"} and (node.get("target") or node.get("cRef"))
    ]
    if faithful.get("candidate_front_source_members") != expected_front_members or faithful.get("candidate_front_relative_links") != front_links:
        raise AssertionError("shared catalogue member/link crosswalk differs from faithful master")
    if faithful.get("whole_body_text_equal_to_candidate") is not True:
        raise AssertionError("support ledger does not attest exact master body text equality")
    if faithful.get("body_comment_count") != len(source_body.xpath(".//comment()")) or faithful.get("body_processing_instruction_count") != len(source_body.xpath(".//processing-instruction()")):
        raise AssertionError("support ledger body lexical-event counts differ")
    if len(proxy_targets) != 173:
        raise AssertionError("proxy targets do not have exact one-per-unit count")
    return {
        "status": "pass",
        "raw_sha256": digest(raw_bytes),
        "master_sha256": digest(master_bytes),
        "proxy_sha256": digest(proxy_bytes),
        "support_sha256": digest(support_bytes),
        "body_source_nodes": len(raw_body_nodes),
        "body_nodes_mapped_exactly_once_in_order": True,
        "body_text_exact": True,
        "chapters": len(expected_chapter_rows),
        "outer_chapter_marker_mismatches_preserved": sum(row["heading_marker_relation"] == "contradicts" for row in expected_chapter_marker_rows),
        "ranges": len(expected_range_rows),
        "commentary_units": len(expected_unit_rows),
        "targets_exact_and_unchanged": True,
        "multi_target_links_preserved_in_master_support_but_not_projected": len(proxy_multis),
        "targetless_link_markers_preserved_in_master_support_but_not_projected": len(proxy_targetless),
        "superscript_or_subscript_renditions_reversibly_flattened": len(proxy_flattened_styles),
        "candidate_front_text_sha256": text_hash(front),
        "context_groups": len(context_groups),
        "excluded_source_context_explicitly_owned": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--proxy", type=Path, required=True)
    parser.add_argument("--support", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(observe(args.source, args.master, args.proxy, args.support), sort_keys=True))


if __name__ == "__main__":
    main()
