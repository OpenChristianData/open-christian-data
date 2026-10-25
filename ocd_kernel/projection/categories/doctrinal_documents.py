"""Source-bound doctrinal-document projection (PIPE-013B).

The mapping keeps normative units, nesting, proofs, revisions, numbering, and
locators explicit.  The checker reconstructs the expected result with lxml
independently of the producer and validates every receipt field.
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
from ocd_kernel.projection import native_content, native_content_check


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"
ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "schemas/v2/categories/doctrinal-documents.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
MAPPING_VERSION = "ocd-doctrinal-documents-mapping-v5"
RECEIPT_VERSION = "ocd-doctrinal-documents-receipt-v2"
ASSEMBLER_VERSION = "ocd-doctrinal-documents-assembler-v2"
_IDENTITY_KEYS = ("work_id", "textual_form_id", "edition_id")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_NORMATIVE_TYPES = {"chapter", "section", "article", "clause", "canon", "rejection", "text", "proposition", "unit"}
_DOCUMENT_KINDS = {"canon", "confession", "covenant", "creed", "declaration", "directory", "statement", "constitution"}
_EXCLUDED_TYPES = {"title-page", "half-title-page", "copyright-page", "imprint", "colophon"}
_TEXT_PARTS = {"front", "body", "back"}
_INLINE = {"ref", "ptr", "hi", "foreign", "seg", "lb", "pb", "anchor", "note"}
_CONTENT_TYPES = {None, "normative", "content"}
_PROOF_CONTENT_TYPE = "content-with-proofs"
_STRUCTURE = {"text", "front", "body", "back", "div", "head", "p", "ab", "list", "item", *_INLINE}
_HEADER = {"seg", "TEI", "teiHeader", "fileDesc", "titleStmt", "title", "publicationStmt", "sourceDesc", "bibl", "idno", "ptr", "revisionDesc", "change", "list", "item", "p", "ab", "date", "editionStmt", "edition", "respStmt", "resp", "name", "author", "availability", "licence", "distributor", "encodingDesc", "projectDesc", "desc", "ref", "note", "publisher", "pubPlace", "biblScope", "facsimile", "surface", "graphic"}
_ATTRIBUTES = {
    "TEI": {XML_ID, XML_LANG}, "teiHeader": {XML_ID, XML_LANG}, "fileDesc": {XML_ID, XML_LANG}, "titleStmt": {XML_ID, XML_LANG},
    "title": {XML_ID, XML_LANG, "type"}, "publicationStmt": {XML_ID, XML_LANG}, "sourceDesc": {XML_ID, XML_LANG},
    "bibl": {XML_ID, XML_LANG, "type"}, "idno": {XML_ID, XML_LANG, "type"}, "ptr": {XML_ID, XML_LANG, "type", "target"},
    "revisionDesc": {XML_ID, XML_LANG}, "change": {XML_ID, XML_LANG, "when", "type"}, "editionStmt": {XML_ID, XML_LANG},
    "edition": {XML_ID, XML_LANG, "n", "type"}, "respStmt": {XML_ID, XML_LANG}, "resp": {XML_ID, XML_LANG, "type"},
    "author": {XML_ID, XML_LANG, "role"}, "name": {XML_ID, XML_LANG}, "availability": {XML_ID, XML_LANG}, "licence": {XML_ID, XML_LANG, "target"},
    "distributor": {XML_ID, XML_LANG}, "encodingDesc": {XML_ID, XML_LANG}, "projectDesc": {XML_ID, XML_LANG},
    "desc": {XML_ID, XML_LANG, "type"}, "date": {XML_ID, XML_LANG, "when"}, "publisher": {XML_ID, XML_LANG},
    "pubPlace": {XML_ID, XML_LANG}, "biblScope": {XML_ID, XML_LANG, "unit", "from", "to"},
    "facsimile": {XML_ID, XML_LANG}, "surface": {XML_ID, XML_LANG, "n"}, "graphic": {XML_ID, XML_LANG, "url"},
    "text": {XML_ID, XML_LANG},
    "front": {XML_ID, XML_LANG}, "body": {XML_ID, XML_LANG}, "back": {XML_ID, XML_LANG}, "div": {XML_ID, XML_LANG, "type", "n"},
    "head": {XML_ID, XML_LANG, "type"}, "p": {XML_ID, XML_LANG, "type", "rend"}, "ab": {XML_ID, XML_LANG, "type"},
    "list": {XML_ID, XML_LANG, "type"}, "item": {XML_ID, XML_LANG, "n", "type"}, "ref": {XML_ID, XML_LANG, "type", "target", "cRef"},
    "note": {XML_ID, XML_LANG, "place", "n", "type"}, "hi": {XML_ID, XML_LANG, "rend", "type"}, "foreign": {XML_ID, XML_LANG, "lang", "type"},
    "seg": {XML_ID, XML_LANG, "type"}, "lb": {XML_ID, XML_LANG, "break", "n"}, "pb": {XML_ID, XML_LANG, "n", "facs", "break"}, "anchor": {XML_ID, XML_LANG, "type", "n"},
}


class UnsupportedStructure(PipelineError):
    """A visible doctrinal source feature is outside the closed mapping."""


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
    """Return the repository logical path, preserving the raw junction label."""
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
        raise PipelineError(f"cannot read doctrinal TEI {path}: {exc}") from exc
    if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
        raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=_RejectingBuilder()))
    except UnsupportedStructure:
        raise
    except ET.ParseError as exc:
        raise PipelineError(f"invalid doctrinal TEI: {exc}") from exc
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise UnsupportedStructure("unsupported-visible: doctrinal TEI root required")
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


def _validate_attributes(root: ET.Element, paths: Mapping[ET.Element, str]) -> None:
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in _HEADER and kind not in _STRUCTURE:
            raise UnsupportedStructure(f"unsupported-visible: element {kind} at {paths[node]}")
        for key in node.attrib:
            if key not in _ATTRIBUTES.get(kind, {XML_ID, XML_LANG}):
                raise UnsupportedStructure(f"unsupported-visible: {kind}@{_attr_name(key)} at {paths[node]}")
        if kind == "ref" and node.get("target") and node.get("cRef"):
            raise UnsupportedStructure(f"unsupported-visible: ref has both target and cRef at {paths[node]}")


def _source_binding(root: ET.Element, context: Mapping[str, Any]) -> dict[str, str]:
    source_desc = [node for node in root.iter() if _local(node.tag) == "sourceDesc"]
    if len(source_desc) != 1:
        raise PipelineError("doctrinal TEI must contain exactly one sourceDesc")
    ids: dict[str, str] = {}
    hashes: dict[str, str] = {}
    source_url = ""
    source_path_label = ""
    for node in source_desc[0].iter():
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
    if any(ids.get(key) != context["identity"][key] for key in _IDENTITY_KEYS):
        raise PipelineError("doctrinal TEI source identity mismatch")
    if not source_url or set(hashes) != {"source_sha256", "retained_sha256"}:
        raise PipelineError("doctrinal TEI sourceDesc has incomplete identity binding")
    for key in hashes:
        expected = context.get(key)
        if expected is not None and hashes[key] != _valid_sha(expected, key):
            raise PipelineError(f"doctrinal TEI {key} mismatch")
    expected_url = context.get("source_url")
    if expected_url is not None and source_url != expected_url:
        raise PipelineError("doctrinal TEI source URL mismatch")
    source_path = context.get("source_path")
    expected_path = context.get("source_logical_path")
    if expected_path is not None or source_path is not None:
        expected_path = expected_path or _logical_source_path(Path(source_path))
        if source_path_label != expected_path:
            raise PipelineError("doctrinal TEI source path mismatch")
    if source_path is not None:
        try:
            actual = _sha_bytes(Path(source_path).read_bytes())
        except OSError as exc:
            raise PipelineError(f"cannot read retained doctrinal source {source_path}: {exc}") from exc
        if actual != hashes["retained_sha256"]:
            raise PipelineError("doctrinal retained source hash does not match sourceDesc")
    binding = {"source_url": source_url, **hashes}
    if source_path_label:
        binding["source_path"] = source_path_label
    return binding


def _source_accounting(context: Mapping[str, Any], binding: Mapping[str, str], selection: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build a private receipt census for the retained source and TEI subset."""
    source_path = context.get("source_path")
    fields = ("source_selector", "source_scope", "source_unit_count", "source_selected_units", "source_census", "source_excerpt_sha256")
    if source_path is None and not any(context.get(field) is not None for field in fields):
        return None
    if source_path is None or any(context.get(field) is None for field in fields):
        raise PipelineError("doctrinal source accounting requires source path, selector, scope, census, selection, and excerpt hash")
    try:
        native_count = int(context["source_unit_count"])
    except (TypeError, ValueError) as exc:
        raise PipelineError("doctrinal source unit count must be an integer") from exc
    census = context["source_census"]
    selected_ids = [str(value) for value in context["source_selected_units"]]
    if not isinstance(census, Sequence) or isinstance(census, (str, bytes)):
        raise PipelineError("doctrinal source census must be a sequence")
    census_copy = [dict(item) if isinstance(item, Mapping) else item for item in census]
    if native_count != len(census_copy):
        raise PipelineError("doctrinal source census count mismatch")
    census_ids = [str(item.get("id")) for item in census_copy if isinstance(item, Mapping) and item.get("id") is not None]
    if len(census_ids) != native_count or len(set(census_ids)) != native_count:
        raise PipelineError("doctrinal source census identities must be unique")
    census_id_set = set(census_ids)
    if any(value not in census_id_set for value in selected_ids) or len(set(selected_ids)) != len(selected_ids):
        raise PipelineError("doctrinal source selection is not present in the census")
    native_selected_ids = [value for value in census_ids if value in set(selected_ids)]
    if selected_ids != native_selected_ids:
        raise PipelineError("doctrinal source selection does not follow native census order")
    if selection["selected_units"] > len(selected_ids):
        raise PipelineError("doctrinal source selection is smaller than the TEI selection")
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


