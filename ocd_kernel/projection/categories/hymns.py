"""PIPE-010 source-bound hymn occurrence projection.

The input is a deliberately closed TEI profile. A row represents an
occurrence in a hymnal and keeps its source-derived hymn text identity apart
from occurrence metadata such as a tune or hymnal setting. The checker below
re-reads the TEI with a separate lxml traversal; it never calls the producer.
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
CATEGORY = "hymns"
MAPPING_VERSION = "ocd-hymns-mapping-provisional-v4"
ASSEMBLER_VERSION = "ocd-hymns-assembler-provisional-v1"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "v2" / "categories" / "hymns.schema.json"
COMMON_SCHEMA_PATH = SCHEMA_PATH.parents[1] / "public-row.schema.json"
NATIVE_SCHEMA_PATH = SCHEMA_PATH.parents[1] / "native-content.schema.json"


class UnsupportedStructure(PipelineError):
    """The selected source contains a visible feature outside this slice."""


_ATTRIBUTES: dict[str, set[str]] = {
    "TEI": {"xml:lang", "xml:id"},
    "teiHeader": set(),
    "revisionDesc": set(),
    "change": {"xml:id", "when"},
    "fileDesc": set(),
    "titleStmt": set(),
    "title": {"xml:id"},
    "publicationStmt": set(),
    "sourceDesc": set(),
    "p": {"xml:id"},
    "ptr": {"type", "target", "xml:id"},
    "idno": {"type", "xml:id"},
    "source": {"xml:id"},
    "text": {"xml:lang"},
    "front": {"xml:id", "type", "n"},
    "body": {"xml:id", "xml:lang", "type", "n"},
    "back": {"xml:id", "type", "n"},
    "div": {"type", "n", "xml:id", "corresp", "sameAs", "xml:lang"},
    "head": {"type", "xml:id"},
    "note": {"type", "place", "n", "xml:id"},
    "lg": {"type", "n", "xml:id"},
    "l": {"xml:id"},
    "label": {"xml:id"},
    "seg": {"type", "rend", "xml:id"},
    "hi": {"rend", "xml:id"},
    "foreign": {"xml:lang", "xml:id"},
    "pb": {"n", "xml:id"},
    "lb": {"break", "xml:id"},
    "ref": {"type", "target", "xml:id"},
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
    "sourceDesc": {"p", "ptr", "idno", "source", "note"},
    "source": {"ptr", "idno", "p"},
    "ptr": set(),
    "idno": set(),
    "text": {"front", "body", "back"},
    "front": {"div", "head", "note"},
    "body": {"div", "head", "note"},
    "back": {"div", "head", "note"},
    "div": {"div", "head", "note", "lg", "ref"},
    "head": {"hi", "seg", "foreign"},
    "note": {"hi", "seg", "foreign", "ref"},
    "lg": {"label", "l", "note"},
    "l": {"hi", "seg", "foreign", "ref", "lb"},
    "label": {"hi", "seg", "foreign"},
    "seg": {"hi", "seg", "foreign"},
    "hi": {"seg", "foreign"},
    "foreign": {"hi", "seg"},
    "p": {"hi", "seg", "foreign", "ref", "ptr", "idno", "lb"},
    "pb": set(),
    "lb": set(),
    "ref": {"hi", "seg", "foreign"},
}

_ELEMENTS = set(_ATTRIBUTES)
_CONTAINERS = {
    "TEI", "teiHeader", "fileDesc", "titleStmt", "publicationStmt", "sourceDesc", "revisionDesc",
    "source", "text", "front", "body", "back", "div", "lg",
}
_METADATA_NOTE_TYPES = {
    "tune", "contributor", "author", "author-birth", "author-death", "year-written",
    "hymnal", "edition", "rights-text", "rights-tune",
}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _metadata_norm(value: str | None) -> str:
    """Trim source metadata while retaining meaningful internal spacing."""
    return re.sub(r"[ \t]*\r?\n[ \t]*", " ", value or "").strip()


def _derived_text_identity(title: str | None, contributor: str | None, text: str) -> str:
    """Derive a stable text-version key from title, contributor, and wording."""
    value = re.sub(r"[^a-z0-9]+", "-", (title or "").casefold()).strip("-")
    if not value:
        raise UnsupportedStructure("hymn occurrence has no title from which to derive text identity")
    basis = f"{_norm(title).casefold()}\n{_norm(contributor).casefold()}\n{text}".encode("utf-8")
    return f"text-{value}-{hashlib.sha256(basis).hexdigest()[:16]}"


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
    pieces: list[str] = []
    node: ET.Element | None = target
    while node is not None:
        tag = _local(node.tag)
        xid = node.get(XML_ID)
        if xid:
            pieces.append(f"{tag}[@xml:id='{xid}']")
        else:
            parent = parents.get(node)
            siblings = [c for c in list(parent) if _local(c.tag) == tag] if parent is not None else [node]
            pieces.append(f"{tag}[{siblings.index(node) + 1}]")
        node = parents.get(node)
    return "/" + "/".join(reversed(pieces))


def _path_lxml(root: etree._Element, target: etree._Element) -> str:
    pieces: list[str] = []
    node: etree._Element | None = target
    while node is not None:
        tag = etree.QName(node).localname
        xid = node.get(XML_ID)
        if xid:
            pieces.append(f"{tag}[@xml:id='{xid}']")
        else:
            parent = node.getparent()
            siblings = [c for c in parent if etree.QName(c).localname == tag] if parent is not None else [node]
            pieces.append(f"{tag}[{siblings.index(node) + 1}]")
        node = node.getparent()
    return "/" + "/".join(reversed(pieces))


def _parse_et(path: Path) -> ET.Element:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read hymn TEI {path}: {exc}") from exc
    compact = raw.replace(b"\x00", b"").upper()
    if any(token in compact for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")):
        raise PipelineError("unsupported-visible: declarations or comments")
    if re.search(rb"<\?(?!xml(?:\s|\?>))", compact, flags=re.I):
        raise PipelineError("unsupported-visible: processing instruction")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    except ET.ParseError as exc:
        raise PipelineError(f"invalid hymn TEI {path}: {exc}") from exc
    _strict_et(root)
    return root


def _strict_et(root: ET.Element) -> None:
    if root.tag != f"{NS}TEI":
        raise UnsupportedStructure("unsupported-visible: master root must be TEI in the TEI namespace")
    seen_ids: set[str] = set()
    for node in root.iter():
        if not isinstance(node.tag, str) or not node.tag.startswith(NS):
            raise UnsupportedStructure("unsupported-visible: non-TEI element or processing instruction")
        tag = _local(node.tag)
        if tag not in _ELEMENTS:
            raise UnsupportedStructure(f"unsupported-visible: element {tag} at {_path_et(root, node)}")
        actual_attrs = {_attribute_name(key) for key in node.attrib}
        unknown = actual_attrs - _ATTRIBUTES[tag]
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {tag} attribute {sorted(unknown)[0]}")
        xid = node.get(XML_ID)
        if xid:
            if xid in seen_ids:
                raise UnsupportedStructure(f"duplicate source xml:id: {xid}")
            seen_ids.add(xid)
        children = list(node)
        for child in children:
            if not isinstance(child.tag, str) or not child.tag.startswith(NS):
                raise UnsupportedStructure(f"unsupported-visible: non-TEI child at {_path_et(root, node)}")
            child_tag = _local(child.tag)
            if child_tag not in _CHILDREN[tag]:
                raise UnsupportedStructure(f"unsupported-visible: {child_tag} child of {tag} at {_path_et(root, node)}")
        if tag in _CONTAINERS and _norm(node.text):
            raise UnsupportedStructure(f"unsupported-visible: loose text in {tag} at {_path_et(root, node)}")
        if tag in _CONTAINERS:
            for child in children:
                if _norm(child.tail):
                    raise UnsupportedStructure(f"unsupported-visible: loose tail after child at {_path_et(root, node)}")
    if [child.tag for child in list(root)] != [f"{NS}teiHeader", f"{NS}text"]:
        raise UnsupportedStructure("unsupported-visible: TEI envelope order")
    header = root.find(f"{NS}teiHeader")
    text = root.find(f"{NS}text")
    if header is None or text is None or [c.tag for c in list(header)] not in ([f"{NS}fileDesc"], [f"{NS}fileDesc", f"{NS}revisionDesc"]):
        raise UnsupportedStructure("unsupported-visible: teiHeader envelope")
    if [c.tag for c in list(text)] != [f"{NS}body"]:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")


def _source_binding_et(root: ET.Element, *, source_url: str | None, source_sha256: str | None, retained_sha256: str | None, retained_path: Path | None) -> dict[str, str | None]:
    source_desc = next((n for n in root.iter() if _local(n.tag) == "sourceDesc"), None)
    if source_desc is None:
        raise PipelineError("hymn TEI must contain sourceDesc")
    ptrs = [n for n in source_desc.iter() if _local(n.tag) == "ptr" and n.get("target")]
    ids = [n for n in source_desc.iter() if _local(n.tag) == "idno" and n.get("type")]
    actual_url = ptrs[0].get("target") if ptrs else None
    if source_url and actual_url != source_url:
        raise PipelineError(f"hymn source URL mismatch: {actual_url!r} != {source_url!r}")
    actual_hash = None
    for item in ids:
        if _norm(item.get("type")).lower() in {"source_sha256", "sha256", "source-sha256"}:
            actual_hash = _norm("".join(item.itertext())).lower().removeprefix("sha256:")
            break
    if actual_hash and not re.fullmatch(r"[0-9a-f]{64}", actual_hash):
        raise PipelineError("hymn source sha256 is invalid")
    requested_hash = source_sha256.lower().removeprefix("sha256:") if source_sha256 else None
    if requested_hash and actual_hash != requested_hash:
        raise PipelineError("hymn source sha256 mismatch")
    if retained_sha256 is not None:
        if retained_path is None:
            raise PipelineError("retained source path is required for retained_sha256")
        observed_retained = hashlib.sha256(Path(retained_path).read_bytes()).hexdigest()
        if retained_sha256 != observed_retained:
            raise PipelineError("retained source sha256 mismatch")
    return {"source_url": actual_url or source_url, "source_sha256": actual_hash or requested_hash, "retained_sha256": retained_sha256}


def _language_et(root: ET.Element, requested: str | None) -> str:
    value = requested or root.get(XML_LANG)
    if not value:
        value = next((n.get(XML_LANG) for n in root.iter() if _local(n.tag) in {"text", "body"} and n.get(XML_LANG)), None)
    if not value or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise PipelineError("hymn language must be declared")
    return value


def _ancestors_et(root: ET.Element, target: ET.Element) -> list[ET.Element]:
    parents: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parents[child] = node
    chain: list[ET.Element] = []
    node: ET.Element | None = target
    while node is not None:
        if _local(node.tag) == "div":
            chain.append(node)
        node = parents.get(node)
    return list(reversed(chain))


def _locator_et(root: ET.Element, unit: ET.Element, occurrence: int) -> dict[str, Any]:
    chain = _ancestors_et(root, unit)
    text_part = "body"
    titles: list[str] = []
    divisions: list[dict[str, Any]] = []
    parents: dict[ET.Element, ET.Element] = {}
    for node in root.iter():
        for child in list(node):
            parents[child] = node
    for item in chain:
        parent = parents.get(item)
        siblings = [c for c in list(parent) if _local(c.tag) == "div" and c.get("type") == item.get("type")] if parent is not None else [item]
        title_node = next((c for c in list(item) if _local(c.tag) in {"head", "label"}), None)
        title = _norm("".join(title_node.itertext())) if title_node is not None else None
        divisions.append({"order": siblings.index(item) + 1, "type": item.get("type"), "titles": [title] if title else []})
        if title and item.get("type") in {"collection", "work", "book", "part", "section"}:
            titles.append(title)
    for ancestor in chain:
        if ancestor.get("type") in {"front", "back"}:
            text_part = ancestor.get("type")
    return {"kind": "hymn-occurrence", "text_part": text_part, "part_titles": titles, "divisions": divisions, "occurrence": occurrence}


def _note_values(unit: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for note in list(unit):
        if _local(note.tag) != "note":
            continue
        typ = _norm(note.get("type")).lower()
        if typ not in _METADATA_NOTE_TYPES:
            raise UnsupportedStructure(f"unsupported-visible: hymn note type {typ or '<missing>'}")
        value = _metadata_norm("".join(note.itertext()))
        if value:
            if typ in values:
                raise UnsupportedStructure(f"duplicate hymn metadata note type: {typ}")
            values[typ] = value
    return values


def _line_et(node: ET.Element) -> str:
    value = _norm("".join(node.itertext()))
    if not value:
        raise UnsupportedStructure("hymn line cannot be empty")
    return value


def _lg_et(node: ET.Element, *, number: int | None = None) -> dict[str, Any]:
    lines: list[str] = []
    label: str | None = None
    for child in list(node):
        tag = _local(child.tag)
        if tag == "l":
            lines.append(_line_et(child))
        elif tag == "label":
            if label is not None:
                raise UnsupportedStructure("hymn refrain has multiple labels")
            label = _norm("".join(child.itertext())) or None
        elif tag == "note":
            raise UnsupportedStructure("unsupported-visible: note inside stanza/refrain")
        else:
            raise UnsupportedStructure(f"unsupported-visible: {tag} inside stanza/refrain")
    if not lines:
        raise UnsupportedStructure("hymn stanza or refrain has no lines")
    result: dict[str, Any] = {"lines": lines}
    if number is not None:
        result["number"] = number
    else:
        result["label"] = label
    return result


def _units_et(root: ET.Element, scope_id: str | None) -> list[ET.Element]:
    body = next((n for n in root.iter() if _local(n.tag) == "body"), None)
    if body is None:
        raise UnsupportedStructure("hymn TEI has no body")
    scope: ET.Element = body
    if scope_id:
        scope = next((n for n in body.iter() if n.get(XML_ID) == scope_id), None)
        if scope is None:
            raise UnsupportedStructure(f"hymn scope xml:id not found: {scope_id}")
    units = [n for n in scope.iter() if _local(n.tag) == "div" and n.get("type") == "hymn"]
    if _local(scope.tag) == "div" and scope.get("type") == "hymn" and scope not in units:
        units.insert(0, scope)
    if not units:
        raise UnsupportedStructure("no source-defined hymn occurrence")
    return units


def _inventory_et(root: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        tag = _local(node.tag)
        path = _path_et(root, node)
        in_header = any(_local(parent.tag) == "teiHeader" for parent in _ancestors_all_et(root, node))
        role = "header-metadata" if in_header else "mapped-source"
        if tag in {"pb", "lb"} and not in_header:
            role = "milestone"
            exclusions.append({"tei_path": path, "reason": "milestone-omitted"})
        elif in_header:
            exclusions.append({"tei_path": path, "reason": "header-metadata"})
        if tag == "hi" and not in_header:
            warnings.append({"tei_path": path, "reason": "typography-to-plain-text"})
        inventory.append({
            "ordinal": ordinal,
            "tei_path": path,
            "tag": tag,
            "role": role,
            "attributes": {_attribute_name(k): v for k, v in sorted(node.attrib.items())},
            "text_sha256": _hash_text(_norm(node.text)),
            "tail_sha256": _hash_text(_norm(node.tail)),
        })
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


def _rows_et(root: ET.Element, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    parents = {child: parent for parent in root.iter() for child in parent}
    for sequence, unit in enumerate(_units_et(root, scope_id), 1):
        declaration = unit
        while declaration is not None and XML_LANG not in declaration.attrib:
            declaration = parents.get(declaration)
        unit_language = declaration.get(XML_LANG) if declaration is not None else language
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", unit_language):
            raise UnsupportedStructure("unsupported-visible: invalid hymn occurrence language")
        occurrence_id = unit.get(XML_ID)
        if not occurrence_id:
            raise UnsupportedStructure(f"hymn occurrence has no xml:id at {_path_et(root, unit)}")
        title_node = next((n for n in list(unit) if _local(n.tag) == "head" and n.get("type", "title") == "title"), None)
        title = _norm("".join(title_node.itertext())) if title_node is not None else None
        author_node = next((n for n in list(unit) if _local(n.tag) == "note" and _norm(n.get("type")).lower() in {"author", "contributor"}), None)
        contributor_hint = _norm("".join(author_node.itertext())) if author_node is not None else None
        explicit_text_id = _norm(unit.get("corresp") or unit.get("sameAs")).lstrip("#")
        stanzas: list[dict[str, Any]] = []
        refrain: dict[str, Any] | None = None
        segments: list[dict[str, Any]] = []
        for child in list(unit):
            tag = _local(child.tag)
            if tag == "lg":
                kind = child.get("type", "stanza")
                if kind == "stanza":
                    raw_number = child.get("n")
                    try:
                        number = int(raw_number) if raw_number else len(stanzas) + 1
                    except (TypeError, ValueError) as exc:
                        raise UnsupportedStructure(f"hymn stanza number is not an integer: {raw_number}") from exc
                    if number < 1:
                        raise UnsupportedStructure("hymn stanza number must be positive")
                    value = _lg_et(child, number=number)
                    stanza = {"number": number, "lines": value["lines"]}
                    stanzas.append(stanza)
                    segments.append({"kind": "stanza", "number": number, "lines": value["lines"]})
                elif kind == "refrain":
                    if refrain is not None:
                        raise UnsupportedStructure("multiple refrain bodies require an explicit reviewed mapping")
                    value = _lg_et(child)
                    refrain = {"label": value.get("label"), "lines": value["lines"]}
                    segments.append({"kind": "refrain", "label": value.get("label"), "lines": value["lines"]})
                elif kind == "refrain-marker":
                    label = _norm("".join(child.itertext())) if list(child) else _norm(child.text)
                    if not label:
                        raise UnsupportedStructure("hymn refrain marker has no label")
                    segments.append({"kind": "refrain-marker", "label": label})
                else:
                    raise UnsupportedStructure(f"unsupported-visible: lg type {kind!r}")
            elif tag in {"head", "note"}:
                continue
            else:
                raise UnsupportedStructure(f"unsupported-visible: {tag} in hymn occurrence")
        if not stanzas:
            raise UnsupportedStructure(f"hymn occurrence {occurrence_id} has no stanzas")
        first_line = stanzas[0]["lines"][0]
        notes = _note_values(unit)
        setting = None
        if "hymnal" in notes or "edition" in notes:
            setting = {"title": notes.get("hymnal"), "edition": notes.get("edition")}
        rights = None
        if "rights-text" in notes or "rights-tune" in notes:
            rights = {"text": notes.get("rights-text"), "tune": notes.get("rights-tune")}
        text = "\n".join(line for segment in segments if "lines" in segment for line in segment["lines"])
        text_id = explicit_text_id or _derived_text_identity(title, contributor_hint, text)
        locator = _locator_et(root, unit, sequence)
        row: dict[str, Any] = {
            **{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
            "record_id": f"{identity['edition_id']}:hymn:{hashlib.sha256(occurrence_id.encode()).hexdigest()[:20]}",
            "sequence": sequence,
            "category": CATEGORY,
            "language": unit_language,
            "text": text,
            "representation_revision": representation_revision,
            "locator": locator,
            "provenance": {"edition_title": edition_title},
            "notes": [],
            "references": [],
            "occurrence_id": hashlib.sha256(occurrence_id.encode()).hexdigest()[:20],
            "hymn_text_id": text_id,
            "first_line": first_line,
            "stanzas": stanzas,
            "segments": segments,
        }
        if title:
            row["title"] = title
        if notes.get("tune"):
            row["tune"] = notes["tune"]
        if notes.get("contributor") or notes.get("author"):
            row["contributor"] = notes.get("contributor") or notes.get("author")
        if notes.get("author-birth"):
            row["author_birth"] = notes["author-birth"]
        if notes.get("author-death"):
            row["author_death"] = notes["author-death"]
        if notes.get("year-written"):
            row["year_written"] = notes["year-written"]
        if setting:
            row["hymnal_setting"] = setting
        if refrain:
            row["refrain"] = refrain
        if rights:
            row["rights"] = rights
        rows.append(row)
        anchors.append({
            "record_id": row["record_id"],
            "source_xml_id": occurrence_id,
            "hymn_text_id": text_id,
            "source_order": sequence,
            "tei_path": _path_et(root, unit),
            "text_sha256": _hash_text(text),
            "text_length": len(text),
            "stanza_count": len(stanzas),
            "stanza_line_counts": [len(item["lines"]) for item in stanzas],
            "refrain_line_count": len(refrain["lines"]) if refrain else 0,
            "refrain_marker_count": sum(1 for item in segments if item["kind"] == "refrain-marker"),
            "segment_kinds": [item["kind"] for item in segments],
            "title": title,
            "first_line": first_line,
            "tune": notes.get("tune"),
            "contributor": notes.get("contributor") or notes.get("author"),
            "author_birth": notes.get("author-birth"),
            "author_death": notes.get("author-death"),
            "year_written": notes.get("year-written"),
            "hymnal_setting": setting,
        })
    return rows, anchors


def _validator() -> jsonschema.Draft202012Validator:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        common = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))
        native = json.loads(NATIVE_SCHEMA_PATH.read_text(encoding="utf-8"))
        registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
        registry = registry.with_resource(native["$id"], Resource.from_contents(native, default_specification=DRAFT202012))
        validator = projection_validator(schema, registry=registry)
        validator.check_schema(schema)
        return validator
    except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise PipelineError(f"invalid hymn schema package: {exc}") from exc


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"invalid hymn public row {row.get('record_id', index)}: {errors[0].message}")


def _receipt(*, tei_path: Path, rows: list[dict[str, Any]], anchors: list[dict[str, Any]], inventory: list[dict[str, Any]], warnings: list[dict[str, str]], exclusions: list[dict[str, str]], source_binding: Mapping[str, str | None]) -> dict[str, Any]:
    return {
        "mapping_version": MAPPING_VERSION,
        "assembler_version": ASSEMBLER_VERSION,
        "master_sha256": sha256_file(tei_path),
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


def project_hymns_document(
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
    retained_path: Path | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Project complete source-defined hymn occurrences into closed rows."""
    required = {"work_id", "textual_form_id", "edition_id"}
    if set(identity) != required or any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise PipelineError("hymn identity requires work_id, textual_form_id, and edition_id")
    path = Path(tei_path)
    root = _parse_et(path)
    binding = _source_binding_et(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256, retained_path=retained_path)
    lang = _language_et(root, language)
    rows, anchors = _rows_et(root, identity=identity, language=lang, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id)
    _validate_rows(rows)
    inventory, warnings, exclusions = _inventory_et(root)
    receipt = _receipt(tei_path=path, rows=rows, anchors=anchors, inventory=inventory, warnings=warnings, exclusions=exclusions, source_binding=binding)
    # The duplicated top-level fields keep the provisional document entrypoint
    # compatible with earlier category experiments; receipt is authoritative.
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


