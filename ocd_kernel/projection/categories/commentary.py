"""Source-defined commentary projection for PIPE-007B.

Commentary rows follow an explicit source unit and its attached scripture or
other target.  The module never creates one row per verse in a range.  Its
checker performs a separate lxml traversal and does not call this producer.
"""

from __future__ import annotations
from ocd_kernel.projection.native_content_check import projection_validator

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from ocd_kernel.library._common import PipelineError, io_path
from ocd_kernel.lib.path_io import resolve_path
from ocd_kernel.projection.categories.native_documents import _entry_attribution, _observe_entry_attribution
from ocd_kernel.projection import native_content
from ocd_kernel.projection.scripture_targets import normalize_explicit_target
from ocd_kernel.projection.scripture_authority import BOOK_CODES_PATH, load_book_codes
from ocd_kernel.projection.scripture_targets_check import observe_explicit_target
from ocd_kernel.projection.envelope import canonical_row_bytes, make_row, row_text_hash

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "schemas" / "v2" / "categories" / "commentary.schema.json"
COMMON_SCHEMA_PATH = ROOT / "schemas" / "v2" / "public-row.schema.json"
CATEGORY = "commentary"
MAPPING_VERSION = "ocd-commentary-mapping-provisional-v9"
ASSEMBLER_VERSION = "ocd-commentary-assembler-provisional-v2"
RECEIPT_VERSION = "ocd-commentary-receipt-provisional-v2"
_IDENTITY_KEYS = ("work_id", "textual_form_id", "edition_id")
_ALLOWED_ELEMENTS = {
    "text", "front", "body", "back", "div", "head", "label", "p", "ab", "seg",
    "hi", "foreign", "ref", "note", "lb", "pb", "anchor", "ptr",
}
_UNIT_TYPES = {"commentary-unit", "commentary", "annotation", "entry"}
_SCRIPTURE_TYPES = {"scripture", "scripture-reference", "primary-scripture"}
_TEXT_PARTS = {"front", "body", "back"}
_HEADER_NAMES = {
    "teiHeader", "encodingDesc", "profileDesc", "langUsage", "language", "textClass",
    "keywords", "term", "p", "fileDesc", "titleStmt", "title", "author", "editor",
    "publicationStmt", "publisher", "availability", "licence", "sourceDesc", "bibl", "notesStmt",
    "idno", "ptr", "note", "revisionDesc", "change", "date", "respStmt", "resp",
}
_ATTRS = {
    "TEI": {"xml:id"}, "text": {"xml:id", "xml:lang"}, "front": {"xml:id"}, "body": {"xml:id"},
    "back": {"xml:id"}, "div": {"type", "subtype", "n", "xml:id", "corresp", "scope", "target", "osisRef", "cRef"},
    "head": {"type", "xml:id"}, "label": {"type", "xml:id", "xml:lang"},
    "p": {"type", "n", "xml:id", "xml:lang"}, "ab": {"type", "n", "xml:id", "xml:lang"},
    "seg": {"type", "n", "xml:id", "xml:lang"}, "hi": {"rend", "xml:id", "xml:lang"},
    "foreign": {"xml:id", "xml:lang"}, "ref": {"type", "target", "cRef", "xml:id"},
    "note": {"type", "place", "n", "xml:id"}, "lb": {"break", "xml:id"},
    "pb": {"n", "xml:id"}, "anchor": {"xml:id"}, "ptr": {"type", "target", "xml:id"},
}
_HEADER_ATTRS = {
    "teiHeader": {"xml:id"}, "encodingDesc": {"xml:id"}, "profileDesc": {"xml:id"},
    "langUsage": {"xml:id"}, "language": {"ident", "xml:id"}, "textClass": {"xml:id"},
    "keywords": {"xml:id"}, "term": {"xml:id"}, "fileDesc": {"xml:id"},
    "titleStmt": {"xml:id"}, "title": {"xml:id", "type"}, "author": {"xml:id"},
    "editor": {"xml:id"}, "publicationStmt": {"xml:id"}, "publisher": {"xml:id"},
    "availability": {"status", "xml:id"}, "licence": {"target", "xml:id"},
    "sourceDesc": {"xml:id"}, "bibl": {"xml:id", "type"}, "idno": {"type", "xml:id"},
    "ptr": {"type", "target", "xml:id"}, "note": {"type", "place", "n", "xml:id"},
    "revisionDesc": {"xml:id"}, "change": {"when", "xml:id"}, "date": {"when", "xml:id"},
    "respStmt": {"xml:id"}, "resp": {"xml:id"},
}
_EXCLUDED_TYPES = {"title-page", "half-title-page", "copyright-page", "imprint", "colophon", "paratext"}
_WARNING_REASONS = {
    "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text",
    "seg": "segmentation-to-plain-text", "note": "note-extracted",
    "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted",
    "lb": "line-break-to-space", "ref": "source-reference-preserved",
}