def _bind_source_units(
    accounting: dict[str, Any] | None, declared: Any,
    leaves: Sequence[tuple[str | None, str]], anchors: list[dict[str, Any]],
) -> None:
    """Bind explicit source identities to independently observed TEI leaves.

    This validates a declaration already bound by acceptance; it does not infer
    correspondence from numbering, counts, prose similarity or list position.
    """
    hierarchy = any(":hierarchy-" in anchor["record_id"] for anchor in anchors)
    if declared is None:
        if hierarchy:
            raise PipelineError("doctrinal hierarchy requires source_tei_unit_bindings in source accounting")
        return
    if accounting is None:
        raise PipelineError("source_tei_unit_bindings require a source census")
    if not isinstance(declared, list) or not declared:
        raise PipelineError("source_tei_unit_bindings must be a nonempty list")
    by_id: dict[str, list[str]] = {}
    source_ids: list[str] = []
    for item in declared:
        if not isinstance(item, Mapping) or set(item) != {"tei_xml_id", "source_unit_ids"}:
            raise PipelineError("invalid source_tei_unit_bindings entry")
        target, ids = item["tei_xml_id"], item["source_unit_ids"]
        if not isinstance(target, str) or not target.strip() or target in by_id:
            raise PipelineError("duplicate or empty source binding TEI identity")
        if not isinstance(ids, list) or not ids or any(not isinstance(value, str) or not value.strip() for value in ids):
            raise PipelineError("source binding requires explicit nonempty source identities")
        by_id[target] = list(ids)
        source_ids.extend(ids)
    if source_ids != accounting["selected_unit_ids"]:
        raise PipelineError("source bindings do not cover selected source identities in census order")
    if list(by_id) != [identity for identity, _ in leaves]:
        raise PipelineError("source bindings do not cover TEI leaves in document order")
    by_path = {path: by_id[identity] for identity, path in leaves}
    for anchor in anchors:
        anchor["source_unit_ids"] = [source_id for path in anchor["selected_leaf_paths"]
                                     for source_id in by_path[path]]
    accounting["tei_unit_bindings"] = [
        {"tei_xml_id": identity, "tei_path": path, "source_unit_ids": by_id[identity]}
        for identity, path in leaves
    ]


def _text_parts(root: ET.Element) -> list[ET.Element]:
    texts = [node for node in list(root) if _local(node.tag) == "text"]
    if len(texts) != 1:
        raise UnsupportedStructure("unsupported-visible: doctrinal TEI requires one text element")
    parts = [node for node in list(texts[0]) if _local(node.tag) in _TEXT_PARTS]
    if not parts:
        raise UnsupportedStructure("unsupported-visible: doctrinal text has no front/body/back")
    if any(_local(node.tag) not in _TEXT_PARTS for node in list(texts[0])):
        raise UnsupportedStructure("unsupported-visible: text contains an unaccounted child")
    return parts


def _render(node: ET.Element | None, *, omit_notes: bool = False) -> str:
    if node is None:
        return ""
    chunks: list[str] = []

    def visit(current: ET.Element) -> None:
        kind = _local(current.tag)
        if kind == "note" and omit_notes:
            return
        if current.text:
            chunks.append(current.text)
        for child in list(current):
            child_kind = _local(child.tag)
            if child_kind == "lb":
                chunks.append("" if child.get("break") == "no" else " ")
            elif child_kind in {"pb", "anchor", "ptr"}:
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
            raise UnsupportedStructure(f"unsupported-visible: doctrinal inline {_local(child.tag)} at {paths[child]}")
        _inline_check(child, paths)


def _proof_content_carrier(node: ET.Element, paths: Mapping[ET.Element, str]) -> ET.Element | None:
    carriers = [child for child in list(node) if _local(child.tag) == "seg" and child.get("type") == _PROOF_CONTENT_TYPE]
    if len(carriers) > 1:
        raise UnsupportedStructure(f"unsupported-visible: multiple content-with-proofs carriers at {paths[node]}")
    if not carriers:
        return None
    carrier = carriers[0]
    if _render(node) != _render(carrier):
        raise UnsupportedStructure(f"unsupported-visible: content-with-proofs carrier does not cover its block at {paths[carrier]}")
    return carrier


def _unit_key(value: str | None, path: str) -> tuple[int, str]:
    value = _norm(value)
    if not value:
        return (0, "")
    match = re.fullmatch(r"([A-Za-z]*)([0-9]+)([A-Za-z&0-9]*)", value)
    if not match or (int(match.group(2)) < 1):
        raise UnsupportedStructure(f"unsupported-visible: invalid doctrinal number {value!r} at {path}")
    return int(match.group(2)), f"{match.group(1)}{match.group(3)}".lower()


