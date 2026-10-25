"""Source-bound catechism question and answer projection (PIPE-013A).

Questions, answers, subquestions, proofs, grouping, numbering, and locators
are intentionally separate values.  The verifier has its own lxml walk and
recomputes both the rows and the private receipt from the TEI bytes.
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
SCHEMA = ROOT / "schemas/v2/categories/catechisms.schema.json"
COMMON = ROOT / "schemas/v2/public-row.schema.json"
MAPPING_VERSION = "ocd-catechisms-mapping-v2"
RECEIPT_VERSION = "ocd-catechisms-receipt-v2"
ASSEMBLER_VERSION = "ocd-catechisms-assembler-v2"
_IDENTITY_KEYS = ("work_id", "textual_form_id", "edition_id")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_LANG_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_QUESTION_TYPES = {"question", "qa", "question-unit"}
_SUBQUESTION_TYPES = {"subquestion", "sub-question"}
_GROUP_TYPES = {"part", "chapter", "section", "group", "lord-day", "lords-day"}
_EXCLUDED_TYPES = {"title-page", "half-title-page", "copyright-page", "imprint", "colophon"}
_TEXT_PARTS = {"front", "body", "back"}
_INLINE = {"ref", "ptr", "hi", "foreign", "seg", "lb", "pb", "anchor", "note"}
_STRUCTURE = {"text", "front", "body", "back", "div", "head", "p", "ab", "list", "item", *_INLINE}
_HEADER = {"TEI", "teiHeader", "fileDesc", "titleStmt", "title", "publicationStmt", "publisher", "sourceDesc", "bibl", "idno", "ptr", "revisionDesc", "change", "list", "item", "p", "date", "editionStmt", "edition", "respStmt", "resp", "author", "availability", "licence", "distributor", "encodingDesc", "projectDesc", "desc", "ref", "note"}
_ATTRIBUTES = {
    "TEI": {XML_ID, XML_LANG}, "teiHeader": {XML_ID, XML_LANG}, "fileDesc": {XML_ID, XML_LANG}, "titleStmt": {XML_ID, XML_LANG},
    "title": {XML_ID, XML_LANG, "type"}, "publicationStmt": {XML_ID, XML_LANG}, "sourceDesc": {XML_ID, XML_LANG},
    "bibl": {XML_ID, XML_LANG, "type"}, "idno": {XML_ID, XML_LANG, "type"}, "ptr": {XML_ID, XML_LANG, "type", "target"},
    "revisionDesc": {XML_ID, XML_LANG}, "change": {XML_ID, XML_LANG, "when", "type"}, "editionStmt": {XML_ID, XML_LANG},
    "edition": {XML_ID, XML_LANG, "n", "type"}, "respStmt": {XML_ID, XML_LANG}, "resp": {XML_ID, XML_LANG, "type"},
    "author": {XML_ID, XML_LANG, "role"}, "availability": {XML_ID, XML_LANG, "status"}, "licence": {XML_ID, XML_LANG, "target"},
    "publisher": {XML_ID, XML_LANG}, "distributor": {XML_ID, XML_LANG}, "encodingDesc": {XML_ID, XML_LANG}, "projectDesc": {XML_ID, XML_LANG},
    "desc": {XML_ID, XML_LANG, "type"}, "date": {XML_ID, XML_LANG, "when"}, "text": {XML_ID, XML_LANG},
    "front": {XML_ID, XML_LANG}, "body": {XML_ID, XML_LANG}, "back": {XML_ID, XML_LANG},
    "div": {XML_ID, XML_LANG, "type", "n"}, "head": {XML_ID, XML_LANG, "type"}, "p": {XML_ID, XML_LANG, "type"}, "ab": {XML_ID, XML_LANG, "type"},
    "list": {XML_ID, XML_LANG, "type"}, "item": {XML_ID, XML_LANG, "n", "type"}, "ref": {XML_ID, XML_LANG, "type", "target", "cRef"},
    "note": {XML_ID, XML_LANG, "place", "n", "type"}, "hi": {XML_ID, XML_LANG, "rend", "type"},
    "foreign": {XML_ID, XML_LANG, "lang", "type"}, "seg": {XML_ID, XML_LANG, "type"},
    "lb": {XML_ID, XML_LANG, "break", "n"}, "pb": {XML_ID, XML_LANG, "n", "facs"}, "anchor": {XML_ID, XML_LANG, "type", "n"},
}


class UnsupportedStructure(PipelineError):
    """A visible source feature is outside the closed catechism mapping."""


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
        raise PipelineError(f"cannot read catechism TEI {path}: {exc}") from exc
    if b"<!doctype" in raw.lower() or b"<!entity" in raw.lower():
        raise UnsupportedStructure("unsupported-visible: DTD or entity declaration")
    try:
        root = ET.fromstring(raw, parser=ET.XMLParser(target=_RejectingBuilder()))
    except UnsupportedStructure:
        raise
    except ET.ParseError as exc:
        raise PipelineError(f"invalid catechism TEI: {exc}") from exc
    if root.tag != f"{{{TEI_NS}}}TEI":
        raise UnsupportedStructure("unsupported-visible: catechism TEI root required")
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
        allowed = _ATTRIBUTES.get(kind, {XML_ID, XML_LANG})
        for key in node.attrib:
            if key not in allowed:
                raise UnsupportedStructure(f"unsupported-visible: {kind}@{_attr_name(key)} at {paths[node]}")
        if kind == "availability" and node.get("status") not in {None, "restricted"}:
            raise UnsupportedStructure(f"unsupported-visible: availability@status at {paths[node]}")
        if kind == "ref" and node.get("target") and node.get("cRef"):
            raise UnsupportedStructure(f"unsupported-visible: ref has both target and cRef at {paths[node]}")


def _logical_source_path(value: Path | str) -> str:
    path = Path(value)
    try:
        # Keep the repository's logical path when ``raw`` is a junction to the
        # durable library.  ``resolve()`` would expose the physical D: path and
        # make a stable TEI source-path binding impossible on Windows.
        return path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError:
        return path.absolute().as_posix()


def _source_binding(root: ET.Element, context: Mapping[str, Any]) -> dict[str, str]:
    source_desc = [node for node in root.iter() if _local(node.tag) == "sourceDesc"]
    if len(source_desc) != 1:
        raise PipelineError("catechism TEI must contain exactly one sourceDesc")
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
    for key in _IDENTITY_KEYS:
        if ids.get(key) != context["identity"][key]:
            raise PipelineError(f"catechism TEI {key} mismatch")
    if not source_url:
        raise PipelineError("catechism TEI sourceDesc is missing source URL")
    if set(hashes) != {"source_sha256", "retained_sha256"}:
        raise PipelineError("catechism TEI sourceDesc is missing source hashes")
    for key in hashes:
        expected = context.get(key)
        if expected is not None and hashes[key] != _valid_sha(expected, key):
            raise PipelineError(f"catechism TEI {key} mismatch")
    expected_url = context.get("source_url")
    if expected_url is not None and source_url != expected_url:
        raise PipelineError("catechism TEI source URL mismatch")
    source_path = context.get("source_path")
    if source_path is not None:
        expected_path = context.get("source_logical_path") or _logical_source_path(source_path)
        if source_path_label != expected_path:
            raise PipelineError("catechism TEI source path mismatch")
        try:
            actual = _sha_bytes(Path(source_path).read_bytes())
        except OSError as exc:
            raise PipelineError(f"cannot read retained catechism source {source_path}: {exc}") from exc
        if actual != hashes["retained_sha256"]:
            raise PipelineError("catechism retained source hash does not match sourceDesc")
    binding = {"source_url": source_url, **hashes}
    if source_path_label:
        binding["source_path"] = source_path_label
    return binding


def _source_accounting(context: Mapping[str, Any], binding: Mapping[str, str], selection: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return explicit retained-source census data supplied by the fixture context.

    The TEI receipt is private, so it may carry the source selector and complete
    native-unit census needed to show why a bounded fixture selected its rows.
    The checker recomputes this structure from the caller context and verifies
    the retained file hash independently; source-specific tests additionally
    derive the census directly from the retained source format.
    """
    source_path = context.get("source_path")
    fields = ("source_selector", "source_scope", "source_unit_count", "source_selected_units", "source_census", "source_excerpt_sha256")
    if source_path is None and not any(context.get(field) is not None for field in fields):
        return None
    if source_path is None or any(context.get(field) is None for field in fields):
        raise PipelineError("catechism source accounting requires source path, selector, scope, census, selection, and excerpt hash")
    try:
        native_count = int(context["source_unit_count"])
    except (TypeError, ValueError) as exc:
        raise PipelineError("catechism source unit count must be an integer") from exc
    census = context["source_census"]
    selected_ids = [str(value) for value in context["source_selected_units"]]
    if not isinstance(census, Sequence) or isinstance(census, (str, bytes)):
        raise PipelineError("catechism source census must be a sequence")
    census_copy = [dict(item) if isinstance(item, Mapping) else item for item in census]
    if native_count != len(census_copy):
        raise PipelineError("catechism source census count mismatch")
    census_ids = [str(item.get("id")) for item in census_copy if isinstance(item, Mapping) and item.get("id") is not None]
    if len(census_ids) != native_count or len(set(census_ids)) != native_count:
        raise PipelineError("catechism source census identities must be unique")
    census_id_set = set(census_ids)
    if any(value not in census_id_set for value in selected_ids) or len(set(selected_ids)) != len(selected_ids):
        raise PipelineError("catechism source selection is not present in the census")
    native_selected_ids = [value for value in census_ids if value in set(selected_ids)]
    if selected_ids != native_selected_ids:
        raise PipelineError("catechism source selection does not follow native census order")
    excerpt_hash = _valid_sha(str(context["source_excerpt_sha256"]), "source_excerpt_sha256")
    excluded_ids = [value for value in census_ids if value not in set(selected_ids)]
    if selection["selected_units"] > len(selected_ids):
        raise PipelineError("catechism source selection is smaller than the TEI selection")
    selected_sub_ids = [str(value) for value in context.get("source_selected_subunits") or []]
    all_sub_ids = [str(sub.get("id")) for item in census_copy if isinstance(item, Mapping) for sub in item.get("subquestions", []) if isinstance(sub, Mapping) and sub.get("id") is not None]
    selected_sub_id_set = set(selected_sub_ids)
    if selected_sub_ids and any(value not in set(all_sub_ids) for value in selected_sub_ids):
        raise PipelineError("catechism source subquestion selection is not present in the census")
    if selected_sub_ids and len(set(selected_sub_ids)) != len(selected_sub_ids):
        raise PipelineError("catechism source subquestion selection is not unique")
    selected_native_sub_ids = [
        str(sub["id"])
        for item in census_copy
        if isinstance(item, Mapping) and str(item.get("id")) in set(selected_ids)
        for sub in item.get("subquestions", [])
        if isinstance(sub, Mapping) and sub.get("id") is not None
    ]
    native_selected_sub_ids = [value for value in selected_native_sub_ids if value in selected_sub_id_set]
    if selected_sub_ids != native_selected_sub_ids:
        raise PipelineError("catechism source subquestion selection does not follow native order")
    return {
        "source_path": binding.get("source_path") or _logical_source_path(source_path),
        "selector": json.loads(json.dumps(context["source_selector"], ensure_ascii=False)),
        "scope": str(context["source_scope"]),
        "source_excerpt_sha256": excerpt_hash,
        "native_unit_count": native_count,
        "selected_unit_ids": selected_ids,
        "excluded_unit_ids": excluded_ids,
        "selected_unit_count": len(selected_ids),
        "excluded_unit_count": len(excluded_ids),
        "selected_subunit_ids": selected_sub_ids,
        "excluded_subunit_ids": [value for value in all_sub_ids if value not in set(selected_sub_ids)] if all_sub_ids else [],
        "census": census_copy,
    }


