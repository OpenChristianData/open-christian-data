"""Independently verify one exact LIB062 candidate from six retained members."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts

import build.tei.lib062_json_catechisms_oracle as family


ORACLE_ID = "ocd-lib062-six-catechisms-independent-oracle"
ORACLE_VERSION = "1"
WORK_IDS = frozenset({
    "1695-baptist-catechism", "exposition-of-the-assemblies-catechism",
    "heidelberg-catechism", "keachs-catechism",
    "matthew-henrys-scripture-catechism", "puritan-catechism",
})


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


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
        raise ValueError("LIB062 source authorities are invalid")
    found = [item for item in authorities if isinstance(item, Mapping) and item.get("role") == role]
    if len(found) != 1:
        raise ValueError(f"LIB062 requires exactly one {role} authority")
    return found[0]


def _unresolved(source_path: str, source_sha: str) -> bytes:
    rows = [
        {"category": "metadata", "status": "open",
         "claim": "Primary-source edition, translation, and authorship allocation remain human-review questions.",
         "source_path": source_path, "source_sha256": source_sha},
        {"category": "rights", "status": "open",
         "claim": "The retained provider statements are evidence only; rights clearance is not claimed.",
         "source_path": source_path, "source_sha256": source_sha},
        {"category": "review", "status": "open",
         "claim": "Human acceptance, accepted IR, promotion, and publication remain unperformed and unauthorized.",
         "source_path": source_path, "source_sha256": source_sha},
    ]
    return b"".join(_canonical(row) for row in rows)


def oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    work_id = source_manifest.record.get("work_id")
    if work_id not in WORK_IDS:
        raise ValueError(f"LIB062 six-work oracle is outside its exact work set: {work_id}")
    packet, source, source_bytes = family._verify_packet_and_source(root, work_id)
    primary = _one_by_role(source_manifest, "primary-source")
    source_path = str(primary["path"])
    source_sha = _sha(source_bytes)
    if source_path != packet["authority"]["path"] or source_sha != packet["authority"]["raw_sha256"]:
        raise ValueError("LIB062 retained member differs from packet")
    observed_tei = candidate.member_bytes("content.tei.xml")
    if observed_tei != family._expected_tei(work_id, packet, source):
        raise ValueError("LIB062 candidate TEI differs from independent source expectation")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, remove_comments=False, huge_tree=True)
    tree = etree.fromstring(observed_tei, parser=parser).getroottree()
    schema = etree.XMLSchema(etree.parse(str(source_manifest.authority_path(str(_one_by_role(source_manifest, "tei-validation-schema")["name"])))))
    if not schema.validate(tree):
        raise ValueError(f"LIB062 TEI P5 validation failed: {schema.error_log.last_error}")
    crosswalk = family._expected_crosswalk(work_id, source)
    key_counts: dict[str, int] = {}
    family._key_counts(source, key_counts)
    expected_accountability = {
        "contract": "ocd-lib062-source-accountability-v1", "work_id": work_id,
        "source_member_disposition": "included in full as sole authority",
        "top_level_keys": ["Metadata", "Data"], "recursive_key_counts": key_counts,
        "data_record_count": len(source["Data"]), "represented_leaf_count": len(crosswalk),
        "omitted_leaf_count": 0, "duplicate_leaf_count": 0, "crosswalk": crosswalk,
    }
    if _strict_json(candidate.member_bytes("source-accountability.json"), "LIB062 accountability") != expected_accountability:
        raise ValueError("LIB062 source accountability drifted")
    provenance = {
        "contract": "ocd-lib062-six-catechisms-provenance-v1", "work_id": work_id,
        "retained_source": {
            "path": source_path, "bytes": len(source_bytes), "sha256": source_sha,
            "normalized_utf8_sha256": _sha(family._normalized_utf8(source_bytes)),
        },
        "retained_metadata": source["Metadata"],
        "rights": {"evidence_path": "raw/Creeds.json/README.md",
                   "provider_statement": "Unlicense claim retained in source packet; worldwide clearance is not claimed",
                   "human_review": "required"},
        "status": {"candidate": "nonaccepted", "human_review": "required",
                   "accepted_ir": "not_accepted", "publication": "not_ready"},
        "authority_boundary": (
            "Retained Creeds.json bytes and the LIB-062 packet are authority. "
            "Legacy data JSON is a catalog claim only and was not read by the converter."
        ),
    }
    if _strict_json(candidate.member_bytes("provenance.json"), "LIB062 provenance") != provenance:
        raise ValueError("LIB062 provenance drifted")
    if candidate.member_bytes("README.source.md") != (root / "sources" / work_id / "LIB-062.README.md").read_bytes():
        raise ValueError("LIB062 source-local attribution README drifted")
    if candidate.member_bytes("unresolved.jsonl") != _unresolved(source_path, source_sha):
        raise ValueError("LIB062 unresolved evidence drifted")
    policy = _strict_json(source_manifest.authority_path(str(_one_by_role(source_manifest, "independent-validation-policy")["name"])).read_bytes(), "LIB062 policy")
    if policy.get("candidate_status") != "nonaccepted" or policy.get("forbidden_oracle_imports") != ["build.tei.lib062_six_catechisms_reconstruction"]:
        raise ValueError("LIB062 independent validation policy drifted")
    closure_sha = _sha(_canonical(family.repository_import_closure(root, Path(__file__))))
    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping) or validator.get("import_closure_sha256") != closure_sha:
        raise ValueError("LIB062 oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure_sha,
        source_sha256=source_sha,
        profile_sha256=str(_one_by_role(source_manifest, "complete-source-feature-profile")["sha256"]),
        package_schema_sha256=str(_one_by_role(source_manifest, "candidate-package-schema")["sha256"]),
        xsd_sha256=str(_one_by_role(source_manifest, "tei-validation-schema")["sha256"]),
        policy_sha256=str(_one_by_role(source_manifest, "independent-validation-policy")["sha256"]),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = ORACLE_ID
oracle.oracle_version = ORACLE_VERSION