def _validate_sibling_order(root: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> None:
    for parent in root.iter():
        units = [child for child in list(parent) if _local(child.tag) == "div" and child.get("type") in _NORMATIVE_TYPES]
        previous: tuple[int, str] | None = None
        for unit in units:
            raw_number = _norm(unit.get("n"))
            if not raw_number:
                previous = None
                continue
            current = _unit_key(raw_number, paths[unit])
            if previous is not None and current <= previous:
                raise UnsupportedStructure(f"unsupported-visible: doctrinal numbering is not ordered at {paths[unit]}")
            previous = current


def _proofs(list_node: ET.Element | None, paths: Mapping[ET.Element, str]) -> list[dict[str, Any]]:
    if list_node is None:
        return []
    result: list[dict[str, Any]] = []
    for item in list(list_node):
        if _local(item.tag) != "item" or not item.get("n"):
            raise UnsupportedStructure(f"unsupported-visible: proof item needs @n at {paths[item]}")
        number, suffix = _unit_key(item.get("n"), paths[item])
        if suffix:
            raise UnsupportedStructure(f"unsupported-visible: proof number must be numeric at {paths[item]}")
        refs = [node for node in item.iter() if _local(node.tag) == "ref"]
        if not refs:
            raise UnsupportedStructure(f"unsupported-visible: proof has no reference at {paths[item]}")
        parsed: list[dict[str, Any]] = []
        for ref in refs:
            target = _norm(ref.get("target") or ref.get("cRef"))
            raw = _render(ref)
            if not target or target.startswith("#") or not raw:
                raise UnsupportedStructure(f"unsupported-visible: invalid doctrinal proof reference at {paths[ref]}")
            parsed.append({"raw": raw, "osis": [target]})
        result.append({"id": number, "references": parsed})
    ids = [item["id"] for item in result]
    if len(ids) != len(set(ids)):
        raise UnsupportedStructure(f"unsupported-visible: duplicate proof number at {paths[list_node]}")
    return result


def _source_revision_events(root):
    events = []
    for note in root.findall('./{'+TEI_NS+'}teiHeader/{'+TEI_NS+'}fileDesc/{'+TEI_NS+'}sourceDesc/{'+TEI_NS+"}note[@type='source-revision']"):
        fields = {}
        if (note.text or '').strip():
            raise UnsupportedStructure('unassigned source revision text')
        for child in note:
            key = 'year' if _local(child.tag) == 'date' else child.get('type') if _local(child.tag) == 'seg' else None
            if key not in ('year', 'revising-body', 'description') or key in fields or len(child) or (child.tail or '').strip():
                raise UnsupportedStructure('unsupported source revision field')
            fields[key] = _norm(child.text or '')
        if not re.fullmatch(r'[1-9][0-9]{0,3}', fields.get('year', '')) or not fields.get('description'):
            raise UnsupportedStructure('source revision requires literal year and description')
        if 'revising-body' in fields and not fields['revising-body']:
            raise UnsupportedStructure('empty source revising body')
        events.append({'year':int(fields['year']), 'body':fields.get('revising-body'), 'description':fields['description']})
    return events


def _observed_source_revision_events(root):
    events = []
    ns = {'t':TEI_NS}
    for note in root.xpath('./t:teiHeader/t:fileDesc/t:sourceDesc/t:note[@type="source-revision"]', namespaces=ns):
        values = {}
        if (note.text or '').strip():
            raise UnsupportedStructure('checker: unassigned source history text')
        for element in note:
            tag = element.tag.rsplit('}', 1)[-1]
            role = 'year' if tag == 'date' else element.get('type') if tag == 'seg' else None
            if role not in ('year', 'revising-body', 'description') or role in values or len(element) or (element.tail or '').strip():
                raise UnsupportedStructure('checker: invalid source history field')
            values[role] = ' '.join((element.text or '').split())
        year = values.get('year', '')
        if not year.isascii() or not year.isdigit() or not 1 <= len(year) <= 4 or year.startswith('0') or not values.get('description'):
            raise UnsupportedStructure('checker: source history year or description missing')
        if values.get('revising-body') == '':
            raise UnsupportedStructure('checker: empty revising body')
        events.append(dict(year=int(year), body=values.get('revising-body'), description=values['description']))
    return events


def _revision_history(root: ET.Element) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    revision_desc = [node for node in root.iter() if _local(node.tag) == "revisionDesc"]
    if len(revision_desc) > 1:
        raise UnsupportedStructure("unsupported-visible: multiple revisionDesc elements")
    if not revision_desc:
        return _source_revision_events(root)
    representation_ids = {_norm("".join(node.itertext())) for node in root.iter()
                          if _local(node.tag) == "idno" and node.get("type") == "representation_revision"}
    for change in [node for node in revision_desc[0].iter() if _local(node.tag) == "change"]:
        if change.get(XML_ID) in representation_ids:
            continue  # Processing provenance stays in the private TEI header.
        raise UnsupportedStructure("unsupported-visible: revisionDesc change is not a declared representation revision; source revision history requires separate evidence")
    return _source_revision_events(root)


def _locator(unit: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str], source_order: int) -> dict[str, Any]:
    part = next((node for node in [unit, *_ancestors(unit, parents)] if _local(node.tag) in _TEXT_PARTS), None)
    if part is None:
        raise UnsupportedStructure(f"unsupported-visible: doctrinal unit has no text part at {paths[unit]}")
    divisions: list[dict[str, Any]] = []
    unit_path: list[str] = []
    for division in reversed([node for node in _ancestors(unit, parents) if _local(node.tag) == "div" and node.get("type") in _NORMATIVE_TYPES]):
        parent = parents.get(division)
        siblings = [child for child in (list(parent) if parent is not None else []) if _local(child.tag) == "div" and child.get("type") in _NORMATIVE_TYPES]
        divisions.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "number": _norm(division.get("n")) or None, "titles": [_render(child) for child in list(division) if _local(child.tag) == "head" and _render(child)]})
        unit_path.append(f"{division.get('type')}:{_norm(division.get('n')) or ''}".rstrip(":"))
    own = f"{unit.get('type')}:{_norm(unit.get('n')) or ''}".rstrip(":")
    unit_path.append(own)
    return {"kind": "unit", "text_part": _local(part.tag), "part_titles": [_render(child) for child in list(part) if _local(child.tag) == "head" and _render(child)], "divisions": divisions, "unit": own, "unit_path": unit_path, "source_order": source_order}


def _is_leaf_unit(node: ET.Element) -> bool:
    return _local(node.tag) == "div" and node.get("type") in _NORMATIVE_TYPES and not any(_local(child.tag) == "div" and child.get("type") in _NORMATIVE_TYPES for child in node.iter() if child is not node)


def _units(parts: Sequence[ET.Element], scope: ET.Element | None, parents: Mapping[ET.Element, ET.Element]) -> tuple[list[ET.Element], list[ET.Element]]:
    all_units = [node for part in parts for node in part.iter() if _is_leaf_unit(node) and not any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *_ancestors(node, parents)])]
    selected = [node for node in all_units if scope is None or node is scope or scope in _ancestors(node, parents)]
    return all_units, selected


def _hierarchy_selection(
    parts: Sequence[ET.Element], scope: ET.Element | None,
    parents: Mapping[ET.Element, ET.Element],
) -> tuple[list[ET.Element], dict[ET.Element, tuple[ET.Element, ...]]]:
    """Select disjoint roots and retain their exact selected leaf membership.

    Output roots may contain multiple leaves; source accounting still counts
    those leaves separately from output rows.
    """
    normative = [
        node for part in parts for node in part.iter()
        if _local(node.tag) == "div" and node.get("type") in _NORMATIVE_TYPES
        and not any(parent.get("type") in _EXCLUDED_TYPES
                    for parent in [node, *_ancestors(node, parents)])
    ]
    eligible = {
        node for node in normative
        if scope is None or node is scope or scope in _ancestors(node, parents)
    }
    mixed = {
        node for node in eligible if not _is_leaf_unit(node)
        and ((node.text or "").strip()
             or any((child.tail or "").strip() for child in node)
             or any(_local(child.tag) in {"p", "ab", "list", "item"}
                    for child in node))
    }
    roots = [
        node for node in normative if node in eligible
        and (_is_leaf_unit(node) or node in mixed)
        and not any(parent in mixed for parent in _ancestors(node, parents))
    ]
    members = {
        root: tuple(node for node in root.iter() if node in eligible and _is_leaf_unit(node))
        for root in roots
    }
    expected = [node for node in normative if node in eligible and _is_leaf_unit(node)]
    observed = [node for root in roots for node in members[root]]
    if observed != expected:
        raise UnsupportedStructure("hierarchy selection lost, duplicated, or reordered source units")
    return roots, members


def _scope(parts: Sequence[ET.Element], scope_id: str | None) -> ET.Element | None:
    if scope_id is None:
        return None
    found = [node for part in parts for node in part.iter() if node.get(XML_ID) == scope_id]
    if len(found) != 1 or _local(found[0].tag) != "div":
        raise UnsupportedStructure(f"unsupported-visible: doctrinal scope is not one div: {scope_id}")
    return found[0]


