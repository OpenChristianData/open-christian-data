"""Family-neutral mechanical attestation assembly for faithful TEI readers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from .contract import CandidatePackage, SourceManifest


_HEX = frozenset("0123456789abcdef")

__all__ = (
    "MechanicalFacts",
    "MechanicalVerificationResult",
    "verify_mechanical_facts",
)


@dataclass(frozen=True, slots=True)
class MechanicalFacts:
    """Closed facts established by an independent source reader."""

    validator_implementation_sha256: str
    validator_import_closure_sha256: str
    source_sha256: str
    profile_sha256: str
    package_schema_sha256: str
    xsd_sha256: str
    policy_sha256: str
    findings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MechanicalVerificationResult:
    """Immutable attestation record consumed by the reconstruction contract."""

    status: str
    oracle_id: str
    oracle_version: str
    implementation_sha256: str
    import_closure_sha256: str
    runtime: str
    source_manifest_sha256: str
    candidate_sha256: str
    profile_sha256: str
    package_schema_sha256: str
    source_sha256: str
    xsd_sha256: str
    policy_sha256: str
    findings: tuple[str, ...]
    result_sha256: str

    def as_record(self) -> dict[str, object]:
        return {
            "status": self.status,
            "oracle_id": self.oracle_id,
            "oracle_version": self.oracle_version,
            "implementation_sha256": self.implementation_sha256,
            "import_closure_sha256": self.import_closure_sha256,
            "runtime": self.runtime,
            "source_manifest_sha256": self.source_manifest_sha256,
            "candidate_sha256": self.candidate_sha256,
            "profile_sha256": self.profile_sha256,
            "package_schema_sha256": self.package_schema_sha256,
            "source_sha256": self.source_sha256,
            "xsd_sha256": self.xsd_sha256,
            "policy_sha256": self.policy_sha256,
            "findings": list(self.findings),
            "result_sha256": self.result_sha256,
        }


def _canonical(record: object) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _runtime_binding() -> str:
    return (
        f"{platform.python_implementation()} {platform.python_version()} "
        f"({Path(sys.executable).resolve(strict=True)})"
    )


def _require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or not set(value) <= _HEX:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def verify_mechanical_facts(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    facts: MechanicalFacts,
) -> MechanicalVerificationResult:
    """Assemble a passing attestation from independently established facts."""

    source_manifest.verify()
    candidate.verify_integrity()
    for name, value in (
        (
            "validator_implementation_sha256",
            facts.validator_implementation_sha256,
        ),
        (
            "validator_import_closure_sha256",
            facts.validator_import_closure_sha256,
        ),
        ("source_sha256", facts.source_sha256),
        ("profile_sha256", facts.profile_sha256),
        ("package_schema_sha256", facts.package_schema_sha256),
        ("xsd_sha256", facts.xsd_sha256),
        ("policy_sha256", facts.policy_sha256),
    ):
        _require_digest(value, name)
    if not isinstance(facts.findings, tuple) or any(
        not isinstance(finding, str) for finding in facts.findings
    ):
        raise ValueError("findings must be a tuple of strings")
    if facts.findings:
        raise ValueError("mechanical verification requires zero findings")
    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping):
        raise ValueError("source manifest validator binding is invalid")
    oracle_id = validator.get("id")
    oracle_version = validator.get("version")
    if not isinstance(oracle_id, str) or not isinstance(oracle_version, str):
        raise ValueError("source manifest validator identity is invalid")
    record: dict[str, object] = {
        "status": "pass",
        "oracle_id": oracle_id,
        "oracle_version": oracle_version,
        "implementation_sha256": facts.validator_implementation_sha256,
        "import_closure_sha256": facts.validator_import_closure_sha256,
        "runtime": _runtime_binding(),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": facts.profile_sha256,
        "package_schema_sha256": facts.package_schema_sha256,
        "source_sha256": facts.source_sha256,
        "xsd_sha256": facts.xsd_sha256,
        "policy_sha256": facts.policy_sha256,
        "findings": list(facts.findings),
    }
    return MechanicalVerificationResult(
        status="pass",
        oracle_id=oracle_id,
        oracle_version=oracle_version,
        implementation_sha256=facts.validator_implementation_sha256,
        import_closure_sha256=facts.validator_import_closure_sha256,
        runtime=str(record["runtime"]),
        source_manifest_sha256=source_manifest.sha256,
        candidate_sha256=candidate.sha256,
        profile_sha256=facts.profile_sha256,
        package_schema_sha256=facts.package_schema_sha256,
        source_sha256=facts.source_sha256,
        xsd_sha256=facts.xsd_sha256,
        policy_sha256=facts.policy_sha256,
        findings=facts.findings,
        result_sha256=_sha(_canonical(record)),
    )
