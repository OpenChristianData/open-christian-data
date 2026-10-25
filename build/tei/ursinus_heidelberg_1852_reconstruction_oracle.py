"""Independent declared-package validation for the retained Ursinus source."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Mapping
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator
from lxml import etree

from build.tei import ursinus_heidelberg_1852_v2_oracle as source_oracle_module
from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-ursinus-1852-independent-source-oracle"
ORACLE_VERSION = "1"
WORK_ID = "ursinus-commentary-heidelberg-catechism-1852"
EDITION_ID = "commdrza00ursi-1852"
ACQUISITION_ID = "ia-commdrza00ursi-second-american-1852"
TEI_NS = "{http://www.tei-c.org/ns/1.0}"
EXPECTED_CLOSURE_PATHS = {
    "build/__init__.py",
    "build/tei/__init__.py",
    "build/tei/ursinus_heidelberg_1852_v2_oracle.py",
    "build/tei/ursinus_heidelberg_1852_reconstruction_oracle.py",
    "ocd_kernel/__init__.py",
    "ocd_kernel/reconstruction/__init__.py",
    "ocd_kernel/reconstruction/contract.py",
    "ocd_kernel/reconstruction/verifier.py",
}


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json(payload: bytes, label: str) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not UTF-8 JSON") from error


def _authority_rows(source_manifest: SourceManifest) -> list[Mapping[str, object]]:
    rows = source_manifest.record.get("authorities")
    if not isinstance(rows, tuple) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("source manifest authority list is invalid")
    return list(rows)


def _by_name(source_manifest: SourceManifest) -> dict[str, Mapping[str, object]]:
    return {str(row["name"]): row for row in _authority_rows(source_manifest)}


def _authority_for_role(source_manifest: SourceManifest, role: str) -> Mapping[str, object]:
    matches = [row for row in _authority_rows(source_manifest) if row.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"source manifest must bind exactly one {role} authority")
    return matches[0]


def _closure(source_manifest: SourceManifest, policy: Mapping[str, object]) -> str:
    dependencies = policy.get("oracle_import_closure")
    if not isinstance(dependencies, list) or set(dependencies) != EXPECTED_CLOSURE_PATHS:
        raise ValueError("independent oracle import closure inventory differs")
    inventory = [
        {"path": path, "sha256": _sha((source_manifest.repository_root / path).read_bytes())}
        for path in sorted(dependencies)
    ]
    return _sha(_canonical(inventory))


def _source_hash(authorities: list[Mapping[str, object]]) -> str:
    rows = sorted(
        (
            {key: row[key] for key in ("name", "path", "bytes", "sha256")}
            for row in authorities
            if row.get("role") == "primary-source"
        ),
        key=lambda row: (str(row["path"]), str(row["name"])),
    )
    if not rows:
        raise ValueError("source manifest has no primary-source authorities")
    if len(rows) == 1:
        return str(rows[0]["sha256"])
    return _sha(_canonical({"contract": "ocd-source-member-set-v1", "members": rows}))


def _verify_source_binding(source_manifest: SourceManifest, policy: Mapping[str, object]) -> tuple[dict[str, Mapping[str, object]], Path, dict[str, object], dict[str, object]]:
    if source_manifest.record.get("work_id") != WORK_ID or source_manifest.record.get("edition_id") != EDITION_ID or source_manifest.record.get("acquisition_id") != ACQUISITION_ID:
        raise ValueError("source manifest work, edition, or acquisition identity differs")
    authorities = _by_name(source_manifest)
    rows = _authority_rows(source_manifest)
    primary = [row for row in rows if row.get("role") == "primary-source"]
    if len(primary) != 5 or len({row.get("path") for row in primary}) != 5:
        raise ValueError("candidate must bind exactly five unique primary-source members")
    envelope = [row for row in rows if row.get("role") == "retained-source-envelope-support"]
    if len(envelope) != 3:
        raise ValueError("candidate must bind all three retained envelope support files")
    source_dir = source_manifest.authority_path("source-ocr-xml").parent
    if {Path(str(row["path"])).name for row in primary} != {"scan.pdf", "ocr.txt", "ocr.xml", "page-numbers.json", "scandata.xml"}:
        raise ValueError("primary-source authorities do not match the retained textual/scan witnesses")

    work = _json(source_manifest.authority_path("work-identity").read_bytes(), "work identity")
    acquisition = _json(source_manifest.authority_path("acquisition-selection").read_bytes(), "acquisition sidecar")
    state = _json(source_manifest.authority_path("work-state").read_bytes(), "work state")
    if not isinstance(work, dict) or work.get("work_id") != WORK_ID:
        raise ValueError("declared work sidecar identity differs")
    if not isinstance(acquisition, dict) or acquisition.get("acquisition_id") != ACQUISITION_ID or acquisition.get("edition_id") != EDITION_ID:
        raise ValueError("declared acquisition sidecar identity differs")
    member_set_path = source_manifest.authority_path("acquisition-member-set")
    if acquisition.get("source_path") != member_set_path.relative_to(source_manifest.repository_root).as_posix():
        raise ValueError("acquisition sidecar does not name its ordered member-set authority")
    expected_member_set = _canonical({
        "contract": "ocd-retained-source-member-set-v1",
        "acquisition_id": ACQUISITION_ID,
        "edition_id": EDITION_ID,
        "scope": acquisition.get("source_scope"),
        "members": [dict(member, position=index) for index, member in enumerate(acquisition.get("retained_files", []), 1)],
    })
    if member_set_path.read_bytes() != expected_member_set or len(expected_member_set) != acquisition.get("source_bytes") or _sha(expected_member_set) != acquisition.get("source_sha256"):
        raise ValueError("acquisition ordered source-member-set bytes or digest differ")
    if not isinstance(state, dict) or state.get("work_id") != WORK_ID:
        raise ValueError("declared state sidecar identity differs")
    target_states = {(row.get("target_type"), row.get("target_id")): row.get("stage") for row in state.get("targets", []) if isinstance(row, dict)}
    if target_states.get(("acquisition", ACQUISITION_ID)) != "acquired" or target_states.get(("edition", EDITION_ID)) != "review":
        raise ValueError("source sidecar lifecycle does not reflect retained acquisition and review-stage candidate")
    retained = {
        (row.get("path"), row.get("bytes"), row.get("sha256"))
        for row in acquisition.get("retained_files", [])
        if isinstance(row, dict)
    }
    primary_members = {(row.get("path"), row.get("bytes"), row.get("sha256")) for row in primary}
    if primary_members != retained:
        raise ValueError("primary-source authority set differs from exact acquisition retained_files")
    for row in primary:
        path = source_manifest.authority_path(str(row["name"]))
        if path.parent != source_dir or path.name != Path(str(row["path"])).name:
            raise ValueError("primary-source authority resolves outside the retained source envelope")
    return authorities, source_dir, work, acquisition


def oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    """Independently verify source identity, scope, TEI, package and linkage facts."""
    source_manifest.verify()
    candidate.verify_integrity()
    authorities = _by_name(source_manifest)
    policy = _json(source_manifest.authority_path("validation-policy").read_bytes(), "validation policy")
    if not isinstance(policy, dict) or policy.get("contract") != "ocd-ursinus-independent-validation-policy-v1":
        raise ValueError("bound validation policy contract differs")
    authority_map, source_dir, work, acquisition = _verify_source_binding(source_manifest, policy)
    profile = _json(source_manifest.authority_path("reconstruction-profile").read_bytes(), "reconstruction profile")
    if not isinstance(profile, dict) or profile.get("contract") != "ocd-ursinus-source-feature-profile-v1":
        raise ValueError("bound reconstruction profile contract differs")
    if profile.get("manifest_rows") != ["L427", "L468"] or profile.get("source_identity", {}).get("item_identifier") != "commdrza00ursi":
        raise ValueError("source profile identity or duplicate-row mapping differs")
    skill = source_manifest.authority_path("source-to-tei-skill").read_text(encoding="utf-8")
    if "One complete top-level titled work, exactly one TEI" not in skill or "produce exactly one candidate TEI document" not in skill:
        raise ValueError("bound source-to-TEI skill does not state the one-complete-work/one-TEI rule")

    manifest_record = dict(candidate.manifest)
    expected_manifest_path = source_manifest.path.relative_to(source_manifest.repository_root).as_posix()
    if (
        manifest_record.get("source_id") != source_manifest.record.get("source_id")
        or manifest_record.get("status") != "nonaccepted"
        or manifest_record.get("source_manifest") != {"path": expected_manifest_path, "sha256": source_manifest.sha256}
        or manifest_record.get("converter") != dict(source_manifest.record.get("converter", {}))
        or manifest_record.get("package_schema") != dict(source_manifest.record.get("package_schema", {}))
    ):
        raise ValueError("candidate manifest source binding differs")
    expected_names = {"README.source.md", "content.tei.xml", "provenance.json", "source-accountability.json", "unresolved.jsonl"}
    if {row.get("name") for row in manifest_record.get("members", []) if isinstance(row, Mapping)} != expected_names:
        raise ValueError("candidate package member inventory differs")

    unresolved_expected = policy.get("unresolved_fidelity_gaps")
    if not isinstance(unresolved_expected, list) or len(unresolved_expected) < 2:
        raise ValueError("validation policy does not bind true fidelity gaps")
    expected_unresolved = b"".join(_canonical(row) for row in unresolved_expected)
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("candidate unresolved fidelity ledger differs from policy")
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    if candidate.member_bytes("README.source.md") != readme:
        raise ValueError("candidate source record differs from the bound source-attribution authority")

    accountability_bytes = candidate.member_bytes("source-accountability.json")
    accountability = _json(accountability_bytes, "candidate source accountability")
    schema = _json(source_manifest.authority_path("source-accountability-schema").read_bytes(), "source accountability schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=lambda item: list(item.absolute_path))
    if errors:
        raise ValueError(f"source accountability schema failure: {errors[0].message}")
    if not isinstance(accountability, dict) or accountability.get("work_id") != WORK_ID or accountability.get("edition_id") != EDITION_ID or accountability.get("acquisition_id") != ACQUISITION_ID:
        raise ValueError("candidate source-accountability work/acquisition binding differs")
    one_work = accountability["one_work_one_tei"]
    if one_work.get("source_attested_complete_work_count") != 1 or one_work.get("candidate_tei_count") != 1 or one_work.get("manifest_rows") != ["L427", "L468"]:
        raise ValueError("candidate one-work/one-TEI scope is not proved")
    source_hashes = accountability.get("source_member_hashes")
    if not isinstance(source_hashes, dict) or len(source_hashes) != 8:
        raise ValueError("candidate source envelope hash inventory is incomplete")
    for name, digest in source_hashes.items():
        if name not in {"scan.pdf", "ocr.txt", "ocr.xml", "page-numbers.json", "scandata.xml", "metadata.json", "acquisition-receipt.json", "member-inventory.tsv"} or _sha((source_dir / name).read_bytes()) != digest:
            raise ValueError(f"candidate source-envelope hash differs: {name}")
    if set(source_hashes) != {Path(str(row["path"])).name for row in [*authority_map.values()] if row.get("role") in {"primary-source", "retained-source-envelope-support"}}:
        raise ValueError("source-accountability members differ from the eight bound retained files")

    provenance = _json(candidate.member_bytes("provenance.json"), "candidate provenance")
    expected_authorities = {name: str(row["sha256"]) for name, row in authorities.items()}
    expected_provenance = {
        "contract": "ocd-ursinus-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "authorities": expected_authorities,
        "converter": dict(source_manifest.record["converter"]),
        "work_id": WORK_ID,
        "edition_id": EDITION_ID,
        "acquisition_id": ACQUISITION_ID,
        "source_id": source_manifest.record["source_id"],
        "source_identity": profile["source_identity"],
        "work_boundary": profile["work_boundary"],
        "retained_source_envelope": sorted(source_hashes),
        "candidate_member": "content.tei.xml",
        "candidate_sha256": _sha(candidate.member_bytes("content.tei.xml")),
        "candidate_status": "nonaccepted",
        "mapping_summary": "One source-titled commentary, represented by exactly one candidate TEI with all 720 PDF/OCR pages and both retained scan-linked diagrams.",
    }
    if provenance != expected_provenance:
        raise ValueError("candidate provenance or sidecar linkage differs")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    tei = etree.fromstring(tei_bytes, parser)
    if tei.tag != TEI_NS + "TEI" or len(tei.findall("./" + TEI_NS + "text")) != 1 or len(tei.findall("./" + TEI_NS + "text/" + TEI_NS + "body")) != 1:
        raise ValueError("candidate TEI does not have one TEI root, one text and one body")
    body = tei.find("./" + TEI_NS + "text/" + TEI_NS + "body")
    if body is None or len(body.findall("./" + TEI_NS + "div")) != 1:
        raise ValueError("one top-level complete titled work must map to one TEI body division")
    title_nodes = tei.findall("./" + TEI_NS + "teiHeader/" + TEI_NS + "fileDesc/" + TEI_NS + "titleStmt/" + TEI_NS + "title")
    if len(title_nodes) != 1 or " ".join("".join(title_nodes[0].itertext()).split()) != profile["source_identity"]["title"]:
        raise ValueError("candidate TEI title does not match the retained source title")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    xsd_parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    etree.XMLSchema(etree.parse(str(xsd_path), xsd_parser)).assertValid(tei)
    rng = etree.RelaxNG(etree.parse(str(source_manifest.authority_path("tei-p5-relaxng")), xsd_parser))
    if not rng.validate(tei):
        raise ValueError("candidate TEI P5 Relax NG validation failed")
    for name in ("tei-p5-xsd-teix", "tei-p5-xsd-xml"):
        source_manifest.authority_path(name)

    # This source-only oracle independently reconstructs page and contents
    # expectations, then verifies every page, paragraph, line, diagram, and URI.
    historical = source_oracle_module.source_oracle(source_manifest.repository_root)
    legacy_tree = ET.ElementTree(ET.fromstring(tei_bytes))
    structural = source_oracle_module.verify_tree(legacy_tree, historical, candidate.path, source_dir)
    if structural["pages"] != 720 or structural["paragraphs"] != 6005 or structural["lines"] != 34726 or structural["contents_rows"] != 436 or structural["empty_ocr_pages"] != 16:
        raise ValueError("independent page, text, or contents totals differ")
    expected_leaf_rows = []
    for page in historical["pages"]:
        lines = page["paragraph_lines"]
        expected_leaf_rows.append((len(lines), sum(len(paragraph) for paragraph in lines), page["printed_page_label"], page["section"]))
    observed_leaf_rows = [
        (row["paragraphs"], row["lines"], row["printed_page_label"], row["section"])
        for row in accountability["leaves"]
    ]
    if observed_leaf_rows != expected_leaf_rows:
        raise ValueError("per-leaf accounting differs from independent retained source")
    row_map = accountability.get("contents_row_map")
    if not isinstance(row_map, list) or len(row_map) != len(historical["contents_anchors"]):
        raise ValueError("source contents row map is incomplete")
    for observed, expected in zip(row_map, historical["contents_anchors"]):
        if observed.get("leaf") != expected["leaf"] or observed.get("row") != expected["row"] or str(observed.get("raw_page_label")) != expected["raw_page_label"] or expected["number_line_id"] not in observed.get("source_line_ids", []):
            raise ValueError("source contents row map differs from retained OCR coordinates")
    candidate_tei = accountability["candidate_tei"]
    if candidate_tei.get("bytes") != len(tei_bytes) or candidate_tei.get("sha256") != _sha(tei_bytes) or candidate_tei.get("root_count") != 1 or candidate_tei.get("text_count") != 1 or candidate_tei.get("body_division_count") != 1:
        raise ValueError("source accounting TEI identity differs")
    scan_envelope = accountability.get("scan_envelope", {})
    if scan_envelope.get("access_pdf_pages") != 720 or scan_envelope.get("ocr_pages") != 720 or scan_envelope.get("scandata_leaves") != 722 or scan_envelope.get("empty_ocr_pages") != 16:
        raise ValueError("source scan/page-envelope accounting differs")
    if [row.get("leaf") for row in scan_envelope.get("excluded_scan_leaves", [])] != [0, 721]:
        raise ValueError("explicit excluded calibration leaves are not accounted")

    for package, expected_version in policy.get("runtime_dependencies", {}).items():
        if importlib.metadata.version(package) != expected_version:
            raise ValueError(f"validation runtime dependency differs: {package}")
    closure = _closure(source_manifest, policy)
    if closure != source_manifest.record["validator"].get("import_closure_sha256"):
        raise ValueError("independent oracle import-closure digest differs")
    xsd_sha = str(_authority_for_role(source_manifest, "tei-validation-schema")["sha256"])
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=_source_hash(_authority_rows(source_manifest)),
        profile_sha256=str(_authority_for_role(source_manifest, "complete-source-feature-profile")["sha256"]),
        package_schema_sha256=str(_authority_for_role(source_manifest, "candidate-package-schema")["sha256"]),
        xsd_sha256=xsd_sha,
        policy_sha256=str(_authority_for_role(source_manifest, "independent-validation-policy")["sha256"]),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = ORACLE_ID
oracle.oracle_version = ORACLE_VERSION