def _row(unit: ET.Element, identity: Mapping[str, str], sequence: int, source_order: int, context: Mapping[str, Any], parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> dict[str, Any]:
    unit_type = _norm(unit.get("type"))
    if unit_type not in _NORMATIVE_TYPES:
        raise UnsupportedStructure(f"unsupported-visible: unknown normative type at {paths[unit]}")
    number = _norm(unit.get("n")) or None
    if number is not None:
        _unit_key(number, paths[unit])
    heading = next((_render(child) for child in list(unit) if _local(child.tag) == "head" and _render(child)), None)
    content_candidates = [child for child in list(unit) if _local(child.tag) in {"p", "ab"}]
    unsupported_content = [node for node in content_candidates if node.get("type") not in _CONTENT_TYPES]
    if unsupported_content:
        raise UnsupportedStructure(f"unsupported-visible: doctrinal content type at {paths[unsupported_content[0]]}")
    content_nodes: list[ET.Element] = []
    proof_content_nodes: list[ET.Element] = []
    proof_content_carriers: list[ET.Element] = []
    for node in content_candidates:
        carrier = _proof_content_carrier(node, paths)
        if carrier is None:
            content_nodes.append(node)
        else:
            proof_content_nodes.append(node)
            proof_content_carriers.append(carrier)
    if len(proof_content_nodes) > 1:
        raise UnsupportedStructure(f"unsupported-visible: multiple content-with-proofs blocks at {paths[unit]}")
    for node in [*content_nodes, *proof_content_nodes]:
        _inline_check(node, paths)
    content_blocks = [_render(node) for node in content_nodes]
    content_with_proofs = _render(proof_content_carriers[0]) if proof_content_carriers else None
    if proof_content_nodes and not content_with_proofs:
        raise UnsupportedStructure(f"unsupported-visible: empty content-with-proofs block at {paths[proof_content_nodes[0]]}")
    proof_lists = [child for child in list(unit) if _local(child.tag) == "list" and child.get("type") == "proofs"]
    if len(proof_lists) > 1:
        raise UnsupportedStructure(f"unsupported-visible: multiple proof lists at {paths[unit]}")
    proofs = _proofs(proof_lists[0] if proof_lists else None, paths)
    locator = _locator(unit, parents, paths, source_order)
    content = "\n\n".join(content_blocks) or (heading or "")
    row = {**{key: identity[key] for key in _IDENTITY_KEYS}, "record_id": f"{identity['edition_id']}:unit-{source_order:06d}", "sequence": sequence, "category": "doctrinal_documents", "language": context["language"], "representation_revision": context["representation_revision"], "text": content, "document_id": identity["work_id"], "document_kind": context["document_kind"], "unit_type": unit_type, "number": number, "title": heading, "content": "\n\n".join(content_blocks) if content_blocks else None, "content_blocks": content_blocks, "content_with_proofs": content_with_proofs, "proofs": proofs, "revision_history": context["revision_history"], "parent_path": locator["unit_path"][:-1], "locator": locator, "provenance": {"edition_title": context["edition_title"]}}

    if not _is_leaf_unit(unit):
        if any(node.get("type") in _EXCLUDED_TYPES for node in unit.iter()):
            raise UnsupportedStructure("excluded paratext inside a normative hierarchy requires explicit partitioning")
        structure = native_content.project_content(unit)
        row["content_format"] = "ocd-native-content-v1"
        row["structure"] = structure
        row["text"] = native_content.readable_content(structure)
        # A parent's identity must remain distinct from its first child when
        # that child is subsequently exported under a narrower scope.
        row["record_id"] = f"{identity['edition_id']}:hierarchy-{source_order:06d}"
    return row



def _inventory(root: ET.Element, parts: Sequence[ET.Element], all_units: Sequence[ET.Element], selected: Sequence[ET.Element], paths: Mapping[ET.Element, str], parents: Mapping[ET.Element, ET.Element], scope: ET.Element | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text_nodes = {node for part in parts for node in part.iter()}
    selected_nodes = {node for unit in selected for node in unit.iter()}
    outside_nodes = {node for unit in all_units if unit not in selected for node in unit.iter()}
    if scope is not None:
        outside_nodes.update(text_nodes - selected_nodes)
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
        elif kind in {"text", "front", "body", "back", "div"} and (
            (node.text or "").strip() or any((child.tail or "").strip() for child in node)
        ):
            raise UnsupportedStructure(f"unsupported-visible: parent text outside projected units at {paths[node]}")
        elif kind in {"p", "ab", "list", "item"}:
            raise UnsupportedStructure(f"unsupported-visible: parent content outside projected units at {paths[node]}")
        elif kind == "head":
            disposition = "excluded-heading"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"unsupported-visible: unassigned doctrinal element at {paths[node]}")
        inventory.append({"ordinal": ordinal, "tei_path": paths[node], "namespace": TEI_NS, "tag": kind, "disposition": disposition, "attributes": {_attr_name(key): value for key, value in sorted(node.attrib.items())}, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    for unit in all_units:
        if unit not in selected_nodes:
            exclusions.append({"tei_path": paths[unit], "reason": "outside-scope", "xml_id": unit.get(XML_ID), "unit_type": unit.get("type"), "number": unit.get("n")})
    for node in sorted(excluded_paratext, key=lambda item: paths[item]):
        if node.get("type") in _EXCLUDED_TYPES:
            exclusions.append({"tei_path": paths[node], "reason": "excluded-paratext", "xml_id": node.get(XML_ID)})
    return inventory, exclusions


def _warnings(root: ET.Element, selected: Sequence[ET.Element], paths: Mapping[ET.Element, str]) -> list[dict[str, str]]:
    selected_nodes = {node for unit in selected for node in unit.iter()}
    native_nodes = {node for unit in selected if not _is_leaf_unit(unit) for node in unit.iter()}
    reasons = {"ref": "source-reference-preserved", "note": "note-extracted", "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text", "seg": "segmentation-to-plain-text", "lb": "line-break-to-space", "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted"}
    return [{"tei_path": paths[node], "reason": "native-content-preserved" if node in native_nodes else reasons[_local(node.tag)]} for node in root.iter() if node in selected_nodes and _local(node.tag) in reasons]


def _validator() -> Any:
    try:
        import jsonschema
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        common = json.loads(COMMON.read_text(encoding="utf-8"))
        registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
        native = json.loads(native_content.SCHEMA.read_text(encoding="utf-8"))
        registry = registry.with_resource(native["$id"], Resource.from_contents(native, default_specification=DRAFT202012))
        validator = projection_validator(schema, registry=registry)
        validator.check_schema(schema)
        return validator
    except (ImportError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(f"invalid doctrinal schema package: {exc}") from exc


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"invalid doctrinal public row {row.get('record_id', f'row-{index}')}: {errors[0].message}")


def project_doctrinal_document(tei_path: Path, *, identity: Mapping[str, str], language: str = "en", representation_revision: str = "tei-v2", edition_title: str = "", document_kind: str = "confession", source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, source_path: Path | None = None, source_logical_path: str | None = None, source_selector: Mapping[str, Any] | None = None, source_scope: str | None = None, source_unit_count: int | None = None, source_selected_units: Sequence[str] | None = None, source_census: Sequence[Mapping[str, Any]] | None = None, source_excerpt_sha256: str | None = None, source_tei_unit_bindings: Sequence[Mapping[str, Any]] | None = None, scope_id: str | None = None) -> dict[str, Any]:
    identity_value = _identity(identity)
    if not isinstance(language, str) or not _LANG_RE.fullmatch(language):
        raise PipelineError("invalid doctrinal language")
    if not isinstance(representation_revision, str) or not representation_revision.strip():
        raise PipelineError("missing doctrinal representation revision")
    if not isinstance(edition_title, str) or not edition_title.strip():
        raise PipelineError("missing doctrinal edition title")
    if document_kind not in _DOCUMENT_KINDS:
        raise PipelineError(f"unsupported-visible: invalid doctrinal document kind {document_kind}")
    context = {"identity": identity_value, "language": language, "representation_revision": representation_revision, "edition_title": edition_title, "document_kind": document_kind, "source_url": source_url, "source_sha256": source_sha256, "retained_sha256": retained_sha256, "source_path": source_path, "source_logical_path": source_logical_path, "source_selector": source_selector, "source_scope": source_scope, "source_unit_count": source_unit_count, "source_selected_units": source_selected_units, "source_census": source_census, "source_excerpt_sha256": source_excerpt_sha256}
    root, raw = _read_root(Path(tei_path))
    paths = _paths(root)
    parents = _parents(root)
    _validate_attributes(root, paths)
    _validate_sibling_order(root, parents, paths)
    binding = _source_binding(root, context)
    parts = _text_parts(root)
    scope = _scope(parts, scope_id)
    all_units, selected_leaves = _units(parts, scope, parents)
    selected, members = _hierarchy_selection(parts, scope, parents)
    if not selected:
        raise UnsupportedStructure("unsupported-visible: doctrinal TEI contains no selected normative units")
    context["revision_history"] = _revision_history(root)
    global_order = {node: index for index, node in enumerate(all_units, 1)}
    hierarchy_order = {node: index for index, node in enumerate(
        [node for part in parts for node in part.iter()
         if _local(node.tag) == "div" and node.get("type") in _NORMATIVE_TYPES], 1)}
    global_order.update({unit: hierarchy_order[unit] for unit in selected if not _is_leaf_unit(unit)})
    rows = [_row(unit, identity_value, sequence, global_order[unit], context, parents, paths) for sequence, unit in enumerate(selected, 1)]
    if len({row["record_id"] for row in rows}) != len(rows):
        raise UnsupportedStructure("unsupported-visible: duplicate doctrinal unit identity")
    inventory, exclusions = _inventory(root, parts, all_units, selected, paths, parents, scope)
    warnings = _warnings(root, selected, paths)
    anchors = [{"record_id": row["record_id"], "tei_path": paths[unit], "xml_id": unit.get(XML_ID), "source_order": global_order[unit], "unit_type": row["unit_type"], "number": row["number"], "text_sha256": _sha_text(row["text"])} for row, unit in zip(rows, selected)]
    for anchor, unit in zip(anchors, selected):
        anchor["selected_leaf_paths"] = [paths[leaf] for leaf in members[unit]]
    selection = {"available_units": len(all_units), "selected_units": len(selected_leaves), "excluded_units": len(all_units) - len(selected_leaves), "scope_id": scope_id}
    source_accounting = _source_accounting(context, binding, selection)
    _bind_source_units(source_accounting, source_tei_unit_bindings,
                       [(node.get(XML_ID), paths[node]) for node in all_units], anchors)
    _validate_rows(rows)
    return {"rows": rows, "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "master_sha256": _sha_bytes(raw), "scope_id": scope_id, "mapping_version": MAPPING_VERSION, "source_binding": binding, "source_accounting": source_accounting, "schema_sha256": _sha_bytes(SCHEMA.read_bytes()), "common_schema_sha256": _sha_bytes(COMMON.read_bytes()), "native_content_schema_sha256": _sha_bytes(native_content.SCHEMA.read_bytes()), "selection": selection, "document_id": identity_value["work_id"], "document_kind": document_kind, "revision_history": context["revision_history"]}


project_document = project_doctrinal_document
project_doctrinal = project_doctrinal_document


def build_doctrinal_receipt(projection: Mapping[str, Any], *, identity: Mapping[str, str]) -> dict[str, Any]:
    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise PipelineError("doctrinal projection rows must be a list")
    return {"schema_version": "ocd-doctrinal-receipt-v2", "receipt_version": RECEIPT_VERSION, "mapping_version": projection.get("mapping_version", MAPPING_VERSION), "assembler_version": ASSEMBLER_VERSION, "category": "doctrinal_documents", "identity": dict(identity), "master_sha256": projection.get("master_sha256"), "schema_sha256": projection.get("schema_sha256", _sha_bytes(SCHEMA.read_bytes())), "common_schema_sha256": projection.get("common_schema_sha256", _sha_bytes(COMMON.read_bytes())), "native_content_schema_sha256": projection.get("native_content_schema_sha256", _sha_bytes(native_content.SCHEMA.read_bytes())), "scope_id": projection.get("scope_id"), "source_binding": dict(projection.get("source_binding", {})), "source_accounting": projection.get("source_accounting"), "selection": dict(projection.get("selection", {})), "document_id": projection.get("document_id"), "document_kind": projection.get("document_kind"), "revision_history": list(projection.get("revision_history", [])), "output_sha256": _sha_bytes(_canonical(rows)), "row_count": len(rows), "anchors": list(projection.get("anchors", [])), "inventory": list(projection.get("inventory", [])), "warnings": list(projection.get("warnings", [])), "exclusions": list(projection.get("exclusions", [])), "unsupported": list(projection.get("unsupported", [])), "independent_check": {"status": "pending", "errors": []}}


def _checker_parse(path: Path) -> tuple[Any, bytes]:
    from lxml import etree
    try:
        raw = path.read_bytes()
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"checker: cannot parse doctrinal TEI: {exc}") from exc
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


def _checker_text(node: Any, *, omit_notes: bool = False) -> str:
    """Read XML events independently; emit each closing element's tail once."""
    from lxml import etree
    chunks: list[str] = []
    skipped_note_depth = 0
    for event, element in etree.iterwalk(node, events=("start", "end")):
        kind = etree.QName(element).localname
        if event == "start":
            if omit_notes and kind == "note":
                skipped_note_depth += 1
            if skipped_note_depth:
                continue
            if kind == "lb":
                chunks.append("" if element.get("break") == "no" else " ")
            elif kind in {"pb", "anchor", "ptr"}:
                chunks.append(" ")
            elif element.text:
                chunks.append(element.text)
        else:
            if omit_notes and kind == "note":
                skipped_note_depth -= 1
            if not skipped_note_depth and element is not node and element.tail:
                chunks.append(element.tail)
    return _norm("".join(chunks))


def _checker_inline_check(node: Any, paths: Mapping[Any, str]) -> None:
    """Validate visible descendants without consulting the ElementTree producer."""
    from lxml import etree

    for child in node:
        kind = etree.QName(child).localname
        if kind not in _INLINE:
            raise UnsupportedStructure(f"checker: doctrinal inline {kind} at {paths[child]}")
        _checker_inline_check(child, paths)


def _checker_proof_content_carrier(node: Any, paths: Mapping[Any, str]) -> Any | None:
    from lxml import etree

    carriers = [child for child in node if etree.QName(child).localname == "seg" and child.get("type") == _PROOF_CONTENT_TYPE]
    if len(carriers) > 1:
        raise UnsupportedStructure(f"checker: multiple content-with-proofs carriers at {paths[node]}")
    if not carriers:
        return None
    carrier = carriers[0]
    if _checker_text(node) != _checker_text(carrier):
        raise UnsupportedStructure(f"checker: content-with-proofs carrier does not cover its block at {paths[carrier]}")
    return carrier


def _checker_source_binding(root: Any, identity: Mapping[str, str]) -> dict[str, str]:
    from lxml import etree
    source = root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces={"tei": TEI_NS})
    if len(source) != 1:
        raise UnsupportedStructure("checker: exactly one sourceDesc is required")
    ids: dict[str, str] = {}
    hashes: dict[str, str] = {}
    source_url = ""
    source_path_label = ""
    for node in source[0].iter():
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
        raise UnsupportedStructure("checker: incomplete doctrinal source binding")
    binding = {"source_url": source_url, **hashes}
    if source_path_label:
        binding["source_path"] = source_path_label
    return binding


def _checker_proofs(list_node: Any, paths: Mapping[Any, str]) -> list[dict[str, Any]]:
    from lxml import etree
    result: list[dict[str, Any]] = []
    for item in list_node.xpath("./tei:item", namespaces={"tei": TEI_NS}):
        match = re.fullmatch(r"([0-9]+)", _norm(item.get("n")))
        if not match or int(match.group(1)) < 1:
            raise UnsupportedStructure(f"checker: invalid proof number at {paths[item]}")
        refs = item.xpath(".//tei:ref", namespaces={"tei": TEI_NS})
        if not refs:
            raise UnsupportedStructure(f"checker: proof has no reference at {paths[item]}")
        parsed: list[dict[str, Any]] = []
        for ref in refs:
            target = _norm(ref.get("target") or ref.get("cRef"))
            raw = _checker_text(ref)
            if not target or target.startswith("#") or not raw:
                raise UnsupportedStructure(f"checker: invalid proof reference at {paths[ref]}")
            parsed.append({"raw": raw, "osis": [target]})
        result.append({"id": int(match.group(1)), "references": parsed})
    ids = [item["id"] for item in result]
    if len(ids) != len(set(ids)):
        raise UnsupportedStructure("checker: duplicate proof number")
    return result


def _checker_revision_history(root: Any) -> list[dict[str, Any]]:
    from lxml import etree
    desc = root.xpath(".//tei:revisionDesc", namespaces={"tei": TEI_NS})
    if len(desc) > 1:
        raise UnsupportedStructure("checker: multiple revisionDesc elements")
    result: list[dict[str, Any]] = []
    representation_ids = set(root.xpath(".//tei:idno[@type='representation_revision']/text()", namespaces={"tei": TEI_NS}))
    representation_ids = {value.strip() for value in representation_ids}
    for change in desc[0].xpath(".//tei:change", namespaces={"tei": TEI_NS}) if desc else []:
        if change.get(XML_ID) not in representation_ids:
            raise UnsupportedStructure("checker: revisionDesc change lacks declared representation identity; source revision history requires separate evidence")
    return _observed_source_revision_events(root)


def _checker_locator(unit: Any, paths: Mapping[Any, str], source_order: int) -> dict[str, Any]:
    from lxml import etree
    part = next((node for node in [unit, *list(unit.iterancestors())] if etree.QName(node).localname in _TEXT_PARTS), None)
    if part is None:
        raise UnsupportedStructure(f"checker: unit has no text part at {paths[unit]}")
    ancestors = [node for node in reversed(list(unit.iterancestors())) if etree.QName(node).localname == "div" and node.get("type") in _NORMATIVE_TYPES]
    divisions: list[dict[str, Any]] = []
    unit_path: list[str] = []
    for division in ancestors:
        parent = division.getparent()
        siblings = [child for child in parent if etree.QName(child).localname == "div" and child.get("type") in _NORMATIVE_TYPES]
        divisions.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "number": _norm(division.get("n")) or None, "titles": [_checker_text(child) for child in division if etree.QName(child).localname == "head" and _checker_text(child)]})
        unit_path.append(f"{division.get('type')}:{_norm(division.get('n')) or ''}".rstrip(":"))
    own = f"{unit.get('type')}:{_norm(unit.get('n')) or ''}".rstrip(":")
    unit_path.append(own)
    return {"kind": "unit", "text_part": etree.QName(part).localname, "part_titles": [_checker_text(child) for child in part if etree.QName(child).localname == "head" and _checker_text(child)], "divisions": divisions, "unit": own, "unit_path": unit_path, "source_order": source_order}


