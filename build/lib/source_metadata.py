"""Closed source-metadata worklist, decision, evidence, and sidecar engine.

This module owns the small M0 metadata seam.  The worklist records what was
selected for examination; authored decisions record evidence, requirement,
adoption, and inspection independently; generated sidecars are projections of
those decisions.  No function in this module promotes a source observation to
an existing v2, TEI, acquisition, or source-config authority automatically.
"""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import jsonschema

from ocd_kernel.lib.storage_topology import StorageTopologyError, resolve_repo_path

from build.lib.source_metadata_contract import (
    SCHEMA_PATH as SCHEMA_PATH,
    MetadataError as MetadataError,
    EvidenceError as EvidenceError,
    _reject_duplicate_keys as _reject_duplicate_keys,
    canonical_bytes as canonical_bytes,
    sha256_bytes as sha256_bytes,
    load_json as load_json,
    load_schema as load_schema,
    schema_enum as schema_enum,
    _schema_for as _schema_for,
    _normal_relative as _normal_relative,
    _pointer_tokens as _pointer_tokens,
    _pointer_value as _pointer_value,
    _json_equal as _json_equal,
    _resolve as _resolve,
    _read_packet_value as _read_packet_value,
)
from build.lib.source_metadata_evidence import BindingVerifier


WRITER_ID = "ocd-source-metadata-v1"
DEFAULT_WORKLIST = Path(
    "plans/2026-08-31-library-pipeline-redesign/artifacts/META-002/worklist.json"
)
DEFAULT_DECISIONS = Path("metadata/decisions")
LEGACY_DECISIONS = Path(
    "plans/2026-08-31-library-pipeline-redesign/artifacts/META-002/decisions"
)
OUTPUT_ROOT = Path("metadata/source-evidence")


