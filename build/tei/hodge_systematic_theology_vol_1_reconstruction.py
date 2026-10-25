"""Entry-local faithful TEI reconstruction for source-to-TEI issue 37c-203."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import tei_el


CONVERTER_ID = "ocd-37c203-hodge-systematic-theology-vol-1-to-tei"
CONVERTER_VERSION = "1"
PROFILE_ID = "hodge-systematic-theology-vol-1-ccel-content-roots-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"

SOURCE_KEY = "hodge-vol-1"
SOURCE_PATH = "raw/ccel/hodge/theology1.xml"
SOURCE_BYTES = 2_243_559
SOURCE_SHA256 = "f01ffb5235657a0b21f56a1a4eb7ef95b836ba9d907f9acd1402e8a6fe450fc6"
WORK_ID = "hodge-systematic-theology-vol-1"
ASSIGNED_ROOTS = ((SOURCE_KEY, "iii", WORK_ID), (SOURCE_KEY, "iv", WORK_ID))
ASSIGNED_ROOT_IDS = ("iii", "iv")
TOP_LEVEL_IDS = ("i", "ii", "iii", "iv", "v")
SUPPORTED_TAGS = {
    "blockquote",
    "br",
    "div",
    "div1",
    "div2",
    "div3",
    "h1",
    "h2",
    "h3",
    "h4",
    "i",
    "note",
    "p",
    "pb",
    "scripRef",
    "span",
    "sup",
    "table",
    "td",
    "th",
    "tr",
}
LANGUAGE_MAP = {"DE": "de", "EL": "grc", "FR": "fr", "HE": "he", "LA": "la"}
SOURCE_ONLY_ATTRIBUTES = {"next", "parsed", "prev", "progress", "version"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _source_tree(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(
            resolve_entities=False,
            no_network=True,
            remove_comments=False,
            remove_pis=False,
            huge_tree=True,
        ),
    )


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


def _source_config(source_manifest: SourceManifest) -> dict[str, Any]:
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


def _policy(source_manifest: SourceManifest) -> dict[str, Any]:
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    if not isinstance(policy, dict) or policy.get("policy_id") != PROFILE_ID:
        raise ValueError("37c-203 validation policy binding drift")
    return policy


def _profile(source_manifest: SourceManifest) -> dict[str, Any]:
    profile = json.loads(
        source_manifest.authority_path("reconstruction-profile").read_bytes()
    )
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
    selected: list[tuple[etree._Element, str, str]] = []
    previous_index = -1
    for key, source_id, work_id in ASSIGNED_ROOTS:
        matches = [
            (index, node)
            for index, node in enumerate(top)
            if node.get("id") == source_id
        ]
        if len(matches) != 1:
            raise ValueError(f"37c-203 assigned source root missing or duplicated: {source_id}")
        index, node = matches[0]
        if index <= previous_index:
            raise ValueError("37c-203 assigned source roots are not in source order")
        previous_index = index
        selected.append((node, key, work_id))
    return selected


def _target_attributes(
    policy: Mapping[str, Any],
    source: etree._Element,
    feature_id: str,
) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    projection = policy["projection"]
    tag = str(source.tag)
    tag_map = projection["tag_map"]
    if tag == "span" and source.get("lang"):
        target_tag = str(projection["language_span_tag"])
    else:
        target_tag = str(tag_map.get(tag, ""))
    if not target_tag:
        raise ValueError(f"37c-203 source element lacks a projection: {tag}")
    attrs: dict[str, str] = {"xml:id": feature_id}
    dispositions: list[dict[str, str]] = []
    rend_tokens: list[str] = []
    if tag in ("div1", "div2", "div3", "div"):
        attrs["type"] = str(
            projection["derived_attributes"]["div_type_template"].format(
                source_tag=tag
            )
        )
    if tag == "span" and not source.get("lang"):
        attrs["type"] = str(projection["derived_attributes"]["plain_span_type"])
    for derived_tag, rend in projection["derived_attributes"]["source_tag_rend"].items():
        if tag == derived_tag and rend:
            rend_tokens.append(str(rend))
    for name, value in source.attrib.items():
        rule = policy["attribute_rules"].get(name)
        if not isinstance(rule, Mapping) or tag not in rule.get("source_tags", ()):
            raise ValueError(
                f"37c-203 source attribute lacks a declared disposition: {tag}@{name}"
            )
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
            rend_tokens.append(f"class={value}")
        elif name == "style":
            destination = "@rend"
            method = "exact-source-style-token-in-rend"
            rend_tokens.append(f"style={value}")
        elif name == "border":
            destination = "@rend"
            method = "exact-source-border-token-in-rend"
            rend_tokens.append(f"border={value}")
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
        if name == "lang":
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
    if rend_tokens:
        attrs["rend"] = "; ".join(rend_tokens)
    if tag == "scripRef":
        attrs["type"] = "scripture"
    return target_tag, attrs, dispositions


def _append(
    policy: Mapping[str, Any],
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, Any]],
    state: list[int],
    parent_feature_id: str | None,
    source_root_id: str,
    work_id: str,
    source_child_ordinal: int,
) -> None:
    if not isinstance(source.tag, str) or source.tag not in SUPPORTED_TAGS:
        raise ValueError(f"37c-203 unsupported assigned source element: {source.tag!r}")
    state[0] += 1
    ordinal = state[0]
    feature_id = f"hodge-systematic-theology-vol-1-feature-{ordinal:06d}"
    target_tag, attrs, dispositions = _target_attributes(policy, source, feature_id)
    target = tei_el(target_tag, attrs)
    target.text = source.text
    parent.append(target)
    source_title = source.get("title") if source.tag in {"div1", "div2", "div3", "div"} else None
    if source_title is not None:
        target.append(tei_el("head", text=source_title))
    row: dict[str, Any] = {
        "attribute_dispositions": dispositions,
        "child_ordinal": source_child_ordinal,
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
        "source_title_head": source_title,
        "source_xml_id": source.get("id"),
        "tail_text_length": len((source.tail or "").encode("utf-8")),
        "tail_text_sha256": _sha((source.tail or "").encode("utf-8")),
        "tei_attributes": attrs,
        "tei_tag": target_tag,
        "tei_xml_id": attrs["xml:id"],
        "work_id": work_id,
    }
    rows.append(row)
    for child_ordinal, child in enumerate(source, 1):
        if not isinstance(child.tag, str):
            raise ValueError("37c-203 assigned source contains a non-element child")
        _append(
            policy,
            child,
            target,
            rows,
            state,
            feature_id,
            source_root_id,
            work_id,
            child_ordinal,
        )
    target.tail = source.tail


def _header(
    tree: etree._ElementTree, config: Mapping[str, Any], source_sha256: str
) -> etree._Element:
    title_nodes = tree.xpath(
        "/ThML/ThML.head/electronicEdInfo/DC/DC.Title[not(@sub)]/text()"
    )
    title = "".join(str(value) for value in title_nodes)
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
    bibl.append(
        tei_el(
            "idno",
            {"type": "CCEL-XML-url"},
            str(config["source_url"]),
        )
    )
    bibl.append(
        tei_el("idno", {"type": "CCEL-path"}, "/ccel/hodge/theology1.html")
    )
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
    bibl.append(
        tei_el(
            "note",
            {"type": "source-attribution"},
            "Sourced via CCEL.org.",
        )
    )
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


def _accountability(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    selected: list[tuple[etree._Element, str, str]],
    rows: list[dict[str, Any]],
    assigned_census: dict[str, Any],
) -> dict[str, Any]:
    complete_census = _census(list(tree.getroot().iter()))
    root_accounting = _root_accounting(tree, set(ASSIGNED_ROOT_IDS))
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
        if cursor + count > len(rows):
            raise ValueError("37c-203 crosswalk root boundary drift")
        cursor += count
    if cursor != len(rows):
        raise ValueError("37c-203 crosswalk root count drift")
    source_authority = source_manifest.record["authorities"]
    primary = next(
        item
        for item in source_authority
        if isinstance(item, Mapping) and item.get("name") == "retained-hodge-vol-1"
    )
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
                "bytes": primary["bytes"],
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
        "root_accounting": root_accounting,
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


def _provenance(
    source_manifest: SourceManifest,
    tree: etree._ElementTree,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    witness_inventory = json.loads(
        source_manifest.authority_path("witness-inventory").read_bytes()
    )
    permission_path = source_manifest.authority_path("ccel-permission-evidence")
    permission_bytes = permission_path.read_bytes()
    metadata = _source_metadata(tree)
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
                "metadata": metadata,
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


def _unresolved() -> bytes:
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


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != "ocd-37c203-hodge-systematic-theology-vol-1-ccel-theology1":
        raise ValueError("37c-203 source manifest identity drift")
    config = _source_config(source_manifest)
    profile = _profile(source_manifest)
    policy = _policy(source_manifest)
    primary = source_manifest.authority_path("retained-hodge-vol-1")
    content = primary.read_bytes()
    if len(content) != SOURCE_BYTES or _sha(content) != SOURCE_SHA256:
        raise ValueError("37c-203 retained source bytes or hash drift")
    tree = _source_tree(primary)
    selected = _selected(tree, source_manifest)
    assigned_nodes = [node for root, _key, _work_id in selected for node in root.iter()]
    assigned_census = _census(assigned_nodes)
    if assigned_census != profile["assigned_census"]:
        raise ValueError("37c-203 assigned source census drift")
    if {
        root.get("id"): sum(1 for _ in root.iter()) for root, _key, _work_id in selected
    } != profile["assigned_root_counts"]:
        raise ValueError("37c-203 assigned root feature counts drift")
    root = _header(tree, config, SOURCE_SHA256)
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "hodge-systematic-theology-vol-1-body"})
    text.append(body)
    root.append(text)
    rows: list[dict[str, Any]] = []
    state = [0]
    for source_root, key, work_id in selected:
        _append(
            policy,
            source_root,
            body,
            rows,
            state,
            None,
            source_root.get("id") or "",
            work_id,
            TOP_LEVEL_IDS.index(source_root.get("id")) + 1,
        )
    if len(rows) != assigned_census["elements"]:
        raise ValueError("37c-203 produced source feature count drift")
    accountability = _accountability(
        source_manifest, tree, selected, rows, assigned_census
    )
    provenance = _provenance(source_manifest, tree, config)
    readme = source_manifest.authority_path("attribution-readme").read_text(
        encoding="utf-8"
    )
    return {
        "README.source.md": readme.encode("utf-8"),
        "content.tei.xml": etree.tostring(
            root, encoding="UTF-8", xml_declaration=True, pretty_print=False
        ),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": _unresolved(),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