class UnsupportedStructure(PipelineError):
    """The selected commentary uses an undeclared structure."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hash_text(value: str) -> str:
    return _hash_bytes(value.encode("utf-8"))


def _attribute_name(key: str) -> str:
    if key == XML_ID:
        return "xml:id"
    if key == XML_LANG:
        return "xml:lang"
    return _local(key) if key.startswith("{") else key


def _valid_hash(value: str, *, field: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PipelineError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _identity(identity: Mapping[str, str]) -> dict[str, str]:
    if set(identity) != set(_IDENTITY_KEYS):
        raise PipelineError("public identity requires exactly work, form, and edition")
    result: dict[str, str] = {}
    for key in _IDENTITY_KEYS:
        value = identity.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise PipelineError(f"invalid public identity {key}")
        result[key] = value
    return result


def _read_root(path: Path) -> tuple[ET.Element, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read commentary TEI {path}: {exc}") from exc
    if any(token in raw.lower() for token in (b"<!doctype", b"<!entity", b"<!--")):
        raise UnsupportedStructure("unsupported-visible: DTD, entity declaration, or comment")
    if re.search(rb"<\?(?!xml\b)", raw, re.IGNORECASE):
        raise UnsupportedStructure("unsupported-visible: processing instruction")

    class _NoExternal(ET.TreeBuilder):
        def doctype(self, name: str, pubid: str, system: str) -> None:
            raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")

        def comment(self, text: str) -> None:
            raise UnsupportedStructure("unsupported-visible: XML comment")

        def pi(self, target: str, text: str) -> None:
            raise UnsupportedStructure("unsupported-visible: processing instruction")

    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=_NoExternal()))
    except ET.ParseError as exc:
        raise PipelineError(f"invalid TEI: {exc}") from exc
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise PipelineError("commentary projection requires a TEI P5 root")
    if any(not isinstance(node.tag, str) or not node.tag.startswith(f"{{{TEI_NS}}}") for node in root.iter()):
        raise UnsupportedStructure("unsupported-visible: non-TEI element")
    return root, raw


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def _paths(root: ET.Element) -> dict[ET.Element, str]:
    paths: dict[ET.Element, str] = {root: "/TEI[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in list(parent):
            kind = _local(child.tag)
            counts[kind] = counts.get(kind, 0) + 1
            paths[child] = f"{paths[parent]}/{kind}[{counts[kind]}]"
    return paths


def _header(root: ET.Element) -> dict[str, Any]:
    source_descs = [n for n in root.iter() if _local(n.tag) == "sourceDesc"]
    if len(source_descs) != 1:
        raise PipelineError("commentary TEI must contain exactly one sourceDesc")
    source_desc = source_descs[0]
    ptrs = [n for n in source_desc.iter() if _local(n.tag) == "ptr"]
    pointers = [(n.get("target") or "").strip() for n in ptrs]
    if len(ptrs) != 1 or not pointers[0]:
        raise UnsupportedStructure("unsupported-visible: commentary sourceDesc requires one source ptr")
    ids: dict[str, str] = {}
    for node in source_desc.iter():
        if _local(node.tag) != "idno":
            continue
        kind = (node.get("type") or "").strip().lower().replace("ocd-", "")
        value = _norm("".join(node.itertext()))
        if not value:
            continue
        if kind in {"sha256", "retained_sha256", "archive_sha256"}:
            key, checked = "retained_sha256", _valid_hash(value, field="retained source sha256")
        elif kind in {"source_sha256", "origin_sha256"}:
            key, checked = "source_sha256", _valid_hash(value, field="source sha256")
        elif kind in {"work_id", "textual_form_id", "edition_id", "acquisition_id", "representation_revision"}:
            key, checked = kind.replace("-", "_"), value
        else:
            continue
        if key in ids and ids[key] != checked:
            raise UnsupportedStructure(f"unsupported-visible: conflicting source idno {key}")
        ids[key] = checked
    if "retained_sha256" not in ids:
        raise PipelineError("commentary TEI sourceDesc must bind retained source sha256")
    return {"source_url": pointers[0], "retained_sha256": ids["retained_sha256"], "source_sha256": ids.get("source_sha256"), "ids": ids}


def _policy() -> tuple[dict[str, dict[str, str]], set[str], set[str], set[str]]:
    try:
        value = json.loads((Path(__file__).resolve().parents[3] / "schemas/v2/public-row.schema.json").read_text(encoding="utf-8"))["x-ocd-projection-policy"]
        return value["script"]["maps"], set(value["script"]["styles"]), set(value["script"]["safe_punctuation"]), set(value["allowed_elements"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError("cannot load commentary rendering policy") from exc


def _render(node: ET.Element, paths: Mapping[ET.Element, str], *, omit_notes: bool = True) -> str:
    script_maps, script_styles, safe_punctuation, allowed = _policy()
    sentinel = "\x00"

    def visit(current: ET.Element, style: str | None = None) -> str:
        kind = _local(current.tag)
        current_style = style
        if kind == "hi" and current.get("rend") in script_styles:
            if style is not None:
                raise UnsupportedStructure(f"unsupported-visible: nested script styles at {paths[current]}")
            current_style = current.get("rend")
        value = current.text or ""
        if current_style:
            mapping = script_maps[current_style]
            chars: list[str] = []
            for char in value:
                if char in mapping or char.isspace() or char in safe_punctuation:
                    chars.append(mapping.get(char, char))
                else:
                    raise UnsupportedStructure(f"unsupported-visible: unsupported {current_style} script character {char!r} at {paths[current]}")
            value = "".join(chars)
        output = [value]
        for child in list(current):
            kind = _local(child.tag)
            if (kind == "note" and omit_notes) or kind in {"pb", "anchor", "ptr", "head", "label"}:
                output.append(sentinel)
            elif kind == "lb":
                output.append("" if child.get("break") == "no" else " ")
            elif kind in {"head", "label"}:
                output.append(sentinel)
            else:
                output.append(visit(child, current_style))
                if kind in {"p", "ab", "seg"}:
                    output.append(" ")
            output.append(child.tail or "")
        return "".join(output)

    value = visit(node)
    for index, char in enumerate(value):
        if char == sentinel:
            before = value[index - 1] if index else ""
            after = value[index + 1] if index + 1 < len(value) else ""
            if before.isalnum() and after.isalnum():
                raise UnsupportedStructure(f"unsupported-visible: omitted inline element creates an ambiguous alphanumeric boundary at {paths[node]}")
    return _norm(value.replace(sentinel, ""))


def _notes(node: ET.Element, paths: Mapping[ET.Element, str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for note in (child for child in node.iter() if _local(child.tag) == "note"):
        place = note.get("place", "unspecified")
        if place not in {"foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place={place} at {paths[note]}")
        result.append({"text": _render(note, paths, omit_notes=False), "place": place, "label": note.get("n", "")})
    return result


def _ancestor(node: ET.Element, parents: Mapping[ET.Element, ET.Element], names: set[str]) -> list[ET.Element]:
    result: list[ET.Element] = []
    current = parents.get(node)
    while current is not None:
        if _local(current.tag) in names:
            result.append(current)
        current = parents.get(current)
    return list(reversed(result))


def _text_part(node: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> str:
    parts = [ancestor for ancestor in _ancestor(node, parents, {"front", "body", "back"})]
    if len(parts) != 1:
        raise UnsupportedStructure(f"unsupported-visible: commentary unit has no unique text part at {paths[node]}")
    return _local(parts[0].tag)


def _scope_source(node: ET.Element, paths: Mapping[ET.Element, str]) -> str:
    attrs = [(key, node.get(key, "").strip()) for key in ("scope", "target", "osisRef", "cRef", "corresp") if node.get(key)]
    if attrs:
        if len({value for _, value in attrs}) > 1:
            raise UnsupportedStructure(f"unsupported-visible: conflicting commentary targets at {paths[node]}")
        raw = attrs[0][1]
    else:
        refs = [ref for ref in node.iter() if _local(ref.tag) == "ref" and (ref.get("type") or "") in _SCRIPTURE_TYPES]
        if len(refs) != 1:
            reason = "no primary target" if not refs else "multiple primary targets"
            raise UnsupportedStructure(f"unsupported-visible: commentary unit requires one {reason} at {paths[node]}")
        ref = refs[0]
        has_target = "target" in ref.attrib
        has_cref = "cRef" in ref.attrib
        if has_target == has_cref:
            raise UnsupportedStructure(f"unsupported-visible: reference requires exactly one target at {paths[ref]}")
        raw = (ref.get("target") if has_target else ref.get("cRef") or "").strip()
    if not raw or raw.startswith("#"):
        raise UnsupportedStructure(f"unsupported-visible: commentary unit requires one nonlocal target at {paths[node]}")
    if len(raw.split()) != 1:
        raise UnsupportedStructure(f"unsupported-visible: commentary target is ambiguous at {paths[node]}")
    return raw


def _book_codes() -> set[str]:
    return load_book_codes(BOOK_CODES_PATH)

def _scope(raw: str) -> dict[str, Any]:
    normalized = raw
    normalized = re.sub(r"^(?:Bible|osis):", "", normalized, flags=re.IGNORECASE)
    if not normalized:
        normalized = raw
    book = r"[1-3]?[A-Za-z][A-Za-z0-9]*"
    number = r"[0-9]+[A-Za-z]?"
    passage = rf"{book}(?:\.{number}){{0,2}}"
    if re.fullmatch(rf"{passage}-(?:{passage}|{number}(?:\.{number})?)", normalized):
        kind = "range"
    elif re.fullmatch(rf"{book}\.{number}\.{number}", normalized):
        kind = "verse"
    elif re.fullmatch(rf"{book}\.{number}", normalized):
        kind = "chapter"
    elif re.fullmatch(book, normalized):
        kind = "book"
    else:
        kind = "other"
    return {"raw": raw, "normalized": normalized, "type": kind}


def _project_scope(raw: str) -> dict[str, Any]:
    result = _scope(raw)
    codes = _book_codes()
    try:
        result['reference'] = normalize_explicit_target(raw, book_codes=codes)
    except PipelineError:
        result['normalization_status'] = 'unsupported-explicit-target'
    else:
        result['normalization_status'] = 'explicit-target-syntax'
    return result


def _observe_scope(raw: str) -> dict[str, Any]:
    result = _scope(raw)  # Existing lexical classification is not an OSIS proof.
    codes = _book_codes()
    try:
        result['reference'] = observe_explicit_target(raw, book_codes=codes)
    except ValueError:
        result['normalization_status'] = 'unsupported-explicit-target'
    else:
        result['normalization_status'] = 'explicit-target-syntax'
    return result


def _source_scope_labels(unit: ET.Element, paths: Mapping[ET.Element, str]) -> dict[str, str]:
    result = {}
    for role, field in [('scripture-reference', 'source_label'), ('scripture-book', 'book_label')]:
        nodes = [node for node in unit if _local(node.tag) == 'label' and node.get('type') == role]
        if len(nodes) > 1:
            raise UnsupportedStructure('duplicate commentary source label')
        if nodes:
            value = _render(nodes[0], paths)
            if not value:
                raise UnsupportedStructure('empty commentary source label')
            result[field] = value
            if field == 'book_label' and nodes[0].get(XML_LANG) is not None:
                result['book_label_language'] = nodes[0].get(XML_LANG)
    return result


def _observed_scope_labels(unit: Any, paths: Mapping[Any, str]) -> dict[str, str]:
    result = {}
    for role, field in [('scripture-reference', 'source_label'), ('scripture-book', 'book_label')]:
        nodes = unit.xpath('./t:label[@type=$role]', namespaces={'t': TEI_NS}, role=role)
        if len(nodes) > 1:
            raise UnsupportedStructure('checker: ambiguous source label')
        if nodes:
            value = _checker_render(nodes[0], paths)
            if not value:
                raise UnsupportedStructure('checker: empty source label')
            result[field] = value
            if field == 'book_label' and nodes[0].get(XML_LANG) is not None:
                result['book_label_language'] = nodes[0].get(XML_LANG)
    return result


def _english_book_label(scope: dict[str, Any]) -> None:
    """Validate an explicit English label against the bound naming authority."""
    if 'book_label' not in scope:
        return
    language = scope.get('book_label_language', '')
    if language.lower().split('-')[0] != 'en':
        scope['book_name_status'] = 'english-language-not-declared'
        return
    names = json.loads(BOOK_CODES_PATH.read_text(encoding='utf-8'))
    label = scope['book_label']
    code = names.get(label) if not label.startswith('_') else None
    if code is None:
        scope['book_name_status'] = 'unrecognized-english-label'
        return
    target = scope.get('reference', {}).get('start', {}).get('book')
    if target is None:
        scope['book_name_status'] = 'target-unresolved'
        return
    if code != target:
        raise UnsupportedStructure('English book label contradicts the scripture target')
    scope['english_book_name'] = label
    scope['book_name_status'] = 'explicit-english-label'


def _divisions(node: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for division in _ancestor(node, parents, {"div"}):
        if division.get("type") in {"selection", "outside-scope"}:
            if division.get("n") is not None or any(_local(child.tag) == "head" for child in division):
                raise UnsupportedStructure("unsupported-visible: administrative wrapper has source heading or number")
            continue
        parent = parents.get(division)
        siblings = [child for child in list(parent) if _local(child.tag) == "div"] if parent is not None else []
        order = siblings.index(division) + 1 if division in siblings else 1
        titles = [_norm("".join(child.itertext())) for child in list(division) if _local(child.tag) == "head" and _norm("".join(child.itertext()))]
        result.append({"order": order, "type": division.get("type"), "titles": titles})
    return result


def _unit_candidates(body: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> list[ET.Element]:
    candidates: list[ET.Element] = []
    for node in body.iter():
        kind = _local(node.tag)
        explicit = any(node.get(key) for key in ("scope", "target", "osisRef", "cRef", "corresp"))
        marked = kind == "div" and node.get("type") in _UNIT_TYPES
        refs = [ref for ref in node.iter() if _local(ref.tag) == "ref" and (ref.get("type") or "") in _SCRIPTURE_TYPES and (ref.get("target") or ref.get("cRef"))]
        if marked and (explicit or refs or any(_local(child.tag) in {"p", "ab", "seg"} for child in list(node))):
            candidates.append(node)
        elif kind in {"p", "ab", "seg"} and (explicit or refs):
            candidates.append(node)
    # A marked wrapper owns its descendant blocks; nested candidates are not
    # separately published, which prevents a passage from becoming artificial
    # verse rows.
    outer: list[ET.Element] = []
    for node in candidates:
        if any(ancestor in candidates for ancestor in _ancestor(node, parents, {"div", "p", "ab", "seg"})):
            continue
        outer.append(node)
    return outer


def _validate_elements(root: ET.Element, paths: Mapping[ET.Element, str]) -> None:
    if [_local(child.tag) for child in list(root)] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: TEI requires teiHeader then text")
    text = next((child for child in list(root) if _local(child.tag) == "text"), None)
    if text is None:
        raise UnsupportedStructure("unsupported-visible: commentary TEI has no text")
    text_children = [_local(child.tag) for child in list(text)]
    if any(kind not in _TEXT_PARTS for kind in text_children) or text_children.count("body") != 1:
        raise UnsupportedStructure("unsupported-visible: text requires one body and optional front/back")
    parents = _parents(root)
    seen_ids: set[str] = set()
    for node in root.iter():
        kind = _local(node.tag)
        if not isinstance(node.tag, str) or not node.tag.startswith(f"{{{TEI_NS}}}"):
            raise UnsupportedStructure(f"unsupported-visible: non-TEI element at {paths.get(node, '?')}")
        if node.get(XML_ID):
            if node.get(XML_ID) in seen_ids:
                raise UnsupportedStructure(f"unsupported-visible: duplicate xml:id at {paths[node]}")
            seen_ids.add(node.get(XML_ID, ""))
        if any(key.startswith("{") and key not in {XML_ID, XML_LANG, f"{{{XML_NS}}}space"} for key in node.attrib):
            raise UnsupportedStructure(f"unsupported-visible: attribute namespace at {paths[node]}")
        attrs = {_attribute_name(key) for key in node.attrib}
        if kind == "TEI":
            unknown = attrs - _ATTRS["TEI"]
            if unknown:
                raise UnsupportedStructure(f"unsupported-visible: TEI/@{sorted(unknown)[0]} at {paths[node]}")
            continue
        in_header = kind == "teiHeader" or any(_local(ancestor.tag) == "teiHeader" for ancestor in _ancestor(node, parents, {"teiHeader"}))
        if in_header:
            if kind not in _HEADER_NAMES:
                raise UnsupportedStructure(f"unsupported-visible: header element {kind} at {paths[node]}")
            # Header attributes are deliberately narrow, while source identity
            # values remain data in idno text rather than arbitrary attributes.
            allowed = {"xml:id", "type", "target", "place", "n", "when", "status", "ident"}
            if kind == "note":
                allowed.add("space")
                if node.get(f"{{{XML_NS}}}space") not in {None, "preserve"}:
                    raise UnsupportedStructure(f"unsupported-visible: header note/@xml:space at {paths[node]}")
            if attrs - allowed:
                raise UnsupportedStructure(f"unsupported-visible: header {kind}/@{sorted(attrs - allowed)[0]} at {paths[node]}")
            continue
        if kind == "div" and node.get("type") in {"selection", "outside-scope"}:
            if node.get("n") is not None or any(_local(child.tag) == "head" for child in list(node)):
                raise UnsupportedStructure("unsupported-visible: administrative wrapper has source heading or number")
        if kind not in _ALLOWED_ELEMENTS:
            raise UnsupportedStructure(f"unsupported-visible: {kind} at {paths[node]}")
        unknown = attrs - _ATTRS.get(kind, set())
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {kind}/@{sorted(unknown)[0]} at {paths[node]}")
        if kind == "note" and node.get("place") not in {None, "foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[node]}")
        if kind == "lb" and node.get("break") not in {None, "yes", "no"}:
            raise UnsupportedStructure(f"unsupported-visible: lb/@break at {paths[node]}")
        if kind == "ref" and "target" in node.attrib and "cRef" in node.attrib:
            raise UnsupportedStructure(f"unsupported-visible: ref has both @target and @cRef at {paths[node]}")
        if kind == "ref" and ((node.get("target") or node.get("cRef")) is not None):
            target = (node.get("target") or node.get("cRef") or "").strip()
            if not target or len(target.split()) != 1:
                raise UnsupportedStructure(f"unsupported-visible: ambiguous reference target at {paths[node]}")
        if kind in {"text", "front", "body", "back", "div"}:
            if _norm(node.text or "") or any(_norm(child.tail or "") for child in list(node)):
                raise UnsupportedStructure(f"unsupported-visible: loose text in {kind} at {paths[node]}")
        if kind in {"lb", "pb", "anchor", "ptr"} and (len(list(node)) or _norm(node.text or "")):
            raise UnsupportedStructure(f"unsupported-visible: nonempty milestone at {paths[node]}")


def _attributes(node: ET.Element) -> dict[str, str]:
    return {
        _attribute_name(key): value
        for key, value in sorted(node.attrib.items())
    }


def _account(
    root: ET.Element,
    candidates: Sequence[ET.Element],
    selected: Sequence[ET.Element],
    paths: Mapping[ET.Element, str],
    parents: Mapping[ET.Element, ET.Element],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    selected_set = set(selected)
    row_nodes = {child for unit in selected for child in unit.iter()}
    outside_nodes = {
        child for unit in candidates if unit not in selected_set for child in unit.iter()
    }
    excluded_nodes: set[ET.Element] = set()
    for node in root.iter():
        if _local(node.tag) == "div" and node.get("type") in _EXCLUDED_TYPES:
            excluded_nodes.update(node.iter())
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for node in root.iter():
        kind = _local(node.tag)
        ancestors = _ancestor(node, parents, {"teiHeader"})
        if kind in {"TEI", "teiHeader"} or any(_local(item.tag) == "teiHeader" for item in ancestors):
            disposition = "private-header"
        elif node in excluded_nodes:
            disposition = "excluded-paratext"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif node in row_nodes and kind in {"head", "label"}:
            disposition = "locator-heading"
        elif node in row_nodes:
            disposition = "row-content"
        elif kind in {"head", "label"}:
            disposition = "locator-heading"
        else:
            disposition = "structure"
        inventory.append({
            "tei_path": paths[node], "disposition": disposition,
            "attributes": _attributes(node), "text_sha256": row_text_hash(node.text or ""),
            "tail_sha256": row_text_hash(node.tail or ""),
        })
        if disposition in {"outside-scope", "excluded-paratext"}:
            exclusions.append({"tei_path": paths[node], "reason": disposition})
        if disposition == "row-content" and kind in _WARNING_REASONS:
            warnings.append({"tei_path": paths[node], "reason": _WARNING_REASONS[kind]})
    return inventory, exclusions, warnings


def _context(*, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str) -> dict[str, str]:
    result = _identity(identity)
    if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", language):
        raise PipelineError("invalid language")
    for key, value in (("representation revision", representation_revision), ("edition title", edition_title)):
        if not isinstance(value, str) or not value.strip():
            raise PipelineError(f"missing {key}")
    result.update(language=language, representation_revision=representation_revision, edition_title=edition_title)
    return result


def _validator() -> Any:
    try:
        import jsonschema
        from referencing import Registry, Resource
        import referencing.jsonschema
        base = Path(__file__).resolve().parents[3]
        schema = json.loads((base / "schemas/v2/categories/commentary.schema.json").read_text(encoding="utf-8"))
        common = json.loads((base / "schemas/v2/public-row.schema.json").read_text(encoding="utf-8"))
        resource = Resource.from_contents(common, default_specification=referencing.jsonschema.DRAFT202012)
        native = json.loads((base / "schemas/v2/native-content.schema.json").read_text(encoding="utf-8"))
        registry = Registry().with_resources([(common["$id"], resource), (native["$id"], Resource.from_contents(native, default_specification=referencing.jsonschema.DRAFT202012))])
        validator = projection_validator(schema, registry=registry, format_checker=jsonschema.FormatChecker())
        validator.check_schema(schema)
        return validator
    except (ImportError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError("invalid commentary projection schema package") from exc


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"invalid commentary public row {row.get('record_id', f'row-{index}')}: {errors[0].message}")


def _projection(tei_path: Path, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None, source_url: str | None, source_sha256: str | None, retained_sha256: str | None, accessed_at: str | None) -> dict[str, Any]:
    context = _context(identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title)
    root, raw = _read_root(tei_path)
    paths = _paths(root)
    parents = _parents(root)
    _validate_elements(root, paths)
    for node in root.iter():
        if _local(node.tag) == "text" and node.get(XML_LANG) and node.get(XML_LANG).strip().lower() != language.strip().lower():
            raise UnsupportedStructure(f"unsupported-visible: source language {node.get(XML_LANG)} differs from emitted language {language}")
    header = _header(root)
    if source_url is not None and header["source_url"] != source_url:
        raise PipelineError("TEI source URL mismatch")
    if source_sha256 is not None and header.get("source_sha256") != _valid_hash(source_sha256, field="source sha256"):
        raise PipelineError("TEI source sha256 mismatch")
    if retained_sha256 is not None and header["retained_sha256"] != _valid_hash(retained_sha256, field="retained source sha256"):
        raise PipelineError("TEI retained sha256 mismatch")
    for key in _IDENTITY_KEYS:
        if header["ids"].get(key) not in {None, context[key]}:
            raise PipelineError(f"TEI {key} mismatch")
    if header["ids"].get("representation_revision") not in {None, representation_revision}:
        raise PipelineError("TEI representation revision mismatch")
    body = next((node for node in root.iter() if _local(node.tag) == "body"), None)
    if body is None:
        raise UnsupportedStructure("unsupported-visible: commentary TEI has no body")
    all_candidates = _unit_candidates(body, parents, paths)
    if not all_candidates:
        raise UnsupportedStructure("unsupported-visible: no explicit commentary units")
    selected = list(all_candidates)
    if scope_id is not None:
        scope = next((node for node in body.iter() if node.get(XML_ID) == scope_id), None)
        if scope is None:
            raise UnsupportedStructure(f"unsupported-visible: commentary scope not found: {scope_id}")
        selected = [node for node in all_candidates if node is scope or node in set(scope.iter())]
        if not selected:
            raise UnsupportedStructure("unsupported-visible: commentary scope contains no units")
    ordinals = {node: index for index, node in enumerate(all_candidates, 1)}
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    references: list[dict[str, Any]] = []
    for sequence, node in enumerate(selected, 1):
        raw_scope = _scope_source(node, paths)
        text = _render(node, paths)
        if not text:
            raise UnsupportedStructure(f"unsupported-visible: empty commentary unit at {paths[node]}")
        part = _text_part(node, parents, paths)
        part_node = next(item for item in _ancestor(node, parents, {part}) if _local(item.tag) == part)
        part_titles = [_norm("".join(child.itertext())) for child in list(part_node) if _local(child.tag) == "head" and _norm("".join(child.itertext()))]
        locator: dict[str, Any] = {"kind": "commentary-unit", "text_part": part, "part_titles": part_titles, "divisions": _divisions(node, parents, paths), "scope": _project_scope(raw_scope), "unit": sequence, "source_order": ordinals[node]}
        locator['scope'].update(_source_scope_labels(node, paths))
        _english_book_label(locator['scope'])
        if node.get('subtype') is not None:
            if node.get('subtype') != 'introduction' or locator['scope'].get('reference', {}).get('kind') not in ('book', 'chapter'):
                raise UnsupportedStructure('introduction requires an explicit book or chapter target')
            locator['unit_role'] = 'introduction'
        public_refs: list[dict[str, Any]] = []
        for ref in [item for item in node.iter() if _local(item.tag) == "ref"]:
            target = (ref.get("target") or ref.get("cRef") or "").strip()
            if not target or len(target.split()) != 1 or ("target" in ref.attrib and "cRef" in ref.attrib) or ("target" not in ref.attrib and "cRef" not in ref.attrib):
                raise UnsupportedStructure(f"unsupported-visible: reference requires one target at {paths[ref]}")
            if "cRef" in ref.attrib and target.startswith("#"):
                raise UnsupportedStructure(f"unsupported-visible: cRef cannot identify a local TEI target at {paths[ref]}")
            item = {"label": _render(ref, paths, omit_notes=False), "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None}
            if ref.get('type'):
                item['source_role'] = ref.get('type')
            if not target.startswith('#'):
                item['source_target'] = target
                if ref.get('type') in _SCRIPTURE_TYPES or ref.get('type') == 'scripture-cross-reference':
                    normalized_scope = _project_scope(target)
                    item['normalization_status'] = normalized_scope['normalization_status']
                    if 'reference' in normalized_scope:
                        item['scripture'] = normalized_scope['reference']
            public_refs.append(item)
            references.append({"tei_path": paths[ref], "original_target": target, **{key: value for key, value in item.items() if key != "label"}})
        notes = _notes(node, paths)
        row = make_row(record_id=f"{context['edition_id']}:commentary-{ordinals[node]:06d}", sequence=sequence, work_id=context["work_id"], textual_form_id=context["textual_form_id"], edition_id=context["edition_id"], category=CATEGORY, language=language, text=text, locator=locator, provenance={"edition_title": edition_title, **_entry_attribution(node)}, representation_revision=representation_revision, notes=notes)
        row["notes"] = row.get("notes", [])
        row["references"] = public_refs
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "tei_path": paths[node], "text_sha256": row_text_hash(text), "source_order": ordinals[node], "locator": copy.deepcopy(locator)})
    inventory, exclusions, warnings = _account(root, all_candidates, selected, paths, parents)
    if not rows:
        raise UnsupportedStructure("unsupported-visible: commentary projection produced no rows")
    _validate_rows(rows)
    result: dict[str, Any] = {"rows": rows, "anchors": anchors, "inventory": inventory, "references": references, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "master_sha256": hashlib.sha256(raw).hexdigest(), "scope_id": scope_id, "mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "source_binding": {"source_url": header["source_url"], "retained_sha256": header["retained_sha256"]}, "authority": {}}
    if header.get("source_sha256"):
        result["source_binding"]["source_sha256"] = header["source_sha256"]
    if accessed_at is not None:
        result["source_binding"]["accessed_at"] = accessed_at
    return result


def project_commentary_document(tei_path: Path, *, identity: dict[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None = None, source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, accessed_at: str | None = None) -> dict[str, Any]:
    """Project a source-bound commentary TEI document at its native unit grain."""
    result = _projection(Path(tei_path), identity=identity, language=language, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256, accessed_at=accessed_at)
    result["receipt"] = build_commentary_receipt(result, identity=identity)
    return result


project = project_commentary_document
project_commentary = project_commentary_document
project_document = project_commentary_document


def build_commentary_receipt(projection: Mapping[str, Any], *, identity: Mapping[str, str], authority: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the complete private receipt from a producer projection.

    Every accounting component is required.  A missing field is a producer
    defect and raises instead of silently becoming an empty list, because an
    empty accounting field can falsely certify an incomplete source mapping.
    """
    identity_value = _identity(identity)
    rows = projection.get("rows")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise PipelineError("commentary projection rows must be a list of objects")
    required = (
        "mapping_version", "assembler_version", "master_sha256", "scope_id",
        "source_binding", "anchors", "inventory", "references", "warnings",
        "exclusions", "unsupported",
    )
    missing = [key for key in required if key not in projection]
    if missing:
        raise PipelineError(f"commentary projection missing receipt fields: {', '.join(missing)}")
    if not isinstance(projection["source_binding"], Mapping):
        raise PipelineError("commentary projection source_binding has invalid type")
    for key in ("anchors", "inventory", "references", "warnings", "exclusions", "unsupported"):
        if not isinstance(projection[key], list):
            raise PipelineError(f"commentary projection {key} has invalid type")
    for key in ("mapping_version", "assembler_version"):
        if not isinstance(projection[key], str) or not projection[key]:
            raise PipelineError(f"commentary projection {key} has invalid value")
    master_sha256 = _valid_hash(str(projection["master_sha256"]), field="master sha256")
    authority_value = authority if authority is not None else projection.get("authority")
    if not isinstance(authority_value, Mapping):
        raise PipelineError("commentary projection authority must be an object")
    receipt = {
        "schema_version": "2.0",
        "receipt_version": RECEIPT_VERSION,
        "mapping_version": projection["mapping_version"],
        "assembler_version": projection["assembler_version"],
        "category": CATEGORY,
        "identity": copy.deepcopy(identity_value),
        "authority": copy.deepcopy(dict(authority_value)),
        "master_sha256": master_sha256,
        "scope_id": projection["scope_id"],
        "source_binding": copy.deepcopy(dict(projection["source_binding"])),
        "output_sha256": _hash_bytes(canonical_row_bytes([dict(row) for row in rows])),
        "row_count": len(rows),
        "anchors": copy.deepcopy(projection["anchors"]),
        "inventory": copy.deepcopy(projection["inventory"]),
        "references": copy.deepcopy(projection["references"]),
        "warnings": copy.deepcopy(projection["warnings"]),
        "exclusions": copy.deepcopy(projection["exclusions"]),
        "unsupported": copy.deepcopy(projection["unsupported"]),
        "schema_sha256": _hash_bytes(SCHEMA_PATH.read_bytes()),
        "common_schema_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()),
        "native_content_schema_sha256": _hash_bytes(native_content.SCHEMA.read_bytes()),
        "book_codes_sha256": _hash_bytes(BOOK_CODES_PATH.read_bytes()),
        "policy_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()),
        "independent_check": {"status": "pending", "errors": []},
    }
    return receipt


