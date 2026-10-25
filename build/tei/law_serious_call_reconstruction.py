"""Source-bound reconstruction of the retained Law / Serious Call ThML witness."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import quote

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-law-serious-call-retained-thml-to-tei"
CONVERTER_VERSION = "1"
WORK_ID = "law-serious-call"
SOURCE_ID = "law-serious-call-retained-thml"
SOURCE_PATH = "raw/ccel/law/serious_call.xml"
SOURCE_SHA256 = "edc2bf6021f36bb7e42e1feb819c37492f920595e05ed31e22d52e7caa12c2bd"
PROFILE_NAME = "law-serious-call-source-profile"
POLICY_NAME = "law-serious-call-independent-validation-policy"
ACCOUNTABILITY_SCHEMA_NAME = "law-serious-call-accountability-schema"
README_NAME = "law-serious-call-source-readme"
CONFIG_NAME = "law-serious-call-source-config"
METADATA_NAME = "law-serious-call-metadata-sidecar"
ATTRIBUTION_NAME = "law-serious-call-data-attribution"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
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
DOCTYPE_RE = re.compile(rb"<!DOCTYPE\s[^\[>]*(?:\[[^]]*\])?>", re.IGNORECASE | re.DOTALL)
ENTITY_RE = re.compile(rb"&([A-Za-z][A-Za-z0-9]*);")
ENTITY_WHITELIST = {b"amp", b"lt", b"gt", b"quot", b"apos"}
NON_ELEMENT_RE = re.compile(
    r"(?P<doctype><!DOCTYPE\s[^\[>]*(?:\[[^]]*\])?>)"
    r"|(?P<comment><!--[\s\S]*?-->)"
    r"|(?P<pi><\?(?!xml(?:\s|\?>))[\s\S]*?\?>)",
    re.IGNORECASE,
)
DATE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:MDCCXXIX|1728|1729)(?![A-Za-z0-9])", re.I)
BODY_TAG_MAP = {
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


def _heading_target_name(source: etree._Element) -> str:
    """Use TEI head only for headings at the start of a division."""

    parent = source.getparent()
    if parent is None or _local(parent) not in {"div1", "div2", "div", "added"}:
        return "ab"
    preceding = []
    for sibling in parent:
        if sibling is source:
            break
        if isinstance(sibling.tag, str):
            preceding.append(sibling)
    if all(_local(sibling) in {"h1", "h2", "h3"} for sibling in preceding):
        return "head"
    return "ab"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_object(content: bytes, label: str) -> dict[str, Any]:
    def build(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} repeats JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=build)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _local(node: etree._Element) -> str:
    return etree.QName(node).localname


def _selector(node: etree._Element) -> str:
    fragments: list[str] = []
    current: etree._Element | None = node
    while current is not None:
        parent = current.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str) and child.tag == current.tag]
            if parent is not None
            else [current]
        )
        fragments.append(f"{_local(current)}[{siblings.index(current) + 1}]")
        current = parent
    return "/" + "/".join(reversed(fragments))


def _parse_source(raw: bytes) -> tuple[etree._Element, list[dict[str, object]]]:
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("retained CCEL ThML source is not UTF-8") from exc
    events = [
        {
            "ordinal": ordinal,
            "kind": str(match.lastgroup),
            "bytes": len(match.group(0).encode("utf-8")),
            "sha256": _sha(match.group(0).encode("utf-8")),
            "lexical": match.group(0),
        }
        for ordinal, match in enumerate(NON_ELEMENT_RE.finditer(decoded), start=1)
    ]
    doctype_count = sum(item["kind"] == "doctype" for item in events)
    if doctype_count != 1:
        raise ValueError("retained CCEL ThML must have one byte-accounted external DOCTYPE")
    without_doctype, substitutions = DOCTYPE_RE.subn(b"", raw, count=1)
    if substitutions != 1:
        raise ValueError("retained CCEL ThML DOCTYPE could not be isolated safely")
    unknown = sorted(set(ENTITY_RE.findall(without_doctype)) - ENTITY_WHITELIST)
    if unknown:
        raise ValueError(f"unsupported named entity in retained CCEL ThML: {unknown[0]!r}")
    parser = etree.XMLParser(
        load_dtd=False,
        resolve_entities=False,
        no_network=True,
        remove_comments=False,
        strip_cdata=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(without_doctype, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained CCEL ThML is not well formed after safe DOCTYPE isolation") from exc
    if root.tag != "ThML" or root.nsmap.get(None):
        raise ValueError("retained source root must be the unnamespaced ThML document")
    return root, events


def _body_xml_id(node: etree._Element, body_ordinal: int) -> str:
    source_id = node.get("id")
    if source_id:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9._-]*", source_id) is None:
            raise ValueError(f"unsafe source xml:id {source_id!r}")
        return source_id
    return f"{WORK_ID}-body-node-{body_ordinal:05d}"


def _header_xml_id(header_ordinal: int, node: etree._Element | None = None) -> str:
    source_id = node.get("id") if node is not None else None
    if source_id:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9._-]*", source_id) is None:
            raise ValueError(f"unsafe source header xml:id {source_id!r}")
        return source_id
    return f"{WORK_ID}-header-node-{header_ordinal:05d}"


def _element_xml_id(
    node: etree._Element,
    *,
    root: etree._Element,
    body: etree._Element,
    body_ordinals: Mapping[etree._Element, int],
    header_ordinals: Mapping[etree._Element, int],
) -> str:
    if node is root:
        return WORK_ID
    if node is body:
        return f"{WORK_ID}-text"
    if node in body_ordinals:
        return _body_xml_id(node, body_ordinals[node])
    if node in header_ordinals:
        return _header_xml_id(header_ordinals[node], node)
    raise ValueError("source element is outside the complete ThML envelope")


def _sha_text(value: str | None) -> str:
    return _sha((value or "").encode("utf-8"))


def _source_features(
    root: etree._Element,
    body: etree._Element,
) -> tuple[list[dict[str, object]], dict[etree._Element, int], dict[etree._Element, int]]:
    all_nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    body_nodes = [node for node in body.iter() if isinstance(node.tag, str)]
    header = root.find("ThML.head")
    if header is None:
        raise ValueError("retained source has no ThML.head")
    header_nodes = [node for node in header.iter() if isinstance(node.tag, str)]
    body_ordinals = {node: ordinal for ordinal, node in enumerate(body_nodes, start=1)}
    header_ordinals = {node: ordinal for ordinal, node in enumerate(header_nodes, start=1)}
    all_ordinals = {node: ordinal for ordinal, node in enumerate(all_nodes, start=1)}
    body_set = set(body_nodes)
    header_set = set(header_nodes)
    rows: list[dict[str, object]] = []
    for ordinal, node in enumerate(all_nodes, start=1):
        parent = node.getparent()
        siblings = (
            [child for child in parent if isinstance(child.tag, str)]
            if parent is not None
            else [node]
        )
        target_id = _element_xml_id(
            node,
            root=root,
            body=body,
            body_ordinals=body_ordinals,
            header_ordinals=header_ordinals,
        )
        if node is root:
            disposition = "represented-by-tei-root"
        elif node is body:
            disposition = "represented-by-tei-text"
        elif node in body_set:
            disposition = "represented-in-tei-body"
        elif node in header_set:
            disposition = "represented-in-tei-header"
        else:
            raise ValueError(f"unaccounted source element {_selector(node)}")
        rows.append(
            {
                "ordinal": ordinal,
                "selector": _selector(node),
                "qname": str(node.tag),
                "attributes": [
                    {"qname": key, "value": value}
                    for key, value in sorted(node.attrib.items())
                ],
                "parent_ordinal": all_ordinals[parent] if parent is not None else None,
                "child_ordinal": siblings.index(node) + 1,
                "text_characters": len(node.text or ""),
                "text_sha256": _sha_text(node.text),
                "tail_characters": len(node.tail or ""),
                "tail_sha256": _sha_text(node.tail),
                "disposition": disposition,
                "target_xml_id": target_id,
            }
        )
    target_ids = [str(item["target_xml_id"]) for item in rows]
    if len(target_ids) != len(set(target_ids)):
        raise ValueError("source-to-TEI target xml:id mapping is not unique")
    return rows, body_ordinals, header_ordinals


def _census(root: etree._Element, body: etree._Element) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    all_nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    body_nodes = [node for node in body.iter() if isinstance(node.tag, str)]
    all_counts = Counter(_local(node) for node in all_nodes)
    body_counts = Counter(_local(node) for node in body_nodes)
    attribute_counts = Counter(key for node in all_nodes for key in node.attrib)
    ids = [node.get("id") for node in all_nodes if node.get("id")]
    if len(ids) != len(set(ids)):
        raise ValueError("retained source contains duplicate ids")
    hrefs = [node.get("href") for node in body_nodes if _local(node) == "a" and node.get("href")]
    return dict(sorted(all_counts.items())), dict(sorted(body_counts.items())), {
        "elements": len(all_nodes),
        "body_elements": len(body_nodes),
        "attributes": sum(len(node.attrib) for node in all_nodes),
        "ids": len(ids),
        "notes": sum(_local(node) == "note" for node in body_nodes),
        "scripture_references": sum(_local(node) == "scripRef" for node in body_nodes),
        "links": len(hrefs),
        "characters": sum(len(node.text or "") + len(node.tail or "") for node in all_nodes),
        "internal_links": sum(str(value).startswith("#") for value in hrefs),
        "external_links": sum(not str(value).startswith("#") for value in hrefs),
    }


def _navigation_exception_records(
    root: etree._Element,
    body: etree._Element,
    profile: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> list[dict[str, object]]:
    source_ids = {
        node.get("id")
        for node in root.iter()
        if isinstance(node.tag, str) and node.get("id")
    }
    if "toc" in source_ids:
        raise ValueError("retained source unexpectedly defines the declared absent navigation target 'toc'")

    total_edges = 0
    resolved_edges = 0
    missing_edges: list[dict[str, str | None]] = []
    for node in body.iter():
        if not isinstance(node.tag, str):
            continue
        for direction in ("prev", "next"):
            raw_target = node.get(direction)
            if raw_target is None:
                continue
            total_edges += 1
            if raw_target in source_ids:
                resolved_edges += 1
                continue
            missing_edges.append(
                {
                    "selector": _selector(node),
                    "direction": direction,
                    "raw_target": raw_target,
                    "carrier_id": node.get("id"),
                }
            )

    expected_missing = [
        {
            "selector": row["selector"],
            "direction": row["direction"],
            "raw_target": row["raw_target"],
            "carrier_id": row["carrier_id"],
        }
        for row in NAVIGATION_EXCEPTION_ROWS
    ]
    if (total_edges, resolved_edges, missing_edges) != (62, 60, expected_missing):
        raise ValueError("retained source navigation inventory differs from the two exact absent-target assertions")

    source_navigation = profile.get("source_navigation")
    if not isinstance(source_navigation, Mapping) or set(source_navigation) != {
        "edge_count",
        "resolved_edge_count",
        "unresolved_edges",
    }:
        raise ValueError("source profile navigation accounting is incomplete or has unexpected fields")
    if (
        source_navigation.get("edge_count") != total_edges
        or source_navigation.get("resolved_edge_count") != resolved_edges
        or source_navigation.get("unresolved_edges") != list(NAVIGATION_EXCEPTION_ROWS)
    ):
        raise ValueError("source profile navigation accounting differs from the retained source")

    if policy.get("source_navigation") != SOURCE_NAVIGATION_POLICY:
        raise ValueError("validation policy does not permit only the two declared source navigation exceptions")
    unresolved = policy.get("unresolved")
    if not isinstance(unresolved, list):
        raise ValueError("validation policy unresolved inventory is missing")
    policy_edges = [
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
    if policy_edges != expected_policy_edges or navigation_prefixed != expected_policy_edges:
        raise ValueError("validation policy unresolved navigation inventory differs from the exact source assertions")
    return [dict(row) for row in NAVIGATION_EXCEPTION_ROWS]


def _profile_and_policy(
    source_manifest: SourceManifest,
    root: etree._Element,
    raw: bytes,
    events: list[dict[str, object]],
    body: etree._Element,
    features: list[dict[str, object]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str], list[dict[str, object]]]:
    profile = _strict_object(_authority_bytes(source_manifest, PROFILE_NAME), "source profile")
    policy = _strict_object(_authority_bytes(source_manifest, POLICY_NAME), "validation policy")
    if profile.get("contract") != "ocd-law-serious-call-source-profile-v1":
        raise ValueError("source profile contract mismatch")
    if profile.get("profile_id") != "law-serious-call-whole-retained-thml-v1":
        raise ValueError("source profile identity mismatch")
    if profile.get("work_id") != WORK_ID or profile.get("source_id") != SOURCE_ID:
        raise ValueError("source profile work/source identity mismatch")
    if policy.get("contract") != "ocd-law-serious-call-independent-validation-policy-v1":
        raise ValueError("validation policy contract mismatch")
    if policy.get("work_id") != WORK_ID or policy.get("source_id") != SOURCE_ID:
        raise ValueError("validation policy work/source identity mismatch")
    source_scope = profile.get("source_scope")
    if not isinstance(source_scope, Mapping) or (
        source_scope.get("member_count") != 1
        or source_scope.get("member_path") != SOURCE_PATH
        or source_scope.get("member_bytes") != len(raw)
        or source_scope.get("member_sha256") != _sha(raw)
        or source_scope.get("selector") != "/ThML[1]"
        or source_scope.get("body_selector") != "/ThML[1]/ThML.body[1]"
        or source_scope.get("disposition") != "complete-whole-retained-member"
    ):
        raise ValueError("source profile does not bind the complete retained member")
    if _sha(raw) != SOURCE_SHA256:
        raise ValueError("retained source bytes differ from the pinned source")
    all_counts, body_counts, census = _census(root, body)
    expected_carriers = profile.get("source_carriers")
    if not isinstance(expected_carriers, Mapping) or (
        census["elements"] != expected_carriers.get("element_count")
        or census["body_elements"] != expected_carriers.get("body_element_count")
        or census["attributes"] != expected_carriers.get("attribute_count")
        or census["ids"] != expected_carriers.get("unique_id_attribute_count")
        or census["notes"] != expected_carriers.get("note_count")
        or census["scripture_references"] != expected_carriers.get("scripture_reference_count")
        or census["links"] != expected_carriers.get("anchor_count")
        or census["internal_links"] != expected_carriers.get("local_link_count")
        or census["external_links"] != expected_carriers.get("external_link_count")
        or all_counts != expected_carriers.get("element_counts")
        or body_counts != expected_carriers.get("body_element_counts")
    ):
        raise ValueError("retained source census differs from its pinned profile")
    all_nodes = [node for node in root.iter() if isinstance(node.tag, str)]
    attribute_counts = dict(sorted(Counter(key for node in all_nodes for key in node.attrib).items()))
    id_values = [node.get("id") for node in all_nodes if node.get("id")]
    id_digest = _sha("\n".join(id_values).encode("utf-8"))
    if (
        attribute_counts != expected_carriers.get("attribute_name_counts")
        or id_digest != expected_carriers.get("id_values_sha256")
    ):
        raise ValueError("retained source attribute or ordered ID census differs from profile")
    profile_events = profile.get("non_element_events")
    if not isinstance(profile_events, Mapping):
        raise ValueError("source profile has no non-element event census")
    compact_events = [
        {key: event[key] for key in ("ordinal", "kind", "bytes", "sha256")}
        for event in events
    ]
    if compact_events != profile_events.get("events"):
        raise ValueError("retained source non-element events differ from its pinned profile")
    if policy.get("scope") != {
        "source_path": SOURCE_PATH,
        "source_sha256": SOURCE_SHA256,
        "source_bytes": len(raw),
        "selector": "/ThML[1]",
        "member_count": 1,
        "disposition": "complete-whole-retained-member",
    }:
        raise ValueError("validation policy source scope is stale")
    navigation_exceptions = _navigation_exception_records(root, body, profile, policy)
    metadata = profile.get("observed_source_metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("source profile has no retained metadata record")
    observed = {
        "title": root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Title)"),
        "author": root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Creator[@scheme='short-form'])"),
        "language": root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Language)"),
        "provider": root.xpath("string(./ThML.head/electronicEdInfo/DC/DC.Publisher)"),
    }
    if observed != dict(metadata):
        raise ValueError("source-profile header metadata differs from current retained source")
    division_profile = profile.get("ordered_divisions")
    actual_divisions = [node for node in body if isinstance(node.tag, str) and _local(node) == "div1"]
    if not isinstance(division_profile, list) or len(actual_divisions) != 30:
        raise ValueError("source profile division envelope is incomplete")
    body_ordinals = {
        node: ordinal
        for ordinal, node in enumerate(
            (node for node in body.iter() if isinstance(node.tag, str)),
            start=1,
        )
    }
    actual_sequence = [
        {
            "ordinal": ordinal,
            "source_id": node.get("id"),
            "source_n": node.get("n"),
            "source_title": node.get("title"),
            "region": row.get("region"),
            "tei_type": row.get("tei_type"),
            "selector": _selector(node),
            "target_xml_id": _body_xml_id(node, body_ordinals[node]),
        }
        for ordinal, (node, row) in enumerate(zip(actual_divisions, division_profile, strict=True), start=1)
    ]
    if actual_sequence != division_profile:
        raise ValueError("source profile does not match the exact ordered division sequence")
    if any(_local(node) not in (set(BODY_TAG_MAP) | {"div", "div1", "div2"}) for node in body.iter() if isinstance(node.tag, str) and node is not body):
        raise ValueError("retained body contains an unsupported ThML element")
    quality = profile.get("source_quality")
    if not isinstance(quality, Mapping) or (
        quality.get("classification") != "proofed"
        or quality.get("marker") != "Proofed"
        or quality.get("new_page_image_proofreading_performed") is not False
    ):
        raise ValueError("source quality claim is not bound to the retained Proofed marker")
    return profile, policy, {key: str(value) for key, value in observed.items()}, navigation_exceptions


def _tei_element(name: str, attributes: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    if name == "TEI":
        node = etree.Element(f"{{{TEI_NS}}}{name}", nsmap={None: TEI_NS})
    else:
        node = etree.Element(f"{{{TEI_NS}}}{name}")
    for key, value in (attributes or {}).items():
        node.set(f"{{{XML_NS}}}id" if key == "xml:id" else key, str(value))
    node.text = text
    return node


def _append(parent: etree._Element, name: str, attributes: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    child = _tei_element(name, attributes, text)
    parent.append(child)
    return child


def _source_pointer(path: str) -> str:
    return "urn:ocd:source-xpath:" + quote(path, safe="")


def _header_segment(
    source: etree._Element,
    *,
    header_ordinals: Mapping[etree._Element, int],
) -> etree._Element:
    tag = _local(source)
    element = _tei_element(
        "seg",
        {
            "xml:id": _header_xml_id(header_ordinals[source], source),
            "type": "source-element",
            "subtype": tag,
            "n": json.dumps(dict(sorted(source.attrib.items())), ensure_ascii=False, separators=(",", ":")),
            "corresp": _source_pointer(_selector(source)),
        },
        source.text,
    )
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("source header contains an unsupported non-element child")
        converted = _header_segment(child, header_ordinals=header_ordinals)
        converted.tail = child.tail
        element.append(converted)
    return element


def _navigation_title_rows(
    profile: Mapping[str, Any],
    source_body: etree._Element,
    body_ordinals: Mapping[etree._Element, int],
) -> list[dict[str, str | None]]:
    expected = profile.get("navigation_titles")
    if not isinstance(expected, list):
        raise ValueError("source profile has no complete navigation-title inventory")
    actual_nodes = [
        node
        for node in source_body.iter()
        if isinstance(node.tag, str) and _local(node) in {"div1", "div2", "div"} and node.get("title") is not None
    ]
    if len(actual_nodes) != len(expected):
        raise ValueError("source navigation-title inventory size changed")
    rows: list[dict[str, str | None]] = []
    for ordinal, (node, expected_row) in enumerate(zip(actual_nodes, expected, strict=True), start=1):
        row: dict[str, str | None] = {
            "ordinal": str(ordinal),
            "source_selector": _selector(node),
            "source_qname": _local(node),
            "source_id": node.get("id"),
            "source_n": node.get("n"),
            "source_title": node.get("title"),
            "target_xml_id": _body_xml_id(node, body_ordinals[node]),
            "candidate_xml_id": str(expected_row.get("candidate_xml_id")),
        }
        comparable = {key: value for key, value in row.items() if key != "ordinal"}
        expected_comparable = {
            "source_selector": expected_row.get("source_selector"),
            "source_qname": expected_row.get("source_qname"),
            "source_id": expected_row.get("source_id"),
            "source_n": expected_row.get("source_n"),
            "source_title": expected_row.get("source_title"),
            "target_xml_id": expected_row.get("target_xml_id"),
            "candidate_xml_id": expected_row.get("candidate_xml_id"),
        }
        if comparable != expected_comparable:
            raise ValueError("source navigation-title mapping differs from its profile")
        rows.append(row)
    return rows


def _renditions(source_header: etree._Element) -> tuple[etree._Element, dict[tuple[str, str], list[str]]]:
    tags_decl = _tei_element("tagsDecl")
    references: dict[tuple[str, str], list[str]] = {}
    style_ordinal = 0
    for style in source_header:
        if not isinstance(style.tag, str) or _local(style) != "style":
            continue
        style_ordinal += 1
        style_type = style.get("type") or "unknown"
        if style_type == "text/css":
            _append(
                tags_decl,
                "rendition",
                {"xml:id": f"{WORK_ID}-rendition-{style_ordinal:03d}", "scheme": "css"},
                style.text or "",
            )
            continue
        if style_type != "text/xcss":
            raise ValueError(f"unsupported ThML style type {style_type!r}")
        rule_ordinal = 0
        for selector_node in style:
            if not isinstance(selector_node.tag, str) or _local(selector_node) != "selector":
                raise ValueError("ThML stylesheet contains an unsupported rule carrier")
            rule_ordinal += 1
            element_name = selector_node.get("element") or ""
            class_name = selector_node.get("class") or ""
            if not class_name and not element_name:
                raise ValueError("ThML selector has neither an element nor a class")
            selector = (element_name if element_name else "") + (f".{class_name}" if class_name else "")
            declarations: list[str] = []
            for property_node in selector_node:
                if not isinstance(property_node.tag, str) or _local(property_node) != "property":
                    raise ValueError("ThML style rule contains an unsupported property carrier")
                property_name = property_node.get("name")
                property_value = property_node.get("value")
                if property_name is None or property_value is None:
                    raise ValueError("ThML style property is incomplete")
                declarations.append(f"{property_name}: {property_value};")
            rendition_id = f"{WORK_ID}-rendition-{style_ordinal:03d}-{rule_ordinal:02d}"
            _append(
                tags_decl,
                "rendition",
                {"xml:id": rendition_id, "scheme": "css", "selector": selector},
                " ".join(declarations),
            )
            if class_name:
                if element_name:
                    references.setdefault((element_name, class_name), []).append(rendition_id)
                references.setdefault(("", class_name), []).append(rendition_id)
    return tags_decl, references


def _copy_common_attributes(
    source: etree._Element,
    attrs: dict[str, str],
    *,
    rendition_refs: Mapping[tuple[str, str], list[str]],
) -> None:
    source_class = source.get("class")
    if source_class:
        attrs["rend"] = source_class
        refs: list[str] = []
        for class_name in source_class.split():
            refs.extend(rendition_refs.get((_local(source), class_name), []))
            refs.extend(rendition_refs.get(("", class_name), []))
        if refs:
            attrs["rendition"] = " ".join(f"#{item}" for item in dict.fromkeys(refs))


def _body_node(
    source: etree._Element,
    *,
    body_ordinals: Mapping[etree._Element, int],
    division_by_id: Mapping[str, Mapping[str, Any]],
    navigation_by_selector: Mapping[str, str],
    rendition_refs: Mapping[tuple[str, str], list[str]],
    retained_ids: set[str],
    navigation_exceptions: Mapping[tuple[str, str], Mapping[str, object]],
) -> etree._Element:
    tag = _local(source)
    source_id = source.get("id")
    heading_target = _heading_target_name(source) if tag in {"h1", "h2", "h3"} else None
    attrs: dict[str, str] = {"xml:id": _body_xml_id(source, body_ordinals[source])}
    if tag == "div1":
        row = division_by_id.get(source_id or "")
        if row is None:
            raise ValueError("source div1 is not in the ordered whole-work profile")
        attrs["type"] = str(row["tei_type"])
        if source.get("n"):
            attrs["n"] = source.get("n", "")
        title_ref = navigation_by_selector.get(_selector(source))
        if title_ref:
            attrs["corresp"] = f"#{title_ref}"
    elif tag == "div2":
        attrs["type"] = "index-subdivision"
        if source.get("n"):
            attrs["n"] = source.get("n", "")
        title_ref = navigation_by_selector.get(_selector(source))
        if title_ref:
            attrs["corresp"] = f"#{title_ref}"
    elif tag == "div":
        attrs["type"] = "index" if (source.get("class") or "").casefold() == "index" else "section"
        title_ref = navigation_by_selector.get(_selector(source))
        if title_ref:
            attrs["corresp"] = f"#{title_ref}"
    elif tag in BODY_TAG_MAP:
        if tag in {"h1", "h2", "h3"}:
            if heading_target == "ab":
                # Preserve the source role for CVW while keeping this interior
                # heading in its exact source order with a schema-valid carrier.
                attrs["type"] = "source-heading"
                attrs["subtype"] = tag
            else:
                attrs["type"] = f"ThML-{tag}"
        elif tag == "i":
            attrs["rend"] = "italic"
        elif tag == "a":
            href = source.get("href")
            if not href:
                raise ValueError(f"source link has no href at {_selector(source)}")
            attrs["target"] = href
        elif tag == "scripRef":
            osis_ref = source.get("osisRef")
            passage = source.get("passage")
            if not osis_ref or not passage:
                raise ValueError(f"incomplete source scripture reference at {_selector(source)}")
            attrs["type"] = "scripture"
            attrs["cRef"] = osis_ref
            attrs["n"] = passage
        elif tag == "insertIndex":
            attrs["type"] = "index-marker"
            if source.get("type"):
                attrs["subtype"] = source.get("type", "")
        elif tag == "added":
            attrs["type"] = "ThML-added"
            if source.get("date"):
                # ThML added wrappers may contain block children; preserve their date on the TEI division.
                attrs["n"] = source.get("date", "")
        elif tag == "note":
            if source.get("n"):
                attrs["n"] = source.get("n", "")
            if source.get("place"):
                attrs["place"] = source.get("place", "")
    else:
        raise ValueError(f"unsupported ThML body element <{tag}> at {_selector(source)}")

    _copy_common_attributes(source, attrs, rendition_refs=rendition_refs)
    for link_attribute in ("prev", "next"):
        target = source.get(link_attribute)
        if target is not None:
            exception = navigation_exceptions.get((_selector(source), link_attribute))
            if exception is not None:
                if (
                    target != exception.get("raw_target")
                    or source.get("id") != exception.get("carrier_id")
                    or target in retained_ids
                ):
                    raise ValueError(f"declared source navigation exception changed at {_selector(source)}")
                continue
            if target not in retained_ids:
                raise ValueError(
                    f"source {link_attribute} target {target!r} is outside the complete retained-ID set at {_selector(source)}"
                )
            attrs[link_attribute] = f"#{target}"

    if tag in {"div1", "div2", "div"}:
        target_name = "div"
    elif tag in {"h1", "h2", "h3"}:
        target_name = heading_target
        if target_name is None:
            raise ValueError(f"source heading target was not resolved at {_selector(source)}")
    else:
        target_name = BODY_TAG_MAP[tag]
    result = _tei_element(target_name, attrs, source.text)
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError(f"unexpected comment or processing instruction inside body at {_selector(source)}")
        converted = _body_node(
            child,
            body_ordinals=body_ordinals,
            division_by_id=division_by_id,
            navigation_by_selector=navigation_by_selector,
            rendition_refs=rendition_refs,
            retained_ids=retained_ids,
            navigation_exceptions=navigation_exceptions,
        )
        converted.tail = child.tail
        result.append(converted)
    return result


def _date_claims(profile: Mapping[str, Any], policy: Mapping[str, Any]) -> list[dict[str, object]]:
    profile_claims = profile.get("date_claims")
    unresolved = policy.get("unresolved")
    if not isinstance(profile_claims, list) or not isinstance(unresolved, list):
        raise ValueError("date-conflict evidence is incomplete")
    date_policy = next((item for item in unresolved if isinstance(item, Mapping) and item.get("id") == "original-publication-date-conflict"), None)
    if not isinstance(date_policy, Mapping) or not isinstance(date_policy.get("claims"), list):
        raise ValueError("validation policy date disagreement record is absent")
    by_locator = {str(item.get("source_locator")): item for item in date_policy["claims"] if isinstance(item, Mapping)}
    rows: list[dict[str, object]] = []
    for profile_claim in profile_claims:
        if not isinstance(profile_claim, Mapping):
            raise ValueError("source profile contains an invalid date claim")
        locator = str(profile_claim.get("source_locator"))
        policy_claim = by_locator.get(locator)
        if policy_claim is None:
            raise ValueError("validation policy does not contain every source date locator")
        rows.append(
            {
                "value": policy_claim.get("value"),
                "source_locator": locator,
                "source_tokens": list(profile_claim.get("tokens", [])),
                "role": profile_claim.get("role"),
            }
        )
    if len(rows) != len(by_locator):
        raise ValueError("validation policy contains date claims outside the pinned profile")
    return rows


def _unresolved_bytes(profile: Mapping[str, Any], policy: Mapping[str, Any]) -> bytes:
    policy_items = policy.get("unresolved")
    if not isinstance(policy_items, list):
        raise ValueError("validation policy unresolved inventory is missing")
    date_claims = _date_claims(profile, policy)
    records: list[dict[str, object]] = []
    for item in policy_items:
        if not isinstance(item, Mapping):
            raise ValueError("validation policy unresolved item is invalid")
        record = dict(item)
        if record.get("id") == "original-publication-date-conflict":
            record["observed_claims"] = date_claims
            record.pop("claims", None)
        records.append(record)
    return b"".join(_canonical(record) for record in records)


def _append_navigation_exception_note(
    notes_stmt: etree._Element,
    record: Mapping[str, object],
) -> None:
    note = _append(
        notes_stmt,
        "note",
        {
            "type": "unresolved-source-navigation-edge",
            "xml:id": f"{WORK_ID}-{record['id']}",
            "corresp": f"#{record['carrier_id']}",
        },
    )
    _append(note, "label", text="Source navigation assertion retained unresolved")
    paragraph = _append(note, "p")
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
        segment = _append(paragraph, "seg", {"type": kind}, str(record[field]))
        segment.tail = tail


def _provenance(
    source_manifest: SourceManifest,
    profile: Mapping[str, Any],
    policy: Mapping[str, Any],
    metadata: Mapping[str, str],
    source_bytes: bytes,
    events: list[dict[str, object]],
) -> dict[str, object]:
    config = _strict_object(_authority_bytes(source_manifest, CONFIG_NAME), "source config")
    config_authority = next(
        authority for authority in source_manifest.record["authorities"]
        if isinstance(authority, Mapping) and authority.get("name") == CONFIG_NAME
    )
    metadata_authority = next(
        authority for authority in source_manifest.record["authorities"]
        if isinstance(authority, Mapping) and authority.get("name") == METADATA_NAME
    )
    attribution_authority = next(
        authority for authority in source_manifest.record["authorities"]
        if isinstance(authority, Mapping) and authority.get("name") == ATTRIBUTION_NAME
    )
    profile_authority = next(
        authority for authority in source_manifest.record["authorities"]
        if isinstance(authority, Mapping) and authority.get("name") == PROFILE_NAME
    )
    if config.get("resource_id") != WORK_ID or config.get("title") != metadata["title"] or config.get("author") != metadata["author"]:
        raise ValueError("retained source header and existing config identity disagree")
    if _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("provenance source hash mismatch")
    return {
        "contract": "ocd-law-serious-call-provenance-v1",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "status": "nonaccepted",
        "scope": {
            "source_path": SOURCE_PATH,
            "source_sha256": SOURCE_SHA256,
            "source_bytes": len(source_bytes),
            "selector": "/ThML[1]",
            "division_count": len(profile["ordered_divisions"]),
            "source_member_count": 1,
            "excluded_retained_members": [],
            "excluded_body_carriers": [],
        },
        "source_metadata": {
            **dict(metadata),
            "source_edition": str(policy["provenance"]["identity"]["edition"]),
            "original_publication_year": None,
            "source_quality": "proofed",
            "proofreading_against_page_images": "not-performed",
        },
        "date_evidence": {
            "status": "unresolved-conflict",
            "claims": _date_claims(profile, policy),
            "config_original_publication_year": config.get("original_publication_year"),
            "config_year_disposition": "not-adopted-because-retained-witness-contains-conflicting-1728-and-1729-claims",
        },
        "retained_authorities": {
            "source_config": {
                "path": config_authority["path"],
                "sha256": config_authority["sha256"],
            },
            "metadata_sidecar": {
                "path": metadata_authority["path"],
                "sha256": metadata_authority["sha256"],
            },
            "source_profile": {
                "path": profile_authority["path"],
                "sha256": profile_authority["sha256"],
            },
            "data_attribution_notice": {
                "path": attribution_authority["path"],
                "sha256": attribution_authority["sha256"],
            },
        },
        "source_quality": {
            "provider_marker": "Proofed",
            "classification": "proofed-source-text-witness",
            "ocr_correction_performed": False,
            "page_image_collation_performed": False,
        },
        "non_element_events": [
            {key: event[key] for key in ("ordinal", "kind", "bytes", "sha256")}
            for event in events
        ],
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
            "converter_id": CONVERTER_ID,
            "converter_version": CONVERTER_VERSION,
            "external_doctype": "removed-before-parse-not-loaded",
            "named_entity_replacement": "none",
            "source_comments": "preserved",
            "notes_and_scripture_references": "preserved",
            "source_navigation_exceptions": "exactly-two-source-target-absent-assertions-preserved-in-header-notes-attached-to-existing-divisions",
        },
    }


def convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    """Produce the five flat members of the nonaccepted candidate package."""

    if source_manifest.record.get("source_id") != SOURCE_ID or source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("source manifest does not identify law-serious-call")
    raw = _authority_bytes(source_manifest, "law-serious-call-retained-source")
    if _sha(raw) != SOURCE_SHA256:
        raise ValueError("retained CCEL source bytes do not match the pinned witness")
    root, events = _parse_source(raw)
    body = root.find("ThML.body")
    header = root.find("ThML.head")
    if body is None or header is None:
        raise ValueError("complete ThML envelope requires both head and body")
    features, body_ordinals, header_ordinals = _source_features(root, body)
    profile, policy, metadata, navigation_exceptions = _profile_and_policy(
        source_manifest,
        root,
        raw,
        events,
        body,
        features,
    )
    all_counts, body_counts, census = _census(root, body)
    id_values = [node.get("id") for node in root.iter() if isinstance(node.tag, str) and node.get("id")]
    retained_ids = set(id_values)
    href_targets = [node.get("href", "")[1:] for node in body.iter() if isinstance(node.tag, str) and _local(node) == "a" and node.get("href", "").startswith("#")]
    if set(href_targets) - retained_ids:
        raise ValueError("retained internal link points outside the exact source member")
    div1s = [node for node in body if isinstance(node.tag, str) and _local(node) == "div1"]
    division_rows = profile["ordered_divisions"]
    navigation_rows = _navigation_title_rows(profile, body, body_ordinals)
    division_by_id = {str(row["source_id"]): row for row in division_rows}
    navigation_by_selector = {
        str(row["source_selector"]): str(row["candidate_xml_id"])
        for row in navigation_rows
    }
    navigation_exceptions_by_edge = {
        (str(row["selector"]), str(row["direction"])): row
        for row in navigation_exceptions
    }
    title_list = _tei_element("list", {"type": "source-navigation-titles"})
    for row in navigation_rows:
        item = _append(
            title_list,
            "item",
            {
                "xml:id": str(row["candidate_xml_id"]),
                "corresp": f"#{row['target_xml_id']}",
                **({"n": str(row["source_n"])} if row["source_n"] else {}),
            },
            str(row["source_title"]),
        )
    tags_decl, rendition_refs = _renditions(header)
    tei = _tei_element("TEI", {"xml:id": WORK_ID})
    tei_header = _append(tei, "teiHeader", {"xml:id": f"{WORK_ID}-tei-header"})
    file_desc = _append(tei_header, "fileDesc")
    title_stmt = _append(file_desc, "titleStmt")
    _append(title_stmt, "title", {"xml:id": f"{WORK_ID}-tei-title"}, metadata["title"])
    _append(title_stmt, "author", {"xml:id": f"{WORK_ID}-tei-author"}, metadata["author"])
    if metadata.get("provider"):
        resp_stmt = _append(title_stmt, "respStmt")
        _append(resp_stmt, "resp", text="Provider of the retained electronic text")
        _append(resp_stmt, "name", {"xml:id": f"{WORK_ID}-tei-provider"}, metadata["provider"])
    edition_stmt = _append(file_desc, "editionStmt")
    _append(edition_stmt, "edition", text=str(policy["provenance"]["identity"]["edition"]))
    publication_stmt = _append(file_desc, "publicationStmt")
    _append(publication_stmt, "publisher", text=metadata.get("provider", "CCEL"))
    availability = _append(publication_stmt, "availability", {"status": "unknown"})
    _append(availability, "p", text="CCEL attribution and no-sale terms are preserved for human rights review; no rights-clearance decision is recorded.")
    notes_stmt = _append(file_desc, "notesStmt")
    metadata_note = _append(
        notes_stmt,
        "note",
        {"type": "retained-thml-header", "xml:id": f"{WORK_ID}-source-header-capture", "corresp": _source_pointer(_selector(header))},
    )
    metadata_note.append(_header_segment(header, header_ordinals=header_ordinals))
    _append(notes_stmt, "note", {"type": "source-navigation-title-inventory"}).append(title_list)
    for exception in navigation_exceptions:
        _append_navigation_exception_note(notes_stmt, exception)
    source_desc = _append(file_desc, "sourceDesc")
    bibl = _append(source_desc, "bibl")
    _append(bibl, "title", text="Retained CCEL ThML witness")
    _append(bibl, "author", text=metadata["author"])
    ref = _append(bibl, "ref", {"target": "https://www.ccel.org/ccel/law/serious_call.xml"}, "CCEL source record")
    ref.set("type", "source-witness")
    _append(bibl, "idno", {"type": "sha256"}, SOURCE_SHA256)
    encoding_desc = _append(tei_header, "encodingDesc")
    project_desc = _append(encoding_desc, "projectDesc")
    _append(project_desc, "p", text="This candidate represents the complete retained ThML member. The source order, paragraphs, headings, notes, scripture references, links, addition, index marker, header metadata, and presentation metadata are accounted for. Exactly two source prev/next assertions to absent target toc remain unresolved in header notes attached to the title page and acknowledgements; no target ID was invented and no generated navigation title was substituted. The external ThML DOCTYPE is byte-accounted but was not loaded; no named-entity substitution or OCR correction was performed.")
    editorial_decl = _append(encoding_desc, "editorialDecl")
    _append(editorial_decl, "p", text="CCEL labels this source text Proofed. No proofreading against page images was performed. Source language and readings are retained; the conflicting 1728 and 1729 claims and the two absent-target source navigation assertions remain unresolved in unresolved.jsonl.")
    if len(tags_decl):
        encoding_desc.append(tags_decl)
    profile_desc = _append(tei_header, "profileDesc")
    lang_usage = _append(profile_desc, "langUsage")
    _append(lang_usage, "language", {"ident": metadata["language"] or "und"}, metadata["language"] or "und")
    divisions_note = _append(profile_desc, "textClass")
    keywords = _append(divisions_note, "keywords", {"scheme": "CCEL-ThML-source-subjects"})
    subjects = root.xpath("./ThML.head/electronicEdInfo/DC/DC.Subject")
    for subject in subjects:
        value = " ".join("".join(subject.itertext()).split())
        if value:
            _append(keywords, "term", {"type": subject.get("scheme", "source")}, value)

    text_node = _append(tei, "text", {"xml:id": f"{WORK_ID}-text"})
    wrappers = {
        "front": _append(text_node, "front"),
        "body": _append(text_node, "body"),
        "back": _append(text_node, "back"),
    }
    if len(div1s) != len(division_rows):
        raise ValueError("candidate source divisions no longer match profile")
    for source_division, profile_row in zip(div1s, division_rows, strict=True):
        region = str(profile_row["region"])
        wrappers[region].append(
            _body_node(
                source_division,
                body_ordinals=body_ordinals,
                division_by_id=division_by_id,
                navigation_by_selector=navigation_by_selector,
                rendition_refs=rendition_refs,
                retained_ids=retained_ids,
                navigation_exceptions=navigation_exceptions_by_edge,
            )
        )

    prolog_comment = root.getprevious()
    comment_text = prolog_comment.text if isinstance(prolog_comment, etree._Comment) else None
    comment_events = [event for event in events if event["kind"] == "comment"]
    if len(comment_events) != 1 or comment_text is None:
        raise ValueError("expected one preserved source prolog comment")
    tei.addprevious(etree.Comment(comment_text))
    tei_bytes = etree.tostring(
        tei.getroottree(),
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    ) + b"\n"

    navigation_inventory = [
        {
            "ordinal": int(row["ordinal"]),
            "source_id": row["source_id"],
            "source_n": row["source_n"],
            "source_title": row["source_title"],
            "selector": row["source_selector"],
            "region": next((d["region"] for d in division_rows if d["source_id"] == row["source_id"]), None),
            "tei_type": next((d["tei_type"] for d in division_rows if d["source_id"] == row["source_id"]), None),
            "target_xml_id": row["target_xml_id"],
            "candidate_xml_id": row["candidate_xml_id"],
        }
        for row in navigation_rows
    ]
    accountability = {
        "contract": "ocd-law-serious-call-source-accountability-v1",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(raw),
            "sha256": _sha(raw),
            "selector": "/ThML[1]",
            "disposition": "complete-whole-retained-member",
        },
        "source_census": census,
        "element_counts": all_counts,
        "body_element_counts": body_counts,
        "ordered_divisions": [
            {
                "ordinal": row["ordinal"],
                "source_id": row["source_id"],
                "source_n": row["source_n"],
                "source_title": row["source_title"],
                "selector": row["selector"],
                "region": row["region"],
                "tei_type": row["tei_type"],
                "target_xml_id": row["source_id"],
            }
            for row in division_rows
        ],
        "navigation_titles": navigation_inventory,
        "source_navigation": {
            "edge_count": 62,
            "resolved_edge_count": 60,
            "unresolved_edges": navigation_exceptions,
        },
        "features": features,
        "non_element_events": [
            {
                "ordinal": event["ordinal"],
                "kind": event["kind"],
                "bytes": event["bytes"],
                "sha256": event["sha256"],
                "disposition": (
                    "preserved-as-tei-comment"
                    if event["kind"] == "comment"
                    else "external-doctype-not-loaded-or-copied"
                    if event["kind"] == "doctype"
                    else "processing-instruction-accountability-only"
                ),
            }
            for event in events
        ],
        "unresolved_date_claims": _date_claims(profile, policy),
        "dispositions": {
            "unsupported_element_count": 0,
            "excluded_member_count": 0,
            "excluded_body_carrier_count": 0,
            "date_conflict": "unresolved",
            "rights_review": "not-decided",
            "accepted_master": False,
        },
    }
    provenance = _provenance(source_manifest, profile, policy, metadata, raw, events)
    readme = _authority_bytes(source_manifest, README_NAME)
    return {
        "README.source.md": readme,
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": _unresolved_bytes(profile, policy),
    }


convert.converter_id = CONVERTER_ID  # type: ignore[attr-defined]
convert.converter_version = CONVERTER_VERSION  # type: ignore[attr-defined]