project = project_hymns_document


def _parse_lxml(path: Path) -> etree._Element:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read hymn TEI {path}: {exc}") from exc
    compact = raw.replace(b"\x00", b"").upper()
    if any(token in compact for token in (b"<!DOCTYPE", b"<!ENTITY", b"<!--")):
        raise PipelineError("unsupported-visible: declarations or comments")
    if re.search(rb"<\?(?!xml(?:\s|\?>))", compact, flags=re.I):
        raise PipelineError("unsupported-visible: processing instruction")
    try:
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"invalid hymn TEI {path}: {exc}") from exc
    _strict_lxml(root)
    return root


def _strict_lxml(root: etree._Element) -> None:
    if etree.QName(root).namespace != TEI_NS:
        raise UnsupportedStructure("unsupported-visible: master root must be TEI in the TEI namespace")
    seen_ids: set[str] = set()
    for node in root.iter():
        if not isinstance(node.tag, str):
            raise UnsupportedStructure("unsupported-visible: comment or processing instruction")
        qname = etree.QName(node)
        if qname.namespace != TEI_NS or qname.localname not in _ELEMENTS:
            raise UnsupportedStructure(f"unsupported-visible: element {qname.localname}")
        tag = qname.localname
        actual_attrs = {_attribute_name(key) for key in node.attrib}
        unknown = actual_attrs - _ATTRIBUTES[tag]
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {tag} attribute {sorted(unknown)[0]}")
        xid = node.get(XML_ID)
        if xid:
            if xid in seen_ids:
                raise UnsupportedStructure(f"duplicate source xml:id: {xid}")
            seen_ids.add(xid)
        children = list(node)
        for child in children:
            if not isinstance(child.tag, str) or etree.QName(child).namespace != TEI_NS:
                raise UnsupportedStructure(f"unsupported-visible: non-TEI child of {tag}")
            if etree.QName(child).localname not in _CHILDREN[tag]:
                raise UnsupportedStructure(f"unsupported-visible: {etree.QName(child).localname} child of {tag}")
        if tag in _CONTAINERS and _norm(node.text):
            raise UnsupportedStructure(f"unsupported-visible: loose text in {tag}")
        if tag in _CONTAINERS:
            for child in children:
                if _norm(child.tail):
                    raise UnsupportedStructure(f"unsupported-visible: loose tail in {tag}")
    if [etree.QName(c).localname for c in root] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: TEI envelope order")
    header = root.find(f"{NS}teiHeader")
    text = root.find(f"{NS}text")
    if header is None or text is None or [etree.QName(c).localname for c in header] not in (["fileDesc"], ["fileDesc", "revisionDesc"]):
        raise UnsupportedStructure("unsupported-visible: teiHeader envelope")
    if [etree.QName(c).localname for c in text] != ["body"]:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")


