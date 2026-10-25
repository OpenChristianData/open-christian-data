"""PIPE-012 source-bound poetry projection.

This slice maps source-named ``div`` elements to public rows.  A poem may be
one source division containing several stanza groups, or a named poem with
named child divisions.  The mapper never invents fixed-size chunks.  The
producer uses :mod:`xml.etree.ElementTree`; the verifier repeats the mapping
with lxml so a producer bug cannot make its own receipt pass.
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

from ocd_kernel.library._common import PipelineError, io_path, sha256_file


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
NS = f"{{{TEI_NS}}}"
CATEGORY = "poetry"
MAPPING_VERSION = "ocd-poetry-mapping-provisional-v2"
ASSEMBLER_VERSION = "ocd-poetry-assembler-provisional-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "v2" / "categories" / "poetry.schema.json"
COMMON_SCHEMA_PATH = SCHEMA_PATH.parents[1] / "public-row.schema.json"


class UnsupportedStructure(PipelineError):
    """A visible poetic structure is outside this slice's closed profile."""


_ATTRIBUTES: dict[str, set[str]] = {
    "TEI": {"xml:lang"},
    "teiHeader": set(),
    "revisionDesc": set(),
    "change": {"xml:id", "when"},
    "fileDesc": set(),
    "titleStmt": set(),
    "title": {"xml:id"},
    "publicationStmt": set(),
    "sourceDesc": set(),
    "bibl": {"type", "xml:id"},
    "ptr": {"type", "target", "xml:id"},
    "idno": {"type", "xml:id"},
    "p": {"xml:id", "rend", "type"},
    "text": {"xml:lang"},
    "front": {"xml:id", "type", "n"},
    "body": {"xml:id", "type", "n"},
    "back": {"xml:id", "type", "n"},
    "div": {"type", "n", "xml:id", "xml:lang"},
    "head": {"type", "xml:id"},
    "label": {"xml:id"},
    "byline": {"xml:id"},
    "author": {"xml:id"},
    "lg": {"type", "n", "xml:id"},
    "l": {"xml:id"},
    "seg": {"type", "n", "xml:id"},
    "hi": {"rend", "xml:id"},
    "foreign": {"xml:lang", "xml:id"},
    "note": {"type", "place", "n", "xml:id"},
    "pb": {"n", "xml:id"},
    "lb": {"break", "xml:id"},
}

_CHILDREN: dict[str, set[str]] = {
    "TEI": {"teiHeader", "text"},
    "teiHeader": {"fileDesc", "revisionDesc"},
    "revisionDesc": {"change"},
    "change": set(),
    "fileDesc": {"titleStmt", "publicationStmt", "sourceDesc"},
    "titleStmt": {"title"},
    "title": set(),
    "publicationStmt": {"p"},
    "sourceDesc": {"p", "bibl"},
    "bibl": {"title", "ptr", "idno", "p", "note"},
    "ptr": set(),
    "idno": set(),
    "p": {"hi", "foreign", "seg", "lb", "pb"},
    "text": {"front", "body", "back"},
    "front": {"div", "head", "label", "note", "p"},
    "body": {"div", "head", "label", "note", "p"},
    "back": {"div", "head", "label", "note", "p"},
    "div": {"head", "label", "byline", "author", "lg", "l", "div", "seg", "hi", "foreign", "note", "pb", "lb", "p"},
    "head": {"hi", "foreign", "seg"},
    "label": {"hi", "foreign", "seg"},
    "byline": {"hi", "foreign", "seg", "author"},
    "author": {"hi", "foreign", "seg"},
    "lg": {"label", "l", "pb", "lb"},
    "l": {"hi", "foreign", "seg", "lb", "pb"},
    "seg": {"hi", "foreign", "seg"},
    "hi": {"hi", "foreign", "seg"},
    "foreign": {"hi", "foreign", "seg"},
    "note": {"hi", "foreign", "seg", "p"},
    "pb": set(),
    "lb": set(),
}
_ELEMENTS = set(_ATTRIBUTES)
_CONTAINERS = {
    "TEI", "teiHeader", "fileDesc", "titleStmt", "publicationStmt", "sourceDesc", "revisionDesc",
    "text", "front", "body", "back", "div", "lg", "bibl",
}
_POEM_TYPES = {"poem", "poetry"}
_DIVISION_TYPE = "poem-division"
_STRUCTURE_TYPES = {"collection", "work", "book", "part", "section", "poem", "poetry", _DIVISION_TYPE}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
        if not isinstance(node.tag, str):
            raise UnsupportedStructure("unsupported-visible: comment or processing instruction")
        tag = _local(node.tag)
        xid = node.get(XML_ID)
        if xid:
            parts.append(f"{tag}[@xml:id='{xid}']")
        else:
            parent = parents.get(node)
            siblings = [child for child in list(parent) if _local(child.tag) == tag] if parent is not None else [node]
            parts.append(f"{tag}[{siblings.index(node) + 1 if node in siblings else 1}]")
        node = parents.get(node)
    return "/" + "/".join(reversed(parts))


def _path_lxml(root: etree._Element, target: etree._Element) -> str:
    parts: list[str] = []
    node: etree._Element | None = target
    while node is not None:
        if not isinstance(node.tag, str):
            raise UnsupportedStructure("unsupported-visible: comment or processing instruction")
        tag = etree.QName(node).localname
        xid = node.get(XML_ID)
        if xid:
            parts.append(f"{tag}[@xml:id='{xid}']")
        else:
            parent = node.getparent()
            siblings = [child for child in parent if etree.QName(child).localname == tag] if parent is not None else [node]
            parts.append(f"{tag}[{siblings.index(node) + 1 if node in siblings else 1}]")
        node = node.getparent()
    return "/" + "/".join(reversed(parts))


