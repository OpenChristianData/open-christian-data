"""LIB-061 source-first producer for the retained Commentaries-Database tree.

The historical LIB-061 producer projected the recovered TAR directly.  This
route keeps that projection algorithm and makes the canonical extracted tree
the primary source members.  ``source-member-equality.json`` records the
archive order and every archive member hash, so the tree route can be checked
without depending on a scratch-drive TAR path.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-lib061-church-fathers-quotations-member-tree-to-tei"
CONVERTER_VERSION = "1"
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
            {
                "name": item["name"],
                "path": item["path"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in source_manifest.record["authorities"]
            if item.get("role") == "primary-source"
        ),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": members}))


def _route_authorities(source_manifest: SourceManifest) -> tuple[Mapping[str, object], ...]:
    record = source_manifest.record
    if (
        record.get("ticket_id") != "LIB-061"
        or record.get("source_id") != SOURCE_ID
        or record.get("work_id") != WORK_ID
        or record.get("contract") != "ocd-source-manifest-v1"
    ):
        raise ValueError("LIB-061 source identity drifted")
    authorities = tuple(item for item in record["authorities"] if isinstance(item, Mapping))
    if not authorities:
        raise ValueError("LIB-061 source manifest has no authorities")
    return authorities


def _envelope(source_manifest: SourceManifest) -> tuple[dict[str, object], list[dict[str, object]]]:
    authorities = _route_authorities(source_manifest)
    envelope_path = source_manifest.authority_path("source-member-equality")
    envelope = _strict_json(envelope_path.read_bytes(), "LIB-061 source member equality")
    if envelope.get("contract") != ENVELOPE_CONTRACT:
        raise ValueError("LIB-061 source envelope contract drifted")
    archive = envelope.get("archive")
    if not isinstance(archive, Mapping) or archive.get("sha256") != ARCHIVE_SHA256 or archive.get("bytes") != ARCHIVE_BYTES:
        raise ValueError("LIB-061 recovered archive identity drifted")
    if archive.get("member_count") != ARCHIVE_MEMBER_COUNT or archive.get("regular_file_count") != ARCHIVE_REGULAR_FILE_COUNT or archive.get("directory_count") != ARCHIVE_DIRECTORY_COUNT or archive.get("toml_file_count") != ARCHIVE_TOML_COUNT:
        raise ValueError("LIB-061 recovered archive census drifted")
    members = envelope.get("members")
    if not isinstance(members, list) or len(members) != ARCHIVE_MEMBER_COUNT:
        raise ValueError("LIB-061 source member inventory is incomplete")
    primary = {
        str(item["path"]): item
        for item in authorities
        if item.get("role") == "primary-source"
    }
    if len(primary) != ARCHIVE_TOML_COUNT:
        raise ValueError("LIB-061 primary TOML authority count drifted")
    observed_paths: set[str] = set()
    regular_count = directory_count = toml_count = 0
    for expected_index, item in enumerate(members):
        if not isinstance(item, Mapping):
            raise ValueError(f"LIB-061 source member {expected_index} is not an object")
        if item.get("index") != expected_index or not isinstance(item.get("archive_path"), str) or not isinstance(item.get("normalized_path"), str):
            raise ValueError(f"LIB-061 source member index/path drift at {expected_index}")
        normalized = str(item["normalized_path"])
        retained = str(item.get("retained_path"))
        expected_retained = RAW_PREFIX if normalized in ("", ".") else f"{RAW_PREFIX}/{normalized}"
        if retained != expected_retained or normalized.startswith("/") or ".." in Path(normalized).parts:
            raise ValueError(f"LIB-061 source member retained path drift at {expected_index}")
        kind = item.get("kind")
        target = _safe_repo_path(source_manifest.repository_root, retained, f"LIB-061 member {expected_index}")
        if kind == "regular-file":
            regular_count += 1
            if not target.is_file() or not isinstance(item.get("bytes"), int) or item.get("bytes") != target.stat().st_size:
                raise ValueError(f"LIB-061 retained member size drift at {expected_index}")
            content_sha = _sha(target.read_bytes())
            if content_sha != item.get("sha256") or item.get("match") != "exact":
                raise ValueError(f"LIB-061 retained member bytes drift at {expected_index}")
            if normalized.lower().endswith(".toml"):
                toml_count += 1
                authority = primary.get(retained)
                if authority is None or authority.get("bytes") != item["bytes"] or authority.get("sha256") != item["sha256"]:
                    raise ValueError(f"LIB-061 primary authority binding drift at {retained}")
                observed_paths.add(retained)
        elif kind == "directory":
            directory_count += 1
            if not target.is_dir() or item.get("sha256") is not None:
                raise ValueError(f"LIB-061 retained directory drift at {expected_index}")
        else:
            raise ValueError(f"LIB-061 unsupported source member kind at {expected_index}")
    if (regular_count, directory_count, toml_count) != (ARCHIVE_REGULAR_FILE_COUNT, ARCHIVE_DIRECTORY_COUNT, ARCHIVE_TOML_COUNT):
        raise ValueError("LIB-061 source member census does not match the recovered archive")
    if observed_paths != set(primary):
        raise ValueError("LIB-061 primary authority set does not equal retained TOML members")
    equality = envelope.get("member_equality")
    if not isinstance(equality, Mapping) or equality.get("matched_regular_file_count") != ARCHIVE_REGULAR_FILE_COUNT or equality.get("missing_member_count") != 0 or equality.get("mismatch_count") != 0:
        raise ValueError("LIB-061 source member equality proof is incomplete")
    return envelope, [dict(item) for item in members]


def _field_item(parent: etree._Element, name: str, value: object) -> None:
    item = etree.SubElement(parent, f"{{{TEI_NS}}}item", n=name)
    label = etree.SubElement(item, f"{{{TEI_NS}}}label")
    label.text = name
    if isinstance(value, str):
        item.set("ana", "#toml-string")
        seg = etree.SubElement(item, f"{{{TEI_NS}}}seg")
        seg.set(f"{{{XML_NS}}}space", "preserve")
        seg.text = value
    elif isinstance(value, int) and not isinstance(value, bool):
        item.set("ana", "#toml-integer")
        num = etree.SubElement(item, f"{{{TEI_NS}}}num", type="integer")
        num.text = str(value)
    else:
        raise ValueError(f"unsupported TOML field type for {name}: {type(value).__name__}")


def _member_reason(member: Mapping[str, object]) -> tuple[str, str]:
    path = str(member["archive_path"])
    kind = member["kind"]
    if kind == "directory":
        return "excluded", "directory-container-only; hierarchy represented by retained member paths"
    if kind == "regular-file" and path.endswith("/metadata.toml"):
        return "included", "parsed-metadata-object-projected-to-TEI"
    if kind == "regular-file" and path.endswith(".toml"):
        return "included", "parsed-commentary-records-projected-to-TEI"
    if path == "./LICENSE":
        return "included-rights", "rights-text-projected-to-README-and-provenance; not literary body"
    return "excluded", "repository-administration-or-documentation; exact bytes accounted; not source quotation content"


def _build_projection(source_manifest: SourceManifest, members: list[dict[str, object]]) -> tuple[bytes, dict[str, object]]:
    root = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS}, attrib={XML_ID: "lib061-church-fathers-quotations"})
    header = etree.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI_NS}}}title").text = "Church Fathers verse-reference quotations"
    publication_stmt = etree.SubElement(file_desc, f"{{{TEI_NS}}}publicationStmt")
    etree.SubElement(publication_stmt, f"{{{TEI_NS}}}p").text = "Nonaccepted reconstruction candidate; publication not ready"
    source_desc = etree.SubElement(file_desc, f"{{{TEI_NS}}}sourceDesc")
    etree.SubElement(source_desc, f"{{{TEI_NS}}}p").text = f"Commentaries-Database.tar; SHA-256 {ARCHIVE_SHA256}"
    encoding_desc = etree.SubElement(header, f"{{{TEI_NS}}}encodingDesc")
    class_decl = etree.SubElement(encoding_desc, f"{{{TEI_NS}}}classDecl")
    taxonomy = etree.SubElement(class_decl, f"{{{TEI_NS}}}taxonomy", attrib={XML_ID: "toml-types"})
    for ident, label_text in (("toml-string", "TOML string"), ("toml-integer", "TOML integer")):
        category = etree.SubElement(taxonomy, f"{{{TEI_NS}}}category", attrib={XML_ID: ident})
        etree.SubElement(category, f"{{{TEI_NS}}}catDesc").text = label_text
    text = etree.SubElement(root, f"{{{TEI_NS}}}text")
    body = etree.SubElement(text, f"{{{TEI_NS}}}body")
    accounting: list[dict[str, object]] = []
    field_counts: dict[str, int] = {}
    field_types: dict[str, dict[str, int]] = {}
    metadata_count = commentary_file_count = record_count = parse_errors = 0
    regular_count = directory_count = 0
    for index, member in enumerate(members):
        raw = b""
        if member["kind"] == "regular-file":
            target = _safe_repo_path(source_manifest.repository_root, str(member["retained_path"]), f"LIB-061 member {index}")
            raw = target.read_bytes()
        disposition, reason = _member_reason(member)
        accounting.append(
            {
                "index": index,
                "path": member["archive_path"],
                "tar_type": "5" if member["kind"] == "directory" else "0",
                "kind": member["kind"],
                "size": member["bytes"],
                "content_sha256": _sha(raw) if member["kind"] == "regular-file" else None,
                "tei_disposition": disposition,
                "reason": reason,
            }
        )
        regular_count += int(member["kind"] == "regular-file")
        directory_count += int(member["kind"] == "directory")
        if not (member["kind"] == "regular-file" and str(member["archive_path"]).endswith(".toml")):
            continue
        try:
            parsed = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            parse_errors += 1
            raise ValueError(f"LIB-061 TOML parse failure at {member['archive_path']}") from exc
        div = etree.SubElement(body, f"{{{TEI_NS}}}div", type="source-member", subtype="metadata" if str(member["archive_path"]).endswith("/metadata.toml") else "commentary", n=str(index))
        etree.SubElement(div, f"{{{TEI_NS}}}head").text = str(member["archive_path"])
        etree.SubElement(div, f"{{{TEI_NS}}}ab", type="source-directory").text = str(Path(str(member["archive_path"])).parent).replace("\\", "/")
        if str(member["archive_path"]).endswith("/metadata.toml"):
            metadata_count += 1
            fields = etree.SubElement(div, f"{{{TEI_NS}}}list", type="toml-object")
            for key, value in parsed.items():
                _field_item(fields, key, value)
                field_counts[key] = field_counts.get(key, 0) + 1
                kind = "integer" if isinstance(value, int) and not isinstance(value, bool) else "string"
                field_types.setdefault(key, {})[kind] = field_types.setdefault(key, {}).get(kind, 0) + 1
        else:
            commentary_file_count += 1
            if list(parsed.keys()) != ["commentary"] or not isinstance(parsed["commentary"], list):
                raise ValueError(f"unexpected commentary TOML shape: {member['archive_path']}")
            for record_index, record in enumerate(parsed["commentary"]):
                rec_div = etree.SubElement(div, f"{{{TEI_NS}}}div", type="commentary-record", n=str(record_index))
                fields = etree.SubElement(rec_div, f"{{{TEI_NS}}}list", type="toml-object")
                for key, value in record.items():
                    _field_item(fields, key, value)
                    field_counts[key] = field_counts.get(key, 0) + 1
                    kind = "integer" if isinstance(value, int) and not isinstance(value, bool) else "string"
                    field_types.setdefault(key, {})[kind] = field_types.setdefault(key, {}).get(kind, 0) + 1
                record_count += 1
    if (len(accounting), regular_count, directory_count, metadata_count, commentary_file_count, record_count, parse_errors) != (ARCHIVE_MEMBER_COUNT, ARCHIVE_REGULAR_FILE_COUNT, ARCHIVE_DIRECTORY_COUNT, ARCHIVE_METADATA_COUNT, ARCHIVE_COMMENTARY_FILE_COUNT, ARCHIVE_RECORD_COUNT, 0):
        raise ValueError("LIB-061 projection census drifted")
    accountability = {
        "contract": "lib061-source-accountability-v9",
        "member_count": len(accounting),
        "regular_file_count": regular_count,
        "directory_count": directory_count,
        "toml_file_count": metadata_count + commentary_file_count,
        "metadata_object_count": metadata_count,
        "commentary_file_count": commentary_file_count,
        "commentary_record_count": record_count,
        "toml_parse_errors": parse_errors,
        "field_occurrences": field_counts,
        "field_type_occurrences": field_types,
        "members": accounting,
        "source_sha256": ARCHIVE_SHA256,
    }
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False), accountability


def _unresolved() -> bytes:
    items = [
        {"id": "LIB061-U1", "scope": "all-commentary-records", "kind": "translation-rights", "status": "human-review-required", "statement": "The retained LICENSE warns that a small number of quotations may originate from copyrighted translations; the affected records are not identified."},
        {"id": "LIB061-U2", "scope": "all-source-metadata", "kind": "identity-and-editorial-assertions", "status": "human-review-required", "statement": "Names, dates, source titles, URLs, authorship, verse associations, and readings are preserved as source assertions, not independently accepted facts."},
    ]
    return b"".join(_canonical(item) for item in items)


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    authorities = _route_authorities(source_manifest)
    profile = _strict_json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "LIB-061 profile")
    policy = _strict_json(source_manifest.authority_path("validation-policy").read_bytes(), "LIB-061 policy")
    if profile.get("profile_id") != "lib061-church-fathers-quotations-member-tree-v1" or policy.get("policy_id") != "lib061-church-fathers-quotations-policy-v1":
        raise ValueError("LIB-061 profile or policy identity drifted")
    envelope, members = _envelope(source_manifest)
    tei_bytes, accountability = _build_projection(source_manifest, members)
    license_path = source_manifest.authority_path("retained-license")
    license_text = license_path.read_text(encoding="utf-8")
    if "PUBLIC DOMAIN" not in license_text.upper():
        raise ValueError("LIB-061 retained license claim drifted")
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    provenance = {
        "contract": "ocd-lib061-provenance-v1",
        "status": "nonaccepted",
        "human_review": "required-not-accepted",
        "publication": "not_ready",
        "ticket_id": "LIB-061",
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_manifest_sha256": source_manifest.sha256,
        "source_envelope": {
            "path": "sources/structured-text/church-fathers-quotations/source-member-equality.json",
            "sha256": _sha(source_manifest.authority_path("source-member-equality").read_bytes()),
            "archive_sha256": ARCHIVE_SHA256,
            "archive_bytes": ARCHIVE_BYTES,
            "primary_member_set_sha256": _source_binding(source_manifest),
        },
        "rights": {
            "source_member": "./LICENSE",
            "classification": "public-domain-dedication-with-unlocalized-translation-caveat",
            "attribution_required": False,
            "summary": "PUBLIC DOMAIN; unrestricted use and no attribution required. Source warns that a small number of quotations may originate from copyrighted translations and invites copyright holders to request removal.",
        },
        "catalog_claim_lineage": {
            "work_id": WORK_ID,
            "claim_count": len(source_manifest.record["catalog_claim_lineage"]["claims"]),
            "status": "derived-output-claims-only",
        },
        "candidate_boundary": {
            "technical_validation_status": "candidate-pending-validation",
            "human_acceptance_status": "unresolved",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
        "authorities": {
            "primary_source_member_count": ARCHIVE_TOML_COUNT,
            "primary_source_member_set_sha256": _source_binding(source_manifest),
            "source_member_equality_sha256": _sha(source_manifest.authority_path("source-member-equality").read_bytes()),
            "profile_sha256": next(item["sha256"] for item in authorities if item.get("name") == "reconstruction-profile"),
            "policy_sha256": next(item["sha256"] for item in authorities if item.get("name") == "validation-policy"),
        },
    }
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": _unresolved(),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
