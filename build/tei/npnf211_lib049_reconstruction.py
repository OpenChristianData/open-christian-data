"""Source-first LIB-049 NPNF211 reconstruction producer."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest
from ocd_kernel.tei.writer import XML_ID, XML_LANG, stamp_header, tei_el


CONVERTER_ID = "ocd-npnf211-lib049-assigned-works-to-tei"
CONVERTER_VERSION = "14"
SOURCE_PATH = "raw/ccel/npnf2/npnf211.xml"
SOURCE_SHA256 = "4ca2fa69fc584c8a697884454a3d95453b044e7548b48ff44a1d95605741a5b2"
SOURCE_BYTES = 4_045_340
SOURCE_ID = "ccel-npnf211-lib049-retained-xml"
PRODUCER_CLOSURE_PATHS = (
    "ocd_kernel/__init__.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/tei/__init__.py",
    "ocd_kernel/tei/normalization.py",
    "ocd_kernel/tei/projection_profile.py",
    "ocd_kernel/tei/writer.py",
    "build/tei/npnf211_lib049_reconstruction.py",
)
ASSIGNED = (
    ("ii", "sulpitius-severus-selected-works"),
    ("iii", "vincent-of-lerins-commonitory"),
    ("iv", "john-cassian-selected-works"),
)
TOP_LEVEL = ("i", "ii", "iii", "iv", "v")
TAG_MAP = {
    "div1": "div", "div2": "div", "div3": "div", "div4": "div",
    "h1": "ab", "h2": "ab", "h3": "ab", "h4": "ab", "h5": "ab", "h6": "ab",
    "hr": "milestone", "i": "hi", "note": "note", "p": "p", "pb": "pb",
    "scripRef": "ref", "span": "seg", "sup": "hi", "table": "table",
    "tr": "row", "td": "cell",
}
EXPECTED_COUNTS = {
    "div1": 3, "div2": 50, "div3": 92, "div4": 1061, "h1": 8, "h2": 26,
    "h3": 69, "h4": 1169, "h5": 2, "h6": 8, "hr": 19, "i": 777,
    "note": 2684, "p": 5129, "pb": 587, "scripRef": 1803, "span": 1442,
    "sup": 2, "table": 1, "td": 12, "tr": 6,
}
EXPECTED_CENSUS = {
    "elements": 14_950,
    "attributes": 34_639,
    "text_nodes": 10_553,
    "tail_nodes_in_scope": 11_893,
    "characters": 2_832_630,
    "non_ascii_characters": 13_199,
    "notes": 2_684,
    "page_breaks": 587,
    "scripture_references": 1_803,
    "comments": 0,
    "processing_instructions": 0,
}
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


def _closure_records() -> list[dict[str, object]]:
    repository_root = Path(__file__).resolve(strict=True).parents[2]
    rows = []
    for logical in PRODUCER_CLOSURE_PATHS:
        content = (repository_root / logical).read_bytes()
        rows.append({"path": logical, "bytes": len(content), "sha256": _sha(content)})
    return rows


def _closure_digest(rows: list[dict[str, object]]) -> str:
    return _sha(_canonical({"contract": "ocd-first-party-import-closure-v1", "files": rows}))


def _parse(path: Path) -> etree._ElementTree:
    return etree.parse(
        str(path),
        etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True),
    )


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def _structure(tree: etree._ElementTree) -> tuple[list[etree._Element], list[etree._Element]]:
    root = tree.getroot()
    if root.tag != "ThML" or root.attrib or root.nsmap:
        raise ValueError("retained NPNF211 root or namespace drifted")
    body = root.find("ThML.body")
    if body is None:
        raise ValueError("retained NPNF211 source has no ThML.body")
    top = [node for node in body if isinstance(node.tag, str) and node.tag == "div1"]
    if tuple(node.get("id") for node in top) != TOP_LEVEL:
        raise ValueError("retained NPNF211 top-level division order drifted")
    by_id = {str(node.get("id")): node for node in top}
    selected = [by_id[scope] for scope, _work_id in ASSIGNED]
    return top, selected


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


def _target_tag(source: etree._Element) -> str:
    if source.tag == "span" and source.get("lang"):
        return "foreign"
    return TAG_MAP[str(source.tag)]


def _tei_attrs(source: etree._Element, number: int) -> tuple[dict[str, str], list[dict[str, str]]]:
    source_id = source.get("id")
    attrs: dict[str, str] = {
        "xml:id": "npnf211-" + (_safe_id(source_id) if source_id else f"feature-{number:05d}")
    }
    dispositions: list[dict[str, str]] = []
    rend: list[str] = []
    tag = str(source.tag)
    for name, value in source.attrib.items():
        destination = "source-accountability"
        method = "preserved-exactly"
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
        dispositions.append({
            "source_attribute": name,
            "source_value": value,
            "destination": destination,
            "method": method,
        })
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


def _append(
    source: etree._Element,
    parent: etree._Element,
    rows: list[dict[str, object]],
    parent_feature_id: str | None,
    *,
    root_of_assigned_scope: bool = False,
) -> None:
    number = len(rows) + 1
    feature_id = f"npnf211-feature-{number:05d}"
    attrs, dispositions = _tei_attrs(source, number)
    target = tei_el(_target_tag(source), attrs)
    title = source.get("title") if str(source.tag).startswith("div") else None
    if title is not None:
        target.append(tei_el("head", text=title))
    target.text = source.text or ""
    source_tail = "" if root_of_assigned_scope else (source.tail or "")
    target.tail = source_tail
    child_ordinal = 1 + sum(1 for child in parent if isinstance(child.tag, str))
    parent.append(target)
    rows.append({
        "feature_id": feature_id,
        "source_selector": _selector(source),
        "source_tag": source.tag,
        "source_xml_id": source.get("id"),
        "attributes": dict(source.attrib),
        "direct_text": source.text or "",
        "tail_text": source_tail,
        "excluded_root_tail": source.tail or "" if root_of_assigned_scope else "",
        "direct_text_sha256": _sha((source.text or "").encode("utf-8")),
        "tail_text_sha256": _sha(source_tail.encode("utf-8")),
        "tei_tag": _target_tag(source),
        "tei_xml_id": target.get(XML_ID),
        "tei_parent_id": parent.get(XML_ID),
        "tei_child_ordinal": child_ordinal,
        "tei_attributes": {
            ("xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else key): value
            for key, value in target.attrib.items()
        },
        "attribute_dispositions": dispositions,
        "disposition": "represented",
        "tei_selector": f"#{target.get(XML_ID)}",
        "parent_feature_id": parent_feature_id,
        "source_title_head": title,
    })
    for child in source:
        if not isinstance(child.tag, str):
            raise ValueError("assigned NPNF211 scope unexpectedly contains comment or processing instruction")
        if child.tag not in TAG_MAP:
            raise ValueError(f"unsupported retained source element {child.tag!r}")
        _append(child, target, rows, feature_id)


def _census(nodes: list[etree._Element], selected: list[etree._Element] | None = None) -> dict[str, int]:
    selected_set = {id(node) for node in (selected or [])}
    return {
        "elements": len(nodes),
        "attributes": sum(len(node.attrib) for node in nodes),
        "text_nodes": sum(node.text is not None for node in nodes),
        "tail_nodes_in_scope": sum(node.tail is not None and id(node) not in selected_set for node in nodes),
        "characters": sum(len(node.text or "") + (0 if id(node) in selected_set else len(node.tail or "")) for node in nodes),
        "non_ascii_characters": sum(sum(ord(char) > 127 for char in (node.text or "") + ("" if id(node) in selected_set else (node.tail or ""))) for node in nodes),
        "notes": sum(node.tag == "note" for node in nodes),
        "page_breaks": sum(node.tag == "pb" for node in nodes),
        "scripture_references": sum(node.tag == "scripRef" for node in nodes),
        "comments": sum(isinstance(node, etree._Comment) for node in nodes),
        "processing_instructions": sum(isinstance(node, etree._ProcessingInstruction) for node in nodes),
    }


def _head_inventory(tree: etree._ElementTree) -> list[dict[str, object]]:
    head = tree.getroot().find("ThML.head")
    if head is None:
        raise ValueError("retained NPNF211 head missing")
    rows = []
    for ordinal, node in enumerate((item for item in head.iter() if isinstance(item.tag, str)), start=1):
        rows.append({
            "ordinal": ordinal,
            "selector": tree.getpath(node),
            "tag": node.tag,
            "attributes": dict(node.attrib),
            "direct_text": node.text or "",
            "tail_text": node.tail or "",
        })
    return rows


def _metadata(tree: etree._ElementTree) -> dict[str, object]:
    def values(tag: str) -> list[dict[str, object]]:
        return [{"text": "".join(node.itertext()), "attributes": dict(node.attrib)} for node in tree.xpath(f"//{tag}")]
    record = {
        "published": values("published"),
        "titles": values("DC.Title"),
        "creators": values("DC.Creator"),
        "publishers": values("DC.Publisher"),
        "dates": values("DC.Date"),
        "identifiers": values("DC.Identifier"),
        "languages": values("DC.Language"),
        "rights": values("DC.Rights"),
    }
    if record["titles"][0]["text"] != TEI_TITLE or record["rights"][0]["text"] != "Public Domain":
        raise ValueError("retained NPNF211 metadata or rights drifted")
    return record


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    closure = _closure_records()
    closure_authority = source_manifest.authority_path("converter-first-party-import-closure")
    try:
        recorded = json.loads(closure_authority.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("converter first-party import closure is not JSON") from exc
    expected_closure = {"contract": "ocd-first-party-import-closure-v1", "files": closure}
    if recorded != expected_closure or _sha(closure_authority.read_bytes()) != _closure_digest(closure):
        raise ValueError("converter first-party import closure drift")
    source = source_manifest.authority_path("retained-thml")
    source_bytes = source.read_bytes()
    if len(source_bytes) != SOURCE_BYTES or _sha(source_bytes) != SOURCE_SHA256:
        raise ValueError("retained NPNF211 authority drifted")
    tree = _parse(source)
    top, selected = _structure(tree)
    assigned_nodes = [node for division in selected for node in division.iter() if isinstance(node.tag, str)]
    counts = dict(sorted(Counter(str(node.tag) for node in assigned_nodes).items()))
    census = _census(assigned_nodes, selected)
    if counts != EXPECTED_COUNTS or census != EXPECTED_CENSUS:
        raise ValueError(f"assigned NPNF211 census drifted: {counts} {census}")

    root = tei_el("TEI", {"xml:id": "npnf211-lib049"})
    root.append(stamp_header(
        title=TEI_TITLE,
        author=TEI_AUTHORS,
        contributors=[{"name": "Philip Schaff", "role": "retained source editor"}],
        source_url=SOURCE_URL,
        source_sha256=SOURCE_SHA256,
        print_source=PRINT_SOURCE,
        rights_statement=RIGHTS_STATEMENT,
    ))
    text = tei_el("text")
    body = tei_el("body", {"xml:id": "npnf211-assigned-body"})
    text.append(body)
    root.append(text)
    crosswalk: list[dict[str, object]] = []
    for source_root, (scope, work_id) in zip(selected, ASSIGNED, strict=True):
        before = len(crosswalk)
        _append(source_root, body, crosswalk, None, root_of_assigned_scope=True)
        crosswalk[before]["work_id"] = work_id
        crosswalk[before]["source_root_id"] = scope

    complete_nodes = [node for node in tree.getroot().iter() if isinstance(node.tag, str)]
    complete_census = _census(complete_nodes)
    excluded_census = {key: complete_census[key] - census[key] for key in census}
    top_accounting = []
    assigned_ids = {scope for scope, _work_id in ASSIGNED}
    reasons = {
        "i": "retained title page outside assigned work roots; retained as metadata and edition evidence",
        "ii": "complete assigned Sulpitius Severus subtree represented",
        "iii": "complete assigned Vincent of Lérins subtree represented",
        "iv": "complete assigned John Cassian subtree represented",
        "v": "retained indexes outside assigned work roots",
    }
    for ordinal, node in enumerate(top, start=1):
        top_accounting.append({
            "ordinal": ordinal,
            "div1_id": node.get("id"),
            "title": node.get("title", ""),
            "disposition": "assigned-work-represented" if node.get("id") in assigned_ids else "source-evidence-outside-work-projection",
            "reason": reasons[str(node.get("id"))],
            "subtree_sha256": _sha(etree.tostring(node, encoding="UTF-8", with_tail=False)),
        })

    doc_comments = [node.text or "" for node in tree.xpath("//comment()")]
    accountability = {
        "contract": "ocd-npnf211-lib049-source-accountability-v14",
        "schema": "npnf211-lib049.source-accountability.schema.json",
        "profile_id": "npnf211-lib049-three-work-v14",
        "source_scope": "complete retained ThML.body direct div1 roots ii, iii, and iv; root tails excluded as outside each subtree",
        "source_member": {"path": SOURCE_PATH, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256, "disposition": "sole retained member included"},
        "document_accounting": {
            "xml_declaration": '<?xml version="1.0" encoding="UTF-8"?>',
            "standalone": False,
            "doctype": '<!DOCTYPE ThML PUBLIC "-//CCEL/DTD Theological Markup Language//EN" "http://www.ccel.org/dtd/ThML10.dtd">',
            "pre_root_comments": doc_comments,
            "pre_root_processing_instructions": [],
            "post_root_nodes": [],
            "root_tag": "ThML",
            "root_attributes": {},
            "root_namespace_declarations": {},
            "head_inventory": _head_inventory(tree),
            "metadata": _metadata(tree),
        },
        "member_accounting": [{"path": SOURCE_PATH, "disposition": "included; every retained document region explicitly included or excluded below"}],
        "source_census": {"complete_document": complete_census, "assigned_scope": census, "excluded_shell_head_front_and_indexes": excluded_census},
        "assigned_work_count": 3,
        "feature_count": len(crosswalk),
        "attribute_count": census["attributes"],
        "feature_counts": counts,
        "omitted_feature_count": 0,
        "duplicate_feature_count": 0,
        "unresolved_feature_count": 0,
        "table_census": {"tables": counts["table"], "rows": counts["tr"], "cells": counts["td"]},
        "top_level_division_accounting": top_accounting,
        "crosswalk": crosswalk,
    }
    metadata = _metadata(tree)
    provenance = {
        "contract": "ocd-npnf211-lib049-provenance-v14",
        "status": "nonaccepted",
        "source_id": source_manifest.record["source_id"],
        "source": {"path": SOURCE_PATH, "bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256, "scope": "direct div1 ii, iii, iv"},
        "works": [
            {
                "ordinal": ordinal,
                "source_root_id": scope,
                "work_id": work_id,
                "source_title": selected[ordinal - 1].get("title", ""),
                "accepted_ir": "not_accepted",
                "human_review": "required",
                "publication": "not_ready",
            }
            for ordinal, (scope, work_id) in enumerate(ASSIGNED, start=1)
        ],
        "retained_metadata": metadata,
        "edition": {"print_source": "Edinburgh, T & T Clark", "print_date": None, "electronic_publisher": "Grand Rapids, MI: Christian Classics Ethereal Library", "electronic_created": "2004-07-25", "print_collation": "not-performed"},
        "rights": {"retained_statement": "Public Domain", "human_rights_decision": "absent", "human_acceptance": "absent", "publication_state": "not_ready"},
        "canonical_data_written": False,
        "canonical_ir_written": False,
    }
    unresolved = [
        {"id": "npnf211-edition-witness", "scope": "edition", "status": "unresolved", "question": "What exact dated print witness corresponds to the retained CCEL XML?", "evidence": "The retained head names Edinburgh, T & T Clark and an electronic creation date but supplies no print date; no print collation was performed."},
        {"id": "npnf211-rights-publication", "scope": "all-three-assigned-works", "status": "unresolved", "question": "Will a maintainer make an independent rights and publication decision?", "evidence": "The retained head states Public Domain; technical preservation of that source claim is not a rights decision or publication authorization."},
        {"id": "npnf211-human-acceptance", "scope": "all-three-assigned-works", "status": "unresolved", "question": "Will a maintainer accept the candidate text?", "evidence": "Technical validation is separate from human textual acceptance."},
    ]
    readme = (
        "# LIB-049 NPNF211 retained-source attribution\n\n"
        f"Retained source: `{SOURCE_PATH}` ({SOURCE_BYTES} bytes; SHA-256 `{SOURCE_SHA256}`).\n\n"
        "The retained ThML identifies the work as “NPNF-211. Sulpitius Severus, Vincent of Lerins, John Cassian,” names Philip Schaff as editor, names Edinburgh, T & T Clark as the print source, identifies Christian Classics Ethereal Library as electronic publisher, and states “Public Domain.” Source URL: https://www.ccel.org/ccel/schaff/npnf211.html.\n\n"
        "This candidate preserves the complete direct `div1` roots `ii`, `iii`, and `iv`. Root `i` (title page), root `v` (indexes), the ThML shell/head, prolog, comments, metadata, and rights claims are explicitly accounted in `source-accountability.json` and `provenance.json`. Human textual acceptance, an independent rights decision, and publication authorization are absent; publication remains `not_ready`.\n"
    ).encode("utf-8")
    return {
        "README.source.md": readme,
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accountability),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()

__all__: tuple[str, ...] = ()
