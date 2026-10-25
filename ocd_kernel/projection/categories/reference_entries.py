"""Source-bound reference-entry projection (PIPE-014A).

Dictionary headwords, definition blocks, source-attested cross-references, and
entry locators remain separate fields.  The checker traverses TEI with lxml
independently of the ElementTree producer and recomputes the complete receipt.
"""

from __future__ import annotations
from ocd_kernel.projection.native_content_check import projection_validator

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence

from ocd_kernel.library._common import PipelineError


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "schemas/v2/categories/reference-entries.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
MAPPING_VERSION = "ocd-reference-entries-mapping-v2"
RECEIPT_VERSION = "ocd-reference-entries-receipt-v2"
ASSEMBLER_VERSION = "ocd-reference-entries-assembler-v2"
_IDENTITY_KEYS = ("work_id", "textual_form_id", "edition_id")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_ENTRY_TYPES = {"dictionary-entry", "encyclopedia-entry", "entry"}
_EASTON_PROFILE = "easton-native-lexical-v1"
_EASTON_IDENTITY = {
    "work_id": "eastons-bible-dictionary",
    "textual_form_id": "eastons-bible-dictionary-retained-electronic",
    "edition_id": "eastons-bible-dictionary-retained-electronic-witness",
}
_EASTON_ROOT_ID = "eastons-bible-dictionary-candidate"
_HITCHCOCK_PROFILE = "hitchcock-native-lexical-v1"
_HITCHCOCK_IDENTITY = {
    "work_id": "hitchcocks-bible-names-dictionary",
    "textual_form_id": "hitchcocks-bible-names-dictionary-retained-electronic",
    "edition_id": "hitchcocks-bible-names-dictionary-retained-electronic-witness",
}
_HITCHCOCK_ROOT_ID = "hitchcocks-bible-names-dictionary-candidate"
_SMITH_PROFILE = "smith-native-lexical-v1"
_SMITH_IDENTITY = {
    "work_id": "smiths-bible-dictionary",
    "textual_form_id": "smiths-bible-dictionary-retained-electronic",
    "edition_id": "smiths-bible-dictionary-retained-electronic-witness",
}
_SMITH_ROOT_ID = "smiths-bible-dictionary-candidate"
_EXCLUDED_TYPES = {"title-page", "half-title-page", "copyright-page", "imprint", "colophon"}
_TEXT_PARTS = {"front", "body", "back"}
_INLINE = {"ref", "ptr", "hi", "foreign", "seg", "lb", "pb", "anchor", "note"}
_STRUCTURE = {"text", "front", "body", "back", "div", "head", "p", "ab", "list", "item", *_INLINE}
_HEADER = {"TEI", "teiHeader", "fileDesc", "titleStmt", "title", "publicationStmt", "sourceDesc", "bibl", "idno", "ptr", "revisionDesc", "change", "list", "item", "p", "ab", "date", "editionStmt", "edition", "respStmt", "resp", "author", "availability", "licence", "distributor", "encodingDesc", "projectDesc", "desc", "ref", "note"}
_EASTON_HEADER = {"listBibl", "num", "publisher"}
_EASTON_LEXICAL = {"entry", "form", "orth", "sense", "def"}
_ATTRIBUTES = {
    "TEI": {XML_ID, XML_LANG}, "teiHeader": {XML_ID, XML_LANG}, "fileDesc": {XML_ID, XML_LANG}, "titleStmt": {XML_ID, XML_LANG},
    "title": {XML_ID, XML_LANG, "type"}, "publicationStmt": {XML_ID, XML_LANG}, "sourceDesc": {XML_ID, XML_LANG},
    "bibl": {XML_ID, XML_LANG, "type"}, "idno": {XML_ID, XML_LANG, "type"}, "ptr": {XML_ID, XML_LANG, "type", "target"},
    "revisionDesc": {XML_ID, XML_LANG}, "change": {XML_ID, XML_LANG, "when", "type"}, "editionStmt": {XML_ID, XML_LANG},
    "edition": {XML_ID, XML_LANG, "n", "type"}, "respStmt": {XML_ID, XML_LANG}, "resp": {XML_ID, XML_LANG, "type"},
    "author": {XML_ID, XML_LANG, "role"}, "availability": {XML_ID, XML_LANG}, "licence": {XML_ID, XML_LANG, "target"},
    "distributor": {XML_ID, XML_LANG}, "encodingDesc": {XML_ID, XML_LANG}, "projectDesc": {XML_ID, XML_LANG},
    "desc": {XML_ID, XML_LANG, "type"}, "date": {XML_ID, XML_LANG, "when"}, "text": {XML_ID, XML_LANG},
    "front": {XML_ID, XML_LANG}, "body": {XML_ID, XML_LANG}, "back": {XML_ID, XML_LANG}, "div": {XML_ID, XML_LANG, "type", "n"},
    "head": {XML_ID, XML_LANG, "type"}, "p": {XML_ID, XML_LANG, "type", "n"}, "ab": {XML_ID, XML_LANG, "type"},
    "list": {XML_ID, XML_LANG, "type"}, "item": {XML_ID, XML_LANG, "n", "type"}, "ref": {XML_ID, XML_LANG, "type", "target", "cRef"},
    "note": {XML_ID, XML_LANG, "place", "n", "type"}, "hi": {XML_ID, XML_LANG, "rend", "type"}, "foreign": {XML_ID, XML_LANG, "lang", "type"},
    "seg": {XML_ID, XML_LANG, "type"}, "lb": {XML_ID, XML_LANG, "break", "n"}, "pb": {XML_ID, XML_LANG, "n", "facs"}, "anchor": {XML_ID, XML_LANG, "type", "n"},
}
_EASTON_ATTRIBUTES = {
    "listBibl": {"type"}, "num": {"type"}, "publisher": set(),
    "entry": {XML_ID, "n"}, "form": set(), "orth": {"type"},
    "sense": {XML_ID}, "def": {XML_ID, "n"},
    "text": {XML_ID, XML_LANG, "type"},
    "availability": {XML_ID, XML_LANG, "status"},
}


def _easton_profile(root: Any, identity: Mapping[str, str], selector: Mapping[str, Any] | None) -> bool:
    """The retained lexical witness is an explicit, exact-identity opt-in."""
    if selector is None or "tei_entry_profile" not in selector:
        return False
    profiles = {
        _EASTON_PROFILE: (_EASTON_IDENTITY, _EASTON_ROOT_ID),
        _HITCHCOCK_PROFILE: (_HITCHCOCK_IDENTITY, _HITCHCOCK_ROOT_ID),
        _SMITH_PROFILE: (_SMITH_IDENTITY, _SMITH_ROOT_ID),
    }
    selected = selector.get("tei_entry_profile")
    if not isinstance(selected, str) or selected not in profiles:
        raise UnsupportedStructure("unsupported-visible: native lexical TEI profile/identity mismatch")
    expected_identity, expected_root = profiles[selected]
    if (any(identity.get(key) != value for key, value in expected_identity.items())
            or root.get(XML_ID) != expected_root):
        raise UnsupportedStructure("unsupported-visible: native lexical TEI profile/identity mismatch")
    return True