def dimension_names(*, schema: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    active = schema if schema is not None else load_schema()
    props = active.get("$defs", {}).get("worklist_subject", {}).get("properties", {})
    dimensions = props.get("dimensions", {}) if isinstance(props, Mapping) else {}
    required = dimensions.get("required") if isinstance(dimensions, Mapping) else None
    if not isinstance(required, list) or not required:
        raise MetadataError("schema does not declare worklist dimensions")
    return tuple(str(item) for item in required)


def _schema_kind(payload: Mapping[str, Any]) -> str:
    versions = {
        "source-metadata-worklist-v1": "worklist",
        "source-metadata-decisions-v1": "decisions",
        "source-metadata-sidecar-v1": "sidecar",
        "source-metadata-index-v1": "index",
    }
    value = payload.get("schema_version")
    if value not in versions:
        raise MetadataError(f"unsupported source metadata schema_version: {value!r}")
    return versions[str(value)]


def _validate_schema(payload: Mapping[str, Any], *, kind: str | None = None) -> str:
    if not isinstance(payload, Mapping):
        raise MetadataError("source metadata document must be an object")
    active_kind = kind or _schema_kind(payload)
    from ocd_kernel.library._common import _read_inputs, read_input_bytes
    cache = _read_inputs.get()
    key = ('source-metadata-schema', active_kind, sha256_bytes(read_input_bytes(SCHEMA_PATH)),
           sha256_bytes(canonical_bytes(payload))) if cache is not None else None
    if cache is not None and key in cache:
        return active_kind
    validator = jsonschema.Draft202012Validator(_schema_for(active_kind), format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(dict(payload)), key=lambda error: list(error.path))
    if errors:
        details = "; ".join(f"{error.json_path}: {error.message}" for error in errors[:8])
        if len(errors) > 8:
            details += f"; {len(errors) - 8} more schema errors"
        raise MetadataError(f"{active_kind} schema violation: {details}")
    if cache is not None:
        cache[key] = True
    return active_kind


def _subject_key(subject: Mapping[str, Any]) -> tuple[str, str]:
    kind = subject.get("kind")
    identifier = subject.get("id")
    if not isinstance(kind, str) or not isinstance(identifier, str):
        raise MetadataError("subject requires string kind and id")
    return kind, identifier


def _subject_text(subject: Mapping[str, Any]) -> str:
    kind, identifier = _subject_key(subject)
    return f"{kind}:{identifier}"


def _safe_subject(subject: Mapping[str, Any]) -> None:
    kind, identifier = _subject_key(subject)
    kinds = schema_enum("subject_kind")
    if kind not in kinds:
        raise MetadataError(f"unsupported subject kind: {kind}")
    if not identifier or "\\" in identifier or "\x00" in identifier:
        raise MetadataError(f"invalid subject id: {identifier!r}")
    parts = PurePosixPath(identifier).parts
    if any(part in {".", ".."} for part in parts) or PurePosixPath(identifier).is_absolute():
        raise MetadataError(f"subject id escapes its namespace: {identifier!r}")
    if kind == "catalog" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
        raise MetadataError(f"catalog subject id is not a safe filename: {identifier!r}")


def _claim_identity(claim: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    scope = claim.get("scope")
    if not isinstance(scope, Mapping):
        raise MetadataError("claim scope is required")
    return (
        str(claim.get("claim_id")),
        str(scope.get("member")),
        str(scope.get("entity")),
        str(scope.get("predicate")),
        str(scope.get("event_role")),
    )


def _validate_claim_semantic_descriptor(claim: Mapping[str, Any]) -> None:
    """Bind an optional typed descriptor to the claim's existing scope.

    The JSON schema defines the supported semantic kinds, predicates, events,
    roles, and event-to-scope combinations.  This check covers the one
    relationship JSON Schema cannot express portably: the descriptor must
    describe the same predicate, event/role, and entity scope already carried
    by the claim.  It remains a structural check; it does not assess whether
    evidence supports the descriptor.
    """

    semantics = claim.get("semantics")
    if semantics is None:
        return
    if not isinstance(semantics, Mapping):
        raise MetadataError(f"claim {claim.get('claim_id')!r} semantics must be an object")
    scope = claim.get("scope")
    if not isinstance(scope, Mapping):
        raise MetadataError(f"claim {claim.get('claim_id')!r} scope is required with semantics")
    semantic_scope = semantics.get("scope")
    if semantic_scope != scope.get("entity"):
        raise MetadataError(
            f"claim {claim.get('claim_id')!r} semantics.scope {semantic_scope!r} "
            f"does not match scope.entity {scope.get('entity')!r}"
        )
    semantic_predicate = semantics.get("predicate")
    if semantic_predicate != scope.get("predicate"):
        raise MetadataError(
            f"claim {claim.get('claim_id')!r} semantics.predicate {semantic_predicate!r} "
            f"does not match scope.predicate {scope.get('predicate')!r}"
        )
    semantic_event_or_role = semantics.get("event")
    if semantic_event_or_role is None:
        semantic_event_or_role = semantics.get("role")
    if semantic_event_or_role != scope.get("event_role"):
        raise MetadataError(
            f"claim {claim.get('claim_id')!r} semantics event/role {semantic_event_or_role!r} "
            f"does not match scope.event_role {scope.get('event_role')!r}"
        )


def _validate_sidecar_semantic_descriptors(sidecar: Mapping[str, Any]) -> None:
    """Apply claim-level descriptor bindings when loading generated sidecars."""

    for payload in sidecar.get("dimensions", {}).values():
        for claim in payload.get("fields", []):
            _validate_claim_semantic_descriptor(claim)


def _worklist_items(worklist: Mapping[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    result: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in worklist.get("subjects", []):
        subject = entry["subject"]
        key = _subject_key(subject)
        for dimension in dimension_names():
            for item in entry["dimensions"][dimension].get("items", []):
                item_id = item["item_id"]
                compound = (*key, item_id)
                if compound in result:
                    raise MetadataError(f"duplicate worklist item id for subject: {_subject_text(subject)}:{item_id}")
                result[compound] = item | {"dimension": dimension, "subject": subject}
    return result


def validate_worklist(worklist: Mapping[str, Any], *, check_inputs: bool = False, root: Path | None = None) -> dict[str, Any]:
    """Validate a frozen worklist and optionally verify its packet hashes."""

    _validate_schema(worklist, kind="worklist")
    required_top = {"schema_version", "writer", "batch_id", "subjects"}
    if set(worklist) != required_top:
        raise MetadataError(f"worklist has unexpected or missing top-level keys: {sorted(set(worklist) ^ required_top)}")
    if worklist.get("schema_version") != "source-metadata-worklist-v1" or worklist.get("writer") != WRITER_ID:
        raise MetadataError("worklist has an unsupported schema_version or writer")
    dimensions_expected = set(dimension_names())
    seen_subjects: set[tuple[str, str]] = set()
    for entry in worklist["subjects"]:
        if set(entry) != {"subject", "dimensions"} or not isinstance(entry["dimensions"], Mapping):
            raise MetadataError("worklist subject must contain only subject and five dimensions")
        if set(entry["dimensions"]) != dimensions_expected:
            raise MetadataError("worklist subject must enumerate exactly the five schema dimensions")
        subject = entry["subject"]
        _safe_subject(subject)
        key = _subject_key(subject)
        if key in seen_subjects:
            raise MetadataError(f"duplicate worklist subject: {_subject_text(subject)}")
        seen_subjects.add(key)
        for dimension in dimension_names():
            seen_items: set[str] = set()
            for item in entry["dimensions"][dimension]["items"]:
                required_item = {
                    "item_id", "field", "source_packet", "input_pointer", "input_value",
                    "input_sha256", "repair_required",
                }
                if set(item) - (required_item | {"requirement"}) or not required_item.issubset(item):
                    raise MetadataError(f"worklist item has unexpected or missing keys: {_subject_text(subject)}")
                item_id = item["item_id"]
                if item_id in seen_items:
                    raise MetadataError(f"duplicate worklist item: {_subject_text(subject)}:{item_id}")
                seen_items.add(item_id)
                _normal_relative(item["source_packet"], field="source_packet")
                if not item["input_pointer"].startswith("/"):
                    raise MetadataError(f"input_pointer must be an RFC 6901 pointer: {item['input_pointer']!r}")
    if check_inputs:
        if root is None:
            raise MetadataError("root is required when checking worklist inputs")
        issues = verify_worklist_inputs(root, worklist)
        if issues:
            raise EvidenceError("worklist input verification failed: " + "; ".join(item["message"] for item in issues))
    return dict(worklist)


def _decision_entries(documents: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for document in documents:
        _validate_schema(document, kind="decisions")
        for decision in document["decisions"]:
            subject = decision["subject"]
            _safe_subject(subject)
            key = _subject_key(subject)
            if key in seen:
                raise MetadataError(f"duplicate decision subject: {_subject_text(subject)}")
            seen.add(key)
            result.append(dict(decision))
    return result


def validate_decision_documents(
    documents: Iterable[Mapping[str, Any]],
    *,
    worklist: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate decision documents, including claim-state relationships."""

    entries = _decision_entries(documents)
    work_items = _worklist_items(worklist) if worklist is not None else {}
    if worklist is not None:
        expected_subjects = {
            _subject_key(entry["subject"])
            for entry in worklist.get("subjects", [])
        }
        unexpected_subjects = [
            _subject_text(decision["subject"])
            for decision in entries
            if _subject_key(decision["subject"]) not in expected_subjects
        ]
        if unexpected_subjects:
            raise MetadataError(
                "decision document contains subjects outside the frozen worklist: "
                + ", ".join(sorted(unexpected_subjects))
            )
    for decision in entries:
        subject = decision["subject"]
        key = _subject_key(subject)
        seen_claims: set[tuple[str, str, str, str, str]] = set()
        for dimension, payload in decision.get("dimensions", {}).items():
            if dimension not in dimension_names():
                raise MetadataError(f"unknown decision dimension: {dimension}")
            for claim in payload["fields"]:
                identity = _claim_identity(claim)
                if identity in seen_claims:
                    raise MetadataError(f"duplicate scoped claim in {_subject_text(subject)}: {identity}")
                seen_claims.add(identity)
                item_key = (*key, claim["worklist_item_id"])
                item = work_items.get(item_key)
                if worklist is not None and item is None:
                    raise MetadataError(
                        f"decision claim references unknown worklist item {claim['worklist_item_id']!r} in {_subject_text(subject)}"
                    )
                _validate_claim_semantics(claim, worklist_item=item)
    return entries


def _validate_claim_semantics(claim: Mapping[str, Any], *, worklist_item: Mapping[str, Any] | None) -> None:
    _validate_claim_semantic_descriptor(claim)
    evidence = claim["evidence"]
    requirement = claim["requirement"]
    adoption = claim["adoption"]
    inspection = claim["inspection"]
    evidence_class = evidence["classification"]
    adoption_class = adoption["classification"]
    destination = adoption["destination"]
    if requirement["classification"] == "required" and destination == "source_evidence_only":
        raise MetadataError(
            f"required claim {claim['claim_id']!r} cannot use source_evidence_only"
        )
    if worklist_item is not None:
        work_requirement = worklist_item.get("requirement")
        if work_requirement is not None and requirement["classification"] != work_requirement:
            raise MetadataError(
                f"claim {claim['claim_id']!r} requirement {requirement['classification']!r} "
                f"does not match worklist {work_requirement!r}"
            )
        if bool(worklist_item.get("repair_required")) and destination == "source_evidence_only":
            raise MetadataError(
                f"claim {claim['claim_id']!r} routes a required authority repair to source_evidence_only"
            )
    if not inspection.get("owner", "").strip():
        raise MetadataError(f"claim {claim['claim_id']!r} is missing an inspection owner")
    if inspection["classification"] in {"inspected", "unavailable"} and not inspection.get("evidence", "").strip():
        raise MetadataError(
            f"claim {claim['claim_id']!r} with inspection status "
            f"{inspection['classification']!r} needs inspection evidence or reason"
        )
    if evidence_class in {"unresolved", "observed_claim"}:
        if not evidence.get("question") or not evidence.get("evidence_needed"):
            raise MetadataError(
                f"claim {claim['claim_id']!r} needs both question and evidence_needed"
            )
    elif evidence_class == "contradicted" and not (
        evidence.get("question") or evidence.get("evidence_needed")
    ):
        raise MetadataError(f"claim {claim['claim_id']!r} needs question or evidence_needed")
    if evidence_class == "supported" and not evidence.get("bindings"):
        raise MetadataError(f"supported claim {claim['claim_id']!r} requires evidence bindings")
    if evidence_class == "not_applicable" and evidence.get("bindings"):
        raise MetadataError(f"not_applicable claim {claim['claim_id']!r} cannot cite evidence bindings")
    if evidence_class == "observed_claim" and adoption_class in {
        "adopted",
        "already_correct",
        "supported_unapplied",
    }:
        raise MetadataError(f"observed-only claim {claim['claim_id']!r} cannot be promoted")
    if (
        adoption_class in {"adopted", "already_correct", "supported_unapplied"}
        and destination != "source_evidence_only"
        and evidence_class != "supported"
    ):
        raise MetadataError(
            f"authority adoption {claim['claim_id']!r} requires supported evidence"
        )
    if adoption_class in {"adopted", "already_correct"} and destination != "source_evidence_only":
        if "target" not in adoption:
            raise MetadataError(f"adopted claim {claim['claim_id']!r} requires an actual target")
        if "value" not in evidence or not _json_equal(
            adoption["target"]["expected_value"], evidence["value"]
        ):
            raise MetadataError(
                f"adopted claim {claim['claim_id']!r} target expected_value "
                "must equal evidence.value"
            )
    if destination == "source_evidence_only" and "target" in adoption:
        raise MetadataError(f"source_evidence_only claim {claim['claim_id']!r} cannot carry an authority target")
    if adoption_class == "not_selected" and not adoption.get("reason"):
        raise MetadataError(f"not_selected claim {claim['claim_id']!r} needs an evidence/usefulness reason")
    if adoption_class == "supported_unapplied" and evidence_class != "supported":
        raise MetadataError(f"supported_unapplied claim {claim['claim_id']!r} requires supported evidence")
    if adoption_class == "not_applicable" and destination != "none":
        raise MetadataError(f"not_applicable claim {claim['claim_id']!r} must use destination none")


def load_worklist(root: Path, path: Path | str | None = None) -> dict[str, Any]:
    candidate = Path(path) if path is not None else DEFAULT_WORKLIST
    if not candidate.is_absolute():
        candidate = Path(root) / candidate
    document = load_json(candidate.resolve())
    validate_worklist(document)
    return document


def _decision_files(root: Path, path: Path | str | None = None) -> list[Path]:
    candidates = [Path(path)] if path is not None else [DEFAULT_DECISIONS, LEGACY_DECISIONS]
    files: list[Path] = []
    for candidate in candidates:
        candidate = candidate if candidate.is_absolute() else Path(root) / candidate
        candidate = candidate.resolve()
        if not candidate.exists():
            continue
        if candidate.is_file():
            files.append(candidate)
        elif candidate.is_dir():
            files.extend(sorted(item for item in candidate.glob("*.json") if item.is_file()))
        else:
            raise MetadataError(f"decisions path is neither a file nor directory: {candidate}")
    return files


def load_decision_documents(root: Path, path: Path | str | None = None) -> list[dict[str, Any]]:
    return [load_json(item) for item in _decision_files(root, path)]


def decision_owner(
    root: Path, subject_kind: str, subject: str, *, sidecar: Mapping[str, Any] | None = None,
) -> str:
    """Return the exact authored file owning one projected metadata subject."""
    root = Path(root).resolve()
    key = (subject_kind, subject)
    matches: list[tuple[Path, dict[str, Any], str]] = []
    for path in _decision_files(root):
        document = load_json(path)
        _validate_schema(document, kind="decisions")
        for row in document["decisions"]:
            if _subject_key(row["subject"]) == key:
                matches.append((path, row, document["batch_id"]))
    if len(matches) != 1:
        raise MetadataError(f"metadata subject has no unique authored owner: {subject_kind}:{subject}")
    path, decision, _decision_batch_id = matches[0]
    if sidecar is not None:
        # Generated batches can combine several historical decision packets.
        index = load_json(root / 'metadata/source-evidence/index.json')
        _validate_schema(index, kind='index')
        if index['batch_id'] != sidecar.get("batch_id") or _sidecar_payload(index, decision) != sidecar:
            raise MetadataError(f"metadata projection differs from its authored decision: {subject_kind}:{subject}")
    return path.relative_to(root).as_posix()


def verify_worklist_inputs(
    root: Path,
    worklist: Mapping[str, Any],
    *,
    subject_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    packet_cache: dict[str, tuple[bytes, str, Any]] = {}
    for entry in worklist.get("subjects", []):
        if subject_keys is not None and _subject_key(entry["subject"]) not in subject_keys:
            continue
        for dimension in dimension_names():
            for item in entry["dimensions"][dimension].get("items", []):
                path_text = item["source_packet"]
                try:
                    cached = packet_cache.get(path_text)
                    if cached is None:
                        path = _resolve(root, path_text, field="source_packet")
                        data = path.read_bytes()
                        actual_hash = sha256_bytes(data)
                        try:
                            parsed = json.loads(
                                data.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
                            )
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            raise EvidenceError(f"source packet is not a JSON object: {exc}") from exc
                        packet_cache[path_text] = (data, actual_hash, parsed)
                    else:
                        data, actual_hash, parsed = cached
                    if actual_hash != item["input_sha256"]:
                        raise EvidenceError(
                            f"input hash mismatch (declared {item['input_sha256']}, actual {actual_hash})"
                        )
                    try:
                        actual_value = _pointer_value(parsed, item["input_pointer"])
                    except (KeyError, MetadataError) as exc:
                        raise EvidenceError(
                            f"cannot resolve JSON pointer {item['input_pointer']!r}: {exc}"
                        ) from exc
                    if not _json_equal(actual_value, item["input_value"]):
                        raise EvidenceError("input pointer value differs from frozen input_value")
                except (EvidenceError, OSError) as exc:
                    issues.append(
                        {
                            "subject": _subject_text(entry["subject"]),
                            "item_id": str(item["item_id"]),
                            "message": f"{path_text}#{item['input_pointer']}: {exc}",
                        }
                    )
    return issues


def _verify_target(root: Path, target: Mapping[str, Any]) -> None:
    path_text = target["path"]
    path = _resolve(root, path_text, field="adoption target")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"adoption target is unavailable: {path_text}") from exc
    actual_hash = sha256_bytes(data)
    if actual_hash != target["current_raw_sha256"]:
        raise EvidenceError(f"adoption target hash mismatch for {path_text}: {actual_hash}")
    selector = target["selector"]
    if selector.startswith("/"):
        actual = _read_packet_value(data, selector)
    else:
        try:
            actual_text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceError(f"adoption target selector requires UTF-8 text: {selector!r}") from exc
        if selector not in actual_text:
            raise EvidenceError(f"adoption target selector is absent: {selector!r}")
        actual = selector
    if not _json_equal(actual, target["expected_value"]):
        raise EvidenceError(f"adoption target value mismatch for {path_text}{selector}")


def verify_evidence(
    root: Path,
    worklist: Mapping[str, Any],
    decisions: Iterable[Mapping[str, Any]],
    *,
    verify_inputs: bool = True,
) -> list[dict[str, str]]:
    """Verify exact raw bindings and target edges without mutating anything."""

    decisions = list(decisions)
    issues: list[dict[str, str]] = []
    subject_keys = {_subject_key(decision["subject"]) for decision in decisions}
    if verify_inputs:
        # The frozen worklist covers the future batch.  A pilot verifies input
        # packets only for decided subjects; undecided subjects remain pending
        # coverage and must not block a valid bounded pilot.
        issues.extend(
            {"kind": "input", **issue}
            for issue in verify_worklist_inputs(root, worklist, subject_keys=subject_keys)
        )
    work_items = _worklist_items(worklist)
    verifier = BindingVerifier(root)
    adopted_by_scope: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = {}
    for decision in decisions:
        subject = decision["subject"]
        subject_key = _subject_key(subject)
        for dimension, payload in decision.get("dimensions", {}).items():
            for claim in payload.get("fields", []):
                claim_id = str(claim["claim_id"])
                evidence = claim["evidence"]
                adoption = claim["adoption"]
                item = work_items.get((*subject_key, claim["worklist_item_id"]))
                try:
                    bindings = evidence.get("bindings", [])
                    for binding in bindings:
                        if binding.get("role") == "primary" and any(
                            segment == "decisions" for segment in PurePosixPath(binding["path"]).parts
                        ):
                            raise EvidenceError("primary evidence cannot be authored decision data")
                        verifier.verify(binding)
                    if evidence["classification"] == "supported" and adoption["classification"] in {
                        "adopted",
                        "already_correct",
                        "supported_unapplied",
                    }:
                        if not any(binding.get("role") == "primary" for binding in bindings):
                            raise EvidenceError("supported authority claim requires a primary binding")
                    if adoption["classification"] in {"adopted", "already_correct"} and adoption["destination"] != "source_evidence_only":
                        _verify_target(root, adoption["target"])
                    if item is not None and item.get("repair_required") and adoption["destination"] == "source_evidence_only":
                        raise EvidenceError("required repair cannot use source_evidence_only")
                    if evidence["classification"] == "observed_claim" and adoption["classification"] in {
                        "adopted",
                        "already_correct",
                        "supported_unapplied",
                    }:
                        raise EvidenceError("observed-only claim cannot be promoted")
                except (EvidenceError, OSError) as exc:
                    issues.append(
                        {
                            "kind": "claim",
                            "subject": _subject_text(subject),
                            "claim_id": claim_id,
                            "message": str(exc),
                        }
                    )
                if adoption["classification"] in {"adopted", "already_correct"}:
                    identity = _claim_identity(claim)
                    adopted_by_scope.setdefault((*subject_key, *identity[1:]), []).append(claim)
    for identity, claims in adopted_by_scope.items():
        values = {canonical_bytes(claim["evidence"].get("value")) for claim in claims}
        if len(values) <= 1:
            continue
        claim_ids = {str(claim["claim_id"]) for claim in claims}
        resolved = all(
            bool(set(claim.get("competing_with", [])) & (claim_ids - {claim["claim_id"]}))
            or bool(set(claim.get("supersedes", [])) & (claim_ids - {claim["claim_id"]}))
            for claim in claims
        )
        if not resolved:
            issues.append(
                {
                    "kind": "claim",
                    "subject": f"{identity[0]}:{identity[1]}",
                    "claim_id": ",".join(sorted(claim_ids)),
                    "message": "competing adopted values have no explicit resolution",
                }
            )
    return issues


def _decision_map(decisions: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in decisions:
        key = _subject_key(decision["subject"])
        if key in result:
            raise MetadataError(f"duplicate decision subject: {_subject_text(decision['subject'])}")
        result[key] = dict(decision)
    return result


def _worklist_map(worklist: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {_subject_key(entry["subject"]): entry for entry in worklist["subjects"]}


def coverage_report(
    worklist: Mapping[str, Any],
    decisions: Iterable[Mapping[str, Any]],
    *,
    evidence_issues: Iterable[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Return independent coverage axes; it deliberately has no aggregate-complete flag."""

    work_map = _worklist_map(worklist)
    decision_map = _decision_map(decisions)
    expected_subjects = set(work_map)
    decided_subjects = set(decision_map)
    missing_subjects = sorted(expected_subjects - decided_subjects)
    unexpected_subjects = sorted(decided_subjects - expected_subjects)
    missing_dimensions: list[dict[str, str]] = []
    missing_claims: list[dict[str, str]] = []
    unexpected_claims: list[dict[str, str]] = []
    requirement_mismatches: list[dict[str, str]] = []
    supported_unapplied: list[dict[str, str]] = []
    required_unapplied_count = 0
    optional_unapplied_count = 0
    required_open: list[dict[str, str]] = []
    missing_owners: list[dict[str, str]] = []
    unexamined: list[dict[str, str]] = []
    optional_open: list[dict[str, str]] = []
    optional_not_selected_count = 0
    expected_fields = 0
    decided_fields = 0
    work_items = _worklist_items(worklist)
    for subject_key, entry in work_map.items():
        decision = decision_map.get(subject_key)
        for dimension in dimension_names():
            expected_items = entry["dimensions"][dimension].get("items", [])
            expected_fields += len(expected_items)
            if decision is None or dimension not in decision.get("dimensions", {}):
                missing_dimensions.append({"subject": _subject_text(entry["subject"]), "dimension": dimension})
                for item in expected_items:
                    row = {"subject": _subject_text(entry["subject"]), "dimension": dimension, "item_id": item["item_id"]}
                    missing_claims.append(row)
                    if item.get("requirement") == "required" or item.get("repair_required"):
                        required_open.append({**row, "reason": "required worklist item has no decision"})
                    else:
                        optional_open.append({**row, "reason": "optional worklist item has no decision"})
                continue
            payload = decision["dimensions"][dimension]
            fields = payload.get("fields", [])
            decided_fields += len(fields)
            if payload.get("status") == "inherited_unexamined":
                unexamined.append({"subject": _subject_text(entry["subject"]), "dimension": dimension, "reason": "dimension is inherited_unexamined"})
            by_item: dict[str, list[Mapping[str, Any]]] = {}
            for claim in fields:
                by_item.setdefault(str(claim["worklist_item_id"]), []).append(claim)
                item = work_items.get((*subject_key, claim["worklist_item_id"]))
                if item is None:
                    unexpected_claims.append(
                        {"subject": _subject_text(entry["subject"]), "dimension": dimension, "item_id": claim["worklist_item_id"]}
                    )
                    continue
                expected_requirement = item.get("requirement")
                actual_requirement = claim["requirement"]["classification"]
                if expected_requirement is not None and expected_requirement != actual_requirement:
                    requirement_mismatches.append(
                        {
                            "subject": _subject_text(entry["subject"]),
                            "item_id": item["item_id"],
                            "expected": expected_requirement,
                            "actual": actual_requirement,
                        }
                    )
                repair_routed_unapplied = (
                    bool(item.get("repair_required"))
                    and claim["adoption"]["destination"] == "source_evidence_only"
                )
                classified_unapplied = claim["adoption"]["classification"] == "supported_unapplied"
                if repair_routed_unapplied or classified_unapplied:
                    if item.get("requirement") == "required" or item.get("repair_required"):
                        required_unapplied_count += 1
                    else:
                        optional_unapplied_count += 1
                if item.get("repair_required") and claim["adoption"]["destination"] == "source_evidence_only":
                    row = {"subject": _subject_text(entry["subject"]), "item_id": item["item_id"], "reason": "required repair routed to source_evidence_only"}
                    supported_unapplied.append(row)
                    required_open.append(row)
                if claim["adoption"]["classification"] == "supported_unapplied":
                    row = {"subject": _subject_text(entry["subject"]), "item_id": item["item_id"], "reason": "supported claim remains unapplied"}
                    supported_unapplied.append(row)
                    if item.get("requirement") == "required" or item.get("repair_required"):
                        required_open.append(row)
                    else:
                        optional_open.append(row)
                if item.get("requirement") == "required" or item.get("repair_required"):
                    if claim["adoption"]["classification"] in {"not_selected", "not_applicable"}:
                        required_open.append(
                            {"subject": _subject_text(entry["subject"]), "item_id": item["item_id"], "reason": "required item was not adopted"}
                        )
                elif claim["adoption"]["classification"] == "not_selected":
                    # A reasoned optional rejection is a valid disposition and
                    # does not keep the optional axis open.
                    optional_not_selected_count += 1
                owner = claim["inspection"].get("owner", "")
                if not isinstance(owner, str) or not owner.strip():
                    missing_owners.append({"subject": _subject_text(entry["subject"]), "item_id": item["item_id"]})
                if claim["inspection"].get("classification") == "inherited_unexamined":
                    unexamined.append(
                        {"subject": _subject_text(entry["subject"]), "item_id": item["item_id"], "reason": "claim is inherited_unexamined"}
                    )
            for item in expected_items:
                if item["item_id"] not in by_item:
                    row = {"subject": _subject_text(entry["subject"]), "dimension": dimension, "item_id": item["item_id"]}
                    missing_claims.append(row)
                    if item.get("requirement") == "required" or item.get("repair_required"):
                        required_open.append({**row, "reason": "required worklist item has no decision"})
                    else:
                        optional_open.append({**row, "reason": "optional worklist item has no decision"})
    dimensions_expected = len(expected_subjects) * len(dimension_names())
    dimensions_decided = dimensions_expected - len(missing_dimensions)
    inherited_dimensions = sum(
        1
        for decision in decision_map.values()
        for payload in decision.get("dimensions", {}).values()
        if payload.get("status") == "inherited_unexamined"
    )
    inherited_claims = sum(1 for item in unexamined if "item_id" in item)
    edge_issues = [dict(issue) for issue in evidence_issues]
    persistence_open = bool(missing_subjects or unexpected_subjects)
    inspection_open = bool(missing_dimensions or missing_claims or missing_owners or unexamined)
    evidence_open = bool(edge_issues)
    required_subjects = {
        key
        for key, entry in work_map.items()
        if any(
            item.get("requirement") == "required" or item.get("repair_required")
            for dimension in dimension_names()
            for item in entry["dimensions"][dimension].get("items", [])
        )
    }
    for subject_key in sorted(set(missing_subjects) & required_subjects):
        required_open.append({"subject": f"{subject_key[0]}:{subject_key[1]}", "reason": "required subject has no decision"})
    required_claim_keys = {
        (_subject_text(decision["subject"]), str(claim["claim_id"]))
        for decision in decision_map.values()
        for payload in decision.get("dimensions", {}).values()
        for claim in payload.get("fields", [])
        if claim["requirement"]["classification"] == "required"
    }
    required_edge_issues = [
        issue
        for issue in edge_issues
        if (str(issue.get("subject")), str(issue.get("claim_id"))) in required_claim_keys
        or (str(issue.get("subject")), str(issue.get("claim_id"))) in {(subject, "") for subject in (_subject_text(work_map[key]["subject"]) for key in required_subjects)}
    ]
    required_open.extend(
        {"subject": str(issue.get("subject")), "item_id": str(issue.get("claim_id", "")), "reason": str(issue.get("message", "evidence verification failed"))}
        for issue in required_edge_issues
    )
    required_open_status = bool(required_open or requirement_mismatches)
    optional_open_status = bool(optional_open)
    return {
        "schema_version": "source-metadata-report-v1",
        "writer": WRITER_ID,
        "batch_id": worklist["batch_id"],
        "persistence": {
            "status": "open" if persistence_open else "covered",
            "expected_subjects": len(expected_subjects),
            "decided_subjects": len(decided_subjects & expected_subjects),
            "missing_subjects": len(missing_subjects),
            "unexpected_subjects": len(unexpected_subjects),
        },
        "inspection": {
            "status": "open" if inspection_open else "covered",
            "expected_dimensions": dimensions_expected,
            "decided_dimensions": dimensions_decided,
            "inspected_dimensions": dimensions_decided - inherited_dimensions,
            "inherited_unexamined_dimensions": inherited_dimensions,
            "inherited_unexamined_claims": inherited_claims,
            "missing_dimensions": len(missing_dimensions),
            "expected_fields": expected_fields,
            "decided_fields": decided_fields,
            "missing_claims": len(missing_claims),
            "missing_owners": len(missing_owners),
        },
        "evidence": {
            "status": "unverified" if evidence_open else "verified",
            "unverified_edges": len(edge_issues),
        },
        "required_repair": {
            "status": "open" if required_open_status else "clear",
            "supported_unapplied": required_unapplied_count,
            "requirement_mismatches": len(requirement_mismatches),
            "open_items": len(required_open),
        },
        "optional_decision": {
            "status": "open" if optional_open_status else "clear",
            "supported_unapplied": optional_unapplied_count,
            "not_selected": optional_not_selected_count,
            "open_items": len(optional_open),
        },
        "missing_subjects": [f"{kind}:{identifier}" for kind, identifier in missing_subjects],
        "unexpected_subjects": [f"{kind}:{identifier}" for kind, identifier in unexpected_subjects],
        "missing_dimensions": sorted(missing_dimensions, key=lambda item: (item["subject"], item["dimension"])),
        "missing_claims": sorted(missing_claims, key=lambda item: (item["subject"], item["dimension"], item["item_id"])),
        "unexpected_claims": sorted(unexpected_claims, key=lambda item: (item["subject"], item["dimension"], item["item_id"])),
        "requirement_mismatches": sorted(requirement_mismatches, key=lambda item: (item["subject"], item["item_id"])),
        "supported_unapplied_repairs": sorted(supported_unapplied, key=lambda item: (item["subject"], item["item_id"])),
        "missing_owners": sorted(missing_owners, key=lambda item: (item["subject"], item["item_id"])),
        "unverified_edges": sorted(edge_issues, key=lambda item: (str(item.get("subject")), str(item.get("claim_id")), str(item.get("message")))),
        "optional_decisions_open": sorted(optional_open, key=lambda item: (item["subject"], item["item_id"])),
        "inspection_unexamined": sorted(unexamined, key=lambda item: (item["subject"], item.get("dimension", ""), item.get("item_id", ""))),
        "required_open_items": sorted(required_open, key=lambda item: (item["subject"], item.get("item_id", ""), item["reason"])),
    }


def build_report(
    root: Path,
    *,
    worklist_path: Path | str | None = None,
    decisions_path: Path | str | None = None,
    verify_inputs: bool = True,
) -> dict[str, Any]:
    root = Path(root).resolve()
    worklist = load_worklist(root, worklist_path)
    documents = load_decision_documents(root, decisions_path)
    if documents:
        decisions = validate_decision_documents(documents, worklist=worklist)
    else:
        decisions = []
    issues = verify_evidence(root, worklist, decisions, verify_inputs=verify_inputs)
    return coverage_report(worklist, decisions, evidence_issues=issues)


def sidecar_relative_path(subject: Mapping[str, Any]) -> str:
    _safe_subject(subject)
    kind, identifier = _subject_key(subject)
    if kind == "catalog":
        filename = f"{identifier}.json"
        return f"metadata/source-evidence/catalog/{filename}"
    lane_hash = sha256_bytes(identifier.encode("utf-8"))
    return f"metadata/source-evidence/lanes/{lane_hash}.json"


def _sidecar_payload(worklist: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    dimensions: dict[str, Any] = {}
    for dimension in dimension_names():
        if dimension not in decision.get("dimensions", {}):
            continue
        payload = copy.deepcopy(decision["dimensions"][dimension])
        payload["fields"] = sorted(
            payload.get("fields", []),
            key=lambda claim: (
                str(claim.get("worklist_item_id")),
                str(claim.get("claim_id")),
                json.dumps(claim.get("scope", {}), sort_keys=True, ensure_ascii=False),
            ),
        )
        dimensions[dimension] = payload
    return {
        "schema_version": "source-metadata-sidecar-v1",
        "writer": WRITER_ID,
        "batch_id": worklist["batch_id"],
        "subject": copy.deepcopy(decision["subject"]),
        "dimensions": dimensions,
    }


def expected_outputs(
    root: Path,
    *,
    worklist_path: Path | str | None = None,
    decisions_path: Path | str | None = None,
) -> tuple[dict[str, bytes], dict[str, Any], dict[str, Any]]:
    root = Path(root).resolve()
    worklist = load_worklist(root, worklist_path)
    documents = load_decision_documents(root, decisions_path)
    decisions = validate_decision_documents(documents, worklist=worklist) if documents else []
    outputs: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    for decision in decisions:
        payload = _sidecar_payload(worklist, decision)
        _validate_schema(payload, kind="sidecar")
        relative = sidecar_relative_path(decision["subject"])
        encoded = canonical_bytes(payload)
        outputs[relative] = encoded
        entries.append(
            {
                "subject": copy.deepcopy(decision["subject"]),
                "path": relative,
                "sha256": sha256_bytes(encoded),
            }
        )
    issues = verify_evidence(root, worklist, decisions)
    report = coverage_report(worklist, decisions, evidence_issues=issues)
    counts = {
        "expected_subjects": report["persistence"]["expected_subjects"],
        "decided_subjects": report["persistence"]["decided_subjects"],
        "sidecars": len(entries),
        "missing_subjects": report["persistence"]["missing_subjects"],
        "missing_dimensions": report["inspection"]["missing_dimensions"],
        "missing_claims": report["inspection"]["missing_claims"],
        "unverified_edges": report["evidence"]["unverified_edges"],
        "supported_unapplied": len(report["supported_unapplied_repairs"]),
    }
    index = {
        "schema_version": "source-metadata-index-v1",
        "writer": WRITER_ID,
        "batch_id": worklist["batch_id"],
        "subjects": sorted(entries, key=lambda item: (item["subject"]["kind"], item["subject"]["id"])),
        "counts": counts,
    }
    _validate_schema(index, kind="index")
    outputs["metadata/source-evidence/index.json"] = canonical_bytes(index)
    return outputs, report, index


def _output_path(root: Path, relative: str) -> Path:
    root = Path(root).resolve()
    try:
        candidate = resolve_repo_path(root, _normal_relative(relative, field="generated output"))
    except StorageTopologyError as exc:
        raise MetadataError(f"generated output cannot be resolved: {relative}: {exc}") from exc
    expected_root = (Path(root).resolve() / OUTPUT_ROOT).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise MetadataError(f"generated output leaves repository checkout: {relative}") from exc
    try:
        candidate.relative_to(expected_root)
    except ValueError as exc:
        raise MetadataError(f"generated output escapes metadata/source-evidence: {relative}") from exc
    return candidate


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Replace one generated output atomically, preserving its old bytes on failure."""

    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise MetadataError(f"cannot atomically write generated output {path}: {exc}") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def write_outputs(
    root: Path,
    *,
    worklist_path: Path | str | None = None,
    decisions_path: Path | str | None = None,
) -> dict[str, Any]:
    outputs, report, index = expected_outputs(root, worklist_path=worklist_path, decisions_path=decisions_path)
    if report["evidence"]["unverified_edges"]:
        raise EvidenceError(
            "refusing to write metadata sidecars with unverified evidence: "
            + "; ".join(
                str(issue.get("message", "evidence verification failed"))
                for issue in report["unverified_edges"][:8]
            )
        )
    root = Path(root).resolve()
    index_relative = "metadata/source-evidence/index.json"
    ordered_outputs = [
        *sorted((relative, data) for relative, data in outputs.items() if relative != index_relative),
        (index_relative, outputs[index_relative]),
    ]
    for relative, data in ordered_outputs:
        path = _output_path(root, relative)
        _write_bytes_atomic(path, data)
    return {"report": report, "index": index, "written": sorted(outputs)}


def persist_subject(
    root: Path,
    subject_kind: str,
    subject: str,
    *,
    worklist_path: Path | str | None = None,
    decisions_path: Path | str | None = None,
    write: bool = False,
) -> dict[str, Any]:
    """Check or replace one existing subject; preserve all other index bytes.

    This deliberately narrow operation requires an unchanged batch and coverage
    contribution. Changes to catalog membership or aggregate counts still belong
    to the full writer. Evidence is freshly verified only for the selected subject;
    preserved index counts are a historical generation snapshot, not a fresh
    catalog evidence report. Run with exclusive coordinator ownership of outputs.
    The returned manifest records both output hashes and the preserved index hash.
    """
    root = Path(root).resolve()
    identity = {"kind": subject_kind, "id": subject}
    relative = sidecar_relative_path(identity)
    key = _subject_key(identity)
    worklist = load_worklist(root, worklist_path)
    selected = [row for row in worklist["subjects"] if _subject_key(row["subject"]) == key]
    if len(selected) != 1:
        raise MetadataError("subject must occur exactly once in the frozen worklist")
    scoped = {**worklist, "subjects": selected}
    documents = []
    for document in load_decision_documents(root, decisions_path):
        rows = [row for row in document["decisions"] if _subject_key(row["subject"]) == key]
        if rows:
            documents.append({**document, "decisions": rows})
    decisions = validate_decision_documents(documents, worklist=scoped)
    if len(decisions) != 1:
        raise MetadataError("subject must have exactly one decision")
    issues = verify_evidence(root, scoped, decisions)
    if issues:
        raise EvidenceError("subject evidence verification failed: " + "; ".join(row["message"] for row in issues))
    report = coverage_report(scoped, decisions, evidence_issues=issues)
    payload = _sidecar_payload(scoped, decisions[0])
    _validate_schema(payload, kind="sidecar")
    after = canonical_bytes(payload)

    index_relative = "metadata/source-evidence/index.json"
    index_path = _output_path(root, index_relative)
    path = _output_path(root, relative)
    if path != root / relative or index_path != root / index_relative:
        raise MetadataError("subject replacement refuses redirected metadata outputs")
    if path != root / relative or index_path != root / index_relative:
        raise MetadataError("subject replacement refuses redirected metadata outputs")
    index_before = index_path.read_bytes()
    before = path.read_bytes()
    old = lookup_sidecar(root, subject_kind, subject)
    index = load_json(index_path)
    if canonical_bytes(index) != index_before:
        raise MetadataError("subject replacement requires a canonical index")
    if index["batch_id"] != worklist["batch_id"] or old["batch_id"] != worklist["batch_id"]:
        raise MetadataError("subject replacement cannot change the index batch")
    keys = [_subject_key(row["subject"]) for row in index["subjects"]]
    if len(keys) != len(set(keys)):
        raise MetadataError("duplicate subject in index")
    old_report = coverage_report(scoped, [old])
    for axis, field in (
        ("inspection", "missing_dimensions"),
        ("inspection", "missing_claims"),
    ):
        if old_report[axis][field] != report[axis][field]:
            raise MetadataError("subject replacement would change aggregate coverage counts")
    if len(old_report["supported_unapplied_repairs"]) != len(report["supported_unapplied_repairs"]):
        raise MetadataError("subject replacement would change aggregate repair counts")
    if index["counts"]["unverified_edges"] != 0:
        raise MetadataError("subject replacement requires a previously verified index snapshot")
    entry = next(row for row in index["subjects"] if _subject_key(row["subject"]) == key)
    entry["sha256"] = sha256_bytes(after)
    index_after = canonical_bytes(index)
    manifest = {
        "operation": "replace-existing-source-metadata-subject-v1",
        "writer": WRITER_ID,
        "subject": identity,
        "evidence_scope": "selected subject only; preserved catalog counts are historical",
        "outputs": [
            {"path": relative, "before_sha256": sha256_bytes(before), "after_sha256": sha256_bytes(after)},
            {"path": index_relative, "before_sha256": sha256_bytes(index_before), "after_sha256": sha256_bytes(index_after)},
        ],
        "preserved_entries_sha256": sha256_bytes(canonical_bytes([
            row for row in index["subjects"] if _subject_key(row["subject"]) != key
        ])),
        "preserved_subject_count": len(index["subjects"]) - 1,
    }
    current = before == after and index_before == index_after
    if write and not current:
        if path.read_bytes() != before or index_path.read_bytes() != index_before:
            raise MetadataError("metadata outputs changed during subject preflight")
        _write_bytes_atomic(path, after)
        try:
            _write_bytes_atomic(index_path, index_after)
        except (MetadataError, OSError):
            _write_bytes_atomic(path, before)
            raise
    return {"report": report, "manifest": manifest, "current": current or write, "written": write and not current}


def check_outputs(
    root: Path,
    *,
    worklist_path: Path | str | None = None,
    decisions_path: Path | str | None = None,
) -> list[dict[str, str]]:
    issues, _report = check_outputs_detailed(root, worklist_path=worklist_path, decisions_path=decisions_path)
    return issues


def check_outputs_detailed(
    root: Path, *, worklist_path: Path | str | None = None,
    decisions_path: Path | str | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Check outputs and return the report from the same verification pass."""
    outputs, report, _index = expected_outputs(root, worklist_path=worklist_path, decisions_path=decisions_path)
    root = Path(root).resolve()
    issues: list[dict[str, str]] = []
    for relative, expected in sorted(outputs.items()):
        path = _output_path(root, relative)
        if not path.is_file():
            issues.append({"path": relative, "message": "generated output is missing"})
            continue
        actual = path.read_bytes()
        if actual != expected:
            issues.append({"path": relative, "message": "generated output is stale"})
    managed_root = (root / OUTPUT_ROOT).resolve()
    for directory_name in ("catalog", "lanes"):
        directory = managed_root / directory_name
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            relative = path.relative_to(root).as_posix()
            if relative not in outputs:
                issues.append({"path": relative, "message": "unexpected managed sidecar"})
    return issues, report


def lookup_sidecar(root: Path, subject_kind: str, subject: str) -> dict[str, Any]:
    payload = {"kind": subject_kind, "id": subject}
    root = Path(root).resolve()
    relative = sidecar_relative_path(payload)
    path = _output_path(root, relative)
    index_path = _output_path(root, "metadata/source-evidence/index.json")
    if not index_path.is_file():
        raise MetadataError("metadata source-evidence index is missing")
    index = load_json(index_path)
    _validate_schema(index, kind="index")
    matches = [entry for entry in index["subjects"] if _subject_key(entry["subject"]) == _subject_key(payload)]
    if len(matches) != 1:
        raise MetadataError(f"index has no unique entry for {_subject_text(payload)}")
    entry = matches[0]
    if entry["path"] != relative:
        raise MetadataError(f"index path mismatch for {_subject_text(payload)}")
    if not path.is_file():
        raise MetadataError(f"sidecar is missing for {_subject_text(payload)}")
    actual_hash = sha256_bytes(path.read_bytes())
    if actual_hash != entry["sha256"]:
        raise MetadataError(f"sidecar hash differs from index for {_subject_text(payload)}")
    sidecar = load_json(path)
    _validate_schema(sidecar, kind="sidecar")
    if _subject_key(sidecar["subject"]) != _subject_key(payload):
        raise MetadataError(f"sidecar subject mismatch at {path}")
    _validate_sidecar_semantic_descriptors(sidecar)
    return sidecar


def _lookup_adopted_claim(
    root: Path, subject_kind: str, subject: str, *, target_path: str,
    selector: str, semantic_kind: str,
) -> dict[str, Any] | None:
    """Own the shared adoption, freshness, exact-target and uniqueness checks."""
    label = semantic_kind.replace('_', ' ')
    root = Path(root).resolve()
    sidecar = lookup_sidecar(root, subject_kind, subject)
    matches = []
    for payload in sidecar['dimensions'].values():
        for claim in payload.get('fields', []):
            if claim.get('semantics', {}).get('kind') != semantic_kind:
                continue
            adoption = claim['adoption']
            if adoption['destination'] != 'v2' or adoption['classification'] not in ('adopted', 'already_correct'):
                continue
            target = adoption.get('target', {})
            if target.get('path') != target_path or target.get('selector') != selector:
                continue
            evidence = claim['evidence']
            if evidence['classification'] != 'supported' or not any(b.get('role') == 'primary' for b in evidence.get('bindings', [])):
                raise EvidenceError(f'adopted {label} requires supported primary evidence')
            if not _json_equal(target.get('expected_value'), evidence.get('value')):
                raise EvidenceError(f'{label} adoption value differs from evidence')
            for binding in evidence['bindings']:
                if binding.get('role') == 'primary' and 'decisions' in PurePosixPath(binding['path']).parts:
                    raise EvidenceError('primary evidence cannot be authored decision data')
                BindingVerifier(root).verify(binding)
            _verify_target(root, target)
            matches.append(claim)
    if len(matches) > 1:
        raise MetadataError(f'multiple adopted {label.replace(" ", "-")} claims for target')
    return copy.deepcopy(matches[0]) if matches else None


def lookup_adopted_original_language(
    root: Path, subject_kind: str, subject: str, *, target_path: str, selector: str,
) -> dict[str, Any] | None:
    """Resolve only a currently evidenced claim adopted into the named v2 target.

    Subject-to-library identity and target selection belong to the caller. An
    evidence-only or unapplied claim never becomes adopted through this lookup.
    """
    return _lookup_adopted_claim(
        root, subject_kind, subject, target_path=target_path,
        selector=selector, semantic_kind='original_language',
    )


def lookup_work_original_language(root: Path, work_path: Path) -> dict[str, Any] | None:
    """Follow an explicit work-to-metadata subject binding, never a name guess."""
    from ocd_kernel.library.identities import load_work
    root = Path(root).resolve()
    work_path = Path(work_path).resolve()
    try:
        relative = work_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise MetadataError('original-language work target is outside repository') from exc
    work = load_work(work_path)
    descriptor = work.get('original_language')
    if descriptor is None:
        return None
    subject = descriptor['source_metadata_subject']
    claim = lookup_adopted_original_language(root, subject['kind'], subject['id'], target_path=relative, selector='/original_language/value')
    if claim is None:
        raise MetadataError('work original language has no matching adopted evidence')
    if claim['evidence']['value'] != descriptor['value']:
        raise MetadataError('work original language differs from adopted evidence')
    return claim


def lookup_adopted_work_kind(
    root: Path, subject_kind: str, subject: str, *, target_path: str, selector: str,
) -> dict[str, Any] | None:
    """Resolve only a currently evidenced claim adopted into the named v2 target.

    Subject-to-library identity and target selection belong to the caller. An
    evidence-only or unapplied claim never becomes adopted through this lookup.
    """
    claim = _lookup_adopted_claim(
        root, subject_kind, subject, target_path=target_path,
        selector=selector, semantic_kind='work_kind',
    )
    from build.lib._generated_enums import STRUCTURED_TEXT__DATA__WORK_KIND
    if claim and claim['evidence']['value'] not in STRUCTURED_TEXT__DATA__WORK_KIND:
        raise MetadataError('unsupported adopted work kind')
    return claim


def lookup_work_kind(root: Path, work_path: Path) -> dict[str, Any] | None:
    """Follow an explicit work-to-metadata subject binding, never a name guess."""
    from ocd_kernel.library.identities import load_work
    root = Path(root).resolve()
    work_path = Path(work_path).resolve()
    try:
        relative = work_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise MetadataError('work-kind work target is outside repository') from exc
    work = load_work(work_path)
    descriptor = work.get('work_kind')
    if descriptor is None:
        return None
    subject = descriptor['source_metadata_subject']
    claim = lookup_adopted_work_kind(root, subject['kind'], subject['id'], target_path=relative, selector='/work_kind/value')
    if claim is None:
        raise MetadataError('work work kind has no matching adopted evidence')
    if claim['evidence']['value'] != descriptor['value']:
        raise MetadataError('work work kind differs from adopted evidence')
    return claim


__all__ = [
    "DEFAULT_DECISIONS",
    "DEFAULT_WORKLIST",
    "LEGACY_DECISIONS",
    "EvidenceError",
    "MetadataError",
    "WRITER_ID",
    "build_report",
    "canonical_bytes",
    "check_outputs",
    "check_outputs_detailed",
    "coverage_report",
    "dimension_names",
    "decision_owner",
    "expected_outputs",
    "load_decision_documents",
    "load_json",
    "load_schema",
    "load_worklist",
    "lookup_sidecar",
    "lookup_adopted_original_language",
    "lookup_work_original_language",
    "lookup_work_kind",
    "lookup_adopted_work_kind",
    "schema_enum",
    "sha256_bytes",
    "sidecar_relative_path",
    "validate_decision_documents",
    "validate_worklist",
    "verify_evidence",
    "verify_worklist_inputs",
    "write_outputs",
]
