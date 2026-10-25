"""Independent checks for the provisional PIPE-001 release tree.

This module intentionally does not import the category projector, receipt
builder, or release assembler.  It parses the accepted TEI and sidecars again
and reconstructs the bounded prose rows so that a receipt or a producer cannot
declare its own output valid.
"""

from __future__ import annotations

import json
import copy
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ocd_kernel.library._common import (
    PipelineError,
    canonical_bytes,
    load_json,
    sha256_bytes,
    sha256_file,
    within,
)
from ocd_kernel.release.public_allowlist import check_public_allowlist


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"

EXPECTED_README = (
    "# OCD offline release\n\n"
    "This deterministic private/public tree was assembled offline from the "
    "selected accepted TEI master. The `public/` directory is the only "
    "uploadable tree; `internal/` contains private receipts and checks.\n"
)

# These literals are the checker contract.  Keeping them here avoids importing
# the producer's constants and accidentally sharing its implementation.
EXPECTED_RECEIPT_VERSION = "ocd-projection-receipt-provisional-v1"
EXPECTED_MAPPING_VERSION = "ocd-prose-mapping-provisional-v1"
EXPECTED_ASSEMBLER_VERSION = "ocd-projection-assembler-provisional-v1"
EXPECTED_SELECTION_VERSION = "ocd-release-selection-provisional-v1"
EXPECTED_RELEASE_VERSION = "ocd-offline-release-provisional-v1"
ALLOWED_INLINE = {"pb", "lb", "seg", "hi", "foreign", "ref", "note", "anchor"}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PipelineError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_object(path: Path) -> dict[str, Any]:
    """Load one object without sharing any release or projection parser."""

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"JSON object required: {path}")
    return value


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _text_without_notes(element: ET.Element) -> str:
    """Return paragraph text after removing note subtrees from a copy.

    The producer walks the original tree recursively and special-cases notes.
    The checker uses a separate tree-copy/removal pass, preserving each note's
    tail at its XML position before relying on ElementTree's normal itertext.
    """

    clone = copy.deepcopy(element)
    for parent in list(clone.iter()):
        children = list(parent)
        for index, child in enumerate(children):
            if _local(child.tag) != "note":
                continue
            tail = child.tail or ""
            parent.remove(child)
            survivors = list(parent)
            previous = next(
                (candidate for candidate in reversed(children[:index]) if candidate in survivors),
                None,
            )
            if previous is not None:
                previous.tail = (previous.tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail
    return _normalize("".join(clone.itertext()))


def _note_text(element: ET.Element) -> str:
    return _normalize("".join(element.itertext()))


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: node for node in root.iter() for child in list(node)}


