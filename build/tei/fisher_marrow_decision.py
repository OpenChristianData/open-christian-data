"""Fisher retained-member census and source-local decision compatibility.

Fisher owns only its reviewed retained-member census.  Candidate review and
decision behavior is delegated to the generic reconstruction decision module
so this source cannot drift into a second decision contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from ocd_kernel.reconstruction import decision as reconstruction_decision
from ocd_kernel.reconstruction.contract import ReviewView, SourceManifest


FISHER_SOURCE_ID = "internet-archive-fisher-marrow-1837-retained-ocr"
FISHER_WORK_ID = "fisher-marrow-of-modern-divinity"
MEMBER_CENSUS_CONTRACT = "ocd-fisher-marrow-member-census-v1"
DECISION_CONTRACT = reconstruction_decision.DECISION_CONTRACT
DECISION_DISPOSITIONS = reconstruction_decision.DECISION_DISPOSITIONS
_EXPECTED_EXCLUDED_PATHS = (
    "data/structured-text/fisher-marrow-of-modern-divinity.json",
    "ir/census/fisher-marrow-of-modern-divinity.ia-ocr.census.json",
    "ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.tei.xml",
    "ir/fisher/fisher-marrow-of-modern-divinity.ia-ocr.viewer-dialogue.png",
    "ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl",
    "ir/fisher/hf/fisher-marrow-of-modern-divinity.ia-ocr.jsonl.loss.json",
    "sources/fisher-marrow-of-modern-divinity/witnesses.json",
    "sources/structured-text/fisher-marrow-of-modern-divinity/config.json",
)


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            _jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def load_verified_review(
    source_manifest: SourceManifest,
    *,
    candidate_path: str | Path,
    validation_path: str | Path,
) -> ReviewView:
    """Delegate Fisher candidate/report verification to the generic contract."""

    return reconstruction_decision.load_verified_review(
        source_manifest,
        candidate_path=candidate_path,
        validation_path=validation_path,
    )


def _manifest_entries(manifest: SourceManifest, field: str) -> list[dict[str, object]]:
    value = manifest.record.get(field)
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"Fisher source manifest {field} must be an array")
    entries: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"Fisher source manifest {field} contains a non-object")
        plain = _jsonable(item)
        if not isinstance(plain, dict):
            raise ValueError(
                f"Fisher source manifest {field} contains an invalid object"
            )
        entries.append(plain)
    return entries


def retained_member_census(source_manifest: SourceManifest) -> dict[str, object]:
    """Return the exact Fisher source-member inventory with reasons.

    The included member must be the manifest's complete primary-source
    authority.  Exclusions are explicit paths from the source manifest; no
    directory or wildcard expansion is accepted.
    """

    source_manifest.verify()
    if source_manifest.record.get("source_id") != FISHER_SOURCE_ID:
        raise ValueError("Fisher member census source identity mismatch")
    if source_manifest.record.get("work_id") != FISHER_WORK_ID:
        raise ValueError("Fisher member census work identity mismatch")

    source_members = _manifest_entries(source_manifest, "source_members")
    excluded_members = _manifest_entries(source_manifest, "excluded_members")
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Fisher source manifest authorities are invalid")
    primary = [
        _jsonable(item)
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == "primary-source"
    ]
    if len(source_members) != len(primary) or len(source_members) != 1:
        raise ValueError(
            "Fisher retained-member census must contain one primary source"
        )

    included: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    seen_names: set[str] = set()
    for item in source_members:
        name = _nonempty(item.get("logical_name"), "Fisher included logical_name")
        path = _nonempty(item.get("path"), "Fisher included path")
        role = _nonempty(item.get("role"), "Fisher included role")
        reason = _nonempty(item.get("reason"), f"Fisher included reason for {path}")
        if name in seen_names or path in seen_paths:
            raise ValueError("Fisher retained-member census contains duplicate members")
        seen_names.add(name)
        seen_paths.add(path)
        if role != "primary-source":
            raise ValueError("Fisher included member is not a primary source")
        authority = next(
            (
                dict(_jsonable(item))
                for item in primary
                if isinstance(item, Mapping)
                and item.get("name") == name
                and item.get("path") == path
            ),
            None,
        )
        if authority is None:
            raise ValueError("Fisher included member is not bound by an authority")
        if item.get("bytes") != authority.get("bytes") or item.get(
            "sha256"
        ) != authority.get("sha256"):
            raise ValueError(f"Fisher included member metadata drifted for {path}")
        resolved = source_manifest.authority_path(name)
        content = resolved.read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(f"Fisher included member bytes drifted for {path}")
        included.append(
            {
                "logical_name": name,
                "path": path,
                "role": role,
                "bytes": item["bytes"],
                "sha256": item["sha256"],
                "disposition": "included",
                "reason": reason,
            }
        )

    excluded: list[dict[str, object]] = []
    for item in excluded_members:
        name = _nonempty(item.get("logical_name"), "Fisher excluded logical_name")
        path = _nonempty(item.get("path"), "Fisher excluded path")
        reason = _nonempty(item.get("reason"), f"Fisher excluded reason for {path}")
        if name in seen_names or path in seen_paths:
            raise ValueError("Fisher retained-member census contains duplicate members")
        seen_names.add(name)
        seen_paths.add(path)
        excluded.append(
            {
                "logical_name": name,
                "path": path,
                "disposition": "excluded",
                "reason": reason,
            }
        )
    excluded.sort(key=lambda item: str(item["path"]))
    if tuple(str(item["path"]) for item in excluded) != _EXPECTED_EXCLUDED_PATHS:
        raise ValueError(
            "Fisher retained-member exclusion inventory differs from reviewed scope"
        )
    included.sort(key=lambda item: str(item["path"]))
    return {
        "contract": MEMBER_CENSUS_CONTRACT,
        "source_id": FISHER_SOURCE_ID,
        "work_id": FISHER_WORK_ID,
        "included": included,
        "excluded": excluded,
        "counts": {
            "included": len(included),
            "excluded": len(excluded),
            "total": len(included) + len(excluded),
        },
    }


def member_census_digest(census: Mapping[str, object]) -> str:
    """Digest a canonical Fisher member census without writing an artifact."""

    return _sha(_canonical(census))


def decision_path(manifest_path: str | Path) -> Path:
    """Return the generic source-local path for the fixed Fisher identity."""

    return reconstruction_decision.decision_path(
        manifest_path,
        source_id=FISHER_SOURCE_ID,
        work_id=FISHER_WORK_ID,
    )


def validate_decision(
    record: Mapping[str, object],
    source_manifest: SourceManifest,
    *,
    candidate_sha256: str | None = None,
    validation_sha256: str | None = None,
) -> dict[str, object]:
    """Validate a Fisher decision through the generic strict contract."""

    return reconstruction_decision.validate_decision(
        record,
        source_manifest,
        source_id=FISHER_SOURCE_ID,
        work_id=FISHER_WORK_ID,
        candidate_sha256=candidate_sha256,
        validation_sha256=validation_sha256,
    )


def decision_record(
    source_manifest: SourceManifest,
    review: ReviewView | None = None,
    *,
    disposition: str,
    rationale: str,
    decided_by: str,
    decided_at: str,
) -> dict[str, object]:
    """Build a Fisher candidate decision through the generic strict contract."""

    return reconstruction_decision.decision_record(
        source_manifest,
        review,
        source_id=FISHER_SOURCE_ID,
        work_id=FISHER_WORK_ID,
        disposition=disposition,
        rationale=rationale,
        decided_by=decided_by,
        decided_at=decided_at,
    )


def serialize_decision(record: Mapping[str, object]) -> bytes:
    """Serialize a generic strict decision deterministically with LF."""

    return reconstruction_decision.serialize_decision(record)


def load_decision(
    path: str | Path, source_manifest: SourceManifest
) -> dict[str, object]:
    """Load a Fisher decision through the generic strict contract."""

    return reconstruction_decision.load_decision(
        path,
        source_manifest,
        source_id=FISHER_SOURCE_ID,
        work_id=FISHER_WORK_ID,
    )


def catalog_decision(
    manifest_path: str | Path,
    *,
    repository_root: str | Path,
    work_id: str,
    candidate_path: str | Path | None = None,
    validation_path: str | Path | None = None,
) -> dict[str, object] | None:
    """Load Fisher evidence through the generic catalog decision reader."""

    if work_id != FISHER_WORK_ID:
        return None
    return reconstruction_decision.catalog_decision(
        manifest_path,
        repository_root=repository_root,
        source_id=FISHER_SOURCE_ID,
        work_id=FISHER_WORK_ID,
        candidate_path=candidate_path,
        validation_path=validation_path,
    )


def expected_excluded_paths() -> tuple[str, ...]:
    """Return the reviewed explicit exclusion inventory for mutation tests."""

    return _EXPECTED_EXCLUDED_PATHS


__all__ = [
    "DECISION_CONTRACT",
    "DECISION_DISPOSITIONS",
    "FISHER_SOURCE_ID",
    "FISHER_WORK_ID",
    "MEMBER_CENSUS_CONTRACT",
    "catalog_decision",
    "decision_path",
    "decision_record",
    "expected_excluded_paths",
    "load_verified_review",
    "load_decision",
    "member_census_digest",
    "retained_member_census",
    "serialize_decision",
    "validate_decision",
]
