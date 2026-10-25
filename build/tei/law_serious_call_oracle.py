"""Independent stdlib-XML oracle for the retained Law / Serious Call witness."""

from __future__ import annotations

from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-law-serious-call-independent-stdlib-xml-oracle"
ORACLE_VERSION = "1"
WORK_ID = "law-serious-call"
SOURCE_ID = "law-serious-call-retained-thml"
SOURCE_PATH = "raw/ccel/law/serious_call.xml"
SOURCE_SHA256 = "edc2bf6021f36bb7e42e1feb819c37492f920595e05ed31e22d52e7caa12c2bd"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
DOCTYPE_RE = re.compile(rb"<!DOCTYPE\s[^\[>]*(?:\[[^]]*\])?>", re.IGNORECASE | re.DOTALL)
ENTITY_RE = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
ENTITY_WHITELIST = {b"amp", b"lt", b"gt", b"quot", b"apos"}
EVENT_RE = re.compile(
    r"(?P<doctype><!DOCTYPE\s[^\[>]*(?:\[[^]]*\])?>)"
    r"|(?P<comment><!--[\s\S]*?-->)"
    r"|(?P<pi><\?(?!xml(?:\s|\?>))[\s\S]*?\?>)",
    re.IGNORECASE,
)
DATE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:MDCCXXIX|1728|1729)(?![A-Za-z0-9])", re.I)
TEI_BODY_TAGS = {
    "a": "ref",
    "added": "div",
    "br": "lb",
    "h1": "head",
    "h2": "head",
    "h3": "head",
    "i": "hi",
    "insertIndex": "anchor",
    "note": "note",
    "p": "p",
    "scripRef": "ref",
}
NAVIGATION_EXCEPTION_ROWS = (
    {
        "id": "navigation-prev-toc-title-page",
        "source_sha256": SOURCE_SHA256,
        "selector": "/ThML[1]/ThML.body[1]/div1[1]",
        "direction": "prev",
        "raw_target": "toc",
        "carrier_id": "i",
        "disposition": "source-target-absent",
        "owner": "source-evidence-maintainer",
        "reopening_condition": "An exact retained witness or primary-source record identifies the destination of this source assertion; rebind and independently reverify without inventing an ID or redirecting to a generated navigation title.",
    },
    {
        "id": "navigation-next-toc-acknowledgements",
        "source_sha256": SOURCE_SHA256,
        "selector": "/ThML[1]/ThML.body[1]/div1[30]",
        "direction": "next",
        "raw_target": "toc",
        "carrier_id": "xxx",
        "disposition": "source-target-absent",
        "owner": "source-evidence-maintainer",
        "reopening_condition": "An exact retained witness or primary-source record identifies the destination of this source assertion; rebind and independently reverify without inventing an ID or redirecting to a generated navigation title.",
    },
)
SOURCE_NAVIGATION_POLICY = {
    "verification_allowance": "permitted-with-exactly-the-declared-source-target-absent-edges",
    "permitted_unresolved_edge_ids": [row["id"] for row in NAVIGATION_EXCEPTION_ROWS],
    "all_other_edges": "must-resolve-within-complete-retained-member-and-remain-in-tei-prev-next",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_object(content: bytes, label: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("source manifest authorities are invalid")
    matches = [item for item in authorities if isinstance(item, Mapping) and item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"source manifest authority {name!r} is not unique")
    return matches[0]


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _tag(node: ET.Element) -> str:
    if not isinstance(node.tag, str):
        return ""
    return node.tag.split("}", 1)[-1]


def _element_children(node: ET.Element) -> list[ET.Element]:
    return [child for child in list(node) if isinstance(child.tag, str)]


def _all_elements(root: ET.Element) -> list[ET.Element]:
    return [node for node in root.iter() if isinstance(node.tag, str)]


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    parents: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in _element_children(parent):
            parents[child] = parent
    return parents


def _selector(node: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> str:
    fragments: list[str] = []
    current = node
    while True:
        parent = parents.get(current)
        peers = _element_children(parent) if parent is not None else [current]
        same = [child for child in peers if child.tag == current.tag]
        fragments.append(f"{_tag(current)}[{same.index(current) + 1}]")
        if parent is None:
            break
        current = parent
    return "/" + "/".join(reversed(fragments))


def _parse_source(raw: bytes) -> tuple[ET.Element, list[dict[str, object]]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("independent reader requires UTF-8 retained ThML") from exc
    events = [
        {
            "ordinal": ordinal,
            "kind": str(match.lastgroup),
            "bytes": len(match.group(0).encode("utf-8")),
            "sha256": _sha(match.group(0).encode("utf-8")),
            "lexical": match.group(0),
        }
        for ordinal, match in enumerate(EVENT_RE.finditer(text), start=1)
    ]
    if sum(row["kind"] == "doctype" for row in events) != 1:
        raise ValueError("independent reader requires one byte-accounted external DOCTYPE")
    prepared, substitutions = DOCTYPE_RE.subn(b"", raw, count=1)
    if substitutions != 1:
        raise ValueError("independent reader could not safely isolate the external DOCTYPE")
    unknown = sorted(set(ENTITY_RE.findall(prepared)) - ENTITY_WHITELIST)
    if unknown:
        raise ValueError(f"independent reader found an unsupported named entity: {unknown[0]!r}")
    builder = ET.TreeBuilder(insert_comments=True, insert_pis=True)
    parser = ET.XMLParser(target=builder)
    try:
        root = ET.fromstring(prepared, parser=parser)
    except ET.ParseError as exc:
        raise ValueError("independent stdlib reader rejected retained ThML") from exc
    if root.tag != "ThML":
        raise ValueError("independent reader found an unexpected ThML root")
    return root, events


def _source_profile_and_policy(source_manifest: SourceManifest) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = _strict_object(_authority_bytes(source_manifest, "law-serious-call-source-profile"), "source profile")
    policy = _strict_object(_authority_bytes(source_manifest, "law-serious-call-independent-validation-policy"), "validation policy")
    if profile.get("contract") != "ocd-law-serious-call-source-profile-v1" or profile.get("profile_id") != "law-serious-call-whole-retained-thml-v1":
        raise ValueError("independent reader rejects the source profile identity")
    if profile.get("work_id") != WORK_ID or profile.get("source_id") != SOURCE_ID:
        raise ValueError("independent reader rejects the work/source profile identity")
    if policy.get("contract") != "ocd-law-serious-call-independent-validation-policy-v1":
        raise ValueError("independent reader rejects the validation policy contract")
    if policy.get("work_id") != WORK_ID or policy.get("source_id") != SOURCE_ID:
        raise ValueError("independent reader rejects the validation policy identity")
    return profile, policy


def _id_value(node: ET.Element, ordinal: int, root: ET.Element, body: ET.Element, header: ET.Element, body_ordinals: Mapping[ET.Element, int], header_ordinals: Mapping[ET.Element, int]) -> str:
    if node is root:
        return WORK_ID
    if node is body:
        return f"{WORK_ID}-text"
    if node in body_ordinals:
        value = node.attrib.get("id")
        return value or f"{WORK_ID}-body-node-{body_ordinals[node]:05d}"
    if node in header_ordinals:
        value = node.attrib.get("id")
        return value or f"{WORK_ID}-header-node-{header_ordinals[node]:05d}"
    raise ValueError(f"independent reader cannot associate source node {ordinal} with TEI")


def _date_claim_rows(profile: Mapping[str, Any], policy: Mapping[str, Any], root: ET.Element) -> list[dict[str, object]]:
    profile_claims = profile.get("date_claims")
    unresolved = policy.get("unresolved")
    if not isinstance(profile_claims, list) or not isinstance(unresolved, list):
        raise ValueError("independent reader found an incomplete date evidence inventory")
    conflict = next((item for item in unresolved if isinstance(item, Mapping) and item.get("id") == "original-publication-date-conflict"), None)
    if not isinstance(conflict, Mapping) or not isinstance(conflict.get("claims"), list):
        raise ValueError("independent reader found no explicit date conflict")
    expected_by_path = {str(item.get("source_locator")): item for item in conflict["claims"] if isinstance(item, Mapping)}
    by_id = {node.attrib.get("id"): node for node in _all_elements(root) if node.attrib.get("id")}
    rows: list[dict[str, object]] = []
    for profile_claim in profile_claims:
        if not isinstance(profile_claim, Mapping):
            raise ValueError("independent reader found an invalid profile date claim")
        path = str(profile_claim.get("source_locator"))
        authority_claim = expected_by_path.get(path)
        if authority_claim is None:
            raise ValueError("date policy claim is missing its profiled source locator")
        locator_match = re.search(r"@id='([^']+)'", path)
        if locator_match is None or locator_match.group(1) not in by_id:
            raise ValueError("independent reader cannot resolve a profiled date locator")
        node = by_id[locator_match.group(1)]
        tokens = sorted(set(DATE_TOKEN_RE.findall("".join(node.itertext()))))
        tokens = [token.upper() if token.casefold() == "mdccxxix" else token for token in tokens]
        if tokens != profile_claim.get("tokens"):
            raise ValueError("source date text differs from the exact profiled tokens")
        rows.append({
            "value": authority_claim.get("value"),
            "source_locator": path,
            "source_tokens": tokens,
            "role": profile_claim.get("role"),
        })
    if len(rows) != len(expected_by_path):
        raise ValueError("date policy has a claim outside the complete profiled evidence set")
    years = {row["value"] for row in rows}
    if years != {"1728", "1729"}:
        raise ValueError("independent reader requires the source date disagreement to remain unresolved")
    return rows


def _event_records(events: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for event in events:
        kind = event["kind"]
        if kind == "comment":
            disposition = "preserved-as-tei-comment"
        elif kind == "doctype":
            disposition = "external-doctype-not-loaded-or-copied"
        else:
            disposition = "processing-instruction-accountability-only"
        result.append({
            "ordinal": event["ordinal"],
            "kind": kind,
            "bytes": event["bytes"],
            "sha256": event["sha256"],
            "disposition": disposition,
        })
    return result


def _regions_and_types(count: int) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for ordinal in range(1, count + 1):
        if ordinal == 1:
            rows.append(("front", "title-page"))
        elif ordinal <= 25:
            rows.append(("body", "chapter"))
        elif ordinal <= 28:
            rows.append(("back", "appendix"))
        elif ordinal == 29:
            rows.append(("back", "indexes"))
        else:
            rows.append(("back", "acknowledgments"))
    return rows


def _division_records(root: ET.Element, body: ET.Element, profile: Mapping[str, Any], parents: Mapping[ET.Element, ET.Element], body_ordinals: Mapping[ET.Element, int]) -> list[dict[str, object]]:
    divisions = [node for node in _element_children(body) if _tag(node) == "div1"]
    expected = profile.get("ordered_divisions")
    if not isinstance(expected, list) or len(divisions) != 30 or len(expected) != len(divisions):
        raise ValueError("independent reader rejects an incomplete 30-division source envelope")
    region_types = _regions_and_types(len(divisions))
    records: list[dict[str, object]] = []
    for ordinal, (node, expected_row, classification) in enumerate(zip(divisions, expected, region_types, strict=True), start=1):
        row = {
            "ordinal": ordinal,
            "source_id": node.attrib.get("id"),
            "source_n": node.attrib.get("n"),
            "source_title": node.attrib.get("title"),
            "selector": _selector(node, parents),
            "region": classification[0],
            "tei_type": classification[1],
            "target_xml_id": node.attrib.get("id") or f"{WORK_ID}-body-node-{body_ordinals[node]:05d}",
        }
        if row != expected_row:
            raise ValueError("independent reader rejects changed source division order or boundaries")
        records.append(row)
    return records


def _navigation_records(body: ET.Element, parents: Mapping[ET.Element, ET.Element], body_ordinals: Mapping[ET.Element, int], divisions: list[dict[str, object]]) -> list[dict[str, object]]:
    region_by_id = {str(row["source_id"]): (row["region"], row["tei_type"]) for row in divisions}
    carriers = [
        node for node in body.iter()
        if isinstance(node.tag, str) and _tag(node) in {"div1", "div2", "div"} and "title" in node.attrib
    ]
    rows: list[dict[str, object]] = []
    for ordinal, node in enumerate(carriers, start=1):
        source_id = node.attrib.get("id")
        region, tei_type = region_by_id.get(str(source_id), (None, None))
        rows.append({
            "ordinal": ordinal,
            "source_id": source_id,
            "source_n": node.attrib.get("n"),
            "source_title": node.attrib["title"],
            "source_qname": _tag(node),
            "selector": _selector(node, parents),
            "region": region,
            "tei_type": tei_type,
            "target_xml_id": source_id or f"{WORK_ID}-body-node-{body_ordinals[node]:05d}",
            "candidate_xml_id": f"{WORK_ID}-navigation-title-{ordinal:03d}",
        })
    return rows


def _source_navigation_exceptions(
    root: ET.Element,
    body: ET.Element,
    parents: Mapping[ET.Element, ET.Element],
    profile: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, object]]:
    source_ids = {
        node.attrib["id"]
        for node in _all_elements(root)
        if "id" in node.attrib
    }
    if "toc" in source_ids:
        raise ValueError("independent reader found an invented source element id 'toc'")

    edge_count = 0
    resolved_count = 0
    missing: list[dict[str, str | None]] = []
    for node in _all_elements(body):
        for direction in ("prev", "next"):
            raw_target = node.attrib.get(direction)
            if raw_target is None:
                continue
            edge_count += 1
            if raw_target in source_ids:
                resolved_count += 1
                continue
            missing.append({
                "selector": _selector(node, parents),
                "direction": direction,
                "raw_target": raw_target,
                "carrier_id": node.attrib.get("id"),
            })

    expected_missing = [
        {
            "selector": row["selector"],
            "direction": row["direction"],
            "raw_target": row["raw_target"],
            "carrier_id": row["carrier_id"],
        }
        for row in NAVIGATION_EXCEPTION_ROWS
    ]
    if (edge_count, resolved_count, missing) != (62, 60, expected_missing):
        raise ValueError("independent reader found navigation edges beyond the two exact absent-target assertions")

    source_navigation = profile.get("source_navigation")
    if not isinstance(source_navigation, Mapping) or set(source_navigation) != {
        "edge_count",
        "resolved_edge_count",
        "unresolved_edges",
    }:
        raise ValueError("independent reader rejects incomplete source navigation accounting")
    if (
        source_navigation.get("edge_count") != edge_count
        or source_navigation.get("resolved_edge_count") != resolved_count
        or source_navigation.get("unresolved_edges") != list(NAVIGATION_EXCEPTION_ROWS)
    ):
        raise ValueError("independent reader rejects changed source navigation profile records")
    if policy.get("source_navigation") != SOURCE_NAVIGATION_POLICY:
        raise ValueError("independent reader rejects a broader source navigation verification allowance")

    unresolved = policy.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("independent reader has no unresolved issue inventory")
    actual_policy_edges = [
        item for item in unresolved
        if isinstance(item, Mapping) and item.get("category") == "source-navigation-edge"
    ]
    expected_policy_edges = [
        {"status": "unresolved", "category": "source-navigation-edge", **row}
        for row in NAVIGATION_EXCEPTION_ROWS
    ]
    navigation_prefixed = [
        item for item in unresolved
        if isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
        and item["id"].startswith("navigation-")
    ]
    if actual_policy_edges != expected_policy_edges or navigation_prefixed != expected_policy_edges:
        raise ValueError("independent reader rejects changed or additional unresolved navigation records")
    return [dict(row) for row in NAVIGATION_EXCEPTION_ROWS]


def _source_census(root: ET.Element, body: ET.Element) -> tuple[dict[str, int], dict[str, int], dict[str, int], str]:
    elements = _all_elements(root)
    body_elements = _all_elements(body)
    all_counts = Counter(_tag(node) for node in elements)
    body_counts = Counter(_tag(node) for node in body_elements)
    attributes = Counter(key for node in elements for key in node.attrib)
    ids = [node.attrib["id"] for node in elements if "id" in node.attrib]
    if len(ids) != len(set(ids)):
        raise ValueError("independent reader found duplicate source ids")
    hrefs = [node.attrib["href"] for node in body_elements if _tag(node) == "a" and "href" in node.attrib]
    census = {
        "elements": len(elements),
        "body_elements": len(body_elements),
        "attributes": sum(len(node.attrib) for node in elements),
        "ids": len(ids),
        "notes": sum(_tag(node) == "note" for node in body_elements),
        "scripture_references": sum(_tag(node) == "scripRef" for node in body_elements),
        "links": len(hrefs),
        "characters": sum(len(node.text or "") + len(node.tail or "") for node in elements),
        "internal_links": sum(value.startswith("#") for value in hrefs),
        "external_links": sum(not value.startswith("#") for value in hrefs),
    }
    ordered_id_hash = _sha("\n".join(ids).encode("utf-8"))
    return dict(sorted(all_counts.items())), dict(sorted(body_counts.items())), {**census, **{f"attribute:{key}": value for key, value in sorted(attributes.items())}}, ordered_id_hash


def _target_id_map(root: ET.Element, body: ET.Element, header: ET.Element) -> tuple[dict[ET.Element, int], dict[ET.Element, int], dict[ET.Element, int]]:
    elements = _all_elements(root)
    body_ordinals = {node: ordinal for ordinal, node in enumerate(_all_elements(body), start=1)}
    header_ordinals = {node: ordinal for ordinal, node in enumerate(_all_elements(header), start=1)}
    all_ordinals = {node: ordinal for ordinal, node in enumerate(elements, start=1)}
    return body_ordinals, header_ordinals, all_ordinals


def _feature_rows(root: ET.Element, body: ET.Element, header: ET.Element, parents: Mapping[ET.Element, ET.Element], ordinals: tuple[dict[ET.Element, int], dict[ET.Element, int], dict[ET.Element, int]]) -> list[dict[str, object]]:
    body_ordinals, header_ordinals, all_ordinals = ordinals
    body_set = set(body_ordinals)
    header_set = set(header_ordinals)
    result = []
    for ordinal, node in enumerate(_all_elements(root), start=1):
        parent = parents.get(node)
        peer_nodes = _element_children(parent) if parent is not None else [node]
        if node is root:
            disposition = "represented-by-tei-root"
        elif node is body:
            disposition = "represented-by-tei-text"
        elif node in body_set:
            disposition = "represented-in-tei-body"
        elif node in header_set:
            disposition = "represented-in-tei-header"
        else:
            raise ValueError("independent reader found an element outside ThML.head/ThML.body")
        result.append({
            "ordinal": ordinal,
            "selector": _selector(node, parents),
            "qname": str(node.tag),
            "attributes": [{"qname": key, "value": value} for key, value in sorted(node.attrib.items())],
            "parent_ordinal": all_ordinals[parent] if parent is not None else None,
            "child_ordinal": peer_nodes.index(node) + 1,
            "text_characters": len(node.text or ""),
            "text_sha256": _sha((node.text or "").encode("utf-8")),
            "tail_characters": len(node.tail or ""),
            "tail_sha256": _sha((node.tail or "").encode("utf-8")),
            "disposition": disposition,
            "target_xml_id": _id_value(node, ordinal, root, body, header, body_ordinals, header_ordinals),
        })
    targets = [row["target_xml_id"] for row in result]
    if len(targets) != len(set(targets)):
        raise ValueError("independent reader found a nonunique source-to-TEI ID map")
    return result


def _expected_accountability(source_manifest: SourceManifest, raw: bytes, root: ET.Element, events: list[dict[str, object]], profile: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, object]:
    body = root.find("ThML.body")
    header = root.find("ThML.head")
    if body is None or header is None:
        raise ValueError("independent reader requires the whole ThML head and body")
    parents = _parent_map(root)
    ordinals = _target_id_map(root, body, header)
    all_counts, body_counts, census_and_attrs, id_hash = _source_census(root, body)
    census = {key: value for key, value in census_and_attrs.items() if ":" not in key}
    attributes = {key.removeprefix("attribute:"): value for key, value in census_and_attrs.items() if key.startswith("attribute:")}
    carriers = profile.get("source_carriers")
    if not isinstance(carriers, Mapping) or (
        all_counts != carriers.get("element_counts")
        or body_counts != carriers.get("body_element_counts")
        or census["elements"] != carriers.get("element_count")
        or census["body_elements"] != carriers.get("body_element_count")
        or census["attributes"] != carriers.get("attribute_count")
        or census["ids"] != carriers.get("unique_id_attribute_count")
        or census["notes"] != carriers.get("note_count")
        or census["scripture_references"] != carriers.get("scripture_reference_count")
        or census["links"] != carriers.get("anchor_count")
        or census["internal_links"] != carriers.get("local_link_count")
        or census["external_links"] != carriers.get("external_link_count")
        or attributes != carriers.get("attribute_name_counts")
        or id_hash != carriers.get("id_values_sha256")
    ):
        raise ValueError("independent source carrier census differs from the pinned profile")
    divisions = _division_records(root, body, profile, parents, ordinals[0])
    navigation_titles = _navigation_records(body, parents, ordinals[0], divisions)
    profile_titles = profile.get("navigation_titles")
    if not isinstance(profile_titles, list) or len(profile_titles) != len(navigation_titles):
        raise ValueError("independent reader rejects the navigation-title inventory length")
    for observed, expected in zip(navigation_titles, profile_titles, strict=True):
        comparable = {
            "ordinal": observed["ordinal"],
            "source_id": observed["source_id"],
            "source_n": observed["source_n"],
            "source_title": observed["source_title"],
            "source_qname": observed["source_qname"],
            "source_selector": observed["selector"],
            "target_xml_id": observed["target_xml_id"],
            "candidate_xml_id": observed["candidate_xml_id"],
        }
        if comparable != expected:
            raise ValueError("independent reader rejects the navigation-title inventory")
    profile_scope = profile.get("source_scope")
    if not isinstance(profile_scope, Mapping) or (
        profile_scope.get("member_count") != 1
        or profile_scope.get("member_path") != SOURCE_PATH
        or profile_scope.get("member_bytes") != len(raw)
        or profile_scope.get("member_sha256") != _sha(raw)
        or profile_scope.get("selector") != "/ThML[1]"
        or profile_scope.get("body_selector") != "/ThML[1]/ThML.body[1]"
        or profile_scope.get("disposition") != "complete-whole-retained-member"
    ):
        raise ValueError("independent reader rejects the source-member envelope")
    date_claims = _date_claim_rows(profile, policy, root)
    navigation_exceptions = _source_navigation_exceptions(root, body, parents, profile, policy)
    member = _authority(source_manifest, "law-serious-call-retained-source")
    event_profile = profile.get("non_element_events")
    observed_events = [{key: event[key] for key in ("ordinal", "kind", "bytes", "sha256")} for event in events]
    if not isinstance(event_profile, Mapping) or observed_events != event_profile.get("events"):
        raise ValueError("independent reader rejects the source lexical-event inventory")
    title_target_rows = []
    for row in navigation_titles:
        division = next((item for item in divisions if item["source_id"] == row["source_id"]), None)
        title_target_rows.append({
            "ordinal": row["ordinal"],
            "source_id": row["source_id"],
            "source_n": row["source_n"],
            "source_title": row["source_title"],
            "selector": row["selector"],
            "region": division["region"] if division else None,
            "tei_type": division["tei_type"] if division else None,
            "target_xml_id": row["target_xml_id"],
            "candidate_xml_id": row["candidate_xml_id"],
        })
    return {
        "contract": "ocd-law-serious-call-source-accountability-v1",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": int(member["bytes"]),
            "sha256": str(member["sha256"]),
            "selector": "/ThML[1]",
            "disposition": "complete-whole-retained-member",
        },
        "source_census": census,
        "element_counts": all_counts,
        "body_element_counts": body_counts,
        "ordered_divisions": divisions,
        "navigation_titles": title_target_rows,
        "source_navigation": {
            "edge_count": 62,
            "resolved_edge_count": 60,
            "unresolved_edges": navigation_exceptions,
        },
        "features": _feature_rows(root, body, header, parents, ordinals),
        "non_element_events": _event_records(events),
        "unresolved_date_claims": date_claims,
        "dispositions": {
            "unsupported_element_count": 0,
            "excluded_member_count": 0,
            "excluded_body_carrier_count": 0,
            "date_conflict": "unresolved",
            "rights_review": "not-decided",
            "accepted_master": False,
        },
    }


def _source_metadata(root: ET.Element) -> dict[str, str]:
    try:
        head = root.find("ThML.head")
        electronic = head.find("electronicEdInfo") if head is not None else None
        dc = electronic.find("DC") if electronic is not None else None
        title = dc.find("DC.Title") if dc is not None else None
        author = next((node for node in dc.findall("DC.Creator") if node.attrib.get("scheme") == "short-form"), None) if dc is not None else None
        language = dc.find("DC.Language") if dc is not None else None
        publisher = dc.find("DC.Publisher") if dc is not None else None
    except AttributeError as exc:
        raise ValueError("independent reader cannot inspect source metadata") from exc
    return {
        "title": "".join(title.itertext()) if title is not None else "",
        "author": "".join(author.itertext()) if author is not None else "",
        "language": "".join(language.itertext()) if language is not None else "",
        "provider": "".join(publisher.itertext()) if publisher is not None else "",
    }


def _expected_provenance(source_manifest: SourceManifest, raw: bytes, root: ET.Element, events: list[dict[str, object]], profile: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, object]:
    config_authority = _authority(source_manifest, "law-serious-call-source-config")
    metadata_authority = _authority(source_manifest, "law-serious-call-metadata-sidecar")
    profile_authority = _authority(source_manifest, "law-serious-call-source-profile")
    attribution_authority = _authority(source_manifest, "law-serious-call-data-attribution")
    config = _strict_object(_authority_bytes(source_manifest, "law-serious-call-source-config"), "source config")
    metadata = _source_metadata(root)
    identity = policy.get("provenance")
    identity = identity.get("identity") if isinstance(identity, Mapping) else None
    if not isinstance(identity, Mapping) or metadata["title"] != identity.get("title") or metadata["author"] != identity.get("author"):
        raise ValueError("independent reader rejects source identity metadata")
    if config.get("resource_id") != WORK_ID or config.get("title") != metadata["title"] or config.get("author") != metadata["author"]:
        raise ValueError("independent reader rejects config/source identity drift")
    if config.get("source_hash") != f"sha256:{_sha(raw)}":
        raise ValueError("independent reader rejects the legacy config source hash")
    date_claims = _date_claim_rows(profile, policy, root)
    scope = profile.get("source_scope")
    return {
        "contract": "ocd-law-serious-call-provenance-v1",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "status": "nonaccepted",
        "scope": {
            "source_path": SOURCE_PATH,
            "source_sha256": _sha(raw),
            "source_bytes": len(raw),
            "selector": "/ThML[1]",
            "division_count": len(profile.get("ordered_divisions", [])),
            "source_member_count": int(scope["member_count"]),
            "excluded_retained_members": [],
            "excluded_body_carriers": [],
        },
        "source_metadata": {
            **metadata,
            "source_edition": str(identity["edition"]),
            "original_publication_year": None,
            "source_quality": "proofed",
            "proofreading_against_page_images": "not-performed",
        },
        "date_evidence": {
            "status": "unresolved-conflict",
            "claims": date_claims,
            "config_original_publication_year": config.get("original_publication_year"),
            "config_year_disposition": "not-adopted-because-retained-witness-contains-conflicting-1728-and-1729-claims",
        },
        "retained_authorities": {
            "source_config": {"path": config_authority["path"], "sha256": config_authority["sha256"]},
            "metadata_sidecar": {"path": metadata_authority["path"], "sha256": metadata_authority["sha256"]},
            "source_profile": {"path": profile_authority["path"], "sha256": profile_authority["sha256"]},
            "data_attribution_notice": {"path": attribution_authority["path"], "sha256": attribution_authority["sha256"]},
        },
        "source_quality": {
            "provider_marker": "Proofed",
            "classification": "proofed-source-text-witness",
            "ocr_correction_performed": False,
            "page_image_collation_performed": False,
        },
        "non_element_events": [{key: event[key] for key in ("ordinal", "kind", "bytes", "sha256")} for event in events],
        "rights_observation": {
            "ccel_attribution_required": True,
            "ccel_no_sale_formatting_terms_observed": True,
            "attribution_notice_path": attribution_authority["path"],
            "rights_clearance": "not-decided",
        },
        "separation": {
            "human_acceptance": "not-decided",
            "rights_clearance": "not-decided",
            "canonical_promotion": "not-performed",
            "publication": "not-authorized",
        },
        "candidate_policy": {
            "converter_id": "ocd-law-serious-call-retained-thml-to-tei",
            "converter_version": "1",
            "external_doctype": "removed-before-parse-not-loaded",
            "named_entity_replacement": "none",
            "source_comments": "preserved",
            "notes_and_scripture_references": "preserved",
            "source_navigation_exceptions": "exactly-two-source-target-absent-assertions-preserved-in-header-notes-attached-to-existing-divisions",
        },
    }


def _expected_unresolved(profile: Mapping[str, Any], policy: Mapping[str, Any], root: ET.Element) -> bytes:
    unresolved = policy.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("independent reader has no unresolved issue inventory")
    claims = _date_claim_rows(profile, policy, root)
    body = root.find("ThML.body")
    if body is None:
        raise ValueError("independent reader cannot resolve source navigation without the complete body")
    _source_navigation_exceptions(root, body, _parent_map(root), profile, policy)
    output = []
    for item in unresolved:
        if not isinstance(item, Mapping):
            raise ValueError("independent reader found an invalid unresolved issue")
        record = dict(item)
        if record.get("id") == "original-publication-date-conflict":
            record["observed_claims"] = claims
            record.pop("claims", None)
        output.append(_canonical(record))
    return b"".join(output)


def _tei(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> ET.Element:
    node = ET.Element(f"{{{TEI_NS}}}{name}")
    for key, value in (attrs or {}).items():
        node.set(XML_ID if key == "xml:id" else key, str(value))
    node.text = text
    return node


def _source_pointer(path: str) -> str:
    from urllib.parse import quote

    return "urn:ocd:source-xpath:" + quote(path, safe="")


def _expected_header_capture(source: ET.Element, header_ordinals: Mapping[ET.Element, int], parents: Mapping[ET.Element, ET.Element]) -> ET.Element:
    def segment(node: ET.Element) -> ET.Element:
        ordinal = header_ordinals[node]
        xml_id = node.attrib.get("id") or f"{WORK_ID}-header-node-{ordinal:05d}"
        attributes = json.dumps(dict(sorted(node.attrib.items())), ensure_ascii=False, separators=(",", ":"))
        result = _tei("seg", {
            "xml:id": xml_id,
            "type": "source-element",
            "subtype": _tag(node),
            "n": attributes,
            "corresp": _source_pointer(_selector(node, parents)),
        }, node.text)
        for child in _element_children(node):
            converted = segment(child)
            converted.tail = child.tail
            result.append(converted)
        return result

    capture = _tei("note", {
        "type": "retained-thml-header",
        "xml:id": f"{WORK_ID}-source-header-capture",
        "corresp": _source_pointer(_selector(source, parents)),
    })
    capture.append(segment(source))
    return capture


def _expected_navigation_note(rows: list[dict[str, object]]) -> ET.Element:
    outer = _tei("note", {"type": "source-navigation-title-inventory"})
    listing = _tei("list", {"type": "source-navigation-titles"})
    for row in rows:
        attrs: dict[str, str] = {
            "xml:id": str(row["candidate_xml_id"]),
            "corresp": f"#{row['target_xml_id']}",
        }
        if row["source_n"]:
            attrs["n"] = str(row["source_n"])
        item = _tei("item", attrs, str(row["source_title"]))
        listing.append(item)
    outer.append(listing)
    return outer


def _expected_navigation_exception_note(record: Mapping[str, object]) -> ET.Element:
    note = _tei(
        "note",
        {
            "type": "unresolved-source-navigation-edge",
            "xml:id": f"{WORK_ID}-{record['id']}",
            "corresp": f"#{record['carrier_id']}",
        },
    )
    note.append(_tei("label", text="Source navigation assertion retained unresolved"))
    paragraph = _tei("p")
    paragraph.text = "Source SHA-256: "
    fields = (
        ("source_sha256", "source-sha256", "; source selector: "),
        ("selector", "source-selector", "; source direction @"),
        ("direction", "source-direction", "; raw target '"),
        ("raw_target", "source-raw-target", "'; carrier ID: "),
        ("carrier_id", "source-carrier-id", "; disposition: "),
        ("disposition", "source-disposition", "; owner: "),
        ("owner", "source-owner", "; reopen when: "),
        ("reopening_condition", "reopening-condition", "."),
    )
    for field, kind, tail in fields:
        segment = _tei("seg", {"type": kind}, str(record[field]))
        segment.tail = tail
        paragraph.append(segment)
    note.append(paragraph)
    return note


def _rendition_nodes(header: ET.Element) -> tuple[list[ET.Element], dict[tuple[str, str], list[str]]]:
    rows: list[ET.Element] = []
    refs: dict[tuple[str, str], list[str]] = {}
    style_ordinal = 0
    for style in _element_children(header):
        if _tag(style) != "style":
            continue
        style_ordinal += 1
        style_kind = style.attrib.get("type")
        if style_kind == "text/css":
            rows.append(_tei("rendition", {
                "xml:id": f"{WORK_ID}-rendition-{style_ordinal:03d}",
                "scheme": "css",
            }, style.text or ""))
        elif style_kind == "text/xcss":
            rule_ordinal = 0
            for selector in _element_children(style):
                if _tag(selector) != "selector":
                    raise ValueError("independent reader rejects an unknown style child")
                rule_ordinal += 1
                element_name = selector.attrib.get("element", "")
                class_name = selector.attrib.get("class", "")
                if not element_name and not class_name:
                    raise ValueError("independent reader rejects an empty style selector")
                selector_value = element_name + (f".{class_name}" if class_name else "")
                props = []
                for prop in _element_children(selector):
                    if _tag(prop) != "property" or "name" not in prop.attrib or "value" not in prop.attrib:
                        raise ValueError("independent reader rejects an incomplete style property")
                    props.append(f"{prop.attrib['name']}: {prop.attrib['value']};")
                rendition_id = f"{WORK_ID}-rendition-{style_ordinal:03d}-{rule_ordinal:02d}"
                rows.append(_tei("rendition", {
                    "xml:id": rendition_id,
                    "scheme": "css",
                    "selector": selector_value,
                }, " ".join(props)))
                if class_name:
                    if element_name:
                        refs.setdefault((element_name, class_name), []).append(rendition_id)
                    refs.setdefault(("", class_name), []).append(rendition_id)
        else:
            raise ValueError("independent reader found an unsupported stylesheet kind")
    return rows, refs


def _node_id(source: ET.Element, body_ordinals: Mapping[ET.Element, int]) -> str:
    source_id = source.attrib.get("id")
    return source_id or f"{WORK_ID}-body-node-{body_ordinals[source]:05d}"


def _heading_target_tag(source: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> str:
    parent = parents.get(source)
    if parent is None or _tag(parent) not in {"div1", "div2", "div", "added"}:
        return "ab"
    siblings = _element_children(parent)
    position = siblings.index(source)
    if all(_tag(sibling) in {"h1", "h2", "h3"} for sibling in siblings[:position]):
        return "head"
    return "ab"


def _tei_body_element(source: ET.Element, body_ordinals: Mapping[ET.Element, int], division_types: Mapping[str, Mapping[str, object]], navigation: Mapping[str, str], rendition_refs: Mapping[tuple[str, str], list[str]], retained_ids: set[str], parents: Mapping[ET.Element, ET.Element], navigation_exceptions: Mapping[tuple[str, str], Mapping[str, object]]) -> ET.Element:
    tag = _tag(source)
    heading_target = _heading_target_tag(source, parents) if tag in {"h1", "h2", "h3"} else None
    attributes: dict[str, str] = {"xml:id": _node_id(source, body_ordinals)}
    if tag == "div1":
        row = division_types.get(source.attrib.get("id", ""))
        if row is None:
            raise ValueError("independent reader found an unprofiled ThML division")
        attributes["type"] = str(row["tei_type"])
        if source.attrib.get("n"):
            attributes["n"] = source.attrib["n"]
        nav_id = navigation.get(_selector(source, parents))
        if nav_id:
            attributes["corresp"] = f"#{nav_id}"
    elif tag == "div2":
        attributes["type"] = "index-subdivision"
        if source.attrib.get("n"):
            attributes["n"] = source.attrib["n"]
        nav_id = navigation.get(_selector(source, parents))
        if nav_id:
            attributes["corresp"] = f"#{nav_id}"
    elif tag == "div":
        attributes["type"] = "index" if source.attrib.get("class", "").casefold() == "index" else "section"
        nav_id = navigation.get(_selector(source, parents))
        if nav_id:
            attributes["corresp"] = f"#{nav_id}"
    else:
        target_name = TEI_BODY_TAGS.get(tag)
        if target_name is None:
            raise ValueError(f"independent reader rejects unknown source body element {_tag(source)}")
        if tag in {"h1", "h2", "h3"}:
            if heading_target == "ab":
                attributes["type"] = "source-heading"
                attributes["subtype"] = tag
            else:
                attributes["type"] = f"ThML-{tag}"
        elif tag == "i":
            attributes["rend"] = "italic"
        elif tag == "a":
            target = source.attrib.get("href")
            if target is None:
                raise ValueError("independent reader rejects a source link without href")
            attributes["target"] = target
        elif tag == "scripRef":
            c_ref = source.attrib.get("osisRef")
            passage = source.attrib.get("passage")
            if not c_ref or not passage:
                raise ValueError("independent reader rejects an incomplete source scripture reference")
            attributes["type"] = "scripture"
            attributes["cRef"] = c_ref
            attributes["n"] = passage
        elif tag == "insertIndex":
            attributes["type"] = "index-marker"
            if source.attrib.get("type"):
                attributes["subtype"] = source.attrib["type"]
        elif tag == "added":
            attributes["type"] = "ThML-added"
            if source.attrib.get("date"):
                attributes["n"] = source.attrib["date"]
        elif tag == "note":
            if source.attrib.get("n"):
                attributes["n"] = source.attrib["n"]
            if source.attrib.get("place"):
                attributes["place"] = source.attrib["place"]
    source_class = source.attrib.get("class")
    if source_class:
        attributes["rend"] = source_class
        rendition_ids = []
        for class_name in source_class.split():
            rendition_ids.extend(rendition_refs.get((_tag(source), class_name), []))
            rendition_ids.extend(rendition_refs.get(("", class_name), []))
        if rendition_ids:
            attributes["rendition"] = " ".join(f"#{value}" for value in dict.fromkeys(rendition_ids))
    for edge in ("prev", "next"):
        target = source.attrib.get(edge)
        if target is not None:
            exception = navigation_exceptions.get((_selector(source, parents), edge))
            if exception is not None:
                if (
                    target != exception.get("raw_target")
                    or source.attrib.get("id") != exception.get("carrier_id")
                    or target in retained_ids
                ):
                    raise ValueError("independent reader found a changed declared source navigation exception")
                continue
            if target not in retained_ids:
                raise ValueError(
                    f"independent reader found source {edge} target {target!r} outside the complete retained-ID set at {_selector(source, parents)}"
                )
            attributes[edge] = f"#{target}"
    if tag in {"div1", "div2", "div"}:
        target_name = "div"
    elif tag in {"h1", "h2", "h3"}:
        target_name = heading_target
        if target_name is None:
            raise ValueError("independent reader did not resolve a source heading target")
    else:
        target_name = TEI_BODY_TAGS[tag]
    result = _tei(target_name, attributes, source.text)
    for child in _element_children(source):
        converted = _tei_body_element(child, body_ordinals, division_types, navigation, rendition_refs, retained_ids, parents, navigation_exceptions)
        converted.tail = child.tail
        result.append(converted)
    return result


def _expected_text(source_body: ET.Element, profile: Mapping[str, Any], nav_rows: list[dict[str, object]], parents: Mapping[ET.Element, ET.Element], navigation_exceptions: Mapping[tuple[str, str], Mapping[str, object]]) -> ET.Element:
    root = source_body
    while _tag(root) != "ThML":
        parent = parents.get(root)
        if parent is None:
            raise ValueError("independent reader cannot reach source root")
        root = parent
    body_nodes = _all_elements(source_body)
    body_ordinals = {node: ordinal for ordinal, node in enumerate(body_nodes, start=1)}
    divisions = [node for node in _element_children(source_body) if _tag(node) == "div1"]
    division_rows = profile["ordered_divisions"]
    division_types = {str(row["source_id"]): row for row in division_rows}
    nav_map = {str(row["selector"]): str(row["candidate_xml_id"]) for row in nav_rows}
    retained_ids = {node.attrib["id"] for node in _all_elements(root) if "id" in node.attrib}
    source_header = root.find("ThML.head")
    if source_header is None:
        raise ValueError("independent reader found no retained header")
    rendition_rows, rendition_refs = _rendition_nodes(source_header)
    text_node = _tei("text", {"xml:id": f"{WORK_ID}-text"})
    wrappers = {name: _tei(name) for name in ("front", "body", "back")}
    for name in ("front", "body", "back"):
        text_node.append(wrappers[name])
    for source_division, route_row in zip(divisions, division_rows, strict=True):
        mapped = _tei_body_element(source_division, body_ordinals, division_types, nav_map, rendition_refs, retained_ids, parents, navigation_exceptions)
        wrappers[str(route_row["region"])].append(mapped)
    return text_node


def _signature(node: Any) -> object:
    if not isinstance(node.tag, str):
        return ("#comment", node.text or "")
    tag = node.tag.split("}", 1)[-1]
    attributes = tuple(sorted((key, value) for key, value in node.attrib.items()))
    children = tuple((_signature(child), child.tail) for child in list(node))
    return (tag, attributes, node.text, children)


def _check_header_and_text(candidate_root: etree._Element, source_root: ET.Element, profile: Mapping[str, Any], policy: Mapping[str, Any], parents: Mapping[ET.Element, ET.Element]) -> None:
    source_body = source_root.find("ThML.body")
    source_header = source_root.find("ThML.head")
    if source_body is None or source_header is None:
        raise ValueError("independent candidate comparison requires whole ThML envelope")
    body_ordinals = {node: ordinal for ordinal, node in enumerate(_all_elements(source_body), start=1)}
    header_ordinals = {node: ordinal for ordinal, node in enumerate(_all_elements(source_header), start=1)}
    divisions = _division_records(source_root, source_body, profile, parents, body_ordinals)
    nav_rows = _navigation_records(source_body, parents, body_ordinals, divisions)
    navigation_exceptions = _source_navigation_exceptions(
        source_root,
        source_body,
        parents,
        profile,
        policy,
    )
    navigation_exception_map = {
        (str(row["selector"]), str(row["direction"])): row
        for row in navigation_exceptions
    }
    if candidate_root.get(XML_ID) != WORK_ID:
        raise ValueError("candidate TEI root does not identify law-serious-call")
    header = candidate_root.find(f"{{{TEI_NS}}}teiHeader")
    text_node = candidate_root.find(f"{{{TEI_NS}}}text")
    if header is None or text_node is None:
        raise ValueError("candidate TEI is missing its header or text")
    file_desc = header.find(f"{{{TEI_NS}}}fileDesc")
    if file_desc is None:
        raise ValueError("candidate TEI fileDesc is missing")
    title_stmt = file_desc.find(f"{{{TEI_NS}}}titleStmt")
    metadata = _source_metadata(source_root)
    title = title_stmt.find(f"{{{TEI_NS}}}title") if title_stmt is not None else None
    author = title_stmt.find(f"{{{TEI_NS}}}author") if title_stmt is not None else None
    if title is None or title.text != metadata["title"] or author is None or author.text != metadata["author"]:
        raise ValueError("candidate TEI title/author differ from retained header evidence")
    edition_stmt = file_desc.find(f"{{{TEI_NS}}}editionStmt")
    edition = edition_stmt.find(f"{{{TEI_NS}}}edition") if edition_stmt is not None else None
    identity = policy["provenance"]["identity"]
    if edition is None or edition.text != identity["edition"]:
        raise ValueError("candidate TEI edition claim differs from the policy's witness-level identity")
    notes_stmt = file_desc.find(f"{{{TEI_NS}}}notesStmt")
    if notes_stmt is None:
        raise ValueError("candidate TEI does not retain source metadata notes")
    notes = list(notes_stmt)
    expected_capture = _expected_header_capture(source_header, header_ordinals, parents)
    expected_nav = _expected_navigation_note(nav_rows)
    expected_exception_notes = [
        _expected_navigation_exception_note(row)
        for row in navigation_exceptions
    ]
    expected_notes = [expected_capture, expected_nav, *expected_exception_notes]
    if len(notes) != len(expected_notes) or [
        _signature(node) for node in notes
    ] != [_signature(node) for node in expected_notes]:
        raise ValueError("candidate TEI source-navigation exception notes are missing, changed, or attached to the wrong carrier")
    encoding_desc = header.find(f"{{{TEI_NS}}}encodingDesc")
    tags_decl = encoding_desc.find(f"{{{TEI_NS}}}tagsDecl") if encoding_desc is not None else None
    expected_renditions, _ = _rendition_nodes(source_header)
    if tags_decl is None or [_signature(node) for node in list(tags_decl)] != [_signature(node) for node in expected_renditions]:
        raise ValueError("candidate TEI style/rendition inventory differs from source")
    profile_desc = header.find(f"{{{TEI_NS}}}profileDesc")
    language = profile_desc.find(f"{{{TEI_NS}}}langUsage/{{{TEI_NS}}}language") if profile_desc is not None else None
    if language is None or language.get("ident") != metadata["language"]:
        raise ValueError("candidate TEI language identity differs from source")
    source_desc = file_desc.find(f"{{{TEI_NS}}}sourceDesc")
    source_ref = source_desc.find(f".//{{{TEI_NS}}}ref") if source_desc is not None else None
    if source_ref is None or source_ref.get("target") != "https://www.ccel.org/ccel/law/serious_call.xml":
        raise ValueError("candidate TEI source witness citation is missing")
    project_desc = encoding_desc.find(f"{{{TEI_NS}}}projectDesc/{{{TEI_NS}}}p") if encoding_desc is not None else None
    editorial_decl = encoding_desc.find(f"{{{TEI_NS}}}editorialDecl/{{{TEI_NS}}}p") if encoding_desc is not None else None
    if project_desc is None or project_desc.text != (
        "This candidate represents the complete retained ThML member. The source order, paragraphs, headings, notes, scripture references, links, addition, index marker, header metadata, and presentation metadata are accounted for. Exactly two source prev/next assertions to absent target toc remain unresolved in header notes attached to the title page and acknowledgements; no target ID was invented and no generated navigation title was substituted. The external ThML DOCTYPE is byte-accounted but was not loaded; no named-entity substitution or OCR correction was performed."
    ):
        raise ValueError("candidate TEI project description omits or changes the source navigation limitation")
    if editorial_decl is None or editorial_decl.text != (
        "CCEL labels this source text Proofed. No proofreading against page images was performed. Source language and readings are retained; the conflicting 1728 and 1729 claims and the two absent-target source navigation assertions remain unresolved in unresolved.jsonl."
    ):
        raise ValueError("candidate TEI editorial declaration omits or changes unresolved source issues")
    ids = [node.get(XML_ID) for node in candidate_root.iter() if node.get(XML_ID)]
    if len(ids) != len(set(ids)):
        raise ValueError("candidate TEI contains duplicate xml:id values")
    id_set = set(ids)
    if "toc" in id_set:
        raise ValueError("candidate TEI invents the absent source navigation target 'toc'")
    expected_text = _expected_text(
        source_body,
        profile,
        nav_rows,
        parents,
        navigation_exception_map,
    )
    if _signature(text_node) != _signature(expected_text):
        raise ValueError("independent oracle found a candidate body/text/topology/order/attachment mutation")
    for node in candidate_root.iter(f"{{{TEI_NS}}}ref"):
        target = node.get("target")
        if target and target.startswith("#") and target[1:] not in id_set:
            raise ValueError(f"candidate TEI has an unresolved local ref {target!r}")
    resolved_navigation_edges = [
        (node, direction, node.get(direction))
        for node in candidate_root.iter()
        for direction in ("prev", "next")
        if node.get(direction) is not None
    ]
    if len(resolved_navigation_edges) != 60:
        raise ValueError("candidate TEI must retain all 60 resolved source prev/next edges")
    for node, direction, target in resolved_navigation_edges:
        if not isinstance(target, str) or not target.startswith("#") or target[1:] not in id_set:
            raise ValueError(f"candidate TEI has an unresolved local {direction} edge {target!r}")
    source_notes = sum(_tag(node) == "note" for node in _all_elements(source_body))
    tei_notes = len(candidate_root.findall(f"./{{{TEI_NS}}}text//{{{TEI_NS}}}note"))
    source_refs = sum(_tag(node) == "scripRef" for node in _all_elements(source_body))
    scripture_refs = len(candidate_root.findall(f".//{{{TEI_NS}}}ref[@type='scripture']"))
    if (source_notes, source_refs) != (tei_notes, scripture_refs):
        raise ValueError("candidate TEI note or scripture-reference count changed")


def _validate_tei(candidate_bytes: bytes, source_events: list[dict[str, object]]) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, huge_tree=False)
    try:
        candidate_root = etree.fromstring(candidate_bytes, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is not well-formed") from exc
    document = candidate_root.getroottree()
    if document.docinfo.doctype:
        raise ValueError("candidate TEI copied a source DOCTYPE into the TEI document")
    source_comment = next((event["lexical"][4:-3] for event in source_events if event["kind"] == "comment"), None)
    previous = candidate_root.getprevious()
    if source_comment is None or not isinstance(previous, etree._Comment) or previous.text != source_comment:
        raise ValueError("candidate TEI did not preserve the source prolog comment")
    schema = compiled_schema()
    if not schema.validate(document):
        first = schema.error_log.last_error
        raise ValueError(f"TEI P5 XSD validation failed: {first}")
    return candidate_root


def _import_closure_digest(source_manifest: SourceManifest) -> str:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("validator import closure authorities are missing")
    files = []
    for authority in authorities:
        if isinstance(authority, Mapping) and authority.get("role") == "validator-dependency":
            files.append({
                "path": authority.get("path"),
                "bytes": authority.get("bytes"),
                "sha256": authority.get("sha256"),
            })
    files.sort(key=lambda row: str(row["path"]))
    if len(files) < 6:
        raise ValueError("validator import closure lacks its local module dependencies")
    external = {
        "jsonschema": importlib.metadata.version("jsonschema"),
        "lxml": importlib.metadata.version("lxml"),
    }
    return _sha(_canonical({
        "contract": "ocd-law-serious-call-validator-import-closure-v1",
        "files": files,
        "external_packages": external,
    }))


def validate(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    """Independently validate source carriers, candidate TEI, and evidence bytes."""

    source_manifest.verify()
    candidate.verify_integrity()
    if source_manifest.record.get("source_id") != SOURCE_ID or source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("independent oracle rejects the source-manifest identity")
    raw = _authority_bytes(source_manifest, "law-serious-call-retained-source")
    if _sha(raw) != "edc2bf6021f36bb7e42e1feb819c37492f920595e05ed31e22d52e7caa12c2bd" or len(raw) != 807207:
        raise ValueError("independent oracle rejects the retained source bytes")
    source_root, events = _parse_source(raw)
    profile, policy = _source_profile_and_policy(source_manifest)
    actual = candidate.member_bytes("source-accountability.json")
    accountability = _expected_accountability(source_manifest, raw, source_root, events, profile, policy)
    accountability_bytes = _canonical(accountability)
    if actual != accountability_bytes:
        raise ValueError("candidate source-accountability does not reconcile every source carrier")
    schema_bytes = _authority_bytes(source_manifest, "law-serious-call-accountability-schema")
    schema = _strict_object(schema_bytes, "source-accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"source-accountability schema validation failed: {errors[0].message}")
    expected_provenance = _expected_provenance(source_manifest, raw, source_root, events, profile, policy)
    if candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError("candidate provenance differs from retained source and policy evidence")
    if candidate.member_bytes("README.source.md") != _authority_bytes(source_manifest, "law-serious-call-source-readme"):
        raise ValueError("candidate source README differs from its exact bound authority")
    expected_unresolved = _expected_unresolved(profile, policy, source_root)
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("candidate unresolved register changed or omitted an evidence-undecidable issue")
    tei_bytes = candidate.member_bytes("content.tei.xml")
    candidate_root = _validate_tei(tei_bytes, events)
    _check_header_and_text(candidate_root, source_root, profile, policy, _parent_map(source_root))

    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("source manifest validator binding is invalid")
    dependencies = [
        (str(authority.get("path")), str(authority.get("sha256")))
        for authority in source_manifest.record["authorities"]
        if isinstance(authority, Mapping) and authority.get("role") == "validator-dependency"
    ]
    if not dependencies:
        raise ValueError("source manifest has no validator dependency authorities")
    closure_sha = _import_closure_digest(source_manifest)
    if closure_sha != validator.get("import_closure_sha256"):
        raise ValueError("validator import closure digest differs from exact local dependencies")
    package_schema = source_manifest.record.get("package_schema")
    authorities = source_manifest.record.get("authorities")
    if not isinstance(package_schema, Mapping) or not isinstance(authorities, tuple):
        raise ValueError("candidate package schema binding is missing")
    role_records = {
        str(item.get("role")): item
        for item in authorities
        if isinstance(item, Mapping) and isinstance(item.get("role"), str)
    }
    for role in (
        "complete-source-feature-profile",
        "candidate-package-schema",
        "tei-validation-schema",
        "independent-validation-policy",
    ):
        if role not in role_records:
            raise ValueError(f"independent reader requires exactly one {role} authority")
        duplicates = sum(isinstance(item, Mapping) and item.get("role") == role for item in authorities)
        if duplicates != 1:
            raise ValueError(f"independent reader found duplicate {role} authorities")
    facts = MechanicalFacts(
        validator_implementation_sha256=str(validator.get("implementation_sha256")),
        validator_import_closure_sha256=closure_sha,
        source_sha256=_sha(raw),
        profile_sha256=str(role_records["complete-source-feature-profile"].get("sha256")),
        package_schema_sha256=str(package_schema.get("sha256")),
        xsd_sha256=str(role_records["tei-validation-schema"].get("sha256")),
        policy_sha256=str(role_records["independent-validation-policy"].get("sha256")),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


validate.oracle_id = ORACLE_ID  # type: ignore[attr-defined]
validate.oracle_version = ORACLE_VERSION  # type: ignore[attr-defined]
