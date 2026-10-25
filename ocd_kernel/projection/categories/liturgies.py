"""PIPE-011 source-bound liturgy service-step projection.

The vertical slice treats the source service sequence as authoritative. Speech,
rubrics, branches, and alternatives are separate row kinds; alternatives are
kept as alternatives and are never flattened into a single spoken sequence.
The checker uses an independent lxml traversal and recomputes the complete
receipt without invoking the producer.
"""

from __future__ import annotations
from ocd_kernel.projection.native_content_check import projection_validator

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

import jsonschema
from lxml import etree
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ocd_kernel.library._common import PipelineError, sha256_file

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = f"{{{TEI_NS}}}"
CATEGORY = "liturgies"
MAPPING_VERSION = "ocd-liturgies-mapping-provisional-v3"
ASSEMBLER_VERSION = "ocd-liturgies-assembler-provisional-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "v2" / "categories" / "liturgies.schema.json"
COMMON_SCHEMA_PATH = SCHEMA_PATH.parents[1] / "public-row.schema.json"


class UnsupportedStructure(PipelineError):
    """The selected service contains a visible unsupported feature."""


_ATTRIBUTES: dict[str, set[str]] = {
    "TEI": {"xml:lang"}, "teiHeader": set(), "revisionDesc": set(), "change": {"xml:id", "when"}, "fileDesc": set(), "titleStmt": set(),
    "title": {"xml:id"}, "publicationStmt": set(), "sourceDesc": set(),
    "p": {"xml:id", "rend", "type"}, "ptr": {"type", "target", "xml:id"},
    "idno": {"type", "xml:id"}, "source": {"xml:id"}, "text": {"xml:lang"},
    "front": {"xml:id", "type", "n"}, "body": {"xml:id", "type", "n"},
    "back": {"xml:id", "type", "n"},
    "div": {"type", "n", "xml:id", "xml:lang"}, "head": {"type", "xml:id"},
    "label": {"xml:id"}, "sp": {"type", "xml:id", "corresp", "sameAs"},
    "speaker": {"xml:id"}, "stage": {"type", "rend", "xml:id"},
    "choice": {"xml:id"}, "seg": {"type", "n", "xml:id"},
    "note": {"type", "place", "n", "xml:id"}, "hi": {"rend", "xml:id"},
    "foreign": {"xml:lang", "xml:id"}, "ref": {"type", "target", "xml:id"},
    "lb": {"break", "xml:id"}, "pb": {"n", "xml:id"},
}

_CHILDREN: dict[str, set[str]] = {
    "TEI": {"teiHeader", "text"}, "teiHeader": {"fileDesc", "revisionDesc"}, "revisionDesc": {"change"}, "change": set(),
    "fileDesc": {"titleStmt", "publicationStmt", "sourceDesc"}, "titleStmt": {"title"},
    "title": set(), "publicationStmt": {"p"}, "sourceDesc": {"p", "ptr", "idno", "source", "note"},
    "source": {"ptr", "idno", "p"}, "ptr": set(), "idno": set(),
    "text": {"front", "body", "back"}, "front": {"div", "head", "label", "note"},
    "body": {"div", "head", "label", "note"}, "back": {"div", "head", "label", "note"},
    "div": {"head", "label", "p", "sp", "stage", "choice", "div", "note", "pb", "lb"},
    "head": {"hi", "seg", "foreign"}, "label": {"hi", "seg", "foreign"},
    "p": {"hi", "seg", "foreign", "ref", "ptr", "idno", "choice", "lb"},
    "sp": {"speaker", "p", "stage", "choice", "lg"}, "speaker": {"hi", "seg", "foreign"},
    "stage": {"hi", "seg", "foreign"}, "choice": {"seg", "note"},
    "seg": {"label", "p", "stage", "hi", "seg", "foreign"},
    "note": {"hi", "seg", "foreign", "ref"}, "hi": {"hi", "seg", "foreign"},
    "foreign": {"hi", "seg"}, "ref": {"hi", "seg", "foreign"},
    "lb": set(), "pb": set(),
}
_ELEMENTS = set(_ATTRIBUTES)
_CONTAINERS = {"TEI", "teiHeader", "fileDesc", "titleStmt", "publicationStmt", "sourceDesc", "revisionDesc", "source", "text", "front", "body", "back", "div", "sp", "choice"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _public_token(source_id: str) -> str:
    """Return the stable public token for a source XML identifier.

    Source XML identifiers remain available through private anchors and the
    inventory. Public rows use a deterministic token so source-local IDs do
    not become part of the public identifier contract.
    """
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:20]


def _source_id_index_et(root: ET.Element) -> dict[str, ET.Element]:
    """Index source nodes by public token, rejecting token collisions."""
    index: dict[str, ET.Element] = {}
    raw_ids: dict[str, str] = {}
    for node in root.iter():
        source_id = node.get(XML_ID)
        if not source_id:
            continue
        token = _public_token(source_id)
        previous = raw_ids.get(token)
        if previous is not None and previous != source_id:
            raise UnsupportedStructure("public source XML-ID token collision")
        raw_ids[token] = source_id
        index[token] = node
    return index


def _source_id_index_lxml(root: etree._Element) -> dict[str, etree._Element]:
    """Index source nodes by public token, rejecting token collisions."""
    index: dict[str, etree._Element] = {}
    raw_ids: dict[str, str] = {}
    for node in root.iter():
        source_id = node.get(XML_ID)
        if not source_id:
            continue
        token = _public_token(source_id)
        previous = raw_ids.get(token)
        if previous is not None and previous != source_id:
            raise UnsupportedStructure("public source XML-ID token collision")
        raw_ids[token] = source_id
        index[token] = node
    return index


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _attribute_name(key: str) -> str:
    if key == XML_ID:
        return "xml:id"
    if key == XML_LANG:
        return "xml:lang"
    if key.startswith("{"):
        return f"{{{key[1:].split('}', 1)[0]}}}{key.split('}', 1)[1]}"
    return key


def _path_et(root: ET.Element, target: ET.Element) -> str:
    parents: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parents[child] = node
    parts: list[str] = []
    node: ET.Element | None = target
    while node is not None:
        tag = _local(node.tag)
        xid = node.get(XML_ID)
        if xid:
            parts.append(f"{tag}[@xml:id='{xid}']")
        else:
            parent = parents.get(node)
            siblings = [child for child in list(parent) if _local(child.tag) == tag] if parent is not None else [node]
            parts.append(f"{tag}[{siblings.index(node) + 1}]")
        node = parents.get(node)
    return "/" + "/".join(reversed(parts))


def _path_lxml(root: etree._Element, target: etree._Element) -> str:
    parts: list[str] = []
    node: etree._Element | None = target
    while node is not None:
        tag = etree.QName(node).localname
        xid = node.get(XML_ID)
        if xid:
            parts.append(f"{tag}[@xml:id='{xid}']")
        else:
            parent = node.getparent()
            siblings = [child for child in parent if etree.QName(child).localname == tag] if parent is not None else [node]
            parts.append(f"{tag}[{siblings.index(node) + 1}]")
        node = node.getparent()
    return "/" + "/".join(reversed(parts))