def _tei_path(root: ET.Element, target: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    components: list[str] = []
    current: ET.Element | None = target
    while current is not None:
        name = _local(current.tag)
        xml_id = current.get(XML_ID)
        if xml_id:
            components.append(f"{name}[@xml:id='{xml_id}']")
        else:
            components.append(name)
        current = parents.get(current)
    return "/" + "/".join(reversed(components))


def _sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _idno_values(root: ET.Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for node in root.iter():
        if _local(node.tag) != "idno":
            continue
        key = (node.get("type") or "").strip().lower()
        value = _normalize("".join(node.itertext()))
        if key and value:
            values.setdefault(key, []).append(value)
    return values


def _single_idno(values: dict[str, list[str]], key: str, errors: list[str]) -> str | None:
    matches = values.get(key, [])
    if len(matches) != 1:
        errors.append(f"TEI requires exactly one {key} idno; found {len(matches)}")
        return None
    return matches[0]


def _tei_metadata(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError, UnicodeError) as exc:
        errors.append(f"cannot parse TEI {path}: {exc}")
        return None
    if root.tag != f"{{{TEI_NS}}}TEI":
        errors.append(f"TEI root is not TEI: {path}")
        return None
    if any(not node.tag.startswith(f"{{{TEI_NS}}}") for node in root.iter()):
        errors.append("unsupported non-TEI namespace in master")
        return None
    source_desc = root.find(f"{{{TEI_NS}}}teiHeader/{{{TEI_NS}}}fileDesc/{{{TEI_NS}}}sourceDesc")
    if source_desc is None:
        errors.append("TEI has no header sourceDesc")
        return None
    idnos = _idno_values(source_desc)
    required = {
        key: _single_idno(idnos, key, errors)
        for key in (
            "work_id",
            "textual_form_id",
            "edition_id",
            "acquisition_id",
            "representation_revision",
            "source_sha256",
            "source_bytes",
        )
    }
    sha_values = idnos.get("sha256", [])
    if len(sha_values) != 1:
        errors.append(f"TEI requires exactly one sha256 idno; found {len(sha_values)}")
        retained_sha256 = None
    else:
        retained_sha256 = sha_values[0].lower()
    pointers = [
        (node.get("target") or "").strip()
        for node in source_desc.iter()
        if _local(node.tag) == "ptr" and (node.get("target") or "").strip()
    ]
    source_notes = {
        (node.get("type") or "").strip().lower(): _normalize("".join(node.itertext()))
        for node in source_desc.iter()
        if _local(node.tag) == "note" and node.get("type")
    }
    source_url = pointers[0] if pointers else None
    if source_url is None:
        errors.append("TEI sourceDesc requires a source URL ptr")
    source_location = source_notes.get("source-location")
    source_scope = source_notes.get("source-scope")
    if not source_location:
        errors.append("TEI sourceDesc requires a source-location note")
    if not source_scope:
        errors.append("TEI sourceDesc requires a source-scope note")
    if required["source_sha256"] is not None:
        value = required["source_sha256"].lower()
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            errors.append("TEI source_sha256 is not a valid SHA-256")
        required["source_sha256"] = value
    if retained_sha256 is not None and (
        len(retained_sha256) != 64
        or any(char not in "0123456789abcdef" for char in retained_sha256)
    ):
        errors.append("TEI sha256 is not a valid SHA-256")
    return {
        "root": root,
        "idnos": idnos,
        "work_id": required["work_id"],
        "textual_form_id": required["textual_form_id"],
        "edition_id": required["edition_id"],
        "acquisition_id": required["acquisition_id"],
        "representation_revision": required["representation_revision"],
        "source_sha256": required["source_sha256"],
        "source_bytes": required["source_bytes"],
        "retained_sha256": retained_sha256,
        "source_url": source_url,
        "source_location": source_location,
        "source_scope": source_scope,
    }


def _scope_id(scope: str | None) -> str | None:
    if not scope:
        return None
    matches = re.findall(r"@(?:xml:)?id\s*=\s*['\"]([^'\"]+)['\"]", scope)
    return matches[-1] if matches else None


def _find_scope(root: ET.Element, scope: str | None, errors: list[str]) -> ET.Element | None:
    body = next((node for node in root.iter() if _local(node.tag) == "body"), None)
    if body is None:
        errors.append("TEI has no body")
        return None
    target_id = _scope_id(scope)
    if target_id:
        matches = [node for node in body.iter() if node.get(XML_ID) == target_id]
        if len(matches) != 1 or _local(matches[0].tag) != "div":
            errors.append(f"source scope does not resolve uniquely to a div: {target_id}")
            return None
        return matches[0]
    leaves = [
        node
        for node in body.iter()
        if _local(node.tag) == "div"
        and any(_local(child.tag) == "p" for child in list(node))
        and not any(_local(child.tag) == "div" for child in list(node))
    ]
    if len(leaves) != 1:
        errors.append(f"TEI prose scope is ambiguous: {len(leaves)} leaf divs")
        return None
    return leaves[0]


def _division_context(
    root: ET.Element, scope: ET.Element, parents: dict[ET.Element, ET.Element]
) -> list[dict[str, Any]]:
    ancestors: list[ET.Element] = []
    current = parents.get(scope)
    while current is not None:
        if _local(current.tag) == "div":
            ancestors.append(current)
        current = parents.get(current)
    ancestors.reverse()
    nodes = ancestors + [scope]
    result: list[dict[str, Any]] = []
    for node in nodes:
        head = next((child for child in list(node) if _local(child.tag) == "head"), None)
        result.append(
            {
                "xml_id": node.get(XML_ID),
                "type": node.get("type"),
                "head": _normalize("".join(head.itertext())) if head is not None else None,
            }
        )
    return result


def _validate_inline_structure(
    root: ET.Element,
    node: ET.Element,
    parents: dict[ET.Element, ET.Element],
    errors: list[str],
    *,
    in_note: bool = False,
) -> None:
    """Flag inline elements outside the bounded PIPE-001 TEI vocabulary."""

    for child in list(node):
        kind = _local(child.tag)
        if kind == "note":
            _validate_inline_structure(root, child, parents, errors, in_note=True)
            continue
        if in_note and kind == "p":
            _validate_inline_structure(root, child, parents, errors, in_note=True)
            continue
        if kind not in ALLOWED_INLINE:
            errors.append(
                f"unsupported prose inline element {kind!r} at {_tei_path(root, child, parents)}"
            )
            continue
        _validate_inline_structure(root, child, parents, errors, in_note=in_note)


def _public_language(root: ET.Element, requested: Any) -> str:
    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    if root.get(XML_LANG):
        return root.get(XML_LANG) or "en"
    for node in root.iter():
        if _local(node.tag) in {"text", "body"} and node.get(XML_LANG):
            return node.get(XML_LANG) or "en"
    return "en"


def _expected_rows(
    metadata: dict[str, Any],
    *,
    edition_title: str,
    language: Any,
    source_url: str,
    accessed_at: str | None,
    acquisition_id: str,
    rights: str | None,
    errors: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = metadata["root"]
    parents = _parent_map(root)
    scope = _find_scope(root, metadata.get("source_scope"), errors)
    if scope is None:
        return [], []
    text_root = root.find(f"{{{TEI_NS}}}text")
    if text_root is None or [child.tag for child in text_root] != [f"{{{TEI_NS}}}body"]:
        errors.append("unaccounted text outside the bounded prose body")
        return [], []
    body = text_root[0]
    covered = set(scope.iter())
    ancestor = parents.get(scope)
    while ancestor is not None and ancestor is not text_root:
        covered.add(ancestor)
        heads = [child for child in ancestor if child.tag == f"{{{TEI_NS}}}head"]
        if len(heads) > 1:
            errors.append("multiple wrapper headings are unsupported")
        for head in heads:
            covered.update(head.iter())
        ancestor = parents.get(ancestor)
    if set(body.iter()) - covered:
        errors.append("unaccounted content outside the selected prose section")
        return [], []
    direct_children = list(scope)
    paragraphs = [node for node in direct_children if _local(node.tag) == "p"]
    if not paragraphs:
        errors.append("selected prose scope has no direct paragraph carriers")
        return [], []
    unsupported = [
        _local(node.tag)
        for node in direct_children
        if _local(node.tag) not in {"head", "p"} | ALLOWED_INLINE
    ]
    if unsupported:
        errors.append("unsupported direct scope children: " + ", ".join(sorted(set(unsupported))))
    context = _division_context(root, scope, parents)
    rows: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    for sequence, paragraph in enumerate(paragraphs, start=1):
        _validate_inline_structure(root, paragraph, parents, errors)
        text = _text_without_notes(paragraph)
        xml_id = paragraph.get(XML_ID)
        if not xml_id:
            errors.append(f"prose paragraph has no xml:id at {_tei_path(root, paragraph, parents)}")
            continue
        if not text:
            errors.append(f"empty direct prose paragraph: {xml_id}")
            continue
        locator = {
            "xml_id": xml_id,
            "source_path": _tei_path(root, paragraph, parents),
            "division_ids": [item["xml_id"] for item in context if item["xml_id"]],
            "division_titles": [item["head"] for item in context if item["head"]],
            "source_order": sequence,
        }
        notes: list[dict[str, Any]] = []
        for note in [node for node in paragraph.iter() if _local(node.tag) == "note"]:
            notes.append(
                {
                    "xml_id": note.get(XML_ID),
                    "place": note.get("place"),
                    "n": note.get("n"),
                    "text": _note_text(note),
                    "source_path": _tei_path(root, note, parents),
                }
            )
        provenance: dict[str, Any] = {
            "edition_title": edition_title,
            "source_url": source_url,
            "acquisition_id": acquisition_id,
        }
        if accessed_at is not None:
            provenance["accessed_at"] = accessed_at
        if rights:
            provenance["rights"] = rights
        row: dict[str, Any] = {
            "record_id": f"{metadata['edition_id']}:unit-{sequence:06d}",
            "sequence": sequence,
            "work_id": metadata["work_id"],
            "textual_form_id": metadata["textual_form_id"],
            "edition_id": metadata["edition_id"],
            "category": "prose",
            "language": _public_language(root, language),
            "text": text,
            "locator": locator,
            "provenance": provenance,
            "representation_revision": metadata["representation_revision"],
        }
        if notes:
            row["notes"] = notes
        rows.append(row)
        anchors.append(
            {
                "record_id": row["record_id"],
                "sequence": sequence,
                "tei_xml_id": xml_id,
                "tei_path": locator["source_path"],
                "locator": locator,
                "text_sha256": _sha256_text(text),
                "notes": [note["xml_id"] for note in notes if note["xml_id"]],
            }
        )
    if not rows:
        errors.append("prose projection has no rows")
    return rows, anchors


def _load_rows(path: Path, errors: list[str]) -> tuple[list[dict[str, Any]], bytes]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read public rows {path}: {exc}")
        return [], b""
    if not raw.endswith(b"\n"):
        errors.append("public JSONL must end with a newline")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            errors.append(f"public JSONL contains an empty line at {index}")
            continue
        try:
            value = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid public JSONL at line {index}: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"public JSONL line {index} is not an object")
            continue
        rows.append(value)
    return rows, raw


def _require_path(root: Path, value: Any, *, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field} must be a non-empty relative path")
        return None
    try:
        return within(root, value, field=field)
    except PipelineError as exc:
        errors.append(str(exc))
        return None


def _safe_component(value: Any) -> bool:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        return False
    candidate = Path(value)
    return candidate.name == value and not candidate.is_absolute()


def _canonical_edition_dir(
    root: Path, identity: dict[str, Any], errors: list[str]
) -> Path | None:
    components = (
        identity.get("work_id"),
        identity.get("textual_form_id"),
        identity.get("edition_id"),
    )
    if not all(_safe_component(value) for value in components):
        errors.append("receipt identity contains an unsafe canonical path component")
        return None
    return (
        root
        / "library"
        / "works"
        / components[0]
        / "forms"
        / components[1]
        / "editions"
        / components[2]
    )


def _root_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""


def _evidence_binds_master(root: Path, work_path: Path, master_path: Path, evidence: Any) -> bool:
    if not isinstance(evidence, list):
        return False
    canonical = master_path.resolve()
    for value in evidence:
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            continue
        for base in (root, work_path.parent):
            if (base / value).resolve() == canonical:
                return True
    return False


def _find_edition_sidecar(root: Path, identity: dict[str, Any], errors: list[str]) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None]:
    work_id = identity.get("work_id")
    form_id = identity.get("textual_form_id")
    edition_id = identity.get("edition_id")
    if not all(isinstance(value, str) and value for value in (work_id, form_id, edition_id)):
        errors.append("receipt identity is incomplete")
        return None, None, None
    edition_dir = _canonical_edition_dir(root, identity, errors)
    if edition_dir is None:
        return None, None, None
    work_path = root / "library" / "works" / work_id / "work.json"
    state_path = root / "library" / "works" / work_id / "state.json"
    try:
        work = _load_object(work_path)
    except PipelineError as exc:
        errors.append(str(exc))
        return None, None, None
    try:
        state = _load_object(state_path)
    except PipelineError as exc:
        errors.append(str(exc))
        state = None
    if work.get("work_id") != work_id:
        errors.append("work sidecar identity mismatch")
    editions: list[dict[str, Any]] = []
    forms = work.get("textual_forms", [])
    if not isinstance(forms, list):
        errors.append("work sidecar textual_forms is not a list")
        forms = []
    for form in forms:
        if isinstance(form, dict) and form.get("textual_form_id") == form_id:
            form_editions = form.get("editions", [])
            if not isinstance(form_editions, list):
                errors.append("work sidecar editions is not a list")
                continue
            editions.extend(
                edition
                for edition in form_editions
                if isinstance(edition, dict) and edition.get("edition_id") == edition_id
            )
    if len(editions) != 1:
        errors.append(f"identity sidecars resolve {len(editions)} matching editions")
        edition = editions[0] if editions else None
    else:
        edition = editions[0]
    if state is not None:
        if state.get("work_id") != work_id:
            errors.append("state sidecar work_id mismatch")
        state_targets = state.get("targets", [])
        if not isinstance(state_targets, list):
            errors.append("state sidecar targets is not a list")
            state_targets = []
        targets = [
            item
            for item in state_targets
            if isinstance(item, dict) and item.get("target_id") == edition_id
        ]
        if len(targets) != 1:
            errors.append(f"state sidecar has {len(targets)} targets for {edition_id}")
        else:
            target = targets[0]
            if target.get("target_type") != "edition":
                errors.append(f"state target {edition_id} is not an edition target")
            if target.get("stage") != "accepted":
                errors.append(f"state target {edition_id} is not accepted")
            evidence = target.get("evidence")
            canonical_master = edition_dir / "master.tei.xml"
            if not _evidence_binds_master(root, work_path, canonical_master, evidence):
                errors.append(f"state target {edition_id} does not evidence its canonical TEI master")
    if edition is None:
        return work_path, work, None
    return work_path, work, edition


def _find_canonical_acquisition(
    root: Path, identity: dict[str, Any], errors: list[str]
) -> tuple[Path | None, dict[str, Any] | None]:
    edition_dir = _canonical_edition_dir(root, identity, errors)
    if edition_dir is None:
        return None, None
    acquisition_dir = edition_dir / "acquisitions"
    if not acquisition_dir.is_dir():
        errors.append(f"canonical acquisition directory is missing: {acquisition_dir}")
        return None, None
    matches: list[tuple[Path, dict[str, Any]]] = []
    for candidate in sorted(acquisition_dir.glob("*.json")):
        try:
            record = _load_object(candidate)
        except PipelineError as exc:
            errors.append(str(exc))
            continue
        if record.get("acquisition_id") == identity.get("acquisition_id"):
            if record.get("edition_id") != identity.get("edition_id"):
                errors.append(f"acquisition edition_id mismatch: {candidate}")
            matches.append((candidate, record))
    if len(matches) != 1:
        errors.append(
            f"canonical acquisition resolves {len(matches)} records for {identity.get('acquisition_id')}"
        )
        return None, None
    return matches[0]


def _check_receipt(
    *,
    root: Path,
    release: Path,
    receipt_path: Path,
    receipt: dict[str, Any],
    rows: list[dict[str, Any]],
    rows_raw: bytes,
    errors: list[str],
) -> None:
    for key in (
        "schema_version",
        "receipt_version",
        "contract",
        "identity",
        "inputs",
        "mapping",
        "assembler",
        "outputs",
        "warnings",
        "exclusions",
        "independent_check",
    ):
        if key not in receipt:
            errors.append(f"receipt missing {key}: {receipt_path}")
    if receipt.get("contract") != "ocd-projection-receipt-v1":
        errors.append(f"receipt contract mismatch: {receipt_path}")
    if receipt.get("schema_version") != "provisional-v1":
        errors.append(f"unsupported receipt schema version: {receipt_path}")
    if receipt.get("receipt_version") != EXPECTED_RECEIPT_VERSION:
        errors.append(f"unsupported receipt version: {receipt_path}")
    independent_check = receipt.get("independent_check")
    if not isinstance(independent_check, dict) or independent_check.get("status") not in {
        "pending",
        "pass",
        "fail",
    }:
        errors.append(f"receipt independent_check status is invalid: {receipt_path}")
    identity = receipt.get("identity")
    if not isinstance(identity, dict):
        errors.append(f"receipt identity is not an object: {receipt_path}")
        return
    for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id"):
        if not isinstance(identity.get(key), str) or not identity[key]:
            errors.append(f"receipt identity missing {key}: {receipt_path}")
    inputs = receipt.get("inputs")
    if not isinstance(inputs, dict):
        errors.append(f"receipt inputs are not an object: {receipt_path}")
        return
    master_path = _require_path(root, inputs.get("master_path"), field="receipt.inputs.master_path", errors=errors)
    acquisition_path = _require_path(root, inputs.get("acquisition_path"), field="receipt.inputs.acquisition_path", errors=errors)
    if master_path is None or acquisition_path is None:
        return
    canonical_edition = _canonical_edition_dir(root, identity, errors)
    canonical_master = canonical_edition / "master.tei.xml" if canonical_edition is not None else None
    canonical_acquisition_path, canonical_acquisition = _find_canonical_acquisition(root, identity, errors)
    if canonical_master is None or not canonical_master.is_file():
        errors.append(f"canonical accepted master is missing: {canonical_master}")
        return
    if master_path.resolve() != canonical_master.resolve():
        errors.append("receipt master_path does not bind the canonical edition master")
    if canonical_acquisition_path is None or canonical_acquisition is None:
        return
    if acquisition_path.resolve() != canonical_acquisition_path.resolve():
        errors.append("receipt acquisition_path does not bind the canonical acquisition sidecar")
    if not acquisition_path.is_file():
        errors.append(f"receipt acquisition sidecar is missing: {acquisition_path}")
    actual_master_sha256 = sha256_file(canonical_master)
    if inputs.get("master_sha256") != actual_master_sha256:
        errors.append(f"accepted master hash mismatch: {canonical_master}")
    acquisition = canonical_acquisition
    expected_source = acquisition.get("source_sha256")
    expected_source = expected_source.lower() if isinstance(expected_source, str) else None
    retained = acquisition.get("retained_files")
    if not isinstance(retained, list) or not retained or not isinstance(retained[0], dict):
        errors.append(f"acquisition retained_files missing: {acquisition_path}")
        retained_item: dict[str, Any] = {}
    else:
        retained_item = retained[0]
    retained_path = _require_path(root, retained_item.get("path"), field="retained_files.path", errors=errors)
    actual_retained_sha256: str | None = None
    if retained_path is not None and retained_path.is_file():
        actual_retained_sha256 = sha256_file(retained_path)
        if retained_item.get("bytes") != retained_path.stat().st_size:
            errors.append(f"retained excerpt byte count mismatch: {retained_path}")
        if retained_item.get("sha256", "").lower() != actual_retained_sha256:
            errors.append(f"retained excerpt hash mismatch: {retained_path}")
    elif retained_path is not None:
        errors.append(f"retained excerpt is missing: {retained_path}")
    if inputs.get("source_sha256") != expected_source:
        errors.append("receipt source_sha256 does not match acquisition source_sha256")
    if inputs.get("retained_sha256") != actual_retained_sha256:
        errors.append("receipt retained_sha256 does not match retained excerpt")
    source_path = acquisition.get("source_path")
    if inputs.get("source_path") != source_path:
        errors.append("receipt source_path does not match acquisition evidence")
    metadata = _tei_metadata(canonical_master, errors)
    if metadata is None:
        return
    expected_identity = {
        "work_id": metadata["work_id"],
        "textual_form_id": metadata["textual_form_id"],
        "edition_id": metadata["edition_id"],
        "acquisition_id": metadata["acquisition_id"],
    }
    if identity != expected_identity:
        errors.append("receipt identity does not match TEI header")
    for key in expected_identity:
        if identity.get(key) != expected_identity[key]:
            errors.append(f"receipt identity mismatch for {key}")
    if metadata["source_sha256"] != expected_source:
        errors.append("TEI source_sha256 does not match acquisition evidence")
    if metadata["source_url"] != acquisition.get("url"):
        errors.append("TEI source URL does not match acquisition evidence")
    if metadata["source_location"] != source_path:
        errors.append("TEI source location does not match acquisition evidence")
    if metadata["retained_sha256"] != actual_retained_sha256:
        errors.append("TEI retained sha256 does not match retained excerpt")
    if str(metadata["source_bytes"]) != str(acquisition.get("source_bytes")):
        errors.append("TEI source_bytes does not match acquisition evidence")
    work_path, work, edition = _find_edition_sidecar(root, identity, errors)
    if work is None or edition is None:
        return
    if edition.get("language") not in {None, "en"}:
        language: Any = edition.get("language")
    else:
        language = edition.get("language") or work.get("language")
    edition_title = edition.get("title")
    if not isinstance(edition_title, str) or not edition_title:
        errors.append("edition title is missing")
        edition_title = ""
    # The representation revision belongs to the TEI header, not the stable
    # edition identity sidecar.
    source_scope = metadata.get("source_scope")
    expected_rows, expected_anchors = _expected_rows(
        metadata,
        edition_title=edition_title,
        language=language,
        source_url=str(acquisition.get("url", "")),
        accessed_at=acquisition.get("accessed_at"),
        acquisition_id=str(identity.get("acquisition_id", "")),
        rights=acquisition.get("rights") if isinstance(acquisition.get("rights"), str) else None,
        errors=errors,
    )
    if rows != expected_rows:
        errors.append("public prose rows do not independently match accepted TEI")
    mapping = receipt.get("mapping")
    if not isinstance(mapping, dict) or mapping.get("category") != "prose":
        errors.append("receipt mapping category is not prose")
    elif mapping.get("version") != EXPECTED_MAPPING_VERSION:
        errors.append("receipt mapping version is unsupported")
    assembler = receipt.get("assembler")
    if not isinstance(assembler, dict) or assembler.get("version") != EXPECTED_ASSEMBLER_VERSION:
        errors.append("receipt assembler version is unsupported")
    receipt_anchors = mapping.get("anchors") if isinstance(mapping, dict) else None
    if receipt_anchors != expected_anchors:
        errors.append("receipt anchors do not independently match accepted TEI")
    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        errors.append("receipt outputs are not an object")
    else:
        if outputs.get("public_path") != _release_relative(release, rows_path := release / "public" / "data" / "prose" / "train.jsonl"):
            errors.append("receipt public_path does not point to public prose JSONL")
        if outputs.get("public_sha256") != sha256_bytes(rows_raw):
            errors.append("receipt public output hash mismatch")
        if outputs.get("row_count") != len(rows):
            errors.append("receipt public row_count mismatch")
        if outputs.get("text_hashes") != [anchor["text_sha256"] for anchor in expected_anchors]:
            errors.append("receipt text_hashes mismatch")
        if outputs.get("sequences") != [anchor["sequence"] for anchor in expected_anchors]:
            errors.append("receipt sequences mismatch")
    if receipt_path.name != f"{identity.get('edition_id')}.json":
        errors.append(f"receipt filename does not bind edition: {receipt_path.name}")


def _release_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _check_public_readme(public_root: Path, errors: list[str], private_values: list[str]) -> None:
    path = public_root / "README.md"
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read public README: {exc}")
        return
    if content != EXPECTED_README:
        errors.append("public README does not match the deterministic release card")
    for value in private_values:
        if value and value in content:
            errors.append(f"public README contains private evidence: {value}")
    for token in ("source_sha256", "master_path", "acquisition_path", "projection-receipts", "state.json"):
        if token in content:
            errors.append(f"public README contains private field: {token}")


def check_release(root: Path, release: Path) -> dict[str, Any]:
    """Independently verify a finished or in-progress local release tree."""

    root = Path(root).resolve()
    release = Path(release).resolve()
    errors: list[str] = []
    if not root.is_dir():
        errors.append(f"fixture root is missing: {root}")
    if not release.is_dir():
        errors.append(f"release root is missing: {release}")
    if errors:
        return {"status": "fail", "errors": errors}

    public_root = release / "public"
    internal_root = release / "internal"
    errors.extend(check_public_allowlist(public_root))
    rows_path = public_root / "data" / "prose" / "train.jsonl"
    rows, rows_raw = _load_rows(rows_path, errors)
    _check_public_readme(
        public_root,
        errors,
        [
            "source_sha256",
            "raw/ccel/npnf2/npnf204.xml",
            "retained/npnf204.vii.ii.i.thml.xml",
        ],
    )
    selection_path = internal_root / "release-selection.json"
    report_path = internal_root / "release-report.json"
    try:
        selection = _load_object(selection_path)
    except PipelineError as exc:
        errors.append(str(exc))
        selection = {}
    try:
        report = _load_object(report_path)
    except PipelineError as exc:
        errors.append(str(exc))
        report = {}
    if selection.get("categories") != ["prose"]:
        errors.append("release selection does not request prose")
    if selection.get("selection_version") != EXPECTED_SELECTION_VERSION:
        errors.append("unsupported release selection version")
    if not isinstance(selection.get("release_id"), str) or not selection["release_id"]:
        errors.append("release selection has no release_id")
    selection_items = selection.get("items")
    if not isinstance(selection_items, list) or not selection_items:
        errors.append("release selection has no items")
        selection_items = []
    valid_statuses = {"included", "warned", "failed", "excluded"}
    for item in selection_items:
        if not isinstance(item, dict):
            errors.append("release selection contains a non-object item")
            continue
        for key in ("work_id", "textual_form_id", "edition_id", "status"):
            if not isinstance(item.get(key), str) or not item[key]:
                errors.append(f"release selection item is missing {key}")
        if item.get("status") not in valid_statuses:
            errors.append(f"release selection item has unsupported status: {item.get('status')!r}")
        if not isinstance(item.get("selected"), bool):
            errors.append("release selection item selected flag must be boolean")
    selected_items = [item for item in selection_items if isinstance(item, dict) and item.get("selected") is True]
    if not selected_items:
        errors.append("release selection has no selected item")
    if len(selected_items) > 1:
        errors.append("PIPE-001 checker supports exactly one selected edition")
    accounting = selection.get("accounting")
    if not isinstance(accounting, dict):
        errors.append("release selection accounting is missing")
    else:
        expected_accounting = {
            "requested": len(selection_items),
            "selected": len(selected_items),
            "included": sum(1 for item in selection_items if isinstance(item, dict) and item.get("status") == "included"),
            "warned": sum(1 for item in selection_items if isinstance(item, dict) and item.get("status") == "warned"),
            "failed": sum(1 for item in selection_items if isinstance(item, dict) and item.get("status") == "failed"),
            "excluded": sum(1 for item in selection_items if isinstance(item, dict) and item.get("status") == "excluded"),
        }
        for key, expected in expected_accounting.items():
            if accounting.get(key) != expected:
                errors.append(f"release accounting {key} does not match selected items")
    receipts_dir = internal_root / "projection-receipts"
    receipt_paths = sorted(receipts_dir.glob("*.json")) if receipts_dir.is_dir() else []
    if not receipt_paths:
        errors.append("release has no projection receipt")
    if len(receipt_paths) != len(selected_items):
        errors.append("projection receipt count does not match selected item count")
    receipt_identities: set[tuple[Any, Any, Any, Any]] = set()
    for receipt_path in receipt_paths:
        try:
            receipt = _load_object(receipt_path)
        except PipelineError as exc:
            errors.append(str(exc))
            continue
        _check_receipt(
            root=root,
            release=release,
            receipt_path=receipt_path,
            receipt=receipt,
            rows=rows,
            rows_raw=rows_raw,
            errors=errors,
        )
        identity = receipt.get("identity")
        if isinstance(identity, dict):
            receipt_identities.add(
                tuple(identity.get(key) for key in ("work_id", "textual_form_id", "edition_id", "acquisition_id"))
            )
    selected_identity_keys = {
        (item.get("work_id"), item.get("textual_form_id"), item.get("edition_id"))
        for item in selected_items
    }
    receipt_identity_keys = {
        identity[:3] for identity in receipt_identities if all(value is not None for value in identity[:3])
    }
    if selected_identity_keys != receipt_identity_keys:
        errors.append("selected release identities do not match projection receipt identities")
    if report:
        if report.get("release_version") != EXPECTED_RELEASE_VERSION:
            errors.append("unsupported release report version")
        if report.get("requested_categories") != ["prose"]:
            errors.append("release report categories do not request prose")
        if report.get("items") != selection_items:
            errors.append("release report items do not match release selection")
        expected_receipt_paths = [_release_relative(release, path) for path in receipt_paths]
        if report.get("receipts") != expected_receipt_paths:
            errors.append("release report receipts do not match projection receipts")
        report_assembler = report.get("assembler")
        if not isinstance(report_assembler, dict) or report_assembler.get("version") != EXPECTED_ASSEMBLER_VERSION:
            errors.append("release report assembler version is unsupported")
        public = report.get("public")
        if not isinstance(public, dict):
            errors.append("release report public section is missing")
        else:
            if public.get("files") != ["README.md", "data/prose/train.jsonl"]:
                errors.append("release report public allowlist does not match")
            if public.get("row_count") != len(rows):
                errors.append("release report public row_count mismatch")
        if report.get("release_id") != selection.get("release_id"):
            errors.append("release report release_id does not match selection")
        if "status" in report and report.get("status") not in {"pass", "fail"}:
            errors.append("release report status is invalid")
    # The check result is recomputed above.  A stored receipt status is evidence
    # to inspect, never authority: pending is valid while the assembler is
    # calling this function, and a forged pass cannot suppress an error here.
    status = "pass" if not errors else "fail"
    return {
        "status": status,
        "errors": errors,
        "rows": len(rows),
        "receipts": len(receipt_paths),
        "accounting": selection.get("accounting", {}),
    }


verify_release = check_release


__all__ = ["check_release", "verify_release"]
