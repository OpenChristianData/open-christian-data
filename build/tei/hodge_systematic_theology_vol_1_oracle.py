"""Producer-independent oracle for source-to-TEI issue 37c-203."""

from __future__ import annotations

import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import sys
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.writer import tei_el


ORACLE_ID = "ocd-37c203-hodge-systematic-theology-vol-1-oracle"
ORACLE_VERSION = "1"
PROFILE_ID = "hodge-systematic-theology-vol-1-ccel-content-roots-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MEMBERS = {
    "README.source.md",
    "content.tei.xml",
    "manifest.json",
    "provenance.json",
    "source-accountability.json",
    "unresolved.jsonl",
}
SOURCE_KEY = "hodge-vol-1"
SOURCE_PATH = "raw/ccel/hodge/theology1.xml"
SOURCE_BYTES = 2_243_559
SOURCE_SHA256 = "f01ffb5235657a0b21f56a1a4eb7ef95b836ba9d907f9acd1402e8a6fe450fc6"
WORK_ID = "hodge-systematic-theology-vol-1"
ASSIGNED_ROOTS = ((SOURCE_KEY, "iii", WORK_ID), (SOURCE_KEY, "iv", WORK_ID))
ASSIGNED_ROOT_IDS = ("iii", "iv")
TOP_LEVEL_IDS = ("i", "ii", "iii", "iv", "v")
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "FR": "fr", "HE": "he", "LA": "la"}
SOURCE_ONLY_ATTRIBUTES = {"next", "parsed", "prev", "progress", "version"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not isinstance(value, dict) or _canonical(value) != content:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _source_tree(content: bytes) -> etree._ElementTree:
    try:
        return etree.parse(
            io.BytesIO(content),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                remove_comments=False,
                remove_pis=False,
                huge_tree=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("retained Hodge source is not well formed") from exc


def _tei_tree(content: bytes) -> etree._ElementTree:
    try:
        return etree.ElementTree(
            etree.fromstring(
                content,
                etree.XMLParser(
                    resolve_entities=False,
                    no_network=True,
                    remove_comments=False,
                    remove_pis=False,
                    huge_tree=True,
                ),
            )
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("candidate TEI is not well formed") from exc


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        parent = current.getparent()
        if parent is None or not isinstance(current.tag, str):
            break
        peers = [child for child in parent if child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    if current is None:
        raise ValueError("source selector escaped ThML.body")
    return "ThML.body/" + "/".join(reversed(parts))


def _census(nodes: list[etree._Element]) -> dict[str, Any]:
    elements = [node for node in nodes if isinstance(node.tag, str)]
    strings = [(node.text or "") + (node.tail or "") for node in elements]
    return {
        "attribute_counts": dict(
            sorted(Counter(name for node in elements for name in node.attrib).items())
        ),
        "attributes": sum(len(node.attrib) for node in elements),
        "characters": sum(len(value) for value in strings),
        "direct_text_bytes": sum(
            len((node.text or "").encode("utf-8")) for node in elements
        ),
        "elements": len(elements),
        "non_ascii_characters": sum(
            sum(ord(char) > 127 for char in value) for value in strings
        ),
        "notes": sum(node.tag == "note" for node in elements),
        "page_breaks": sum(node.tag == "pb" for node in elements),
        "scripture_refs": sum(node.tag == "scripRef" for node in elements),
        "tag_counts": dict(sorted(Counter(node.tag for node in elements).items())),
        "tail_text_bytes": sum(
            len((node.tail or "").encode("utf-8")) for node in elements
        ),
        "tail_nodes": sum(bool(node.tail) for node in elements),
        "text_nodes": sum(bool(node.text) for node in elements),
    }


def _subtract(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in left:
        if key in ("tag_counts", "attribute_counts"):
            result[key] = {
                name: value - right.get(key, {}).get(name, 0)
                for name, value in left[key].items()
                if value - right.get(key, {}).get(name, 0)
            }
        else:
            result[key] = left[key] - right.get(key, 0)
    return result


def _document_accounting(tree: etree._ElementTree) -> dict[str, Any]:
    root = tree.getroot()
    before: list[dict[str, str]] = []
    node = root.getprevious()
    while node is not None:
        before.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getprevious()
    before.reverse()
    after: list[dict[str, str]] = []
    node = root.getnext()
    while node is not None:
        after.append(
            {
                "kind": "comment"
                if node.tag is etree.Comment
                else "processing-instruction",
                "text": node.text or "",
                "tail": node.tail or "",
            }
        )
        node = node.getnext()
    return {
        "doctype": tree.docinfo.doctype,
        "encoding": tree.docinfo.encoding,
        "post_root_nodes": after,
        "pre_root_nodes": before,
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {
            "" if key is None else key: value for key, value in root.nsmap.items()
        },
        "root_tag": root.tag,
        "standalone": tree.docinfo.standalone,
        "xml_version": tree.docinfo.xml_version,
    }


def _metadata_entries(nodes: list[etree._Element]) -> list[dict[str, Any]]:
    return [
        {
            "attributes": dict(node.attrib),
            "tag": node.tag,
            "tail": node.tail or "",
            "text": node.text or "",
        }
        for node in nodes
    ]


def _source_metadata(tree: etree._ElementTree) -> dict[str, Any]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained Hodge source lacks ThML.head")
    electronic = head.find("electronicEdInfo")
    if electronic is None:
        raise ValueError("retained Hodge source lacks electronicEdInfo")
    dc = electronic.find("DC")
    return {
        "dc_entries": _metadata_entries(list(dc) if dc is not None else []),
        "electronic_ed_info_entries": _metadata_entries(
            [node for node in electronic if node.tag != "DC"]
        ),
        "head_c14n_sha256": _sha(etree.tostring(head, method="c14n", with_comments=True)),
        "print_source_entries": _metadata_entries(
            list(head.find("printSourceInfo"))
            if head.find("printSourceInfo") is not None
            else []
        ),
    }


def _config(source_manifest: SourceManifest) -> dict[str, Any]:
    config = json.loads(source_manifest.authority_path("work-config").read_bytes())
    if not isinstance(config, dict):
        raise ValueError("37c-203 work config is not a JSON object")
    if (
        config.get("resource_id") != WORK_ID
        or config.get("title") != "Systematic Theology, Vol. 1"
        or config.get("author") != "Charles Hodge"
        or config.get("source_url") != "https://www.ccel.org/ccel/hodge/theology1.xml"
        or config.get("source_format") != "ThML XML"
        or config.get("source_hash") != f"sha256:{SOURCE_SHA256}"
    ):
        raise ValueError("37c-203 work config source identity or hash drift")
    return config


def _authority(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _policy(source_manifest: SourceManifest) -> dict[str, Any]:
    policy = json.loads(_authority(source_manifest, "validation-policy"))
    if not isinstance(policy, dict) or policy.get("policy_id") != PROFILE_ID:
        raise ValueError("37c-203 validation policy binding drift")
    return policy


def _profile(source_manifest: SourceManifest) -> dict[str, Any]:
    profile = json.loads(_authority(source_manifest, "reconstruction-profile"))
    if not isinstance(profile, dict) or profile.get("profile_id") != PROFILE_ID:
        raise ValueError("37c-203 reconstruction profile binding drift")
    return profile


def _selected(
    tree: etree._ElementTree, source_manifest: SourceManifest
) -> list[tuple[etree._Element, str, str]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained Hodge source lacks ThML.body")
    top = [child for child in body if isinstance(child.tag, str)]
    if [node.tag for node in top] != ["div1"] * len(top):
        raise ValueError("Hodge source envelope contains an unsupported top-level node")
    if tuple(node.get("id") for node in top) != TOP_LEVEL_IDS:
        raise ValueError("Hodge source top-level div1 envelope drift")
    scope = source_manifest.record.get("scope")
    if not isinstance(scope, Mapping):
        raise ValueError("37c-203 source scope is invalid")
    assigned = tuple(tuple(item) for item in scope.get("assigned_roots_in_source_order", ()))
    if assigned != ASSIGNED_ROOTS or tuple(scope.get("excluded_top_level_roots", ())) != (
        "i",
        "ii",
        "v",
    ):
        raise ValueError("37c-203 source scope binding drift")
    result: list[tuple[etree._Element, str, str]] = []
    previous = -1
    for key, source_id, work_id in ASSIGNED_ROOTS:
        matches = [
            (index, node)
            for index, node in enumerate(top)
            if node.get("id") == source_id
        ]
        if len(matches) != 1:
            raise ValueError(f"37c-203 source root missing or duplicated: {source_id}")
        index, node = matches[0]
        if index <= previous:
            raise ValueError("37c-203 assigned source root order drift")
        previous = index
        result.append((node, key, work_id))
    return result


def _target_attributes(
    policy: Mapping[str, Any], source: etree._Element, feature_id: str
) -> tuple[str, dict[str, str]]:
    projection = policy["projection"]
    source_tag = str(source.tag)
    target_tag = (
        str(projection["language_span_tag"])
        if source_tag == "span" and source.get("lang")
        else str(projection["tag_map"].get(source_tag, ""))
    )
    if not target_tag:
        raise ValueError(f"37c-203 source element lacks a projection: {source_tag}")
    attrs: dict[str, str] = {"xml:id": feature_id}
    rend: list[str] = []
    if source_tag in ("div1", "div2", "div3", "div"):
        attrs["type"] = str(
            projection["derived_attributes"]["div_type_template"].format(
                source_tag=source_tag
            )
        )
    if source_tag == "span" and not source.get("lang"):
        attrs["type"] = str(projection["derived_attributes"]["plain_span_type"])
    source_rend = projection["derived_attributes"]["source_tag_rend"]
    if source_tag in source_rend and source_rend[source_tag]:
        rend.append(str(source_rend[source_tag]))
    for name, value in source.attrib.items():
        rule = policy["attribute_rules"].get(name)
        if not isinstance(rule, Mapping) or source_tag not in rule.get("source_tags", ()):
            raise ValueError(
                f"37c-203 source attribute lacks a declared disposition: {source_tag}@{name}"
            )
        if name == "class":
            rend.append(f"class={value}")
        elif name == "style":
            rend.append(f"style={value}")
        elif name == "border":
            rend.append(f"border={value}")
        elif name == "lang":
            if value not in LANGUAGE_MAP:
                raise ValueError(f"37c-203 unsupported source language code: {value}")
            attrs["xml:lang"] = LANGUAGE_MAP[value]
        elif name == "n":
            attrs["n"] = value
        elif name == "href":
            attrs["facs"] = value
        elif name == "passage":
            attrs["cRef"] = value
        elif name == "osisRef":
            attrs["target"] = value
        elif name == "rowspan":
            attrs["rows"] = value
        elif name == "colspan":
            attrs["cols"] = value
        elif name in SOURCE_ONLY_ATTRIBUTES or name in {"id", "title"}:
            continue
        else:
            raise ValueError(f"37c-203 source attribute mapping is incomplete: {name}")
    if rend:
        attrs["rend"] = "; ".join(rend)
    if source_tag == "scripRef":
        attrs["type"] = "scripture"
    return target_tag, attrs


def _expected_rows(
    selected: list[tuple[etree._Element, str, str]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def visit(
        source: etree._Element,
        parent_feature_id: str | None,
        source_root_id: str,
        work_id: str,
        child_ordinal: int,
    ) -> None:
        if not isinstance(source.tag, str):
            raise ValueError("37c-203 assigned source contains a non-element node")
        ordinal = len(rows) + 1
        feature_id = f"hodge-systematic-theology-vol-1-feature-{ordinal:06d}"
        target_tag, target_attrs = _target_attributes(policy, source, feature_id)
        dispositions: list[dict[str, str]] = []
        for name, value in source.attrib.items():
            rule = policy["attribute_rules"].get(name)
            if name == "id":
                destination = "@xml:id-and-source-accountability"
                method = "deterministic-global-feature-id"
            elif name == "title":
                destination = "child::head[1]"
                method = "synthetic-head-preserves-exact-source-title"
            elif name in SOURCE_ONLY_ATTRIBUTES:
                destination = "source-accountability-only"
                method = "preserved-exactly-in-accountability"
            elif name == "class":
                destination = "@rend"
                method = "exact-source-class-token-in-rend"
            elif name == "style":
                destination = "@rend"
                method = "exact-source-style-token-in-rend"
            elif name == "border":
                destination = "@rend"
                method = "exact-source-border-token-in-rend"
            else:
                destination = str(rule.get("disposition", "source-accountability-only"))
                method = "declared-attribute-map"
            dispositions.append(
                {
                    "destination": destination,
                    "method": method,
                    "source_attribute": name,
                    "source_value": value,
                }
            )
        rows.append(
            {
                "attribute_dispositions": dispositions,
                "child_ordinal": child_ordinal,
                "direct_text_length": len((source.text or "").encode("utf-8")),
                "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
                "disposition": "represented",
                "feature_id": feature_id,
                "parent_feature_id": parent_feature_id,
                "source_attributes": dict(source.attrib),
                "source_member": SOURCE_KEY,
                "source_root_id": source_root_id,
                "source_selector": _selector(source),
                "source_tag": source.tag,
                "source_title_head": source.get("title")
                if source.tag in {"div1", "div2", "div3", "div"}
                else None,
                "source_xml_id": source.get("id"),
                "tail_text_length": len((source.tail or "").encode("utf-8")),
                "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
                "tei_attributes": target_attrs,
                "tei_tag": target_tag,
                "tei_xml_id": target_attrs["xml:id"],
                "work_id": work_id,
            }
        )
        for ordinal_in_parent, child in enumerate(source, 1):
            if not isinstance(child.tag, str):
                raise ValueError("37c-203 assigned source contains a non-element child")
            visit(child, feature_id, source_root_id, work_id, ordinal_in_parent)

    for source_root, _key, work_id in selected:
        visit(
            source_root,
            None,
            source_root.get("id") or "",
            work_id,
            TOP_LEVEL_IDS.index(source_root.get("id")) + 1,
        )
    return rows


def _expected_header(
    tree: etree._ElementTree, config: Mapping[str, Any], source_sha256: str
) -> etree._Element:
    title = "".join(
        str(value)
        for value in tree.xpath(
            "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
        )
    )
    if title != "Systematic Theology - Volume I":
        raise ValueError("37c-203 retained electronic title drift")
    root = tei_el("TEI", {"xml:id": "hodge-systematic-theology-vol-1-candidate"})
    header = tei_el("teiHeader")
    file_desc = tei_el("fileDesc")
    title_stmt = tei_el("titleStmt")
    title_stmt.append(tei_el("title", {"type": "retained-electronic-title"}, title))
    title_stmt.append(tei_el("author", text="Charles Hodge"))
    resp_stmt = tei_el("respStmt")
    resp_stmt.append(tei_el("resp", text="electronic source"))
    resp_stmt.append(tei_el("name", text="Christian Classics Ethereal Library"))
    title_stmt.append(resp_stmt)
    file_desc.append(title_stmt)
    publication = tei_el("publicationStmt")
    publication.append(
        tei_el("publisher", text="Grand Rapids, MI: Christian Classics Ethereal Library")
    )
    availability = tei_el("availability", {"status": "unknown"})
    availability.append(
        tei_el(
            "p",
            text="Electronic source rights statement is empty; human rights review remains required.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = tei_el("sourceDesc")
    bibl = tei_el("bibl", {"xml:id": "source-hodge-systematic-theology-vol-1"})
    bibl.append(tei_el("title", {"type": "retained-electronic-title"}, title))
    bibl.append(tei_el("author", text="Charles Hodge"))
    bibl.append(
        tei_el(
            "publisher",
            text="Grand Rapids, MI: Christian Classics Ethereal Library",
        )
    )
    bibl.append(tei_el("date", {"when": "2005-06-20"}, "2005-06-20"))
    bibl.append(tei_el("idno", {"type": "CCEL-XML-url"}, str(config["source_url"])))
    bibl.append(tei_el("idno", {"type": "CCEL-path"}, "/ccel/hodge/theology1.html"))
    bibl.append(tei_el("idno", {"type": "sha256"}, source_sha256))
    bibl.append(
        tei_el(
            "note",
            {"type": "local-edition-claim", "source": "work-config"},
            str(config["source_edition"]),
        )
    )
    bibl.append(
        tei_el(
            "note",
            {"type": "retained-header-rights"},
            "DC.Rights is empty in the retained electronic header.",
        )
    )
    bibl.append(tei_el("note", {"type": "source-attribution"}, "Sourced via CCEL.org."))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    root.append(header)
    return root


def _root_accounting(
    tree: etree._ElementTree, assigned_ids: set[str]
) -> list[dict[str, Any]]:
    body = tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("retained Hodge source lacks ThML.body")
    result: list[dict[str, Any]] = []
    for ordinal, node in enumerate(body, 1):
        if not isinstance(node.tag, str):
            raise ValueError("Hodge source body contains a non-element top-level node")
        source_id = node.get("id")
        assigned = source_id in assigned_ids
        result.append(
            {
                "census": _census(list(node.iter())),
                "disposition": "assigned-work-root-represented"
                if assigned
                else "source-evidence-outside-work-projection",
                "feature_count": sum(1 for _ in node.iter()),
                "id": source_id,
                "ordinal": ordinal,
                "reason": "complete source-native subtree represented in retained order"
                if assigned
                else "title-page, prefatory, or index material outside the assigned volume content roots",
                "selector": _selector(node),
                "tag": node.tag,
                "title": node.get("title", ""),
            }
        )
    return result


def _expected_accountability(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    selected: list[tuple[etree._Element, str, str]],
    rows: list[dict[str, Any]],
    assigned_census: dict[str, Any],
) -> dict[str, Any]:
    complete_census = _census(list(tree.getroot().iter()))
    root_bindings: list[dict[str, Any]] = []
    cursor = 0
    for source_root, key, work_id in selected:
        count = sum(1 for _ in source_root.iter())
        root_bindings.append(
            {
                "feature_count": count,
                "root_census": _census(list(source_root.iter())),
                "source_key": key,
                "source_member": SOURCE_PATH,
                "source_root_id": source_root.get("id"),
                "source_root_selector": _selector(source_root),
                "source_root_title": source_root.get("title", ""),
                "source_order": ASSIGNED_ROOT_IDS.index(source_root.get("id")) + 1,
                "work_id": work_id,
            }
        )
        cursor += count
    if cursor != len(rows):
        raise ValueError("37c-203 crosswalk root count drift")
    return {
        "assigned_census": assigned_census,
        "assigned_root_count": len(selected),
        "assigned_work_count": 1,
        "attribute_count": assigned_census["attributes"],
        "complete_source_envelope": {
            "assigned_root_ids_in_source_order": list(ASSIGNED_ROOT_IDS),
            "excluded_root_ids": [item for item in TOP_LEVEL_IDS if item not in ASSIGNED_ROOT_IDS],
            "top_level_root_ids_in_source_order": list(TOP_LEVEL_IDS),
            "top_level_root_count": len(TOP_LEVEL_IDS),
        },
        "contract": "ocd-37c203-source-accountability-v1",
        "crosswalk": rows,
        "duplicate_feature_count": 0,
        "feature_count": len(rows),
        "member_accounting": [
            {
                "assigned_scope_census": assigned_census,
                "bytes": SOURCE_BYTES,
                "complete_document_census": complete_census,
                "document_accounting": _document_accounting(tree),
                "excluded_scope_census": _subtract(complete_census, assigned_census),
                "key": SOURCE_KEY,
                "path": SOURCE_PATH,
                "sha256": SOURCE_SHA256,
                "disposition": "retained primary source; assigned content roots represented and all excluded top-level roots explicitly accounted",
            }
        ],
        "omitted_feature_count": 0,
        "profile_id": PROFILE_ID,
        "root_accounting": _root_accounting(tree, set(ASSIGNED_ROOT_IDS)),
        "root_bindings": root_bindings,
        "schema": "inline-entry-structural-contract-v1",
        "source_member_count": 1,
        "unresolved_feature_count": 0,
        "work_bindings": [
            {
                "root_ids": list(ASSIGNED_ROOT_IDS),
                "source_key": SOURCE_KEY,
                "source_member": SOURCE_PATH,
                "work_id": WORK_ID,
            }
        ],
    }


def _expected_provenance(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    witness_inventory = json.loads(_authority(source_manifest, "witness-inventory"))
    permission_path = source_manifest.authority_path("ccel-permission-evidence")
    permission_bytes = permission_path.read_bytes()
    return {
        "canonical_data_written": False,
        "canonical_ir_written": False,
        "contract": "ocd-37c203-provenance-v1",
        "publication_state": "not_ready",
        "source_id": source_manifest.record["source_id"],
        "source_scope": {
            "assigned_roots": [list(item) for item in ASSIGNED_ROOTS],
            "excluded_top_level_roots": [item for item in TOP_LEVEL_IDS if item not in ASSIGNED_ROOT_IDS],
            "kind": "complete-source-subtrees",
        },
        "sources": {
            SOURCE_KEY: {
                "bytes": SOURCE_BYTES,
                "config_claims": dict(config),
                "metadata": _source_metadata(tree),
                "path": SOURCE_PATH,
                "permission_evidence": {
                    "bytes": len(permission_bytes),
                    "path": "docs/sources/ccel-permission.md",
                    "sha256": _sha(permission_bytes),
                },
                "sha256": SOURCE_SHA256,
                "witness_inventory": witness_inventory,
            }
        },
        "works": [
            {
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
                "root_ids": list(ASSIGNED_ROOT_IDS),
                "source_key": SOURCE_KEY,
                "source_member": SOURCE_PATH,
                "textual_form": "retained English CCEL electronic ThML witness; translation or revision allocation not established",
                "translation_credit": {
                    "credited_to": [],
                    "status": "not-established-in-retained-source",
                    "work_specific_allocation": None,
                },
                "work_id": WORK_ID,
            }
        ],
    }


def _expected_unresolved() -> bytes:
    records = [
        {
            "evidence": "The retained ThML head has no printSourceInfo element. The local config records the original-edition claim New York: Scribner, Armstrong, 1872-1873, but this route does not treat that local claim as independently proven by the retained electronic source.",
            "id": "hodge-systematic-theology-vol-1-print-edition-claim",
            "scope": "edition and witness identity",
            "status": "unresolved",
        },
        {
            "evidence": "The retained source credits Charles Hodge and identifies CCEL metadata, but does not establish a work-specific translator, reviser, or contributor allocation for the selected content roots.",
            "id": "hodge-systematic-theology-vol-1-textual-form-and-contributors",
            "scope": "textual form and contributors",
            "status": "unresolved",
        },
        {
            "evidence": "The retained electronic DC.Rights field is empty. The bound CCEL permission evidence permits parsing ThML/XML, but technical verification is not a rights clearance, human acceptance, durable IR admission, or publication authorization.",
            "id": "hodge-systematic-theology-vol-1-rights-and-acceptance",
            "scope": "rights, human acceptance, and publication",
            "status": "unresolved",
        },
        {
            "evidence": "CVW visual comparison has not been performed for the exact source/candidate pair. Visual reach, metadata adoption, durable IR admission, promotion, and publication remain separate gates.",
            "id": "hodge-systematic-theology-vol-1-visual-review-and-admission",
            "scope": "visual review and downstream admission",
            "status": "unresolved",
        },
    ]
    return b"".join(_canonical(record) for record in records)


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {
        "xml:id"
        if key == f"{{{XML_NS}}}id"
        else "xml:lang"
        if key == f"{{{XML_NS}}}lang"
        else key: value
        for key, value in node.attrib.items()
    }


def _verify_node(
    source: etree._Element,
    target: etree._Element,
    policy: Mapping[str, Any],
    state: list[int],
    parent_feature_id: str | None,
) -> None:
    state[0] += 1
    feature_id = f"hodge-systematic-theology-vol-1-feature-{state[0]:06d}"
    target_tag, target_attrs = _target_attributes(policy, source, feature_id)
    if target.tag != f"{{{TEI_NS}}}{target_tag}":
        raise ValueError(f"TEI tag drift at {_selector(source)}")
    if _normalized_attrs(target) != target_attrs:
        raise ValueError(f"TEI attribute drift at {_selector(source)}")
    if (target.text or "") != (source.text or "") or (target.tail or "") != (
        source.tail or ""
    ):
        raise ValueError(f"TEI direct text or tail drift at {_selector(source)}")
    children = list(target)
    index = 0
    title = source.get("title") if source.tag in {"div1", "div2", "div3", "div"} else None
    if title is not None:
        if (
            not children
            or children[0].tag != f"{{{TEI_NS}}}head"
            or _normalized_attrs(children[0])
            or children[0].text != title
            or children[0].tail
            or len(children[0])
        ):
            raise ValueError(f"division head drift at {_selector(source)}")
        index = 1
    for source_child in source:
        if index >= len(children):
            raise ValueError(f"TEI source child omitted at {_selector(source)}")
        _verify_node(source_child, children[index], policy, state, feature_id)
        index += 1
    if index != len(children):
        raise ValueError(f"TEI omission, duplication, or invention at {_selector(source)}")


def _first_party_module_path(root: Path, module: str) -> Path | None:
    direct = root.joinpath(*module.split(".")).with_suffix(".py")
    package = root.joinpath(*module.split("."), "__init__.py")
    if direct.is_file():
        return direct
    if package.is_file():
        return package
    return None


def _resolved_import_name(
    module: str, path: Path, imported: str | None, level: int
) -> str:
    if level == 0:
        return imported or ""
    parts = module.split(".")
    base = parts if path.name == "__init__.py" else parts[:-1]
    base = base[: len(base) - (level - 1)]
    if imported:
        base.extend(imported.split("."))
    return ".".join(base)


def _closure_paths(root: Path, policy: Mapping[str, Any]) -> tuple[Path, ...]:
    forbidden = tuple(policy.get("forbidden_oracle_imports", []))
    pending = ["build.tei.hodge_systematic_theology_vol_1_oracle"]
    modules: dict[str, Path] = {}
    while pending:
        module = pending.pop()
        if module in modules:
            continue
        path = _first_party_module_path(root, module)
        if path is None:
            continue
        modules[module] = path
        parts = module.split(".")
        package_parts = parts if path.name == "__init__.py" else parts[:-1]
        for index in range(1, len(package_parts) + 1):
            package = ".".join(package_parts[:index])
            if package not in modules:
                pending.append(package)
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(parsed):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _resolved_import_name(module, path, node.module, node.level)
                if base:
                    names.append(base)
                    names.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif isinstance(node, ast.Call) and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"__import__", "eval", "exec", "import_module"}
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                )
            ):
                raise ValueError("oracle closure contains dynamic import or execution")
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"oracle closure contains forbidden import {name}")
                if _first_party_module_path(root, name) is not None:
                    pending.append(name)
    return tuple(sorted(set(modules.values()), key=lambda item: item.as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, Any]) -> str:
    return _sha(
        _canonical(
            [
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": _sha(path.read_bytes()),
                }
                for path in _closure_paths(root, policy)
            ]
        )
    )


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    if set(candidate.member_names) != MEMBERS or candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("37c-203 candidate member or status drift")
    root = source_manifest.repository_root
    converter = source_manifest.record["converter"]
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("source_manifest") != expected_manifest
        or candidate.manifest.get("converter") != converter
        or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]
    ):
        raise ValueError("37c-203 candidate authority binding drift")
    config = _config(source_manifest)
    profile = _profile(source_manifest)
    policy = _policy(source_manifest)
    content = _authority(source_manifest, "retained-hodge-vol-1")
    if len(content) != SOURCE_BYTES or _sha(content) != SOURCE_SHA256:
        raise ValueError("37c-203 retained source bytes or hash drift")
    tree = _source_tree(content)
    selected = _selected(tree, source_manifest)
    assigned_nodes = [node for root_node, _key, _work_id in selected for node in root_node.iter()]
    assigned_census = _census(assigned_nodes)
    if assigned_census != profile["assigned_census"]:
        raise ValueError("37c-203 independent source census drift")
    if {
        root_node.get("id"): sum(1 for _ in root_node.iter())
        for root_node, _key, _work_id in selected
    } != profile["assigned_root_counts"]:
        raise ValueError("37c-203 independent root feature census drift")
    rows = _expected_rows(selected, policy)
    if len(rows) != assigned_census["elements"] or sum(
        len(row["source_attributes"]) for row in rows
    ) != assigned_census["attributes"]:
        raise ValueError("37c-203 independent source row census drift")
    tei = _tei_tree(candidate.member_bytes("content.tei.xml"))
    root_node = tei.getroot()
    if (
        root_node.tag != f"{{{TEI_NS}}}TEI"
        or _normalized_attrs(root_node) != {"xml:id": "hodge-systematic-theology-vol-1-candidate"}
        or root_node.text
        or root_node.tail
        or root_node.getprevious() is not None
        or root_node.getnext() is not None
    ):
        raise ValueError("37c-203 TEI root topology drift")
    children = list(root_node)
    if len(children) != 2 or [etree.QName(child).localname for child in children] != [
        "teiHeader",
        "text",
    ]:
        raise ValueError("37c-203 TEI root child inventory drift")
    expected_header = _expected_header(tree, config, SOURCE_SHA256).find(
        f"{{{TEI_NS}}}teiHeader"
    )
    if expected_header is None:
        raise ValueError("37c-203 expected header missing")
    actual_header = children[0]
    expected_header_bytes = etree.tostring(expected_header, method="c14n", with_comments=True)
    if etree.tostring(actual_header, method="c14n", with_comments=True) != expected_header_bytes:
        raise ValueError("37c-203 TEI header metadata drift")
    if _sha(expected_header_bytes) != policy["tei_topology"]["header_c14n_sha256"]:
        raise ValueError("37c-203 TEI header policy hash drift")
    text = children[1]
    if text.text or text.tail or _normalized_attrs(text) or len(text) != 1:
        raise ValueError("37c-203 TEI text topology drift")
    body = text[0]
    if (
        body.tag != f"{{{TEI_NS}}}body"
        or _normalized_attrs(body) != {"xml:id": "hodge-systematic-theology-vol-1-body"}
        or body.text
        or body.tail
    ):
        raise ValueError("37c-203 TEI body topology drift")
    work_roots = list(body)
    if len(work_roots) != len(selected):
        raise ValueError("37c-203 TEI assigned root count drift")
    state = [0]
    for (source_root, _key, _work_id), target_root in zip(selected, work_roots, strict=True):
        _verify_node(source_root, target_root, policy, state, None)
    if state[0] != assigned_census["elements"]:
        raise ValueError("37c-203 TEI projection count drift")
    schema = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path("tei-p5-xsd")))
    )
    try:
        schema.assertValid(tei)
    except etree.DocumentInvalid as exc:
        raise ValueError("37c-203 candidate fails TEI P5 XSD") from exc
    expected_accountability = _expected_accountability(
        source_manifest, tree, selected, rows, assigned_census
    )
    accountability = _strict_json(
        candidate.member_bytes("source-accountability.json"), "source accountability"
    )
    if accountability != expected_accountability:
        raise ValueError("37c-203 source-accountability drift")
    if _strict_json(candidate.member_bytes("provenance.json"), "provenance") != _expected_provenance(
        source_manifest, tree, config
    ):
        raise ValueError("37c-203 provenance metadata or state drift")
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved():
        raise ValueError("37c-203 unresolved evidence drift")
    if candidate.member_bytes("README.source.md") != _authority(
        source_manifest, "attribution-readme"
    ):
        raise ValueError("37c-203 source attribution README drift")
    result: dict[str, object] = {
        "candidate_sha256": candidate.sha256,
        "findings": [],
        "implementation_sha256": _sha(Path(__file__).resolve().read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "package_schema_sha256": _sha(_authority(source_manifest, "candidate-package-schema")),
        "policy_sha256": _sha(_authority(source_manifest, "validation-policy")),
        "profile_sha256": _sha(_authority(source_manifest, "reconstruction-profile")),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": SOURCE_SHA256,
        "status": "pass",
        "xsd_sha256": _sha(_authority(source_manifest, "tei-p5-xsd")),
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
