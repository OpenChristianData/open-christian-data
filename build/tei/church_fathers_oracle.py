"""Independent LIB-061 oracle for the retained Commentaries-Database tree.

The oracle repeats the recovered v9 member accounting and TOML comparison
against the source manifest's extracted-member envelope. It does not import
the producer or any legacy church-fathers parser.
"""

from __future__ import annotations

import ast
import hashlib
import json
import platform
import sys
import tomllib
from pathlib import Path
from typing import Mapping

import jsonschema
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-lib061-church-fathers-quotations-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
SOURCE_ID = "church-fathers-quotations"
WORK_ID = "church-fathers-quotations"
ARCHIVE_SHA256 = "5a4ba3ef4bfd168cdaf4cd6bcc4e8cc655c90da97bfe5abf3e6fe9338d86fbe6"
ARCHIVE_BYTES = 132_531_712
ARCHIVE_MEMBER_COUNT = 59_021
ARCHIVE_REGULAR_FILE_COUNT = 58_682
ARCHIVE_DIRECTORY_COUNT = 339
ARCHIVE_TOML_COUNT = 58_675
ARCHIVE_METADATA_COUNT = 335
ARCHIVE_COMMENTARY_FILE_COUNT = 58_340
ARCHIVE_RECORD_COUNT = 70_194
RAW_PREFIX = "raw/Commentaries-Database"
ENVELOPE_CONTRACT = "ocd-source-member-equality-v1"
EXPECTED_FIELDS = {
    "append_to_author_name": 6750,
    "author": 12,
    "content": 11,
    "context": 6,
    "default_year": 335,
    "location": 8,
    "quote": 70194,
    "source_title": 67945,
    "source_url": 67945,
    "text": 26,
    "time": 440,
    "wiki": 335,
    "work": 8,
}
EXPECTED_TYPES = {
    "append_to_author_name": {"string": 6750},
    "author": {"string": 12},
    "content": {"string": 11},
    "context": {"string": 6},
    "default_year": {"integer": 335},
    "location": {"string": 8},
    "quote": {"string": 70194},
    "source_title": {"string": 67945},
    "source_url": {"string": 67945},
    "text": {"string": 26},
    "time": {"integer": 440},
    "wiki": {"string": 335},
    "work": {"string": 8},
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
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


def _safe_repo_path(root: Path, logical: str, label: str) -> Path:
    lexical = Path(logical)
    if lexical.is_absolute() or ".." in lexical.parts or lexical.as_posix() != logical:
        raise ValueError(f"{label} path is not repository-relative")
    return (root / lexical).resolve(strict=True)


def _source_binding(source_manifest: SourceManifest) -> str:
    members = sorted(
        (
            {"name": item["name"], "path": item["path"], "bytes": item["bytes"], "sha256": item["sha256"]}
            for item in source_manifest.record["authorities"]
            if item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _authorities(source_manifest: SourceManifest) -> tuple[Mapping[str, object], ...]:
    record = source_manifest.record
    if record.get("ticket_id") != "LIB-061" or record.get("source_id") != SOURCE_ID or record.get("work_id") != WORK_ID:
        raise ValueError("LIB-061 source identity drifted")
    return tuple(item for item in record["authorities"] if isinstance(item, Mapping))


def _envelope(source_manifest: SourceManifest) -> list[dict[str, object]]:
    authorities = _authorities(source_manifest)
    envelope = _strict_json(source_manifest.authority_path("source-member-equality").read_bytes(), "LIB-061 source member equality")
    archive = envelope.get("archive")
    if envelope.get("contract") != ENVELOPE_CONTRACT or not isinstance(archive, Mapping):
        raise ValueError("LIB-061 source envelope identity drifted")
    if (archive.get("bytes"), archive.get("sha256"), archive.get("member_count"), archive.get("regular_file_count"), archive.get("directory_count"), archive.get("toml_file_count")) != (ARCHIVE_BYTES, ARCHIVE_SHA256, ARCHIVE_MEMBER_COUNT, ARCHIVE_REGULAR_FILE_COUNT, ARCHIVE_DIRECTORY_COUNT, ARCHIVE_TOML_COUNT):
        raise ValueError("LIB-061 recovered archive census drifted")
    members = envelope.get("members")
    if not isinstance(members, list) or len(members) != ARCHIVE_MEMBER_COUNT:
        raise ValueError("LIB-061 source envelope member count drifted")
    primary = {str(item["path"]): item for item in authorities if item.get("role") == "primary-source"}
    if len(primary) != ARCHIVE_TOML_COUNT:
        raise ValueError("LIB-061 primary authority count drifted")
    observed_primary: set[str] = set()
    regular = directories = tomls = 0
    for index, raw_item in enumerate(members):
        if not isinstance(raw_item, Mapping):
            raise ValueError(f"LIB-061 source member {index} is not an object")
        item = dict(raw_item)
        if item.get("index") != index or not isinstance(item.get("archive_path"), str) or not isinstance(item.get("normalized_path"), str):
            raise ValueError(f"LIB-061 source member index/path drift at {index}")
        normalized = str(item["normalized_path"])
        retained = str(item.get("retained_path"))
        expected_retained = RAW_PREFIX if normalized in ("", ".") else f"{RAW_PREFIX}/{normalized}"
        if retained != expected_retained or normalized.startswith("/") or ".." in Path(normalized).parts:
            raise ValueError(f"LIB-061 source member path drift at {index}")
        target = _safe_repo_path(source_manifest.repository_root, retained, f"LIB-061 source member {index}")
        if item.get("kind") == "regular-file":
            regular += 1
            if not target.is_file() or target.stat().st_size != item.get("bytes") or _sha(target.read_bytes()) != item.get("sha256") or item.get("match") != "exact":
                raise ValueError(f"LIB-061 source member bytes drift at {index}")
            if normalized.lower().endswith(".toml"):
                tomls += 1
                authority = primary.get(retained)
                if authority is None or authority.get("bytes") != item.get("bytes") or authority.get("sha256") != item.get("sha256"):
                    raise ValueError(f"LIB-061 primary authority drift at {retained}")
                observed_primary.add(retained)
        elif item.get("kind") == "directory":
            directories += 1
            if not target.is_dir() or item.get("sha256") is not None:
                raise ValueError(f"LIB-061 source directory drift at {index}")
        else:
            raise ValueError(f"LIB-061 unsupported source member kind at {index}")
    if (regular, directories, tomls) != (ARCHIVE_REGULAR_FILE_COUNT, ARCHIVE_DIRECTORY_COUNT, ARCHIVE_TOML_COUNT) or observed_primary != set(primary):
        raise ValueError("LIB-061 source member accounting is incomplete")
    equality = envelope.get("member_equality")
    if not isinstance(equality, Mapping) or (equality.get("matched_regular_file_count"), equality.get("missing_member_count"), equality.get("mismatch_count")) != (ARCHIVE_REGULAR_FILE_COUNT, 0, 0):
        raise ValueError("LIB-061 source member equality proof drifted")
    return [dict(item) for item in members]


def _xml_field(item: etree._Element) -> tuple[str, object]:
    name = item.get("n")
    label = item.find(f"{{{TEI_NS}}}label")
    if label is None or label.text != name:
        raise ValueError("LIB-061 field label/name drift")
    marker = item.get("ana")
    if marker == "#toml-string":
        seg = item.find(f"{{{TEI_NS}}}seg")
        if seg is None or len(seg) or dict(seg.attrib) != {f"{{{XML_NS}}}space": "preserve"}:
            raise ValueError("LIB-061 string field shape drift")
        return str(name), seg.text or ""
    if marker == "#toml-integer":
        num = item.find(f"{{{TEI_NS}}}num")
        if num is None or len(num) or num.get("type") != "integer" or num.text is None:
            raise ValueError("LIB-061 integer field shape drift")
        return str(name), int(num.text)
    raise ValueError("LIB-061 TOML type marker drift")


def _expected_accounting(source_manifest: SourceManifest, members: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, int], dict[str, dict[str, int]], int, int, int]:
    accounting: list[dict[str, object]] = []
    field_counts: dict[str, int] = {}
    field_types: dict[str, dict[str, int]] = {}
    metadata_count = commentary_count = record_count = 0
    for index, member in enumerate(members):
        raw = b""
        if member["kind"] == "regular-file":
            raw = _safe_repo_path(source_manifest.repository_root, str(member["retained_path"]), f"LIB-061 source member {index}").read_bytes()
        path = str(member["archive_path"])
        if member["kind"] == "directory":
            tar_type = "5"
        elif member["kind"] == "regular-file":
            tar_type = "0"
        else:
            raise ValueError("LIB-061 member kind drift")
        if path.endswith("/metadata.toml"):
            disposition, reason = "included", "parsed-metadata-object-projected-to-TEI"
        elif path.endswith(".toml"):
            disposition, reason = "included", "parsed-commentary-records-projected-to-TEI"
        elif path == "./LICENSE":
            disposition, reason = "included-rights", "rights-text-projected-to-README-and-provenance; not literary body"
        elif member["kind"] == "directory":
            disposition, reason = "excluded", "directory-container-only; hierarchy represented by retained member paths"
        else:
            disposition, reason = "excluded", "repository-administration-or-documentation; exact bytes accounted; not source quotation content"
        accounting.append({"index": index, "path": path, "tar_type": tar_type, "kind": member["kind"], "size": member["bytes"], "content_sha256": _sha(raw) if member["kind"] == "regular-file" else None, "tei_disposition": disposition, "reason": reason})
        if not (member["kind"] == "regular-file" and path.endswith(".toml")):
            continue
        try:
            parsed = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"LIB-061 TOML parse failure at {path}") from exc
        if path.endswith("/metadata.toml"):
            metadata_count += 1
            records = [parsed]
        else:
            commentary_count += 1
            if list(parsed.keys()) != ["commentary"] or not isinstance(parsed["commentary"], list):
                raise ValueError(f"LIB-061 commentary TOML shape drift at {path}")
            records = parsed["commentary"]
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"LIB-061 TOML record shape drift at {path}")
            for key, value in record.items():
                field_counts[key] = field_counts.get(key, 0) + 1
                kind = "integer" if isinstance(value, int) and not isinstance(value, bool) else "string"
                field_types.setdefault(key, {})[kind] = field_types.setdefault(key, {}).get(kind, 0) + 1
            record_count += int(not path.endswith("/metadata.toml"))
    return accounting, field_counts, field_types, metadata_count, commentary_count, record_count


