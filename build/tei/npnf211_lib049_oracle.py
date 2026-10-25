"""Producer-independent LIB-049 NPNF211 retained-source oracle."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-npnf211-lib049-source-to-tei-oracle"
ORACLE_VERSION = "14"
SOURCE_SHA256 = "4ca2fa69fc584c8a697884454a3d95453b044e7548b48ff44a1d95605741a5b2"
SOURCE_BYTES = 4_045_340
SOURCE_PATH = "raw/ccel/npnf2/npnf211.xml"
VALIDATOR_CLOSURE_PATHS = (
    "ocd_kernel/__init__.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "build/tei/npnf211_lib049_oracle.py",
)
ASSIGNED = (
    ("ii", "sulpitius-severus-selected-works"),
    ("iii", "vincent-of-lerins-commonitory"),
    ("iv", "john-cassian-selected-works"),
)
EXPECTED_COUNTS = {
    "div1": 3, "div2": 50, "div3": 92, "div4": 1061, "h1": 8, "h2": 26,
    "h3": 69, "h4": 1169, "h5": 2, "h6": 8, "hr": 19, "i": 777,
    "note": 2684, "p": 5129, "pb": 587, "scripRef": 1803, "span": 1442,
    "sup": 2, "table": 1, "td": 12, "tr": 6,
}
EXPECTED_CENSUS = {
    "elements": 14_950, "attributes": 34_639, "text_nodes": 10_553,
    "tail_nodes_in_scope": 11_893, "characters": 2_832_630,
    "non_ascii_characters": 13_199, "notes": 2_684, "page_breaks": 587,
    "scripture_references": 1_803, "comments": 0, "processing_instructions": 0,
}
TAG_MAP = {
    "div1": "div", "div2": "div", "div3": "div", "div4": "div",
    "h1": "ab", "h2": "ab", "h3": "ab", "h4": "ab", "h5": "ab", "h6": "ab",
    "hr": "milestone", "i": "hi", "note": "note", "p": "p", "pb": "pb",
    "scripRef": "ref", "span": "seg", "sup": "hi", "table": "table",
    "tr": "row", "td": "cell",
}
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
Q = lambda name: f"{{{TEI_NS}}}{name}"
TEI_TITLE = "NPNF-211. Sulpitius Severus, Vincent of Lerins, John Cassian"
TEI_AUTHORS = "Sulpitius Severus; Vincent of Lérins; John Cassian"
SOURCE_URL = "https://www.ccel.org/ccel/schaff/npnf211.html"
PRINT_SOURCE = "Retained ThML head: Edinburgh, T & T Clark; no retained print date or print collation."
RIGHTS_STATEMENT = (
    "The retained CCEL ThML head states Public Domain. This records the source-supplied "
    "claim only; human rights review, textual acceptance, and publication authorization are absent."
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _strict(content: bytes, label: str) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"{label} duplicate JSON key")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not a JSON object")
    return value


def _parse_source(path: Path) -> etree._ElementTree:
    return etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True))


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _source_roots(tree: etree._ElementTree) -> list[etree._Element]:
    root = tree.getroot()
    if root.tag != "ThML" or root.attrib or root.nsmap:
        raise ValueError("source shell drift")
    body = root.find("ThML.body")
    if body is None:
        raise ValueError("source body missing")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in top) != ("i", "ii", "iii", "iv", "v"):
        raise ValueError("source top-level order drift")
    by_id = {str(node.get("id")): node for node in top}
    return [by_id[scope] for scope, _work_id in ASSIGNED]


def _source_features(roots: list[etree._Element]) -> list[tuple[etree._Element, etree._Element]]:
    return [(node, root) for root in roots for node in root.iter() if isinstance(node.tag, str)]


def _expected_topology(
    source_features: list[tuple[etree._Element, etree._Element]],
) -> list[dict[str, object]]:
    by_node: dict[int, tuple[str, str]] = {}
    rows: list[dict[str, object]] = []
    root_ordinal = 0
    for ordinal, (source, source_root) in enumerate(source_features, start=1):
        feature_id = f"npnf211-feature-{ordinal:05d}"
        attrs, _dispositions = _expected_attrs(source, ordinal)
        if source is source_root:
            root_ordinal += 1
            row = {
                "tei_parent_id": "npnf211-assigned-body",
                "tei_child_ordinal": root_ordinal,
                "parent_feature_id": None,
            }
        else:
            parent = source.getparent()
            if parent is None or id(parent) not in by_node:
                raise ValueError("independent source topology is incomplete")
            parent_feature_id, parent_tei_id = by_node[id(parent)]
            preceding = sum(
                1
                for child in parent
                if isinstance(child.tag, str) and child is not source and child.getparent().index(child) < parent.index(source)
            )
            projected_title = str(parent.tag).startswith("div") and parent.get("title") is not None
            row = {
                "tei_parent_id": parent_tei_id,
                "tei_child_ordinal": 1 + preceding + int(projected_title),
                "parent_feature_id": parent_feature_id,
            }
        by_node[id(source)] = (feature_id, attrs["xml:id"])
        rows.append(row)
    return rows


def _expected_tag(node: etree._Element) -> str:
    if node.tag == "span" and node.get("lang"):
        return "foreign"
    return TAG_MAP[str(node.tag)]


def _expected_attrs(node: etree._Element, ordinal: int) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = node.get("id")
    attrs: dict[str, str] = {"xml:id": "npnf211-" + (_safe_id(source_id) if source_id else f"feature-{ordinal:05d}")}
    dispositions: list[dict[str, str]] = []
    rend: list[str] = []
    tag = str(node.tag)
    for name, value in node.attrib.items():
        destination, method = "source-accountability", "preserved-exactly"
        if name == "id":
            destination, method = "@xml:id", "deterministic-prefix"
        elif name == "n":
            attrs["n"], destination = value, "@n"
        elif name == "href" and tag == "pb":
            attrs["facs"], destination = value, "@facs"
        elif name == "passage" and tag == "scripRef":
            attrs["cRef"], destination = value, "@cRef"
        elif name == "osisRef" and tag == "scripRef":
            attrs["target"], destination = value, "@target"
        elif name == "lang" and tag == "span":
            attrs["xml:lang"] = {"EL": "grc", "FR": "fr", "HE": "he"}.get(value, value.lower())
            destination, method = "@xml:lang", "declared-language-code-map"
        elif name in {"class", "style", "dir", "border"}:
            rend.append(f"{name}:{value}")
            destination, method = "@rend", "labelled-source-rendering"
        elif name == "title" and tag.startswith("div"):
            destination = "child::head[1]"
        dispositions.append({"source_attribute": name, "source_value": value, "destination": destination, "method": method})
    if tag == "i":
        rend.append("italic")
    elif tag == "sup":
        rend.append("superscript")
    if rend:
        attrs["rend"] = ";".join(rend)
    if tag == "scripRef":
        attrs["type"] = "scripture"
    elif tag == "hr":
        attrs["unit"] = "source-horizontal-rule"
    elif tag.startswith("h") and tag[1:].isdigit():
        attrs["type"] = f"source-{tag}"
    return attrs, dispositions


def _normalized_attrs(node: etree._Element) -> dict[str, str]:
    return {("xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key): value for key, value in node.attrib.items()}


def _selector(node: etree._Element) -> str:
    parts: list[str] = []
    current: etree._Element | None = node
    while current is not None and current.tag != "ThML.body":
        if not isinstance(current.tag, str):
            break
        parent = current.getparent()
        if parent is None:
            break
        peers = [child for child in parent if isinstance(child.tag, str) and child.tag == current.tag]
        parts.append(f"{current.tag}[{peers.index(current) + 1}]")
        current = parent
    return "ThML.body/" + "/".join(reversed(parts))


def _census(features: list[tuple[etree._Element, etree._Element]]) -> dict[str, int]:
    return {
        "elements": len(features),
        "attributes": sum(len(node.attrib) for node, _root in features),
        "text_nodes": sum(node.text is not None for node, _root in features),
        "tail_nodes_in_scope": sum(node.tail is not None and node is not root for node, root in features),
        "characters": sum(len(node.text or "") + (0 if node is root else len(node.tail or "")) for node, root in features),
        "non_ascii_characters": sum(sum(ord(char) > 127 for char in (node.text or "") + ("" if node is root else (node.tail or ""))) for node, root in features),
        "notes": sum(node.tag == "note" for node, _root in features),
        "page_breaks": sum(node.tag == "pb" for node, _root in features),
        "scripture_references": sum(node.tag == "scripRef" for node, _root in features),
        "comments": 0,
        "processing_instructions": 0,
    }


def _head_inventory(tree: etree._ElementTree) -> list[dict[str, object]]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("source head missing")
    return [
        {"ordinal": ordinal, "selector": tree.getpath(node), "tag": node.tag, "attributes": dict(node.attrib), "direct_text": node.text or "", "tail_text": node.tail or ""}
        for ordinal, node in enumerate((item for item in head.iter() if isinstance(item.tag, str)), start=1)
    ]


def _metadata(tree: etree._ElementTree) -> dict[str, object]:
    def values(tag: str) -> list[dict[str, object]]:
        return [{"text": "".join(node.itertext()), "attributes": dict(node.attrib)} for node in tree.xpath(f"//{tag}")]
    return {"published": values("published"), "titles": values("DC.Title"), "creators": values("DC.Creator"), "publishers": values("DC.Publisher"), "dates": values("DC.Date"), "identifiers": values("DC.Identifier"), "languages": values("DC.Language"), "rights": values("DC.Rights")}


def _complete_census(tree: etree._ElementTree) -> dict[str, int]:
    nodes = [node for node in tree.getroot().iter() if isinstance(node.tag, str)]
    return {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes_in_scope": sum(node.tail is not None for node in nodes),
        "characters": sum(len(node.text or "") + len(node.tail or "") for node in nodes),
        "non_ascii_characters": sum(sum(ord(char) > 127 for char in (node.text or "") + (node.tail or "")) for node in nodes),
        "notes": sum(node.tag == "note" for node in nodes),
        "page_breaks": sum(node.tag == "pb" for node in nodes),
        "scripture_references": sum(node.tag == "scripRef" for node in nodes),
        "comments": 0,
        "processing_instructions": 0,
    }


def _document_accounting(source_tree: etree._ElementTree, source_bytes: bytes) -> dict[str, object]:
    declaration = re.match(br"\A(<\?xml[^?]*\?>)", source_bytes)
    if declaration is None:
        raise ValueError("retained source XML declaration missing")
    root = source_tree.getroot()
    preceding: list[etree._Element] = []
    node = root.getprevious()
    while node is not None:
        preceding.append(node)
        node = node.getprevious()
    preceding.reverse()
    following: list[etree._Element] = []
    node = root.getnext()
    while node is not None:
        following.append(node)
        node = node.getnext()
    if following:
        raise ValueError("retained source post-root node representation is undefined")
    return {
        "xml_declaration": declaration.group(1).decode("utf-8"),
        "standalone": bool(source_tree.docinfo.standalone),
        "doctype": source_tree.docinfo.doctype,
        "pre_root_comments": [node.text or "" for node in preceding if isinstance(node, etree._Comment)],
        "pre_root_processing_instructions": [
            {"target": node.target, "text": node.text or ""}
            for node in preceding
            if isinstance(node, etree._ProcessingInstruction)
        ],
        "post_root_nodes": [],
        "root_tag": root.tag,
        "root_attributes": dict(root.attrib),
        "root_namespace_declarations": {("" if key is None else key): value for key, value in root.nsmap.items()},
        "head_inventory": _head_inventory(source_tree),
        "metadata": _metadata(source_tree),
    }


def _top_level_accounting(source_tree: etree._ElementTree) -> list[dict[str, object]]:
    body = source_tree.getroot().find("ThML.body")
    if body is None:
        raise ValueError("source body missing")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    assigned_ids = {scope for scope, _work_id in ASSIGNED}
    reasons = {
        "i": "retained title page outside assigned work roots; retained as metadata and edition evidence",
        "ii": "complete assigned Sulpitius Severus subtree represented",
        "iii": "complete assigned Vincent of Lérins subtree represented",
        "iv": "complete assigned John Cassian subtree represented",
        "v": "retained indexes outside assigned work roots",
    }
    return [
        {
            "ordinal": ordinal,
            "div1_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": "assigned-work-represented" if node.get("id") in assigned_ids else "source-evidence-outside-work-projection",
            "reason": reasons[str(node.get("id"))],
            "subtree_sha256": _sha(etree.tostring(node, encoding="UTF-8", with_tail=False)),
        }
        for ordinal, node in enumerate(top, start=1)
    ]


def _check_shell(content: bytes) -> etree._ElementTree:
    declaration = b"<?xml version='1.0' encoding='UTF-8'?>\n"
    if not content.startswith(declaration + b'<TEI xmlns="http://www.tei-c.org/ns/1.0"'):
        raise ValueError("TEI prolog drift")
    if not content.endswith(b"</TEI>"):
        raise ValueError("TEI terminal root boundary drift")
    if content.count(b'xmlns="http://www.tei-c.org/ns/1.0"') != 1 or b"xmlns:" in content:
        raise ValueError("TEI namespace declaration drift")
    try:
        tree = etree.ElementTree(etree.fromstring(content, etree.XMLParser(remove_comments=False, no_network=True)))
    except etree.XMLSyntaxError as exc:
        raise ValueError("TEI well-formedness failure") from exc
    if tree.xpath("//comment()") or tree.xpath("//processing-instruction()"):
        raise ValueError("TEI comment or processing instruction invention")
    return tree


def _check_header(tree: etree._ElementTree) -> None:
    root = tree.getroot()
    headers = root.findall(Q("teiHeader"))
    if len(headers) != 1:
        raise ValueError("TEI metadata drift")
    header = headers[0]
    def one(path: str) -> etree._Element:
        values = header.xpath(path, namespaces={"tei": TEI_NS})
        if len(values) != 1:
            raise ValueError("TEI metadata drift")
        return values[0]
    if one("./tei:fileDesc/tei:titleStmt/tei:title").text != TEI_TITLE:
        raise ValueError("TEI metadata drift")
    if one("./tei:fileDesc/tei:titleStmt/tei:author").text != TEI_AUTHORS:
        raise ValueError("TEI metadata drift")
    if one("./tei:fileDesc/tei:titleStmt/tei:respStmt/tei:name").text != "Philip Schaff":
        raise ValueError("TEI metadata drift")
    if one("./tei:fileDesc/tei:publicationStmt/tei:publisher").text != "Open Christian Data":
        raise ValueError("TEI metadata drift")
    availability = one("./tei:fileDesc/tei:publicationStmt/tei:availability")
    if availability.get("status") != "restricted" or one("./tei:fileDesc/tei:publicationStmt/tei:availability/tei:p").text != RIGHTS_STATEMENT:
        raise ValueError("TEI rights drift")
    if one("./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr").get("target") != SOURCE_URL:
        raise ValueError("TEI metadata drift")
    if one("./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno").text != SOURCE_SHA256:
        raise ValueError("TEI metadata drift")
    if one("./tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note").text != PRINT_SOURCE:
        raise ValueError("TEI metadata drift")


def _check_body(source_features: list[tuple[etree._Element, etree._Element]], tree: etree._ElementTree) -> None:
    root = tree.getroot()
    if _normalized_attrs(root) != {"xml:id": "npnf211-lib049"}:
        raise ValueError("TEI shell structure drift")
    if [child.tag for child in root] != [Q("teiHeader"), Q("text")]:
        raise ValueError("TEI shell structure drift")
    text = root.find(Q("text"))
    if text is None or text.attrib or text.text not in {None, ""}:
        raise ValueError("TEI shell structure drift")
    body = text.find(Q("body"))
    if body is None or _normalized_attrs(body) != {"xml:id": "npnf211-assigned-body"} or body.text not in {None, ""}:
        raise ValueError("TEI shell structure drift")
    mapped = [node for node in body.iterdescendants() if isinstance(node.tag, str) and node.get(XML_ID)]
    if len(mapped) < len(source_features):
        raise ValueError("TEI source feature omission")
    if len(mapped) > len(source_features):
        raise ValueError("TEI source feature duplication or invention")
    expected_ids = []
    for ordinal, (source, source_root) in enumerate(source_features, start=1):
        attrs, _dispositions = _expected_attrs(source, ordinal)
        expected_ids.append(attrs["xml:id"])
    if [node.get(XML_ID) for node in mapped] != expected_ids:
        raise ValueError("TEI source feature reordering")
    topology = _expected_topology(source_features)
    for ordinal, ((source, source_root), candidate, expected_topology) in enumerate(zip(source_features, mapped, topology, strict=True), start=1):
        attrs, _dispositions = _expected_attrs(source, ordinal)
        parent = candidate.getparent()
        actual_topology = {
            "tei_parent_id": None if parent is None else parent.get(XML_ID),
            "tei_child_ordinal": 1 + sum(1 for child in parent if isinstance(child.tag, str) and child is not candidate and parent.index(child) < parent.index(candidate)) if parent is not None else 0,
            "parent_feature_id": expected_topology["parent_feature_id"],
        }
        if {key: actual_topology[key] for key in ("tei_parent_id", "tei_child_ordinal")} != {key: expected_topology[key] for key in ("tei_parent_id", "tei_child_ordinal")}:
            raise ValueError("TEI source topology drift")
        if candidate.tag != Q(_expected_tag(source)):
            raise ValueError("TEI source feature tag drift")
        if _normalized_attrs(candidate) != attrs:
            raise ValueError("TEI source attribute drift")
        if (candidate.text or "") != (source.text or ""):
            raise ValueError("TEI source direct text drift")
        expected_tail = "" if source is source_root else (source.tail or "")
        if (candidate.tail or "") != expected_tail:
            raise ValueError("TEI source tail text drift")
        title = source.get("title") if str(source.tag).startswith("div") else None
        heads = [child for child in candidate if child.tag == Q("head")]
        if title is not None:
            if len(heads) != 1 or heads[0].text != title or heads[0].attrib or len(heads[0]):
                raise ValueError("TEI source title projection drift")
        elif heads:
            raise ValueError("TEI source title invention")
    allowed_without_ids = [node for node in body.iterdescendants() if isinstance(node.tag, str) and not node.get(XML_ID)]
    if len(allowed_without_ids) != sum(str(source.tag).startswith("div") and source.get("title") is not None for source, _root in source_features) or any(node.tag != Q("head") for node in allowed_without_ids):
        raise ValueError("TEI surplus structure")


def _check_accountability(
    source_tree: etree._ElementTree,
    source_bytes: bytes,
    source_features: list[tuple[etree._Element, etree._Element]],
    candidate: CandidatePackage,
) -> None:
    account = _strict(candidate.member_bytes("source-accountability.json"), "source accountability")
    if account.get("contract") != "ocd-npnf211-lib049-source-accountability-v14" or account.get("profile_id") != "npnf211-lib049-three-work-v14":
        raise ValueError("source accountability identity drift")
    if account.get("feature_count") != 14_950 or account.get("attribute_count") != 34_639 or account.get("feature_counts") != EXPECTED_COUNTS:
        raise ValueError("source accountability coverage drift")
    if any(account.get(name) != 0 for name in ("omitted_feature_count", "duplicate_feature_count", "unresolved_feature_count")):
        raise ValueError("source accountability incomplete coverage")
    if account.get("table_census") != {"tables": 1, "rows": 6, "cells": 12}:
        raise ValueError("source accountability table drift")
    crosswalk = account.get("crosswalk")
    if not isinstance(crosswalk, list) or len(crosswalk) != len(source_features):
        raise ValueError("source accountability crosswalk coverage drift")
    topology = _expected_topology(source_features)
    for ordinal, ((source, source_root), row, expected_topology) in enumerate(zip(source_features, crosswalk, topology, strict=True), start=1):
        attrs, dispositions = _expected_attrs(source, ordinal)
        expected_tail = "" if source is source_root else (source.tail or "")
        expected = {
            "feature_id": f"npnf211-feature-{ordinal:05d}",
            "source_selector": _selector(source),
            "source_tag": source.tag,
            "source_xml_id": source.get("id"),
            "attributes": dict(source.attrib),
            "direct_text": source.text or "",
            "tail_text": expected_tail,
            "excluded_root_tail": (source.tail or "") if source is source_root else "",
            "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
            "tail_text_sha256": _sha(expected_tail.encode("utf-8")),
            "tei_tag": _expected_tag(source),
            "tei_xml_id": attrs["xml:id"],
            **expected_topology,
            "tei_attributes": attrs,
            "attribute_dispositions": dispositions,
            "disposition": "represented",
            "tei_selector": f"#{attrs['xml:id']}",
            "source_title_head": source.get("title") if str(source.tag).startswith("div") else None,
        }
        if source is source_root:
            scope = str(source.get("id"))
            work_id = dict(ASSIGNED)[scope]
            expected["work_id"] = work_id
            expected["source_root_id"] = scope
        if any(row.get(key) != expected[key] for key in ("tei_parent_id", "tei_child_ordinal", "parent_feature_id")):
            raise ValueError("source accountability topology drift")
        if row != expected:
            raise ValueError("source accountability crosswalk drift")
    if account.get("document_accounting") != _document_accounting(source_tree, source_bytes):
        raise ValueError("source accountability document shell drift")
    expected_member = {"path": SOURCE_PATH, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256, "disposition": "sole retained member included"}
    expected_member_accounting = [{"path": SOURCE_PATH, "disposition": "included; every retained document region explicitly included or excluded below"}]
    if account.get("source_member") != expected_member or account.get("member_accounting") != expected_member_accounting:
        raise ValueError("source accountability member accounting drift")
    source_census = account.get("source_census")
    complete_census = _complete_census(source_tree)
    expected_census = {
        "complete_document": complete_census,
        "assigned_scope": EXPECTED_CENSUS,
        "excluded_shell_head_front_and_indexes": {key: complete_census[key] - EXPECTED_CENSUS[key] for key in EXPECTED_CENSUS},
    }
    if source_census != expected_census:
        raise ValueError("source accountability census drift")
    if account.get("top_level_division_accounting") != _top_level_accounting(source_tree):
        raise ValueError("source accountability top-level disposition drift")
    expected_keys = {
        "contract", "schema", "profile_id", "source_scope", "source_member",
        "document_accounting", "member_accounting", "source_census",
        "assigned_work_count", "feature_count", "attribute_count", "feature_counts",
        "omitted_feature_count", "duplicate_feature_count", "unresolved_feature_count",
        "table_census", "top_level_division_accounting", "crosswalk",
    }
    if set(account) != expected_keys or account.get("schema") != "npnf211-lib049.source-accountability.schema.json" or account.get("source_scope") != "complete retained ThML.body direct div1 roots ii, iii, and iv; root tails excluded as outside each subtree" or account.get("assigned_work_count") != 3:
        raise ValueError("source accountability shape drift")


def _check_evidence(source_tree: etree._ElementTree, candidate: CandidatePackage) -> None:
    provenance = _strict(candidate.member_bytes("provenance.json"), "provenance")
    if provenance.get("status") != "nonaccepted" or provenance.get("retained_metadata") != _metadata(source_tree):
        raise ValueError("provenance metadata drift")
    works = provenance.get("works")
    if not isinstance(works, list) or [(row.get("source_root_id"), row.get("work_id")) for row in works] != list(ASSIGNED):
        raise ValueError("provenance work assignment drift")
    if any((row.get("human_review"), row.get("accepted_ir"), row.get("publication")) != ("required", "not_accepted", "not_ready") for row in works):
        raise ValueError("provenance state drift")
    rights = provenance.get("rights")
    if not isinstance(rights, dict) or rights.get("retained_statement") != "Public Domain" or rights.get("publication_state") != "not_ready":
        raise ValueError("provenance rights drift")
    unresolved = [json.loads(line) for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines() if line]
    if [row.get("id") for row in unresolved] != ["npnf211-edition-witness", "npnf211-rights-publication", "npnf211-human-acceptance"] or any(row.get("status") != "unresolved" for row in unresolved):
        raise ValueError("unresolved evidence drift")
    readme = candidate.member_bytes("README.source.md").decode("utf-8")
    for value in (SOURCE_SHA256, "Public Domain", "publication remains `not_ready`", "Human textual acceptance"):
        if value not in readme:
            raise ValueError("source attribution README drift")


def _closure_records() -> list[dict[str, object]]:
    repository_root = Path(__file__).resolve(strict=True).parents[2]
    rows = []
    for logical in VALIDATOR_CLOSURE_PATHS:
        content = (repository_root / logical).read_bytes()
        rows.append({"path": logical, "bytes": len(content), "sha256": _sha(content)})
    return rows


def _closure_digest(rows: list[dict[str, object]]) -> str:
    return _sha(_canonical({"contract": "ocd-first-party-import-closure-v1", "files": rows}))


def _runtime() -> str:
    return f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"


def _authority(source_manifest: SourceManifest, role: str) -> str:
    values = [item for item in source_manifest.record["authorities"] if item["role"] == role]
    if len(values) != 1:
        raise ValueError(f"authority role {role} is not unique")
    return str(values[0]["sha256"])


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    source_path = source_manifest.authority_path("retained-thml")
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("wrong retained source bytes")
    source_tree = _parse_source(source_path)
    roots = _source_roots(source_tree)
    source_features = _source_features(roots)
    counts = dict(sorted(Counter(str(node.tag) for node, _root in source_features).items()))
    if counts != EXPECTED_COUNTS or _census(source_features) != EXPECTED_CENSUS:
        raise ValueError("independent retained source census drift")

    content = candidate.member_bytes("content.tei.xml")
    candidate_tree = _check_shell(content)
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    xsd = etree.XMLSchema(etree.parse(str(xsd_path)))
    if not xsd.validate(candidate_tree):
        raise ValueError("TEI P5 schema failure")
    _check_header(candidate_tree)
    _check_body(source_features, candidate_tree)
    _check_accountability(source_tree, source_bytes, source_features, candidate)
    accountability_schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "source accountability schema")
    account = _strict(candidate.member_bytes("source-accountability.json"), "source accountability")
    errors = sorted(Draft202012Validator(accountability_schema).iter_errors(account), key=str)
    if errors:
        raise ValueError(f"source accountability schema failure: {errors[0].message}")
    _check_evidence(source_tree, candidate)

    validator = source_manifest.record["validator"]
    implementation_sha = _sha(Path(__file__).read_bytes())
    closure = _closure_records()
    closure_authority = source_manifest.authority_path("validator-first-party-import-closure")
    recorded_document = _strict(closure_authority.read_bytes(), "validator first-party import closure")
    if recorded_document != {"contract": "ocd-first-party-import-closure-v1", "files": closure}:
        raise ValueError("oracle first-party import closure drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": _closure_digest(closure),
        "runtime": _runtime(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _authority(source_manifest, "complete-source-feature-profile"),
        "package_schema_sha256": _authority(source_manifest, "candidate-package-schema"),
        "source_sha256": SOURCE_SHA256,
        "xsd_sha256": _authority(source_manifest, "tei-validation-schema"),
        "policy_sha256": _authority(source_manifest, "independent-validation-policy"),
        "result_sha256": "",
        "findings": [],
    }
    if validator["implementation_sha256"] != implementation_sha or _sha(closure_authority.read_bytes()) != result["import_closure_sha256"] or validator["import_closure_sha256"] != result["import_closure_sha256"]:
        raise ValueError("oracle implementation or closure binding drift")
    digest_record = {key: value for key, value in result.items() if key != "result_sha256"}
    result["result_sha256"] = _sha(_canonical(digest_record))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