def _strict_et(root: ET.Element) -> None:
    if root.tag != f"{NS}TEI":
        raise UnsupportedStructure("unsupported-visible: master root must be TEI in the TEI namespace")
    ids: set[str] = set()
    for node in root.iter():
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            raise UnsupportedStructure("unsupported-visible: non-TEI element or processing instruction")
        tag = _local(node.tag)
        if tag not in _ELEMENTS:
            raise UnsupportedStructure(f"unsupported-visible: element {tag}")
        unknown = {_attribute_name(key) for key in node.attrib} - _ATTRIBUTES[tag]
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {tag} attribute {sorted(unknown)[0]}")
        xid = node.get(XML_ID)
        if xid:
            if xid in ids:
                raise UnsupportedStructure(f"duplicate source xml:id: {xid}")
            ids.add(xid)
        for child in list(node):
            if not isinstance(child.tag, str) or not child.tag.startswith(NS):
                raise UnsupportedStructure(f"unsupported-visible: non-TEI child of {tag}")
            child_tag = _local(child.tag)
            if child_tag not in _CHILDREN[tag]:
                raise UnsupportedStructure(f"unsupported-visible: {child_tag} child of {tag}")
        if tag in _CONTAINERS and _norm(node.text):
            raise UnsupportedStructure(f"unsupported-visible: loose text in {tag}")
        if tag in _CONTAINERS and any(_norm(child.tail) for child in list(node)):
            raise UnsupportedStructure(f"unsupported-visible: loose tail in {tag}")
    if [child.tag for child in list(root)] != [f"{NS}teiHeader", f"{NS}text"]:
        raise UnsupportedStructure("unsupported-visible: TEI envelope order")
    header = root.find(f"{NS}teiHeader")
    text = root.find(f"{NS}text")
    if header is None or text is None or [child.tag for child in list(header)] not in ([f"{NS}fileDesc"], [f"{NS}fileDesc", f"{NS}revisionDesc"]):
        raise UnsupportedStructure("unsupported-visible: teiHeader envelope")
    if [child.tag for child in list(text)] != [f"{NS}body"]:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")