def _source_binding_lxml(root: etree._Element, *, source_url: str | None, source_sha256: str | None, retained_sha256: str | None, retained_path: Path | None) -> dict[str, str | None]:
    source_desc = root.xpath(".//t:sourceDesc", namespaces={"t": TEI_NS})
    if len(source_desc) != 1:
        raise PipelineError("hymn TEI must contain one sourceDesc")
    ptrs = source_desc[0].xpath(".//t:ptr[@target]", namespaces={"t": TEI_NS})
    actual_url = ptrs[0].get("target") if ptrs else None
    if source_url and actual_url != source_url:
        raise PipelineError("hymn source URL mismatch")
    actual_hash = None
    for node in source_desc[0].xpath(".//t:idno[@type]", namespaces={"t": TEI_NS}):
        if _norm(node.get("type")).lower() in {"source_sha256", "sha256", "source-sha256"}:
            actual_hash = _norm("".join(node.itertext())).lower().removeprefix("sha256:")
            break
    if actual_hash and not re.fullmatch(r"[0-9a-f]{64}", actual_hash):
        raise PipelineError("hymn source sha256 is invalid")
    requested_hash = source_sha256.lower().removeprefix("sha256:") if source_sha256 else None
    if requested_hash and actual_hash != requested_hash:
        raise PipelineError("hymn source sha256 mismatch")
    if retained_sha256 is not None:
        if retained_path is None:
            raise PipelineError("retained source path is required for retained_sha256")
        observed_retained = hashlib.sha256(Path(retained_path).read_bytes()).hexdigest()
        if retained_sha256 != observed_retained:
            raise PipelineError("retained source sha256 mismatch")
    return {"source_url": actual_url or source_url, "source_sha256": actual_hash or requested_hash, "retained_sha256": retained_sha256}