def _expected_tei(source_manifest: SourceManifest, members: list[dict[str, object]]) -> bytes:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS}, attrib={XML_ID: "lib061-church-fathers-quotations"})
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = "Church Fathers verse-reference quotations"
    publication = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI_NS}}}p").text = "Nonaccepted reconstruction candidate; publication not ready"
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    etree.SubElement(source_desc, f"{{{TEI_NS}}}p").text = f"Commentaries-Database.tar; SHA-256 {ARCHIVE_SHA256}"
    encoding = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    class_decl = etree.SubElement(encoding, f"{{{TEI_NS}}}classDecl")
    taxonomy = etree.SubElement(class_decl, f"{{{TEI_NS}}}taxonomy", attrib={XML_ID: "toml-types"})
    for ident, label_text in (("toml-string", "TOML string"), ("toml-integer", "TOML integer")):
        category = etree.SubElement(taxonomy, f"{{{TEI_NS}}}category", attrib={XML_ID: ident})
        etree.SubElement(category, f"{{{TEI_NS}}}catDesc").text = label_text
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    for index, member in enumerate(members):
        if not (member["kind"] == "regular-file" and str(member["archive_path"]).endswith(".toml")):
            continue
        raw = _safe_repo_path(source_manifest.repository_root, str(member["retained_path"]), f"LIB-061 source member {index}").read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
        is_metadata = str(member["archive_path"]).endswith("/metadata.toml")
        div = etree.SubElement(body, f"{{{TEI_NS}}}div", type="source-member", subtype="metadata" if is_metadata else "commentary", n=str(index))
        etree.SubElement(div, f"{{{TEI_NS}}}head").text = str(member["archive_path"])
        etree.SubElement(div, f"{{{TEI_NS}}}ab", type="source-directory").text = str(Path(str(member["archive_path"])).parent).replace("\\", "/")
        def add_fields(parent: etree._Element, record: Mapping[str, object]) -> None:
            fields = etree.SubElement(parent, f"{{{TEI_NS}}}list", type="toml-object")
            for key, value in record.items():
                item = etree.SubElement(fields, f"{{{TEI_NS}}}item", n=key)
                item.set("ana", "#toml-string" if isinstance(value, str) else "#toml-integer")
                label = etree.SubElement(item, f"{{{TEI_NS}}}label")
                label.text = key
                if isinstance(value, str):
                    seg = etree.SubElement(item, f"{{{TEI_NS}}}seg")
                    seg.set(f"{{{XML_NS}}}space", "preserve")
                    seg.text = value
                elif isinstance(value, int) and not isinstance(value, bool):
                    num = etree.SubElement(item, f"{{{TEI_NS}}}num", type="integer")
                    num.text = str(value)
                else:
                    raise ValueError(f"LIB-061 unsupported TOML type at {member['archive_path']}")
        if is_metadata:
            add_fields(div, parsed)
        else:
            if list(parsed.keys()) != ["commentary"]:
                raise ValueError(f"LIB-061 commentary shape drift at {member['archive_path']}")
            for record_index, record in enumerate(parsed["commentary"]):
                rec_div = etree.SubElement(div, f"{{{TEI_NS}}}div", type="commentary-record", n=str(record_index))
                add_fields(rec_div, record)
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _catalog_claims(source_manifest: SourceManifest) -> dict[str, object]:
    lineage = source_manifest.record.get("catalog_claim_lineage")
    if not isinstance(lineage, Mapping) or lineage.get("contract") != "ocd-catalog-claim-lineage-v1" or lineage.get("work_id") != WORK_ID or lineage.get("claim_count") != 325:
        raise ValueError("LIB-061 catalog claim lineage identity drifted")
    claims = lineage.get("claims")
    if not isinstance(claims, tuple) or len(claims) != 325:
        raise ValueError("LIB-061 catalog claim set is incomplete")
    observed_paths: set[str] = set()
    observed_ids: set[str] = set()
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("LIB-061 catalog claim is not an object")
        source_path = claim.get("source_path")
        legacy = claim.get("legacy_source_sha256")
        if not isinstance(source_path, str) or source_path != Path(source_path).as_posix() or Path(source_path).is_absolute() or ".." in Path(source_path).parts:
            raise ValueError("LIB-061 catalog claim path drifted")
        if not isinstance(legacy, str) or not legacy.startswith("sha256:") or len(legacy) != 71:
            raise ValueError("LIB-061 catalog legacy hash drifted")
        path = _safe_repo_path(source_manifest.repository_root, f"data/{source_path}", "LIB-061 catalog claim")
        value = _strict_json(path.read_bytes(), f"LIB-061 catalog claim {source_path}")
        meta = value.get("meta")
        if not isinstance(meta, Mapping) or meta.get("schema_type") != "church_fathers" or meta.get("id") != path.stem:
            raise ValueError(f"LIB-061 catalog identity drift at {source_path}")
        provenance = meta.get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("source_hash") != legacy:
            raise ValueError(f"LIB-061 catalog source hash drift at {source_path}")
        observed_paths.add(source_path)
        observed_ids.add(str(meta["id"]))
    expected_files = {f"church-fathers/{path.name}" for path in (source_manifest.repository_root / "data" / "church-fathers").glob("*.json")}
    if expected_files != observed_paths or len(observed_ids) != 325:
        raise ValueError("LIB-061 catalog claim set does not equal the 325 stored outputs")
    return {"work_id": WORK_ID, "claim_count": len(claims), "distinct_exact_ids": len(observed_ids)}


