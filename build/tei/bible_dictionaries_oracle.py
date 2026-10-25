"""Independent oracle for the three LIB-021 JSONL dictionary candidates."""

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


ORACLE_ID = "ocd-lib021-bible-dictionaries-independent-oracle"
ORACLE_VERSION = "1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_RAW_MANIFEST_SHA256 = (
    "3438b540e27f767ae4f0172a18ff466ed2d4ab5aed73a1b4af9755f92e52c37b"
)
_WORKS = {
    "eastons-bible-dictionary": {
        "source_id": "jwbickel-bible-dictionaries-eastons-jsonl",
        "authority": "jwbickel-bible-dictionaries-eastons-jsonl",
        "member": "eastons.jsonl",
        "records": 3963,
        "definitions": 7464,
        "title": "Easton's Bible Dictionary",
    },
    "hitchcocks-bible-names-dictionary": {
        "source_id": "jwbickel-bible-dictionaries-hitchcocks-jsonl",
        "authority": "jwbickel-bible-dictionaries-hitchcocks-jsonl",
        "member": "hitchcocks.jsonl",
        "records": 2622,
        "definitions": 2622,
        "title": "Hitchcock's Bible Names Dictionary",
    },
    "smiths-bible-dictionary": {
        "source_id": "jwbickel-bible-dictionaries-smiths-jsonl",
        "authority": "jwbickel-bible-dictionaries-smiths-jsonl",
        "member": "smiths.jsonl",
        "records": 4560,
        "definitions": 5362,
        "title": "Smith's Bible Dictionary",
    },
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _strict(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority(manifest: SourceManifest, name: str) -> Mapping[str, object]:
    for item in manifest.record.get("authorities", ()):
        if isinstance(item, Mapping) and item.get("name") == name:
            return item
    raise ValueError(f"LIB-021 authority {name!r} is missing")


def _records(source: bytes) -> tuple[tuple[int, bytes, dict[str, object]], ...]:
    result: list[tuple[int, bytes, dict[str, object]]] = []
    for number, line in enumerate(source.splitlines(keepends=True), 1):
        if not line.strip():
            raise ValueError(f"empty source JSONL line {number}")
        record = _strict(line, f"source record {number}")
        if set(record) != {"term", "definitions"}:
            raise ValueError(f"source record {number} fields drifted")
        if not isinstance(record["term"], str) or not record["term"]:
            raise ValueError(f"source record {number} term is invalid")
        definitions = record["definitions"]
        if (
            not isinstance(definitions, list)
            or not definitions
            or any(not isinstance(value, str) or not value for value in definitions)
        ):
            raise ValueError(f"source record {number} definitions are invalid")
        result.append((number, line, record))
    return tuple(result)


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


def _expected_accountability(
    manifest: SourceManifest,
    work_id: str,
    records: tuple[tuple[int, bytes, dict[str, object]], ...],
) -> dict[str, object]:
    spec = _WORKS[work_id]
    source = manifest.authority_path(str(spec["authority"])).read_bytes()
    crosswalk: list[dict[str, object]] = []
    for ordinal, (line_number, line_bytes, record) in enumerate(records, 1):
        entry_id = f"{work_id}-entry-{ordinal:05d}"
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
        for block, definition in enumerate(definitions, 1):
            definition_id = f"{work_id}-entry-{ordinal:05d}-definition-{block:03d}"
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
    return {
        "contract": f"ocd-{work_id}-source-accountability-v1",
        "schema": f"sources/{work_id}/{work_id}.source-accountability.schema.json",
        "profile_id": f"{work_id}-jwbickel-jsonl-v1",
        "work_id": work_id,
        "source_id": manifest.record["source_id"],
        "source_sha256": _sha(source),
        "source_record_count": len(records),
        "definition_block_count": sum(
            len(record["definitions"]) for _, _, record in records
        ),
        "observation_counts": {
            "records": len(records),
            "definition_blocks": sum(
                len(record["definitions"]) for _, _, record in records
            ),
            "total": len(crosswalk),
            "represented": len(crosswalk),
            "omitted": 0,
            "duplicate": 0,
        },
        "crosswalk": crosswalk,
    }


def _qname(local: str) -> str:
    return f"{{{_TEI}}}{local}"


def _element(
    parent: etree._Element,
    local: str,
    *,
    text: str | None = None,
    **attributes: str,
) -> etree._Element:
    node = etree.SubElement(parent, _qname(local), attributes)
    if text is not None:
        node.text = text
    return node


def _expected_tei(
    profile: Mapping[str, object],
    work_id: str,
    records: tuple[tuple[int, bytes, dict[str, object]], ...],
) -> etree._Element:
    identity = profile.get("identity")
    source_scope = profile.get("source_scope")
    if not isinstance(identity, Mapping) or not isinstance(source_scope, Mapping):
        raise ValueError("LIB-021 profile TEI authority is invalid")
    source_member = source_scope.get("retained_member")
    if not isinstance(source_member, Mapping):
        raise ValueError("LIB-021 profile retained member is invalid")

    root = etree.Element(_qname("TEI"), nsmap={None: _TEI})
    root.set(_XML_ID, f"{work_id}-candidate")
    header = _element(root, "teiHeader")
    file_desc = _element(header, "fileDesc")
    title_stmt = _element(file_desc, "titleStmt")
    _element(title_stmt, "title", text=str(identity["title"]))
    publication = _element(file_desc, "publicationStmt")
    _element(publication, "publisher", text="Open Christian Data")
    availability = _element(publication, "availability", status="restricted")
    _element(
        availability,
        "p",
        text=(
            "Nonaccepted candidate only; publication is not authorized while "
            "source rights and identity remain under human review."
        ),
    )
    source_desc = _element(file_desc, "sourceDesc")
    list_bibl = _element(source_desc, "listBibl", type="retained-source-order")
    bibl = _element(list_bibl, "bibl", **{_XML_ID: f"{work_id}-retained-source"})
    _element(bibl, "title", text=str(source_member["hf_filename"]))
    _element(bibl, "ptr", target=str(source_member["source_url"]))
    _element(
        bibl,
        "idno",
        text=str(source_member["sha256"]),
        type="sha256",
    )
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
        text=(
            "Ticket source order 1-3 is Easton, Hitchcock, Smith; Torrey is "
            "source order 4 and belongs to LIB-022."
        ),
        type="source-order",
    )
    _element(
        bibl,
        "note",
        text=(
            "The retained JSONL source has only term and definitions fields; "
            "inline reference-looking text remains literal definition text."
        ),
        type="field-census",
    )
    encoding = _element(header, "encodingDesc")
    _element(
        encoding,
        "p",
        text=(
            "Every retained JSONL record is represented once in source order. "
            "Each definitions array item remains one ordered definition block; "
            "no alternate terms or structured references are invented."
        ),
    )
    text = _element(
        root,
        "text",
        **{_XML_ID: f"{work_id}-text", "type": "dictionary"},
    )
    body = _element(text, "body", **{_XML_ID: f"{work_id}-body"})
    for ordinal, (_, _, record) in enumerate(records, 1):
        entry_id = f"{work_id}-entry-{ordinal:05d}"
        entry = _element(
            body,
            "entry",
            n=str(ordinal),
            **{_XML_ID: entry_id},
        )
        form = _element(entry, "form")
        _element(form, "orth", text=str(record["term"]), type="headword")
        sense = _element(entry, "sense", **{_XML_ID: f"{entry_id}-sense"})
        definitions = record["definitions"]
        assert isinstance(definitions, list)
        for block, definition in enumerate(definitions, 1):
            _element(
                sense,
                "def",
                text=str(definition),
                n=str(block),
                **{_XML_ID: f"{entry_id}-definition-{block:03d}"},
            )
    return root


def _projection(node: etree._Element) -> tuple[object, ...]:
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        node.text or "",
        node.tail or "",
        tuple(_projection(child) for child in node),
    )