def _parse_et(path: Path) -> ET.Element:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read liturgy TEI {path}: {exc}") from exc
    compact = raw.replace(b"\x00", b"")
    if any(token in compact.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(rb"<\?(?!xml(?:\s|\?>))", compact, flags=re.I):
        raise PipelineError("unsupported-visible: declarations, comments, or processing instructions")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    except ET.ParseError as exc:
        raise PipelineError(f"invalid liturgy TEI {path}: {exc}") from exc
    _strict_et(root)
    return root


def _source_binding_et(root: ET.Element, *, source_url: str | None, source_sha256: str | None, retained_sha256: str | None) -> dict[str, str | None]:
    source_desc = next((node for node in root.iter() if _local(node.tag) == "sourceDesc"), None)
    if source_desc is None:
        raise PipelineError("liturgy TEI must contain sourceDesc")
    ptrs = [node for node in source_desc.iter() if _local(node.tag) == "ptr" and node.get("target")]
    actual_url = ptrs[0].get("target") if ptrs else None
    if source_url and actual_url != source_url:
        raise PipelineError("liturgy source URL mismatch")
    actual_hash = None
    for node in source_desc.iter():
        if _local(node.tag) == "idno" and _norm(node.get("type")).lower() in {"source_sha256", "sha256", "source-sha256"}:
            actual_hash = _norm("".join(node.itertext())).lower().removeprefix("sha256:")
            break
    if actual_hash and not re.fullmatch(r"[0-9a-f]{64}", actual_hash):
        raise PipelineError("liturgy source sha256 is invalid")
    requested = source_sha256.lower().removeprefix("sha256:") if source_sha256 else None
    if requested and actual_hash != requested:
        raise PipelineError("liturgy source sha256 mismatch")
    return {"source_url": actual_url or source_url, "source_sha256": actual_hash or requested, "retained_sha256": retained_sha256}


def _language_et(root: ET.Element, requested: str | None) -> str:
    value = requested or root.get(XML_LANG)
    if not value:
        value = next((node.get(XML_LANG) for node in root.iter() if _local(node.tag) in {"text", "body"} and node.get(XML_LANG)), None)
    if not value or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise PipelineError("liturgy language must be declared")
    return value


def _note_text(node: ET.Element) -> str:
    return _norm("".join(node.itertext()))


def _label_et(node: ET.Element) -> str | None:
    head = next((child for child in list(node) if _local(child.tag) in {"head", "label"}), None)
    return _note_text(head) if head is not None else None


def _branch_chain_et(root: ET.Element, node: ET.Element) -> list[ET.Element]:
    parents: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in list(parent):
            parents[child] = parent
    chain: list[ET.Element] = []
    current: ET.Element | None = node
    while current is not None:
        if _local(current.tag) == "div" and current.get("type") == "branch":
            chain.append(current)
        current = parents.get(current)
    return list(reversed(chain))


def _locator_et(root: ET.Element, service: ET.Element, node: ET.Element, service_number: int, step_number: int) -> dict[str, Any]:
    chain = []
    parents: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in list(parent):
            parents[child] = parent
    current: ET.Element | None = node
    while current is not None:
        if _local(current.tag) == "div":
            chain.append(current)
        current = parents.get(current)
    chain = list(reversed(chain))
    divisions: list[dict[str, Any]] = []
    part_titles: list[str] = []
    for item in chain:
        parent = parents.get(item)
        siblings = [child for child in list(parent) if _local(child.tag) == "div" and child.get("type") == item.get("type")] if parent is not None else [item]
        title = _label_et(item)
        divisions.append({"order": siblings.index(item) + 1, "type": item.get("type"), "titles": [title] if title else []})
        if title and item.get("type") in {"collection", "work", "book", "part", "section"}:
            part_titles.append(title)
    text_part = next((item.get("type") for item in chain if item.get("type") in {"front", "back"}), "body")
    return {"kind": "liturgy-step", "text_part": text_part, "part_titles": part_titles, "divisions": divisions, "service": service_number, "step": step_number}


def _speech_et(node: ET.Element) -> str:
    paragraphs = [child for child in list(node) if _local(child.tag) == "p"]
    if not paragraphs:
        raise UnsupportedStructure("liturgy speech has no paragraph")
    return "\n".join(_note_text(child) for child in paragraphs)


def _choice_et(node: ET.Element) -> tuple[str, list[dict[str, str | None]]]:
    alternatives: list[dict[str, str | None]] = []
    for segment in list(node):
        if _local(segment.tag) != "seg" or segment.get("type") != "alternative":
            if _local(segment.tag) == "note":
                continue
            raise UnsupportedStructure("choice must contain source-defined alternative seg elements")
        labels = [child for child in list(segment) if _local(child.tag) == "label"]
        paragraphs = [child for child in list(segment) if _local(child.tag) in {"p", "stage"}]
        if paragraphs:
            text = "\n".join(_note_text(child) for child in paragraphs)
        else:
            text = " ".join(part for part in [_norm(segment.text)] + [_norm(child.tail) for child in list(segment)] if part)
        if not text:
            raise UnsupportedStructure("liturgy alternative has no text")
        alternatives.append({"label": _note_text(labels[0]) if labels else None, "text": text})
    if len(alternatives) < 2:
        raise UnsupportedStructure("liturgy choice requires at least two alternatives")
    return " | ".join(item["text"] or "" for item in alternatives), alternatives


def _validate_public_links(rows: list[dict[str, Any]]) -> None:
    """Ensure hashed response and branch links resolve within this projection."""
    step_ids = {str(row["step_id"]) for row in rows}
    branch_ids = {str(row["step_id"]) for row in rows if row.get("step_kind") == "branch"}
    for row in rows:
        response_to = row.get("response_to")
        if response_to is not None and str(response_to) not in step_ids:
            raise UnsupportedStructure(f"liturgy response target does not resolve: {response_to}")
        branch = row.get("branch")
        if branch is not None:
            if not isinstance(branch, Mapping) or str(branch.get("id")) not in branch_ids:
                raise UnsupportedStructure(f"liturgy branch link does not resolve: {branch}")


def _step_row_et(root: ET.Element, service: ET.Element, node: ET.Element, *, service_number: int, step_number: int, language: str, identity: Mapping[str, str], representation_revision: str, edition_title: str, branch: ET.Element | None) -> dict[str, Any]:
    kind = _local(node.tag)
    source_step_id = node.get(XML_ID)
    source_service_id = service.get(XML_ID)
    if not source_step_id:
        raise UnsupportedStructure(f"liturgy step {kind} has no xml:id")
    if not source_service_id:
        raise UnsupportedStructure("liturgy service has no xml:id")
    step_id = _public_token(source_step_id)
    service_id = _public_token(source_service_id)
    branch_data = None
    if branch is not None:
        source_branch_id = branch.get(XML_ID)
        if not source_branch_id:
            raise UnsupportedStructure("liturgy branch has no xml:id")
        branch_data = {"id": _public_token(source_branch_id), "label": _label_et(branch)}
    row: dict[str, Any] = {
        **{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
        "record_id": f"{identity['edition_id']}:liturgy:{service_id}:{step_id}",
        "sequence": step_number,
        "category": CATEGORY,
        "language": language,
        "text": "",
        "representation_revision": representation_revision,
        "locator": _locator_et(root, service, node, service_number, step_number),
        "provenance": {"edition_title": edition_title},
        "notes": [], "references": [],
        "service_id": service_id, "service_title": _label_et(service) or "",
        "step_id": step_id, "step_kind": "text", "sequence_in_service": step_number,
    }
    if branch_data:
        row["branch"] = branch_data
    if kind == "sp":
        row["step_kind"] = "speech"
        speakers = [child for child in list(node) if _local(child.tag) == "speaker"]
        if len(speakers) != 1:
            raise UnsupportedStructure("liturgy speech requires one speaker")
        row["speaker"] = _note_text(speakers[0])
        row["text"] = _speech_et(node)
        target = _norm(node.get("corresp") or node.get("sameAs")).lstrip("#")
        if target:
            row["response_to"] = _public_token(target)
    elif kind == "p":
        choices = [child for child in list(node) if _local(child.tag) == "choice"]
        if choices:
            if len(choices) != 1:
                raise UnsupportedStructure("liturgy alternative paragraph requires one choice")
            row["step_kind"] = "alternative"
            row["text"], row["alternatives"] = _choice_et(choices[0])
        else:
            row["text"] = _note_text(node)
        if node.get("rend") == "rubric":
            row["step_kind"] = "rubric"
            row["rubric"] = {"text": row["text"], "source_type": "p@rend=rubric"}
        elif not choices:
            row["step_kind"] = "text"
    elif kind == "stage":
        row["text"] = _note_text(node)
        row["step_kind"] = "rubric"
        row["rubric"] = {"text": row["text"], "source_type": "stage"}
    elif kind == "choice":
        row["step_kind"] = "alternative"
        row["text"], row["alternatives"] = _choice_et(node)
    elif kind == "div" and node.get("type") == "branch":
        row["step_kind"] = "branch"
        row["text"] = _label_et(node) or ""
        row["branch"] = {"id": step_id, "label": _label_et(node)}
    else:
        raise UnsupportedStructure(f"unsupported-visible: {kind} in service sequence")
    if not row["text"] and row["step_kind"] not in {"alternative", "branch"}:
        raise UnsupportedStructure(f"liturgy step {step_id} has no visible text")
    return row


def _services_et(root: ET.Element) -> list[ET.Element]:
    body = next((node for node in root.iter() if _local(node.tag) == "body"), None)
    if body is None:
        raise UnsupportedStructure("liturgy TEI has no body")
    services = [node for node in list(body) if _local(node.tag) == "div" and node.get("type") == "service"]
    if not services:
        raise UnsupportedStructure("no source-defined liturgy service")
    return services


def _rows_et(root: ET.Element, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    services = _services_et(root)
    if scope_id:
        services = [service for service in services if service.get(XML_ID) == scope_id]
        if not services:
            raise UnsupportedStructure(f"liturgy scope xml:id not found: {scope_id}")
    source_index = _source_id_index_et(root)
    parents: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in list(parent):
            parents[child] = parent
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for service_number, service in enumerate(services, 1):
        heads = [child for child in list(service) if _local(child.tag) == "head"]
        if len(heads) != 1 or not _note_text(heads[0]):
            raise UnsupportedStructure("liturgy service requires one non-empty head")
        step_number = 0

        def walk(parent: ET.Element, active_branch: ET.Element | None = None) -> None:
            nonlocal step_number
            for child in list(parent):
                kind = _local(child.tag)
                if kind in {"head", "label", "note", "pb", "lb"}:
                    continue
                if kind == "div" and child.get("type") == "section":
                    if active_branch is not None:
                        raise UnsupportedStructure("liturgy section cannot be nested in a branch")
                    walk(child)
                elif kind == "div" and child.get("type") == "branch":
                    if active_branch is not None:
                        raise UnsupportedStructure("liturgy branch cannot be nested in a branch")
                    if child.get("n") is not None:
                        try:
                            if int(child.get("n") or "0") < 1:
                                raise UnsupportedStructure("liturgy branch source order must be positive")
                        except ValueError as exc:
                            raise UnsupportedStructure("liturgy branch source order must be an integer") from exc
                    step_number += 1
                    rows.append(_step_row_et(root, service, child, service_number=service_number, step_number=step_number, language=language, identity=identity, representation_revision=representation_revision, edition_title=edition_title, branch=active_branch))
                    walk(child, child)
                elif kind in {"sp", "p", "stage", "choice"}:
                    step_number += 1
                    rows.append(_step_row_et(root, service, child, service_number=service_number, step_number=step_number, language=language, identity=identity, representation_revision=representation_revision, edition_title=edition_title, branch=active_branch))
                else:
                    raise UnsupportedStructure(f"unsupported-visible: {kind} in service sequence")
        service_row_count = len(rows)
        walk(service)
        if len(rows) == service_row_count:
            raise UnsupportedStructure(f"liturgy service {service.get(XML_ID)} has no mapped steps")
    _validate_public_links(rows)
    for row in rows:
        source_node = source_index.get(row["step_id"])
        if source_node is None:
            raise UnsupportedStructure(f"liturgy step anchor not found: {row['step_id']}")
        source_service = source_node
        while source_service is not None and not (_local(source_service.tag) == "div" and source_service.get("type") == "service"):
            source_service = parents.get(source_service)
        if source_service is None or not source_service.get(XML_ID):
            raise UnsupportedStructure(f"liturgy service anchor not found: {row['step_id']}")
        source_branch = source_node
        while source_branch is not None and not (_local(source_branch.tag) == "div" and source_branch.get("type") == "branch"):
            source_branch = parents.get(source_branch)
        anchors.append({
            "record_id": row["record_id"],
            "service_id": row["service_id"],
            "step_id": row["step_id"],
            "source_xml_id": source_node.get(XML_ID),
            "source_service_xml_id": source_service.get(XML_ID),
            "source_branch_xml_id": source_branch.get(XML_ID) if source_branch is not None else None,
            "source_order": row["sequence"],
            "sequence_in_service": row["sequence_in_service"],
            "step_kind": row["step_kind"],
            "tei_path": _path_et(root, source_node),
            "text_sha256": _hash_text(row["text"]),
            "text_length": len(row["text"]),
            "branch": row.get("branch"),
        })
    return rows, anchors


def _inventory_et(root: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    inventory: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    exclusions: list[dict[str, str]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        tag = _local(node.tag)
        path = _path_et(root, node)
        in_header = any(_local(parent.tag) == "teiHeader" for parent in _ancestors_all_et(root, node))
        if in_header:
            role = "header-metadata"
            exclusions.append({"tei_path": path, "reason": "header-metadata"})
        elif tag in {"head", "label"}:
            role = "structural-heading"
            exclusions.append({"tei_path": path, "reason": "structural-heading"})
        elif tag in {"note", "pb", "lb"}:
            role = "excluded-source-detail"
            exclusions.append({"tei_path": path, "reason": "source-detail-excluded"})
        else:
            role = "mapped-source"
        if tag == "hi" and not in_header:
            warnings.append({"tei_path": path, "reason": "typography-to-plain-text"})
        inventory.append({"ordinal": ordinal, "tei_path": path, "tag": tag, "role": role, "attributes": {_attribute_name(k): v for k, v in sorted(node.attrib.items())}, "text_sha256": _hash_text(_norm(node.text)), "tail_sha256": _hash_text(_norm(node.tail))})
    return inventory, warnings, exclusions


def _ancestors_all_et(root: ET.Element, target: ET.Element) -> list[ET.Element]:
    parents: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parents[child] = node
    chain: list[ET.Element] = []
    node: ET.Element | None = target
    while node is not None:
        chain.append(node)
        node = parents.get(node)
    return list(reversed(chain))


def _validator() -> jsonschema.Draft202012Validator:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        common = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
        registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
        native = json.loads((SCHEMA_PATH.parents[1] / "native-content.schema.json").read_text(encoding="utf-8"))
        registry = registry.with_resource(native["$id"], Resource.from_contents(native, default_specification=DRAFT202012))
        validator = projection_validator(schema, registry=registry)
        validator.check_schema(schema)
        return validator
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise PipelineError(f"invalid liturgy schema package: {exc}") from exc


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"invalid liturgy public row {row.get('record_id', index)}: {errors[0].message}")


def _receipt(*, path: Path, rows: list[dict[str, Any]], anchors: list[dict[str, Any]], inventory: list[dict[str, Any]], warnings: list[dict[str, str]], exclusions: list[dict[str, str]], source_binding: Mapping[str, str | None]) -> dict[str, Any]:
    return {"mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "master_sha256": sha256_file(path), "source_binding": dict(source_binding), "policy_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(), "common_schema_sha256": hashlib.sha256(COMMON_SCHEMA_PATH.read_bytes()).hexdigest(), "output_sha256": hashlib.sha256(_canonical(rows)).hexdigest(), "row_count": len(rows), "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending"}}


def project_liturgies_document(tei_path: Path, *, identity: Mapping[str, str], language: str | None = None, representation_revision: str, edition_title: str, scope_id: str | None = None, source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, projection_profile: str | None = None, **_: Any) -> dict[str, Any]:
    if projection_profile == 'ocd-liturgies-chrysostom-1866-retained-members-v1':
        if scope_id is not None:
            raise UnsupportedStructure('Chrysostom requires the complete declared electronic witness')
        from ocd_kernel.projection.categories.liturgies_chrysostom import project_document
        return project_document(tei_path, identity=identity, language=language,
                                representation_revision=representation_revision, edition_title=edition_title,
                                projection_profile=projection_profile, source_url=source_url,
                                source_sha256=source_sha256, retained_sha256=retained_sha256)
    if projection_profile in ('ocd-liturgies-bcp1549-retained-members-v1', 'ocd-liturgies-bcp1559-retained-members-v1'):
        if scope_id is not None:
            raise UnsupportedStructure('retained HTML BCP requires the complete declared member set')
        if projection_profile == 'ocd-liturgies-bcp1549-retained-members-v1':
            from ocd_kernel.projection.categories.liturgies_bcp1549 import project_document
        else:
            from ocd_kernel.projection.categories.liturgies_bcp1559 import project_document
        return project_document(tei_path, identity=identity, language=language,
                                representation_revision=representation_revision, edition_title=edition_title,
                                projection_profile=projection_profile, source_url=source_url,
                                source_sha256=source_sha256, retained_sha256=retained_sha256)
    if projection_profile is not None:
        from ocd_kernel.projection.categories.liturgies_bcp1662 import PROFILE as BCP_PROFILE, project_document as project_bcp
        if projection_profile == BCP_PROFILE:
            if scope_id is not None:
                raise PipelineError("unsupported liturgy projection profile scope")
            return project_bcp(tei_path, identity=identity, language=language,
                               representation_revision=representation_revision,
                               edition_title=edition_title, projection_profile=projection_profile,
                               source_url=source_url, source_sha256=source_sha256,
                               retained_sha256=retained_sha256)
        from ocd_kernel.projection.categories.liturgies_office import PROFILE, project_document

        if projection_profile != PROFILE or scope_id is not None:
            raise PipelineError("unsupported liturgy projection profile or scope")
        return project_document(tei_path, identity=identity, language=language,
                                representation_revision=representation_revision,
                                edition_title=edition_title, projection_profile=projection_profile,
                                source_url=source_url, source_sha256=source_sha256,
                                retained_sha256=retained_sha256)
    required = {"work_id", "textual_form_id", "edition_id"}
    if set(identity) != required or any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise PipelineError("liturgy identity requires work_id, textual_form_id, and edition_id")
    path = Path(tei_path)
    root = _parse_et(path)
    binding = _source_binding_et(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256)
    lang = _language_et(root, language)
    rows, anchors = _rows_et(root, identity=identity, language=lang, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id)
    _validate_rows(rows)
    inventory, warnings, exclusions = _inventory_et(root)
    receipt = _receipt(path=path, rows=rows, anchors=anchors, inventory=inventory, warnings=warnings, exclusions=exclusions, source_binding=binding)
    return {"rows": rows, "receipt": receipt, "mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "master_sha256": receipt["master_sha256"], "source_binding": binding, "scope_id": scope_id, "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "independent_check": receipt["independent_check"]}


project = project_liturgies_document


def _parse_lxml(path: Path) -> etree._Element:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read liturgy TEI {path}: {exc}") from exc
    compact = raw.replace(b"\x00", b"")
    if any(token in compact.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(rb"<\?(?!xml(?:\s|\?>))", compact, flags=re.I):
        raise PipelineError("unsupported-visible: declarations, comments, or processing instructions")
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"invalid liturgy TEI {path}: {exc}") from exc
    _strict_lxml(root)
    return root


def _strict_lxml(root: etree._Element) -> None:
    if etree.QName(root).namespace != TEI_NS:
        raise UnsupportedStructure("unsupported-visible: master root must be TEI in the TEI namespace")
    ids: set[str] = set()
    for node in root.iter():
        if not isinstance(node.tag, str):
            raise UnsupportedStructure("unsupported-visible: comment or processing instruction")
        qname = etree.QName(node)
        if qname.namespace != TEI_NS or qname.localname not in _ELEMENTS:
            raise UnsupportedStructure(f"unsupported-visible: element {qname.localname}")
        tag = qname.localname
        unknown = {_attribute_name(key) for key in node.attrib} - _ATTRIBUTES[tag]
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {tag} attribute {sorted(unknown)[0]}")
        xid = node.get(XML_ID)
        if xid:
            if xid in ids:
                raise UnsupportedStructure(f"duplicate source xml:id: {xid}")
            ids.add(xid)
        for child in node:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != TEI_NS:
                raise UnsupportedStructure(f"unsupported-visible: non-TEI child of {tag}")
            if etree.QName(child).localname not in _CHILDREN[tag]:
                raise UnsupportedStructure(f"unsupported-visible: {etree.QName(child).localname} child of {tag}")
        if tag in _CONTAINERS and _norm(node.text):
            raise UnsupportedStructure(f"unsupported-visible: loose text in {tag}")
        if tag in _CONTAINERS and any(_norm(child.tail) for child in node):
            raise UnsupportedStructure(f"unsupported-visible: loose tail in {tag}")
    if [etree.QName(child).localname for child in root] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: TEI envelope order")
    header = root.find(f"{NS}teiHeader")
    text = root.find(f"{NS}text")
    if header is None or text is None or [etree.QName(child).localname for child in header] not in (["fileDesc"], ["fileDesc", "revisionDesc"]):
        raise UnsupportedStructure("unsupported-visible: teiHeader envelope")
    if [etree.QName(child).localname for child in text] != ["body"]:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")


def _source_binding_lxml(root: etree._Element, *, source_url: str | None, source_sha256: str | None, retained_sha256: str | None) -> dict[str, str | None]:
    desc = root.xpath(".//t:sourceDesc", namespaces={"t": TEI_NS})
    if len(desc) != 1:
        raise PipelineError("liturgy TEI must contain one sourceDesc")
    ptrs = desc[0].xpath(".//t:ptr[@target]", namespaces={"t": TEI_NS})
    actual_url = ptrs[0].get("target") if ptrs else None
    if source_url and actual_url != source_url:
        raise PipelineError("liturgy source URL mismatch")
    actual_hash = None
    for node in desc[0].xpath(".//t:idno[@type]", namespaces={"t": TEI_NS}):
        if _norm(node.get("type")).lower() in {"source_sha256", "sha256", "source-sha256"}:
            actual_hash = _norm("".join(node.itertext())).lower().removeprefix("sha256:")
            break
    if actual_hash and not re.fullmatch(r"[0-9a-f]{64}", actual_hash):
        raise PipelineError("liturgy source sha256 is invalid")
    requested = source_sha256.lower().removeprefix("sha256:") if source_sha256 else None
    if requested and actual_hash != requested:
        raise PipelineError("liturgy source sha256 mismatch")
    return {"source_url": actual_url or source_url, "source_sha256": actual_hash or requested, "retained_sha256": retained_sha256}


def _inventory_lxml(root: etree._Element) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    inventory: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    exclusions: list[dict[str, str]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        tag = etree.QName(node).localname
        path = _path_lxml(root, node)
        in_header = bool(node.xpath("ancestor-or-self::t:teiHeader", namespaces={"t": TEI_NS}))
        if in_header:
            role = "header-metadata"
            exclusions.append({"tei_path": path, "reason": "header-metadata"})
        elif tag in {"head", "label"}:
            role = "structural-heading"
            exclusions.append({"tei_path": path, "reason": "structural-heading"})
        elif tag in {"note", "pb", "lb"}:
            role = "excluded-source-detail"
            exclusions.append({"tei_path": path, "reason": "source-detail-excluded"})
        else:
            role = "mapped-source"
        if tag == "hi" and not in_header:
            warnings.append({"tei_path": path, "reason": "typography-to-plain-text"})
        inventory.append({"ordinal": ordinal, "tei_path": path, "tag": tag, "role": role, "attributes": {_attribute_name(k): v for k, v in sorted(node.attrib.items())}, "text_sha256": _hash_text(_norm(node.text)), "tail_sha256": _hash_text(_norm(node.tail))})
    return inventory, warnings, exclusions


def _language_lxml(root: etree._Element, requested: str | None) -> str:
    value = requested or root.get(XML_LANG)
    if not value:
        values = root.xpath("/t:TEI/t:text/@xml:lang | /t:TEI/t:text/t:body/@xml:lang", namespaces={"t": TEI_NS, "xml": XML_NS})
        value = values[0] if values else None
    if not value or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise PipelineError("liturgy language must be declared")
    return value


def _label_lxml(node: etree._Element) -> str | None:
    found = node.xpath("./t:head | ./t:label", namespaces={"t": TEI_NS})
    return _norm("".join(found[0].itertext())) if found else None


def _locator_lxml(root: etree._Element, node: etree._Element, service_number: int, step_number: int) -> dict[str, Any]:
    chain: list[etree._Element] = []
    current: etree._Element | None = node
    while current is not None:
        if etree.QName(current).localname == "div":
            chain.append(current)
        current = current.getparent()
    chain.reverse()
    part_titles: list[str] = []
    divisions: list[dict[str, Any]] = []
    for item in chain:
        parent = item.getparent()
        siblings = [child for child in parent if etree.QName(child).localname == "div" and child.get("type") == item.get("type")] if parent is not None else [item]
        title = _label_lxml(item)
        divisions.append({"order": siblings.index(item) + 1, "type": item.get("type"), "titles": [title] if title else []})
        if title and item.get("type") in {"collection", "work", "book", "part", "section"}:
            part_titles.append(title)
    text_part = next((item.get("type") for item in chain if item.get("type") in {"front", "back"}), "body")
    return {"kind": "liturgy-step", "text_part": text_part, "part_titles": part_titles, "divisions": divisions, "service": service_number, "step": step_number}


def _choice_lxml(node: etree._Element) -> tuple[str, list[dict[str, str | None]]]:
    alternatives: list[dict[str, str | None]] = []
    for segment in node.xpath("./t:seg", namespaces={"t": TEI_NS}):
        if segment.get("type") != "alternative":
            raise UnsupportedStructure("choice contains non-alternative seg")
        labels = segment.xpath("./t:label", namespaces={"t": TEI_NS})
        paragraphs = segment.xpath("./t:p | ./t:stage", namespaces={"t": TEI_NS})
        if paragraphs:
            text = "\n".join(_norm("".join(item.itertext())) for item in paragraphs)
        else:
            text = " ".join(part for part in [_norm(segment.text)] + [_norm(child.tail) for child in segment] if part)
        if not text:
            raise UnsupportedStructure("liturgy alternative has no text")
        alternatives.append({"label": _norm("".join(labels[0].itertext())) if labels else None, "text": text})
    if len(alternatives) < 2:
        raise UnsupportedStructure("liturgy choice requires at least two alternatives")
    return " | ".join(item["text"] or "" for item in alternatives), alternatives


def _rows_lxml(root: etree._Element, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ns = {"t": TEI_NS}
    services = root.xpath("/t:TEI/t:text/t:body/t:div[@type='service']", namespaces=ns)
    if scope_id:
        services = [service for service in services if service.get(XML_ID) == scope_id]
        if not services:
            raise UnsupportedStructure(f"liturgy scope xml:id not found: {scope_id}")
    if not services:
        raise UnsupportedStructure("no source-defined liturgy service")
    source_index = _source_id_index_lxml(root)
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for service_number, service in enumerate(services, 1):
        heads = service.xpath("./t:head", namespaces=ns)
        if len(heads) != 1 or not _norm("".join(heads[0].itertext())):
            raise UnsupportedStructure("liturgy service requires one non-empty head")
        step_number = 0

        def walk(parent: etree._Element, active_branch: etree._Element | None = None) -> None:
            nonlocal step_number
            for child in parent:
                kind = etree.QName(child).localname
                if kind in {"head", "label", "note", "pb", "lb"}:
                    continue
                branch = active_branch
                if kind == "div" and child.get("type") == "section":
                    if active_branch is not None:
                        raise UnsupportedStructure("liturgy section cannot be nested in a branch")
                    walk(child)
                elif kind == "div" and child.get("type") == "branch":
                    if active_branch is not None:
                        raise UnsupportedStructure("liturgy branch cannot be nested in a branch")
                    if child.get("n") is not None:
                        try:
                            if int(child.get("n") or "0") < 1:
                                raise UnsupportedStructure("liturgy branch source order must be positive")
                        except ValueError as exc:
                            raise UnsupportedStructure("liturgy branch source order must be an integer") from exc
                    step_number += 1
                    rows.append(_row_lxml(root, service, child, service_number, step_number, language, identity, representation_revision, edition_title, branch))
                    walk(child, child)
                elif kind in {"sp", "p", "stage", "choice"}:
                    step_number += 1
                    rows.append(_row_lxml(root, service, child, service_number, step_number, language, identity, representation_revision, edition_title, branch))
                else:
                    raise UnsupportedStructure(f"unsupported-visible: {kind} in service sequence")
        service_row_count = len(rows)
        walk(service)
        if len(rows) == service_row_count:
            raise UnsupportedStructure(f"liturgy service {service.get(XML_ID)} has no mapped steps")
    _validate_public_links(rows)
    for row in rows:
        source_node = source_index.get(row["step_id"])
        if source_node is None:
            raise UnsupportedStructure(f"liturgy step anchor not found: {row['step_id']}")
        source_service = source_node
        while source_service is not None and not (etree.QName(source_service).localname == "div" and source_service.get("type") == "service"):
            source_service = source_service.getparent()
        if source_service is None or not source_service.get(XML_ID):
            raise UnsupportedStructure(f"liturgy service anchor not found: {row['step_id']}")
        source_branch = source_node
        while source_branch is not None and not (etree.QName(source_branch).localname == "div" and source_branch.get("type") == "branch"):
            source_branch = source_branch.getparent()
        anchors.append({
            "record_id": row["record_id"],
            "service_id": row["service_id"],
            "step_id": row["step_id"],
            "source_xml_id": source_node.get(XML_ID),
            "source_service_xml_id": source_service.get(XML_ID),
            "source_branch_xml_id": source_branch.get(XML_ID) if source_branch is not None else None,
            "source_order": row["sequence"],
            "sequence_in_service": row["sequence_in_service"],
            "step_kind": row["step_kind"],
            "tei_path": _path_lxml(root, source_node),
            "text_sha256": _hash_text(row["text"]),
            "text_length": len(row["text"]),
            "branch": row.get("branch"),
        })
    return rows, anchors


def _row_lxml(root: etree._Element, service: etree._Element, node: etree._Element, service_number: int, step_number: int, language: str, identity: Mapping[str, str], representation_revision: str, edition_title: str, branch: etree._Element | None) -> dict[str, Any]:
    ns = {"t": TEI_NS}
    kind = etree.QName(node).localname
    source_step_id = node.get(XML_ID)
    source_service_id = service.get(XML_ID)
    if not source_step_id:
        raise UnsupportedStructure(f"liturgy step {kind} has no xml:id")
    if not source_service_id:
        raise UnsupportedStructure("liturgy service has no xml:id")
    step_id = _public_token(source_step_id)
    service_id = _public_token(source_service_id)
    branch_data = None
    if branch is not None:
        source_branch_id = branch.get(XML_ID)
        if not source_branch_id:
            raise UnsupportedStructure("liturgy branch has no xml:id")
        branch_data = {"id": _public_token(source_branch_id), "label": _label_lxml(branch)}
    service_title = _label_lxml(service) or ""
    row: dict[str, Any] = {**{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")}, "record_id": f"{identity['edition_id']}:liturgy:{service_id}:{step_id}", "sequence": step_number, "category": CATEGORY, "language": language, "text": "", "representation_revision": representation_revision, "locator": _locator_lxml(root, node, service_number, step_number), "provenance": {"edition_title": edition_title}, "notes": [], "references": [], "service_id": service_id, "service_title": service_title, "step_id": step_id, "step_kind": "text", "sequence_in_service": step_number}
    if branch_data:
        row["branch"] = branch_data
    if kind == "sp":
        speakers = node.xpath("./t:speaker", namespaces=ns)
        paragraphs = node.xpath("./t:p", namespaces=ns)
        if len(speakers) != 1 or not paragraphs:
            raise UnsupportedStructure("liturgy speech requires one speaker and paragraph")
        row["step_kind"] = "speech"
        row["speaker"] = _norm("".join(speakers[0].itertext()))
        row["text"] = "\n".join(_norm("".join(item.itertext())) for item in paragraphs)
        target = _norm(node.get("corresp") or node.get("sameAs")).lstrip("#")
        if target:
            row["response_to"] = _public_token(target)
    elif kind == "p":
        choices = node.xpath("./t:choice", namespaces=ns)
        if choices:
            if len(choices) != 1:
                raise UnsupportedStructure("liturgy alternative paragraph requires one choice")
            row["step_kind"] = "alternative"
            row["text"], row["alternatives"] = _choice_lxml(choices[0])
        else:
            row["text"] = _norm("".join(node.itertext()))
        if node.get("rend") == "rubric":
            row["step_kind"] = "rubric"
            row["rubric"] = {"text": row["text"], "source_type": "p@rend=rubric"}
    elif kind == "stage":
        row["text"] = _norm("".join(node.itertext()))
        row["step_kind"] = "rubric"
        row["rubric"] = {"text": row["text"], "source_type": "stage"}
    elif kind == "choice":
        row["step_kind"] = "alternative"
        row["text"], row["alternatives"] = _choice_lxml(node)
    elif kind == "div" and node.get("type") == "branch":
        row["step_kind"] = "branch"
        row["text"] = _label_lxml(node) or ""
        row["branch"] = {"id": step_id, "label": _label_lxml(node)}
    else:
        raise UnsupportedStructure(f"unsupported-visible: {kind} in service sequence")
    if not row["text"] and row["step_kind"] not in {"alternative", "branch"}:
        raise UnsupportedStructure(f"liturgy step {step_id} has no visible text")
    return row


def verify_liturgies_document(tei_path: Path, rows: list[dict[str, Any]], receipt: Mapping[str, Any] | None = None, *, identity: Mapping[str, str], language: str | None = None, representation_revision: str, edition_title: str, scope_id: str | None = None, source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, projection_profile: str | None = None, **_: Any) -> list[str]:
    """Independently reconcile source sequence, rows, and every receipt field."""
    if projection_profile == 'ocd-liturgies-chrysostom-1866-retained-members-v1':
        if scope_id is not None:
            return ['Chrysostom requires the complete declared electronic witness']
        from ocd_kernel.projection.categories.liturgies_chrysostom_check import verify_document
        return verify_document(tei_path, rows, receipt, identity=identity, language=language,
                               representation_revision=representation_revision, edition_title=edition_title,
                               projection_profile=projection_profile, source_url=source_url,
                               source_sha256=source_sha256, retained_sha256=retained_sha256)
    if projection_profile in ('ocd-liturgies-bcp1549-retained-members-v1', 'ocd-liturgies-bcp1559-retained-members-v1'):
        if scope_id is not None:
            return ['retained HTML BCP requires the complete declared member set']
        if projection_profile == 'ocd-liturgies-bcp1549-retained-members-v1':
            from ocd_kernel.projection.categories.liturgies_bcp1549_check import verify_document
        else:
            from ocd_kernel.projection.categories.liturgies_bcp1559_check import verify_document
        return verify_document(tei_path, rows, receipt, identity=identity, language=language,
                               representation_revision=representation_revision, edition_title=edition_title,
                               projection_profile=projection_profile, source_url=source_url,
                               source_sha256=source_sha256, retained_sha256=retained_sha256)
    if projection_profile is not None:
        from ocd_kernel.projection.categories.liturgies_bcp1662_check import PROFILE as BCP_PROFILE, verify_document as verify_bcp
        if projection_profile == BCP_PROFILE:
            if scope_id is not None:
                return ["unsupported liturgy projection profile scope"]
            return verify_bcp(tei_path, rows, receipt, identity=identity, language=language,
                              representation_revision=representation_revision,
                              edition_title=edition_title, projection_profile=projection_profile,
                              source_url=source_url, source_sha256=source_sha256,
                              retained_sha256=retained_sha256)
        from ocd_kernel.projection.categories.liturgies_office import PROFILE
        from ocd_kernel.projection.categories.liturgies_office_check import verify_document

        if projection_profile != PROFILE or scope_id is not None:
            return ["unsupported liturgy projection profile or scope"]
        return verify_document(tei_path, rows, receipt, identity=identity, language=language,
                               representation_revision=representation_revision,
                               edition_title=edition_title, projection_profile=projection_profile,
                               source_url=source_url, source_sha256=source_sha256,
                               retained_sha256=retained_sha256)
    errors: list[str] = []
    try:
        path = Path(tei_path)
        root = _parse_lxml(path)
        binding = _source_binding_lxml(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256)
        lang = _language_lxml(root, language)
        expected_rows, expected_anchors = _rows_lxml(root, identity=identity, language=lang, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id)
        inventory, warnings, exclusions = _inventory_lxml(root)
        if not isinstance(rows, list) or rows != expected_rows:
            errors.append("source correspondence: rows differ in service order, roles, branches, alternatives, identity, or text")
        if receipt is None or not isinstance(receipt, Mapping):
            errors.append("receipt is missing")
        else:
            expected = _receipt(path=path, rows=expected_rows, anchors=expected_anchors, inventory=inventory, warnings=warnings, exclusions=exclusions, source_binding=binding)
            if set(receipt) != set(expected):
                errors.append("receipt fields differ")
            for key, value in expected.items():
                if receipt.get(key) != value:
                    errors.append(f"receipt correspondence: {key}")
        validator = _validator()
        for index, row in enumerate(rows if isinstance(rows, list) else [], 1):
            for error in validator.iter_errors(row):
                errors.append(f"schema row {index}: {error.message}")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, PipelineError, etree.XMLSyntaxError) as exc:
        errors.append(str(exc))
    return errors


_ACCEPTED_IDENTITY_KEYS = ("work_id", "textual_form_id", "edition_id")


def _accepted_authority(
    root: Path,
    *,
    acceptance_path: Path,
    work_path: Path,
    master_path: Path,
    acquisition_path: Path,
) -> dict[str, dict[str, str]]:
    """Bind the accepted sidecars and master by root-relative path and bytes."""

    base = Path(root).resolve()
    bindings: dict[str, dict[str, str]] = {}
    for name, value in (
        ("acceptance", acceptance_path),
        ("work", work_path),
        ("master", master_path),
        ("acquisition", acquisition_path),
    ):
        path = Path(value).resolve()
        if not path.is_file():
            raise PipelineError(f"accepted authority file is missing: {path}")
        try:
            relative = path.relative_to(base).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PipelineError(f"accepted authority file is outside root: {path}") from exc
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise PipelineError(f"cannot read accepted authority file: {path}") from exc
        bindings[name] = {"path": relative, "sha256": digest}
    return bindings


def _bcp1662_aggregate_member(base: Path, identity: Mapping[str, str], acquisition: Mapping[str, Any], source: Mapping[str, Any], included: Any) -> dict[str, Any]:
    """Bind the named retained collection to all25 actual HTML members."""
    from ocd_kernel.projection.categories.liturgies_bcp1662 import IDENTITY as BCP_IDENTITY
    from ocd_kernel.lib.storage_topology import resolve_repo_path
    if ({key: identity.get(key) for key in _ACCEPTED_IDENTITY_KEYS} != BCP_IDENTITY
            or acquisition.get("source_kind") != "retained-member-set"
            or not isinstance(included, list) or len(included) != 25
            or len(acquisition.get("retained_files", [])) != 25):
        raise PipelineError("BCP1662 accepted retained member scope differs")
    ordered = sorted(included, key=lambda item: item["position"])
    for position, (selected, retained) in enumerate(zip(ordered, acquisition["retained_files"]), 1):
        if selected.get("position") != position or any(selected.get(k) != retained.get(k) for k in ("path", "sha256", "bytes")):
            raise PipelineError("BCP1662 accepted source membership/order differs")
        physical = resolve_repo_path(base, retained["path"])
        raw = physical.read_bytes()
        if len(raw) != retained["bytes"] or hashlib.sha256(raw).hexdigest() != retained["sha256"]:
            raise PipelineError("BCP1662 retained source member bytes differ")
    member = {"path": source["source_path"], "sha256": source["source_sha256"], "bytes": source["source_bytes"]}
    if any(source.get("source_" + k) != acquisition.get("source_" + k) for k in ("path", "sha256", "bytes")):
        raise PipelineError("BCP1662 acquired aggregate binding differs")
    return member


def _bcp_retained_html_aggregate_member(base: Path, identity: Mapping[str, str], acquisition: Mapping[str, Any], source: Mapping[str, Any], included: Any) -> dict[str, Any]:
    """Bind only the complete declared1549/1559 retained HTML member sets."""
    from ocd_kernel.library._common import io_path
    from ocd_kernel.lib.storage_topology import resolve_repo_path
    if identity.get('work_id') == 'bcp-1549':
        from ocd_kernel.projection.categories.liturgies_bcp1549 import IDENTITY, MEMBERS
    elif identity.get('work_id') == 'bcp-1559':
        from ocd_kernel.projection.categories.liturgies_bcp1559 import IDENTITY, MEMBERS
    else:
        raise PipelineError('unsupported retained HTML BCP identity')
    if ({key: identity.get(key) for key in _ACCEPTED_IDENTITY_KEYS} != IDENTITY
            or acquisition.get('source_kind') != 'retained-member-set'
            or not isinstance(included, list) or len(included) != len(MEMBERS)
            or len(acquisition.get('retained_files', [])) != len(MEMBERS)
            or any(not isinstance(item, Mapping) or not isinstance(item.get('position'), int) for item in included)):
        raise PipelineError('retained HTML BCP identity/member scope differs')
    ordered = sorted(included, key=lambda item: item['position'])
    expected_paths = {f"raw/bcp-full-text/{identity['work_id']}/{name}" for name in MEMBERS}
    if {item.get('path') for item in acquisition['retained_files']} != expected_paths:
        raise PipelineError('retained HTML BCP declared member names differ')
    for position, (selected, retained) in enumerate(zip(ordered, acquisition['retained_files']), 1):
        if selected['position'] != position or any(selected.get(key) != retained.get(key) for key in ('path', 'sha256', 'bytes')):
            raise PipelineError('retained HTML BCP acquisition membership/order differs')
        raw = io_path(resolve_repo_path(base, retained['path'])).read_bytes()
        if len(raw) != retained['bytes'] or hashlib.sha256(raw).hexdigest() != retained['sha256']:
            raise PipelineError('retained HTML BCP actual source bytes differ')
    if any(source.get('source_'+key) != acquisition.get('source_'+key) for key in ('path', 'sha256', 'bytes')):
        raise PipelineError('retained HTML BCP acquired aggregate pointer differs')
    return {'path': source['source_path'], 'sha256': source['source_sha256'], 'bytes': source['source_bytes']}


def _accepted_metadata(root: Path, acceptance_path: Path) -> dict[str, Any]:
    """Validate promotion and derive all projection context from acceptance."""

    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
    from ocd_kernel.tei.acceptance import validate_acceptance

    base = Path(root).resolve()
    accepted_path = Path(acceptance_path).resolve()
    accepted = validate_acceptance(accepted_path, root=base)
    if accepted["promotion"]["status"] != "promoted":
        raise PipelineError("liturgy projection requires a promoted accepted master")
    raw_identity = accepted.get("identity")
    if not isinstance(raw_identity, Mapping):
        raise PipelineError("accepted liturgy identity is missing")
    identity = {}
    for key in (*_ACCEPTED_IDENTITY_KEYS, "acquisition_id"):
        value = raw_identity.get(key)
        if not isinstance(value, str) or not value.strip():
            raise PipelineError(f"accepted liturgy identity is missing {key}")
        identity[key] = value
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    if (
        work.work_id != identity["work_id"]
        or edition.textual_form_id != identity["textual_form_id"]
        or edition.edition_id != identity["edition_id"]
    ):
        raise PipelineError("accepted identity does not identify the canonical liturgy edition")
    form = next(
        (
            value
            for value in work.record.get("textual_forms", [])
            if isinstance(value, Mapping)
            and value.get("textual_form_id") == edition.textual_form_id
        ),
        None,
    )
    if not isinstance(form, Mapping):
        raise PipelineError("accepted liturgy textual form is missing")
    category = edition.record.get("category", form.get("category"))
    if category != CATEGORY:
        raise PipelineError("accepted edition is not a liturgies category")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not language.strip():
        raise PipelineError("accepted liturgy edition has no language")
    acquisition_path, acquisition = acquisition_for_edition(
        base,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=identity["acquisition_id"],
    )
    source = accepted.get("source")
    scope = accepted.get("scope")
    if not isinstance(source, Mapping) or not isinstance(scope, Mapping):
        raise PipelineError("accepted liturgy source or scope is missing")
    included = scope.get("included_members")
    if identity["work_id"] == "chrysostom-divine-and-sacred-liturgy":
        from ocd_kernel.projection.categories.liturgies_chrysostom import accepted_source_member
        member = accepted_source_member(base, identity, acquisition, source, included)
    elif identity["work_id"] == "bcp-1662":
        member = _bcp1662_aggregate_member(base, identity, acquisition, source, included)
    elif identity["work_id"] in ('bcp-1549', 'bcp-1559'):
        member = _bcp_retained_html_aggregate_member(base, identity, acquisition, source, included)
    elif isinstance(included, list) and len(included) == 1 and isinstance(included[0], Mapping):
        member = included[0]
    else:
        raise PipelineError("accepted liturgy scope must identify exactly one retained source member")
    member_path = member.get("path")
    member_hash = member.get("sha256")
    member_bytes = member.get("bytes")
    if (
        not isinstance(member_path, str)
        or not member_path
        or not isinstance(member_hash, str)
        or not isinstance(member_bytes, int)
    ):
        raise PipelineError("accepted liturgy retained source member is incomplete")
    try:
        retained_path = resolve_repo_path(base, member_path)
    except (OSError, RuntimeError, ValueError, StorageTopologyError) as exc:
        raise PipelineError("accepted liturgy retained source is outside root") from exc
    if not retained_path.is_file():
        raise PipelineError(f"accepted liturgy retained source is missing: {member_path}")
    try:
        retained_bytes = retained_path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read accepted liturgy retained source: {retained_path}") from exc
    if len(retained_bytes) != member_bytes or hashlib.sha256(retained_bytes).hexdigest() != member_hash:
        raise PipelineError("accepted liturgy retained source proof is stale")
    revision = accepted.get("representation_revision")
    if not isinstance(revision, Mapping) or not isinstance(revision.get("id"), str) or not revision["id"].strip():
        raise PipelineError("accepted liturgy representation revision is missing")
    authority = _accepted_authority(
        base,
        acceptance_path=accepted_path,
        work_path=work.path,
        master_path=edition.path,
        acquisition_path=acquisition_path,
    )
    return {
        "root": base,
        "acceptance": accepted,
        "acceptance_path": accepted_path,
        "identity": {key: identity[key] for key in _ACCEPTED_IDENTITY_KEYS},
        "work": work,
        "edition": edition,
        "master_path": Path(edition.path).resolve(),
        "language": language,
        "acquisition": acquisition,
        "acquisition_path": acquisition_path,
        "source_url": acquisition.get("url"),
        "source_sha256": source.get("source_sha256"),
        "retained_path": retained_path,
        "retained_sha256": member_hash,
        "representation_revision": revision["id"],
        "authority": authority,
    }


def _accepted_office_profile(metadata: Mapping[str, Any]) -> str | None:
    """Require the declared office profile for this exact accepted work."""
    if metadata['identity']['work_id'] == 'chrysostom-divine-and-sacred-liturgy':
        from ocd_kernel.projection.categories.prose import _accepted_projection_profile
        from ocd_kernel.projection.categories.liturgies_chrysostom import PROFILE
        profile = _accepted_projection_profile(metadata['root'], {'accepted': metadata['acceptance']})
        if profile != PROFILE:
            raise PipelineError('Chrysostom accepted exact projection_profile is absent or unsupported')
        return profile
    if metadata['identity']['work_id'] in ('bcp-1549', 'bcp-1559'):
        from ocd_kernel.projection.categories.prose import _accepted_projection_profile
        expected = 'ocd-liturgies-'+metadata['identity']['work_id'].replace('-', '')+'-retained-members-v1'
        profile = _accepted_projection_profile(metadata['root'], {'accepted': metadata['acceptance']})
        if profile != expected:
            raise PipelineError('retained HTML BCP accepted exact projection_profile is absent or unsupported')
        return profile
    if metadata["identity"]["work_id"] == "bcp-1662":
        from ocd_kernel.projection.categories.prose import _accepted_projection_profile
        from ocd_kernel.projection.categories.liturgies_bcp1662 import PROFILE as BCP_PROFILE
        profile = _accepted_projection_profile(metadata["root"], {"accepted": metadata["acceptance"]})
        if profile != BCP_PROFILE:
            raise PipelineError("BCP1662 accepted exact projection_profile is absent or unsupported")
        return profile
    if metadata["identity"]["work_id"] != "convicts-visitor":
        return None
    from ocd_kernel.projection.categories.prose import _accepted_projection_profile
    from ocd_kernel.projection.categories.liturgies_office import PROFILE as OFFICE_PROFILE

    profile = _accepted_projection_profile(metadata["root"], {"accepted": metadata["acceptance"]})
    if profile is None:
        raise PipelineError("convicts-visitor accepted liturgy projection_profile is absent")
    if profile != OFFICE_PROFILE:
        raise PipelineError(f"convicts-visitor accepted liturgy projection_profile is unsupported: {profile!r}")
    return profile


def project_accepted_liturgies(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Project a promoted liturgy master using validated acceptance authority."""

    metadata = _accepted_metadata(root, acceptance_path)
    profile = _accepted_office_profile(metadata)

    result = project_liturgies_document(
        metadata["master_path"],
        identity=metadata["identity"],
        language=metadata["language"],
        representation_revision=metadata["representation_revision"],
        edition_title=metadata["edition"].title,
        source_url=metadata["source_url"],
        source_sha256=metadata["source_sha256"],
        retained_sha256=metadata["retained_sha256"],
        projection_profile=profile,
    )
    result["authority"] = dict(metadata["authority"])
    result["receipt"] = dict(result["receipt"])
    result["receipt"]["authority"] = dict(metadata["authority"])
    return result


project_accepted = project_accepted_liturgies


def verify_accepted_liturgies(
    root: Path,
    *,
    acceptance_path: Path,
    rows: list[dict[str, Any]],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted liturgy rows without invoking the producer."""

    try:
        metadata = _accepted_metadata(root, acceptance_path)
        profile = _accepted_office_profile(metadata)
        if receipt is None or not isinstance(receipt, Mapping):
            return ["accepted liturgies receipt is missing"]
        errors: list[str] = []
        if receipt.get("authority") != metadata["authority"]:
            errors.append("accepted authority bindings differ")
        document_receipt = {key: value for key, value in receipt.items() if key != "authority"}
        errors.extend(
            verify_liturgies_document(
                metadata["master_path"],
                rows,
                document_receipt,
                identity=metadata["identity"],
                language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
                source_url=metadata["source_url"],
                source_sha256=metadata["source_sha256"],
                retained_sha256=metadata["retained_sha256"],
                projection_profile=profile,
            )
        )
        return sorted(set(errors))
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