def _unresolved() -> bytes:
    items = [
        {"id": "LIB061-U1", "scope": "all-commentary-records", "kind": "translation-rights", "status": "human-review-required", "statement": "The retained LICENSE warns that a small number of quotations may originate from copyrighted translations; the affected records are not identified."},
        {"id": "LIB061-U2", "scope": "all-source-metadata", "kind": "identity-and-editorial-assertions", "status": "human-review-required", "statement": "Names, dates, source titles, URLs, authorship, verse associations, and readings are preserved as source assertions, not independently accepted facts."},
    ]
    return b"".join(_canonical(item) for item in items)


def _closure_digest(root: Path) -> str:
    paths = [Path(__file__).resolve(strict=True), (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True), (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True)]
    records = [{"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(paths, key=lambda path: path.relative_to(root).as_posix())]
    return _sha(_canonical(records))


def _verify_provenance_source_bindings(
    source_manifest: SourceManifest, provenance: Mapping[str, object]
) -> None:
    """Enforce the existing LIB-061 provenance fields against source authority."""
    if provenance.get("source_manifest_sha256") != source_manifest.sha256:
        raise ValueError("LIB-061 provenance source manifest binding drifted")
    member_digest = _source_binding(source_manifest)
    envelope_digest = _sha(source_manifest.authority_path("source-member-equality").read_bytes())
    expected = {
        "source_envelope": {
            "sha256": envelope_digest,
            "primary_member_set_sha256": member_digest,
        },
        "authorities": {
            "primary_source_member_count": sum(
                item.get("role") == "primary-source"
                for item in source_manifest.record["authorities"]
            ),
            "primary_source_member_set_sha256": member_digest,
            "source_member_equality_sha256": envelope_digest,
        },
    }
    for section, fields in expected.items():
        actual = provenance.get(section)
        if not isinstance(actual, Mapping):
            raise ValueError(f"LIB-061 provenance {section} bindings missing")
        for field, value in fields.items():
            if type(actual.get(field)) is not type(value) or actual[field] != value:
                raise ValueError(f"LIB-061 provenance {section}.{field} binding drifted")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    authorities = _authorities(source_manifest)
    profile = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "LIB-061 profile")
    policy = _strict_json(source_manifest.authority_path("validation-policy").read_bytes(), "LIB-061 policy")
    if profile.get("profile_id") != "lib061-church-fathers-quotations-member-tree-v1" or policy.get("policy_id") != "lib061-church-fathers-quotations-policy-v1":
        raise ValueError("LIB-061 profile or policy identity drifted")
    closure = _strict_json(source_manifest.authority_path("oracle-import-closure").read_bytes(), "LIB-061 oracle import closure")
    if closure.get("contract") != "ocd-lib061-oracle-import-closure-v1" or closure.get("digest") != _closure_digest(source_manifest.repository_root):
        raise ValueError("LIB-061 oracle import closure drifted")
    members = _envelope(source_manifest)
    accountability_members, field_counts, field_types, metadata_count, commentary_count, record_count = _expected_accounting(source_manifest, members)
    expected_accountability = {
        "contract": "lib061-source-accountability-v9",
        "member_count": len(accountability_members),
        "regular_file_count": ARCHIVE_REGULAR_FILE_COUNT,
        "directory_count": ARCHIVE_DIRECTORY_COUNT,
        "toml_file_count": ARCHIVE_TOML_COUNT,
        "metadata_object_count": metadata_count,
        "commentary_file_count": commentary_count,
        "commentary_record_count": record_count,
        "toml_parse_errors": 0,
        "field_occurrences": field_counts,
        "field_type_occurrences": field_types,
        "members": accountability_members,
        "source_sha256": ARCHIVE_SHA256,
    }
    schema = _strict_json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "LIB-061 accountability schema")
    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _strict_json(accountability_bytes, "LIB-061 candidate accountability")
    jsonschema.Draft202012Validator(schema).validate(accountability)
    if accountability != expected_accountability:
        raise ValueError("LIB-061 candidate source accountability differs from independent source projection")
    tei_bytes = candidate.member_bytes("content.tei.xml")
    if tei_bytes != _expected_tei(source_manifest, members):
        raise ValueError("LIB-061 candidate TEI differs from independent source projection")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False, huge_tree=True)
    document = etree.fromstring(tei_bytes, parser)
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")), parser))
    if not xsd.validate(etree.ElementTree(document)):
        raise ValueError("LIB-061 strict TEI XSD validation failed: " + " | ".join(str(error) for error in xsd.error_log))
    readme = candidate.member_bytes("README.source.md")
    expected_readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    if readme != expected_readme or b"nonaccepted" not in readme.lower() or ARCHIVE_SHA256.encode() not in readme or b"copyrighted translations" not in readme:
        raise ValueError("LIB-061 README source/lifecycle/rights evidence drifted")
    if candidate.member_bytes("unresolved.jsonl") != _unresolved():
        raise ValueError("LIB-061 unresolved evidence drifted")
    provenance = _strict_json(candidate.member_bytes("provenance.json"), "LIB-061 candidate provenance")
    _verify_provenance_source_bindings(source_manifest, provenance)
    if provenance.get("status") != "nonaccepted" or provenance.get("work_id") != WORK_ID or provenance.get("publication") != "not_ready" or provenance.get("candidate_boundary", {}).get("canonical_data_or_ir_written") is not False:
        raise ValueError("LIB-061 provenance lifecycle drifted")
    if provenance.get("source_envelope", {}).get("archive_sha256") != ARCHIVE_SHA256:
        raise ValueError("LIB-061 provenance source envelope drifted")
    _catalog_claims(source_manifest)
    validator_closure = closure.get("digest")
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": str(validator_closure),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": next(item["sha256"] for item in authorities if item.get("role") == "complete-source-feature-profile"),
        "package_schema_sha256": next(item["sha256"] for item in authorities if item.get("role") == "candidate-package-schema"),
        "source_sha256": _source_binding(source_manifest),
        "xsd_sha256": next(item["sha256"] for item in authorities if item.get("role") == "tei-validation-schema"),
        "policy_sha256": next(item["sha256"] for item in authorities if item.get("role") == "independent-validation-policy"),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
