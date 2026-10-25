"""Work-local draft adapter for the retained Joshua master TEI.

The original candidate remains the faithful whole-source TEI. This script
creates a small native commentary projection proxy and a reversible support
crosswalk; it does not edit the candidate, project public rows, or install data.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
XML_LANG = f"{{{XML}}}lang"
RAW_SHA256 = "98657e5ee3b1564e7d16729a8fd4fc73b1f46439f02e750fdbe700488fc33879"
MASTER_SHA256 = "54005425b3e87bf0255c19a74e0efa17d494b9554c992a3bb534cd9e921324bb"
CCEL_URL = "https://www.ccel.org/ccel/calvin/commentaries.html"
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


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _parse(path: Path) -> tuple[etree._Element, bytes]:
    raw = path.read_bytes()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=True, remove_comments=False, remove_pis=False)
    return etree.fromstring(raw, parser), raw


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    parent = node.getparent()
    if parent is None:
        return f"/{_local(node)}[1]"
    siblings = [child for child in parent if isinstance(child.tag, str)]
    return f"{_selector(parent)}/{_local(node)}[{siblings.index(node) + 1}]"


def _source_uri(selector: str) -> str:
    return "urn:source-member:calcom07.xml:urn:source-xpath:" + quote(selector, safe="")


def _attrs(node: etree._Element) -> dict[str, str]:
    return {
        ("xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else etree.QName(key).localname if key.startswith("{") else key): value
        for key, value in sorted(node.attrib.items())
    }


def _text_hash(node: etree._Element) -> str:
    return _sha("".join(node.itertext()).encode("utf-8"))


def _norm_text(node: etree._Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _set_attrs(node: etree._Element, attrs: dict[str, str]) -> None:
    for key, value in attrs.items():
        node.set(key, value)


def _copy_proxy_node(source: etree._Element, attr_records: list[dict[str, Any]], source_selector: str) -> etree._Element:
    kind = _local(source)
    if kind not in ALLOWED:
        raise ValueError(f"unsupported selected-unit element {kind} at {source_selector}")
    target = source.get("target") or source.get("cRef") or ""
    multi_target_ref = kind == "ref" and len(target.split()) > 1
    missing_target_ref = kind == "ref" and not target
    unsupported_ref = multi_target_ref or missing_target_ref
    proxy_kind = "seg" if unsupported_ref else kind
    result = etree.Element(f"{{{TEI}}}{proxy_kind}")
    original = _attrs(source)
    projected: dict[str, str] = {}
    projection_notes: list[str] = []
    if unsupported_ref and source.get(XML_ID):
        projected[XML_ID] = source.get(XML_ID)
        projected["type"] = "source-link-unprojected" if multi_target_ref else "source-link-without-target"
    for key, value in original.items():
        actual_key = XML_ID if key == "xml:id" else XML_LANG if key == "xml:lang" else key
        if unsupported_ref:
            continue
        elif kind == "hi" and key == "rend" and value in {"superscript", "subscript"}:
            projection_notes.append("source rendition retained in master/support; literal text kept because current script renderer rejects this source content")
        elif actual_key in ALLOWED[kind] and actual_key != "corresp":
            projected[actual_key] = value
        elif kind == "foreign" and key == "lang":
            if XML_LANG in projected:
                raise ValueError(f"foreign has conflicting lang attributes at {source_selector}")
            projected[XML_LANG] = value
    if multi_target_ref:
        projection_notes.append("source multi-target link retained exactly in master/support; label remains visible; link is not emitted as a public reference")
    elif missing_target_ref:
        projection_notes.append("targetless source link marker retained exactly in master/support; no public reference is emitted")
    _set_attrs(result, projected)
    result.text = source.text
    record = {
        "source_selector": source_selector,
        "source_uri": source.get("corresp"),
        "candidate_xml_id": source.get(XML_ID),
        "candidate_tag": kind,
        "proxy_tag": proxy_kind,
        "candidate_attributes": original,
        "proxy_attributes": {
            ("xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key): value
            for key, value in projected.items()
        },
        "text_sha256": _text_hash(source),
        "projection_notes": projection_notes,
    }
    attr_records.append(record)
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError(f"non-element content inside selected unit at {source_selector}")
        copied = _copy_proxy_node(child, attr_records, _unquote_corresp(child.get("corresp")))
        copied.tail = child.tail
        result.append(copied)
    return result


def _unquote_corresp(value: str | None) -> str:
    from urllib.parse import unquote
    prefix = "urn:source-member:calcom07.xml:urn:source-xpath:"
    if value is None or not value.startswith(prefix):
        raise ValueError("candidate node lacks the selected member source URI")
    return unquote(value[len(prefix):])


def _context_category(root_id: str) -> str:
    if root_id == "i":
        return "title-page-and-imprint"
    if root_id == "ii":
        return "translator-preface"
    if root_id == "iii":
        return "argument-of-joshua"
    if root_id == "xxviii":
        return "translation-appendix"
    if root_id == "xxix":
        return "indexes"
    if root_id in CHAPTER_IDS:
        return "commentary-context-and-range-tables"
    return "other-body-context"


def build(raw_path: Path, master_path: Path, proxy_path: Path, support_path: Path) -> dict[str, Any]:
    raw, raw_bytes = _parse(raw_path)
    master, master_bytes = _parse(master_path)
    if _sha(raw_bytes) != RAW_SHA256:
        raise ValueError("retained calcom07.xml bytes differ from the reviewed member")
    if _sha(master_bytes) != MASTER_SHA256:
        raise ValueError("Joshua master candidate differs from the parent-reviewed TEI")

    candidate_by_uri: dict[str, list[etree._Element]] = defaultdict(list)
    for node in master.iter():
        value = node.get("corresp") if isinstance(node.tag, str) else None
        if value:
            candidate_by_uri[value].append(node)
    body = next(node for node in raw if isinstance(node.tag, str) and _local(node) == "ThML.body")
    source_body = [node for node in body.iter() if isinstance(node.tag, str)]
    body_crosswalk: list[dict[str, Any]] = []
    body_order: list[etree._Element] = []
    for node in source_body:
        selector = _selector(node)
        uri = _source_uri(selector)
        matches = candidate_by_uri.get(uri, [])
        if len(matches) != 1:
            raise ValueError(f"source body node maps to {len(matches)} candidate nodes: {selector}")
        projected = matches[0]
        if "".join(node.itertext()) != "".join(projected.itertext()):
            raise ValueError(f"source body node text mismatch: {selector}")
        body_order.append(projected)
        body_crosswalk.append({
            "source_selector": selector,
            "source_tag": _local(node),
            "source_attributes": _attrs(node),
            "source_text_sha256": _text_hash(node),
            "candidate_corresp": projected.get("corresp"),
            "candidate_tag": _local(projected),
            "candidate_xml_id": projected.get(XML_ID),
            "candidate_attributes": _attrs(projected),
            "candidate_text_sha256": _text_hash(projected),
        })
    if len({item["candidate_corresp"] for item in body_crosswalk}) != len(body_crosswalk):
        raise ValueError("source body crosswalk has duplicate candidate ownership")
    owned_uris = {item["candidate_corresp"] for item in body_crosswalk}
    candidate_body_nodes = [node for node in master.iter() if isinstance(node.tag, str) and node.get("corresp") in owned_uris]
    if candidate_body_nodes != body_order:
        raise ValueError("source body candidate ownership is not in exact source order")

    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI, "xml": XML})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = "Commentary on Joshua"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "John Calvin"
    pub_stmt = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(pub_stmt, f"{{{TEI}}}publisher").text = "Open Christian Data"
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibl = etree.SubElement(source_desc, f"{{{TEI}}}bibl", type="primary-source-member")
    etree.SubElement(bibl, f"{{{TEI}}}ptr", type="ccel-source-catalogue", target=CCEL_URL)
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="filename").text = "calcom07.xml"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="retained_sha256").text = RAW_SHA256
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="source_sha256").text = RAW_SHA256
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="work_id").text = "calvin-commentary-on-joshua"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="textual_form_id").text = "calvin-commentary-on-joshua-english"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="edition_id").text = "calvin-commentary-on-joshua-ccel-electronic"
    etree.SubElement(bibl, f"{{{TEI}}}idno", type="acquisition_id").text = "calvin-joshua-direct-ccel-xml-source-set"
    profile = etree.SubElement(header, f"{{{TEI}}}profileDesc")
    usage = etree.SubElement(profile, f"{{{TEI}}}langUsage")
    etree.SubElement(usage, f"{{{TEI}}}language", ident="en").text = "English"
    text = etree.SubElement(root, f"{{{TEI}}}text")
    native_body = etree.SubElement(text, f"{{{TEI}}}body")

    chapter_crosswalk: list[dict[str, Any]] = []
    chapter_marker_crosswalk: list[dict[str, Any]] = []
    range_crosswalk: list[dict[str, Any]] = []
    unit_crosswalk: list[dict[str, Any]] = []
    projected_attrs: list[dict[str, Any]] = []
    unit_count = 0
    range_count = 0
    seen_units: set[str] = set()
    for expected_number, chapter_id in enumerate(CHAPTER_IDS, 1):
        chapters = raw.xpath(f"//*[local-name()='div1' and @id='{chapter_id}']")
        if len(chapters) != 1:
            raise ValueError(f"chapter wrapper identity is ambiguous: {chapter_id}")
        source_chapter = chapters[0]
        source_chapter_selector = _selector(source_chapter)
        chapter_elements = list(source_chapter.iter())
        first_range_index = next((i for i, node in enumerate(chapter_elements) if isinstance(node.tag, str) and _local(node) == "div2"), len(chapter_elements))
        printed = [node for node in chapter_elements[:first_range_index] if isinstance(node.tag, str) and re.fullmatch(r"CHAPTER\s+\d+", _norm_text(node), re.IGNORECASE)]
        if len(printed) != 1 or int(re.search(r"\d+", _norm_text(printed[0])).group()) != expected_number:
            raise ValueError(f"chapter heading does not attest chapter {expected_number}: {chapter_id}")
        chapter_label = _norm_text(printed[0])
        outer_markers = [node for node in source_chapter if isinstance(node.tag, str) and _local(node) == "scripCom"]
        if len(outer_markers) != 1 or not outer_markers[0].get("osisRef"):
            raise ValueError(f"chapter wrapper must retain one exact outer scripCom marker: {chapter_id}")
        outer_marker = outer_markers[0]
        outer_target = outer_marker.get("osisRef")
        target_match = re.fullmatch(r"Bible:Josh\.(\d+)", outer_target)
        marker_chapter = int(target_match.group(1)) if target_match else None
        chapter_marker_crosswalk.append({
            "chapter_id": chapter_id,
            "chapter_selector": source_chapter_selector,
            "printed_heading_selector": _selector(printed[0]),
            "printed_heading": chapter_label,
            "marker_selector": _selector(outer_marker),
            "marker_attributes": _attrs(outer_marker),
            "exact_osisRef": outer_target,
            "target_chapter_if_explicit": marker_chapter,
            "heading_marker_relation": "matches" if marker_chapter == expected_number else "contradicts" if marker_chapter is not None else "unparsed",
            "projection_use": "context only; per-unit target comes from the nearest range-local scripCom marker",
        })
        chapter = etree.SubElement(native_body, f"{{{TEI}}}div", type="commentary-chapter", n=chapter_id)
        chapter.set(XML_ID, f"calvin-joshua-chapter-{expected_number:02d}")
        chapter_head = etree.SubElement(chapter, f"{{{TEI}}}head")
        chapter_head.text = chapter_label
        chapter_crosswalk.append({
            "source_id": chapter_id,
            "source_selector": source_chapter_selector,
            "source_wrapper_label": source_chapter.get("id"),
            "heading_selector": _selector(printed[0]),
            "heading_text": chapter_label,
            "chapter_number": expected_number,
            "proxy_xml_id": chapter.get(XML_ID),
        })
        direct_ranges = [node for node in source_chapter if isinstance(node.tag, str) and _local(node) == "div2"]
        range_local_index = 0
        for source_range in direct_ranges:
            range_local_index += 1
            range_count += 1
            range_selector = _selector(source_range)
            range_id = source_range.get("id")
            tables = [node for node in source_range if isinstance(node.tag, str) and _local(node) == "table"]
            if not range_id or len(tables) != 1:
                raise ValueError(f"range wrapper lacks unique source table/id: {range_selector}")
            title_refs = [node for node in tables[0].iter() if isinstance(node.tag, str) and _local(node) == "scripRef"]
            if not title_refs:
                raise ValueError(f"range table has no source scripture label: {range_selector}")
            title_ref = title_refs[0]
            label = _norm_text(title_ref)
            interval = title_ref.get("osisRef")
            passage = title_ref.get("passage")
            if not label or not interval or passage != label:
                raise ValueError(f"range title/target not directly attested: {range_selector}")
            native_range = etree.SubElement(chapter, f"{{{TEI}}}div", type="commentary-range", n=range_id)
            native_range.set(XML_ID, f"calvin-joshua-range-{range_count:02d}")
            heading = etree.SubElement(native_range, f"{{{TEI}}}head")
            range_ref = etree.SubElement(heading, f"{{{TEI}}}ref", type="scripture", cRef=interval)
            range_ref.text = label
            range_crosswalk.append({
                "source_id": range_id,
                "source_selector": range_selector,
                "parent_chapter_id": chapter_id,
                "label_selector": _selector(title_ref),
                "label": label,
                "passage": passage,
                "osisRef": interval,
                "candidate_label_corresp": _source_uri(_selector(title_ref)),
                "proxy_xml_id": native_range.get(XML_ID),
            })
            raw_units = [node for node in source_range.iter() if isinstance(node.tag, str) and _local(node) == "div" and node.get("class") == "Commentary"]
            range_unit_index = 0
            for source_unit in raw_units:
                range_unit_index += 1
                unit_count += 1
                source_selector = _selector(source_unit)
                source_uri = _source_uri(source_selector)
                candidate_hits = candidate_by_uri.get(source_uri, [])
                if len(candidate_hits) != 1:
                    raise ValueError(f"commentary source unit maps to {len(candidate_hits)} master nodes: {source_selector}")
                marker_nodes = [node for node in source_range.iter() if isinstance(node.tag, str) and _local(node) == "scripCom"]
                unit_order = list(source_range.iter()).index(source_unit)
                previous_markers = [node for node in marker_nodes if list(source_range.iter()).index(node) < unit_order]
                if not previous_markers:
                    raise ValueError(f"commentary unit has no preceding source scripCom: {source_selector}")
                marker = previous_markers[-1]
                target = marker.get("osisRef")
                if not target:
                    raise ValueError(f"source scripCom lacks osisRef: {_selector(marker)}")
                master_unit = candidate_hits[0]
                if "".join(source_unit.itertext()) != "".join(master_unit.itertext()):
                    raise ValueError(f"commentary unit source/master text differs: {source_selector}")
                proxy_unit = _copy_proxy_node(master_unit, projected_attrs, source_selector)
                proxy_unit.set("type", "commentary-unit")
                proxy_unit.set("scope", target)
                native_range.append(proxy_unit)
                root_attr_record = next(record for record in reversed(projected_attrs) if record["candidate_xml_id"] == master_unit.get(XML_ID))
                root_attr_record["proxy_attributes"] = _attrs(proxy_unit)
                if source_uri in seen_units:
                    raise ValueError(f"duplicate commentary unit ownership: {source_selector}")
                seen_units.add(source_uri)
                unit_crosswalk.append({
                    "sequence": unit_count,
                    "source_selector": source_selector,
                    "source_id": source_unit.get("id"),
                    "source_uri": source_uri,
                    "master_xml_id": master_unit.get(XML_ID),
                    "master_candidate_attrs": _attrs(master_unit),
                    "source_text_sha256": _text_hash(source_unit),
                    "master_text_sha256": _text_hash(master_unit),
                    "marker_selector": _selector(marker),
                    "marker_attributes": _attrs(marker),
                    "exact_scope": target,
                    "chapter_id": chapter_id,
                    "range_id": range_id,
                    "proxy_xml_id": proxy_unit.get(XML_ID),
                    "proxy_selector": f"/TEI[1]/text[1]/body[1]/div[{expected_number}]/div[{range_local_index}]/div[{range_unit_index}]",
                    "descendant_element_count": sum(1 for node in source_unit.iter() if isinstance(node.tag, str)),
                })
    if (len(chapter_crosswalk), range_count, unit_count, len(seen_units)) != (24, 50, 173, 173):
        raise ValueError("Joshua source chapter/range/unit partition failed exact cardinalities")
    all_source_unit_uris = {
        _source_uri(_selector(node))
        for node in body.iter()
        if isinstance(node.tag, str) and _local(node) == "div" and node.get("class") == "Commentary"
    }
    if all_source_unit_uris != seen_units:
        raise ValueError("selected commentary units do not own every body Commentary block exactly once")

    chapter_ids = set(CHAPTER_IDS)
    outside_units = [node for node in source_body if not any(ancestor.get("class") == "Commentary" and _local(ancestor) == "div" for ancestor in node.iterancestors())]
    top_roots = [node for node in body if isinstance(node.tag, str) and _local(node) == "div1"]
    context_groups = []
    for source_root in top_roots:
        root_id = source_root.get("id", "")
        all_nodes = [node for node in source_root.iter() if isinstance(node.tag, str)]
        context_nodes = [node for node in all_nodes if not (node.get("class") == "Commentary" and _local(node) == "div") and not any(ancestor.get("class") == "Commentary" and _local(ancestor) == "div" for ancestor in node.iterancestors())]
        context_groups.append({
            "source_id": root_id,
            "source_selector": _selector(source_root),
            "category": _context_category(root_id),
            "disposition": "retained-in-faithful-whole-work-master-and-node-crosswalk; not emitted as commentary rows",
            "element_count": len(context_nodes),
            "element_tags": dict(sorted(Counter(_local(node) for node in context_nodes).items())),
            "text_characters": sum(len(node.text or "") + len(node.tail or "") for node in context_nodes),
            "source_text_sha256": _text_hash(source_root),
            "source_attributes": _attrs(source_root),
        })
    master_front = next((node for node in master.iter() if isinstance(node.tag, str) and _local(node) == "front"), None)
    front_members = [node for node in master_front.iter() if isinstance(node.tag, str) and node.get("type") == "source-member"] if master_front is not None else []
    front_links = [
        {
            "candidate_selector": _selector(node),
            "candidate_xml_id": node.get(XML_ID),
            "candidate_corresp": node.get("corresp"),
            "attributes": _attrs(node),
            "label": "".join(node.itertext()),
            "label_sha256": _text_hash(node),
        }
        for node in master_front.iter()
        if master_front is not None and isinstance(node.tag, str) and _local(node) in {"ref", "ptr"} and (node.get("target") or node.get("cRef"))
    ]
    support = {
        "contract": "ocd-calvin-joshua-projection-support-v1",
        "status": "work-local draft; source/candidate remain nonaccepted; no install or canonical mutation",
        "faithful_master": {
            "path": str(master_path), "bytes": len(master_bytes), "sha256": MASTER_SHA256,
            "raw_member": "raw/ccel/calvin-commentaries/calcom07.xml",
            "raw_member_bytes": len(raw_bytes), "raw_member_sha256": RAW_SHA256,
            "whole_body_selector": _selector(body),
            "whole_body_element_count": len(source_body),
            "body_comment_count": len(body.xpath(".//comment()")),
            "body_processing_instruction_count": len(body.xpath(".//processing-instruction()")),
            "whole_body_text_sha256": _text_hash(body),
            "whole_body_text_equal_to_candidate": "".join(body.itertext()) == "".join(next(node for node in master.iter() if isinstance(node.tag, str) and node.get("corresp") == _source_uri(_selector(body))).itertext()),
            "candidate_front_text_sha256": _text_hash(master_front) if master_front is not None else None,
            "candidate_front_element_count": sum(1 for node in master_front.iter() if isinstance(node.tag, str)) if master_front is not None else 0,
            "candidate_front_source_members": [{"member": node.get("n"), "selector": _selector(node), "xml_id": node.get(XML_ID), "corresp": node.get("corresp"), "element_count": sum(1 for child in node.iter() if isinstance(child.tag, str)), "text_sha256": _text_hash(node)} for node in front_members],
            "candidate_front_relative_links": front_links,
            "shared_catalogue_source": {"member": "commentaries.xml", "sha256": "d5167554c4c40ac2ba320e9ec75afd2565001e0f5f84b0245832b7bfa183b08f", "ownership": "shared collection-level front matter; sibling hrefs remain outside Joshua scope"},
        },
        "projection": {"scope": "173 exact source Commentary divs grouped by printed chapter and source scripture-range table", "exact_target_rule": "copy the nearest preceding scripCom/@osisRef within the same source div2 without correction", "body_node_count": 173, "chapter_count": 24, "range_count": 50},
        "chapter_crosswalk": chapter_crosswalk,
        "chapter_marker_crosswalk": chapter_marker_crosswalk,
        "range_crosswalk": range_crosswalk,
        "unit_crosswalk": unit_crosswalk,
        "projected_node_attribute_crosswalk": projected_attrs,
        "context_groups": context_groups,
        "body_node_crosswalk": body_crosswalk,
        "reversibility": {"method": "proxy nodes map to exact candidate xml:id and corresp; complete original attributes/text/tree remain in immutable master; projected attributes and removed/renamed values recorded per node", "full_body_mapped_once_in_source_order": True, "full_body_text_equal": True, "front_preface_argument_translation_index_tables_notes_links_retained_in_master": True},
        "shared_runtime_change_required": False,
    }
    proxy_path.parent.mkdir(parents=True, exist_ok=True)
    support_path.parent.mkdir(parents=True, exist_ok=True)
    proxy_bytes = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    proxy_path.write_bytes(proxy_bytes)
    support["projection"]["proxy_path"] = str(proxy_path)
    support["projection"]["proxy_bytes"] = len(proxy_bytes)
    support["projection"]["proxy_sha256"] = _sha(proxy_bytes)
    support_bytes = _json_bytes(support)
    support_path.write_bytes(support_bytes)
    return {"proxy_sha256": _sha(proxy_bytes), "proxy_bytes": len(proxy_bytes), "support_sha256": _sha(support_bytes), "support_bytes": len(support_bytes), "chapters": 24, "ranges": 50, "units": 173, "body_nodes": len(body_crosswalk)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--proxy", type=Path, required=True)
    parser.add_argument("--support", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.master, args.proxy, args.support), sort_keys=True))


if __name__ == "__main__":
    main()
