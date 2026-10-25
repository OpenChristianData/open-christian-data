"""LIB-022 producer for Torrey's New Topical Textbook."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib022-torreys-topical-textbook-jsonl-to-tei"
CONVERTER_VERSION = "1"
_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_SOURCE_ID = "jwbickel-bible-dictionaries-torreys-jsonl"
_WORK_ID = "torreys-topical-textbook"
_SOURCE_SHA = "8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c"
_RAW_MANIFEST_SHA = "3438b540e27f767ae4f0172a18ff466ed2d4ab5aed73a1b4af9755f92e52c37b"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _builtin(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _builtin(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_builtin(item) for item in value]
    return value


def _expected_scope() -> dict[str, object]:
    return {
        "source_order": {"ticket_order": 4, "raw_manifest_order": 4, "raw_manifest_path": "raw/bible_dictionaries/manifest.json"},
        "source_order_members": [
            {"local_filename": "eastons.jsonl", "source_id": "jwbickel-bible-dictionaries-eastons-jsonl", "ticket_id": "LIB-021", "work_id": "eastons-bible-dictionary", "disposition": "exclude", "reason": "Retained member belongs to LIB-021."},
            {"local_filename": "hitchcocks.jsonl", "source_id": "jwbickel-bible-dictionaries-hitchcocks-jsonl", "ticket_id": "LIB-021", "work_id": "hitchcocks-bible-names-dictionary", "disposition": "exclude", "reason": "Retained member belongs to LIB-021."},
            {"local_filename": "smiths.jsonl", "source_id": "jwbickel-bible-dictionaries-smiths-jsonl", "ticket_id": "LIB-021", "work_id": "smiths-bible-dictionary", "disposition": "exclude", "reason": "Retained member belongs to LIB-021."},
            {"local_filename": "torreys.jsonl", "source_id": _SOURCE_ID, "ticket_id": "LIB-022", "work_id": _WORK_ID, "bytes": 1036596, "sha256": _SOURCE_SHA, "records": 623, "definition_blocks": 23549, "disposition": "include", "reason": "Assigned LIB-022 member; every record and definition is represented in source order."},
        ],
        "retained_member_census": {"dataset_manifest_sha256": _RAW_MANIFEST_SHA, "retained": ["torreys.jsonl"], "excluded": ["eastons.jsonl", "hitchcocks.jsonl", "smiths.jsonl"]},
    }


def _validate_scope(record: Mapping[str, object]) -> None:
    expected = _expected_scope()
    observed = {name: _builtin(record.get(name)) for name in expected}
    if observed != expected:
        raise ValueError("LIB-022 retained source scope or sibling exclusions drifted")


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result
    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _records(content: bytes) -> tuple[tuple[int, bytes, dict[str, object]], ...]:
    result = []
    for line_no, line in enumerate(content.splitlines(keepends=True), 1):
        if not line.strip():
            raise ValueError(f"blank source line {line_no}")
        record = _strict(line, f"source record {line_no}")
        if set(record) != {"term", "definitions"}:
            raise ValueError(f"source record {line_no} fields drifted")
        term, definitions = record["term"], record["definitions"]
        if not isinstance(term, str) or not term or not isinstance(definitions, list) or not definitions or any(not isinstance(item, str) or not item for item in definitions):
            raise ValueError(f"source record {line_no} shape invalid")
        result.append((line_no, line, record))
    return tuple(result)


def _require_bindings(source: SourceManifest) -> tuple[dict[str, object], dict[str, object], bytes]:
    if source.record.get("source_id") != _SOURCE_ID or source.record.get("work_id") != _WORK_ID or source.record.get("ticket_id") != "LIB-022":
        raise ValueError("LIB-022 source binding mismatch")
    _validate_scope(source.record)
    raw = source.authority_path("bible-dictionaries-manifest").read_bytes()
    if _sha(raw) != _RAW_MANIFEST_SHA:
        raise ValueError("retained dataset manifest hash drifted")
    source_bytes = source.authority_path("torreys-jsonl").read_bytes()
    if _sha(source_bytes) != _SOURCE_SHA or len(source_bytes) != 1036596:
        raise ValueError("retained Torrey source hash or size drifted")
    profile = _strict(source.authority_path("reconstruction-profile").read_bytes(), "profile")
    policy = _strict(source.authority_path("validation-policy").read_bytes(), "policy")
    if profile.get("profile_id") != "torreys-topical-textbook-jwbickel-jsonl-v1" or policy.get("policy_id") != "torreys-topical-textbook-jwbickel-jsonl-policy-v1":
        raise ValueError("profile or policy identity drifted")
    return profile, policy, source_bytes


def _tei(profile: Mapping[str, object], records: tuple[tuple[int, bytes, dict[str, object]], ...]) -> bytes:
    root = etree.Element(f"{{{_NS}}}TEI", nsmap={None: _NS})
    root.set(_XML_ID, f"{_WORK_ID}-candidate")
    header = etree.SubElement(root, f"{{{_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{_NS}}}title").text = str(profile["identity"]["title"])
    pub = etree.SubElement(file_desc, f"{{{_NS}}}publicationStmt")
    etree.SubElement(pub, f"{{{_NS}}}p").text = "Nonaccepted candidate; publication is not authorized."
    source_desc = etree.SubElement(file_desc, f"{{{_NS}}}sourceDesc")
    etree.SubElement(source_desc, f"{{{_NS}}}p").text = "JWBickel/BibleDictionaries retained TorreysTopicalTextbook.jsonl."
    text = etree.SubElement(root, f"{{{_NS}}}text")
    body = etree.SubElement(text, f"{{{_NS}}}body")
    for ordinal, (_, _, record) in enumerate(records, 1):
        entry = etree.SubElement(body, f"{{{_NS}}}entry", {_XML_ID: f"{_WORK_ID}-entry-{ordinal:05d}"})
        form = etree.SubElement(entry, f"{{{_NS}}}form")
        etree.SubElement(form, f"{{{_NS}}}orth").text = record["term"]
        for block, definition in enumerate(record["definitions"], 1):
            sense = etree.SubElement(entry, f"{{{_NS}}}sense", {_XML_ID: f"{_WORK_ID}-entry-{ordinal:05d}-sense-{block:03d}"})
            etree.SubElement(sense, f"{{{_NS}}}def", {_XML_ID: f"{_WORK_ID}-entry-{ordinal:05d}-definition-{block:03d}"}).text = definition
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False, with_tail=False)


def _unresolved() -> bytes:
    rows = [
        {"id": f"{_WORK_ID}-edition-identity", "scope": "work", "status": "unresolved", "question": "Which historical edition or witness does the retained structured member represent?", "consequence": "candidate remains nonaccepted"},
        {"id": f"{_WORK_ID}-structured-source-rights", "scope": "source-member", "status": "unresolved", "question": "What license, if any, governs the modern JWBickel structured JSONL?", "consequence": "publication is not authorized"},
        {"id": f"{_WORK_ID}-textual-reference-review", "scope": "definitions", "status": "unresolved", "question": "Should embedded citation-looking strings receive later editorial review?", "consequence": "literal source text remains authoritative"},
    ]
    return b"".join(_canonical(row) for row in rows)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    profile, policy, source_bytes = _require_bindings(source_manifest)
    records = _records(source_bytes)
    if len(records) != 623 or sum(len(record[2]["definitions"]) for record in records) != 23549:
        raise ValueError("retained source census drifted")
    crosswalk = []
    for ordinal, (line_no, line, record) in enumerate(records, 1):
        entry_id = f"#{_WORK_ID}-entry-{ordinal:05d}"
        crosswalk.append({"id": f"{_WORK_ID}-entry-{ordinal:05d}", "kind": "entry", "source_line": line_no, "source_record_sha256": _sha(line), "source_field": "term", "source_index": 0, "source_term": record["term"], "value": record["term"], "target": entry_id, "status": "represented"})
        for index, definition in enumerate(record["definitions"], 1):
            crosswalk.append({"id": f"{_WORK_ID}-entry-{ordinal:05d}-definition-{index:03d}", "kind": "definition", "source_line": line_no, "source_record_sha256": _sha(line), "source_field": "definitions", "source_index": index, "source_term": record["term"], "value": definition, "target": f"{entry_id}-definition-{index:03d}", "status": "represented"})
    accountability = {"contract": "ocd-torreys-topical-textbook-source-accountability-v1", "schema": "sources/torreys-topical-textbook/torreys-topical-textbook.source-accountability.schema.json", "profile_id": profile["profile_id"], "work_id": _WORK_ID, "source_id": _SOURCE_ID, "source_sha256": _SOURCE_SHA, "source_record_count": 623, "definition_block_count": 23549, "observation_counts": {"records": 623, "definition_blocks": 23549, "total": 24172, "represented": 24172, "omitted": 0, "duplicate": 0}, "crosswalk": crosswalk}
    provenance = {"contract": "ocd-lib022-torreys-topical-textbook-candidate-provenance-v1", "ticket_id": "LIB-022", "work_id": _WORK_ID, "source_id": _SOURCE_ID, "source_sha256": _SOURCE_SHA, "source_manifest_sha256": source_manifest.sha256, "candidate_boundary": {"status": "nonaccepted", "publication": "not_ready", "canonical_writes": False}, "attribution": "Credit JWBickel/BibleDictionaries and link the retained dataset URL.", "profile_id": profile["profile_id"], "policy_id": policy["policy_id"]}
    return {"content.tei.xml": _tei(profile, records), "source-accountability.json": _canonical(accountability), "provenance.json": _canonical(provenance), "unresolved.jsonl": _unresolved(), "README.source.md": source_manifest.authority_path("source-attribution-readme").read_bytes()}


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