def _strict_et(root: ET.Element) -> None:
    if root.tag != f"{NS}TEI":
        raise UnsupportedStructure("unsupported-visible: master root must be TEI in the TEI namespace")
    ids: set[str] = set()
    for node in root.iter():
        if not isinstance(node.tag, str):
            raise UnsupportedStructure("unsupported-visible: comment or processing instruction")
        if not node.tag.startswith(NS):
            raise UnsupportedStructure(f"unsupported-visible: non-TEI element at {_path_et(root, node)}")
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
    if [_local(child.tag) for child in list(root)] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: TEI envelope order")
    header = root.find(f"{NS}teiHeader")
    text = root.find(f"{NS}text")
    if header is None or text is None or [_local(child.tag) for child in list(header)] not in (["fileDesc"], ["fileDesc", "revisionDesc"]):
        raise UnsupportedStructure("unsupported-visible: teiHeader envelope")
    if [_local(child.tag) for child in list(text)] != ["body"]:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")
    file_desc = header.find(f"{NS}fileDesc")
    if file_desc is None or [_local(child.tag) for child in list(file_desc)] != ["titleStmt", "publicationStmt", "sourceDesc"]:
        raise UnsupportedStructure("unsupported-visible: fileDesc envelope")


def _parse_et(path: Path) -> ET.Element:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read poetry TEI {path}: {exc}") from exc
    compact = raw.replace(b"\x00", b"")
    if any(token in compact.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(rb"<\?(?!xml(?:\s|\?>))", compact, flags=re.I):
        raise PipelineError("unsupported-visible: declarations, comments, or processing instructions")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PipelineError(f"invalid poetry TEI {path}: {exc}") from exc
    _strict_et(root)
    return root


def _strict_lxml(root: etree._Element) -> None:
    if not isinstance(root.tag, str) or etree.QName(root).namespace != TEI_NS or etree.QName(root).localname != "TEI":
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
            child_tag = etree.QName(child).localname
            if child_tag not in _CHILDREN[tag]:
                raise UnsupportedStructure(f"unsupported-visible: {child_tag} child of {tag}")
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
    file_desc = header.find(f"{NS}fileDesc")
    if file_desc is None or [etree.QName(child).localname for child in file_desc] != ["titleStmt", "publicationStmt", "sourceDesc"]:
        raise UnsupportedStructure("unsupported-visible: fileDesc envelope")


def _parse_lxml(path: Path) -> etree._Element:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read poetry TEI {path}: {exc}") from exc
    compact = raw.replace(b"\x00", b"")
    if any(token in compact.upper() for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")) or re.search(rb"<\?(?!xml(?:\s|\?>))", compact, flags=re.I):
        raise PipelineError("unsupported-visible: declarations, comments, or processing instructions")
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"invalid poetry TEI {path}: {exc}") from exc
    _strict_lxml(root)
    return root


def _source_binding_et(root: ET.Element, *, source_url: str | None, source_sha256: str | None, retained_sha256: str | None) -> dict[str, str | None]:
    source_desc = [node for node in root.iter() if _local(node.tag) == "sourceDesc"]
    if len(source_desc) != 1:
        raise PipelineError("poetry TEI must contain one sourceDesc")
    ptrs = [node for node in source_desc[0].iter() if _local(node.tag) == "ptr" and node.get("target")]
    if len(ptrs) != 1:
        raise PipelineError("poetry sourceDesc must contain one source URL ptr")
    actual_url = _norm(ptrs[0].get("target"))
    if source_url and actual_url != source_url:
        raise PipelineError("poetry source URL mismatch")
    values: dict[str, str] = {}
    for node in source_desc[0].iter():
        if _local(node.tag) == "idno" and node.get("type"):
            values[_norm(node.get("type")).lower()] = _norm("".join(node.itertext())).lower().removeprefix("sha256:")
    actual_source = values.get("source_sha256") or values.get("source-sha256") or values.get("sha256")
    if actual_source and not re.fullmatch(r"[0-9a-f]{64}", actual_source):
        raise PipelineError("poetry source sha256 is invalid")
    requested_source = source_sha256.lower().removeprefix("sha256:") if source_sha256 else None
    if requested_source and actual_source != requested_source:
        raise PipelineError("poetry source sha256 mismatch")
    actual_retained = values.get("retained_sha256") or values.get("retained-sha256")
    if actual_retained and not re.fullmatch(r"[0-9a-f]{64}", actual_retained):
        raise PipelineError("poetry retained sha256 is invalid")
    requested_retained = retained_sha256.lower().removeprefix("sha256:") if retained_sha256 else None
    if requested_retained and actual_retained and requested_retained != actual_retained:
        raise PipelineError("poetry retained sha256 mismatch")
    return {"source_url": actual_url, "source_sha256": actual_source or requested_source, "retained_sha256": actual_retained or requested_retained}


def _source_binding_lxml(root: etree._Element, *, source_url: str | None, source_sha256: str | None, retained_sha256: str | None) -> dict[str, str | None]:
    desc = root.xpath(".//t:sourceDesc", namespaces={"t": TEI_NS})
    if len(desc) != 1:
        raise PipelineError("poetry TEI must contain one sourceDesc")
    ptrs = desc[0].xpath(".//t:ptr[@target]", namespaces={"t": TEI_NS})
    if len(ptrs) != 1:
        raise PipelineError("poetry sourceDesc must contain one source URL ptr")
    actual_url = _norm(ptrs[0].get("target"))
    if source_url and actual_url != source_url:
        raise PipelineError("poetry source URL mismatch")
    values: dict[str, str] = {}
    for node in desc[0].xpath(".//t:idno[@type]", namespaces={"t": TEI_NS}):
        values[_norm(node.get("type")).lower()] = _norm("".join(node.itertext())).lower().removeprefix("sha256:")
    actual_source = values.get("source_sha256") or values.get("source-sha256") or values.get("sha256")
    if actual_source and not re.fullmatch(r"[0-9a-f]{64}", actual_source):
        raise PipelineError("poetry source sha256 is invalid")
    requested_source = source_sha256.lower().removeprefix("sha256:") if source_sha256 else None
    if requested_source and actual_source != requested_source:
        raise PipelineError("poetry source sha256 mismatch")
    actual_retained = values.get("retained_sha256") or values.get("retained-sha256")
    if actual_retained and not re.fullmatch(r"[0-9a-f]{64}", actual_retained):
        raise PipelineError("poetry retained sha256 is invalid")
    requested_retained = retained_sha256.lower().removeprefix("sha256:") if retained_sha256 else None
    if requested_retained and actual_retained and requested_retained != actual_retained:
        raise PipelineError("poetry retained sha256 mismatch")
    return {"source_url": actual_url, "source_sha256": actual_source or requested_source, "retained_sha256": actual_retained or requested_retained}


def _language_et(root: ET.Element, requested: str | None) -> str:
    value = requested or root.get(XML_LANG)
    if not value:
        text = next((node for node in root.iter() if _local(node.tag) == "text"), None)
        value = text.get(XML_LANG) if text is not None else None
    if not value or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise PipelineError("poetry language must be declared")
    return value


def _language_lxml(root: etree._Element, requested: str | None) -> str:
    value = requested or root.get(XML_LANG)
    if not value:
        values = root.xpath("/t:TEI/t:text/@xml:lang | /t:TEI/t:text/t:body/@xml:lang", namespaces={"t": TEI_NS, "xml": XML_NS})
        value = values[0] if values else None
    if not value or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise PipelineError("poetry language must be declared")
    return value


def _parents_et(root: ET.Element) -> dict[ET.Element, ET.Element]:
    parents: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parents[child] = node
    return parents


def _title_et(node: ET.Element) -> str | None:
    heading = next((child for child in list(node) if _local(child.tag) in {"head", "label"}), None)
    value = _norm("".join(heading.itertext())) if heading is not None else ""
    return value or None


def _title_lxml(node: etree._Element) -> str | None:
    headings = node.xpath("./t:head | ./t:label", namespaces={"t": TEI_NS})
    value = _norm("".join(headings[0].itertext())) if headings else ""
    return value or None


def _find_units_et(root: ET.Element, scope_id: str | None) -> list[ET.Element]:
    body = next((node for node in root.iter() if _local(node.tag) == "body"), None)
    if body is None:
        raise UnsupportedStructure("poetry TEI has no body")
    scope: ET.Element = body
    if scope_id:
        scope = next((node for node in body.iter() if node.get(XML_ID) == scope_id), None)
        if scope is None:
            raise UnsupportedStructure(f"poetry scope xml:id not found: {scope_id}")
    units: list[ET.Element] = []
    for node in scope.iter():
        if _local(node.tag) != "div":
            continue
        typ = node.get("type")
        if typ in _POEM_TYPES:
            child_divisions = [child for child in list(node) if _local(child.tag) == "div" and child.get("type") == _DIVISION_TYPE]
            direct_groups = [child for child in list(node) if _local(child.tag) == "lg"]
            if child_divisions and direct_groups:
                raise UnsupportedStructure("poem cannot mix direct stanza groups and poem-division children")
            if child_divisions:
                units.extend(child_divisions)
            elif direct_groups:
                units.append(node)
            else:
                raise UnsupportedStructure(f"poem {node.get(XML_ID) or '<missing id>'} has no stanza groups or named divisions")
        elif typ == _DIVISION_TYPE:
            parent = _parents_et(root).get(node)
            if parent is None or parent.get("type") not in _POEM_TYPES:
                raise UnsupportedStructure("poem-division must be a child of a poem")
    if _local(scope.tag) == "div" and scope.get("type") in _POEM_TYPES and scope not in units:
        if any(child.get("type") == _DIVISION_TYPE for child in list(scope) if _local(child.tag) == "div"):
            units = [child for child in list(scope) if _local(child.tag) == "div" and child.get("type") == _DIVISION_TYPE]
        else:
            units.insert(0, scope)
    if _local(scope.tag) == "div" and scope.get("type") == _DIVISION_TYPE and scope not in units:
        units.insert(0, scope)
    if not units:
        raise UnsupportedStructure("no source-named poem or poem division")
    return units


def _find_units_lxml(root: etree._Element, scope_id: str | None) -> list[etree._Element]:
    body_nodes = root.xpath("/t:TEI/t:text/t:body", namespaces={"t": TEI_NS})
    if len(body_nodes) != 1:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")
    body = body_nodes[0]
    scope: etree._Element = body
    if scope_id:
        matches = body.xpath(".//*[@xml:id=$id]", namespaces={"xml": XML_NS}, id=scope_id)
        if len(matches) != 1:
            raise UnsupportedStructure(f"poetry scope xml:id not found: {scope_id}")
        scope = matches[0]
    units: list[etree._Element] = []
    for node in scope.iter("{*}div"):
        typ = node.get("type")
        if typ in _POEM_TYPES:
            child_divisions = [child for child in node if etree.QName(child).localname == "div" and child.get("type") == _DIVISION_TYPE]
            direct_groups = [child for child in node if etree.QName(child).localname == "lg"]
            if child_divisions and direct_groups:
                raise UnsupportedStructure("poem cannot mix direct stanza groups and poem-division children")
            if child_divisions:
                units.extend(child_divisions)
            elif direct_groups:
                units.append(node)
            else:
                raise UnsupportedStructure(f"poem {node.get(XML_ID) or '<missing id>'} has no stanza groups or named divisions")
        elif typ == _DIVISION_TYPE:
            parent = node.getparent()
            if parent is None or parent.get("type") not in _POEM_TYPES:
                raise UnsupportedStructure("poem-division must be a child of a poem")
    if etree.QName(scope).localname == "div" and scope.get("type") in _POEM_TYPES and scope not in units:
        children = [child for child in scope if etree.QName(child).localname == "div" and child.get("type") == _DIVISION_TYPE]
        units = children if children else [scope]
    if etree.QName(scope).localname == "div" and scope.get("type") == _DIVISION_TYPE and scope not in units:
        units.insert(0, scope)
    if not units:
        raise UnsupportedStructure("no source-named poem or poem division")
    return units


def _validate_unit_et(root: ET.Element, unit: ET.Element) -> None:
    for node in unit.iter():
        if node is unit:
            continue
        kind = _local(node.tag)
        if kind not in {"head", "label", "byline", "author", "lg", "l", "seg", "hi", "foreign", "note", "pb", "lb", "div", "p"}:
            raise UnsupportedStructure(f"unsupported-visible: {kind} at {_path_et(root, node)}")
        if kind == "div" and node.get("type") != _DIVISION_TYPE:
            raise UnsupportedStructure(f"unsupported-visible: div type {node.get('type')!r} inside poem")
        if kind == "p":
            raise UnsupportedStructure(f"unsupported-visible: p inside poem at {_path_et(root, node)}")


def _validate_unit_lxml(root: etree._Element, unit: etree._Element) -> None:
    for node in unit.iter():
        if node is unit:
            continue
        kind = etree.QName(node).localname
        if kind not in {"head", "label", "byline", "author", "lg", "l", "seg", "hi", "foreign", "note", "pb", "lb", "div", "p"}:
            raise UnsupportedStructure(f"unsupported-visible: {kind} at {_path_lxml(root, node)}")
        if kind == "div" and node.get("type") != _DIVISION_TYPE:
            raise UnsupportedStructure(f"unsupported-visible: div type {node.get('type')!r} inside poem")
        if kind == "p":
            raise UnsupportedStructure(f"unsupported-visible: p inside poem at {_path_lxml(root, node)}")


def _stanzas_et(unit: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = [child for child in list(unit) if _local(child.tag) == "lg"]
    if not groups:
        raise UnsupportedStructure(f"poem division {unit.get(XML_ID) or '<missing id>'} has no stanza groups")
    stanzas: list[dict[str, Any]] = []
    source_groups: list[dict[str, Any]] = []
    for ordinal, group in enumerate(groups, 1):
        if group.get("type") not in {None, "stanza"}:
            raise UnsupportedStructure(f"unsupported-visible: lg type {group.get('type')!r} in poem")
        lines: list[str] = []
        line_ids: list[str] = []
        for child in list(group):
            kind = _local(child.tag)
            if kind == "l":
                value = _norm("".join(child.itertext()))
                if not value:
                    raise UnsupportedStructure("poem line cannot be empty")
                lines.append(value)
                line_id = child.get(XML_ID)
                if not line_id:
                    raise UnsupportedStructure("poem line has no source xml:id")
                line_ids.append(line_id)
            elif kind in {"label", "pb", "lb"}:
                continue
            else:
                raise UnsupportedStructure(f"unsupported-visible: {kind} inside poem stanza")
        if not lines:
            raise UnsupportedStructure("poem stanza has no lines")
        raw_number = group.get("n")
        try:
            number = int(raw_number) if raw_number else ordinal
        except (TypeError, ValueError) as exc:
            raise UnsupportedStructure("poem stanza number is not an integer") from exc
        if number < 1:
            raise UnsupportedStructure("poem stanza number must be positive")
        stanzas.append({"number": number, "lines": lines})
        source_groups.append({"xml_id": group.get(XML_ID), "number": number, "line_ids": line_ids})
    return stanzas, source_groups


def _stanzas_lxml(unit: etree._Element) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    groups = [child for child in unit if etree.QName(child).localname == "lg"]
    if not groups:
        raise UnsupportedStructure(f"poem division {unit.get(XML_ID) or '<missing id>'} has no stanza groups")
    stanzas: list[dict[str, Any]] = []
    source_groups: list[dict[str, Any]] = []
    for ordinal, group in enumerate(groups, 1):
        if group.get("type") not in {None, "stanza"}:
            raise UnsupportedStructure(f"unsupported-visible: lg type {group.get('type')!r} in poem")
        lines: list[str] = []
        line_ids: list[str] = []
        for child in group:
            kind = etree.QName(child).localname
            if kind == "l":
                value = _norm("".join(child.itertext()))
                if not value:
                    raise UnsupportedStructure("poem line cannot be empty")
                lines.append(value)
                line_id = child.get(XML_ID)
                if not line_id:
                    raise UnsupportedStructure("poem line has no source xml:id")
                line_ids.append(line_id)
            elif kind in {"label", "pb", "lb"}:
                continue
            else:
                raise UnsupportedStructure(f"unsupported-visible: {kind} inside poem stanza")
        if not lines:
            raise UnsupportedStructure("poem stanza has no lines")
        raw_number = group.get("n")
        try:
            number = int(raw_number) if raw_number else ordinal
        except (TypeError, ValueError) as exc:
            raise UnsupportedStructure("poem stanza number is not an integer") from exc
        if number < 1:
            raise UnsupportedStructure("poem stanza number must be positive")
        stanzas.append({"number": number, "lines": lines})
        source_groups.append({"xml_id": group.get(XML_ID), "number": number, "line_ids": line_ids})
    return stanzas, source_groups


def _ancestor_poem_et(root: ET.Element, unit: ET.Element) -> ET.Element:
    parents = _parents_et(root)
    node: ET.Element | None = unit
    while node is not None:
        if _local(node.tag) == "div" and node.get("type") in _POEM_TYPES:
            if not node.get(XML_ID):
                raise UnsupportedStructure("poem has no source xml:id")
            return node
        node = parents.get(node)
    raise UnsupportedStructure("poem division has no poem ancestor")


def _ancestor_poem_lxml(root: etree._Element, unit: etree._Element) -> etree._Element:
    node: etree._Element | None = unit
    while node is not None:
        if etree.QName(node).localname == "div" and node.get("type") in _POEM_TYPES:
            if not node.get(XML_ID):
                raise UnsupportedStructure("poem has no source xml:id")
            return node
        node = node.getparent()
    raise UnsupportedStructure("poem division has no poem ancestor")


def _locator_et(root: ET.Element, unit: ET.Element, poem: ET.Element, poem_order: int) -> dict[str, Any]:
    parents = _parents_et(root)
    chain: list[ET.Element] = []
    node: ET.Element | None = unit
    while node is not None:
        if _local(node.tag) == "div":
            chain.append(node)
        node = parents.get(node)
    chain.reverse()
    part_titles: list[str] = []
    divisions: list[dict[str, Any]] = []
    for item in chain:
        parent = parents.get(item)
        typ = item.get("type")
        siblings = [child for child in list(parent) if _local(child.tag) == "div" and child.get("type") == typ] if parent is not None else [item]
        title = _title_et(item)
        divisions.append({"order": siblings.index(item) + 1 if item in siblings else 1, "type": typ, "titles": [title] if title else []})
        if title and typ in _STRUCTURE_TYPES - {_DIVISION_TYPE}:
            part_titles.append(title)
    text_part = next((item.get("type") for item in chain if item.get("type") in {"front", "back"}), "body")
    return {"kind": "poem-division", "text_part": text_part, "part_titles": part_titles, "divisions": divisions, "poem": hashlib.sha256((poem.get(XML_ID) or "").encode()).hexdigest()[:20], "division": poem_order}


def _locator_lxml(root: etree._Element, unit: etree._Element, poem: etree._Element, poem_order: int) -> dict[str, Any]:
    chain: list[etree._Element] = []
    node: etree._Element | None = unit
    while node is not None:
        if etree.QName(node).localname == "div":
            chain.append(node)
        node = node.getparent()
    chain.reverse()
    part_titles: list[str] = []
    divisions: list[dict[str, Any]] = []
    for item in chain:
        parent = item.getparent()
        typ = item.get("type")
        siblings = [child for child in parent if etree.QName(child).localname == "div" and child.get("type") == typ] if parent is not None else [item]
        title = _title_lxml(item)
        divisions.append({"order": siblings.index(item) + 1 if item in siblings else 1, "type": typ, "titles": [title] if title else []})
        if title and typ in _STRUCTURE_TYPES - {_DIVISION_TYPE}:
            part_titles.append(title)
    text_part = next((item.get("type") for item in chain if item.get("type") in {"front", "back"}), "body")
    return {"kind": "poem-division", "text_part": text_part, "part_titles": part_titles, "divisions": divisions, "poem": hashlib.sha256((poem.get(XML_ID) or "").encode()).hexdigest()[:20], "division": poem_order}


def _unit_row_et(*, root: ET.Element, unit: ET.Element, poem: ET.Element, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, sequence: int, poem_order: int) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_unit_et(root, unit)
    division_id = unit.get(XML_ID)
    if not division_id:
        raise UnsupportedStructure(f"poem division has no xml:id at {_path_et(root, unit)}")
    poem_id = poem.get(XML_ID)
    if not poem_id:
        raise UnsupportedStructure("poem has no source xml:id")
    stanzas, source_groups = _stanzas_et(unit)
    title = _title_et(poem)
    text = "\n".join(line for stanza in stanzas for line in stanza["lines"])
    row: dict[str, Any] = {
        **{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
        "record_id": f"{identity['edition_id']}:poetry:{hashlib.sha256(division_id.encode()).hexdigest()[:20]}",
        "sequence": sequence,
        "category": CATEGORY,
        "language": language,
        "text": text,
        "representation_revision": representation_revision,
        "locator": _locator_et(root, unit, poem, poem_order),
        "provenance": {"edition_title": edition_title},
        "notes": [],
        "references": [],
        "poem_id": hashlib.sha256(poem_id.encode()).hexdigest()[:20],
        "division_id": hashlib.sha256(division_id.encode()).hexdigest()[:20],
        "stanzas": stanzas,
    }
    if title:
        row["poem_title"] = title
    line_ids = [line_id for group in source_groups for line_id in group["line_ids"]]
    anchor = {
        "record_id": row["record_id"],
        "source_xml_id": division_id,
        "poem_id": poem_id,
        "tei_path": _path_et(root, unit),
        "source_order": sequence,
        "poem_order": poem_order,
        "text_sha256": _hash_text(text),
        "text_length": len(text),
        "stanza_count": len(stanzas),
        "line_count": len(line_ids),
        "stanza_ids": [group["xml_id"] for group in source_groups],
        "line_ids": line_ids,
        "stanza_numbers": [stanza["number"] for stanza in stanzas],
        "stanza_line_counts": [len(stanza["lines"]) for stanza in stanzas],
        "poem_title": title,
    }
    return row, anchor


def _unit_row_lxml(*, root: etree._Element, unit: etree._Element, poem: etree._Element, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, sequence: int, poem_order: int) -> tuple[dict[str, Any], dict[str, Any]]:
    _validate_unit_lxml(root, unit)
    division_id = unit.get(XML_ID)
    if not division_id:
        raise UnsupportedStructure(f"poem division has no xml:id at {_path_lxml(root, unit)}")
    poem_id = poem.get(XML_ID)
    if not poem_id:
        raise UnsupportedStructure("poem has no source xml:id")
    stanzas, source_groups = _stanzas_lxml(unit)
    title = _title_lxml(poem)
    text = "\n".join(line for stanza in stanzas for line in stanza["lines"])
    row: dict[str, Any] = {
        **{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
        "record_id": f"{identity['edition_id']}:poetry:{hashlib.sha256(division_id.encode()).hexdigest()[:20]}",
        "sequence": sequence,
        "category": CATEGORY,
        "language": language,
        "text": text,
        "representation_revision": representation_revision,
        "locator": _locator_lxml(root, unit, poem, poem_order),
        "provenance": {"edition_title": edition_title},
        "notes": [],
        "references": [],
        "poem_id": hashlib.sha256(poem_id.encode()).hexdigest()[:20],
        "division_id": hashlib.sha256(division_id.encode()).hexdigest()[:20],
        "stanzas": stanzas,
    }
    if title:
        row["poem_title"] = title
    line_ids = [line_id for group in source_groups for line_id in group["line_ids"]]
    anchor = {
        "record_id": row["record_id"],
        "source_xml_id": division_id,
        "poem_id": poem_id,
        "tei_path": _path_lxml(root, unit),
        "source_order": sequence,
        "poem_order": poem_order,
        "text_sha256": _hash_text(text),
        "text_length": len(text),
        "stanza_count": len(stanzas),
        "line_count": len(line_ids),
        "stanza_ids": [group["xml_id"] for group in source_groups],
        "line_ids": line_ids,
        "stanza_numbers": [stanza["number"] for stanza in stanzas],
        "stanza_line_counts": [len(stanza["lines"]) for stanza in stanzas],
        "poem_title": title,
    }
    return row, anchor


def _rows_et(root: ET.Element, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units = _find_units_et(root, scope_id)
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    poem_orders: dict[str, int] = {}
    for sequence, unit in enumerate(units, 1):
        poem = _ancestor_poem_et(root, unit)
        poem_id = poem.get(XML_ID) or ""
        poem_orders[poem_id] = poem_orders.get(poem_id, 0) + 1
        row, anchor = _unit_row_et(root=root, unit=unit, poem=poem, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title, sequence=sequence, poem_order=poem_orders[poem_id])
        rows.append(row)
        anchors.append(anchor)
    return rows, anchors


def _rows_lxml(root: etree._Element, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units = _find_units_lxml(root, scope_id)
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    poem_orders: dict[str, int] = {}
    for sequence, unit in enumerate(units, 1):
        poem = _ancestor_poem_lxml(root, unit)
        poem_id = poem.get(XML_ID) or ""
        poem_orders[poem_id] = poem_orders.get(poem_id, 0) + 1
        row, anchor = _unit_row_lxml(root=root, unit=unit, poem=poem, identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title, sequence=sequence, poem_order=poem_orders[poem_id])
        rows.append(row)
        anchors.append(anchor)
    return rows, anchors


def _inventory_et(root: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    units = {node.get(XML_ID) for node in root.iter() if _local(node.tag) == "div" and node.get("type") in _POEM_TYPES | {_DIVISION_TYPE}}
    parents = _parents_et(root)
    inventory: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    exclusions: list[dict[str, str]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        tag = _local(node.tag)
        path = _path_et(root, node)
        in_header = False
        parent: ET.Element | None = node
        while parent is not None:
            if _local(parent.tag) == "teiHeader":
                in_header = True
                break
            parent = parents.get(parent)
        if in_header:
            role = "header-metadata"
            exclusions.append({"tei_path": path, "reason": "header-metadata"})
        elif node.get(XML_ID) in units:
            role = "mapped-poem-division"
        elif tag in {"head", "label", "byline", "author"}:
            role = "structural-heading"
            exclusions.append({"tei_path": path, "reason": "structural-heading"})
        elif tag in {"note", "pb", "lb"}:
            role = "excluded-source-detail"
            exclusions.append({"tei_path": path, "reason": "source-detail-excluded"})
        else:
            role = "mapped-poem-content" if tag in {"lg", "l"} else "structure"
        if tag == "hi":
            warnings.append({"tei_path": path, "reason": "typography-to-plain-text"})
        if tag == "foreign":
            warnings.append({"tei_path": path, "reason": "language-span-to-plain-text"})
        inventory.append({"ordinal": ordinal, "tei_path": path, "tag": tag, "role": role, "attributes": {_attribute_name(key): value for key, value in sorted(node.attrib.items())}, "text_sha256": _hash_text(_norm(node.text)), "tail_sha256": _hash_text(_norm(node.tail))})
    return inventory, warnings, exclusions


def _inventory_lxml(root: etree._Element) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    units = {node.get(XML_ID) for node in root.iter() if etree.QName(node).localname == "div" and node.get("type") in _POEM_TYPES | {_DIVISION_TYPE}}
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
        elif node.get(XML_ID) in units:
            role = "mapped-poem-division"
        elif tag in {"head", "label", "byline", "author"}:
            role = "structural-heading"
            exclusions.append({"tei_path": path, "reason": "structural-heading"})
        elif tag in {"note", "pb", "lb"}:
            role = "excluded-source-detail"
            exclusions.append({"tei_path": path, "reason": "source-detail-excluded"})
        else:
            role = "mapped-poem-content" if tag in {"lg", "l"} else "structure"
        if tag == "hi":
            warnings.append({"tei_path": path, "reason": "typography-to-plain-text"})
        if tag == "foreign":
            warnings.append({"tei_path": path, "reason": "language-span-to-plain-text"})
        inventory.append({"ordinal": ordinal, "tei_path": path, "tag": tag, "role": role, "attributes": {_attribute_name(key): value for key, value in sorted(node.attrib.items())}, "text_sha256": _hash_text(_norm(node.text)), "tail_sha256": _hash_text(_norm(node.tail))})
    return inventory, warnings, exclusions


def _validator() -> jsonschema.Draft202012Validator:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        common = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
        registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
        native = json.loads((SCHEMA_PATH.parents[1] / 'native-content.schema.json').read_text(encoding='utf-8'))
        registry = registry.with_resource(native['$id'], Resource.from_contents(native, default_specification=DRAFT202012))
        validator = projection_validator(schema, registry=registry)
        validator.check_schema(schema)
        return validator
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise PipelineError(f"invalid poetry schema package: {exc}") from exc


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        found = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if found:
            raise PipelineError(f"invalid poetry public row {row.get('record_id', index)}: {found[0].message}")


def _receipt(*, path: Path, rows: list[dict[str, Any]], anchors: list[dict[str, Any]], inventory: list[dict[str, Any]], warnings: list[dict[str, str]], exclusions: list[dict[str, str]], source_binding: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        "mapping_version": MAPPING_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "master_sha256": sha256_file(path),
        "source_binding": dict(source_binding),
        "policy_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
        "common_schema_sha256": hashlib.sha256(COMMON_SCHEMA_PATH.read_bytes()).hexdigest(),
        "output_sha256": hashlib.sha256(_canonical(rows)).hexdigest(),
        "row_count": len(rows),
        "anchors": anchors,
        "inventory": inventory,
        "warnings": warnings,
        "exclusions": exclusions,
        "unsupported": [],
        "independent_check": {"status": "pending"},
    }


def _require_identity(identity: Mapping[str, str]) -> None:
    required = {"work_id", "textual_form_id", "edition_id"}
    if set(identity) != required or any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise PipelineError("poetry identity requires work_id, textual_form_id, and edition_id")


def project_poetry_document(
    tei_path: Path,
    *,
    identity: Mapping[str, str],
    language: str | None = None,
    representation_revision: str,
    edition_title: str,
    scope_id: str | None = None,
    source_url: str | None = None,
    source_sha256: str | None = None,
    retained_sha256: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Project source-named poems and divisions into closed public rows."""
    _require_identity(identity)
    path = Path(tei_path)
    root = _parse_et(path)
    binding = _source_binding_et(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256)
    lang = _language_et(root, language)
    rows, anchors = _rows_et(root, identity=identity, language=lang, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id)
    _validate_rows(rows)
    inventory, warnings, exclusions = _inventory_et(root)
    receipt = _receipt(path=path, rows=rows, anchors=anchors, inventory=inventory, warnings=warnings, exclusions=exclusions, source_binding=binding)
    return {
        "rows": rows,
        "receipt": receipt,
        "mapping_version": MAPPING_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "master_sha256": receipt["master_sha256"],
        "source_binding": binding,
        "scope_id": scope_id,
        "anchors": anchors,
        "inventory": inventory,
        "warnings": warnings,
        "exclusions": exclusions,
        "unsupported": [],
        "independent_check": receipt["independent_check"],
    }


project = project_poetry_document


def verify_poetry_document(
    tei_path: Path,
    rows: list[dict[str, Any]],
    receipt: Mapping[str, Any] | None = None,
    *,
    identity: Mapping[str, str],
    language: str | None = None,
    representation_revision: str,
    edition_title: str,
    scope_id: str | None = None,
    source_url: str | None = None,
    source_sha256: str | None = None,
    retained_sha256: str | None = None,
    **_: Any,
) -> list[str]:
    """Recompute rows and the complete receipt with an independent lxml walk."""
    errors: list[str] = []
    try:
        _require_identity(identity)
        path = Path(tei_path)
        root = _parse_lxml(path)
        binding = _source_binding_lxml(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256)
        lang = _language_lxml(root, language)
        expected_rows, expected_anchors = _rows_lxml(root, identity=identity, language=lang, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id)
        expected_inventory, expected_warnings, expected_exclusions = _inventory_lxml(root)
        if not isinstance(rows, list) or rows != expected_rows:
            errors.append("source correspondence: rows differ in poem identity, order, stanza/line structure, locator, or text")
        if receipt is None or not isinstance(receipt, Mapping):
            errors.append("receipt is missing")
        else:
            expected = _receipt(path=path, rows=expected_rows, anchors=expected_anchors, inventory=expected_inventory, warnings=expected_warnings, exclusions=expected_exclusions, source_binding=binding)
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


verify_document = verify_poetry_document


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
        raise PipelineError("poetry projection requires a promoted accepted master")
    raw_identity = accepted.get("identity")
    if not isinstance(raw_identity, Mapping):
        raise PipelineError("accepted poetry identity is missing")
    identity = {}
    for key in (*_ACCEPTED_IDENTITY_KEYS, "acquisition_id"):
        value = raw_identity.get(key)
        if not isinstance(value, str) or not value.strip():
            raise PipelineError(f"accepted poetry identity is missing {key}")
        identity[key] = value
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    if (
        work.work_id != identity["work_id"]
        or edition.textual_form_id != identity["textual_form_id"]
        or edition.edition_id != identity["edition_id"]
    ):
        raise PipelineError("accepted identity does not identify the canonical poetry edition")
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
        raise PipelineError("accepted poetry textual form is missing")
    category = edition.record.get("category", form.get("category"))
    if category != CATEGORY:
        raise PipelineError("accepted edition is not a poetry category")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not language.strip():
        raise PipelineError("accepted poetry edition has no language")
    acquisition_path, acquisition = acquisition_for_edition(
        base,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=identity["acquisition_id"],
    )
    source = accepted.get("source")
    scope = accepted.get("scope")
    if not isinstance(source, Mapping) or not isinstance(scope, Mapping):
        raise PipelineError("accepted poetry source or scope is missing")
    included = scope.get("included_members")
    if not isinstance(included, list) or len(included) != 1 or not isinstance(included[0], Mapping):
        raise PipelineError("accepted poetry scope must identify exactly one retained source member")
    member = included[0]
    member_path = member.get("path")
    member_hash = member.get("sha256")
    member_bytes = member.get("bytes")
    if (
        not isinstance(member_path, str)
        or not member_path
        or not isinstance(member_hash, str)
        or not isinstance(member_bytes, int)
    ):
        raise PipelineError("accepted poetry retained source member is incomplete")
    try:
        retained_path = resolve_repo_path(base, member_path)
    except (OSError, RuntimeError, ValueError, StorageTopologyError) as exc:
        raise PipelineError("accepted poetry retained source is outside root") from exc
    if not retained_path.is_file():
        raise PipelineError(f"accepted poetry retained source is missing: {member_path}")
    try:
        retained_bytes = retained_path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read accepted poetry retained source: {retained_path}") from exc
    if len(retained_bytes) != member_bytes or hashlib.sha256(retained_bytes).hexdigest() != member_hash:
        raise PipelineError("accepted poetry retained source proof is stale")
    revision = accepted.get("representation_revision")
    if not isinstance(revision, Mapping) or not isinstance(revision.get("id"), str) or not revision["id"].strip():
        raise PipelineError("accepted poetry representation revision is missing")
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


def _uses_native_edition(path: Path) -> bool:
    """Keep complete editions intact unless they use the explicit poem profile.

    The existing stanza profile describes named poem divisions. A whole edition
    with front/back matter or native book divisions uses ordered native units.
    Selection is structural, never a fallback after a failed verification.
    """
    try:
        root = ET.parse(io_path(path)).getroot()
    except ET.ParseError as exc:
        raise PipelineError('invalid poetry XML') from exc
    if root.tag == NS + 'teiCorpus':
        return True
    text = root.find(NS + 'text')
    if text is None:
        raise PipelineError('poetry edition has no text')
    return (text.find(NS + 'front') is not None or text.find(NS + 'back') is not None
            or not any(node.get('type') == 'poem' for node in text.iter(NS + 'div')))


def project_accepted_poetry(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Project a promoted poetry master using validated acceptance authority."""

    from ocd_kernel.projection.categories.sermons import _accepted_context
    context = _accepted_context(root, acceptance_path, expected_category='poetry')
    if _uses_native_edition(context['edition'].path):
        from ocd_kernel.projection.categories.native_documents import project_accepted_document
        return project_accepted_document(root, acceptance_path=acceptance_path, category='poetry')
    metadata = _accepted_metadata(root, acceptance_path)
    result = project_poetry_document(
        metadata["master_path"],
        identity=metadata["identity"],
        language=metadata["language"],
        representation_revision=metadata["representation_revision"],
        edition_title=metadata["edition"].title,
        source_url=metadata["source_url"],
        source_sha256=metadata["source_sha256"],
        retained_sha256=metadata["retained_sha256"],
    )
    result["authority"] = dict(metadata["authority"])
    result["receipt"] = dict(result["receipt"])
    result["receipt"]["authority"] = dict(metadata["authority"])
    return result


project_accepted = project_accepted_poetry


def verify_accepted_poetry(
    root: Path,
    *,
    acceptance_path: Path,
    rows: list[dict[str, Any]],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted poetry rows without invoking the producer."""

    try:
        from ocd_kernel.projection.categories.sermons import _accepted_context
        context = _accepted_context(root, acceptance_path, expected_category='poetry')
        if _uses_native_edition(context['edition'].path):
            from ocd_kernel.projection.categories.native_documents import verify_accepted_document
            return verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category='poetry')
        metadata = _accepted_metadata(root, acceptance_path)
        if receipt is None or not isinstance(receipt, Mapping):
            return ["accepted poetry receipt is missing"]
        errors: list[str] = []
        if receipt.get("authority") != metadata["authority"]:
            errors.append("accepted authority bindings differ")
        document_receipt = {key: value for key, value in receipt.items() if key != "authority"}
        errors.extend(
            verify_poetry_document(
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
            )
        )
        return sorted(set(errors))
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