class UnsupportedStructure(PipelineError):
    """A visible reference-entry feature is outside the closed mapping."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_text(value: str) -> str:
    return _sha_bytes(value.encode("utf-8"))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _attr_name(key: str) -> str:
    if key == XML_ID:
        return "xml:id"
    if key == XML_LANG:
        return "xml:lang"
    return key.rsplit("}", 1)[-1] if key.startswith("{") else key


def _logical_source_path(path: Path) -> str:
    try:
        return path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError:
        return path.absolute().as_posix()


def _paths(root: ET.Element) -> dict[ET.Element, str]:
    paths: dict[ET.Element, str] = {root: f"/{_local(root.tag)}[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in list(parent):
            kind = _local(child.tag)
            counts[kind] = counts.get(kind, 0) + 1
            paths[child] = f"{paths[parent]}/{kind}[{counts[kind]}]"
    return paths


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def _ancestors(node: ET.Element, parents: Mapping[ET.Element, ET.Element]) -> list[ET.Element]:
    result: list[ET.Element] = []
    current = parents.get(node)
    while current is not None:
        result.append(current)
        current = parents.get(current)
    return result


class _RejectingBuilder(ET.TreeBuilder):
    def comment(self, text: str) -> None:
        raise UnsupportedStructure("unsupported-visible: XML comment")

    def pi(self, target: str, text: str) -> None:
        raise UnsupportedStructure("unsupported-visible: processing instruction")

    def doctype(self, name: str, pubid: str, system: str) -> None:
        raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")


def _read_root(path: Path) -> tuple[ET.Element, bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PipelineError(f"cannot read reference-entry TEI {path}: {exc}") from exc
    if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
        raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=_RejectingBuilder()))
    except UnsupportedStructure:
        raise
    except ET.ParseError as exc:
        raise PipelineError(f"invalid reference-entry TEI: {exc}") from exc
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise UnsupportedStructure("unsupported-visible: reference-entry TEI root required")
    for node in root.iter():
        if not isinstance(node.tag, str) or not node.tag.startswith(f"{{{TEI_NS}}}"):
            raise UnsupportedStructure("unsupported-visible: non-TEI element or namespace")
    return root, raw


def _identity(identity: Mapping[str, str]) -> dict[str, str]:
    if set(identity) != set(_IDENTITY_KEYS):
        raise PipelineError("public identity requires exactly work_id, textual_form_id, and edition_id")
    result: dict[str, str] = {}
    for key in _IDENTITY_KEYS:
        value = identity.get(key)
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise PipelineError(f"invalid public identity {key}")
        result[key] = value
    return result


def _valid_sha(value: str, field: str) -> str:
    value = str(value).strip().lower().removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PipelineError(f"{field} must be a SHA-256 digest")
    return value


def _validate_attributes(root: ET.Element, paths: Mapping[ET.Element, str], *, easton: bool = False) -> None:
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in _HEADER and kind not in _STRUCTURE and not (easton and kind in _EASTON_HEADER | _EASTON_LEXICAL):
            raise UnsupportedStructure(f"unsupported-visible: element {kind} at {paths[node]}")
        for key in node.attrib:
            allowed = _EASTON_ATTRIBUTES.get(kind, _ATTRIBUTES.get(kind, {XML_ID, XML_LANG})) if easton else _ATTRIBUTES.get(kind, {XML_ID, XML_LANG})
            if key not in allowed:
                raise UnsupportedStructure(f"unsupported-visible: {kind}@{_attr_name(key)} at {paths[node]}")
        if kind == "ref" and node.get("target") and node.get("cRef"):
            raise UnsupportedStructure(f"unsupported-visible: ref has both target and cRef at {paths[node]}")


def _source_binding(root: ET.Element, context: Mapping[str, Any], *, easton: bool = False) -> dict[str, str]:
    source_desc = [node for node in root.iter() if _local(node.tag) == "sourceDesc"]
    if len(source_desc) != 1:
        raise PipelineError("reference-entry TEI must contain exactly one sourceDesc")
    binding = source_desc[0]
    if easton:
        scoped = [node for node in binding if _local(node.tag) == "bibl" and node.get("type") == "ocd-acceptance-binding"]
        if len(scoped) != 1:
            raise PipelineError("Easton native TEI requires one scoped acceptance binding")
        binding = scoped[0]
    ids: dict[str, str] = {}
    hashes: dict[str, str] = {}
    source_url = ""
    source_path_label = ""
    for node in binding.iter():
        kind = _local(node.tag)
        if kind == "idno":
            value = _norm("".join(node.itertext()))
            typ = (node.get("type") or "").lower().replace("-", "_")
            if typ in _IDENTITY_KEYS:
                ids[typ] = value
            elif typ in {"source_sha256", "origin_sha256"}:
                hashes["source_sha256"] = _valid_sha(value, "source_sha256")
            elif typ in {"retained_sha256", "archive_sha256", "sha256"}:
                hashes["retained_sha256"] = _valid_sha(value, "retained_sha256")
        elif kind in {"ptr", "ref"} and not source_url and node.get("target"):
            source_url = _norm(node.get("target"))
        elif kind == "note" and (node.get("type") or "").lower().replace("-", "_") in {"source_path", "source_location"}:
            source_path_label = _norm("".join(node.itertext()))
    for key in _IDENTITY_KEYS:
        if ids.get(key) != context["identity"][key]:
            raise PipelineError(f"reference-entry TEI {key} mismatch")
    if not source_url:
        raise PipelineError("reference-entry TEI sourceDesc is missing source URL")
    if set(hashes) != {"source_sha256", "retained_sha256"}:
        raise PipelineError("reference-entry TEI sourceDesc is missing source hashes")
    for key in hashes:
        expected = context.get(key)
        if expected is not None and hashes[key] != _valid_sha(expected, key):
            raise PipelineError(f"reference-entry TEI {key} mismatch")
    expected_url = context.get("source_url")
    if expected_url is not None and source_url != expected_url:
        raise PipelineError("reference-entry TEI source URL mismatch")
    source_path = context.get("source_path")
    if source_path is not None:
        expected_path = context.get("source_logical_path") or _logical_source_path(Path(source_path))
        if source_path_label != expected_path:
            raise PipelineError("reference-entry TEI source path mismatch")
        try:
            actual = _sha_bytes(Path(source_path).read_bytes())
        except OSError as exc:
            raise PipelineError(f"cannot read retained reference source {source_path}: {exc}") from exc
        if actual != hashes["retained_sha256"]:
            raise PipelineError("reference-entry retained source hash does not match sourceDesc")
    binding = {"source_url": source_url, **hashes}
    if source_path_label:
        binding["source_path"] = source_path_label
    return binding


def _text_parts(root: ET.Element) -> list[ET.Element]:
    texts = [node for node in list(root) if _local(node.tag) == "text"]
    if len(texts) != 1:
        raise UnsupportedStructure("unsupported-visible: reference entries require one text element")
    parts = [node for node in list(texts[0]) if _local(node.tag) in _TEXT_PARTS]
    if not parts or any(_local(node.tag) not in _TEXT_PARTS for node in list(texts[0])):
        raise UnsupportedStructure("unsupported-visible: reference text has no accounted front/body/back")
    return parts


def _easton_lexical(entry: ET.Element, ordinal: int, paths: Mapping[ET.Element, str], *, work_id: str = "eastons-bible-dictionary") -> tuple[str, list[str]]:
    """Read only the exact retained entry/form/orth/sense/def shape."""
    prefix = f"{work_id}-entry-{ordinal:05d}"
    if (entry.get("n") != str(ordinal) or entry.get(XML_ID) != prefix
            or [_local(node.tag) for node in entry] != ["form", "sense"]
            or (entry.text or "").strip() or (entry.tail or "").strip()):
        raise UnsupportedStructure(f"unsupported-visible: Easton entry identity/shape at {paths[entry]}")
    form, sense = list(entry)
    if (len(form) != 1 or _local(form[0].tag) != "orth" or (form.text or "").strip()
            or (form.tail or "").strip() or sense.get(XML_ID) != prefix + "-sense"
            or (sense.text or "").strip() or (sense.tail or "").strip()):
        raise UnsupportedStructure(f"unsupported-visible: Easton form/sense at {paths[entry]}")
    orth = form[0]
    if (orth.get("type") != "headword" or not orth.text or len(orth)
            or (orth.tail or "").strip()):
        raise UnsupportedStructure(f"unsupported-visible: Easton headword at {paths[orth]}")
    definitions = list(sense)
    if not definitions:
        raise UnsupportedStructure(f"unsupported-visible: Easton entry has no definitions at {paths[entry]}")
    for index, node in enumerate(definitions, 1):
        if (_local(node.tag) != "def" or node.get("n") != str(index)
                or node.get(XML_ID) != f"{prefix}-definition-{index:03d}"
                or not node.text or len(node) or (node.tail or "").strip()):
            raise UnsupportedStructure(f"unsupported-visible: Easton definition at {paths[node]}")
    return orth.text, [node.text for node in definitions]


def _render(node: ET.Element | None) -> str:
    if node is None:
        return ""
    chunks: list[str] = []

    def visit(current: ET.Element) -> None:
        if current.text:
            chunks.append(current.text)
        for child in list(current):
            kind = _local(child.tag)
            if kind == "lb":
                chunks.append("" if child.get("break") == "no" else " ")
            elif kind in {"pb", "anchor", "ptr"}:
                chunks.append(" ")
            else:
                visit(child)
            if child.tail:
                chunks.append(child.tail)

    visit(node)
    return _norm("".join(chunks))


def _inline_check(node: ET.Element, paths: Mapping[ET.Element, str]) -> None:
    for child in list(node):
        if _local(child.tag) not in _INLINE:
            raise UnsupportedStructure(f"unsupported-visible: reference inline {_local(child.tag)} at {paths[child]}")
        _inline_check(child, paths)


def _entries(parts: Sequence[ET.Element], scope: ET.Element | None, parents: Mapping[ET.Element, ET.Element], *, easton: bool = False, work_id: str = "eastons-bible-dictionary") -> tuple[list[ET.Element], list[ET.Element]]:
    if easton:
        if (len(parts) != 1 or _local(parts[0].tag) != "body"
                or parents[parts[0]].get(XML_ID) != f"{work_id}-text"
                or parents[parts[0]].get("type") != "dictionary"
                or parts[0].get(XML_ID) != f"{work_id}-body"
                or (parts[0].text or "").strip()
                or any(_local(node.tag) != "entry" for node in parts[0])):
            raise UnsupportedStructure("unsupported-visible: Easton body must contain only native entries")
        all_entries = list(parts[0])
        return all_entries, [node for node in all_entries if scope is None or node is scope]
    all_entries = [
        node for part in parts for node in part.iter()
        if _local(node.tag) == "div" and node.get("type") in _ENTRY_TYPES
        and not any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *_ancestors(node, parents)])
    ]
    selected = [node for node in all_entries if scope is None or node is scope or scope in _ancestors(node, parents)]
    return all_entries, selected


def _scope(parts: Sequence[ET.Element], scope_id: str | None, *, easton: bool = False) -> ET.Element | None:
    if scope_id is None:
        return None
    found = [node for part in parts for node in part.iter() if node.get(XML_ID) == scope_id]
    if len(found) != 1 or (easton and _local(found[0].tag) != "entry") or (not easton and (_local(found[0].tag) != "div" or found[0].get("type") not in _ENTRY_TYPES)):
        raise UnsupportedStructure(f"unsupported-visible: reference scope is not one entry div: {scope_id}")
    return found[0]


def _source_order(entry: ET.Element, fallback: int, paths: Mapping[ET.Element, str]) -> int:
    raw = _norm(entry.get("n"))
    if not raw:
        return fallback
    if not raw.isdigit() or int(raw) < 1:
        raise UnsupportedStructure(f"unsupported-visible: reference source order must be a positive integer at {paths[entry]}")
    return int(raw)


def _source_entry_id(source_order: int) -> str:
    """Return a public source-order identifier, never a private TEI xml:id."""
    return f"source-order-{source_order:06d}"


def _headword(entry: ET.Element, paths: Mapping[ET.Element, str]) -> str:
    heads = [child for child in list(entry) if _local(child.tag) == "head" and (child.get("type") or "headword") == "headword"]
    if len(heads) != 1 or not _render(heads[0]):
        raise UnsupportedStructure(f"unsupported-visible: reference entry needs exactly one non-empty headword at {paths[entry]}")
    return _render(heads[0])


def _alternate_terms(entry: ET.Element, paths: Mapping[ET.Element, str]) -> list[str] | None:
    lists = [child for child in list(entry) if _local(child.tag) == "list" and child.get("type") == "alternate-terms"]
    if len(lists) > 1:
        raise UnsupportedStructure(f"unsupported-visible: multiple alternate-term lists at {paths[entry]}")
    if not lists:
        return None
    terms: list[str] = []
    for item in list(lists[0]):
        if _local(item.tag) != "item" or not _render(item):
            raise UnsupportedStructure(f"unsupported-visible: alternate term item is empty at {paths[item]}")
        terms.append(_render(item))
    if len(terms) != len(set(terms)):
        raise UnsupportedStructure(f"unsupported-visible: duplicate alternate term at {paths[lists[0]]}")
    return terms


def _definition_nodes(entry: ET.Element, paths: Mapping[ET.Element, str]) -> list[ET.Element]:
    nodes = [child for child in list(entry) if _local(child.tag) in {"p", "ab"}]
    if not nodes:
        raise UnsupportedStructure(f"unsupported-visible: reference entry has no definition blocks at {paths[entry]}")
    for node in nodes:
        _inline_check(node, paths)
        if not _render(node):
            raise UnsupportedStructure(f"unsupported-visible: empty reference definition at {paths[node]}")
    return nodes


def _cross_references(definitions: Sequence[ET.Element], paths: Mapping[ET.Element, str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for definition in definitions:
        for node in definition.iter():
            if _local(node.tag) != "ref" or (node.get("type") or "") != "cross-reference":
                continue
            raw = _render(node)
            target = _norm(node.get("target") or node.get("cRef"))
            if not raw or not target or target.startswith("#"):
                raise UnsupportedStructure(f"unsupported-visible: invalid reference cross-reference at {paths[node]}")
            result.append({"raw": raw, "target_term": target})
    return result


def _locator(entry: ET.Element, headword: str, source_order: int, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> dict[str, Any]:
    part = next((node for node in [entry, *_ancestors(entry, parents)] if _local(node.tag) in _TEXT_PARTS), None)
    if part is None:
        raise UnsupportedStructure(f"unsupported-visible: reference entry has no text part at {paths[entry]}")
    divisions: list[dict[str, Any]] = []
    for division in reversed([node for node in _ancestors(entry, parents) if _local(node.tag) == "div" and node.get("type") not in _ENTRY_TYPES and node.get("type") not in _TEXT_PARTS]):
        parent = parents.get(division)
        siblings = [child for child in (list(parent) if parent is not None else []) if _local(child.tag) == "div" and child.get("type") not in _ENTRY_TYPES and child.get("type") not in _TEXT_PARTS]
        divisions.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "number": _norm(division.get("n")) or None, "titles": [_render(child) for child in list(division) if _local(child.tag) == "head" and _render(child)]})
    return {"kind": "reference-entry", "text_part": _local(part.tag), "part_titles": [_render(child) for child in list(part) if _local(child.tag) == "head" and _render(child)], "divisions": divisions, "headword": headword, "entry_order": source_order}


def _row(entry: ET.Element, identity: Mapping[str, str], sequence: int, source_order: int, context: Mapping[str, Any], parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str], *, easton: bool = False) -> dict[str, Any]:
    if easton:
        headword, definition_blocks = _easton_lexical(entry, source_order, paths, work_id=identity["work_id"])
        cross_references: list[dict[str, str]] = []
        alternate_terms = None
    else:
        headword = _headword(entry, paths)
        definitions = _definition_nodes(entry, paths)
        definition_blocks = [_render(node) for node in definitions]
        cross_references = _cross_references(definitions, paths)
        alternate_terms = _alternate_terms(entry, paths)
    locator = _locator(entry, headword, source_order, parents, paths)
    source_entry_id = _source_entry_id(source_order)
    return {
        **{key: identity[key] for key in _IDENTITY_KEYS},
        "record_id": f"{identity['edition_id']}:entry-{source_order:06d}",
        "sequence": sequence,
        "category": "reference_entries",
        "language": context["language"],
        "representation_revision": context["representation_revision"],
        "text": "\n\n".join(definition_blocks),
        "entry_id": f"{identity['edition_id']}:entry-{source_order:06d}",
        "source_entry_id": source_entry_id,
        "entry_kind": context["entry_kind"],
        "headword": headword,
        "alternate_terms": alternate_terms,
        "definition_blocks": definition_blocks,
        "cross_references": cross_references,
        "source_order": source_order,
        "locator": locator,
        "provenance": {"edition_title": context["edition_title"]},
    }


def _inventory(root: ET.Element, parts: Sequence[ET.Element], all_entries: Sequence[ET.Element], selected: Sequence[ET.Element], paths: Mapping[ET.Element, str], parents: Mapping[ET.Element, ET.Element], *, easton: bool = False, work_id: str = "eastons-bible-dictionary") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text_nodes = {node for part in parts for node in part.iter()}
    selected_nodes = {node for entry in selected for node in entry.iter()}
    outside_nodes = {node for entry in all_entries if entry not in selected for node in entry.iter()}
    excluded_paratext = {node for part in parts for node in part.iter() if any(ancestor.get("type") in _EXCLUDED_TYPES for ancestor in [node, *_ancestors(node, parents)])}
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        kind = _local(node.tag)
        if node not in text_nodes:
            disposition = "private-header"
        elif node in excluded_paratext:
            disposition = "excluded-paratext"
        elif node in selected_nodes:
            disposition = "row-content"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif kind == "head":
            disposition = "excluded-heading"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"unsupported-visible: unassigned reference element at {paths[node]}")
        inventory.append({"ordinal": ordinal, "tei_path": paths[node], "namespace": TEI_NS, "tag": kind, "disposition": disposition, "attributes": {_attr_name(key): value for key, value in sorted(node.attrib.items())}, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    for entry in all_entries:
        if entry not in selected:
            headword = _easton_lexical(entry, _source_order(entry, 0, paths), paths, work_id=work_id)[0] if easton else _headword(entry, paths)
            exclusions.append({"tei_path": paths[entry], "reason": "outside-scope", "xml_id": entry.get(XML_ID), "headword": headword})
    for node in sorted(excluded_paratext, key=lambda item: paths[item]):
        if node.get("type") in _EXCLUDED_TYPES:
            exclusions.append({"tei_path": paths[node], "reason": "excluded-paratext", "xml_id": node.get(XML_ID)})
    return inventory, exclusions


def _warnings(root: ET.Element, selected: Sequence[ET.Element], paths: Mapping[ET.Element, str]) -> list[dict[str, str]]:
    selected_nodes = {node for entry in selected for node in entry.iter()}
    reasons = {"ref": "source-reference-preserved", "note": "note-extracted", "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text", "seg": "segmentation-to-plain-text", "lb": "line-break-to-space", "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted"}
    return [{"tei_path": paths[node], "reason": reasons[_local(node.tag)]} for node in root.iter() if node in selected_nodes and _local(node.tag) in reasons]


def _source_accounting(context: Mapping[str, Any], binding: Mapping[str, str], selection: Mapping[str, Any]) -> dict[str, Any] | None:
    source_path = context.get("source_path")
    fields = ("source_selector", "source_scope", "source_unit_count", "source_selected_units", "source_census", "source_excerpt_sha256")
    if source_path is None and not any(context.get(field) is not None for field in fields):
        return None
    if source_path is None or any(context.get(field) is None for field in fields):
        raise PipelineError("reference source accounting requires source path, selector, scope, census, selection, and excerpt hash")
    try:
        native_count = int(context["source_unit_count"])
    except (TypeError, ValueError) as exc:
        raise PipelineError("reference source unit count must be an integer") from exc
    census = context["source_census"]
    selected_ids = [str(value) for value in context["source_selected_units"]]
    if not isinstance(census, Sequence) or isinstance(census, (str, bytes)):
        raise PipelineError("reference source census must be a sequence")
    census_copy = [dict(item) if isinstance(item, Mapping) else item for item in census]
    if native_count != len(census_copy):
        raise PipelineError("reference source census count mismatch")
    census_ids = [str(item.get("id")) for item in census_copy if isinstance(item, Mapping) and item.get("id") is not None]
    if len(census_ids) != native_count or len(set(census_ids)) != native_count:
        raise PipelineError("reference source census identities must be unique")
    census_id_set = set(census_ids)
    if any(value not in census_id_set for value in selected_ids) or len(set(selected_ids)) != len(selected_ids):
        raise PipelineError("reference source selection is not present in the census")
    native_selected_ids = [value for value in census_ids if value in set(selected_ids)]
    if selected_ids != native_selected_ids:
        raise PipelineError("reference source selection does not follow native census order")
    if selection["selected_units"] > len(selected_ids):
        raise PipelineError("reference source selection is smaller than the TEI selection")
    excerpt_hash = _valid_sha(str(context["source_excerpt_sha256"]), "source_excerpt_sha256")
    excluded_ids = [value for value in census_ids if value not in set(selected_ids)]
    return {
        "source_path": binding.get("source_path") or _logical_source_path(Path(source_path)),
        "selector": json.loads(json.dumps(context["source_selector"], ensure_ascii=False)),
        "scope": str(context["source_scope"]),
        "source_excerpt_sha256": excerpt_hash,
        "native_unit_count": native_count,
        "selected_unit_ids": selected_ids,
        "excluded_unit_ids": excluded_ids,
        "selected_unit_count": len(selected_ids),
        "excluded_unit_count": len(excluded_ids),
        "census": census_copy,
    }


def _validator() -> Any:
    try:
        import jsonschema
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        common = json.loads(COMMON.read_text(encoding="utf-8"))
        registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
        native_path = ROOT / "schemas/v2/native-content.schema.json"
        native_schema = json.loads(native_path.read_text(encoding="utf-8"))
        registry = registry.with_resource(native_schema["$id"], Resource.from_contents(native_schema, default_specification=DRAFT202012))
        validator = projection_validator(schema, registry=registry)
        validator.check_schema(schema)
        return validator
    except (ImportError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(f"invalid reference-entry schema package: {exc}") from exc


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"invalid reference public row {row.get('record_id', f'row-{index}')}: {errors[0].message}")


def project_reference_entries(tei_path: Path, *, identity: Mapping[str, str], language: str = "en", representation_revision: str = "tei-v2", edition_title: str = "", entry_kind: str = "dictionary-entry", source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, source_path: Path | None = None, source_logical_path: str | None = None, source_selector: Mapping[str, Any] | None = None, source_scope: str | None = None, source_unit_count: int | None = None, source_selected_units: Sequence[str] | None = None, source_census: Sequence[Mapping[str, Any]] | None = None, source_excerpt_sha256: str | None = None, scope_id: str | None = None) -> dict[str, Any]:
    identity_value = _identity(identity)
    if not isinstance(language, str) or not _LANG_RE.fullmatch(language):
        raise PipelineError("invalid reference-entry language")
    if not isinstance(representation_revision, str) or not representation_revision.strip():
        raise PipelineError("missing reference-entry representation revision")
    if not isinstance(edition_title, str) or not edition_title.strip():
        raise PipelineError("missing reference-entry edition title")
    if not isinstance(entry_kind, str) or not entry_kind.strip():
        raise PipelineError("missing reference-entry kind")
    context = {"identity": identity_value, "language": language, "representation_revision": representation_revision, "edition_title": edition_title, "entry_kind": entry_kind, "source_url": source_url, "source_sha256": source_sha256, "retained_sha256": retained_sha256, "source_path": source_path, "source_logical_path": source_logical_path, "source_selector": source_selector, "source_scope": source_scope, "source_unit_count": source_unit_count, "source_selected_units": source_selected_units, "source_census": source_census, "source_excerpt_sha256": source_excerpt_sha256}
    root, raw = _read_root(Path(tei_path))
    easton = _easton_profile(root, identity_value, source_selector)
    paths = _paths(root)
    parents = _parents(root)
    _validate_attributes(root, paths, easton=easton)
    binding = _source_binding(root, context, easton=easton)
    parts = _text_parts(root)
    scope = _scope(parts, scope_id, easton=easton)
    all_entries, selected = _entries(parts, scope, parents, easton=easton, work_id=identity_value["work_id"])
    if not selected:
        raise UnsupportedStructure("unsupported-visible: reference TEI contains no selected entry")
    global_order = {node: index for index, node in enumerate(all_entries, 1)}
    rows = [_row(entry, identity_value, sequence, _source_order(entry, global_order[entry], paths), context, parents, paths, easton=easton) for sequence, entry in enumerate(selected, 1)]
    if len({row["entry_id"] for row in rows}) != len(rows):
        raise UnsupportedStructure("unsupported-visible: duplicate reference entry identity")
    inventory, exclusions = _inventory(root, parts, all_entries, selected, paths, parents, easton=easton, work_id=identity_value["work_id"])
    warnings = _warnings(root, selected, paths)
    anchors = [{"record_id": row["record_id"], "tei_path": paths[entry], "xml_id": entry.get(XML_ID), "source_order": row["source_order"], "source_entry_id": row["source_entry_id"], "headword": row["headword"], "text_sha256": _sha_text(row["text"])} for row, entry in zip(rows, selected)]
    selection = {"available_units": len(all_entries), "selected_units": len(selected), "excluded_units": len(all_entries) - len(selected), "scope_id": scope_id}
    source_accounting = _source_accounting(context, binding, selection)
    if easton and (source_accounting is None or source_accounting["selected_unit_ids"] != [entry.get(XML_ID) for entry in selected]):
        raise PipelineError("Easton selected source census does not match native entry order")
    _validate_rows(rows)
    return {"rows": rows, "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "master_sha256": _sha_bytes(raw), "scope_id": scope_id, "mapping_version": MAPPING_VERSION, "source_binding": binding, "source_accounting": source_accounting, "schema_sha256": _sha_bytes(SCHEMA.read_bytes()), "common_schema_sha256": _sha_bytes(COMMON.read_bytes()), "selection": selection}


project_reference_entry = project_reference_entries
project_entry = project_reference_entries
project_document = project_reference_entries


def build_reference_entries_receipt(projection: Mapping[str, Any], *, identity: Mapping[str, str]) -> dict[str, Any]:
    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise PipelineError("reference projection rows must be a list")
    return {"schema_version": "ocd-reference-entries-receipt-v2", "receipt_version": RECEIPT_VERSION, "mapping_version": projection.get("mapping_version", MAPPING_VERSION), "assembler_version": ASSEMBLER_VERSION, "category": "reference_entries", "identity": dict(identity), "master_sha256": projection.get("master_sha256"), "schema_sha256": projection.get("schema_sha256", _sha_bytes(SCHEMA.read_bytes())), "common_schema_sha256": projection.get("common_schema_sha256", _sha_bytes(COMMON.read_bytes())), "scope_id": projection.get("scope_id"), "source_binding": dict(projection.get("source_binding", {})), "source_accounting": projection.get("source_accounting"), "selection": dict(projection.get("selection", {})), "output_sha256": _sha_bytes(_canonical(rows)), "row_count": len(rows), "anchors": list(projection.get("anchors", [])), "inventory": list(projection.get("inventory", [])), "warnings": list(projection.get("warnings", [])), "exclusions": list(projection.get("exclusions", [])), "unsupported": list(projection.get("unsupported", [])), "independent_check": {"status": "pending", "errors": []}}


def _checker_parse(path: Path) -> tuple[Any, bytes]:
    from lxml import etree
    try:
        raw = path.read_bytes()
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"checker: cannot parse reference-entry TEI: {exc}") from exc
    if root.getroottree().docinfo.doctype or root.xpath("//comment() | //processing-instruction()"):
        raise UnsupportedStructure("unsupported-visible: declarations, comments, or processing instructions")
    qname = etree.QName(root)
    if qname.namespace != TEI_NS or qname.localname != "TEI":
        raise UnsupportedStructure("unsupported-visible: checker requires TEI root")
    return root, raw


def _checker_paths(root: Any) -> dict[Any, str]:
    from lxml import etree
    paths: dict[Any, str] = {root: "/TEI[1]"}
    for parent in root.iter():
        counts: dict[str, int] = {}
        for child in parent:
            kind = etree.QName(child).localname
            counts[kind] = counts.get(kind, 0) + 1
            paths[child] = f"{paths[parent]}/{kind}[{counts[kind]}]"
    return paths


def _checker_text(node: Any) -> str:
    from lxml import etree
    chunks: list[str] = []

    def visit(current: Any) -> None:
        if current.text:
            chunks.append(current.text)
        for child in current:
            kind = etree.QName(child).localname
            if kind == "lb":
                chunks.append("" if child.get("break") == "no" else " ")
            elif kind in {"pb", "anchor", "ptr"}:
                chunks.append(" ")
            else:
                visit(child)
            if child.tail:
                chunks.append(child.tail)

    visit(node)
    return _norm("".join(chunks))


def _checker_inline_check(node: Any, paths: Mapping[Any, str]) -> None:
    """Validate visible descendants without consulting the ElementTree producer."""
    from lxml import etree

    for child in node:
        kind = etree.QName(child).localname
        if kind not in _INLINE:
            raise UnsupportedStructure(f"checker: reference inline {kind} at {paths[child]}")
        _checker_inline_check(child, paths)


def _checker_source_order(entry: Any, fallback: int, paths: Mapping[Any, str]) -> int:
    raw = _norm(entry.get("n"))
    if not raw:
        return fallback
    if not raw.isdigit() or int(raw) < 1:
        raise UnsupportedStructure(f"checker: reference source order must be a positive integer at {paths[entry]}")
    return int(raw)


def _checker_source_binding(root: Any, identity: Mapping[str, str], *, easton: bool = False) -> dict[str, str]:
    from lxml import etree
    source = root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces={"tei": TEI_NS})
    if len(source) != 1:
        raise UnsupportedStructure("checker: exactly one sourceDesc is required")
    binding_node = source[0]
    if easton:
        scoped = source[0].xpath("./tei:bibl[@type='ocd-acceptance-binding']", namespaces={"tei": TEI_NS})
        if len(scoped) != 1:
            raise UnsupportedStructure("checker: one scoped Easton acceptance binding is required")
        binding_node = scoped[0]
    ids: dict[str, str] = {}
    hashes: dict[str, str] = {}
    source_url = ""
    source_path_label = ""
    for node in binding_node.iter():
        kind = etree.QName(node).localname
        if kind == "idno":
            value = _norm("".join(node.itertext()))
            typ = (node.get("type") or "").lower().replace("-", "_")
            if typ in _IDENTITY_KEYS:
                ids[typ] = value
            elif typ in {"source_sha256", "origin_sha256"}:
                hashes["source_sha256"] = _valid_sha(value, "source_sha256")
            elif typ in {"retained_sha256", "archive_sha256", "sha256"}:
                hashes["retained_sha256"] = _valid_sha(value, "retained_sha256")
        elif kind in {"ptr", "ref"} and not source_url and node.get("target"):
            source_url = _norm(node.get("target"))
        elif kind == "note" and (node.get("type") or "").lower().replace("-", "_") in {"source_path", "source_location"}:
            source_path_label = _norm("".join(node.itertext()))
    if any(ids.get(key) != identity[key] for key in _IDENTITY_KEYS) or not source_url or set(hashes) != {"source_sha256", "retained_sha256"}:
        raise UnsupportedStructure("checker: incomplete reference-entry source binding")
    binding = {"source_url": source_url, **hashes}
    if source_path_label:
        binding["source_path"] = source_path_label
    return binding


def _checker_easton_entries(root: Any, identity: Mapping[str, str], language: str, revision: str, title: str, entry_kind: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    """Recompute native lexical rows directly with lxml, separate from the producer."""
    from lxml import etree

    work_id = identity["work_id"]
    ns = {"t": TEI_NS}
    texts = root.xpath("./t:text", namespaces=ns)
    if len(texts) != 1 or texts[0].get(XML_ID) != f"{work_id}-text" or texts[0].get("type") != "dictionary":
        raise UnsupportedStructure("checker: Easton text identity/shape mismatch")
    if len(texts[0]) != 1 or etree.QName(texts[0][0]).localname != "body":
        raise UnsupportedStructure("checker: Easton text requires one body")
    body = texts[0][0]
    if body.get(XML_ID) != f"{work_id}-body" or (body.text or "").strip():
        raise UnsupportedStructure("checker: Easton body identity/content mismatch")
    entries = list(body)
    if not entries or any(etree.QName(node).localname != "entry" for node in entries):
        raise UnsupportedStructure("checker: Easton body requires native entries only")
    paths = _checker_paths(root)
    selected = []
    for ordinal, entry in enumerate(entries, 1):
        prefix = f"{work_id}-entry-{ordinal:05d}"
        if entry.get("n") != str(ordinal) or entry.get(XML_ID) != prefix or (entry.text or "").strip() or (entry.tail or "").strip():
            raise UnsupportedStructure(f"checker: Easton entry identity/content at {paths[entry]}")
        if scope_id is None or scope_id == prefix:
            selected.append((ordinal, entry))
    if not selected:
        raise UnsupportedStructure("checker: Easton selection has no entry")
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for ordinal, entry in enumerate(entries, 1):
        prefix = f"{work_id}-entry-{ordinal:05d}"
        if [etree.QName(node).localname for node in entry] != ["form", "sense"]:
            raise UnsupportedStructure(f"checker: Easton entry shape at {paths[entry]}")
        form, sense = entry
        if (len(form) != 1 or etree.QName(form[0]).localname != "orth"
                or (form.text or "").strip() or (form.tail or "").strip()
                or sense.get(XML_ID) != prefix + "-sense"
                or (sense.text or "").strip() or (sense.tail or "").strip()):
            raise UnsupportedStructure(f"checker: Easton form/sense at {paths[entry]}")
        orth = form[0]
        if orth.get("type") != "headword" or orth.text is None or not orth.text or len(orth) or (orth.tail or "").strip():
            raise UnsupportedStructure(f"checker: Easton orth at {paths[orth]}")
        definitions = list(sense)
        if not definitions:
            raise UnsupportedStructure(f"checker: Easton definition missing at {paths[entry]}")
        blocks: list[str] = []
        for number, definition in enumerate(definitions, 1):
            if (etree.QName(definition).localname != "def" or definition.get("n") != str(number)
                    or definition.get(XML_ID) != f"{prefix}-definition-{number:03d}"
                    or definition.text is None or not definition.text or len(definition)
                    or (definition.tail or "").strip()):
                raise UnsupportedStructure(f"checker: Easton definition at {paths[definition]}")
            blocks.append(definition.text)
        headword = orth.text
        if scope_id is not None and scope_id != prefix:
            continue
        sequence = len(rows) + 1
        source_entry_id = _source_entry_id(ordinal)
        locator = {"kind": "reference-entry", "text_part": "body", "part_titles": [], "divisions": [], "headword": headword, "entry_order": ordinal}
        row = {**{key: identity[key] for key in _IDENTITY_KEYS}, "record_id": f"{identity['edition_id']}:entry-{ordinal:06d}", "sequence": sequence, "category": "reference_entries", "language": language, "representation_revision": revision, "text": "\n\n".join(blocks), "entry_id": f"{identity['edition_id']}:entry-{ordinal:06d}", "source_entry_id": source_entry_id, "entry_kind": entry_kind, "headword": headword, "alternate_terms": None, "definition_blocks": blocks, "cross_references": [], "source_order": ordinal, "locator": locator, "provenance": {"edition_title": title}}
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "tei_path": paths[entry], "xml_id": entry.get(XML_ID), "source_order": ordinal, "source_entry_id": source_entry_id, "headword": headword, "text_sha256": _sha_text(row["text"])})
    selected_nodes = {node for _, entry in selected for node in entry.iter()}
    outside_nodes = {node for entry in entries if entry not in [item for _, item in selected] for node in entry.iter()}
    text_nodes = set(body.iter())
    inventory: list[dict[str, Any]] = []
    for number, node in enumerate(root.iter(), 1):
        kind = etree.QName(node).localname
        if node not in text_nodes:
            disposition = "private-header"
        elif node in selected_nodes:
            disposition = "row-content"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"checker: unassigned Easton element at {paths[node]}")
        attrs = {_attr_name(key): value for key, value in sorted(node.attrib.items())}
        inventory.append({"ordinal": number, "tei_path": paths[node], "namespace": etree.QName(node).namespace or "", "tag": kind, "disposition": disposition, "attributes": attrs, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    exclusions = [{"tei_path": paths[entry], "reason": "outside-scope", "xml_id": entry.get(XML_ID), "headword": entry[0][0].text} for entry in entries if entry not in [item for _, item in selected]]
    return rows, anchors, inventory, exclusions, [], {"available_units": len(entries), "selected_units": len(selected), "excluded_units": len(entries) - len(selected), "scope_id": scope_id}


def _checker_entries(root: Any, identity: Mapping[str, str], language: str, revision: str, title: str, entry_kind: str, scope_id: str | None, *, easton: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    if easton:
        return _checker_easton_entries(root, identity, language, revision, title, entry_kind, scope_id)
    from lxml import etree
    ns = {"t": TEI_NS}
    text = root.xpath("./t:text", namespaces=ns)
    if len(text) != 1:
        raise UnsupportedStructure("checker: one text is required")
    parts = [node for node in text[0] if etree.QName(node).localname in _TEXT_PARTS]
    all_entries = [node for part in parts for node in part.xpath(".//t:div", namespaces=ns) if node.get("type") in _ENTRY_TYPES and not any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *list(node.iterancestors())])]
    scope = None
    if scope_id is not None:
        found = root.xpath(".//*[@xml:id=$value]", namespaces={"xml": XML_NS}, value=scope_id)
        if len(found) != 1 or found[0].get("type") not in _ENTRY_TYPES:
            raise UnsupportedStructure("checker: scope is not one reference entry")
        scope = found[0]
    selected = [node for node in all_entries if scope is None or node is scope or scope in list(node.iterancestors())]
    if not selected:
        raise UnsupportedStructure("checker: no selected reference entry")
    paths = _checker_paths(root)
    global_order = {id(node): index for index, node in enumerate(all_entries, 1)}
    source_orders: dict[int, Any] = {}
    seen_source_orders: dict[int, Any] = {}
    seen_xml_ids: dict[str, Any] = {}
    for entry in all_entries:
        source_order = _checker_source_order(entry, global_order[id(entry)], paths)
        if source_order in seen_source_orders:
            raise UnsupportedStructure(f"checker: duplicate reference source order at {paths[entry]}")
        seen_source_orders[source_order] = entry
        source_orders[id(entry)] = source_order
        xml_id = entry.get(XML_ID)
        if xml_id:
            if xml_id in seen_xml_ids:
                raise UnsupportedStructure(f"checker: duplicate reference xml:id at {paths[entry]}")
            seen_xml_ids[xml_id] = entry
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for sequence, entry in enumerate(selected, 1):
        heads = [child for child in entry if etree.QName(child).localname == "head" and (child.get("type") or "headword") == "headword"]
        if len(heads) != 1 or not _checker_text(heads[0]):
            raise UnsupportedStructure(f"checker: one non-empty headword is required at {paths[entry]}")
        _checker_inline_check(heads[0], paths)
        headword = _checker_text(heads[0])
        definitions = [child for child in entry if etree.QName(child).localname in {"p", "ab"}]
        if not definitions or any(not _checker_text(node) for node in definitions):
            raise UnsupportedStructure(f"checker: reference definition blocks are missing at {paths[entry]}")
        for definition in definitions:
            _checker_inline_check(definition, paths)
        definition_blocks = [_checker_text(node) for node in definitions]
        cross_refs: list[dict[str, str]] = []
        for definition in definitions:
            for node in definition.xpath(".//t:ref", namespaces=ns):
                if (node.get("type") or "") != "cross-reference":
                    continue
                raw = _checker_text(node)
                target = _norm(node.get("target") or node.get("cRef"))
                if not raw or not target or target.startswith("#"):
                    raise UnsupportedStructure(f"checker: invalid cross-reference at {paths[node]}")
                cross_refs.append({"raw": raw, "target_term": target})
        alternate_lists = [child for child in entry if etree.QName(child).localname == "list" and child.get("type") == "alternate-terms"]
        if len(alternate_lists) > 1:
            raise UnsupportedStructure(f"checker: multiple alternate-term lists at {paths[entry]}")
        alternate_terms: list[str] | None = None
        if alternate_lists:
            terms: list[str] = []
            for item in alternate_lists[0]:
                if etree.QName(item).localname != "item" or not _checker_text(item):
                    raise UnsupportedStructure(f"checker: alternate term item is empty at {paths[item]}")
                _checker_inline_check(item, paths)
                terms.append(_checker_text(item))
            if len(terms) != len(set(terms)):
                raise UnsupportedStructure(f"checker: duplicate alternate term at {paths[alternate_lists[0]]}")
            alternate_terms = terms
        part = next((node for node in [entry, *list(entry.iterancestors())] if etree.QName(node).localname in _TEXT_PARTS), None)
        if part is None:
            raise UnsupportedStructure(f"checker: reference entry has no text part at {paths[entry]}")
        divisions: list[dict[str, Any]] = []
        ancestors = [node for node in reversed(list(entry.iterancestors())) if etree.QName(node).localname == "div" and node.get("type") not in _ENTRY_TYPES and node.get("type") not in _TEXT_PARTS]
        for division in ancestors:
            parent = division.getparent()
            siblings = [child for child in parent if etree.QName(child).localname == "div" and child.get("type") not in _ENTRY_TYPES and child.get("type") not in _TEXT_PARTS]
            divisions.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "number": _norm(division.get("n")) or None, "titles": [_checker_text(child) for child in division if etree.QName(child).localname == "head" and _checker_text(child)]})
        source_order = source_orders[id(entry)]
        locator = {"kind": "reference-entry", "text_part": etree.QName(part).localname, "part_titles": [_checker_text(child) for child in part if etree.QName(child).localname == "head" and _checker_text(child)], "divisions": divisions, "headword": headword, "entry_order": source_order}
        source_entry_id = _source_entry_id(source_order)
        row = {**{key: identity[key] for key in _IDENTITY_KEYS}, "record_id": f"{identity['edition_id']}:entry-{source_order:06d}", "sequence": sequence, "category": "reference_entries", "language": language, "representation_revision": revision, "text": "\n\n".join(definition_blocks), "entry_id": f"{identity['edition_id']}:entry-{source_order:06d}", "source_entry_id": source_entry_id, "entry_kind": entry_kind, "headword": headword, "alternate_terms": alternate_terms, "definition_blocks": definition_blocks, "cross_references": cross_refs, "source_order": source_order, "locator": locator, "provenance": {"edition_title": title}}
        rows.append(row)
        anchors.append({"record_id": row["record_id"], "tei_path": paths[entry], "xml_id": entry.get(f"{{{XML_NS}}}id"), "source_order": source_order, "source_entry_id": source_entry_id, "headword": headword, "text_sha256": _sha_text(row["text"])})
    selected_nodes = {node for entry in selected for node in entry.iter()}
    outside_nodes = {node for entry in all_entries if entry not in selected for node in entry.iter()}
    text_nodes = {node for part in parts for node in part.iter()}
    excluded_paratext = {node for part in parts for node in part.iter() if any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *list(node.iterancestors())])}
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        kind = etree.QName(node).localname
        if node not in text_nodes:
            disposition = "private-header"
        elif node in excluded_paratext:
            disposition = "excluded-paratext"
        elif node in selected_nodes:
            disposition = "row-content"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif kind == "head":
            disposition = "excluded-heading"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"checker: unassigned reference element at {paths[node]}")
        attrs = {"xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else (key.rsplit("}", 1)[-1] if key.startswith("{") else key): value for key, value in sorted(node.attrib.items())}
        inventory.append({"ordinal": ordinal, "tei_path": paths[node], "namespace": etree.QName(node).namespace or "", "tag": kind, "disposition": disposition, "attributes": attrs, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    for entry in all_entries:
        if entry not in selected:
            heads = [child for child in entry if etree.QName(child).localname == "head" and (child.get("type") or "headword") == "headword"]
            exclusions.append({"tei_path": paths[entry], "reason": "outside-scope", "xml_id": entry.get(XML_ID), "headword": _checker_text(heads[0]) if len(heads) == 1 else None})
    for node in sorted(excluded_paratext, key=lambda item: paths[item]):
        if node.get("type") in _EXCLUDED_TYPES:
            exclusions.append({"tei_path": paths[node], "reason": "excluded-paratext", "xml_id": node.get(XML_ID)})
    reasons = {"ref": "source-reference-preserved", "note": "note-extracted", "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text", "seg": "segmentation-to-plain-text", "lb": "line-break-to-space", "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted"}
    warnings = [{"tei_path": paths[node], "reason": reasons[etree.QName(node).localname]} for node in root.iter() if node in selected_nodes and etree.QName(node).localname in reasons]
    return rows, anchors, inventory, exclusions, warnings, {"available_units": len(all_entries), "selected_units": len(selected), "excluded_units": len(all_entries) - len(selected), "scope_id": scope_id}


def verify_reference_entries(tei_path: Path, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None = None, *, identity: Mapping[str, str], language: str = "en", representation_revision: str = "tei-v2", edition_title: str = "", entry_kind: str = "dictionary-entry", source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, source_path: Path | None = None, source_logical_path: str | None = None, source_selector: Mapping[str, Any] | None = None, source_scope: str | None = None, source_unit_count: int | None = None, source_selected_units: Sequence[str] | None = None, source_census: Sequence[Mapping[str, Any]] | None = None, source_excerpt_sha256: str | None = None, scope_id: str | None = None) -> list[str]:
    if isinstance(rows, Mapping):
        if "rows" not in rows:
            return ["checker requires a projection object with rows"]
        if receipt is None and isinstance(rows.get("receipt"), Mapping):
            receipt = rows["receipt"]
        provided = rows["rows"]
    else:
        provided = rows
    try:
        identity_value = _identity(identity)
        if not _LANG_RE.fullmatch(language) or not representation_revision.strip() or not edition_title.strip() or not entry_kind.strip():
            raise PipelineError("checker: invalid reference-entry context")
        root, raw = _checker_parse(Path(tei_path))
        easton = _easton_profile(root, identity_value, source_selector)
        paths = _checker_paths(root)
        from lxml import etree
        for node in root.iter():
            qname = etree.QName(node)
            if qname.namespace != TEI_NS or (qname.localname not in _HEADER and qname.localname not in _STRUCTURE and not (easton and qname.localname in _EASTON_HEADER | _EASTON_LEXICAL)):
                raise UnsupportedStructure(f"unsupported-visible: element at {paths[node]}")
            for key in node.attrib:
                allowed = _EASTON_ATTRIBUTES.get(qname.localname, _ATTRIBUTES.get(qname.localname, {XML_ID, XML_LANG})) if easton else _ATTRIBUTES.get(qname.localname, {XML_ID, XML_LANG})
                if key not in allowed:
                    raise UnsupportedStructure(f"unsupported-visible: attribute at {paths[node]}")
        binding = _checker_source_binding(root, identity_value, easton=easton)
        if source_url is not None and binding["source_url"] != source_url:
            raise PipelineError("checker: source URL mismatch")
        if source_sha256 is not None and binding["source_sha256"] != _valid_sha(source_sha256, "source_sha256"):
            raise PipelineError("checker: source_sha256 mismatch")
        if retained_sha256 is not None and binding["retained_sha256"] != _valid_sha(retained_sha256, "retained_sha256"):
            raise PipelineError("checker: retained_sha256 mismatch")
        if source_path is not None:
            expected_path = source_logical_path or _logical_source_path(Path(source_path))
            if binding.get("source_path") != expected_path:
                raise PipelineError("checker: source path mismatch")
            if _sha_bytes(Path(source_path).read_bytes()) != binding["retained_sha256"]:
                raise PipelineError("checker: retained source hash mismatch")
        expected_rows, anchors, inventory, exclusions, warnings, selection = _checker_entries(root, identity_value, language, representation_revision, edition_title, entry_kind, scope_id, easton=easton)
        context = {"source_path": source_path, "source_selector": source_selector, "source_scope": source_scope, "source_unit_count": source_unit_count, "source_selected_units": source_selected_units, "source_census": source_census, "source_excerpt_sha256": source_excerpt_sha256}
        source_accounting = _source_accounting(context, binding, selection)
        if easton and (source_accounting is None or source_accounting["selected_unit_ids"] != [anchor["xml_id"] for anchor in anchors]):
            raise PipelineError("checker: Easton selected source census does not match native entry order")
        _validate_rows(expected_rows)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if not isinstance(provided, Sequence) or isinstance(provided, (str, bytes)):
        errors.append("reference rows must be a sequence")
    elif list(provided) != expected_rows:
        errors.append("reference rows do not match independent TEI traversal")
    if receipt is None:
        errors.append("reference receipt is missing")
        return errors
    if not isinstance(receipt, Mapping):
        return errors + ["reference receipt must be an object"]
    expected_receipt = {"schema_version": "ocd-reference-entries-receipt-v2", "receipt_version": RECEIPT_VERSION, "mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "category": "reference_entries", "identity": identity_value, "master_sha256": _sha_bytes(raw), "schema_sha256": _sha_bytes(SCHEMA.read_bytes()), "common_schema_sha256": _sha_bytes(COMMON.read_bytes()), "scope_id": scope_id, "source_binding": binding, "source_accounting": source_accounting, "selection": selection, "output_sha256": _sha_bytes(_canonical(expected_rows)), "row_count": len(expected_rows), "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending", "errors": []}}
    if set(receipt) != set(expected_receipt):
        errors.append("reference receipt fields differ")
    for key, wanted in expected_receipt.items():
        if receipt.get(key) != wanted:
            errors.append(f"reference receipt {key} mismatch")
    if isinstance(provided, Sequence) and not isinstance(provided, (str, bytes)):
        try:
            _validate_rows(provided)  # type: ignore[arg-type]
        except PipelineError as exc:
            errors.append(str(exc))
    return errors


check_reference_entries = verify_reference_entries
verify_document = verify_reference_entries


def _accepted_kind(document: Mapping[str, Any], field: str, allowed: set[str]) -> str:
    nested = document.get("projection_context")
    source = nested if isinstance(nested, Mapping) else document
    value = source.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise PipelineError(f"source.accounting {field} is missing or invalid")
    return value


def _accepted_metadata(root: Path, acceptance_path: Path) -> dict[str, Any]:
    """Validate promoted authority and derive the complete reference context."""

    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.tei.acceptance import validate_acceptance
    from ocd_kernel.projection.categories.catechisms import (
        _accepted_bound_file,
        _accepted_local_binding,
        _accepted_projection_context,
    )

    base = Path(root).resolve()
    accepted_path = Path(acceptance_path).resolve()
    accepted = validate_acceptance(accepted_path, root=base)
    if accepted["promotion"]["status"] != "promoted":
        raise PipelineError("reference projection requires a promoted accepted master")
    accepted_identity = accepted.get("identity")
    if not isinstance(accepted_identity, Mapping):
        raise PipelineError("accepted identity is missing")
    identity = {key: accepted_identity[key] for key in (*_IDENTITY_KEYS, "acquisition_id")}
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    if work.work_id != identity["work_id"] or edition.textual_form_id != identity["textual_form_id"]:
        raise PipelineError("accepted identity does not identify the canonical reference edition")
    forms = [
        item
        for item in work.record.get("textual_forms", [])
        if isinstance(item, Mapping)
        and item.get("textual_form_id") == edition.textual_form_id
    ]
    if len(forms) != 1:
        raise PipelineError("accepted identity has no unique canonical textual form")
    form = forms[0]
    category = edition.record.get("category", form.get("category"))
    if category != "reference-entries":
        raise PipelineError("accepted edition category mismatch")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not _LANG_RE.fullmatch(language):
        raise PipelineError("accepted reference edition has no valid language")
    revision = accepted.get("representation_revision")
    if not isinstance(revision, Mapping) or not isinstance(revision.get("id"), str) or not revision["id"].strip():
        raise PipelineError("accepted representation revision is missing")
    acquisition_path, acquisition = acquisition_for_edition(
        base,
        identity["work_id"],
        identity["edition_id"],
        acquisition_id=identity["acquisition_id"],
    )
    source = accepted.get("source")
    scope = accepted.get("scope")
    if not isinstance(source, Mapping) or not isinstance(scope, Mapping):
        raise PipelineError("accepted source or scope is missing")
    included = scope.get("included_members")
    if not isinstance(included, list) or len(included) != 1 or not isinstance(included[0], Mapping):
        raise PipelineError("reference projection requires exactly one accepted retained member")
    retained_path, retained_authority = _accepted_bound_file(
        base, included[0], field="scope.included_members[0]"
    )
    accounting_path, accounting_authority = _accepted_bound_file(
        base, source.get("accounting"), field="source.accounting"
    )
    try:
        accounting_document = json.loads(accounting_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"source.accounting is not readable JSON: {accounting_path}") from exc
    if not isinstance(accounting_document, Mapping):
        raise PipelineError("source.accounting must contain an object")
    projection_context = _accepted_projection_context(accounting_document)
    if projection_context["available"] and projection_context["source_scope"] != scope.get("declared"):
        raise PipelineError("source.accounting projection scope does not bind accepted scope")
    entry_kind = _accepted_kind(accounting_document, "entry_kind", _ENTRY_TYPES)
    source_url = acquisition.get("url")
    source_sha256 = source.get("source_sha256")
    source_logical_path = source.get("source_path")
    if not isinstance(source_url, str) or not source_url.strip():
        raise PipelineError("accepted acquisition has no source URL")
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise PipelineError("accepted source has no source SHA-256")
    if not isinstance(source_logical_path, str) or not source_logical_path.strip():
        raise PipelineError("accepted source has no source path")
    authority = {
        "acceptance": _accepted_local_binding(base, accepted_path, field="acceptance"),
        "work": _accepted_local_binding(base, work.path, field="work"),
        "master": _accepted_local_binding(base, edition.path, field="master"),
        "acquisition": _accepted_local_binding(base, acquisition_path, field="acquisition"),
        "source_accounting": accounting_authority,
        "retained_source": retained_authority,
    }
    return {
        "root": base,
        "acceptance": accepted,
        "acceptance_path": accepted_path,
        "identity": {key: identity[key] for key in _IDENTITY_KEYS},
        "edition": edition,
        "master_path": Path(edition.path).resolve(),
        "language": language,
        "representation_revision": revision["id"],
        "entry_kind": entry_kind,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "retained_sha256": included[0]["sha256"],
        "source_logical_path": source_logical_path,
        "retained_path": retained_path if projection_context["available"] else None,
        "source_context": projection_context,
        "authority": authority,
    }


def _native_catholic_acceptance(acceptance_path: Path) -> bool:
    from ocd_kernel.tei.acceptance import load_acceptance
    document = load_acceptance(Path(acceptance_path).resolve())
    identity = document.get("identity")
    return isinstance(identity, Mapping) and dict(identity) == {'work_id': 'catholic-encyclopedia-vol01', 'textual_form_id': 'catholic-encyclopedia-vol01-retained-en', 'edition_id': 'catholic-encyclopedia-vol01-retained-electronic', 'acquisition_id': 'catholic-encyclopedia-vol01-acquired-member-set'}


def iter_accepted_native_reference_entries(root: Path, *, acceptance_path: Path):
    """Exact-work streamed units; all other identities fail closed."""
    if not _native_catholic_acceptance(acceptance_path):
        raise PipelineError("streamed native reference units require the reviewed Catholic work")
    from .lib025_native_reference_accepted import iter_accepted
    yield from iter_accepted(root, acceptance_path=acceptance_path)


def project_accepted_reference_entries(
    root: Path, *, acceptance_path: Path
) -> dict[str, Any]:
    """Project promoted reference entries from validated acceptance authority."""

    if _native_catholic_acceptance(acceptance_path):
        from .lib025_native_reference_accepted import project_accepted
        return project_accepted(root, acceptance_path=acceptance_path)
    metadata = _accepted_metadata(root, acceptance_path)
    context = metadata["source_context"]
    kwargs: dict[str, Any] = {
        "identity": metadata["identity"],
        "language": metadata["language"],
        "representation_revision": metadata["representation_revision"],
        "edition_title": metadata["edition"].title,
        "entry_kind": metadata["entry_kind"],
        "source_url": metadata["source_url"],
        "source_sha256": metadata["source_sha256"],
        "retained_sha256": metadata["retained_sha256"],
    }
    if context["available"]:
        kwargs.update(
            source_path=metadata["retained_path"],
            source_logical_path=metadata["source_logical_path"],
            source_selector=context["source_selector"],
            source_scope=context["source_scope"],
            source_unit_count=context["source_unit_count"],
            source_selected_units=context["source_selected_units"],
            source_census=context["source_census"],
            source_excerpt_sha256=context["source_excerpt_sha256"],
        )
    projection = project_reference_entries(metadata["master_path"], **kwargs)
    receipt = build_reference_entries_receipt(projection, identity=metadata["identity"])
    receipt["authority"] = dict(metadata["authority"])
    receipt["scope"] = "tei-document; context derived from validated acceptance"
    projection["receipt"] = receipt
    projection["authority"] = dict(metadata["authority"])
    return projection


def verify_accepted_reference_entries(
    root: Path,
    *,
    acceptance_path: Path,
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted reference rows without invoking the producer."""

    try:
        if _native_catholic_acceptance(acceptance_path):
            from .lib025_native_reference_accepted import verify_accepted
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt_document=receipt)
        metadata = _accepted_metadata(root, acceptance_path)
        if receipt is None:
            return ["accepted reference receipt is missing"]
        if not isinstance(receipt, Mapping):
            return ["accepted reference receipt must be an object"]
        errors: list[str] = []
        if receipt.get("authority") != metadata["authority"]:
            errors.append("accepted authority bindings differ")
        if receipt.get("scope") != "tei-document; context derived from validated acceptance":
            errors.append("accepted scope label differs")
        context = metadata["source_context"]
        kwargs: dict[str, Any] = {
            "identity": metadata["identity"],
            "language": metadata["language"],
            "representation_revision": metadata["representation_revision"],
            "edition_title": metadata["edition"].title,
            "entry_kind": metadata["entry_kind"],
            "source_url": metadata["source_url"],
            "source_sha256": metadata["source_sha256"],
            "retained_sha256": metadata["retained_sha256"],
        }
        if context["available"]:
            kwargs.update(
                source_path=metadata["retained_path"],
                source_logical_path=metadata["source_logical_path"],
                source_selector=context["source_selector"],
                source_scope=context["source_scope"],
                source_unit_count=context["source_unit_count"],
                source_selected_units=context["source_selected_units"],
                source_census=context["source_census"],
                source_excerpt_sha256=context["source_excerpt_sha256"],
            )
        document_receipt = dict(receipt)
        document_receipt.pop("authority", None)
        document_receipt.pop("scope", None)
        errors.extend(
            verify_reference_entries(
                metadata["master_path"], rows, document_receipt, **kwargs
            )
        )
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]

__all__ = ["project_reference_entries", "project_reference_entry", "project_entry", "project_document", "build_reference_entries_receipt", "verify_reference_entries", "check_reference_entries", "verify_document", "project_accepted_reference_entries", "verify_accepted_reference_entries", "MAPPING_VERSION", "RECEIPT_VERSION", "ASSEMBLER_VERSION", "UnsupportedStructure"]