def _text_parts(root: ET.Element) -> list[ET.Element]:
    texts = [node for node in list(root) if _local(node.tag) == "text"]
    if len(texts) != 1:
        raise UnsupportedStructure("unsupported-visible: catechism requires one text element")
    parts = [node for node in list(texts[0]) if _local(node.tag) in _TEXT_PARTS]
    if not parts:
        raise UnsupportedStructure("unsupported-visible: catechism text has no front/body/back")
    if any(_local(node.tag) not in _TEXT_PARTS for node in list(texts[0])):
        raise UnsupportedStructure("unsupported-visible: text contains an unaccounted child")
    return parts


def _render(node: ET.Element, *, omit_notes: bool = False) -> str:
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


def _check_inline(node: ET.Element, paths: Mapping[ET.Element, str]) -> None:
    for child in list(node):
        if _local(child.tag) not in _INLINE:
            raise UnsupportedStructure(f"unsupported-visible: catechism inline {_local(child.tag)} at {paths[child]}")
        _check_inline(child, paths)


def _number(value: str, path: str) -> tuple[int, str]:
    match = re.fullmatch(r"([0-9]+)([A-Za-z]*)", _norm(value))
    if not match or int(match.group(1)) < 1:
        raise UnsupportedStructure(f"unsupported-visible: bad catechism number {_norm(value)!r} at {path}")
    return int(match.group(1)), match.group(2).lower()


def _proofs(list_node: ET.Element | None, paths: Mapping[ET.Element, str]) -> list[dict[str, Any]]:
    if list_node is None:
        return []
    result: list[dict[str, Any]] = []
    for item in list(list_node):
        if _local(item.tag) != "item" or not item.get("n"):
            raise UnsupportedStructure(f"unsupported-visible: proof item needs @n at {paths[item]}")
        number, suffix = _number(item.get("n", ""), paths[item])
        if suffix:
            raise UnsupportedStructure(f"unsupported-visible: proof number must be numeric at {paths[item]}")
        refs = [node for node in item.iter() if _local(node.tag) == "ref"]
        if not refs:
            raise UnsupportedStructure(f"unsupported-visible: proof {number} has no ref at {paths[item]}")
        parsed: list[dict[str, Any]] = []
        for ref in refs:
            target = _norm(ref.get("target") or ref.get("cRef"))
            raw = _render(ref)
            if not target or target.startswith("#") or not raw:
                raise UnsupportedStructure(f"unsupported-visible: invalid proof ref at {paths[ref]}")
            parsed.append({"raw": raw, "osis": [target]})
        result.append({"id": number, "references": parsed})
    ids = [item["id"] for item in result]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise UnsupportedStructure(f"unsupported-visible: proof numbering is not ordered at {paths[list_node]}")
    return result


def _locator(unit: ET.Element, parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str]) -> tuple[dict[str, Any], str | None]:
    part = next((node for node in [unit, *_ancestors(unit, parents)] if _local(node.tag) in _TEXT_PARTS), None)
    if part is None:
        raise UnsupportedStructure(f"unsupported-visible: catechism unit has no text part at {paths[unit]}")
    groups = [node for node in reversed(_ancestors(unit, parents)) if _local(node.tag) == "div" and node.get("type") in _GROUP_TYPES]
    divisions: list[dict[str, Any]] = []
    for division in groups:
        parent = parents.get(division)
        siblings = [child for child in (list(parent) if parent is not None else []) if _local(child.tag) == "div" and child.get("type") in _GROUP_TYPES]
        divisions.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "number": _norm(division.get("n")) or None, "titles": [_render(child) for child in list(division) if _local(child.tag) == "head" and _render(child)]})
    group = None
    if groups:
        heading = next((child for child in list(groups[-1]) if _local(child.tag) == "head"), None)
        group = _render(heading) if heading is not None else None
    return ({"kind": "question", "text_part": _local(part.tag), "part_titles": [_render(child) for child in list(part) if _local(child.tag) == "head" and _render(child)], "divisions": divisions, "question": _norm(unit.get("n")) or None, "source_order": 0}, group)


def _subquestions(unit: ET.Element, paths: Mapping[ET.Element, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous: tuple[int, str] | None = None
    for child in list(unit):
        if _local(child.tag) != "div" or child.get("type") not in _SUBQUESTION_TYPES:
            continue
        item_id = _norm(child.get("n"))
        current = _number(item_id, paths[child])
        if previous is not None and current <= previous:
            raise UnsupportedStructure(f"unsupported-visible: subquestion numbering is not ordered at {paths[child]}")
        previous = current
        questions = [node for node in list(child) if _local(node.tag) in {"head", "p"} and node.get("type") == "question"]
        answers = [node for node in list(child) if _local(node.tag) in {"p", "ab"} and node.get("type") == "answer"]
        proof_lists = [node for node in list(child) if _local(node.tag) == "list" and node.get("type") == "proofs"]
        if len(questions) != 1 or len(answers) != 1 or len(proof_lists) > 1:
            raise UnsupportedStructure(f"unsupported-visible: malformed subquestion {item_id} at {paths[child]}")
        _check_inline(questions[0], paths)
        _check_inline(answers[0], paths)
        result.append({"item_id": item_id, "question": _render(questions[0]), "answer": _render(answers[0], omit_notes=True), "proofs": _proofs(proof_lists[0] if proof_lists else None, paths)})
    return result


def _row(root: ET.Element, unit: ET.Element, identity: Mapping[str, str], sequence: int, context: Mapping[str, Any], parents: Mapping[ET.Element, ET.Element], paths: Mapping[ET.Element, str], source_order: int) -> dict[str, Any]:
    item_id = _norm(unit.get("n")) or None
    number = _number(item_id, paths[unit])[0] if item_id is not None else source_order
    record_suffix = item_id if item_id is not None else "occurrence-" + _sha_text(unit.get(XML_ID) or paths[unit])[:20]
    questions = [node for node in list(unit) if _local(node.tag) in {"head", "p"} and node.get("type") == "question"]
    answers = [node for node in list(unit) if _local(node.tag) in {"p", "ab"} and node.get("type") == "answer"]
    proof_lists = [node for node in list(unit) if _local(node.tag) == "list" and node.get("type") == "proofs"]
    if len(questions) != 1 or len(answers) != 1 or len(proof_lists) > 1:
        raise UnsupportedStructure(f"unsupported-visible: question {item_id} needs one question, answer, and proof list at {paths[unit]}")
    _check_inline(questions[0], paths)
    _check_inline(answers[0], paths)
    question = _render(questions[0])
    answer = _render(answers[0], omit_notes=True)
    if not question or not answer:
        raise UnsupportedStructure(f"unsupported-visible: empty question or answer at {paths[unit]}")
    proofs = _proofs(proof_lists[0] if proof_lists else None, paths)
    locator, group = _locator(unit, parents, paths)
    locator["source_order"] = source_order
    subs = _subquestions(unit, paths)
    return {**{key: identity[key] for key in _IDENTITY_KEYS}, "record_id": f"{identity['edition_id']}:question-{record_suffix}", "sequence": sequence, "category": "catechisms", "language": context["language"], "representation_revision": context["representation_revision"], "text": f"Q: {question} A: {answer}", "item_id": item_id, "sort_key": number, "question": question, "answer": answer, "answer_with_proofs": _render(answers[0]) if proofs else None, "proofs": proofs, "group": group, "sub_questions": subs or None, "locator": locator, "provenance": {"edition_title": context["edition_title"]}}


def _scope(parts: Sequence[ET.Element], scope_id: str | None) -> ET.Element | None:
    if scope_id is None:
        return None
    found = [node for part in parts for node in part.iter() if node.get(XML_ID) == scope_id]
    if len(found) != 1 or _local(found[0].tag) != "div":
        raise UnsupportedStructure(f"unsupported-visible: catechism scope is not one div: {scope_id}")
    return found[0]


def _units(parts: Sequence[ET.Element], scope: ET.Element | None, parents: Mapping[ET.Element, ET.Element]) -> tuple[list[ET.Element], list[ET.Element]]:
    all_units: list[ET.Element] = []
    for part in parts:
        for node in part.iter():
            if _local(node.tag) != "div" or node.get("type") not in _QUESTION_TYPES:
                continue
            ancestors = _ancestors(node, parents)
            if any(parent.get("type") in _QUESTION_TYPES for parent in ancestors):
                continue
            if any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *ancestors]):
                continue
            all_units.append(node)
    selected = [node for node in all_units if scope is None or node is scope or scope in _ancestors(node, parents)]
    return all_units, selected