def _checker_parse(path: Path) -> tuple[Any, bytes, dict[Any, str], dict[Any, Any]]:
    """Parse TEI independently with lxml and reject hidden XML constructs."""
    from lxml import etree
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read commentary TEI {path}: {exc}") from exc
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False)
    try:
        tree = etree.fromstring(raw, parser=parser).getroottree()
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise PipelineError(f"invalid commentary TEI: {exc}") from exc
    root = tree.getroot()
    if tree.docinfo.doctype:
        raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")
    if root.xpath("//comment()"):
        raise UnsupportedStructure("unsupported-visible: XML comment")
    if root.xpath("//processing-instruction()"):
        raise UnsupportedStructure("unsupported-visible: processing instruction")
    if etree.QName(root).namespace != TEI_NS or etree.QName(root).localname != "TEI":
        raise PipelineError("commentary projection requires a TEI P5 root")
    parents = {child: parent for parent in root.iter() for child in parent}
    paths: dict[Any, str] = {root: "/TEI[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in parent:
            kind = etree.QName(child).localname
            counts[kind] = counts.get(kind, 0) + 1
            paths[child] = f"{paths[parent]}/{kind}[{counts[kind]}]"
    return root, raw, paths, parents


def _checker_validate(root: Any, paths: Mapping[Any, str], parents: Mapping[Any, Any]) -> None:
    """Validate the closed TEI subset without using the producer traversal."""
    from lxml import etree
    if [etree.QName(child).localname for child in root] != ["teiHeader", "text"]:
        raise UnsupportedStructure("unsupported-visible: TEI requires teiHeader then text")
    text_nodes = root.xpath("./tei:text", namespaces={"tei": TEI_NS})
    if len(text_nodes) != 1:
        raise UnsupportedStructure("unsupported-visible: commentary requires one text")
    parts = [etree.QName(child).localname for child in text_nodes[0]]
    if any(kind not in _TEXT_PARTS for kind in parts) or parts.count("body") != 1:
        raise UnsupportedStructure("unsupported-visible: text requires one body and optional front/back")
    seen: set[str] = set()
    for node in root.iter():
        kind = etree.QName(node).localname
        if etree.QName(node).namespace != TEI_NS:
            raise UnsupportedStructure(f"unsupported-visible: non-TEI element at {paths[node]}")
        node_id = node.get(f"{{{XML_NS}}}id")
        if node_id:
            if node_id in seen:
                raise UnsupportedStructure(f"unsupported-visible: duplicate xml:id at {paths[node]}")
            seen.add(node_id)
        if any(etree.QName(key).namespace is not None and key not in {f"{{{XML_NS}}}id", f"{{{XML_NS}}}lang", f"{{{XML_NS}}}space"} for key in node.attrib):
            raise UnsupportedStructure(f"unsupported-visible: attribute namespace at {paths[node]}")
        attrs = {
            "xml:id" if key == f"{{{XML_NS}}}id" else "xml:lang" if key == f"{{{XML_NS}}}lang" else etree.QName(key).localname if key.startswith("{") else key
            for key in node.attrib
        }
        if kind == "TEI":
            unknown = attrs - _ATTRS["TEI"]
            if unknown:
                raise UnsupportedStructure(f"unsupported-visible: TEI/@{sorted(unknown)[0]} at {paths[node]}")
            continue
        current = parents.get(node)
        in_header = kind == "teiHeader"
        while current is not None:
            if etree.QName(current).localname == "teiHeader":
                in_header = True
                break
            current = parents.get(current)
        if in_header:
            if kind not in _HEADER_NAMES:
                raise UnsupportedStructure(f"unsupported-visible: header element {kind} at {paths[node]}")
            allowed = {"xml:id", "type", "target", "place", "n", "when", "status", "ident"}
            if kind == "note":
                allowed.add("space")
                if node.get(f"{{{XML_NS}}}space") not in {None, "preserve"}:
                    raise UnsupportedStructure(f"unsupported-visible: header note/@xml:space at {paths[node]}")
            if attrs - allowed:
                raise UnsupportedStructure(f"unsupported-visible: header {kind}/@{sorted(attrs - allowed)[0]} at {paths[node]}")
            continue
        if kind == "div" and node.get("type") in {"selection", "outside-scope"}:
            if node.get("n") is not None or any(etree.QName(child).localname == "head" for child in node):
                raise UnsupportedStructure("unsupported-visible: administrative wrapper has source heading or number")
        if kind not in _ALLOWED_ELEMENTS:
            raise UnsupportedStructure(f"unsupported-visible: {kind} at {paths[node]}")
        unknown = attrs - _ATTRS.get(kind, set())
        if unknown:
            raise UnsupportedStructure(f"unsupported-visible: {kind}/@{sorted(unknown)[0]} at {paths[node]}")
        if kind == "note" and node.get("place") not in {None, "foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[node]}")
        if kind == "lb" and node.get("break") not in {None, "yes", "no"}:
            raise UnsupportedStructure(f"unsupported-visible: lb/@break at {paths[node]}")
        if kind == "ref" and "target" in node.attrib and "cRef" in node.attrib:
            raise UnsupportedStructure(f"unsupported-visible: ref has both @target and @cRef at {paths[node]}")
        if kind == "ref" and ("target" in node.attrib or "cRef" in node.attrib):
            target = (node.get("target") if "target" in node.attrib else node.get("cRef") or "").strip()
            if not target or len(target.split()) != 1:
                raise UnsupportedStructure(f"unsupported-visible: ambiguous reference target at {paths[node]}")
        if kind in {"text", "front", "body", "back", "div"}:
            if (node.text or "").strip() or any((child.tail or "").strip() for child in node):
                raise UnsupportedStructure(f"unsupported-visible: loose text in {kind} at {paths[node]}")
        if kind in {"lb", "pb", "anchor", "ptr"} and (len(node) or (node.text or "").strip()):
            raise UnsupportedStructure(f"unsupported-visible: nonempty milestone at {paths[node]}")


def _checker_header(root: Any, paths: Mapping[Any, str]) -> dict[str, Any]:
    from lxml import etree
    source_descs = root.xpath(".//tei:sourceDesc", namespaces={"tei": TEI_NS})
    if len(source_descs) != 1:
        raise PipelineError("commentary TEI must contain exactly one sourceDesc")
    ptrs = source_descs[0].xpath(".//tei:ptr", namespaces={"tei": TEI_NS})
    pointers = [(node.get("target") or "").strip() for node in ptrs]
    if len(ptrs) != 1 or not pointers[0]:
        raise UnsupportedStructure("unsupported-visible: commentary sourceDesc requires one source ptr")
    ids: dict[str, str] = {}
    for node in source_descs[0].xpath(".//tei:idno", namespaces={"tei": TEI_NS}):
        kind = (node.get("type") or "").strip().lower().replace("ocd-", "")
        value = _norm("".join(node.itertext()))
        if not value:
            continue
        if kind in {"sha256", "retained_sha256", "archive_sha256"}:
            key, checked = "retained_sha256", _valid_hash(value, field="retained source sha256")
        elif kind in {"source_sha256", "origin_sha256"}:
            key, checked = "source_sha256", _valid_hash(value, field="source sha256")
        elif kind in {"work_id", "textual_form_id", "edition_id", "acquisition_id", "representation_revision"}:
            key, checked = kind.replace("-", "_"), value
        else:
            continue
        if key in ids and ids[key] != checked:
            raise UnsupportedStructure(f"unsupported-visible: conflicting source idno {key}")
        ids[key] = checked
    if "retained_sha256" not in ids:
        raise PipelineError("commentary TEI sourceDesc must bind retained source sha256")
    return {"source_url": pointers[0], "retained_sha256": ids["retained_sha256"], "source_sha256": ids.get("source_sha256"), "ids": ids}


def _checker_ancestors(node: Any, parents: Mapping[Any, Any]) -> list[Any]:
    result: list[Any] = []
    current = parents.get(node)
    while current is not None:
        result.insert(0, current)
        current = parents.get(current)
    return result


def _checker_scope_source(node: Any, paths: Mapping[Any, str]) -> str:
    attrs = [(key, (node.get(key) or "").strip()) for key in ("scope", "target", "osisRef", "cRef", "corresp") if node.get(key)]
    if attrs:
        if len({value for _, value in attrs}) != 1:
            raise UnsupportedStructure(f"unsupported-visible: conflicting commentary targets at {paths[node]}")
        raw = attrs[0][1]
    else:
        refs = [ref for ref in node.xpath(".//tei:ref", namespaces={"tei": TEI_NS}) if (ref.get("type") or "") in _SCRIPTURE_TYPES]
        if len(refs) != 1:
            reason = "no primary target" if not refs else "multiple primary targets"
            raise UnsupportedStructure(f"unsupported-visible: commentary unit requires one {reason} at {paths[node]}")
        ref = refs[0]
        has_target, has_cref = "target" in ref.attrib, "cRef" in ref.attrib
        if has_target == has_cref:
            raise UnsupportedStructure(f"unsupported-visible: reference requires exactly one target at {paths[ref]}")
        raw = (ref.get("target") if has_target else ref.get("cRef") or "").strip()
    if not raw or raw.startswith("#") or len(raw.split()) != 1:
        raise UnsupportedStructure(f"unsupported-visible: commentary target is ambiguous at {paths[node]}")
    return raw


def _checker_candidates(body: Any, parents: Mapping[Any, Any]) -> list[Any]:
    from lxml import etree
    candidates: list[Any] = []
    for node in body.iter():
        kind = etree.QName(node).localname
        explicit = any(node.get(key) for key in ("scope", "target", "osisRef", "cRef", "corresp"))
        marked = kind == "div" and node.get("type") in _UNIT_TYPES
        refs = [ref for ref in node.xpath(".//tei:ref", namespaces={"tei": TEI_NS}) if (ref.get("type") or "") in _SCRIPTURE_TYPES and (ref.get("target") or ref.get("cRef"))]
        if marked and (explicit or refs or any(etree.QName(child).localname in {"p", "ab", "seg"} for child in node)):
            candidates.append(node)
        elif kind in {"p", "ab", "seg"} and (explicit or refs):
            candidates.append(node)
    result: list[Any] = []
    candidate_set = set(candidates)
    for node in candidates:
        if any(ancestor in candidate_set for ancestor in _checker_ancestors(node, parents) if etree.QName(ancestor).localname in {"div", "p", "ab", "seg"}):
            continue
        result.append(node)
    return result


def _checker_render(node: Any, paths: Mapping[Any, str], *, omit_notes: bool = True) -> str:
    from lxml import etree
    try:
        policy = json.loads(COMMON_SCHEMA_PATH.read_text(encoding="utf-8"))["x-ocd-projection-policy"]
        maps = policy["script"]["maps"]
        styles = set(policy["script"]["styles"])
        punctuation = set(policy["script"]["safe_punctuation"])
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PipelineError("cannot load controlled script rendering policy") from exc
    sentinel = "\x00"

    def visit(current: Any, style: str | None = None) -> str:
        kind = etree.QName(current).localname
        current_style = style
        if kind == "hi" and current.get("rend") in styles:
            if style is not None:
                raise UnsupportedStructure(f"unsupported-visible: nested script styles at {paths[current]}")
            current_style = current.get("rend")
        value = current.text or ""
        if current_style:
            converted: list[str] = []
            for char in value:
                if char in maps[current_style] or char.isspace() or char in punctuation:
                    converted.append(maps[current_style].get(char, char))
                else:
                    raise UnsupportedStructure(f"unsupported-visible: unsupported {current_style} script character {char!r} at {paths[current]}")
            value = "".join(converted)
        output = [value]
        for child in current:
            ck = etree.QName(child).localname
            if (ck == "note" and omit_notes) or ck in {"pb", "anchor", "ptr", "head", "label"}:
                output.append(sentinel)
            elif ck == "lb":
                output.append("" if child.get("break") == "no" else " ")
            else:
                output.append(visit(child, current_style))
                if ck in {"p", "ab", "seg"}:
                    output.append(" ")
            output.append(child.tail or "")
        return "".join(output)

    value = visit(node)
    for index, char in enumerate(value):
        if char == sentinel:
            before = value[index - 1] if index else ""
            after = value[index + 1] if index + 1 < len(value) else ""
            if before.isalnum() and after.isalnum():
                raise UnsupportedStructure(f"unsupported-visible: omitted inline boundary at {paths[node]}")
    return _norm(value.replace(sentinel, ""))


def _checker_divisions(node: Any, parents: Mapping[Any, Any]) -> list[dict[str, Any]]:
    from lxml import etree
    result: list[dict[str, Any]] = []
    for division in [item for item in _checker_ancestors(node, parents) if etree.QName(item).localname == "div"]:
        if division.get("type") in {"selection", "outside-scope"}:
            if division.get("n") is not None or any(etree.QName(child).localname == "head" for child in division):
                raise UnsupportedStructure("unsupported-visible: administrative wrapper has source heading or number")
            continue
        parent = parents.get(division)
        siblings = [child for child in parent if etree.QName(child).localname == "div"] if parent is not None else []
        titles = [_norm("".join(child.itertext())) for child in division if etree.QName(child).localname == "head" and _norm("".join(child.itertext()))]
        result.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "titles": titles})
    return result


