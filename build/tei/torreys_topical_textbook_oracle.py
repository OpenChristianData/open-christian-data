"""Independent LIB-022 oracle; it never imports or calls the producer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib022-torreys-topical-textbook-independent-oracle"
ORACLE_VERSION = "1"
_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_WORK_ID = "torreys-topical-textbook"
_SOURCE_ID = "jwbickel-bible-dictionaries-torreys-jsonl"
_SOURCE_SHA = "8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c"


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
        "retained_member_census": {"dataset_manifest_sha256": "3438b540e27f767ae4f0172a18ff466ed2d4ab5aed73a1b4af9755f92e52c37b", "retained": ["torreys.jsonl"], "excluded": ["eastons.jsonl", "hitchcocks.jsonl", "smiths.jsonl"]},
    }


def _validate_scope(record: Mapping[str, object]) -> None:
    expected = _expected_scope()
    observed = {name: _builtin(record.get(name)) for name in expected}
    if observed != expected:
        raise ValueError("LIB-022 retained source scope or sibling exclusions drifted")


def _json(content: bytes, label: str) -> dict[str, object]:
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


def _source_records(content: bytes) -> list[tuple[int, bytes, dict[str, object]]]:
    rows = []
    for line_no, line in enumerate(content.splitlines(keepends=True), 1):
        if not line.strip():
            raise ValueError(f"blank source line {line_no}")
        row = _json(line, f"source record {line_no}")
        if set(row) != {"term", "definitions"} or not isinstance(row["term"], str) or not isinstance(row["definitions"], list):
            raise ValueError(f"source record {line_no} shape drifted")
        rows.append((line_no, line, row))
    return rows


def _closure(root: Path) -> str:
    paths = {
        Path(__file__).resolve(strict=True),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    }
    records = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())}
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    ]
    return _sha(_canonical(records))


def _assert_text_only(element: etree._Element, expected: str) -> None:
    if element.text != expected or len(element) != 0 or element.tail not in (None, ""):
        raise ValueError(f"Torrey TEI term or definition/header text or child structure drifted on {element.tag}")


def _assert_attrs(element: etree._Element, expected: dict[str, str]) -> None:
    if dict(element.attrib) != expected:
        raise ValueError(f"Torrey TEI attributes drifted on {element.tag}")


def _verify_tei(source: SourceManifest, candidate: CandidatePackage, rows: list[tuple[int, bytes, dict[str, object]]]) -> None:
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
        schema = etree.XMLSchema(etree.parse(str(source.authority_path("tei-p5-xsd"))))
        schema.assertValid(root)
    except etree.LxmlError as exc:
        raise ValueError("Torrey candidate TEI failed direct P5 XSD validation") from exc
    if root.tag != f"{{{_NS}}}TEI" or root.get(_XML_ID) != "torreys-topical-textbook-candidate" or len(root) != 2:
        raise ValueError("TEI root identity or top-level structure drifted")
    _assert_attrs(root, {_XML_ID: "torreys-topical-textbook-candidate"})
    header, text = list(root)
    if header.tag != f"{{{_NS}}}teiHeader" or text.tag != f"{{{_NS}}}text":
        raise ValueError("TEI top-level structure drifted")
    if len(header) != 1 or header[0].tag != f"{{{_NS}}}fileDesc":
        raise ValueError("TEI header structure drifted")
    file_desc = header[0]
    if [item.tag for item in list(file_desc)] != [
        f"{{{_NS}}}titleStmt",
        f"{{{_NS}}}publicationStmt",
        f"{{{_NS}}}sourceDesc",
    ]:
        raise ValueError("TEI file description structure drifted")
    title_stmt, publication_stmt, source_desc = list(file_desc)
    if len(title_stmt) != 1 or title_stmt[0].tag != f"{{{_NS}}}title":
        raise ValueError("TEI title statement structure drifted")
    _assert_attrs(title_stmt, {})
    _assert_attrs(title_stmt[0], {})
    _assert_text_only(title_stmt[0], "Torrey's New Topical Textbook")
    if len(publication_stmt) != 1 or publication_stmt[0].tag != f"{{{_NS}}}p":
        raise ValueError("TEI publication statement structure drifted")
    _assert_attrs(publication_stmt, {})
    _assert_text_only(publication_stmt[0], "Nonaccepted candidate; publication is not authorized.")
    if len(source_desc) != 1 or source_desc[0].tag != f"{{{_NS}}}p":
        raise ValueError("TEI source description structure drifted")
    _assert_attrs(source_desc, {})
    _assert_text_only(source_desc[0], "JWBickel/BibleDictionaries retained TorreysTopicalTextbook.jsonl.")
    if len(text) != 1 or text[0].tag != f"{{{_NS}}}body":
        raise ValueError("TEI text structure drifted")
    body = text[0]
    ns = {"tei": _NS}
    entries = body.xpath("./tei:entry", namespaces=ns)
    if len(entries) != len(rows):
        raise ValueError("TEI entry census drifted")
    for ordinal, ((line_no, _, record), entry) in enumerate(zip(rows, entries, strict=True), 1):
        expected_entry = f"torreys-topical-textbook-entry-{ordinal:05d}"
        _assert_attrs(entry, {_XML_ID: expected_entry})
        if len(entry) != 1 + len(record["definitions"]):
            raise ValueError(f"entry {ordinal} ID drifted")
        if entry[0].tag != f"{{{_NS}}}form":
            raise ValueError(f"entry {ordinal} form structure drifted")
        _assert_attrs(entry[0], {})
        if len(entry[0]) != 1 or entry[0][0].tag != f"{{{_NS}}}orth":
            raise ValueError(f"entry {ordinal} form structure drifted")
        _assert_attrs(entry[0][0], {})
        _assert_text_only(entry[0][0], record["term"])
        orth = entry.xpath("./tei:form/tei:orth", namespaces=ns)
        senses = entry.xpath("./tei:sense", namespaces=ns)
        if len(orth) != 1 or orth[0].text != record["term"] or len(senses) != len(record["definitions"]):
            raise ValueError(f"entry {ordinal} term or definition census drifted at source line {line_no}")
        for index, (sense, definition) in enumerate(zip(senses, record["definitions"], strict=True), 1):
            expected_sense = f"{expected_entry}-sense-{index:03d}"
            _assert_attrs(sense, {_XML_ID: expected_sense})
            if len(sense) != 1:
                raise ValueError("sense ID drifted")
            defs = sense.xpath("./tei:def", namespaces=ns)
            if len(defs) != 1 or defs[0].text != definition or defs[0].get(_XML_ID) != f"{expected_entry}-definition-{index:03d}":
                raise ValueError("definition text or ID drifted")
            _assert_attrs(defs[0], {_XML_ID: f"{expected_entry}-definition-{index:03d}"})
            _assert_text_only(defs[0], definition)


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    if record.get("source_id") != "jwbickel-bible-dictionaries-torreys-jsonl" or record.get("ticket_id") != "LIB-022":
        raise ValueError("LIB-022 source binding drifted")
    _validate_scope(record)
    source_bytes = source_manifest.authority_path("torreys-jsonl").read_bytes()
    if _sha(source_bytes) != _SOURCE_SHA:
        raise ValueError("source hash drifted")
    rows = _source_records(source_bytes)
    if len(rows) != 623 or sum(len(row[2]["definitions"]) for row in rows) != 23549:
        raise ValueError("source counts drifted")
    profile = _json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile")
    policy = _json(source_manifest.authority_path("validation-policy").read_bytes(), "policy")
    schema = _json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "accountability schema")
    accountability = _json(candidate.member_bytes("source-accountability.json"), "accountability")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"accountability schema failure: {errors[0].message}")
    if accountability.get("source_sha256") != _SOURCE_SHA or accountability.get("observation_counts") != {"records": 623, "definition_blocks": 23549, "total": 24172, "represented": 24172, "omitted": 0, "duplicate": 0}:
        raise ValueError("accountability binding drifted")
    crosswalk = accountability.get("crosswalk")
    if not isinstance(crosswalk, list):
        raise ValueError("accountability crosswalk missing")
    expected_crosswalk = []
    for ordinal, (line_no, line, row) in enumerate(rows, 1):
        entry = f"#torreys-topical-textbook-entry-{ordinal:05d}"
        expected_crosswalk.append({"id": f"torreys-topical-textbook-entry-{ordinal:05d}", "kind": "entry", "source_line": line_no, "source_record_sha256": _sha(line), "source_field": "term", "source_index": 0, "source_term": row["term"], "value": row["term"], "target": entry, "status": "represented"})
        for index, definition in enumerate(row["definitions"], 1):
            expected_crosswalk.append({"id": f"torreys-topical-textbook-entry-{ordinal:05d}-definition-{index:03d}", "kind": "definition", "source_line": line_no, "source_record_sha256": _sha(line), "source_field": "definitions", "source_index": index, "source_term": row["term"], "value": definition, "target": f"{entry}-definition-{index:03d}", "status": "represented"})
    if crosswalk != expected_crosswalk:
        raise ValueError("accountability crosswalk drifted")
    if profile.get("identity", {}).get("title") != "Torrey's New Topical Textbook" or policy.get("candidate_status") != "nonaccepted":
        raise ValueError("profile or policy drifted")
    _verify_tei(source_manifest, candidate, rows)
    package_schema_bytes = source_manifest.authority_path("candidate-package-schema").read_bytes()
    package_schema = _json(package_schema_bytes, "candidate package schema")
    manifest = _json((candidate.path / "manifest.json").read_bytes(), "candidate manifest")
    manifest_errors = sorted(Draft202012Validator(package_schema).iter_errors(manifest), key=str)
    if manifest_errors:
        raise ValueError(f"candidate manifest schema failure: {manifest_errors[0].message}")
    expected_members = [
        {"name": name, "bytes": len(candidate.member_bytes(name)), "sha256": _sha(candidate.member_bytes(name))}
        for name in sorted(("README.source.md", "content.tei.xml", "provenance.json", "source-accountability.json", "unresolved.jsonl"))
    ]
    expected_manifest = {
        "contract": "ocd-candidate-package-v1",
        "status": "nonaccepted",
        "source_id": record["source_id"],
        "source_manifest": {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "converter": dict(record["converter"]),
        "package_schema": dict(record["package_schema"]),
        "members": expected_members,
    }
    if manifest != expected_manifest:
        raise ValueError("candidate manifest binding drifted")
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {
        "contract": "ocd-lib022-torreys-topical-textbook-candidate-provenance-v1",
        "ticket_id": "LIB-022",
        "work_id": _WORK_ID,
        "source_id": _SOURCE_ID,
        "source_sha256": _SOURCE_SHA,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_boundary": {"status": "nonaccepted", "publication": "not_ready", "canonical_writes": False},
        "attribution": "Credit JWBickel/BibleDictionaries and link the retained dataset URL.",
        "profile_id": profile["profile_id"],
        "policy_id": policy["policy_id"],
    }
    if provenance != expected_provenance or candidate.member_bytes("provenance.json") != _canonical(expected_provenance):
        raise ValueError("provenance or publication boundary drifted")
    expected_unresolved = [
        {"id": f"{_WORK_ID}-edition-identity", "scope": "work", "status": "unresolved", "question": "Which historical edition or witness does the retained structured member represent?", "consequence": "candidate remains nonaccepted"},
        {"id": f"{_WORK_ID}-structured-source-rights", "scope": "source-member", "status": "unresolved", "question": "What license, if any, governs the modern JWBickel structured JSONL?", "consequence": "publication is not authorized"},
        {"id": f"{_WORK_ID}-textual-reference-review", "scope": "definitions", "status": "unresolved", "question": "Should embedded citation-looking strings receive later editorial review?", "consequence": "literal source text remains authoritative"},
    ]
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in expected_unresolved):
        raise ValueError("unresolved evidence drifted")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("attribution README drifted")
    validator = record.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("validator binding drifted")
    closure = _closure(source_manifest.repository_root)
    if closure != validator.get("import_closure_sha256"):
        raise ValueError("Torrey oracle import closure drifted")
    result = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": "python-3.14-lxml-jsonschema", "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256, "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        "package_schema_sha256": _sha(package_schema_bytes),
        "source_sha256": _SOURCE_SHA, "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(source_manifest.authority_path("validation-policy").read_bytes()), "findings": [],
    }
    result["runtime"] = f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