def _inventory(root: ET.Element, parts: Sequence[ET.Element], all_units: Sequence[ET.Element], selected: Sequence[ET.Element], paths: Mapping[ET.Element, str], parents: Mapping[ET.Element, ET.Element]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text_nodes = {node for part in parts for node in part.iter()}
    selected_nodes = {node for unit in selected for node in unit.iter()}
    outside_nodes = {node for unit in all_units if unit not in selected for node in unit.iter()}
    excluded_paratext = {node for part in parts for node in part.iter() if any(ancestor.get("type") in _EXCLUDED_TYPES for ancestor in [node, *_ancestors(node, parents)])}
    group_heads = {child for unit in selected for ancestor in _ancestors(unit, parents) if _local(ancestor.tag) == "div" and ancestor.get("type") in _GROUP_TYPES for child in list(ancestor) if _local(child.tag) == "head"}
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
        elif node in group_heads:
            disposition = "locator-heading"
        elif kind == "head":
            disposition = "excluded-heading"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"unsupported-visible: unassigned catechism element at {paths[node]}")
        inventory.append({"ordinal": ordinal, "tei_path": paths[node], "namespace": TEI_NS, "tag": kind, "disposition": disposition, "attributes": {_attr_name(key): value for key, value in sorted(node.attrib.items())}, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    for unit in all_units:
        if unit not in selected:
            exclusions.append({"tei_path": paths[unit], "reason": "outside-scope", "xml_id": unit.get(XML_ID), "item_id": unit.get("n")})
    for node in sorted(excluded_paratext, key=lambda item: paths[item]):
        if node.get("type") in _EXCLUDED_TYPES:
            exclusions.append({"tei_path": paths[node], "reason": "excluded-paratext", "xml_id": node.get(XML_ID)})
    return inventory, exclusions


def _warnings(root: ET.Element, selected: Sequence[ET.Element], paths: Mapping[ET.Element, str]) -> list[dict[str, str]]:
    selected_nodes = {node for unit in selected for node in unit.iter()}
    reasons = {"ref": "source-reference-preserved", "note": "note-extracted", "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text", "seg": "segmentation-to-plain-text", "lb": "line-break-to-space", "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted"}
    return [{"tei_path": paths[node], "reason": reasons[_local(node.tag)]} for node in root.iter() if node in selected_nodes and _local(node.tag) in reasons]


def _validator() -> Any:
    try:
        import jsonschema
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        common = json.loads(COMMON.read_text(encoding="utf-8"))
        native = json.loads((ROOT / "schemas/v2/native-content.schema.json").read_text(encoding="utf-8"))
        registry = Registry().with_resource(common["$id"], Resource.from_contents(common, default_specification=DRAFT202012))
        registry = registry.with_resource(native["$id"], Resource.from_contents(native, default_specification=DRAFT202012))
        validator = projection_validator(schema, registry=registry)
        validator.check_schema(schema)
        return validator
    except (ImportError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise PipelineError(f"invalid catechism schema package: {exc}") from exc


def _validate_rows(rows: Sequence[Mapping[str, Any]]) -> None:
    validator = _validator()
    for index, row in enumerate(rows, 1):
        errors = sorted(validator.iter_errors(row), key=lambda error: list(error.path))
        if errors:
            raise PipelineError(f"invalid catechism public row {row.get('record_id', f'row-{index}')}: {errors[0].message}")


def project_catechism_document(tei_path: Path, *, identity: Mapping[str, str], language: str = "en", representation_revision: str = "tei-v2", edition_title: str = "", source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, source_path: Path | None = None, source_logical_path: str | None = None, source_selector: Mapping[str, Any] | None = None, source_scope: str | None = None, source_unit_count: int | None = None, source_selected_units: Sequence[str] | None = None, source_selected_subunits: Sequence[str] | None = None, source_census: Sequence[Mapping[str, Any]] | None = None, source_excerpt_sha256: str | None = None, scope_id: str | None = None) -> dict[str, Any]:
    identity_value = _identity(identity)
    if not isinstance(language, str) or not _LANG_RE.fullmatch(language):
        raise PipelineError("invalid catechism language")
    if not isinstance(representation_revision, str) or not representation_revision.strip():
        raise PipelineError("missing catechism representation revision")
    if not isinstance(edition_title, str) or not edition_title.strip():
        raise PipelineError("missing catechism edition title")
    context = {"identity": identity_value, "language": language, "representation_revision": representation_revision, "edition_title": edition_title, "source_url": source_url, "source_sha256": source_sha256, "retained_sha256": retained_sha256, "source_path": source_path, "source_logical_path": source_logical_path, "source_selector": source_selector, "source_scope": source_scope, "source_unit_count": source_unit_count, "source_selected_units": source_selected_units, "source_selected_subunits": source_selected_subunits, "source_census": source_census, "source_excerpt_sha256": source_excerpt_sha256}
    root, raw = _read_root(Path(tei_path))
    paths = _paths(root)
    parents = _parents(root)
    _validate_attributes(root, paths)
    binding = _source_binding(root, context)
    parts = _text_parts(root)
    scope = _scope(parts, scope_id)
    all_units, selected = _units(parts, scope, parents)
    if not selected:
        raise UnsupportedStructure("unsupported-visible: catechism contains no selected question units")
    global_order = {node: index for index, node in enumerate(all_units, 1)}
    rows: list[dict[str, Any]] = []
    previous: tuple[int, str] | None = None
    seen: set[str] = set()
    for sequence, unit in enumerate(selected, 1):
        if unit.get("n") is not None:
            current = _number(unit.get("n") or "", paths[unit])
            if previous is not None and current <= previous:
                raise UnsupportedStructure("unsupported-visible: catechism question numbering is not strictly increasing")
            previous = current
        row = _row(root, unit, identity_value, sequence, context, parents, paths, global_order[unit])
        if row["record_id"] in seen:
            raise UnsupportedStructure(f"unsupported-visible: duplicate catechism question {row['item_id']}")
        seen.add(row["record_id"])
        rows.append(row)
    inventory, exclusions = _inventory(root, parts, all_units, selected, paths, parents)
    warnings = _warnings(root, selected, paths)
    anchors = [{"record_id": row["record_id"], "tei_path": paths[unit], "xml_id": unit.get(XML_ID), "source_order": global_order[unit], "item_id": row["item_id"], "proof_count": len(row["proofs"]), "subquestion_count": len(row["sub_questions"] or []), "text_sha256": _sha_text(row["text"])} for row, unit in zip(rows, selected)]
    selection = {"available_units": len(all_units), "selected_units": len(selected), "excluded_units": len(all_units) - len(selected), "scope_id": scope_id}
    source_accounting = _source_accounting(context, binding, selection)
    _validate_rows(rows)
    return {"rows": rows, "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "master_sha256": _sha_bytes(raw), "scope_id": scope_id, "mapping_version": MAPPING_VERSION, "source_binding": binding, "schema_sha256": _sha_bytes(SCHEMA.read_bytes()), "common_schema_sha256": _sha_bytes(COMMON.read_bytes()), "selection": selection, "source_accounting": source_accounting}


project_catechism = project_catechism_document
project_document = project_catechism_document


def build_catechism_receipt(projection: Mapping[str, Any], *, identity: Mapping[str, str]) -> dict[str, Any]:
    rows = projection.get("rows")
    if not isinstance(rows, list):
        raise PipelineError("catechism projection rows must be a list")
    return {"schema_version": "ocd-catechism-receipt-v2", "receipt_version": RECEIPT_VERSION, "mapping_version": projection.get("mapping_version", MAPPING_VERSION), "assembler_version": ASSEMBLER_VERSION, "category": "catechisms", "identity": dict(identity), "master_sha256": projection.get("master_sha256"), "schema_sha256": projection.get("schema_sha256", _sha_bytes(SCHEMA.read_bytes())), "common_schema_sha256": projection.get("common_schema_sha256", _sha_bytes(COMMON.read_bytes())), "scope_id": projection.get("scope_id"), "source_binding": dict(projection.get("source_binding", {})), "source_accounting": projection.get("source_accounting"), "selection": dict(projection.get("selection", {})), "output_sha256": _sha_bytes(_canonical(rows)), "row_count": len(rows), "anchors": list(projection.get("anchors", [])), "inventory": list(projection.get("inventory", [])), "warnings": list(projection.get("warnings", [])), "exclusions": list(projection.get("exclusions", [])), "unsupported": list(projection.get("unsupported", [])), "independent_check": {"status": "pending", "errors": []}}


def _checker_parse(path: Path) -> tuple[Any, bytes]:
    from lxml import etree
    try:
        raw = path.read_bytes()
        root = etree.fromstring(raw, parser=etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, remove_pis=False))
    except (OSError, etree.XMLSyntaxError) as exc:
        raise PipelineError(f"checker: cannot parse catechism TEI: {exc}") from exc
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


def _checker_source_binding(root: Any, identity: Mapping[str, str]) -> dict[str, str]:
    from lxml import etree
    source = root.xpath("./tei:teiHeader/tei:fileDesc/tei:sourceDesc", namespaces={"tei": TEI_NS})
    if len(source) != 1:
        raise UnsupportedStructure("checker: exactly one sourceDesc is required")
    found: dict[str, str] = {}
    hashes: dict[str, str] = {}
    source_url = ""
    source_path_label = ""
    for node in source[0].iter():
        kind = etree.QName(node).localname
        if kind == "idno":
            value = _norm("".join(node.itertext()))
            typ = (node.get("type") or "").lower().replace("-", "_")
            if typ in _IDENTITY_KEYS:
                found[typ] = value
            elif typ in {"source_sha256", "origin_sha256"}:
                hashes["source_sha256"] = _valid_sha(value, "source_sha256")
            elif typ in {"retained_sha256", "archive_sha256", "sha256"}:
                hashes["retained_sha256"] = _valid_sha(value, "retained_sha256")
        elif kind in {"ptr", "ref"} and not source_url and node.get("target"):
            source_url = _norm(node.get("target"))
        elif kind == "note" and (node.get("type") or "").lower().replace("-", "_") in {"source_path", "source_location"}:
            source_path_label = _norm("".join(node.itertext()))
    if any(found.get(key) != identity[key] for key in _IDENTITY_KEYS):
        raise UnsupportedStructure("checker: source identity mismatch")
    if not source_url or set(hashes) != {"source_sha256", "retained_sha256"}:
        raise UnsupportedStructure("checker: incomplete source identity binding")
    binding = {"source_url": source_url, **hashes}
    if source_path_label:
        binding["source_path"] = source_path_label
    return binding


def _checker_proofs(list_node: Any, paths: Mapping[Any, str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in list_node.xpath("./tei:item", namespaces={"tei": TEI_NS}):
        match = re.fullmatch(r"([0-9]+)", _norm(item.get("n")))
        if not match or int(match.group(1)) < 1:
            raise UnsupportedStructure(f"checker: invalid proof number at {paths[item]}")
        refs = item.xpath(".//tei:ref", namespaces={"tei": TEI_NS})
        if not refs:
            raise UnsupportedStructure(f"checker: proof has no ref at {paths[item]}")
        parsed: list[dict[str, Any]] = []
        for ref in refs:
            target = _norm(ref.get("target") or ref.get("cRef"))
            text = _checker_text(ref)
            if not target or target.startswith("#") or not text:
                raise UnsupportedStructure(f"checker: invalid proof reference at {paths[ref]}")
            parsed.append({"raw": text, "osis": [target]})
        result.append({"id": int(match.group(1)), "references": parsed})
    ids = [item["id"] for item in result]
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise UnsupportedStructure("checker: proof numbering is not ordered")
    return result


def _checker_locator(unit: Any, paths: Mapping[Any, str]) -> tuple[dict[str, Any], str | None]:
    from lxml import etree
    part = next((node for node in [unit, *list(unit.iterancestors())] if etree.QName(node).localname in _TEXT_PARTS), None)
    if part is None:
        raise UnsupportedStructure(f"checker: question has no text part at {paths[unit]}")
    groups = [node for node in reversed(list(unit.iterancestors())) if etree.QName(node).localname == "div" and node.get("type") in _GROUP_TYPES]
    divisions: list[dict[str, Any]] = []
    for division in groups:
        parent = division.getparent()
        siblings = [child for child in (parent if parent is not None else []) if etree.QName(child).localname == "div" and child.get("type") in _GROUP_TYPES]
        divisions.append({"order": siblings.index(division) + 1 if division in siblings else 1, "type": division.get("type"), "number": _norm(division.get("n")) or None, "titles": [_checker_text(child) for child in division if etree.QName(child).localname == "head" and _checker_text(child)]})
    group = None
    if groups:
        heading = next((child for child in groups[-1] if etree.QName(child).localname == "head"), None)
        group = _checker_text(heading) if heading is not None else None
    return ({"kind": "question", "text_part": etree.QName(part).localname, "part_titles": [_checker_text(child) for child in part if etree.QName(child).localname == "head" and _checker_text(child)], "divisions": divisions, "question": _norm(unit.get("n")) or None, "source_order": 0}, group)


def _checker_rows(root: Any, identity: Mapping[str, str], language: str, revision: str, title: str, scope_id: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], dict[str, int]]:
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
    all_units: list[Any] = []
    for part in parts:
        for node in part.xpath(".//t:div", namespaces=ns):
            if node.get("type") not in _QUESTION_TYPES:
                continue
            ancestors = list(node.iterancestors())
            if any(parent.get("type") in _QUESTION_TYPES for parent in ancestors):
                continue
            if any(parent.get("type") in _EXCLUDED_TYPES for parent in [node, *ancestors]):
                continue
            all_units.append(node)
    selected = [node for node in all_units if scope is None or node is scope or scope in list(node.iterancestors())]
    if not selected:
        raise UnsupportedStructure("checker: no selected question units")
    paths = _checker_paths(root)
    global_order = {id(node): index for index, node in enumerate(all_units, 1)}
    rows: list[dict[str, Any]] = []
    previous: tuple[int, str] | None = None
    for sequence, unit in enumerate(selected, 1):
        item_id = _norm(unit.get("n")) or None
        match = re.fullmatch(r"([0-9]+)([A-Za-z]*)", item_id) if item_id is not None else None
        if unit.get("n") is not None:
            if not match or int(match.group(1)) < 1:
                raise UnsupportedStructure(f"checker: invalid question number at {paths[unit]}")
            current = (int(match.group(1)), match.group(2).lower())
            if previous is not None and current <= previous:
                raise UnsupportedStructure("checker: question numbering is not ordered")
            previous = current
        record_suffix = item_id if item_id is not None else "occurrence-" + hashlib.sha256((unit.get(XML_ID) or paths[unit]).encode("utf-8")).hexdigest()[:20]
        questions = [child for child in unit if etree.QName(child).localname in {"head", "p"} and child.get("type") == "question"]
        answers = [child for child in unit if etree.QName(child).localname in {"p", "ab"} and child.get("type") == "answer"]
        proof_lists = [child for child in unit if etree.QName(child).localname == "list" and child.get("type") == "proofs"]
        if len(questions) != 1 or len(answers) != 1 or len(proof_lists) > 1:
            raise UnsupportedStructure(f"checker: malformed question at {paths[unit]}")
        question = _checker_text(questions[0])
        answer = _checker_text(answers[0], omit_notes=True)
        proofs = _checker_proofs(proof_lists[0], paths) if proof_lists else []
        subs: list[dict[str, Any]] = []
        sub_previous: tuple[int, str] | None = None
        for child in unit:
            if etree.QName(child).localname != "div" or child.get("type") not in _SUBQUESTION_TYPES:
                continue
            sub_id = _norm(child.get("n"))
            sub_match = re.fullmatch(r"([0-9]+)([A-Za-z]*)", sub_id)
            if not sub_match:
                raise UnsupportedStructure(f"checker: invalid subquestion number at {paths[child]}")
            sub_current = (int(sub_match.group(1)), sub_match.group(2).lower())
            if sub_previous is not None and sub_current <= sub_previous:
                raise UnsupportedStructure("checker: subquestion numbering is not ordered")
            sub_previous = sub_current
            sq = [item for item in child if etree.QName(item).localname in {"head", "p"} and item.get("type") == "question"]
            sa = [item for item in child if etree.QName(item).localname in {"p", "ab"} and item.get("type") == "answer"]
            sl = [item for item in child if etree.QName(item).localname == "list" and item.get("type") == "proofs"]
            if len(sq) != 1 or len(sa) != 1 or len(sl) > 1:
                raise UnsupportedStructure(f"checker: malformed subquestion at {paths[child]}")
            subs.append({"item_id": sub_id, "question": _checker_text(sq[0]), "answer": _checker_text(sa[0], omit_notes=True), "proofs": _checker_proofs(sl[0], paths) if sl else []})
        locator, group = _checker_locator(unit, paths)
        locator["source_order"] = global_order[id(unit)]
        rows.append({**{key: identity[key] for key in _IDENTITY_KEYS}, "record_id": f"{identity['edition_id']}:question-{record_suffix}", "sequence": sequence, "category": "catechisms", "language": language, "representation_revision": revision, "text": f"Q: {question} A: {answer}", "item_id": item_id, "sort_key": int(match.group(1)) if match else global_order[id(unit)], "question": question, "answer": answer, "answer_with_proofs": _checker_text(answers[0]) if proofs else None, "proofs": proofs, "group": group, "sub_questions": subs or None, "locator": locator, "provenance": {"edition_title": title}})
    selected_nodes = {node for unit in selected for node in unit.iter()}
    outside_nodes = {node for unit in all_units if unit not in selected for node in unit.iter()}
    text_nodes = {node for part in parts for node in part.iter()}
    group_heads = {child for unit in selected for ancestor in unit.iterancestors() if etree.QName(ancestor).localname == "div" and ancestor.get("type") in _GROUP_TYPES for child in ancestor if etree.QName(child).localname == "head"}
    inventory: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for ordinal, node in enumerate(root.iter(), 1):
        qname = etree.QName(node)
        kind = qname.localname
        ancestors = list(node.iterancestors())
        if node not in text_nodes:
            disposition = "private-header"
        elif any(ancestor.get("type") in _EXCLUDED_TYPES for ancestor in [node, *ancestors]):
            disposition = "excluded-paratext"
        elif node in selected_nodes:
            disposition = "row-content"
        elif node in outside_nodes:
            disposition = "outside-scope"
        elif node in group_heads:
            disposition = "locator-heading"
        elif kind == "head":
            disposition = "excluded-heading"
        elif kind in _STRUCTURE:
            disposition = "structure"
        else:
            raise UnsupportedStructure(f"checker: unassigned element at {paths[node]}")
        attrs = {"xml:id" if key == XML_ID else "xml:lang" if key == XML_LANG else (key.rsplit("}", 1)[-1] if key.startswith("{") else key): value for key, value in sorted(node.attrib.items())}
        inventory.append({"ordinal": ordinal, "tei_path": paths[node], "namespace": qname.namespace or "", "tag": kind, "disposition": disposition, "attributes": attrs, "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or "")})
    for unit in all_units:
        if unit not in selected:
            exclusions.append({"tei_path": paths[unit], "reason": "outside-scope", "xml_id": unit.get(XML_ID), "item_id": unit.get("n")})
    for node in text_nodes:
        if node.get("type") in _EXCLUDED_TYPES:
            exclusions.append({"tei_path": paths[node], "reason": "excluded-paratext", "xml_id": node.get(XML_ID)})
    reasons = {"ref": "source-reference-preserved", "note": "note-extracted", "hi": "styling-to-plain-text", "foreign": "language-span-to-plain-text", "seg": "segmentation-to-plain-text", "lb": "line-break-to-space", "pb": "milestone-omitted", "anchor": "milestone-omitted", "ptr": "milestone-omitted"}
    warnings = [{"tei_path": paths[node], "reason": reasons[etree.QName(node).localname]} for node in root.iter() if node in selected_nodes and etree.QName(node).localname in reasons]
    anchors = [{"record_id": row["record_id"], "tei_path": paths[unit], "xml_id": unit.get(XML_ID), "source_order": global_order[id(unit)], "item_id": row["item_id"], "proof_count": len(row["proofs"]), "subquestion_count": len(row["sub_questions"] or []), "text_sha256": _sha_text(row["text"])} for row, unit in zip(rows, selected)]
    return rows, anchors, inventory, exclusions, warnings, {"available_units": len(all_units), "selected_units": len(selected), "excluded_units": len(all_units) - len(selected), "scope_id": scope_id}


def verify_catechism(tei_path: Path, rows: Sequence[Mapping[str, Any]] | Mapping[str, Any], receipt: Mapping[str, Any] | None = None, *, identity: Mapping[str, str], language: str = "en", representation_revision: str = "tei-v2", edition_title: str = "", source_url: str | None = None, source_sha256: str | None = None, retained_sha256: str | None = None, source_path: Path | None = None, source_logical_path: str | None = None, source_selector: Mapping[str, Any] | None = None, source_scope: str | None = None, source_unit_count: int | None = None, source_selected_units: Sequence[str] | None = None, source_selected_subunits: Sequence[str] | None = None, source_census: Sequence[Mapping[str, Any]] | None = None, source_excerpt_sha256: str | None = None, scope_id: str | None = None) -> list[str]:
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
        if not _LANG_RE.fullmatch(language) or not representation_revision.strip() or not edition_title.strip():
            raise PipelineError("checker: invalid projection context")
        root, raw = _checker_parse(Path(tei_path))
        paths = _checker_paths(root)
        from lxml import etree
        for node in root.iter():
            qname = etree.QName(node)
            if qname.namespace != TEI_NS or (qname.localname not in _HEADER and qname.localname not in _STRUCTURE):
                raise UnsupportedStructure(f"checker: unsupported element at {paths[node]}")
            allowed = _ATTRIBUTES.get(qname.localname, {XML_ID, XML_LANG})
            for key in node.attrib:
                if key not in allowed:
                    raise UnsupportedStructure(f"checker: unsupported attribute at {paths[node]}")
            if qname.localname == "availability" and node.get("status") not in {None, "restricted"}:
                raise UnsupportedStructure(f"checker: unsupported availability status at {paths[node]}")
        binding = _checker_source_binding(root, identity_value)
        if source_url is not None and binding["source_url"] != source_url:
            raise PipelineError("checker: source URL mismatch")
        if source_sha256 is not None and binding["source_sha256"] != _valid_sha(source_sha256, "source_sha256"):
            raise PipelineError("checker: source_sha256 mismatch")
        if retained_sha256 is not None and binding["retained_sha256"] != _valid_sha(retained_sha256, "retained_sha256"):
            raise PipelineError("checker: retained_sha256 mismatch")
        context = {"identity": identity_value, "source_url": source_url, "source_sha256": source_sha256, "retained_sha256": retained_sha256, "source_path": source_path, "source_logical_path": source_logical_path, "source_selector": source_selector, "source_scope": source_scope, "source_unit_count": source_unit_count, "source_selected_units": source_selected_units, "source_selected_subunits": source_selected_subunits, "source_census": source_census, "source_excerpt_sha256": source_excerpt_sha256}
        if source_path is not None:
            expected_path = source_logical_path or _logical_source_path(source_path)
            if binding.get("source_path") != expected_path:
                raise PipelineError("checker: source path mismatch")
            if _sha_bytes(Path(source_path).read_bytes()) != binding["retained_sha256"]:
                raise PipelineError("checker: retained source hash mismatch")
        expected_rows, anchors, inventory, exclusions, warnings, selection = _checker_rows(root, identity_value, language, representation_revision, edition_title, scope_id)
        source_accounting = _source_accounting(context, binding, selection)
        _validate_rows(expected_rows)
    except (PipelineError, OSError, ValueError, TypeError, KeyError) as exc:
        return [str(exc)]
    errors: list[str] = []
    if not isinstance(provided, Sequence) or isinstance(provided, (str, bytes)):
        errors.append("catechism rows must be a sequence")
    elif list(provided) != expected_rows:
        errors.append("catechism rows do not match independent TEI traversal")
    if receipt is None:
        errors.append("catechism receipt is missing")
        return errors
    if not isinstance(receipt, Mapping):
        return errors + ["catechism receipt must be an object"]
    expected_receipt = {"schema_version": "ocd-catechism-receipt-v2", "receipt_version": RECEIPT_VERSION, "mapping_version": MAPPING_VERSION, "assembler_version": ASSEMBLER_VERSION, "category": "catechisms", "identity": identity_value, "master_sha256": _sha_bytes(raw), "schema_sha256": _sha_bytes(SCHEMA.read_bytes()), "common_schema_sha256": _sha_bytes(COMMON.read_bytes()), "scope_id": scope_id, "source_binding": binding, "source_accounting": source_accounting, "selection": selection, "output_sha256": _sha_bytes(_canonical(expected_rows)), "row_count": len(expected_rows), "anchors": anchors, "inventory": inventory, "warnings": warnings, "exclusions": exclusions, "unsupported": [], "independent_check": {"status": "pending", "errors": []}}
    if set(receipt) != set(expected_receipt):
        errors.append("catechism receipt fields differ")
    for key, wanted in expected_receipt.items():
        if receipt.get(key) != wanted:
            errors.append(f"catechism receipt {key} mismatch")
    if isinstance(provided, Sequence) and not isinstance(provided, (str, bytes)):
        try:
            _validate_rows(provided)  # type: ignore[arg-type]
        except PipelineError as exc:
            errors.append(str(exc))
    return errors


check_catechism = verify_catechism
verify_document = verify_catechism


def _accepted_bound_file(
    root: Path, binding: Mapping[str, Any], *, field: str
) -> tuple[Path, dict[str, str]]:
    """Resolve and independently check one acceptance evidence binding."""

    from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path
    from ocd_kernel.library._common import ensure_relative_path, sha256_file

    if not isinstance(binding, Mapping):
        raise PipelineError(f"{field} must be an object")
    reference = binding.get("path")
    if not isinstance(reference, str):
        raise PipelineError(f"{field}.path must be a string")
    try:
        normalized = ensure_relative_path(reference, field=f"{field}.path").as_posix()
        path = resolve_repo_path(root, normalized)
    except (PipelineError, StorageTopologyError) as exc:
        raise PipelineError(f"cannot resolve {field}: {reference}") from exc
    if not path.is_file():
        raise PipelineError(f"{field} does not resolve to a file: {reference}")
    expected_bytes = binding.get("bytes")
    expected_sha256 = binding.get("sha256")
    if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool):
        raise PipelineError(f"{field}.bytes is invalid")
    if not isinstance(expected_sha256, str):
        raise PipelineError(f"{field}.sha256 is invalid")
    actual_bytes = path.stat().st_size
    actual_sha256 = sha256_file(path)
    if actual_bytes != expected_bytes or actual_sha256 != expected_sha256:
        raise PipelineError(f"{field} binding is stale: {reference}")
    return path, {"path": normalized, "sha256": actual_sha256}


def _accepted_local_binding(root: Path, path: Path, *, field: str) -> dict[str, str]:
    from ocd_kernel.library._common import sha256_file
    from ocd_kernel.lib.path_io import resolve_path

    root = resolve_path(root, strict=True)
    path = resolve_path(path, strict=True)
    if not path.is_file():
        raise PipelineError(f"accepted {field} file is missing: {path}")
    try:
        relative = path.relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError) as exc:
        raise PipelineError(f"accepted {field} is outside root: {path}") from exc
    return {"path": relative, "sha256": sha256_file(path)}


def _accepted_projection_context(document: Mapping[str, Any]) -> dict[str, Any]:
    """Read optional rich context without treating a generic source proof as it."""

    nested = document.get("projection_context")
    if nested is not None and not isinstance(nested, Mapping):
        raise PipelineError("source.accounting projection_context must be an object")
    context = nested if isinstance(nested, Mapping) else document
    aliases = {
        "source_selector": "source_selector" if nested is not None else "selector",
        "source_scope": "source_scope" if nested is not None else "scope",
        "source_unit_count": "source_unit_count" if nested is not None else "native_unit_count",
        "source_selected_units": "source_selected_units" if nested is not None else "selected_unit_ids",
        "source_census": "source_census" if nested is not None else "census",
        "source_excerpt_sha256": "source_excerpt_sha256",
        "source_selected_subunits": "source_selected_subunits" if nested is not None else "selected_subunit_ids",
    }
    marker_keys = (
        "projection_context",
        "source_selector",
        "selector",
        "source_unit_count",
        "native_unit_count",
        "source_selected_units",
        "selected_unit_ids",
        "source_census",
        "census",
        "source_excerpt_sha256",
        "source_selected_subunits",
        "selected_subunit_ids",
    )
    if nested is None and not any(key in document for key in marker_keys):
        return {
            "available": False,
            "source_selector": None,
            "source_scope": None,
            "source_unit_count": None,
            "source_selected_units": None,
            "source_selected_subunits": None,
            "source_census": None,
            "source_excerpt_sha256": None,
        }
    required = (
        "source_selector",
        "source_scope",
        "source_unit_count",
        "source_selected_units",
        "source_census",
        "source_excerpt_sha256",
    )
    missing = [key for key in required if aliases[key] not in context]
    if missing:
        raise PipelineError(
            "source.accounting projection context is incomplete: "
            + ", ".join(missing)
        )
    selector = context[aliases["source_selector"]]
    scope = context[aliases["source_scope"]]
    count = context[aliases["source_unit_count"]]
    selected = context[aliases["source_selected_units"]]
    census = context[aliases["source_census"]]
    if not isinstance(selector, Mapping):
        raise PipelineError("source.accounting projection selector must be an object")
    if not isinstance(scope, str) or not scope.strip():
        raise PipelineError("source.accounting projection scope is invalid")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise PipelineError("source.accounting projection unit count is invalid")
    if not isinstance(selected, list) or any(not isinstance(item, str) for item in selected):
        raise PipelineError("source.accounting projection selected units are invalid")
    if not isinstance(census, list) or any(not isinstance(item, Mapping) for item in census):
        raise PipelineError("source.accounting projection census is invalid")
    if count != len(census):
        raise PipelineError("source.accounting projection census count mismatch")
    excerpt = context[aliases["source_excerpt_sha256"]]
    excerpt = _valid_sha(str(excerpt), "source_excerpt_sha256")
    selected_subunits = context.get(aliases["source_selected_subunits"])
    if selected_subunits is not None:
        if not isinstance(selected_subunits, list) or any(
            not isinstance(item, str) for item in selected_subunits
        ):
            raise PipelineError("source.accounting projection selected subunits are invalid")
    try:
        copied_selector = json.loads(json.dumps(selector, ensure_ascii=False))
        copied_census = json.loads(json.dumps(list(census), ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise PipelineError("source.accounting projection context is not JSON data") from exc
    return {
        "available": True,
        "source_selector": copied_selector,
        "source_scope": scope,
        "source_unit_count": count,
        "source_selected_units": list(selected),
        "source_selected_subunits": (
            list(selected_subunits) if selected_subunits is not None else None
        ),
        "source_census": copied_census,
        "source_excerpt_sha256": excerpt,
    }



_NATIVE_MAPPING_VERSION = "ocd-catechisms-source-transcription-v1"
_NATIVE_FORMAT = "ocd-native-content-v1"


def _native_source_unit_et(root: ET.Element) -> tuple[ET.Element, list[ET.Element], list[ET.Element]]:
    """Select the complete source-line transcription, including provider wrapper."""
    if [child.tag for child in root] != [f"{{{TEI_NS}}}teiHeader", f"{{{TEI_NS}}}text"]:
        raise UnsupportedStructure("native catechism requires one header and text")
    text = root[1]
    if [child.tag for child in text] != [f"{{{TEI_NS}}}body"]:
        raise UnsupportedStructure("native catechism text parts differ")
    body = text[0]
    if len(body) != 1 or body[0].tag != f"{{{TEI_NS}}}div":
        raise UnsupportedStructure("native catechism requires one complete body transcription")
    unit = body[0]
    if unit.get("type") != "catechism" or unit.get("subtype") != "gutenberg-source-transcription":
        raise UnsupportedStructure("native catechism transcription identity differs")
    if any((node.text or "").strip() or any((child.tail or "").strip() for child in node)
           for node in (text, body)):
        raise UnsupportedStructure("native catechism has loose text outside transcription")
    lines = [node for node in unit.iter() if node.tag == f"{{{TEI_NS}}}div" and node.get("type") == "source-line"]
    if not lines:
        raise UnsupportedStructure("native catechism has no source-line carriers")
    for number, line in enumerate(lines, 1):
        if len(line) != 1 or _local(line[0].tag) not in {"ab", "head"} or line[0].get("n") != str(number):
            raise UnsupportedStructure(f"native catechism source line {number} differs")
        if (line.text or "").strip() or (line[0].tail or "").strip() or len(line[0]):
            raise UnsupportedStructure(f"native catechism source line {number} has loose content")
    questions = [node for node in unit.iter() if node.tag == f"{{{TEI_NS}}}div" and node.get("type") == "question-answer"]
    if not questions:
        raise UnsupportedStructure("native catechism has no explicit question-answer groups")
    return unit, lines, questions


def _native_question_answers_et(questions: Sequence[ET.Element]) -> list[dict[str, Any]]:
    result = []
    seen_ids: set[str] = set()
    for order, question in enumerate(questions, 1):
        identifier = question.get(XML_ID)
        if not identifier or identifier in seen_ids or any(child.get("type") != "source-line" for child in question):
            raise UnsupportedStructure("native catechism Q/A has no unique line grouping")
        seen_ids.add(identifier)
        question_lines = []
        answer_lines = []
        answer_started = False
        for carrier in question:
            line = carrier[0]
            role = line.get("type")
            if role in {"question", "question-continuation"}:
                if answer_started:
                    raise UnsupportedStructure("native catechism question follows answer")
                question_lines.append({"number": line.get("n"), "role": role, "text": line.text or ""})
            elif role == "answer":
                answer_started = True
                answer_lines.append({"number": line.get("n"), "role": role, "text": line.text or ""})
            elif role != "blank":
                raise UnsupportedStructure(f"native catechism Q/A contains unclassified {role} line")
        if (not answer_lines and len(question_lines) > 1
                and question_lines[0]['text'].rstrip().endswith('?')
                and all(line['role'] == 'question-continuation' for line in question_lines[1:])):
            # The retained source contains one unlabelled answer after a
            # complete question. Keep the literal TEI role in structure;
            # classify its text as answer for the navigation index.
            answer_lines = [{**line, 'role': 'answer'} for line in question_lines[1:]]
            question_lines = question_lines[:1]
        if (not question_lines or question_lines[0]["role"] != "question"
                or not answer_lines or any(not line["text"].strip() for line in question_lines + answer_lines)):
            raise UnsupportedStructure("native catechism Q/A question or answer is missing")
        match = re.match(r"^([0-9]+\.)\s+Q\.", question_lines[0]["text"])
        result.append({
            "source_order": order,
            "source_number": match.group(1) if match else None,
            "question_lines": question_lines, "answer_lines": answer_lines,
        })
    return result


def _native_inventory_et(root: ET.Element) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = _paths(root)
    parents = _parents(root)
    inventory = []
    exclusions = []
    for ordinal, node in enumerate(root.iter(), 1):
        header = node.tag == f"{{{TEI_NS}}}teiHeader" or any(
            parent.tag == f"{{{TEI_NS}}}teiHeader" for parent in _ancestors(node, parents)
        )
        role = "bibliographic-header" if header else "native-content-or-envelope"
        inventory.append({
            "ordinal": ordinal, "tei_path": paths[node], "tag": _local(node.tag),
            "attributes": {_attr_name(key): value for key, value in sorted(node.attrib.items())},
            "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or ""),
            "role": role,
        })
        if header:
            exclusions.append({"ordinal": ordinal, "reason": role})
    return inventory, exclusions


def _project_native_accepted_catechism(metadata: Mapping[str, Any]) -> dict[str, Any]:
    from ocd_kernel.projection import native_content

    root, raw = _read_root(metadata["master_path"])
    unit, lines, questions = _native_source_unit_et(root)
    content = native_content.project_content(unit)
    readable = native_content.readable_content(content)
    question_answers = _native_question_answers_et(questions)
    identity = metadata["identity"]
    record_id = f"{identity['edition_id']}:source-transcription"
    row = {
        **identity, "record_id": record_id, "sequence": 1, "category": "catechisms",
        "language": metadata["language"], "text": readable,
        "representation_revision": metadata["representation_revision"],
        "provenance": {"edition_title": metadata["edition"].title},
        "locator": {"kind": "source-transcription", "text_part": "body", "unit": 1},
        "content_format": _NATIVE_FORMAT, "structure": [content],
        "source_line_count": len(lines), "question_answers": question_answers,
    }
    _validate_rows([row])
    inventory, exclusions = _native_inventory_et(root)
    receipt = {
        "scope": "tei-document; context derived from validated acceptance",
        "mapping_version": _NATIVE_MAPPING_VERSION,
        "master_sha256": _sha_bytes(raw), "schema_sha256": _sha_bytes(SCHEMA.read_bytes()),
        "common_schema_sha256": _sha_bytes(COMMON.read_bytes()),
        "native_content_schema_sha256": _sha_bytes(native_content.SCHEMA.read_bytes()),
        "output_sha256": _sha_bytes(_canonical([row])), "row_count": 1,
        "source_line_count": len(lines), "question_answer_count": len(questions),
        "question_anchors": [{"source_order": i, "tei_id": q.get(XML_ID)} for i, q in enumerate(questions, 1)],
        "anchors": [{"unit_id": unit.get(XML_ID), "record_id": record_id,
                     "text_sha256": _sha_text(readable)}],
        "inventory": inventory, "exclusions": exclusions, "warnings": [],
        "unsupported": [], "independent_check": {"status": "pending"},
        "authority": dict(metadata["authority"]),
    }
    return {"rows": [row], "receipt": receipt, "authority": dict(metadata["authority"])}



def _is_native_transcription(path: Path) -> bool:
    root, _ = _read_root(path)
    body = root.find(f"{{{TEI_NS}}}text/{{{TEI_NS}}}body")
    return bool(body is not None and len(body) == 1
                and body[0].get("subtype") == "gutenberg-source-transcription")


def _verify_native_accepted_catechism(
    metadata: Mapping[str, Any], rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> list[str]:
    """Independently observe the full accepted tree with lxml and native checks."""
    from lxml import etree
    from ocd_kernel.projection.native_content_check import observe_content, verify_content, SCHEMA as NATIVE_SCHEMA

    try:
        root, raw = _checker_parse(metadata["master_path"])
        ns = f"{{{TEI_NS}}}"
        if [node.tag for node in root] != [ns + "teiHeader", ns + "text"]:
            raise ValueError("native catechism header/text envelope differs")
        text = root[1]
        if [node.tag for node in text] != [ns + "body"] or len(text[0]) != 1:
            raise ValueError("native catechism body envelope differs")
        body = text[0]
        unit = body[0]
        if (unit.tag != ns + "div" or unit.get("type") != "catechism"
                or unit.get("subtype") != "gutenberg-source-transcription"):
            raise ValueError("native catechism transcription differs")
        if any((node.text or "").strip() or any((child.tail or "").strip() for child in node)
               for node in (text, body)):
            raise ValueError("native catechism text outside transcription differs")
        lines = [node for node in unit.iter() if node.tag == ns + "div" and node.get("type") == "source-line"]
        if not lines:
            raise ValueError("native catechism source-line census is empty")
        for index, carrier in enumerate(lines, 1):
            if (len(carrier) != 1 or carrier[0].tag not in {ns + "ab", ns + "head"}
                    or carrier[0].get("n") != str(index) or len(carrier[0])
                    or (carrier.text or "").strip() or (carrier[0].tail or "").strip()):
                raise ValueError(f"native catechism source line {index} differs")
        questions = [node for node in unit.iter() if node.tag == ns + "div" and node.get("type") == "question-answer"]
        if not questions:
            raise ValueError("native catechism has no explicit Q/A groups")
        indexed = []
        seen_ids = set()
        for index, question in enumerate(questions, 1):
            identifier = question.get(XML_ID)
            if not identifier or identifier in seen_ids or any(child.tag != ns + "div" or child.get("type") != "source-line" for child in question):
                raise ValueError("native catechism Q/A structure differs")
            seen_ids.add(identifier)
            q_lines, a_lines = [], []
            answered = False
            for carrier in question:
                leaf = carrier[0]
                role = leaf.get("type")
                entry = {"number": leaf.get("n"), "role": role, "text": leaf.text or ""}
                if role in ("question", "question-continuation"):
                    if answered:
                        raise ValueError("native catechism Q/A order differs")
                    q_lines.append(entry)
                elif role == "answer":
                    answered = True
                    a_lines.append(entry)
                elif role != "blank":
                    raise ValueError("native catechism Q/A role differs")
            if (not a_lines and len(q_lines) > 1
                    and q_lines[0]['text'].rstrip().endswith('?')
                    and all(line['role'] == 'question-continuation' for line in q_lines[1:])):
                a_lines = [{**line, 'role': 'answer'} for line in q_lines[1:]]
                q_lines = q_lines[:1]
            if (not q_lines or q_lines[0]["role"] != "question" or not a_lines
                    or any(not line["text"].strip() for line in q_lines + a_lines)):
                raise ValueError("native catechism Q/A content differs")
            prefix, marker, _ = q_lines[0]["text"].partition(" Q.")
            source_number = prefix if marker and re.fullmatch(r"[0-9]+\.", prefix) else None
            indexed.append({"source_order": index,
                            "source_number": source_number,
                            "question_lines": q_lines, "answer_lines": a_lines})
        fragment = etree.tostring(unit, with_tail=False)
        structure, readable = observe_content(fragment)
        identity = metadata["identity"]
        record_id = f"{identity['edition_id']}:source-transcription"
        expected_row = {
            **identity, "record_id": record_id, "sequence": 1, "category": "catechisms",
            "language": metadata["language"], "text": readable,
            "representation_revision": metadata["representation_revision"],
            "provenance": {"edition_title": metadata["edition"].title},
            "locator": {"kind": "source-transcription", "text_part": "body", "unit": 1},
            "content_format": _NATIVE_FORMAT, "structure": [structure],
            "source_line_count": len(lines), "question_answers": indexed,
        }
        inventory = []
        exclusions = []
        paths = {}
        for node in root.iter():
            parent = node.getparent()
            if parent is None:
                location = f"/{etree.QName(node).localname}[1]"
            else:
                siblings = [child for child in parent if child.tag == node.tag]
                location = f"{paths[parent]}/{etree.QName(node).localname}[{siblings.index(node) + 1}]"
            paths[node] = location
            header = node.tag == ns + "teiHeader" or any(parent.tag == ns + "teiHeader" for parent in node.iterancestors())
            role = "bibliographic-header" if header else "native-content-or-envelope"
            item = {
                "ordinal": len(inventory) + 1, "tei_path": location,
                "tag": etree.QName(node).localname,
                "attributes": {
                    ("xml:" + etree.QName(key).localname if etree.QName(key).namespace == XML_NS else key): value
                    for key, value in sorted(node.attrib.items())
                },
                "text_sha256": _sha_text(node.text or ""), "tail_sha256": _sha_text(node.tail or ""),
                "role": role,
            }
            inventory.append(item)
            if header:
                exclusions.append({"ordinal": item["ordinal"], "reason": role})
        expected_receipt = {
            "scope": "tei-document; context derived from validated acceptance",
            "mapping_version": _NATIVE_MAPPING_VERSION,
            "master_sha256": _sha_bytes(raw), "schema_sha256": _sha_bytes(SCHEMA.read_bytes()),
            "common_schema_sha256": _sha_bytes(COMMON.read_bytes()),
            "native_content_schema_sha256": _sha_bytes(NATIVE_SCHEMA.read_bytes()),
            "output_sha256": _sha_bytes(_canonical([expected_row])), "row_count": 1,
            "source_line_count": len(lines), "question_answer_count": len(questions),
            "question_anchors": [{"source_order": i, "tei_id": q.get(XML_ID)} for i, q in enumerate(questions, 1)],
            "anchors": [{"unit_id": unit.get(XML_ID), "record_id": record_id,
                         "text_sha256": _sha_text(readable)}],
            "inventory": inventory, "exclusions": exclusions, "warnings": [],
            "unsupported": [], "independent_check": {"status": "pending"},
            "authority": dict(metadata["authority"]),
        }
        errors = []
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or list(rows) != [expected_row]:
            errors.append("native catechism rows differ from complete source observation")
        if dict(receipt) != expected_receipt:
            errors.append("native catechism receipt differs from independent accounting")
        errors.extend(verify_content(fragment, structure, readable))
        if not errors:
            _validate_rows([expected_row])
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return [f"native catechism verification failed: {exc}"]

def _accepted_metadata(root: Path, acceptance_path: Path) -> dict[str, Any]:
    from ocd_kernel.library.acquisitions import acquisition_for_edition
    from ocd_kernel.library.identities import edition_by_id, resolve_edition_language
    from ocd_kernel.tei.acceptance import validate_acceptance

    base = Path(root).resolve()
    accepted_path = Path(acceptance_path).resolve()
    accepted = validate_acceptance(accepted_path, root=base)
    if accepted["promotion"]["status"] != "promoted":
        raise PipelineError("catechism projection requires a promoted accepted master")
    accepted_identity = accepted.get("identity")
    if not isinstance(accepted_identity, Mapping):
        raise PipelineError("accepted identity is missing")
    identity = {key: accepted_identity[key] for key in (*_IDENTITY_KEYS, "acquisition_id")}
    work, edition = edition_by_id(base, identity["edition_id"], work_id=identity["work_id"])
    if work.work_id != identity["work_id"] or edition.textual_form_id != identity["textual_form_id"]:
        raise PipelineError("accepted identity does not identify the canonical catechism edition")
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
    if category != "catechisms":
        raise PipelineError("accepted edition category mismatch")
    language = resolve_edition_language(work.record, edition.record, edition.textual_form_id)
    if not isinstance(language, str) or not _LANG_RE.fullmatch(language):
        raise PipelineError("accepted catechism edition has no valid language")
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
        raise PipelineError("catechism projection requires exactly one accepted retained member")
    retained_binding = included[0]
    retained_path, retained_authority = _accepted_bound_file(
        base, retained_binding, field="scope.included_members[0]"
    )
    accounting_binding = source.get("accounting")
    accounting_path, accounting_authority = _accepted_bound_file(
        base, accounting_binding, field="source.accounting"
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
        "source_url": source_url,
        "source_sha256": source_sha256,
        "retained_sha256": retained_binding["sha256"],
        "source_logical_path": source_logical_path,
        "retained_path": retained_path if projection_context["available"] else None,
        "source_context": projection_context,
        "authority": authority,
    }


def project_accepted_catechisms(root: Path, *, acceptance_path: Path) -> dict[str, Any]:
    """Project a promoted catechism using only validated acceptance authority."""

    from build.tools.project_1695_baptist_catechism import ACCEPTANCE as baptist_acceptance, project_accepted

    if Path(acceptance_path).resolve() == (Path(root).absolute() / baptist_acceptance).resolve():
        return project_accepted(root, acceptance_path=acceptance_path)

    from ocd_kernel.projection.categories.creeds_json_two_catechisms import ROUTES as creeds_json_routes
    for work_id, route in creeds_json_routes.items():
        suffix = f"/library/works/{work_id}/forms/{work_id}-retained-electronic/editions/{route['edition_id']}/acceptance.json"
        if Path(acceptance_path).as_posix().endswith(suffix):
            from ocd_kernel.projection.categories.creeds_json_two_catechisms_profile import project
            return project(root, acceptance_path=acceptance_path)
    from ocd_kernel.projection.categories.creeds_json_lib062_remaining import ROUTES as lib062_routes, STAGEABLE
    for work_id in STAGEABLE:
        route = lib062_routes[work_id]
        form_id = route.get("textual_form_id", f"{work_id}-retained-electronic")
        suffix = f"/library/works/{work_id}/forms/{form_id}/editions/{route['edition_id']}/acceptance.json"
        if Path(acceptance_path).as_posix().endswith(suffix):
            from ocd_kernel.projection.categories.creeds_json_lib062_remaining_profile import project
            return project(root, acceptance_path=acceptance_path)
    metadata = _accepted_metadata(root, acceptance_path)
    context = metadata["source_context"]
    kwargs: dict[str, Any] = {
        "identity": metadata["identity"],
        "language": metadata["language"],
        "representation_revision": metadata["representation_revision"],
        "edition_title": metadata["edition"].title,
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
            source_selected_subunits=context["source_selected_subunits"],
            source_census=context["source_census"],
            source_excerpt_sha256=context["source_excerpt_sha256"],
        )
    if _is_native_transcription(metadata["master_path"]):
        return _project_native_accepted_catechism(metadata)
    projection = project_catechism_document(metadata["master_path"], **kwargs)
    receipt = build_catechism_receipt(projection, identity=metadata["identity"])
    receipt["authority"] = dict(metadata["authority"])
    receipt["scope"] = "tei-document; context derived from validated acceptance"
    projection["receipt"] = receipt
    projection["authority"] = dict(metadata["authority"])
    return projection


def verify_accepted_catechisms(
    root: Path,
    *,
    acceptance_path: Path,
    rows: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> list[str]:
    """Verify accepted catechism rows without invoking the producer."""

    try:
        from build.tools.project_1695_baptist_catechism import ACCEPTANCE as baptist_acceptance, verify_accepted

        if Path(acceptance_path).resolve() == (Path(root).absolute() / baptist_acceptance).resolve():
            return verify_accepted(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)

        from ocd_kernel.projection.categories.creeds_json_two_catechisms import ROUTES as creeds_json_routes
        for work_id, route in creeds_json_routes.items():
            suffix = f"/library/works/{work_id}/forms/{work_id}-retained-electronic/editions/{route['edition_id']}/acceptance.json"
            if Path(acceptance_path).as_posix().endswith(suffix):
                from ocd_kernel.projection.categories.creeds_json_two_catechisms_profile import verify
                return verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
        from ocd_kernel.projection.categories.creeds_json_lib062_remaining import ROUTES as lib062_routes, STAGEABLE
        for work_id in STAGEABLE:
            route = lib062_routes[work_id]
            form_id = route.get("textual_form_id", f"{work_id}-retained-electronic")
            suffix = f"/library/works/{work_id}/forms/{form_id}/editions/{route['edition_id']}/acceptance.json"
            if Path(acceptance_path).as_posix().endswith(suffix):
                from ocd_kernel.projection.categories.creeds_json_lib062_remaining_profile import verify
                return verify(root, acceptance_path=acceptance_path, rows=rows, receipt=receipt)
        metadata = _accepted_metadata(root, acceptance_path)
        if receipt is None:
            return ["accepted catechism receipt is missing"]
        if not isinstance(receipt, Mapping):
            return ["accepted catechism receipt must be an object"]
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
                source_selected_subunits=context["source_selected_subunits"],
                source_census=context["source_census"],
                source_excerpt_sha256=context["source_excerpt_sha256"],
            )
        if _is_native_transcription(metadata["master_path"]):
            return _verify_native_accepted_catechism(metadata, rows, receipt)
        document_receipt = dict(receipt)
        document_receipt.pop("authority", None)
        document_receipt.pop("scope", None)
        errors.extend(
            verify_catechism(
                metadata["master_path"], rows, document_receipt, **kwargs
            )
        )
        return errors
    except (PipelineError, OSError, ValueError, KeyError, TypeError) as exc:
        return [str(exc)]

__all__ = ["project_catechism_document", "project_catechism", "project_document", "build_catechism_receipt", "verify_catechism", "check_catechism", "verify_document", "project_accepted_catechisms", "verify_accepted_catechisms", "MAPPING_VERSION", "RECEIPT_VERSION", "ASSEMBLER_VERSION", "UnsupportedStructure"]
