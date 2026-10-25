"""Independent oracle for the retained L741 DBNL TEI.2 source candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XMLID = f"{{{XML_NS}}}id"
XMLBASE = f"{{{XML_NS}}}base"
SCORE_IMAGE_BASE = "https://www.dbnl.org/tekst/_eva005evan01_01/"
TEI = f"{{{TEI_NS}}}TEI"
SOURCE_LOGICAL = "raw/dbnl/evangelische-gezangen-1806/evangelische-gezangen-1806.xml"
SOURCE_SHA256 = "d8132943dd20b1053d1d77bda57cab2b69c9dc567e38ea4450baab914925abb9"
SOURCE_BYTES = 574306
SOURCE_ID = "dbnl-eva005evan01-1806"
WITNESS_ID = "dbnl-eva005evan01-1806-witness"
WORK_ID = "evangelische-gezangen-1806"
TEXTUAL_FORM_ID = "evangelische-gezangen-1806-dbnl-retained"
EDITION_ID = "evangelische-gezangen-1806-dbnl-electronic"
ACQUISITION_ID = "evangelische-gezangen-1806-dbnl-acquired"
WORK_CATALOG_LINK = {
    "contract": "ocd-workcatalog-link-v1",
    "work_id": WORK_ID,
    "textual_form_id": TEXTUAL_FORM_ID,
    "edition_id": EDITION_ID,
    "acquisition_id": ACQUISITION_ID,
    "work_record": {
        "path": "library/works/evangelische-gezangen-1806/work.json",
        "snapshot_path": "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/work-catalog-work-record.json",
        "sha256": "a2cf66e3e7c5c7916669fd6c098f21d448a63029de311f55ff580b604d2d8e13",
    },
    "state_record": {
        "path": "library/works/evangelische-gezangen-1806/state.json",
        "snapshot_path": "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/work-catalog-state-record.json",
        "sha256": "4e07ee042dbea86f90f3644e04e88f8a2e887706b94a4874c52a15ae1aca9be6",
    },
    "acquisition_record": {
        "path": "library/works/evangelische-gezangen-1806/forms/evangelische-gezangen-1806-dbnl-retained/editions/evangelische-gezangen-1806-dbnl-electronic/acquisitions/evangelische-gezangen-1806-dbnl-acquired.json",
        "snapshot_path": "sources/manifest-acquisitions/l741-evangelische-gezangen-1806/work-catalog-acquisition-record.json",
        "sha256": "b694e97b4560799b8e8027e5d53ed7dee9341e01319f20ac5f3a72f90a634e29",
    },
}
TITLE = "Evangelische Gezangen, om nevens het Boek der Psalmen bij den openbaren godsdienst in de Nederlandsche Hervormde Gemeenten gebruikt te worden"
ORACLE_ID = "ocd-l741-dbnl-evangelische-gezangen-1806-independent-oracle"
ORACLE_VERSION = "3"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _local(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1] if isinstance(node.tag, str) else "comment-or-pi"


def _text(node: ET.Element) -> str:
    return (node.text or "") + "".join(_text(child) + (child.tail or "") for child in list(node))


def _profile(source_manifest: SourceManifest) -> dict[str, Any]:
    return json.loads(source_manifest.authority_path("complete-source-feature-profile").read_bytes())


def _policy(source_manifest: SourceManifest) -> dict[str, Any]:
    return json.loads(source_manifest.authority_path("independent-validation-policy").read_bytes())


def _verify_work_catalog_link(source_manifest: SourceManifest, profile: dict[str, Any]) -> dict[str, Any]:
    expected_ids = {
        "work_id": WORK_ID,
        "textual_form_id": TEXTUAL_FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
    }
    if any(source_manifest.record.get(key) != value for key, value in expected_ids.items()):
        raise ValueError("oracle source manifest does not bind the existing WorkCatalog identity chain")
    if any(profile.get(key) != value for key, value in expected_ids.items()):
        raise ValueError("oracle profile does not bind the existing WorkCatalog identity chain")
    link = profile.get("work_catalog_link")
    if link != WORK_CATALOG_LINK:
        raise ValueError("oracle WorkCatalog link differs from the exact canonical sidecar snapshots")

    work_raw = source_manifest.authority_path("registered-work-identity").read_bytes()
    state_raw = source_manifest.authority_path("registered-work-state").read_bytes()
    acquisition_raw = source_manifest.authority_path("registered-work-acquisition").read_bytes()
    observed_hashes = {
        "work_record": _sha(work_raw),
        "state_record": _sha(state_raw),
        "acquisition_record": _sha(acquisition_raw),
    }
    if any(link[key]["sha256"] != value for key, value in observed_hashes.items()):
        raise ValueError("oracle WorkCatalog snapshot bytes differ from their canonical sidecar digests")

    work = json.loads(work_raw)
    state = json.loads(state_raw)
    acquisition = json.loads(acquisition_raw)
    forms = [entry for entry in work.get("textual_forms", []) if entry.get("textual_form_id") == TEXTUAL_FORM_ID]
    editions = [entry for entry in forms[0].get("editions", []) if entry.get("edition_id") == EDITION_ID] if len(forms) == 1 else []
    if work.get("work_id") != WORK_ID or work.get("title") != TITLE or len(forms) != 1 or len(editions) != 1 or ACQUISITION_ID not in editions[0].get("acquisition_ids", []):
        raise ValueError("oracle WorkCatalog record does not identify the retained title and electronic edition")
    if state.get("work_id") != WORK_ID:
        raise ValueError("oracle WorkCatalog state record points at a different work")
    stages = {
        item.get("target_id"): item.get("stage")
        for item in state.get("targets", [])
        if item.get("target_id") in (EDITION_ID, ACQUISITION_ID)
    }
    if stages != {EDITION_ID: "acquired", ACQUISITION_ID: "acquired"}:
        raise ValueError("oracle WorkCatalog state no longer records the existing edition and acquisition at acquired stage")
    if acquisition.get("acquisition_id") != ACQUISITION_ID or acquisition.get("edition_id") != EDITION_ID or acquisition.get("source_path") != SOURCE_LOGICAL or acquisition.get("source_sha256") != SOURCE_SHA256 or acquisition.get("source_bytes") != SOURCE_BYTES:
        raise ValueError("oracle WorkCatalog acquisition record does not bind the exact retained DBNL XML")
    return dict(link)


def _parse_xml(raw: bytes) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    return ET.fromstring(raw, parser=parser)


def _source_header_slice(raw: bytes) -> bytes:
    start = raw.find(b"<teiHeader>")
    if start < 0 or raw.find(b"<teiHeader>", start + 1) >= 0:
        raise ValueError("oracle did not find exactly one retained L741 teiHeader")
    marker = b"</teiHeader>"
    end = raw.find(marker, start)
    if end < 0:
        raise ValueError("oracle retained L741 teiHeader close tag is absent")
    return raw[start : end + len(marker)]


def _source_and_bundle(source_manifest: SourceManifest, profile: dict[str, Any]) -> tuple[bytes, ET.Element, ET.Element, list[dict[str, Any]]]:
    source_manifest.verify()
    _verify_work_catalog_link(source_manifest, profile)
    source_path = source_manifest.authority_path("retained-dbnl-tei2-xml")
    raw = source_path.read_bytes()
    if len(raw) != SOURCE_BYTES or _sha(raw) != SOURCE_SHA256:
        raise ValueError("oracle retained L741 source bytes differ from exact assigned witness")
    if raw != resolve_repo_path(source_manifest.repository_root, SOURCE_LOGICAL).read_bytes():
        raise ValueError("oracle primary source is not the exact retained L741 storage route")
    bundle_root = resolve_repo_path(source_manifest.repository_root, profile["retained_bundle_root"]).resolve(strict=True)
    actual = {member.name: member for member in bundle_root.iterdir() if member.is_file()}
    expected = {item["name"]: item for item in profile["retained_bundle_members"]}
    if len(expected) != profile.get("retained_bundle_member_count") or len(expected) != 5 or set(actual) != set(expected):
        raise ValueError("oracle current L741 five-file retained source bundle differs")
    for name, item in expected.items():
        content = actual[name].read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(f"oracle current L741 source bundle member differs: {name}")
    receipt = json.loads(source_manifest.authority_path("retained-dbNL-acquisition-receipt").read_bytes())
    if receipt.get("manifest_row") != "L741" or receipt.get("source_id") != "DBNL-_eva005evan01" or receipt.get("member", {}).get("sha256") != SOURCE_SHA256:
        raise ValueError("oracle source receipt does not bind L741 and its exact DBNL XML")
    asset_receipt = json.loads(source_manifest.authority_path("l741-score-image-acquisition-receipt").read_bytes())
    if asset_receipt.get("manifest_row") != "L741" or asset_receipt.get("source_id") != "DBNL-_eva005evan01" or asset_receipt.get("retained_primary_source", {}).get("sha256") != SOURCE_SHA256 or asset_receipt.get("source_target_base") != SCORE_IMAGE_BASE or asset_receipt.get("member_count") != 68:
        raise ValueError("oracle L741 score-image receipt does not bind the exact source")
    receipt_assets = {item["name"]: item for item in asset_receipt["members"]}
    authorities = {item["name"]: item for item in source_manifest.record["authorities"]}
    root = _parse_xml(raw)
    if root.tag != "TEI.2":
        raise ValueError("oracle retained XML root is not TEI.2")
    title_nodes = root.findall("./teiHeader/fileDesc/titleStmt/title")
    edition_nodes = root.findall("./teiHeader/fileDesc/editionStmt/edition")
    title_code = root.findall("./teiHeader/fileDesc/publicationStmt/idno")
    if len(title_nodes) != 1 or _text(title_nodes[0]).strip() != TITLE:
        raise ValueError("oracle exact DBNL TEI.2 title statement differs")
    if len(edition_nodes) != 1 or "eerste druk uit 1806" not in " ".join(_text(edition_nodes[0]).split()):
        raise ValueError("oracle first-edition identity is not present in retained source")
    if not any(node.get("type") == "titelcode" and (node.text or "").strip() == "_eva005evan01_01" for node in title_code):
        raise ValueError("oracle retained DBNL title code differs")
    source_body = root.find("./text/body")
    if source_body is None:
        raise ValueError("oracle retained L741 source has no text/body")
    header_bytes = _source_header_slice(raw)
    if len(header_bytes) != profile["document_envelope"].get("header_raw_byte_count") or _sha(header_bytes) != profile["document_envelope"].get("header_raw_sha256"):
        raise ValueError("oracle source header capture profile differs")
    source_divs = [node for node in list(source_body) if isinstance(node.tag, str) and _local(node) == "div"]
    body_nodes = list(source_body)
    if len(body_nodes) != 199 or len(source_divs) != 198 or _local(body_nodes[0]) != "cf" or any(_local(node) != "div" for node in body_nodes[1:]):
        raise ValueError("oracle exact L741 body top-level structure differs")
    source_paths = _path_map(root)
    source_refs = []
    for node in source_body.iter():
        if not isinstance(node.tag, str) or _local(node) != "xptr":
            continue
        source_refs.append({"source_order": len(source_refs) + 1, "to": node.get("to"), "source_element_path": source_paths[node]})
    expected_refs = profile["source_body"]["external_score_image_pointers"]
    if profile["source_body"].get("score_image_target_base") != SCORE_IMAGE_BASE or len(source_refs) != 68 or len(expected_refs) != 68:
        raise ValueError("oracle source score-image pointer inventory is incomplete")
    for source_ref, item in zip(source_refs, expected_refs, strict=True):
        if any(item.get(key) != source_ref[key] for key in ("source_order", "to", "source_element_path")):
            raise ValueError("oracle source score-image pointer order, target, or source path differs")
        authority = authorities.get(item.get("asset_authority"))
        receipt_item = receipt_assets.get(item["to"])
        if authority is None or receipt_item is None or authority.get("role") != "source-resource" or authority.get("path") != item.get("asset_logical_path") or authority.get("bytes") != item.get("asset_bytes") or authority.get("sha256") != item.get("asset_sha256"):
            raise ValueError(f"oracle L741 score-image authority differs: {item['to']}")
        if receipt_item.get("logical_path") != item.get("asset_logical_path") or receipt_item.get("source_url") != SCORE_IMAGE_BASE + item["to"] or receipt_item.get("content_type") != "image/gif" or receipt_item.get("bytes") != item.get("asset_bytes") or receipt_item.get("sha256") != item.get("asset_sha256") or item.get("asset_url") != receipt_item.get("source_url"):
            raise ValueError(f"oracle L741 score-image receipt/profile mismatch: {item['to']}")
        image_path = source_manifest.authority_path(item["asset_authority"])
        expected_path = resolve_repo_path(source_manifest.repository_root, item["asset_logical_path"]).resolve(strict=True)
        image_bytes = image_path.read_bytes()
        if image_path != expected_path or len(image_bytes) != item["asset_bytes"] or _sha(image_bytes) != item["asset_sha256"] or image_bytes[:6] not in (b"GIF87a", b"GIF89a"):
            raise ValueError(f"oracle retained L741 score-image bytes differ: {item['to']}")
    return raw, root, source_body, expected_refs


def _tag_map(name: str) -> str:
    if name == "cf":
        return "div"
    if name == "xptr":
        return "graphic"
    return name


def _source_nodes(source_body: ET.Element) -> list[ET.Element]:
    nodes = []
    for node in source_body.iter():
        if node is source_body:
            continue
        if not isinstance(node.tag, str):
            raise ValueError("oracle found an unsupported comment or PI inside the L741 source body")
        nodes.append(node)
    return nodes


def _node_record(node: ET.Element, order: int) -> dict[str, Any]:
    name = _local(node)
    text = (node.text or "").encode("utf-8")
    tail = (node.tail or "").encode("utf-8")
    return {
        "source_order": order,
        "source_path": None,
        "source_element": name,
        "candidate_element": _tag_map(name),
        "candidate_xml_id": f"l741-source-element-{order:06d}",
        "source_attributes": dict(sorted(node.attrib.items())),
        "source_text_bytes": len(text),
        "source_text_sha256": _sha(text),
        "source_tail_bytes": len(tail),
        "source_tail_sha256": _sha(tail),
        "candidate_corresp": f"#{WITNESS_ID}",
    }


def _path_map(root: ET.Element) -> dict[ET.Element, str]:
    paths: dict[ET.Element, str] = {root: "/TEI.2"}

    def visit(parent: ET.Element) -> None:
        children = [child for child in list(parent) if isinstance(child.tag, str)]
        totals: dict[str, int] = {}
        seen: dict[str, int] = {}
        for child in children:
            name = _local(child)
            totals[name] = totals.get(name, 0) + 1
        for child in list(parent):
            if not isinstance(child.tag, str):
                continue
            name = _local(child)
            seen[name] = seen.get(name, 0) + 1
            part = f"{name}[{seen[name]}]" if totals[name] > 1 else name
            paths[child] = f"{paths[parent]}/{part}"
            visit(child)

    visit(root)
    return paths


def _mapped_candidate_nodes(root: ET.Element) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    text_node = root.find(f"{{{TEI_NS}}}text")
    if text_node is None:
        return result
    for part in ("front", "body", "back"):
        wrapper = text_node.find(f"{{{TEI_NS}}}{part}")
        if wrapper is None:
            continue
        for node in wrapper.iter():
            if node is wrapper:
                continue
            node_id = node.get(XMLID)
            if node_id and node_id.startswith("l741-source-element-"):
                if node_id in result:
                    raise ValueError("oracle candidate repeats a source-element xml:id")
                result[node_id] = node
    return result


def _compare_source_element_tree(source_body: ET.Element, candidate: ET.Element, source_paths: dict[ET.Element, str]) -> list[dict[str, Any]]:
    sources = _source_nodes(source_body)
    targets = _mapped_candidate_nodes(candidate)
    if len(sources) != len(targets):
        raise ValueError("candidate does not map each source-body element exactly once")
    expected_records = []
    for order, source in enumerate(sources, 1):
        record = _node_record(source, order)
        source_path = source_paths.get(source)
        if source_path is None:
            raise ValueError(f"oracle source locator is absent for {record['candidate_xml_id']}")
        record["source_path"] = source_path
        expected_records.append(record)
        target = targets.get(record["candidate_xml_id"])
        if target is None:
            raise ValueError(f"candidate is missing source node {record['candidate_xml_id']}")
        if _local(target) != record["candidate_element"]:
            raise ValueError(f"candidate element mapping differs at source node {record['candidate_xml_id']}")
        target_attrs = dict(target.attrib)
        expected_attrs: dict[str, str] = {}
        for key, value in source.attrib.items():
            if _local(source) == "xptr" and key == "to":
                continue
            expected_attrs["n" if _local(source) == "interp" and key == "value" else key] = value
        if _local(source) == "xptr":
            expected_attrs["url"] = target.get("url")
        if _local(source) == "cf":
            expected_attrs["type"] = "source-title-matter"
        expected_attrs[XMLID] = record["candidate_xml_id"]
        expected_attrs["corresp"] = f"#{WITNESS_ID}"
        if target_attrs != expected_attrs:
            raise ValueError(f"candidate source attributes or witness link differ at {record['candidate_xml_id']}")
        if (target.text or "") != (source.text or "") or (target.tail or "") != (source.tail or ""):
            raise ValueError(f"candidate source text or tail differs at {record['candidate_xml_id']}")
        expected_children = [f"l741-source-element-{idx:06d}" for idx in _descendant_order_indices(source, sources)]
        actual_children = [child.get(XMLID) for child in list(target)]
        if actual_children != expected_children:
            raise ValueError(f"candidate child order differs at {record['candidate_xml_id']}")
    return expected_records


def _path_map_for_node(node: ET.Element) -> str:
    # Source paths are diagnostic locators; profile pointer paths are checked separately.
    chain = []
    current = node
    while current is not None:
        chain.append(current)
        current = getattr(current, "_parent", None)
    return "/TEI.2/text/body/" + _local(node)


def _descendant_order_indices(source: ET.Element, ordered: list[ET.Element]) -> list[int]:
    wanted = {id(child) for child in list(source)}
    return [i for i, node in enumerate(ordered, 1) if id(node) in wanted]


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    root_path = source_manifest.repository_root
    profile_raw = source_manifest.authority_path("complete-source-feature-profile").read_bytes()
    profile = json.loads(profile_raw)
    policy_raw = source_manifest.authority_path("independent-validation-policy").read_bytes()
    policy = json.loads(policy_raw)
    raw, source_root, source_body, pointers = _source_and_bundle(source_manifest, profile)
    header_raw = _source_header_slice(raw).decode("utf-8", errors="strict")

    xml = candidate.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    document = etree.fromstring(xml, parser)
    if document.tag != TEI:
        raise ValueError("candidate is not one direct TEI P5 root")
    tei_roots = [node for node in document.iter() if node.tag == TEI]
    if len(tei_roots) != 1 or document.get(XMLID) != WORK_ID:
        raise ValueError("candidate must have one top-level TEI root and no descendant TEI roots")
    schema = compiled_schema()
    if not schema.validate(document):
        raise ValueError(f"candidate TEI P5 XSD validation failed: {schema.error_log[:1]}")
    header = document.find(f"{{{TEI_NS}}}teiHeader")
    text_node = document.find(f"{{{TEI_NS}}}text")
    if header is None or text_node is None or [etree.QName(child).localname for child in document] != ["teiHeader", "text"]:
        raise ValueError("candidate direct TEI root structure differs")
    titles = document.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:titleStmt/t:title[@type='main']", namespaces={"t": TEI_NS})
    if len(titles) != 1 or "".join(titles[0].itertext()) != TITLE:
        raise ValueError("candidate title statement differs from the exact retained work")
    source_ids = document.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:publicationStmt/t:idno[@type='source-id']", namespaces={"t": TEI_NS})
    if len(source_ids) != 1 or (source_ids[0].text or "") != SOURCE_ID:
        raise ValueError("candidate source id differs from retained DBNL record")
    header_notes = document.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:notesStmt/t:note[@type='dbnl-tei2-header-xml']", namespaces={"t": TEI_NS})
    doctype_notes = document.xpath("/t:TEI/t:teiHeader/t:fileDesc/t:notesStmt/t:note[@type='source-doctype']", namespaces={"t": TEI_NS})
    if len(header_notes) != 1 or header_notes[0].get(XMLID) != WITNESS_ID or (header_notes[0].text or "") != header_raw:
        raise ValueError("candidate exact source-header byte slice is absent or changed")
    doctype_match = re.search(rb'<!DOCTYPE TEI\.2 PUBLIC "[^\"]+" "[^\"]+">', raw)
    if doctype_match is None or len(doctype_notes) != 1 or (doctype_notes[0].text or "").encode("utf-8") != doctype_match.group(0):
        raise ValueError("candidate source DTD declaration record differs")

    wrappers = [text_node.find(f"{{{TEI_NS}}}{name}") for name in ("front", "body", "back")]
    if any(node is None for node in wrappers):
        raise ValueError("candidate text must contain exactly front, body, and back")
    front, body, back = wrappers
    if [etree.QName(child).localname for child in text_node] != ["front", "body", "back"]:
        raise ValueError("candidate text division order differs")
    source_children = list(source_body)
    source_divs = [node for node in source_children if isinstance(node.tag, str) and _local(node) == "div"]
    expected_front_ids = ["l741-source-element-000001"]
    source_nodes = _source_nodes(source_body)
    source_index = {id(node): index for index, node in enumerate(source_nodes, 1)}
    expected_front_ids = [f"l741-source-element-{source_index[id(node)]:06d}" for node in [source_children[0], *source_divs[:2]]]
    expected_body_ids = [f"l741-source-element-{source_index[id(node)]:06d}" for node in source_divs[2:194]]
    expected_back_ids = [f"l741-source-element-{source_index[id(node)]:06d}" for node in source_divs[194:]]
    for wrapper, expected_ids, label in ((front, expected_front_ids, "front"), (body, expected_body_ids, "body"), (back, expected_back_ids, "back")):
        if [child.get(XMLID) for child in wrapper] != expected_ids:
            raise ValueError(f"candidate {label} source division boundary or order differs")
    if len(expected_front_ids) != 3 or len(expected_body_ids) != 192 or len(expected_back_ids) != 4:
        raise ValueError("oracle source division partition differs from the pinned one-work profile")
    expected_text = _text(source_body)
    candidate_text = _text(text_node)
    if candidate_text != expected_text:
        raise ValueError("candidate source-body text stream differs from retained XML")
    if _sha(candidate_text.encode("utf-8")) != profile["source_body"]["text_stream_sha256"]:
        raise ValueError("candidate source text-stream digest differs from the profiled witness")

    source_paths = _path_map(source_root)
    node_records = _compare_source_element_tree(source_body, document, source_paths)
    source_body_counts: dict[str, int] = {}
    for node in _source_nodes(source_body):
        source_body_counts[_local(node)] = source_body_counts.get(_local(node), 0) + 1
    candidate_labels = [node.get("n") for node in document.xpath(".//t:pb", namespaces={"t": TEI_NS})]
    source_labels = [node.get("n") for node in source_body.iter() if isinstance(node.tag, str) and _local(node) == "pb"]
    if candidate_labels != source_labels or len(candidate_labels) != 414:
        raise ValueError("candidate 414 page-break labels or order differs")
    if len(document.xpath(".//t:lg[@type='poem']", namespaces={"t": TEI_NS})) != 265:
        raise ValueError("candidate poem-group count differs from source (265)")
    interp_values = [
        {"type": node.get("type"), "value": node.get("value")}
        for node in source_body.iter()
        if isinstance(node.tag, str) and _local(node) == "interp"
    ]
    candidate_interps = [
        {"type": node.get("type"), "value": node.get("n")}
        for node in document.xpath(".//t:interp", namespaces={"t": TEI_NS})
    ]
    if candidate_interps != interp_values or len(candidate_interps) != 194:
        raise ValueError("candidate tune/song interp values or their order differ")
    for local, expected_count in (("interpGrp", 193), ("table", 26), ("row", 192), ("cell", 384), ("figure", 68), ("graphic", 68)):
        count = len(document.xpath(f".//t:{local}", namespaces={"t": TEI_NS}))
        if count != expected_count:
            raise ValueError(f"candidate {local} count differs from source ({expected_count})")
    candidate_graphics = document.xpath(".//t:graphic", namespaces={"t": TEI_NS})
    candidate_targets = [node.get("url") for node in candidate_graphics]
    source_targets = [node.get("to") for node in source_body.iter() if isinstance(node.tag, str) and _local(node) == "xptr"]
    expected_targets = [source_manifest.authority_path(item["asset_authority"]).resolve(strict=True).as_uri() for item in pointers]
    if candidate_targets != expected_targets or any(node.get(XMLBASE) is not None for node in candidate_graphics):
        raise ValueError("candidate score-image links are not exact local file URIs to retained resources")
    for item, target in zip(pointers, candidate_targets, strict=True):
        retained = source_manifest.authority_path(item["asset_authority"]).resolve(strict=True)
        if target != retained.as_uri():
            raise ValueError(f"candidate score-image URI differs from retained source target: {target}")
        content = retained.read_bytes()
        if len(content) != item["asset_bytes"] or _sha(content) != item["asset_sha256"]:
            raise ValueError(f"candidate local score-image URI target bytes differ from retained source: {target}")

    corrections = [
        "".join(node.itertext()).strip()
        for node in source_root.findall("./teiHeader/fileDesc/editionStmt/respStmt/resp/corr")
    ]
    candidate_corrections = [
        "".join(node.itertext()).strip()
        for node in document.xpath("/t:TEI/t:teiHeader/t:encodingDesc/t:editorialDecl/t:correction/t:p", namespaces={"t": TEI_NS})
    ]
    if len(corrections) != 3 or candidate_corrections != corrections:
        raise ValueError("candidate DBNL editorial intervention statements differ")

    account = json.loads(candidate.member_bytes("source-accountability.json"))
    source_manifest_logical = source_manifest.path.relative_to(root_path).as_posix()
    if account.get("source_manifest") != {"path": source_manifest_logical, "sha256": source_manifest.sha256}:
        raise ValueError("candidate source-accountability manifest linkage differs")
    if any(account.get(key) != value for key, value in {
        "work_id": WORK_ID,
        "textual_form_id": TEXTUAL_FORM_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "work_catalog_link": profile["work_catalog_link"],
    }.items()):
        raise ValueError("candidate source-accountability WorkCatalog identity linkage differs")
    if account.get("primary_source") != profile["primary_source"] or account.get("retained_bundle_members") != profile["retained_bundle_members"] or account.get("retained_bundle_member_count") != profile["retained_bundle_member_count"]:
        raise ValueError("candidate primary-source or retained bundle accounting differs")
    if account.get("source_element_counts") != profile["source_element_counts"] or account.get("source_comment_count") != profile["source_comment_count"]:
        raise ValueError("candidate full source element or comment inventory differs")
    source_account = account.get("source_body", {})
    if source_account.get("source_body_element_count") != len(node_records) or source_account.get("one_to_one_source_element_map") != node_records:
        raise ValueError("candidate source-to-P5 element accounting is not complete and one-to-one")
    if source_account.get("source_text_character_count") != len(expected_text) or source_account.get("source_text_stream_sha256") != _sha(expected_text.encode("utf-8")) or source_account.get("candidate_text_stream_sha256") != _sha(candidate_text.encode("utf-8")) or source_account.get("candidate_text_stream_matches_source") is not True:
        raise ValueError("candidate source text-stream accounting differs")
    if source_account.get("page_break_count") != 414 or source_account.get("page_break_labels") != source_labels or source_account.get("poem_group_count") != 265 or source_account.get("interp_group_count") != 193 or source_account.get("interp_count") != 194 or source_account.get("interp_values") != interp_values:
        raise ValueError("candidate page, poem, or tune/song relation accounting differs")
    expected_packaged_images = [
        {"uri": source_manifest.authority_path(item["asset_authority"]).resolve(strict=True).as_uri(), "source_path": item["asset_logical_path"], "bytes": item["asset_bytes"], "sha256": item["asset_sha256"]}
        for item in pointers
    ]
    if source_account.get("table_count") != 26 or source_account.get("table_row_count") != 192 or source_account.get("table_cell_count") != 384 or source_account.get("figure_count") != 68 or source_account.get("external_score_image_pointers") != pointers or source_account.get("candidate_score_image_links") != expected_packaged_images:
        raise ValueError("candidate index, score, or packaged local target accounting differs")
    tei_account = account.get("candidate_tei", {})
    if tei_account.get("member") != "content.tei.xml" or tei_account.get("bytes") != len(xml) or tei_account.get("sha256") != _sha(xml) or tei_account.get("direct_root_qname") != TEI or tei_account.get("root_type") != "TEI" or tei_account.get("root_count") != 1 or tei_account.get("descendant_tei_count") != 0 or tei_account.get("mapped_source_element_count") != len(node_records) or tei_account.get("source_mapped_elements_one_to_one") is not True or tei_account.get("text_children") != ["front", "body", "back"]:
        raise ValueError("candidate TEI root count or source linkage accounting differs")
    if account.get("editorial_interventions") != corrections or account.get("limitations") != profile["limitations"] or account.get("complete_source_accounting") is not True or account.get("status") != "nonaccepted":
        raise ValueError("candidate intervention, source-gap, or nonaccepted accounting differs")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("candidate source attribution README differs")
    if json.loads(candidate.member_bytes("provenance.json")) != policy["provenance"]:
        raise ValueError("candidate provenance differs from the source policy")
    expected_unresolved_bytes = b"".join(_canonical(item) for item in policy["unresolved"])
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved_bytes:
        raise ValueError("candidate unresolved resource and review-gap sidecar differs")
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_id") != SOURCE_ID:
        raise ValueError("candidate package status or source identity differs")

    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure(root_path),
        source_sha256=SOURCE_SHA256,
        profile_sha256=_sha(profile_raw),
        package_schema_sha256=_sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_raw),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


def _closure(root: Path) -> str:
    paths = (
        "build/tei/l741_evangelische_gezangen_1806_oracle.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
        "ocd_kernel/tei/validate.py",
    )
    inventory = [{"path": item, "sha256": _sha((root / item).read_bytes())} for item in paths]
    return _sha(_canonical(inventory))


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
