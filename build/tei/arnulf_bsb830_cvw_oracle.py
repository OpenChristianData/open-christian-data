"""Independent Arnulf source/accepted-byte oracle for a CVW review package."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import platform
import sys

from build.tei.openmgh_exact_work_div import check_candidate, parse_tei, source_work_div
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.install_accepted import _io_path
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-arnulf-bsb830-exact-div-cvw-oracle"
ORACLE_VERSION = "1"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return sha256(content).hexdigest()


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _record(content: bytes, name: str) -> dict:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    profile = _record(source_manifest.authority_path("reconstruction-profile").read_bytes(), "profile")
    policy = _record(source_manifest.authority_path("validation-policy").read_bytes(), "policy")
    exact = _record(source_manifest.authority_path("exact-work-div-manifest").read_bytes(), "exact manifest")
    inventory = _record(source_manifest.authority_path("source-inventory").read_bytes(), "inventory")
    work = _record(source_manifest.authority_path("work-sidecar").read_bytes(), "work")
    source = source_manifest.authority_path("extracted-xml").read_bytes()
    acquisition_path = source_manifest.repository_root / profile["acquisition_path"]
    acquisition_bytes = Path(_io_path(acquisition_path)).read_bytes()
    acquisition = _record(acquisition_bytes, "acquisition")
    master_path = source_manifest.repository_root / profile["accepted_master_path"]
    master = Path(_io_path(master_path)).read_bytes()
    if (
        profile.get("contract") != "ocd-openmgh-exclusive-profile-v1"
        or policy.get("contract") != "ocd-arnulf-bsb830-cvw-policy-v1"
        or exact.get("contract") != "ocd-openmgh-exact-work-div-batch-v1"
        or inventory.get("contract") != "ocd-arnulf-bsb830-source-selection-v1"
        or _sha(source) != profile.get("source_sha256")
        or _sha(acquisition_bytes) != profile.get("acquisition_sha256")
        or _sha(master) != profile.get("accepted_master_sha256")
        or _sha(source_manifest.authority_path("exact-work-div-manifest").read_bytes()) != profile.get("exact_manifest_sha256")
        or work.get("work_id") != profile.get("work_id")
        or acquisition.get("source_path") != profile.get("source_path")
        or acquisition.get("source_sha256") != profile.get("source_sha256")
        or inventory.get("selected_work_div_index") != 4
        or inventory.get("selected_part_count") != 2
        or len(exact.get("works", [])) != 1
    ):
        raise ValueError("Arnulf retained, accepted, or declared identity drifted")
    entry = exact["works"][0]
    if entry.get("work_id") != profile["work_id"]:
        raise ValueError("exact manifest selected another work")
    content = candidate.member_bytes("content.tei.xml")
    if content != master:
        raise ValueError("CVW candidate bytes differ from the accepted master")
    actual = parse_tei(content)
    if actual.get(XML_ID) != f"ocd-{profile['work_id']}-openmgh-electronic-v1":
        raise ValueError("accepted TEI root identity drifted")
    details = check_candidate(source, content, exact, entry, work, acquisition)
    selected, _ = source_work_div(source, exact, entry, work, acquisition)
    parts = [node for node in selected if node.tag.endswith("}div") and node.get("type") == "part"]
    declared_parts = inventory["selected_part_boundaries"]
    if len(parts) != len(declared_parts):
        raise ValueError("letter/tract part count drifted")
    for part, declaration in zip(parts, declared_parts, strict=True):
        lines = [node.get(XML_ID) for node in part.iter() if node.tag.endswith("}lb")]
        if not lines or (lines[0], lines[-1]) != (
            declaration["first_line_id"], declaration["last_line_id"]
        ):
            raise ValueError("letter/tract source span drifted")
    accounting = _record(candidate.member_bytes("source-accountability.json"), "accounting")
    provenance = _record(candidate.member_bytes("provenance.json"), "provenance")
    if (
        accounting.get("contract") != "ocd-openmgh-exclusive-accounting-v1"
        or accounting.get("work_id") != profile["work_id"]
        or accounting.get("source_sha256") != profile["source_sha256"]
        or accounting.get("work_div_ordinal") != 5
        or accounting.get("element_counts", {}).get("lb") != details["source_line_breaks"]
        or accounting.get("element_counts", {}).get("pb") != details["source_page_breaks"]
        or provenance.get("status") != "nonaccepted"
        or provenance.get("canonical_ir_written") is not False
        or provenance.get("work_id") != profile["work_id"]
        or not candidate.member_bytes("unresolved.jsonl").strip()
        or b"Monumenta Germaniae Historica" not in candidate.member_bytes("README.source.md")
    ):
        raise ValueError("candidate accounting or review provenance drifted")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    compiled_schema().assertValid(actual)
    closure = policy.get("closure_inputs")
    if not isinstance(closure, list) or not closure or any(not isinstance(item, str) for item in closure):
        raise ValueError("oracle closure is invalid")
    closure_entries = [
        {"path": relative, "sha256": _sha((source_manifest.repository_root / relative).read_bytes())}
        for relative in closure
    ]
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": _sha(_json(closure_entries)),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(xsd_path.read_bytes()),
        "policy_sha256": _sha(source_manifest.authority_path("validation-policy").read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_json(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION


__all__ = ("_oracle",)
