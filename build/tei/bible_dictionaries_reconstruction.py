"""Deterministic LIB-021 JSONL dictionary to TEI candidate producer.

The producer reads only the authority paths in the source manifest.  It keeps
the retained JSONL records as the source of truth: each record becomes one TEI
entry, each ``definitions`` item remains one ordered definition block, and
reference-looking text remains literal because the retained source has no
structured reference field.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib021-bible-dictionaries-jsonl-to-tei"
CONVERTER_VERSION = "1"
_TICKET_ID = "LIB-021"
_DATASET = "JWBickel/BibleDictionaries"
_DATASET_URL = "https://huggingface.co/datasets/JWBickel/BibleDictionaries"
_RAW_MANIFEST_PATH = "raw/bible_dictionaries/manifest.json"
_RAW_MANIFEST_SHA256 = (
    "3438b540e27f767ae4f0172a18ff466ed2d4ab5aed73a1b4af9755f92e52c37b"
)
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


_SOURCE_MEMBERS: tuple[dict[str, object], ...] = (
    {
        "source_id": "jwbickel-bible-dictionaries-eastons-jsonl",
        "local_filename": "eastons.jsonl",
        "hf_filename": "Easton's Bible Dictionary.jsonl",
        "source_url": f"{_DATASET_URL}/resolve/main/Easton's Bible Dictionary.jsonl",
        "download_date": "2026-03-30T08:32:28Z",
        "bytes": 2690740,
        "sha256": "978e09fdb66e9c6b722085f868c0cc84030df9e15c6188a06390f3822888082a",
        "records": 3963,
        "definition_blocks": 7464,
        "block_count_min": 1,
        "block_count_max": 27,
        "term_characters": 30624,
        "definition_characters": 2497386,
        "duplicate_terms": [
            {"term": "Kadesh", "occurrences": 2},
            {"term": "Salmon", "occurrences": 2},
        ],
        "ticket_id": _TICKET_ID,
        "work_id": "eastons-bible-dictionary",
        "raw_manifest_order": 1,
    },
    {
        "source_id": "jwbickel-bible-dictionaries-hitchcocks-jsonl",
        "local_filename": "hitchcocks.jsonl",
        "hf_filename": "Hitchcock's Bible Names Dictionary.jsonl",
        "source_url": f"{_DATASET_URL}/resolve/main/Hitchcock's Bible Names Dictionary.jsonl",
        "download_date": "2026-03-30T08:32:31Z",
        "bytes": 164940,
        "sha256": "e25b127cfc9c6f6f14eb9aa059ea0b3ed7ceaf97e2fd88c192d74387c3e904a5",
        "records": 2622,
        "definition_blocks": 2622,
        "block_count_min": 1,
        "block_count_max": 1,
        "term_characters": 17563,
        "definition_characters": 58229,
        "duplicate_terms": [
            {"term": "Abel", "occurrences": 2},
            {"term": "Eli", "occurrences": 2},
            {"term": "Noah", "occurrences": 2},
            {"term": "Rahab", "occurrences": 2},
        ],
        "ticket_id": _TICKET_ID,
        "work_id": "hitchcocks-bible-names-dictionary",
        "raw_manifest_order": 2,
    },
    {
        "source_id": "jwbickel-bible-dictionaries-smiths-jsonl",
        "local_filename": "smiths.jsonl",
        "hf_filename": "Smith's Bible Dictionary.jsonl",
        "source_url": f"{_DATASET_URL}/resolve/main/Smith's Bible Dictionary.jsonl",
        "download_date": "2026-03-30T08:32:35Z",
        "bytes": 2919477,
        "sha256": "ac91b1c3c359690c2953bd94b9d3dcb34f012a69d734179e82be5f07866cbe0d",
        "records": 4560,
        "definition_blocks": 5362,
        "block_count_min": 1,
        "block_count_max": 6,
        "term_characters": 36340,
        "definition_characters": 2718707,
        "duplicate_terms": [],
        "ticket_id": _TICKET_ID,
        "work_id": "smiths-bible-dictionary",
        "raw_manifest_order": 3,
    },
    {
        "source_id": "jwbickel-bible-dictionaries-torreys-jsonl",
        "local_filename": "torreys.jsonl",
        "hf_filename": "TorreysTopicalTextbook.jsonl",
        "source_url": f"{_DATASET_URL}/resolve/main/TorreysTopicalTextbook.jsonl",
        "download_date": "2026-03-30T08:32:38Z",
        "bytes": 1036596,
        "sha256": "8211c20290e951f60e21187e3bdaea639c8cf59343675b6518c6c17423906a1c",
        "records": 623,
        "definition_blocks": 23549,
        "block_count_min": 2,
        "block_count_max": 215,
        "term_characters": 8314,
        "definition_characters": 915386,
        "duplicate_terms": [
            {"term": "Communion With God", "occurrences": 2},
            {"term": "Early Rising", "occurrences": 2},
        ],
        "ticket_id": "LIB-022",
        "work_id": "torreys-topical-textbook",
        "raw_manifest_order": 4,
    },
)

_WORKS: dict[str, dict[str, object]] = {
    "jwbickel-bible-dictionaries-eastons-jsonl": {
        "work_id": "eastons-bible-dictionary",
        "title": "Easton's Bible Dictionary",
        "profile_id": "eastons-bible-dictionary-jwbickel-jsonl-v1",
        "policy_id": "eastons-bible-dictionary-jwbickel-jsonl-policy-v1",
        "accountability_contract": "ocd-eastons-bible-dictionary-source-accountability-v1",
        "profile_contract": "ocd-eastons-bible-dictionary-reconstruction-profile-v1",
        "policy_contract": "ocd-eastons-bible-dictionary-validation-policy-v1",
        "ticket_order": 1,
    },
    "jwbickel-bible-dictionaries-hitchcocks-jsonl": {
        "work_id": "hitchcocks-bible-names-dictionary",
        "title": "Hitchcock's Bible Names Dictionary",
        "profile_id": "hitchcocks-bible-names-dictionary-jwbickel-jsonl-v1",
        "policy_id": "hitchcocks-bible-names-dictionary-jwbickel-jsonl-policy-v1",
        "accountability_contract": "ocd-hitchcocks-bible-names-dictionary-source-accountability-v1",
        "profile_contract": "ocd-hitchcocks-bible-names-dictionary-reconstruction-profile-v1",
        "policy_contract": "ocd-hitchcocks-bible-names-dictionary-validation-policy-v1",
        "ticket_order": 2,
    },
    "jwbickel-bible-dictionaries-smiths-jsonl": {
        "work_id": "smiths-bible-dictionary",
        "title": "Smith's Bible Dictionary",
        "profile_id": "smiths-bible-dictionary-jwbickel-jsonl-v1",
        "policy_id": "smiths-bible-dictionary-jwbickel-jsonl-policy-v1",
        "accountability_contract": "ocd-smiths-bible-dictionary-source-accountability-v1",
        "profile_contract": "ocd-smiths-bible-dictionary-reconstruction-profile-v1",
        "policy_contract": "ocd-smiths-bible-dictionary-validation-policy-v1",
        "ticket_order": 3,
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
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


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _source_member(source_id: str) -> dict[str, object]:
    for member in _SOURCE_MEMBERS:
        if member["source_id"] == source_id:
            return dict(member)
    raise ValueError(f"unknown LIB-021 source id: {source_id}")


def _scope_record(member: Mapping[str, object], *, included: bool) -> dict[str, object]:
    result = {
        "source_id": member["source_id"],
        "local_filename": member["local_filename"],
        "hf_filename": member["hf_filename"],
        "source_url": member["source_url"],
        "download_date": member["download_date"],
        "raw_manifest_order": member["raw_manifest_order"],
        "ticket_id": member["ticket_id"],
        "work_id": member["work_id"],
        "bytes": member["bytes"],
        "sha256": member["sha256"],
        "records": member["records"],
        "definition_blocks": member["definition_blocks"],
        "block_count_min": member["block_count_min"],
        "block_count_max": member["block_count_max"],
        "term_characters": member["term_characters"],
        "definition_characters": member["definition_characters"],
        "duplicate_terms": member["duplicate_terms"],
        "exact_keys": ["definitions", "term"],
        "blank_lines": 0,
        "line_ending": "LF",
        "ends_with_newline": True,
        "disposition": "include" if included else "exclude",
    }
    if included:
        result["reason"] = (
            "Assigned LIB-021 work member; retain every non-empty JSONL record "
            "and every definitions block in source order."
        )
    elif member["ticket_id"] == "LIB-022":
        result["reason"] = (
            "Outside LIB-021; assigned to LIB-022 topical-reference scope."
        )
    else:
        result["reason"] = (
            f"Outside this work route; retained by its separate {member['ticket_id']} "
            f"work route for {member['work_id']}."
        )
    return result


def _full_scope(source_id: str) -> list[dict[str, object]]:
    current = _source_member(source_id)
    return [
        _scope_record(member, included=member["source_id"] == current["source_id"])
        for member in _SOURCE_MEMBERS
    ]


def _profile_scope(source_id: str) -> dict[str, object]:
    current = _source_member(source_id)
    full = _full_scope(source_id)
    return {
        "dataset": _DATASET,
        "dataset_url": _DATASET_URL,
        "dataset_manifest": {
            "path": _RAW_MANIFEST_PATH,
            "sha256": _RAW_MANIFEST_SHA256,
        },
        "member_census": full,
        "retained_member": next(
            item for item in full if item["disposition"] == "include"
        ),
        "excluded_members": [item for item in full if item["disposition"] == "exclude"],
        "jsonl_record_rule": "Every non-empty physical JSONL line is one source record.",
        "top_level_fields": ["definitions", "term"],
        "record_shape": {
            "term": "non-empty string preserved exactly",
            "definitions": "non-empty ordered array of strings preserved exactly",
        },
        "observation_counts": {
            "records": current["records"],
            "definition_blocks": current["definition_blocks"],
            "total": int(current["records"]) + int(current["definition_blocks"]),
        },
    }


def _profile_and_policy(
    source_manifest: SourceManifest,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    source_id = str(source_manifest.record.get("source_id"))
    spec = _WORKS.get(source_id)
    if spec is None:
        raise ValueError("source manifest is not an assigned LIB-021 dictionary route")
    if (
        source_manifest.record.get("ticket_id") != _TICKET_ID
        or source_manifest.record.get("work_id") != spec["work_id"]
    ):
        raise ValueError("source manifest ticket/work binding mismatch")
    profile = _strict_json(
        source_manifest.authority_path("reconstruction-profile").read_bytes(),
        "reconstruction profile",
    )
    policy = _strict_json(
        source_manifest.authority_path("validation-policy").read_bytes(),
        "validation policy",
    )
    raw_manifest = _strict_json(
        source_manifest.authority_path(
            "jwbickel-bible-dictionaries-manifest"
        ).read_bytes(),
        "retained dataset manifest",
    )
    if (
        profile.get("profile_id") != spec["profile_id"]
        or profile.get("contract") != spec["profile_contract"]
    ):
        raise ValueError("reconstruction profile identity mismatch")
    if (
        policy.get("policy_id") != spec["policy_id"]
        or policy.get("contract") != spec["policy_contract"]
    ):
        raise ValueError("validation policy identity mismatch")
    return spec, profile, {"policy": policy, "raw_manifest": raw_manifest}


def _verify_frozen_claims(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    policy: Mapping[str, object],
    raw_manifest: Mapping[str, object],
) -> dict[str, object]:
    source_id = str(source_manifest.record["source_id"])
    current = _source_member(source_id)
    expected_full = _full_scope(source_id)
    if (
        _sha(
            source_manifest.authority_path(
                "jwbickel-bible-dictionaries-manifest"
            ).read_bytes()
        )
        != _RAW_MANIFEST_SHA256
    ):
        raise ValueError("retained dataset manifest is not the frozen source claim")
    if raw_manifest.get("source") != _DATASET or raw_manifest.get("files") != [
        {
            "hf_filename": member["hf_filename"],
            "local_filename": member["local_filename"],
            "source_url": member["source_url"],
            "file_size_bytes": member["bytes"],
            "sha256": member["sha256"],
            "download_date": member["download_date"],
        }
        for member in _SOURCE_MEMBERS
    ]:
        raise ValueError("retained dataset manifest member order or claim drifted")
    if source_manifest.record.get("source_order") != {
        "ticket_order": current["raw_manifest_order"],
        "raw_manifest_order": current["raw_manifest_order"],
        "raw_manifest_path": _RAW_MANIFEST_PATH,
    }:
        raise ValueError("source manifest source-order claim drifted")
    if _plain(source_manifest.record.get("source_order_members")) != expected_full:
        raise ValueError("source manifest complete source census drifted")
    retained_census = _plain(source_manifest.record.get("retained_member_census"))
    if not isinstance(retained_census, dict) or retained_census != {
        "dataset_manifest_sha256": _RAW_MANIFEST_SHA256,
        "retained": [
            next(item for item in expected_full if item["disposition"] == "include")
        ],
        "excluded": [
            item for item in expected_full if item["disposition"] == "exclude"
        ],
    }:
        raise ValueError("source manifest retained-member census drifted")
    source_scope = profile.get("source_scope")
    if (
        not isinstance(source_scope, Mapping)
        or source_scope.get("member_census") != expected_full
    ):
        raise ValueError("reconstruction profile source census drifted")
    if source_scope.get("retained_member") != next(
        item for item in expected_full if item["disposition"] == "include"
    ):
        raise ValueError("reconstruction profile retained member drifted")
    expected_counts = {
        "records": current["records"],
        "definition_blocks": current["definition_blocks"],
        "total": int(current["records"]) + int(current["definition_blocks"]),
    }
    if source_scope.get("observation_counts") != expected_counts:
        raise ValueError("reconstruction profile counts drifted")
    if policy.get("required_source_order") != [
        member["local_filename"] for member in expected_full
    ]:
        raise ValueError("validation policy source order drifted")
    if policy.get("required_counts") != {
        "records": current["records"],
        "definition_blocks": current["definition_blocks"],
        "observations": int(current["records"]) + int(current["definition_blocks"]),
        "unresolved_rows": 3,
    }:
        raise ValueError("validation policy counts drifted")
    return current


def _read_records(source: bytes) -> tuple[tuple[int, bytes, dict[str, object]], ...]:
    records: list[tuple[int, bytes, dict[str, object]]] = []
    for line_number, line_bytes in enumerate(source.splitlines(keepends=True), start=1):
        if not line_bytes.strip():
            raise ValueError(f"source JSONL has an empty line at {line_number}")
        try:
            record = _strict_json(line_bytes, f"source record {line_number}")
        except ValueError as exc:
            raise ValueError(f"source JSONL record {line_number} is invalid") from exc
        if set(record) != {"term", "definitions"}:
            raise ValueError(f"source JSONL record {line_number} has unexpected fields")
        term = record["term"]
        definitions = record["definitions"]
        if not isinstance(term, str) or not term:
            raise ValueError(f"source JSONL record {line_number} has an invalid term")
        if (
            not isinstance(definitions, list)
            or not definitions
            or any(not isinstance(value, str) or not value for value in definitions)
        ):
            raise ValueError(
                f"source JSONL record {line_number} has invalid definitions"
            )
        records.append((line_number, line_bytes, record))
    return tuple(records)


def _entry_id(work_id: str, ordinal: int) -> str:
    return f"{work_id}-entry-{ordinal:05d}"


def _definition_id(work_id: str, ordinal: int, block: int) -> str:
    return f"{work_id}-entry-{ordinal:05d}-definition-{block:03d}"


def _qname(local: str) -> str:
    return f"{{{_TEI_NS}}}{local}"


def _element(
    parent: etree._Element, local: str, *, text: str | None = None, **attributes: str
) -> etree._Element:
    node = etree.SubElement(parent, _qname(local), attributes)
    if text is not None:
        node.text = text
    return node


def _tei(
    source_manifest: SourceManifest,
    profile: Mapping[str, object],
    current: Mapping[str, object],
    records: tuple[tuple[int, bytes, dict[str, object]], ...],
) -> bytes:
    work_id = str(source_manifest.record["work_id"])
    title = str(profile["identity"]["title"])
    source_member = profile["source_scope"]["retained_member"]
    assert isinstance(source_member, Mapping)
    root = etree.Element(_qname("TEI"), nsmap={None: _TEI_NS})
    root.set(_XML_ID, f"{work_id}-candidate")
    header = _element(root, "teiHeader")
    file_desc = _element(header, "fileDesc")
    title_stmt = _element(file_desc, "titleStmt")
    _element(title_stmt, "title", text=title)
    publication = _element(file_desc, "publicationStmt")
    _element(publication, "publisher", text="Open Christian Data")
    availability = _element(publication, "availability", status="restricted")
    _element(
        availability,
        "p",
        text="Nonaccepted candidate only; publication is not authorized while source rights and identity remain under human review.",
    )
    source_desc = _element(file_desc, "sourceDesc")
    list_bibl = _element(source_desc, "listBibl", type="retained-source-order")
    bibl = _element(list_bibl, "bibl", **{_XML_ID: f"{work_id}-retained-source"})
    _element(bibl, "title", text=str(source_member["hf_filename"]))
    _element(bibl, "ptr", target=str(source_member["source_url"]))
    _element(bibl, "idno", text=str(source_member["sha256"]), type="sha256")
    _element(bibl, "num", text=str(source_member["bytes"]), type="bytes")
    _element(bibl, "num", text=str(source_member["records"]), type="records")
    _element(
        bibl,
        "num",
        text=str(source_member["definition_blocks"]),
        type="definition-blocks",
    )
    _element(
        bibl,
        "note",
        text="Ticket source order 1-3 is Easton, Hitchcock, Smith; Torrey is source order 4 and belongs to LIB-022.",
        type="source-order",
    )
    _element(
        bibl,
        "note",
        text="The retained JSONL source has only term and definitions fields; inline reference-looking text remains literal definition text.",
        type="field-census",
    )
    encoding = _element(header, "encodingDesc")
    _element(
        encoding,
        "p",
        text="Every retained JSONL record is represented once in source order. Each definitions array item remains one ordered definition block; no alternate terms or structured references are invented.",
    )
    text = _element(root, "text", **{_XML_ID: f"{work_id}-text", "type": "dictionary"})
    body = _element(text, "body", **{_XML_ID: f"{work_id}-body"})
    for ordinal, (_line_number, _line_bytes, record) in enumerate(records, start=1):
        entry = _element(
            body, "entry", n=str(ordinal), **{_XML_ID: _entry_id(work_id, ordinal)}
        )
        form = _element(entry, "form")
        _element(form, "orth", text=str(record["term"]), type="headword")
        sense = _element(
            entry, "sense", **{_XML_ID: f"{_entry_id(work_id, ordinal)}-sense"}
        )
        definitions = record["definitions"]
        assert isinstance(definitions, list)
        for block, definition in enumerate(definitions, start=1):
            _element(
                sense,
                "def",
                text=str(definition),
                n=str(block),
                **{_XML_ID: _definition_id(work_id, ordinal, block)},
            )
    return etree.tostring(
        root, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )


def _authority_bindings(
    source_manifest: SourceManifest,
) -> dict[str, dict[str, object]]:
    authorities = source_manifest.record["authorities"]
    assert isinstance(authorities, tuple)
    result: dict[str, dict[str, object]] = {}
    for item in authorities:
        assert isinstance(item, Mapping)
        result[str(item["name"])] = {
            "path": item["path"],
            "sha256": item["sha256"],
            "bytes": item["bytes"],
            "role": item["role"],
        }
    return result


def _unresolved(
    source_manifest: SourceManifest, profile: Mapping[str, object]
) -> list[dict[str, object]]:
    work_id = str(source_manifest.record["work_id"])
    source_id = str(source_manifest.record["source_id"])
    return [
        {
            "id": f"{work_id}-edition-identity",
            "profile": profile["profile_id"],
            "subject": {"type": "work-id", "value": work_id},
            "question": "Which historical edition, expression, or transcription state does this structured JSONL witness represent?",
            "blocking_scope": "edition-identity-and-acceptance",
            "escalation": "human-review",
            "consequence": "candidate remains nonaccepted",
            "evidence": [{"type": "retained-source", "value": source_id}],
        },
        {
            "id": f"{work_id}-structured-source-rights",
            "profile": profile["profile_id"],
            "subject": {"type": "source-id", "value": source_id},
            "question": "Is there a recorded license for the modern JWBickel structured JSONL, or should an independently built replacement witness be used?",
            "blocking_scope": "rights-acceptance-and-publication",
            "escalation": "human-review",
            "consequence": "candidate remains nonaccepted and publication is not authorized",
            "evidence": [
                {
                    "type": "source-attribution-readme",
                    "value": "source-attribution-readme",
                },
                {"type": "repository-rights-ledger", "value": "docs/SOURCES.md"},
            ],
        },
        {
            "id": f"{work_id}-textual-reference-review",
            "profile": profile["profile_id"],
            "subject": {"type": "work-id", "value": work_id},
            "question": "Should inline citation-looking strings receive structured TEI reference markup after independent textual collation?",
            "blocking_scope": "editorial-and-reference-structure-review",
            "escalation": "human-review",
            "consequence": "literal source text remains authoritative for this candidate",
            "evidence": [
                {"type": "source-field-census", "value": "term-and-definitions-only"}
            ],
        },
    ]


def _closure_digest(root: Path, policy: Mapping[str, object]) -> str:
    paths = {
        Path(__file__).resolve(),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True),
    }
    forbidden = tuple(
        str(value) for value in policy.get("forbidden_import_prefixes", [])
    )
    records: list[dict[str, str]] = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError("producer closure contains dynamic execution")
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(
                        f"producer closure contains forbidden import {name}"
                    )
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path.read_bytes()),
            }
        )
    return _sha(_canonical(records))


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Return the exact five non-manifest members for the generic seam."""

    source_manifest.verify()
    spec, profile, extras = _profile_and_policy(source_manifest)
    policy = extras["policy"]
    raw_manifest = extras["raw_manifest"]
    assert isinstance(policy, Mapping)
    assert isinstance(raw_manifest, Mapping)
    current = _verify_frozen_claims(source_manifest, profile, policy, raw_manifest)
    root = source_manifest.repository_root
    producer_closure = _closure_digest(root, policy)
    if producer_closure != profile.get(
        "producer_import_closure_sha256"
    ) or producer_closure != source_manifest.record.get(
        "producer_import_closure_sha256"
    ):
        raise ValueError("producer import closure binding mismatch")
    source = source_manifest.authority_path(str(current["source_id"]))
    records = _read_records(source.read_bytes())
    if len(records) != current["records"]:
        raise ValueError("retained dictionary record count does not match frozen claim")
    definition_count = sum(len(record[2]["definitions"]) for record in records)
    if definition_count != current["definition_blocks"]:
        raise ValueError(
            "retained dictionary definition-block count does not match frozen claim"
        )
    tei_bytes = _tei(source_manifest, profile, current, records)
    work_id = str(spec["work_id"])
    profile_id = str(spec["profile_id"])
    crosswalk: list[dict[str, object]] = []
    for ordinal, (line_number, line_bytes, record) in enumerate(records, start=1):
        entry_id = _entry_id(work_id, ordinal)
        crosswalk.append(
            {
                "id": entry_id,
                "kind": "entry",
                "source_line": line_number,
                "source_record_sha256": _sha(line_bytes),
                "source_field": "term",
                "source_index": 0,
                "source_term": record["term"],
                "value": record["term"],
                "target": f"#{entry_id}",
                "status": "represented",
            }
        )
        definitions = record["definitions"]
        assert isinstance(definitions, list)
        for block, definition in enumerate(definitions, start=1):
            definition_id = _definition_id(work_id, ordinal, block)
            crosswalk.append(
                {
                    "id": definition_id,
                    "kind": "definition",
                    "source_line": line_number,
                    "source_record_sha256": _sha(line_bytes),
                    "source_field": "definitions",
                    "source_index": block,
                    "source_term": record["term"],
                    "value": definition,
                    "target": f"#{definition_id}",
                    "status": "represented",
                }
            )
    accountability = {
        "contract": spec["accountability_contract"],
        "schema": f"sources/{work_id}/{work_id}.source-accountability.schema.json",
        "profile_id": profile_id,
        "work_id": work_id,
        "source_id": source_manifest.record["source_id"],
        "source_sha256": _sha(source.read_bytes()),
        "source_record_count": len(records),
        "definition_block_count": definition_count,
        "observation_counts": {
            "records": len(records),
            "definition_blocks": definition_count,
            "total": len(crosswalk),
            "represented": len(crosswalk),
            "omitted": 0,
            "duplicate": 0,
        },
        "crosswalk": crosswalk,
    }
    authority_bindings = _authority_bindings(source_manifest)
    source_member = profile["source_scope"]["retained_member"]
    assert isinstance(source_member, Mapping)
    provenance = {
        "contract": "ocd-lib021-bible-dictionaries-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": _TICKET_ID,
        "work_id": work_id,
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "identity": _plain(profile["identity"]),
        "source": {
            "dataset": _DATASET,
            "dataset_url": _DATASET_URL,
            "member": _plain(source_member),
            "manifest_path": _RAW_MANIFEST_PATH,
            "manifest_sha256": _RAW_MANIFEST_SHA256,
        },
        "source_order": _plain(source_manifest.record["source_order_members"]),
        "authorities": authority_bindings,
        "rights": _plain(profile["rights"]),
        "candidate_boundary": {
            "acceptance_status": "nonaccepted",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
    }
    unresolved = _unresolved(source_manifest, profile)
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