def _checker_rows(root: Any, identity: Mapping[str, str], language: str, revision: str, title: str, document_kind: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], dict[str, int], list[dict[str, Any]]]:
    from lxml import etree
    ns = {"t": TEI_NS}
    text = root.xpath("./t:text", namespaces=ns)
    if len(text) != 1:
        raise UnsupportedStructure("checker: one text is required")
    parts = [node for node in text[0] if etree.QName(node).localname in _TEXT_PARTS]
    if not parts:
        raise UnsupportedStructure("checker: no text part")
    scope = None
    if scope_id is not None:
        found = root.xpath(".//*[@xml:id=$value]", namespaces={"xml": XML_NS}, value=scope_id)
        if len(found) != 1 or etree.QName(found[0]).localname != "div":
            raise UnsupportedStructure("checker: scope is not one div")
        scope = found[0]
    all_units = [node for part in parts for node in part.xpath(".//t:div", namespaces=ns) if node.get("type") in _NORMATIVE_TYPES and not any(child.tag.endswith("}div") and child.get("type") in _NORMATIVE_TYPES for child in node.iterdescendants()) and not any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *list(node.iterancestors())])]
    selected_leaves = [node for node in all_units if scope is None or node is scope or scope in list(node.iterancestors())]
    normative = [node for part in parts for node in part.xpath(".//t:div", namespaces=ns)
                 if node.get("type") in _NORMATIVE_TYPES]
    eligible = [node for node in normative
                if (scope is None or node is scope or scope in list(node.iterancestors()))
                and not any(ancestor.get("type") in _EXCLUDED_TYPES
                            for ancestor in [node, *node.iterancestors()])]
    containers = {node for node in eligible if node not in all_units
                  and ((node.text or "").strip()
                       or any((child.tail or "").strip() for child in node)
                       or node.xpath("./t:p | ./t:ab | ./t:list | ./t:item", namespaces=ns))}
    selected = [node for node in eligible if (node in all_units or node in containers)
                and not any(ancestor in containers for ancestor in node.iterancestors())]
    members = {node: tuple(leaf for leaf in selected_leaves
                          if leaf is node or node in list(leaf.iterancestors()))
               for node in selected}
    if [leaf for node in selected for leaf in members[node]] != selected_leaves:
        raise UnsupportedStructure("checker: selected hierarchy leaf coverage differs")
    if not selected:
        raise UnsupportedStructure("checker: no selected normative units")
    paths = _checker_paths(root)
    global_order = {id(node): index for index, node in enumerate(all_units, 1)}
    global_order.update({id(node): index for index, node in enumerate(normative, 1)
                         if node in selected and node not in all_units})
    for parent in root.iter():
        units = [child for child in parent if etree.QName(child).localname == "div" and child.get("type") in _NORMATIVE_TYPES]
        previous: tuple[int, str] | None = None
        for unit in units:
            raw_number = _norm(unit.get("n"))
            match = re.fullmatch(r"([A-Za-z]*)([0-9]+)([A-Za-z&0-9]*)", raw_number) if raw_number else None
            if raw_number and (not match or int(match.group(2)) < 1):
                raise UnsupportedStructure(f"checker: invalid normative number at {paths[unit]}")
            if not raw_number:
                previous = None
                continue
            current = (int(match.group(2)), f"{match.group(1)}{match.group(3)}".lower())
            if previous is not None and current <= previous:
                raise UnsupportedStructure("checker: normative numbering is not ordered")
            previous = current
    history = _checker_revision_history(root)
    rows: list[dict[str, Any]] = []
    for sequence, unit in enumerate(selected, 1):
        unit_type = _norm(unit.get("type"))
        number = _norm(unit.get("n")) or None
        heading_node = next((child for child in unit if etree.QName(child).localname == "head"), None)
        if heading_node is not None:
            _checker_inline_check(heading_node, paths)
        heading = _checker_text(heading_node) if heading_node is not None else None
        content_candidates = [child for child in unit if etree.QName(child).localname in {"p", "ab"}]
        unsupported_content = [child for child in content_candidates if child.get("type") not in _CONTENT_TYPES]
        if unsupported_content:
            raise UnsupportedStructure(f"checker: doctrinal content type at {paths[unsupported_content[0]]}")
        content_nodes: list[Any] = []
        proof_content_nodes: list[Any] = []
        proof_content_carriers: list[Any] = []
        for node in content_candidates:
            carrier = _checker_proof_content_carrier(node, paths)
            if carrier is None:
                content_nodes.append(node)
            else:
                proof_content_nodes.append(node)
                proof_content_carriers.append(carrier)
        if len(proof_content_nodes) > 1:
            raise UnsupportedStructure(f"checker: multiple content-with-proofs blocks at {paths[unit]}")
        for node in [*content_nodes, *proof_content_nodes]:
            _checker_inline_check(node, paths)
        content_blocks = [_checker_text(node) for node in content_nodes]
        content_with_proofs = _checker_text(proof_content_carriers[0]) if proof_content_carriers else None
        if proof_content_nodes and not content_with_proofs:
            raise UnsupportedStructure(f"checker: empty content-with-proofs block at {paths[proof_content_nodes[0]]}")
        proof_lists = [child for child in unit if etree.QName(child).localname == "list" and child.get("type") == "proofs"]
        if len(proof_lists) > 1:
            raise UnsupportedStructure(f"checker: multiple proof lists at {paths[unit]}")
        proofs = _checker_proofs(proof_lists[0], paths) if proof_lists else []
        locator = _checker_locator(unit, paths, global_order[id(unit)])
        content = "\n\n".join(content_blocks) or (heading or "")
        rows.append({**{key: identity[key] for key in _IDENTITY_KEYS}, "record_id": f"{identity['edition_id']}:unit-{global_order[id(unit)]:06d}", "sequence": sequence, "category": "doctrinal_documents", "language": language, "representation_revision": revision, "text": content, "document_id": identity["work_id"], "document_kind": document_kind, "unit_type": unit_type, "number": number, "title": heading, "content": "\n\n".join(content_blocks) if content_blocks else None, "content_blocks": content_blocks, "content_with_proofs": content_with_proofs, "proofs": proofs, "revision_history": history, "parent_path": locator["unit_path"][:-1], "locator": locator, "provenance": {"edition_title": title}})
        if unit not in all_units:
            if any(node.get("type") in _EXCLUDED_TYPES for node in unit.iter()):
                raise UnsupportedStructure("checker: hierarchy contains excluded paratext")
            structure, readable = native_content_check.observe_content(etree.tostring(unit, with_tail=False))
            rows[-1]["content_format"] = "ocd-native-content-v1"
            rows[-1]["structure"] = structure
            rows[-1]["text"] = readable
            rows[-1]["record_id"] = f"{identity['edition_id']}:hierarchy-{global_order[id(unit)]:06d}"
    selected_nodes = {node for unit in selected for node in unit.iter()}
    outside_nodes = {node for unit in all_units if unit not in selected for node in unit.iter()}
    text_nodes = {node for part in parts for node in part.iter()}
    if scope is not None:
        outside_nodes.update(text_nodes - selected_nodes)
    excluded_paratext = {node for part in parts for node in part.iter() if any(ancestor.get("type") in _EXCLUDED_TYPES for ancestor in [node, *list(node.iterancestors())])}
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        qname = etree.QName(node)
        kind = qname.localname
        if node not in text_nodes:
            disposition = "private-header"
        elif node in excluded_paratext:
            disposition = "excluded-paratext"
        elif node in selected_nodes:
            disposition = "row-content"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif kind in {"text", "front", "body", "back", "div"} and (
            (node.text or "").strip() or any((child.tail or "").strip() for child in node)
        ):
            raise UnsupportedStructure(f"unsupported-visible: parent text outside projected units at {paths[node]}")
        elif kind in {"p", "ab", "list", "item"}:
            raise UnsupportedStructure(f"unsupported-visible: parent content outside projected units at {paths[node]}")
        elif kind == "head":
            disposition = "excluded-heading"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"checker: unassigned element at {paths[node]}")
        attrs = {"xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else (key.rsplit("}", 1)[-1] if key.startswith("{") else key): value for key, value in sorted(node.attrib.items())}
        inventory.append({"ordinal": ordinal, "tei_path": paths[node], "namespace": qname.namespace or "", "tag": kind, "disposition": disposition, "attributes": attrs, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    for unit in all_units:
        if unit not in selected_nodes:
            exclusions.append({"tei_path": paths[unit], "reason": "outside-scope", "xml_id": unit.get(XML_ID), "unit_type": unit.get("type"), "number": unit.get("n")})
    for node in sorted(excluded_paratext, key=lambda item: paths[item]):
        if node.get("type") in _EXCLUDED_TYPES:
            exclusions.append({"tei_path": paths[node], "reason": "excluded-paratext", "xml_id": node.get(XML_ID)})
    native_nodes = {node for unit in selected if unit not in all_units for node in unit.iter()}
    reasons = {"ref": "source-reference-preserved", "note": "note-extracted", "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text", "seg": "segmentation-to-plain-text", "lb": "line-break-to-space", "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted"}
    warnings = [{"tei_path": paths[node], "reason": "native-content-preserved" if node in native_nodes else reasons[etree.QName(node).localname]} for node in root.iter() if node in selected_nodes and etree.QName(node).localname in reasons]
    anchors = [{"record_id": row["record_id"], "tei_path": paths[unit], "xml_id": unit.get(XML_ID), "source_order": global_order[id(unit)], "unit_type": row["unit_type"], "number": row["number"], "text_sha256": _sha_text(row["text"])} for row, unit in zip(rows, selected)]
    for anchor, unit in zip(anchors, selected):
        anchor["selected_leaf_paths"] = [paths[leaf] for leaf in members[unit]]
    selection = {"available_units": len(all_units), "selected_units": len(selected_leaves), "excluded_units": len(all_units) - len(selected_leaves), "scope_id": scope_id}
    return rows, anchors, inventory, exclusions, warnings, selection, history


def verify_doctrinal_document(tei_path: Path, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None = None, *, identity: Mapping[str, str], language: str = "en", representation_revision: str = "tei-v2", edition_title: str = "", document_kind: str = "confession", source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, source_path: Path | None = None, source_logical_path: str | None = None, source_selector: Mapping[str, Any] | None = None, source_scope: str | None = None, source_unit_count: int | None = None, source_selected_units: Sequence[str] | None = None, source_census: Sequence[Mapping[str, Any]] | None = None, source_excerpt_sha256: str | None = None, source_tei_unit_bindings: Sequence[Mapping[str, Any]] | None = None, scope_id: str | None = None) -> list[str]:
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
        if not _LANG_RE.fullmatch(language) or not representation_revision.strip() or not edition_title.strip() or document_kind not in _DOCUMENT_KINDS:
            raise PipelineError("checker: invalid doctrinal projection context")
        context = {"identity": identity_value, "source_url": source_url, "source_sha256": source_sha256, "retained_sha256": retained_sha256, "source_path": source_path, "source_logical_path": source_logical_path, "source_selector": source_selector, "source_scope": source_scope, "source_unit_count": source_unit_count, "source_selected_units": source_selected_units, "source_census": source_census, "source_excerpt_sha256": source_excerpt_sha256}
        root, raw = _checker_parse(Path(tei_path))
        paths = _checker_paths(root)
        from lxml import etree
        for node in root.iter():
            qname = etree.QName(node)
            if qname.namespace != TEI_NS or (qname.localname not in _HEADER and qname.localname not in _STRUCTURE):
                raise UnsupportedStructure(f"checker: unsupported element at {paths[node]}")
            for key in node.attrib:
                if key not in _ATTRIBUTES.get(qname.localname, {XML_ID, XML_LANG}):
                    raise UnsupportedStructure(f"checker: unsupported attribute at {paths[node]}")
        binding = _checker_source_binding(root, identity_value)
        if source_url is not None and binding["source_url"] != source_url:
            raise PipelineError("checker: source URL mismatch")
        if source_sha256 is not None and binding["source_sha256"] != _valid_sha(source_sha256, "source_sha256"):
            raise PipelineError("checker: source_sha256 mismatch")
        if retained_sha256 is not None and binding["retained_sha256"] != _valid_sha(retained_sha256, "retained_sha256"):
            raise PipelineError("checker: retained_sha256 mismatch")
        if source_logical_path is not None or source_path is not None:
            expected_path = source_logical_path or _logical_source_path(Path(source_path))
            if binding.get("source_path") != expected_path:
                raise PipelineError("checker: source path mismatch")
        if source_path is not None:
            if _sha_bytes(Path(source_path).read_bytes()) != binding["retained_sha256"]:
                raise PipelineError("checker: retained source hash mismatch")
        expected_rows, anchors, inventory, exclusions, warnings, selection, history = _checker_rows(root, identity_value, language, representation_revision, edition_title, document_kind, scope_id)
        source_accounting = _source_accounting(context, binding, selection)
        leaves = [(node.get(XML_ID), paths[node]) for node in root.xpath("./t:text/*//t:div", namespaces={"t": TEI_NS})
                  if node.get("type") in _NORMATIVE_TYPES
                  and not any(child.get("type") in _NORMATIVE_TYPES for child in node.xpath(".//t:div", namespaces={"t": TEI_NS}))
                  and not any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *node.iterancestors()])]
        _bind_source_units(source_accounting, source_tei_unit_bindings, leaves, anchors)
        _validate_rows(expected_rows)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if not isinstance(provided, Sequence) or isinstance(provided, (str, bytes)):
        errors.append("doctrinal rows must be a sequence")
    elif list(provided) != expected_rows:
        errors.append("doctrinal rows do not match independent TEI traversal")
    if receipt is None:
        errors.append("doctrinal receipt is missing")
        return errors
    if not isinstance(receipt, Mapping):
        return errors + ["doctrinal receipt must be an object"]
    expected_receipt = {"schema_version": "ocd-doctrinal-receipt-v2", "receipt_version": RECEIPT_VERSION, "mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "category": "doctrinal_documents", "identity": identity_value, "master_sha256": _sha_bytes(raw), "schema_sha256": _sha_bytes(SCHEMA.read_bytes()), "common_schema_sha256": _sha_bytes(COMMON.read_bytes()), "native_content_schema_sha256": _sha_bytes(native_content.SCHEMA.read_bytes()), "scope_id": scope_id, "source_binding": binding, "source_accounting": source_accounting, "selection": selection, "document_id": identity_value["work_id"], "document_kind": document_kind, "revision_history": history, "output_sha256": _sha_bytes(_canonical(expected_rows)), "row_count": len(expected_rows), "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending", "errors": []}}
    if set(receipt) != set(expected_receipt):
        errors.append("doctrinal receipt fields differ")
    for key, wanted in expected_receipt.items():
        if receipt.get(key) != wanted:
            errors.append(f"doctrinal receipt {key} mismatch")
    if isinstance(provided, Sequence) and not isinstance(provided, (str, bytes)):
        try:
            _validate_rows(provided)  # type: ignore[arg-type]
        except PipelineError as exc:
            errors.append(str(exc))
    return errors


check_doctrinal_document = verify_doctrinal_document
verify_document = verify_doctrinal_document


def _accepted_kind(document: Mapping[str, Any], field: str, allowed: set[str]) -> str:
    nested = document.get("projection_context")
    source = nested if isinstance(nested, Mapping) else document
    value = source.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise PipelineError(f"source.accounting {field} is missing or invalid")
    return value


def _accepted_metadata(root: Path, acceptance_path: Path) -> dict[str, Any]:
    """Validate promoted authority and derive the complete doctrinal context."""

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
        raise PipelineError("doctrinal projection requires a promoted accepted master")
    accepted_identity = accepted.get("identity")
    if not isinstance(accepted_identity, Mapping):
        raise PipelineError("accepted identity is missing")
    identity = {key: accepted_identity[key] for key in (*_IDENTITY_KEYS, "acquisition_id")}
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    if work.work_id != identity["work_id"] or edition.textual_form_id != identity["textual_form_id"]:
        raise PipelineError("accepted identity does not identify the canonical doctrinal edition")
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
    if category != "doctrinal-documents":
        raise PipelineError("accepted edition category mismatch")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not _LANG_RE.fullmatch(language):
        raise PipelineError("accepted doctrinal edition has no valid language")
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
    if not isinstance(included, list) or not included or any(not isinstance(item, Mapping) for item in included):
        raise PipelineError("doctrinal projection requires accepted retained members")
    member_set = source.get("source_kind") == "retained-member-set"
    retained_members: list[dict[str, Any]] = []
    if member_set:
        from ocd_kernel.library.acquisitions import source_member_set_bytes

        if (
            source.get("source_path") != acquisition.get("source_path")
            or source.get("source_bytes") != acquisition.get("source_bytes")
            or source.get("source_sha256") != acquisition.get("source_sha256")
        ):
            raise PipelineError("doctrinal accepted member-set source differs from acquisition")
        retained_path, retained_authority = _accepted_bound_file(
            base,
            {"path": source.get("source_path"), "bytes": source.get("source_bytes"), "sha256": source.get("source_sha256")},
            field="source.member_set",
        )
        if retained_path.read_bytes() != source_member_set_bytes(acquisition):
            raise PipelineError("doctrinal source-member-set manifest differs from acquisition")
        acquisition_members = acquisition.get("retained_files")
        if not isinstance(acquisition_members, list) or len(acquisition_members) < 2:
            raise PipelineError("doctrinal source-member-set acquisition has no complete member list")
        expected_included = []
        included_paths = [item.get("path") for item in included]
        if any(not isinstance(path, str) for path in included_paths) or len(set(included_paths)) != len(included_paths):
            raise PipelineError("doctrinal accepted retained member paths are invalid or repeated")
        for position, member in enumerate(acquisition_members, 1):
            if not isinstance(member, Mapping):
                raise PipelineError("doctrinal acquisition retained member is invalid")
            _, authority_member = _accepted_bound_file(
                base, member, field=f"acquisition.retained_files[{position - 1}]"
            )
            retained_members.append({"position": position, **authority_member})
            if member.get("path") in included_paths:
                expected_included.append({
                    key: member.get(key) for key in ("path", "bytes", "sha256", "scope")
                } | {"position": position})
        actual_included = [{key: item.get(key) for key in ("path", "bytes", "sha256", "scope", "position")} for item in included]
        if actual_included != expected_included:
            raise PipelineError("doctrinal accepted retained members differ from ordered acquisition selection")
        retained_sha256 = source["source_sha256"]
    else:
        if len(included) != 1:
            raise PipelineError("doctrinal projection requires exactly one accepted retained member")
        retained_path, retained_authority = _accepted_bound_file(
            base, included[0], field="scope.included_members[0]"
        )
        retained_sha256 = included[0]["sha256"]
    accounting_path, accounting_authority = _accepted_bound_file(
        base, source.get("accounting"), field="source.accounting"
    )
    try:
        accounting_document = json.loads(accounting_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"source.accounting is not readable JSON: {accounting_path}") from exc
    if not isinstance(accounting_document, Mapping):
        raise PipelineError("source.accounting must contain an object")
    source_profile = accounting_document.get("projection_profile")
    if source_profile is not None:
        from ocd_kernel.projection.categories.creeds_json_carrier import PROFILE
        if source_profile != PROFILE:
            raise PipelineError("unsupported accepted doctrinal projection profile")
    projection_context = _accepted_projection_context(accounting_document)
    declaration_context = accounting_document.get("projection_context", accounting_document)
    projection_context["source_tei_unit_bindings"] = declaration_context.get("source_tei_unit_bindings")
    if projection_context["available"] and projection_context["source_scope"] != scope.get("declared"):
        raise PipelineError("source.accounting projection scope does not bind accepted scope")
    document_kind = _accepted_kind(accounting_document, "document_kind", _DOCUMENT_KINDS)
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
    if member_set:
        authority["retained_members"] = retained_members
    return {
        "root": base,
        "acceptance": accepted,
        "acceptance_path": accepted_path,
        "identity": {key: identity[key] for key in _IDENTITY_KEYS},
        "edition": edition,
        "master_path": Path(edition.path).resolve(),
        "language": language,
        "representation_revision": revision["id"],
        "document_kind": document_kind,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "retained_sha256": retained_sha256,
        "source_logical_path": source_logical_path,
        "member_set": member_set,
        "retained_path": retained_path if projection_context["available"] else None,
        "source_context": projection_context,
        "source_profile": source_profile,
        "authority": authority,
    }


def project_accepted_doctrinal_documents(
    root: Path, *, acceptance_path: Path
) -> dict[str, Any]:
    """Project a promoted doctrinal document from validated authority."""

    metadata = _accepted_metadata(root, acceptance_path)
    if metadata["source_profile"] is not None:
        from ocd_kernel.projection.categories.creeds_json_carrier import project as project_tree
        projection = project_tree(root, acceptance_path=acceptance_path)
        projection["receipt"].update(
            authority=dict(metadata["authority"]),
            scope="tei-document; context derived from validated acceptance",
        )
        projection["authority"] = dict(metadata["authority"])
        return projection
    context = metadata["source_context"]
    kwargs: dict[str, Any] = {
        "identity": metadata["identity"],
        "language": metadata["language"],
        "representation_revision": metadata["representation_revision"],
        "edition_title": metadata["edition"].title,
        "document_kind": metadata["document_kind"],
        "source_url": metadata["source_url"],
        "source_sha256": metadata["source_sha256"],
        "retained_sha256": metadata["retained_sha256"],
    }
    if metadata["member_set"]:
        kwargs["source_logical_path"] = metadata["source_logical_path"]
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
            source_tei_unit_bindings=context["source_tei_unit_bindings"],
        )
    projection = project_doctrinal_document(metadata["master_path"], **kwargs)
    receipt = build_doctrinal_receipt(projection, identity=metadata["identity"])
    receipt["authority"] = dict(metadata["authority"])
    receipt["scope"] = "tei-document; context derived from validated acceptance"
    projection["receipt"] = receipt
    projection["authority"] = dict(metadata["authority"])
    return projection


def verify_accepted_doctrinal_documents(
    root: Path,
    *,
    acceptance_path: Path,
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted doctrinal rows without invoking the producer."""

    try:
        metadata = _accepted_metadata(root, acceptance_path)
        if receipt is None:
            return ["accepted doctrinal receipt is missing"]
        if not isinstance(receipt, Mapping):
            return ["accepted doctrinal receipt must be an object"]
        errors: list[str] = []
        if receipt.get("authority") != metadata["authority"]:
            errors.append("accepted authority bindings differ")
        if receipt.get("scope") != "tei-document; context derived from validated acceptance":
            errors.append("accepted scope label differs")
        if metadata["source_profile"] is not None:
            from ocd_kernel.projection.categories.creeds_json_carrier import verify as verify_tree
            document_receipt = dict(receipt)
            document_receipt.pop("authority", None)
            document_receipt.pop("scope", None)
            errors.extend(verify_tree(root, acceptance_path=acceptance_path, rows=rows, receipt=document_receipt))
            return errors
        context = metadata["source_context"]
        kwargs: dict[str, Any] = {
            "identity": metadata["identity"],
            "language": metadata["language"],
            "representation_revision": metadata["representation_revision"],
            "edition_title": metadata["edition"].title,
            "document_kind": metadata["document_kind"],
            "source_url": metadata["source_url"],
            "source_sha256": metadata["source_sha256"],
            "retained_sha256": metadata["retained_sha256"],
        }
        if metadata["member_set"]:
            kwargs["source_logical_path"] = metadata["source_logical_path"]
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
            source_tei_unit_bindings=context["source_tei_unit_bindings"],
            )
        document_receipt = dict(receipt)
        document_receipt.pop("authority", None)
        document_receipt.pop("scope", None)
        errors.extend(
            verify_doctrinal_document(
                metadata["master_path"], rows, document_receipt, **kwargs
            )
        )
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]

__all__ = ["project_doctrinal_document", "project_doctrinal", "project_document", "build_doctrinal_receipt", "verify_doctrinal_document", "check_doctrinal_document", "verify_document", "project_accepted_doctrinal_documents", "verify_accepted_doctrinal_documents", "MAPPING_VERSION", "RECEIPT_VERSION", "ASSEMBLER_VERSION", "UnsupportedStructure"]
