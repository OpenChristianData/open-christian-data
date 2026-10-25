"""Independent standard-package oracle for LIB-062 Westminster Larger."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

import build.tei.lib062_json_catechisms_oracle as family


ORACLE_ID = "ocd-lib062-westminster-larger-catechism-independent-oracle"
ORACLE_VERSION = "1"
WORK_ID = "westminster-larger-catechism"


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

    value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _one_by_role(source: SourceManifest, role: str) -> Mapping[str, object]:
    authorities = source.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("LIB-062 source authorities are invalid")
    found = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == role
    ]
    if len(found) != 1:
        raise ValueError(f"LIB-062 requires exactly one {role} authority")
    return found[0]


def _authority_bytes(source: SourceManifest, role: str) -> bytes:
    authority = _one_by_role(source, role)
    return source.authority_path(str(authority["name"])).read_bytes()


def _closure_digest(root: Path, entry: Path) -> str:
    records = family.repository_import_closure(root, entry)
    return _sha(_canonical(records))


def _unresolved(source_path: str, source_sha: str) -> bytes:
    return b"".join(
        _canonical(row)
        for row in (
            {
                "category": "metadata",
                "status": "open",
                "claim": "Primary-source edition, translation, and authorship allocation remain human-review questions.",
                "source_path": source_path,
                "source_sha256": source_sha,
            },
            {
                "category": "rights",
                "status": "open",
                "claim": "The retained provider statements are evidence only; rights clearance is not claimed.",
                "source_path": source_path,
                "source_sha256": source_sha,
            },
            {
                "category": "review",
                "status": "open",
                "claim": "Human acceptance, accepted IR, promotion, and publication remain unperformed and unauthorized.",
                "source_path": source_path,
                "source_sha256": source_sha,
            },
        )
    )


def oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    if source_manifest.record.get("work_id") != WORK_ID:
        raise ValueError("LIB-062 manifest work identity drifted")
    packet, source, source_bytes = family._verify_packet_and_source(root, WORK_ID)
    primary = _one_by_role(source_manifest, "primary-source")
    source_path = str(primary["path"])
    if source_path != packet["authority"]["path"]:
        raise ValueError("LIB-062 manifest source path drifted")
    source_sha = _sha(source_bytes)
    normalized_sha = _sha(family._normalized_utf8(source_bytes))
    if source_sha != packet["authority"]["raw_sha256"]:
        raise ValueError("LIB-062 retained source hash drifted")

    expected_tei = family._expected_tei(WORK_ID, packet, source)
    observed_tei = candidate.member_bytes("content.tei.xml")
    if observed_tei != expected_tei:
        raise ValueError("LIB-062 standard TEI differs from independent expectation")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_comments=False, huge_tree=True
    )
    tree = etree.fromstring(observed_tei, parser=parser).getroottree()
    schema = etree.XMLSchema(
        etree.parse(str(source_manifest.authority_path(str(_one_by_role(source_manifest, "tei-validation-schema")["name"]))))
    )
    if not schema.validate(tree):
        raise ValueError(f"LIB-062 TEI P5 validation failed: {schema.error_log.last_error}")

    crosswalk = family._expected_crosswalk(WORK_ID, source)
    key_counts: dict[str, int] = {}
    family._key_counts(source, key_counts)
    expected_accountability = {
        "contract": "ocd-lib062-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member_disposition": "included in full as sole authority",
        "top_level_keys": ["Metadata", "Data"],
        "recursive_key_counts": key_counts,
        "data_record_count": len(source["Data"]),
        "represented_leaf_count": len(crosswalk),
        "omitted_leaf_count": 0,
        "duplicate_leaf_count": 0,
        "crosswalk": crosswalk,
    }
    if _strict_json(
        candidate.member_bytes("source-accountability.json"),
        "LIB-062 source accountability",
    ) != expected_accountability:
        raise ValueError("LIB-062 source accountability drifted")
    metadata = source["Metadata"]
    assert isinstance(metadata, dict)
    expected_provenance = {
        "contract": "ocd-lib062-westminster-larger-catechism-provenance-v1",
        "work_id": WORK_ID,
        "retained_source": {
            "path": source_path,
            "bytes": len(source_bytes),
            "sha256": source_sha,
            "normalized_utf8_sha256": normalized_sha,
        },
        "retained_metadata": metadata,
        "rights": {
            "evidence_path": "raw/Creeds.json/README.md",
            "provider_statement": "Unlicense claim retained in source packet; worldwide clearance is not claimed",
            "human_review": "required",
        },
        "status": {
            "candidate": "nonaccepted",
            "human_review": "required",
            "accepted_ir": "not_accepted",
            "publication": "not_ready",
        },
        "authority_boundary": (
            "Retained Creeds.json bytes and the LIB-062 packet are authority. "
            "The legacy data JSON is a catalog claim only and was not read by the converter."
        ),
    }
    if _strict_json(candidate.member_bytes("provenance.json"), "LIB-062 provenance") != expected_provenance:
        raise ValueError("LIB-062 provenance drifted")
    if candidate.member_bytes("README.source.md") != (root / "sources/westminster-larger-catechism/LIB-062.README.md").read_bytes():
        raise ValueError("LIB-062 attribution README drifted")
    if candidate.member_bytes("unresolved.jsonl") != _unresolved(source_path, source_sha):
        raise ValueError("LIB-062 unresolved evidence drifted")

    policy = _strict_json(_authority_bytes(source_manifest, "independent-validation-policy"), "LIB-062 validation policy")
    if policy.get("candidate_status") != "nonaccepted":
        raise ValueError("LIB-062 validation policy status drifted")
    closure_sha = _closure_digest(root, Path(__file__))
    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping) or validator.get("import_closure_sha256") != closure_sha:
        raise ValueError("LIB-062 oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure_sha,
        source_sha256=source_sha,
        profile_sha256=str(_one_by_role(source_manifest, "complete-source-feature-profile")["sha256"]),
        package_schema_sha256=str(_one_by_role(source_manifest, "candidate-package-schema")["sha256"]),
        xsd_sha256=str(_one_by_role(source_manifest, "tei-validation-schema")["sha256"]),
        policy_sha256=_sha(_authority_bytes(source_manifest, "independent-validation-policy")),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = ORACLE_ID
oracle.oracle_version = ORACLE_VERSION


__all__ = ("ORACLE_ID", "ORACLE_VERSION", "oracle")