def _inventory_lxml(root: etree._Element) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]]]:
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        tag = etree.QName(node).localname
        path = _path_lxml(root, node)
        in_header = bool(node.xpath("ancestor-or-self::t:teiHeader", namespaces={"t": TEI_NS}))
        role = "header-metadata" if in_header else "mapped-source"
        if tag in {"pb", "lb"} and not in_header:
            role = "milestone"
            exclusions.append({"tei_path": path, "reason": "milestone-omitted"})
        elif in_header:
            exclusions.append({"tei_path": path, "reason": "header-metadata"})
        if tag == "hi" and not in_header:
            warnings.append({"tei_path": path, "reason": "typography-to-plain-text"})
        inventory.append({
            "ordinal": ordinal,
            "tei_path": path,
            "tag": tag,
            "role": role,
            "attributes": {_attribute_name(k): v for k, v in sorted(node.attrib.items())},
            "text_sha256": _hash_text(_norm(node.text)),
            "tail_sha256": _hash_text(_norm(node.tail)),
        })
    return inventory, warnings, exclusions


def _rows_lxml(root: etree._Element, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ns = {"t": TEI_NS}
    body = root.xpath("/t:TEI/t:text/t:body", namespaces=ns)
    if len(body) != 1:
        raise UnsupportedStructure("unsupported-visible: text must contain one body")
    scope: etree._Element = body[0]
    if scope_id:
        matches = body[0].xpath(".//*[@xml:id=$id]", namespaces={"xml": XML_NS}, id=scope_id)
        if len(matches) != 1:
            raise UnsupportedStructure(f"hymn scope xml:id not found: {scope_id}")
        scope = matches[0]
    units = scope.xpath(".//t:div[@type='hymn']", namespaces=ns)
    if etree.QName(scope).localname == "div" and scope.get("type") == "hymn" and scope not in units:
        units.insert(0, scope)
    if not units:
        raise UnsupportedStructure("no source-defined hymn occurrence")
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    norm_node = lambda node: _norm("".join(node.itertext()))
    for sequence, unit in enumerate(units, 1):
        declared = unit.xpath("ancestor-or-self::*[@xml:lang][1]/@xml:lang", namespaces={"t": TEI_NS, "xml": XML_NS})
        unit_language = declared[0] if declared else language
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", unit_language):
            raise UnsupportedStructure("unsupported-visible: invalid hymn occurrence language")
        occurrence_id = unit.get(XML_ID)
        if not occurrence_id:
            raise UnsupportedStructure("hymn occurrence has no xml:id")
        title_nodes = unit.xpath("./t:head[@type='title' or not(@type)]", namespaces=ns)
        title = norm_node(title_nodes[0]) if title_nodes else None
        author_nodes = unit.xpath("./t:note[@type='author' or @type='contributor']", namespaces=ns)
        contributor_hint = norm_node(author_nodes[0]) if author_nodes else None
        explicit_text_id = _norm(unit.get("corresp") or unit.get("sameAs")).lstrip("#")
        stanzas: list[dict[str, Any]] = []
        refrain: dict[str, Any] | None = None
        segments: list[dict[str, Any]] = []
        for child in unit:
            tag = etree.QName(child).localname
            if tag == "lg":
                if any(etree.QName(item).localname not in {"l", "label"} for item in child):
                    raise UnsupportedStructure("unsupported-visible: note inside stanza/refrain")
                kind = child.get("type", "stanza")
                line_nodes = child.xpath("./t:l", namespaces=ns)
                lines = [norm_node(node) for node in line_nodes]
                if kind == "stanza":
                    if any(not line for line in lines) or not lines:
                        raise UnsupportedStructure("hymn stanza or refrain has no lines")
                    raw_number = child.get("n")
                    try:
                        number = int(raw_number) if raw_number else len(stanzas) + 1
                    except (TypeError, ValueError) as exc:
                        raise UnsupportedStructure("hymn stanza number is not an integer") from exc
                    stanza = {"number": number, "lines": lines}
                    stanzas.append(stanza)
                    segments.append({"kind": "stanza", "number": number, "lines": lines})
                elif kind == "refrain":
                    if any(not line for line in lines) or not lines:
                        raise UnsupportedStructure("hymn stanza or refrain has no lines")
                    if refrain is not None:
                        raise UnsupportedStructure("multiple refrain bodies require an explicit reviewed mapping")
                    labels = child.xpath("./t:label", namespaces=ns)
                    if len(labels) > 1:
                        raise UnsupportedStructure("hymn refrain has multiple labels")
                    label = norm_node(labels[0]) if labels else None
                    refrain = {"label": label or None, "lines": lines}
                    segments.append({"kind": "refrain", "label": label or None, "lines": lines})
                elif kind == "refrain-marker":
                    labels = child.xpath("./t:label", namespaces=ns)
                    label = norm_node(labels[0]) if labels else norm_node(child)
                    if not label:
                        raise UnsupportedStructure("hymn refrain marker has no label")
                    segments.append({"kind": "refrain-marker", "label": label})
                else:
                    raise UnsupportedStructure(f"unsupported-visible: lg type {kind!r}")
            elif tag in {"head", "note"}:
                continue
            else:
                raise UnsupportedStructure(f"unsupported-visible: {tag} in hymn occurrence")
        if not stanzas:
            raise UnsupportedStructure(f"hymn occurrence {occurrence_id} has no stanzas")
        notes: dict[str, str] = {}
        for note in unit.xpath("./t:note", namespaces=ns):
            typ = _norm(note.get("type")).lower()
            if typ not in _METADATA_NOTE_TYPES:
                raise UnsupportedStructure(f"unsupported-visible: hymn note type {typ or '<missing>'}")
            value = re.sub(r"[ \t]*\r?\n[ \t]*", " ", "".join(note.itertext())).strip()
            if value:
                if typ in notes:
                    raise UnsupportedStructure(f"duplicate hymn metadata note type: {typ}")
                notes[typ] = value
        setting = {"title": notes.get("hymnal"), "edition": notes.get("edition")} if "hymnal" in notes or "edition" in notes else None
        rights = {"text": notes.get("rights-text"), "tune": notes.get("rights-tune")} if "rights-text" in notes or "rights-tune" in notes else None
        text = "\n".join(line for segment in segments if "lines" in segment for line in segment["lines"])
        text_id = explicit_text_id or _derived_text_identity(title, contributor_hint, text)
        chain: list[etree._Element] = []
        ancestor: etree._Element | None = unit
        while ancestor is not None:
            if etree.QName(ancestor).localname == "div":
                chain.append(ancestor)
            ancestor = ancestor.getparent()
        chain.reverse()
        part_titles: list[str] = []
        divisions: list[dict[str, Any]] = []
        for item in chain:
            parent = item.getparent()
            siblings = [node for node in parent if etree.QName(node).localname == "div" and node.get("type") == item.get("type")] if parent is not None else [item]
            head_nodes = item.xpath("./t:head | ./t:label", namespaces=ns)
            title_value = norm_node(head_nodes[0]) if head_nodes else None
            divisions.append({"order": siblings.index(item) + 1, "type": item.get("type"), "titles": [title_value] if title_value else []})
            if title_value and item.get("type") in {"collection", "work", "book", "part", "section"}:
                part_titles.append(title_value)
        text_part = next((ancestor.get("type") for ancestor in chain if ancestor.get("type") in {"front", "back"}), "body")
        row: dict[str, Any] = {
            **{key: identity[key] for key in ("work_id", "textual_form_id", "edition_id")},
            "record_id": f"{identity['edition_id']}:hymn:{hashlib.sha256(occurrence_id.encode()).hexdigest()[:20]}",
            "sequence": sequence,
            "category": CATEGORY,
            "language": unit_language,
            "text": text,
            "representation_revision": representation_revision,
            "locator": {"kind": "hymn-occurrence", "text_part": text_part, "part_titles": part_titles, "divisions": divisions, "occurrence": sequence},
            "provenance": {"edition_title": edition_title},
            "notes": [],
            "references": [],
            "occurrence_id": hashlib.sha256(occurrence_id.encode()).hexdigest()[:20],
            "hymn_text_id": text_id,
            "first_line": stanzas[0]["lines"][0],
            "stanzas": stanzas,
            "segments": segments,
        }
        if title:
            row["title"] = title
        if notes.get("tune"):
            row["tune"] = notes["tune"]
        if notes.get("contributor") or notes.get("author"):
            row["contributor"] = notes.get("contributor") or notes.get("author")
        if notes.get("author-birth"):
            row["author_birth"] = notes["author-birth"]
        if notes.get("author-death"):
            row["author_death"] = notes["author-death"]
        if notes.get("year-written"):
            row["year_written"] = notes["year-written"]
        if setting:
            row["hymnal_setting"] = setting
        if refrain:
            row["refrain"] = refrain
        if rights:
            row["rights"] = rights
        rows.append(row)
        anchors.append({
            "record_id": row["record_id"], "source_xml_id": occurrence_id, "hymn_text_id": text_id,
            "source_order": sequence, "tei_path": _path_lxml(root, unit), "text_sha256": _hash_text(text),
            "text_length": len(text), "stanza_count": len(stanzas), "stanza_line_counts": [len(x["lines"]) for x in stanzas],
            "refrain_line_count": len(refrain["lines"]) if refrain else 0, "refrain_marker_count": sum(1 for x in segments if x["kind"] == "refrain-marker"), "segment_kinds": [x["kind"] for x in segments],
            "title": title, "first_line": stanzas[0]["lines"][0], "tune": notes.get("tune"),
            "contributor": notes.get("contributor") or notes.get("author"),
            "author_birth": notes.get("author-birth"), "author_death": notes.get("author-death"),
            "year_written": notes.get("year-written"), "hymnal_setting": setting,
        })
    return rows, anchors


def _language_lxml(root: etree._Element, requested: str | None) -> str:
    value = requested or root.get(XML_LANG)
    if not value:
        values = root.xpath("/t:TEI/t:text/@xml:lang | /t:TEI/t:text/t:body/@xml:lang", namespaces={"t": TEI_NS, "xml": XML_NS})
        value = values[0] if values else None
    if not value or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
        raise PipelineError("hymn language must be declared")
    return value


def verify_hymns_document(
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
    retained_path: Path | None = None,
    **_: Any,
) -> list[str]:
    """Recompute source rows and all receipt fields without calling ``project``."""
    errors: list[str] = []
    try:
        path = Path(tei_path)
        root = _parse_lxml(path)
        binding = _source_binding_lxml(root, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256, retained_path=retained_path)
        lang = _language_lxml(root, language)
        expected_rows, expected_anchors = _rows_lxml(root, identity=identity, language=lang, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id)
        expected_inventory, expected_warnings, expected_exclusions = _inventory_lxml(root)
        if not isinstance(rows, list) or rows != expected_rows:
            errors.append("source correspondence: rows differ in identity, order, metadata, structure, or text")
        if receipt is None or not isinstance(receipt, Mapping):
            errors.append("receipt is missing")
        else:
            expected = _receipt(tei_path=path, rows=expected_rows, anchors=expected_anchors, inventory=expected_inventory, warnings=expected_warnings, exclusions=expected_exclusions, source_binding=binding)
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
        if not io_path(path).is_file():
            raise PipelineError(f"accepted authority file is missing: {path}")
        try:
            relative = path.relative_to(base).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PipelineError(f"accepted authority file is outside root: {path}") from exc
        try:
            digest = hashlib.sha256(io_path(path).read_bytes()).hexdigest()
        except OSError as exc:
            raise PipelineError(f"cannot read accepted authority file: {path}") from exc
        bindings[name] = {"path": relative, "sha256": digest}
    return bindings


def _select_accepted_source_member(
    work_id: str, included: list[Any]
) -> Mapping[str, Any]:
    """Select an exact text member without discarding retained support accounting."""
    if work_id == "l744-pg33105-chinook-hymns":
        from .chinook_hymns import SOURCE_MEMBER_PATH

        if len(included) != 1 or not isinstance(included[0], Mapping):
            raise PipelineError("PG33105 acceptance must include only its exact HTML text member")
        if included[0].get("path") != SOURCE_MEMBER_PATH:
            raise PipelineError(f"PG33105 acceptance must select its exact retained HTML member: {SOURCE_MEMBER_PATH}")
        return included[0]
    if work_id == "l744-pg33128-gospel-hymns":
        from .pg33128_hymns import SOURCE_MEMBER_PATH, select_pg33128_member

        member = select_pg33128_member(included)
        if member.get("path") != SOURCE_MEMBER_PATH:
            raise PipelineError(f"PG33128 adapter selected an unexpected source member: {member.get('path')!r}")
        return member
    if len(included) != 1 or not isinstance(included[0], Mapping):
        raise PipelineError("accepted hymn scope must identify exactly one retained source member")
    return included[0]


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
        raise PipelineError("hymn projection requires a promoted accepted master")
    raw_identity = accepted.get("identity")
    if not isinstance(raw_identity, Mapping):
        raise PipelineError("accepted hymn identity is missing")
    identity = {}
    for key in (*_ACCEPTED_IDENTITY_KEYS, "acquisition_id"):
        value = raw_identity.get(key)
        if not isinstance(value, str) or not value.strip():
            raise PipelineError(f"accepted hymn identity is missing {key}")
        identity[key] = value
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    if (
        work.work_id != identity["work_id"]
        or edition.textual_form_id != identity["textual_form_id"]
        or edition.edition_id != identity["edition_id"]
    ):
        raise PipelineError("accepted identity does not identify the canonical hymn edition")
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
        raise PipelineError("accepted hymn textual form is missing")
    category = edition.record.get("category", form.get("category"))
    if category != CATEGORY:
        raise PipelineError("accepted edition is not a hymns category")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not language.strip():
        raise PipelineError("accepted hymn edition has no language")
    acquisition_path, acquisition = acquisition_for_edition(
        base,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=identity["acquisition_id"],
    )
    source = accepted.get("source")
    scope = accepted.get("scope")
    if not isinstance(source, Mapping) or not isinstance(scope, Mapping):
        raise PipelineError("accepted hymn source or scope is missing")
    included = scope.get("included_members")
    if not isinstance(included, list) or not included:
        raise PipelineError("accepted hymn scope has no retained source members")
    member = _select_accepted_source_member(identity["work_id"], included)
    member_path = member.get("path")
    member_hash = member.get("sha256")
    member_bytes = member.get("bytes")
    if (
        not isinstance(member_path, str)
        or not member_path
        or not isinstance(member_hash, str)
        or not isinstance(member_bytes, int)
    ):
        raise PipelineError("accepted hymn retained source member is incomplete")
    try:
        retained_path = resolve_repo_path(base, member_path)
    except (OSError, RuntimeError, ValueError, StorageTopologyError) as exc:
        raise PipelineError("accepted hymn retained source is outside root") from exc
    if not io_path(retained_path).is_file():
        raise PipelineError(f"accepted hymn retained source is missing: {member_path}")
    try:
        retained_bytes = io_path(retained_path).read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read accepted hymn retained source: {retained_path}") from exc
    if len(retained_bytes) != member_bytes or hashlib.sha256(retained_bytes).hexdigest() != member_hash:
        raise PipelineError("accepted hymn retained source proof is stale")
    revision = accepted.get("representation_revision")
    if not isinstance(revision, Mapping) or not isinstance(revision.get("id"), str) or not revision["id"].strip():
        raise PipelineError("accepted hymn representation revision is missing")
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


def project_accepted_hymns(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Project a promoted hymns master using validated acceptance authority."""

    metadata = _accepted_metadata(root, acceptance_path)
    work_id = metadata["identity"]["work_id"]
    if work_id == "evangelische-gezangen-1806":
        from .l741_gezangen import project_l741_document

        result = project_l741_document(
            metadata["master_path"],
            retained_path=metadata["retained_path"],
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
        )
    elif work_id == "l744-pg33105-chinook-hymns":
        from .chinook_hymns import project_chinook_document

        result = project_chinook_document(
            metadata["master_path"],
            retained_path=metadata["retained_path"],
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
        )
    elif work_id == "l744-pg33128-gospel-hymns":
        from .pg33128_hymns import project_pg33128_document

        result = project_pg33128_document(
            metadata["master_path"],
            retained_path=metadata["retained_path"],
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
        )
    elif work_id == "hymns-for-christian-devotion":
        from .pg20476_hymns import project_pg20476_document

        result = project_pg20476_document(
            metadata["master_path"],
            retained_path=metadata["retained_path"],
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
        )
    elif work_id == "hymnary-pd":
        from .hymnary_pd_native import project_hymnary_document

        result = project_hymnary_document(
            metadata["master_path"],
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
            source_url=metadata["source_url"],
            source_sha256=metadata["source_sha256"],
            retained_sha256=metadata["retained_sha256"],
            retained_path=metadata["retained_path"],
        )
    elif work_id == "evangelical-lutheran-hymn-book-abridged":
        from .lutheran_hymnbook_native import project_lutheran_document

        result = project_lutheran_document(
            metadata["master_path"], identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
            source_url=metadata["source_url"],
            source_sha256=metadata["source_sha256"],
            retained_sha256=metadata["retained_sha256"],
            retained_path=metadata["retained_path"],
        )
    elif work_id == "otterbein-hymnal":
        from .otterbein_hymnal_native import project_otterbein_document

        result = project_otterbein_document(
            metadata["master_path"], identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
            source_url=metadata["source_url"],
            source_sha256=metadata["source_sha256"],
            retained_sha256=metadata["retained_sha256"],
            retained_path=metadata["retained_path"],
        )
    else:
        result = project_hymns_document(
            metadata["master_path"],
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=metadata["representation_revision"],
            edition_title=metadata["edition"].title,
            source_url=metadata["source_url"],
            source_sha256=metadata["source_sha256"],
            retained_sha256=metadata["retained_sha256"],
            retained_path=metadata["retained_path"],
        )
    result["authority"] = dict(metadata["authority"])
    result["receipt"] = dict(result["receipt"])
    result["receipt"]["authority"] = dict(metadata["authority"])
    return result


project_accepted = project_accepted_hymns


def verify_accepted_hymns(
    root: Path,
    *,
    acceptance_path: Path,
    rows: list[dict[str, Any]],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted hymns rows without invoking the producer."""

    try:
        metadata = _accepted_metadata(root, acceptance_path)
        if receipt is None or not isinstance(receipt, Mapping):
            return ["accepted hymns receipt is missing"]
        authority = receipt.get("authority")
        errors: list[str] = []
        if authority != metadata["authority"]:
            errors.append("accepted authority bindings differ")
        document_receipt = {key: value for key, value in receipt.items() if key != "authority"}
        work_id = metadata["identity"]["work_id"]
        if work_id == "evangelische-gezangen-1806":
            from .l741_gezangen import verify_l741_document

            errors.extend(verify_l741_document(
                metadata["master_path"], rows, document_receipt,
                retained_path=metadata["retained_path"],
                identity=metadata["identity"],
                language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
            ))
        elif work_id == "l744-pg33105-chinook-hymns":
            from .chinook_hymns import verify_chinook_document

            errors.extend(verify_chinook_document(
                metadata["master_path"], rows, document_receipt,
                retained_path=metadata["retained_path"],
                identity=metadata["identity"],
                language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
            ))
        elif work_id == "l744-pg33128-gospel-hymns":
            from .pg33128_hymns import verify_pg33128_document

            errors.extend(verify_pg33128_document(
                metadata["master_path"], rows, document_receipt,
                retained_path=metadata["retained_path"],
                identity=metadata["identity"],
                language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
            ))
        elif work_id == "hymns-for-christian-devotion":
            from .pg20476_hymns import verify_pg20476_document

            errors.extend(verify_pg20476_document(
                metadata["master_path"], rows, document_receipt,
                retained_path=metadata["retained_path"],
                identity=metadata["identity"],
                language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
            ))
        elif work_id == "hymnary-pd":
            from .hymnary_pd_native import verify_hymnary_document

            errors.extend(verify_hymnary_document(
                metadata["master_path"], rows, document_receipt,
                identity=metadata["identity"],
                language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
                source_url=metadata["source_url"],
                source_sha256=metadata["source_sha256"],
                retained_sha256=metadata["retained_sha256"],
                retained_path=metadata["retained_path"],
            ))
        elif work_id == "evangelical-lutheran-hymn-book-abridged":
            from .lutheran_hymnbook_native import verify_lutheran_document

            errors.extend(verify_lutheran_document(
                metadata["master_path"], rows, document_receipt,
                identity=metadata["identity"], language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
                source_url=metadata["source_url"],
                source_sha256=metadata["source_sha256"],
                retained_sha256=metadata["retained_sha256"],
                retained_path=metadata["retained_path"],
            ))
        elif work_id == "otterbein-hymnal":
            from .otterbein_hymnal_native import verify_otterbein_document

            errors.extend(verify_otterbein_document(
                metadata["master_path"], rows, document_receipt,
                identity=metadata["identity"], language=metadata["language"],
                representation_revision=metadata["representation_revision"],
                edition_title=metadata["edition"].title,
                source_url=metadata["source_url"],
                source_sha256=metadata["source_sha256"],
                retained_sha256=metadata["retained_sha256"],
                retained_path=metadata["retained_path"],
            ))
        else:
            errors.extend(verify_hymns_document(
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
                retained_path=metadata["retained_path"],
            ))
        return sorted(set(errors))
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