def _verify_tei(
    manifest: SourceManifest,
    candidate: CandidatePackage,
    profile: Mapping[str, object],
    work_id: str,
    records: tuple[tuple[int, bytes, dict[str, object]], ...],
) -> None:
    try:
        root = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.XMLSyntaxError as exc:
        raise ValueError("LIB-021 TEI XML is not well-formed") from exc
    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    if not schema.validate(root):
        raise ValueError(f"LIB-021 TEI schema failure: {schema.error_log}")
    expected = _expected_tei(profile, work_id, records)
    expected_bytes = etree.tostring(
        expected,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    expected_root = etree.fromstring(expected_bytes)
    if _projection(root) != _projection(expected_root):
        raise ValueError("LIB-021 complete TEI projection drift")


def _expected_unresolved(work_id: str, profile_id: str) -> bytes:
    rows = (
        {
            "id": f"{work_id}-edition-identity",
            "profile": profile_id,
            "subject": {"type": "work-id", "value": work_id},
            "question": "Which historical edition, expression, or transcription state does this structured JSONL witness represent?",
            "blocking_scope": "edition-identity-and-acceptance",
            "escalation": "human-review",
            "consequence": "candidate remains nonaccepted",
            "evidence": [
                {"type": "retained-source", "value": _WORKS[work_id]["source_id"]}
            ],
        },
        {
            "id": f"{work_id}-structured-source-rights",
            "profile": profile_id,
            "subject": {"type": "source-id", "value": _WORKS[work_id]["source_id"]},
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
            "profile": profile_id,
            "subject": {"type": "work-id", "value": work_id},
            "question": "Should inline citation-looking strings receive structured TEI reference markup after independent textual collation?",
            "blocking_scope": "editorial-and-reference-structure-review",
            "escalation": "human-review",
            "consequence": "literal source text remains authoritative for this candidate",
            "evidence": [
                {"type": "source-field-census", "value": "term-and-definitions-only"}
            ],
        },
    )
    return b"".join(_canonical(row) for row in rows)


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    work_id = str(source_manifest.record.get("work_id"))
    spec = _WORKS.get(work_id)
    if spec is None or source_manifest.record.get("ticket_id") != "LIB-021":
        raise ValueError("LIB-021 source identity drift")
    if source_manifest.record.get("source_id") != spec["source_id"]:
        raise ValueError("LIB-021 source id drift")
    converter = source_manifest.record["converter"]
    validator = source_manifest.record["validator"]
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("LIB-021 callable bindings are invalid")
    expected_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get(
        "source_manifest"
    ) != {"path": expected_path, "sha256": source_manifest.sha256}:
        raise ValueError("LIB-021 candidate binding drift")
    if candidate.manifest.get("converter") != dict(converter) or candidate.manifest.get(
        "package_schema"
    ) != dict(source_manifest.record["package_schema"]):
        raise ValueError("LIB-021 candidate authority binding drift")
    raw_manifest = _strict(
        source_manifest.authority_path(
            "jwbickel-bible-dictionaries-manifest"
        ).read_bytes(),
        "JWBickel retained manifest",
    )
    if (
        _sha(
            source_manifest.authority_path(
                "jwbickel-bible-dictionaries-manifest"
            ).read_bytes()
        )
        != _RAW_MANIFEST_SHA256
    ):
        raise ValueError("LIB-021 retained manifest drift")
    files = raw_manifest.get("files")
    if not isinstance(files, list) or [
        item.get("local_filename") for item in files if isinstance(item, Mapping)
    ] != ["eastons.jsonl", "hitchcocks.jsonl", "smiths.jsonl", "torreys.jsonl"]:
        raise ValueError("LIB-021 retained manifest order drift")
    source = source_manifest.authority_path(str(spec["authority"])).read_bytes()
    records = _records(source)
    if (
        len(records) != spec["records"]
        or sum(len(record["definitions"]) for _, _, record in records)
        != spec["definitions"]
    ):
        raise ValueError("LIB-021 retained record census drift")
    expected_accountability = _expected_accountability(
        source_manifest, work_id, records
    )
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _strict(accountability_bytes, "LIB-021 accountability")
    if accountability != expected_accountability or accountability_bytes != _canonical(
        expected_accountability
    ):
        raise ValueError("LIB-021 source accountability drift")
    schema = _strict(
        source_manifest.authority_path("source-accountability-schema").read_bytes(),
        "LIB-021 accountability schema",
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"LIB-021 accountability schema failure: {errors[0].message}")
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    profile = _strict(profile_bytes, "LIB-021 reconstruction profile")
    _verify_tei(source_manifest, candidate, profile, work_id, records)
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    policy = _strict(policy_bytes, "LIB-021 validation policy")
    if (
        policy.get("oracle_id") != ORACLE_ID
        or policy.get("oracle_version") != ORACLE_VERSION
    ):
        raise ValueError("LIB-021 oracle policy binding drift")
    provenance = _strict(
        candidate.member_bytes("provenance.json"), "LIB-021 provenance"
    )
    if (
        provenance.get("contract")
        != "ocd-lib021-bible-dictionaries-candidate-provenance-v1"
        or provenance.get("status") != "nonaccepted"
        or provenance.get("ticket_id") != "LIB-021"
        or provenance.get("work_id") != work_id
        or provenance.get("source_id") != spec["source_id"]
        or provenance.get("source_manifest_sha256") != source_manifest.sha256
        or provenance.get("identity") != profile.get("identity")
        or provenance.get("source_order")
        != _plain(source_manifest.record.get("source_order_members"))
        or provenance.get("rights") != profile.get("rights")
        or provenance.get("candidate_boundary")
        != {
            "acceptance_status": "nonaccepted",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        }
    ):
        raise ValueError("LIB-021 provenance drift")
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved(
        work_id, str(profile["profile_id"])
    ):
        raise ValueError("LIB-021 unresolved ledger drift")
    if (
        candidate.member_bytes("README.source.md")
        != source_manifest.authority_path("source-attribution-readme").read_bytes()
    ):
        raise ValueError("LIB-021 attribution README drift")
    closure = _closure(source_manifest.repository_root)
    if closure != validator.get("import_closure_sha256"):
        raise ValueError("LIB-021 oracle import closure drift")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