def _checker_notes(node: Any, paths: Mapping[Any, str]) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    for note in node.xpath(".//tei:note", namespaces={"tei": TEI_NS}):
        place = note.get("place", "unspecified")
        if place not in {"foot", "end", "unspecified"}:
            raise UnsupportedStructure(f"unsupported-visible: note/@place at {paths[note]}")
        notes.append({"text": _checker_render(note, paths, omit_notes=False), "place": place, "label": note.get("n", "")})
    return notes


def _checker_account(root: Any, candidates: Sequence[Any], selected: Sequence[Any], paths: Mapping[Any, str], parents: Mapping[Any, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    from lxml import etree
    selected_set = set(selected)
    row_nodes = {child for unit in selected for child in unit.iter()}
    outside_nodes = {child for unit in candidates if unit not in selected_set for child in unit.iter()}
    excluded_nodes: set[Any] = set()
    for node in root.iter():
        if etree.QName(node).localname == "div" and node.get("type") in _EXCLUDED_TYPES:
            excluded_nodes.update(node.iter())
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for node in root.iter():
        kind = etree.QName(node).localname
        ancestors = _checker_ancestors(node, parents)
        if kind in {"TEI", "teiHeader"} or any(etree.QName(item).localname == "teiHeader" for item in ancestors):
            disposition = "private-header"
        elif node in excluded_nodes:
            disposition = "excluded-paratext"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif node in row_nodes and kind in {"head", "label"}:
            disposition = "locator-heading"
        elif node in row_nodes:
            disposition = "row-content"
        elif kind in {"head", "label"}:
            disposition = "locator-heading"
        else:
            disposition = "structure"
        attrs = {"xml:id" if key == f"{{{XML_NS}}}id" else "xml:lang" if key == f"{{{XML_NS}}}lang" else etree.QName(key).localname if key.startswith("{") else key: value for key, value in sorted(node.attrib.items())}
        inventory.append({"tei_path": paths[node], "disposition": disposition, "attributes": attrs, "text_sha256": _hash_text(node.text or ""), "tail_sha256": _hash_text(node.tail or "")})
        if disposition in {"outside-scope", "excluded-paratext"}:
            exclusions.append({"tei_path": paths[node], "reason": disposition})
        if disposition == "row-content" and kind in _WARNING_REASONS:
            warnings.append({"tei_path": paths[node], "reason": _WARNING_REASONS[kind]})
    return inventory, exclusions, warnings


def _checker_expected(path: Path, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None, source_url: str | None, source_sha256: str | None, retained_sha256: str | None, accessed_at: str | None, authority: Mapping[str, Any] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recompute rows and the complete receipt with an independent lxml walk."""
    from lxml import etree
    identity_value = _identity(identity)
    root, raw, paths, parents = _checker_parse(path)
    _checker_validate(root, paths, parents)
    for node in root.iter():
        if etree.QName(node).localname == "text" and node.get(XML_LANG) and node.get(XML_LANG).strip().lower() != language.strip().lower():
            raise UnsupportedStructure(f"unsupported-visible: source language {node.get(XML_LANG)} differs from emitted language {language}")
    header = _checker_header(root, paths)
    if source_url is not None and header["source_url"] != source_url:
        raise PipelineError("TEI source URL mismatch")
    if source_sha256 is not None and header.get("source_sha256") != _valid_hash(source_sha256, field="source sha256"):
        raise PipelineError("TEI source sha256 mismatch")
    if retained_sha256 is not None and header["retained_sha256"] != _valid_hash(retained_sha256, field="retained source sha256"):
        raise PipelineError("TEI retained sha256 mismatch")
    for key in _IDENTITY_KEYS:
        if header["ids"].get(key) not in {None, identity_value[key]}:
            raise PipelineError(f"TEI {key} mismatch")
    if header["ids"].get("representation_revision") not in {None, representation_revision}:
        raise PipelineError("TEI representation revision mismatch")
    body_nodes = root.xpath("./tei:text/tei:body", namespaces={"tei": TEI_NS})
    if len(body_nodes) != 1:
        raise UnsupportedStructure("unsupported-visible: commentary TEI requires one body")
    all_candidates = _checker_candidates(body_nodes[0], parents)
    if not all_candidates:
        raise UnsupportedStructure("unsupported-visible: no explicit commentary units")
    selected = list(all_candidates)
    if scope_id is not None:
        scopes = root.xpath(".//*[@xml:id=$id]", namespaces={"xml": XML_NS}, id=scope_id)
        if len(scopes) != 1 or scopes[0] not in set(body_nodes[0].iter()):
            raise UnsupportedStructure(f"unsupported-visible: commentary scope not found: {scope_id}")
        selected = [node for node in all_candidates if node is scopes[0] or node in set(scopes[0].iter())]
        if not selected:
            raise UnsupportedStructure("unsupported-visible: commentary scope contains no units")
    ordinals = {id(node): index for index, node in enumerate(all_candidates, 1)}
    expected: list[dict[str, Any]] = []
    receipt_refs: list[dict[str, Any]] = []
    for sequence, node in enumerate(selected, 1):
        raw_scope = _checker_scope_source(node, paths)
        text = _checker_render(node, paths)
        if not text:
            raise UnsupportedStructure(f"unsupported-visible: empty commentary unit at {paths[node]}")
        text_parts = [ancestor for ancestor in _checker_ancestors(node, parents) if etree.QName(ancestor).localname in _TEXT_PARTS]
        if len(text_parts) != 1:
            raise UnsupportedStructure(f"unsupported-visible: commentary unit has no unique text part at {paths[node]}")
        part = etree.QName(text_parts[0]).localname
        part_titles = [_norm("".join(head.itertext())) for head in text_parts[0] if etree.QName(head).localname == "head" and _norm("".join(head.itertext()))]
        locator: dict[str, Any] = {"kind": "commentary-unit", "text_part": part, "part_titles": part_titles, "divisions": _checker_divisions(node, parents), "scope": _observe_scope(raw_scope), "unit": sequence, "source_order": ordinals[id(node)]}
        locator['scope'].update(_observed_scope_labels(node, paths))
        _english_book_label(locator['scope'])
        if node.get('subtype') is not None:
            if node.get('subtype') != 'introduction' or locator['scope'].get('reference', {}).get('kind') not in ('book', 'chapter'):
                raise UnsupportedStructure('checker: invalid introduction role or scope')
            locator['unit_role'] = 'introduction'
        public_refs: list[dict[str, Any]] = []
        for ref in node.xpath(".//tei:ref", namespaces={"tei": TEI_NS}):
            has_target, has_cref = "target" in ref.attrib, "cRef" in ref.attrib
            if has_target == has_cref:
                raise UnsupportedStructure(f"unsupported-visible: reference requires one target at {paths[ref]}")
            target = (ref.get("target") if has_target else ref.get("cRef") or "").strip()
            if not target or len(target.split()) != 1:
                raise UnsupportedStructure(f"unsupported-visible: ambiguous reference target at {paths[ref]}")
            if has_cref and target.startswith("#"):
                raise UnsupportedStructure(f"unsupported-visible: cRef cannot identify a local TEI target at {paths[ref]}")
            item = {"label": _checker_render(ref, paths, omit_notes=False), "resolution": "external", "target_record_id": None, "target_note": None, "source_note": None}
            if ref.get('type'):
                item['source_role'] = ref.get('type')
            if not target.startswith('#'):
                item['source_target'] = target
                if ref.get('type') in _SCRIPTURE_TYPES or ref.get('type') == 'scripture-cross-reference':
                    normalized_scope = _observe_scope(target)
                    item['normalization_status'] = normalized_scope['normalization_status']
                    if 'reference' in normalized_scope:
                        item['scripture'] = normalized_scope['reference']
            public_refs.append(item)
            receipt_refs.append({"tei_path": paths[ref], "original_target": target, **{key: value for key, value in item.items() if key != "label"}})
        notes = _checker_notes(node, paths)
        row = make_row(record_id=f"{identity_value['edition_id']}:commentary-{ordinals[id(node)]:06d}", sequence=sequence, work_id=identity_value["work_id"], textual_form_id=identity_value["textual_form_id"], edition_id=identity_value["edition_id"], category=CATEGORY, language=language, text=text, locator=locator, provenance={"edition_title": edition_title, **_observe_entry_attribution(node)}, representation_revision=representation_revision, notes=notes)
        row["notes"] = notes
        row["references"] = public_refs
        expected.append(row)
    inventory, exclusions, warnings = _checker_account(root, all_candidates, selected, paths, parents)
    binding: dict[str, Any] = {"source_url": header["source_url"], "retained_sha256": header["retained_sha256"]}
    if header.get("source_sha256"):
        binding["source_sha256"] = header["source_sha256"]
    if accessed_at is not None:
        binding["accessed_at"] = accessed_at
    authority_value = authority if authority is not None else {}
    if not isinstance(authority_value, Mapping):
        raise PipelineError("commentary authority must be an object")
    receipt = {
        "schema_version": "2.0", "receipt_version": RECEIPT_VERSION,
        "mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION,
        "category": CATEGORY, "identity": copy.deepcopy(identity_value),
        "authority": copy.deepcopy(dict(authority_value)), "master_sha256": _hash_bytes(raw),
        "scope_id": scope_id, "source_binding": binding,
        "output_sha256": _hash_bytes(canonical_row_bytes(expected)), "row_count": len(expected),
        "anchors": [{"record_id": row["record_id"], "tei_path": paths[selected[index]], "text_sha256": row_text_hash(row["text"]), "source_order": row["locator"]["source_order"], "locator": copy.deepcopy(row["locator"])} for index, row in enumerate(expected)],
        "inventory": inventory, "references": receipt_refs, "warnings": warnings,
        "exclusions": exclusions, "unsupported": [],
        "schema_sha256": _hash_bytes(SCHEMA_PATH.read_bytes()),
        "common_schema_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()),
        "native_content_schema_sha256": _hash_bytes(native_content.SCHEMA.read_bytes()),
        "book_codes_sha256": _hash_bytes(BOOK_CODES_PATH.read_bytes()),
        "policy_sha256": _hash_bytes(COMMON_SCHEMA_PATH.read_bytes()),
        "independent_check": {"status": "pending", "errors": []},
    }
    return expected, receipt


def verify_commentary_document(tei_path: Path, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None = None, *, identity: Mapping[str, str], language: str, representation_revision: str, edition_title: str, scope_id: str | None = None, source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, accessed_at: str | None = None, authority: Mapping[str, Any] | None = None, **_: Any) -> list[str]:
    """Check rows and every receipt field with a producer-independent traversal."""
    errors: list[str] = []
    try:
        identity_value = _identity(identity)
    except (PipelineError, TypeError, ValueError) as exc:
        return [str(exc)]
    if isinstance(rows, Mapping):
        if "rows" not in rows:
            return ["checker requires a projection object with rows"]
        if receipt is None and isinstance(rows.get("receipt"), Mapping):
            receipt = rows["receipt"]
        provided = rows["rows"]
    else:
        provided = rows
    if not isinstance(provided, Sequence) or isinstance(provided, (str, bytes)):
        return ["checker requires a row sequence"]
    try:
        expected, expected_receipt = _checker_expected(Path(tei_path), identity=identity_value, language=language, representation_revision=representation_revision, edition_title=edition_title, scope_id=scope_id, source_url=source_url, source_sha256=source_sha256, retained_sha256=retained_sha256, accessed_at=accessed_at, authority=authority)
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
    if len(provided) != len(expected):
        errors.append(f"row count mismatch: {len(provided)} != {len(expected)}")
    for index, (actual, wanted) in enumerate(zip(provided, expected), 1):
        if not isinstance(actual, Mapping):
            errors.append(f"row {index} is not an object")
            continue
        if dict(actual) != wanted:
            for key in sorted(set(actual) | set(wanted)):
                if actual.get(key) != wanted.get(key):
                    errors.append(f"row {index} {key} mismatch")
        schema_errors = sorted(_validator().iter_errors(actual), key=lambda error: list(error.path))
        if schema_errors:
            errors.append(f"row {index} schema mismatch: {schema_errors[0].message}")
    if receipt is None:
        errors.append("commentary receipt is missing")
    elif not isinstance(receipt, Mapping):
        errors.append("commentary receipt must be an object")
    else:
        for key, wanted in expected_receipt.items():
            if receipt.get(key) != wanted:
                errors.append(f"commentary receipt {key} mismatch")
        if set(receipt) != set(expected_receipt):
            errors.append("commentary receipt fields mismatch")
    return sorted(set(errors))


check_commentary_document = verify_commentary_document
verify_document = verify_commentary_document


def _accepted_authority(
    root: Path,
    *,
    acceptance_path: Path,
    work_path: Path,
    master_path: Path,
    acquisition_path: Path,
) -> dict[str, dict[str, str]]:
    """Bind accepted authority files by exact relative path and bytes hash."""

    base = resolve_path(root)
    bindings: dict[str, dict[str, str]] = {}
    for name, value in (
        ("acceptance", acceptance_path),
        ("work", work_path),
        ("master", master_path),
        ("acquisition", acquisition_path),
    ):
        path = resolve_path(value)
        if not io_path(path).is_file():
            raise PipelineError(f"accepted authority file is missing: {path}")
        try:
            relative = path.relative_to(base).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PipelineError(f"accepted authority file is outside root: {path}") from exc
        bindings[name] = {"path": relative, "sha256": _hash_bytes(io_path(path).read_bytes())}
    return bindings


def _accepted_metadata(root: Path, acceptance_path: Path) -> dict[str, Any]:
    """Validate accepted sidecars and derive the canonical edition context."""

    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.tei.acceptance import validate_acceptance

    base = resolve_path(root)
    accepted_path = resolve_path(acceptance_path)
    accepted = validate_acceptance(accepted_path, root=base)
    if accepted["promotion"]["status"] != "promoted":
        raise PipelineError("commentary projection requires a promoted accepted master")
    identity = {key: accepted["identity"][key] for key in _IDENTITY_KEYS}
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    category = edition.record.get("category", work.record.get("category"))
    if category != CATEGORY:
        raise PipelineError("accepted edition is not a commentary category")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str):
        raise PipelineError("accepted commentary edition has no language")
    acquisition_path, acquisition = acquisition_for_edition(
        base,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=accepted["identity"]["acquisition_id"],
    )
    master_path = resolve_path(edition.path)
    authority = _accepted_authority(
        base,
        acceptance_path=accepted_path,
        work_path=work.path,
        master_path=master_path,
        acquisition_path=acquisition_path,
    )
    return {
        "root": base,
        "acceptance": accepted,
        "acceptance_path": accepted_path,
        "identity": identity,
        "work": work,
        "edition": edition,
        "master_path": master_path,
        "language": language,
        "acquisition": acquisition,
        "acquisition_path": acquisition_path,
        "authority": authority,
    }


def _validate_accepted_header(
    header: Mapping[str, Any], metadata: Mapping[str, Any]
) -> None:
    """Bind category TEI source facts to the validated acceptance record."""

    accepted = metadata["acceptance"]
    acquisition = metadata["acquisition"]
    source = accepted["source"]
    if header.get("source_url") != acquisition.get("url"):
        raise PipelineError("accepted commentary master source URL does not bind acquisition")
    if header.get("source_sha256") != source["source_sha256"]:
        raise PipelineError("accepted commentary master source SHA-256 does not bind acquisition")
    included = accepted["scope"].get("included_members", [])
    if len(included) == 1 and header.get("retained_sha256") != included[0]["sha256"]:
        raise PipelineError("accepted commentary master retained hash does not bind source accounting")


def project_accepted_commentary(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Project a promoted commentary master from validated acceptance evidence."""

    metadata = _accepted_metadata(root, acceptance_path)
    from ocd_kernel.projection.categories.prose import _accepted_projection_profile
    from ocd_kernel.projection.categories.lib040_augustine_divisions import PROFILE as LIB040_DIVISIONS_PROFILE
    if _accepted_projection_profile(metadata["root"], {"accepted": metadata["acceptance"]}) == LIB040_DIVISIONS_PROFILE:
        from ocd_kernel.projection.categories.lib040_augustine_divisions import project as project_lib040_divisions
        return project_lib040_divisions(root, acceptance_path=acceptance_path, category="commentary")
    from ocd_kernel.projection.categories import commentary_source_native
    source_native_family = commentary_source_native.route(metadata)
    if source_native_family is not None:
        return commentary_source_native.project(metadata, source_native_family)
    from ocd_kernel.projection.categories import augustine_psalms_native
    if augustine_psalms_native.route(metadata):
        return augustine_psalms_native.project(metadata)
    accepted = metadata["acceptance"]
    identity = metadata["identity"]
    edition = metadata["edition"]
    edition_path = metadata["master_path"]
    from ocd_kernel.projection.categories import native_documents
    if native_documents.is_source_collection(edition_path):
        return native_documents.project_accepted_document(root, acceptance_path=acceptance_path, category='commentary')
    root_tei, _ = _read_root(edition_path)
    _validate_elements(root_tei, _paths(root_tei))
    header = _header(root_tei)
    _validate_accepted_header(header, metadata)
    result = project_commentary_document(
        edition_path,
        identity=identity,
        language=metadata["language"],
        representation_revision=accepted["representation_revision"]["id"],
        edition_title=edition.title,
        source_url=header["source_url"],
        source_sha256=header.get("source_sha256"),
        retained_sha256=header["retained_sha256"],
    )
    result["authority"] = copy.deepcopy(metadata["authority"])
    result["receipt"] = build_commentary_receipt(
        result, identity=identity, authority=result["authority"]
    )
    return result


project_accepted = project_accepted_commentary


def verify_accepted_commentary(
    root: Path,
    *,
    acceptance_path: Path,
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted rows without invoking the category producer."""

    try:
        metadata = _accepted_metadata(root, acceptance_path)
        from ocd_kernel.projection.categories.prose import _accepted_projection_profile
        from ocd_kernel.projection.categories.lib040_augustine_divisions import PROFILE as LIB040_DIVISIONS_PROFILE
        if _accepted_projection_profile(metadata["root"], {"accepted": metadata["acceptance"]}) == LIB040_DIVISIONS_PROFILE:
            from ocd_kernel.projection.categories.lib040_augustine_divisions import verify as verify_lib040_divisions
            return verify_lib040_divisions(root, acceptance_path=acceptance_path, category="commentary", rows=rows, receipt=receipt)
        from ocd_kernel.projection.categories import commentary_source_native
        source_native_family = commentary_source_native.route(metadata)
        if source_native_family is not None:
            return commentary_source_native.verify(metadata, source_native_family, rows, receipt)
        from ocd_kernel.projection.categories import augustine_psalms_native
        if augustine_psalms_native.route(metadata):
            return augustine_psalms_native.verify(metadata, rows, receipt)
        master_path = metadata["master_path"]
        from ocd_kernel.projection.categories import native_documents
        if native_documents.is_source_collection(master_path):
            return native_documents.verify_accepted_document(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt, category='commentary')
        checker_root, _raw, checker_paths, checker_parents = _checker_parse(master_path)
        _checker_validate(checker_root, checker_paths, checker_parents)
        header = _checker_header(checker_root, checker_paths)
        _validate_accepted_header(header, metadata)
        accepted = metadata["acceptance"]
        return verify_commentary_document(
            master_path,
            rows,
            receipt,
            identity=metadata["identity"],
            language=metadata["language"],
            representation_revision=accepted["representation_revision"]["id"],
            edition_title=metadata["edition"].title,
            source_url=header["source_url"],
            source_sha256=header.get("source_sha256"),
            retained_sha256=header["retained_sha256"],
            authority=metadata["authority"],
        )
    except (PipelineError, OSError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]


__all__ = ["ASSEMBLER_VERSION", "CATEGORY", "MAPPING_VERSION", "RECEIPT_VERSION", "UnsupportedStructure", "build_commentary_receipt", "check_commentary_document", "project", "project_accepted", "project_accepted_commentary", "project_commentary", "project_commentary_document", "project_document", "verify_accepted_commentary", "verify_commentary_document", "verify_document"]
