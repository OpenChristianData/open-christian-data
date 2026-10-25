"""Read-only claim-level recheck of retained source metadata evidence.

The metadata review writer deliberately removes binding bodies from individual
claims and stores them once in ``review.json['evidence']``.  This module reads
that review view, resolves the historical bindings against a supplied checkout,
and reports which claims are unchanged, changed, missing, or unverifiable.

It does not rewrite a binding, refresh a historical value, or make a semantic
approval decision.  A receipt is optional.  When present, its authority
comparison snapshots are checked as additional claim evidence and receipt
artifact drift is reported separately from claim status.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from build.lib import source_metadata as sm
from build.lib.source_metadata_evidence import inspect_binding as _binding_check
from build.lib import source_metadata_review as review


IMPACT_SCHEMA_VERSION = "source-metadata-impact-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUS_ORDER = ("unchanged", "changed", "missing", "unverifiable")
_VIEW_KEYS = {"notice", "structure", "claims", "evidence", "alerts", "authority_comparisons"}
_SCOPE_KEYS = {"member", "entity", "predicate", "event_role"}
_EVIDENCE_KEYS = {"classification", "value", "binding_references", "question", "evidence_needed"}
_ADOPTION_KEYS = {"classification", "destination", "reason", "target"}
_TARGET_KEYS = {"path", "selector", "expected_value", "current_raw_sha256", "value_check"}
_AUTHORITY_SNAPSHOT_KEYS = {
    "path",
    "selector",
    "path_available",
    "selector_available",
    "availability",
    "value",
    "raw_sha256",
    "bytes",
    "reason",
}
_UNAVAILABLE_REASONS = {"path_unavailable", "json_unavailable", "selector_unavailable"}
_AUTHORITY_VIEW_KEYS = {
    "subject",
    "field",
    "scope",
    "authority",
    "evidence_references",
    "review",
    "mapped_value",
    "mapped_claim",
    "comparison",
    "alerts",
}


def _error(message: str) -> sm.MetadataError:
    return sm.MetadataError(message)


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _subject(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "id"}:
        raise _error(f"{label} must contain exactly kind and id")
    try:
        sm._safe_subject(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise _error(f"invalid {label}") from exc
    return {"kind": value["kind"], "id": value["id"]}


def _subject_key(value: Mapping[str, Any], *, label: str = "subject") -> tuple[str, str]:
    normalized = _subject(value, label=label)
    return normalized["kind"], normalized["id"]


def _scope(value: Any, *, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _SCOPE_KEYS:
        raise _error(f"{label} must contain exactly member, entity, predicate, and event_role")
    if any(not isinstance(item, str) or not item for item in value.values()):
        raise _error(f"{label} values must be nonempty strings")
    return {key: value[key] for key in sorted(_SCOPE_KEYS)}


def _relative_path(value: Any, *, label: str) -> str:
    try:
        return sm._normal_relative(value, field=label)
    except (TypeError, ValueError, sm.MetadataError) as exc:
        raise _error(f"{label} must be a normalized repository-relative path") from exc


def _digest(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise _error(f"{label} must be a lowercase 64-character SHA-256")
    return value


def _binding_reference(binding: Mapping[str, Any]) -> str:
    # Keep identity exactly aligned with the review producer.
    return review._binding_reference(binding)


def _validate_binding(value: Any, *, reference: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"evidence binding {reference} must be an object")
    try:
        validator = sm.jsonschema.Draft202012Validator(sm._schema_for("binding"))
        errors = sorted(validator.iter_errors(dict(value)), key=lambda item: list(item.path))
    except (TypeError, ValueError) as exc:
        raise _error(f"evidence binding {reference} cannot be validated") from exc
    if errors:
        raise _error(f"evidence binding {reference} is invalid: {errors[0].message}")
    normalized = _copy(dict(value))
    actual_reference = _binding_reference(normalized)
    if actual_reference != reference:
        raise _error(f"evidence binding reference mismatch: {reference}")
    return normalized


def _validate_target(value: Any, *, claim_label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(f"{claim_label} adoption target must be an object")
    try:
        validator = sm.jsonschema.Draft202012Validator(sm._schema_for("target"))
        errors = sorted(validator.iter_errors(dict(value)), key=lambda item: list(item.path))
    except (TypeError, ValueError) as exc:
        raise _error(f"{claim_label} adoption target cannot be validated") from exc
    if errors:
        raise _error(f"{claim_label} adoption target is invalid: {errors[0].message}")
    if set(value) != _TARGET_KEYS:
        raise _error(f"{claim_label} adoption target has unexpected keys")
    return _copy(dict(value))


def _validate_claim_row(row: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(row, Mapping) or set(row) != {"key", "claim"}:
        raise _error(f"review claim row {index} must contain exactly key and claim")
    raw_key = row["key"]
    if not isinstance(raw_key, (list, tuple)) or len(raw_key) != 8:
        raise _error(f"review claim row {index} key must contain eight values")
    if any(not isinstance(item, str) or not item for item in raw_key):
        raise _error(f"review claim row {index} key values must be nonempty strings")
    key = tuple(raw_key)
    subject_value = {"kind": key[0], "id": key[1]}
    subject_key = _subject_key(subject_value, label=f"review claim row {index} subject")
    dimensions = sm.dimension_names()
    if key[2] not in dimensions:
        raise _error(f"review claim row {index} has an unknown dimension")
    claim = row["claim"]
    if not isinstance(claim, Mapping):
        raise _error(f"review claim row {index} claim must be an object")
    if not {"worklist_item_id", "claim_id", "scope", "evidence", "adoption"}.issubset(claim):
        raise _error(f"review claim row {index} is missing claim identity or evidence")
    if set(claim) - set(sm.load_schema()["$defs"]["claim"]["properties"]):
        raise _error(f"review claim row {index} has unsupported claim keys")
    claim_id = claim["claim_id"]
    item_id = claim["worklist_item_id"]
    if not isinstance(claim_id, str) or not claim_id:
        raise _error(f"review claim row {index} claim_id must be a nonempty string")
    if not isinstance(item_id, str) or not item_id:
        raise _error(f"review claim row {index} worklist_item_id must be a nonempty string")
    scope = _scope(claim["scope"], label=f"review claim row {index} scope")
    if (key[3], key[4], key[5], key[6], key[7]) != (
        claim_id,
        scope["member"],
        scope["entity"],
        scope["predicate"],
        scope["event_role"],
    ):
        raise _error(f"review claim row {index} key does not match claim identity")
    evidence = claim["evidence"]
    if not isinstance(evidence, Mapping):
        raise _error(f"review claim row {index} evidence must be an object")
    if set(evidence) - _EVIDENCE_KEYS or "classification" not in evidence:
        raise _error(f"review claim row {index} evidence has unsupported or missing keys")
    if not isinstance(evidence["classification"], str) or not evidence["classification"]:
        raise _error(f"review claim row {index} evidence classification must be a string")
    references = evidence.get("binding_references", [])
    if not isinstance(references, list):
        raise _error(f"review claim row {index} binding_references must be an array")
    if any(not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None for item in references):
        raise _error(f"review claim row {index} binding_references must be SHA-256 IDs")
    if len(set(references)) != len(references):
        raise _error(f"review claim row {index} binding_references must be unique")
    adoption = claim["adoption"]
    if not isinstance(adoption, Mapping) or not {"classification", "destination"}.issubset(adoption):
        raise _error(f"review claim row {index} adoption is malformed")
    if set(adoption) - _ADOPTION_KEYS:
        raise _error(f"review claim row {index} adoption has unsupported keys")
    target = None
    if "target" in adoption:
        target = _validate_target(adoption["target"], claim_label=f"review claim row {index}")
    normalized_claim = _copy(dict(claim))
    normalized_claim["scope"] = scope
    normalized_claim["evidence"] = _copy(dict(evidence))
    normalized_claim["evidence"]["binding_references"] = list(references)
    normalized_claim["adoption"] = _copy(dict(adoption))
    if target is not None:
        normalized_claim["adoption"]["target"] = target
    return {
        "key": key,
        "subject": {"kind": subject_key[0], "id": subject_key[1]},
        "dimension": key[2],
        "claim": normalized_claim,
    }


def _validate_review_view(value: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, Mapping):
        raise _error("review view must be a JSON object")
    required = {"notice", "structure", "claims", "evidence", "alerts"}
    if not required.issubset(value) or set(value) - _VIEW_KEYS:
        raise _error("review view has unsupported or missing top-level keys")
    if not isinstance(value["notice"], str):
        raise _error("review view notice must be a string")
    if not isinstance(value["structure"], list) or not isinstance(value["alerts"], list):
        raise _error("review view structure and alerts must be arrays")
    raw_claims = value["claims"]
    if not isinstance(raw_claims, list):
        raise _error("review view claims must be an array")
    evidence_map = value["evidence"]
    if not isinstance(evidence_map, Mapping):
        raise _error("review view evidence must be an object")
    bindings: dict[str, dict[str, Any]] = {}
    for reference, binding in evidence_map.items():
        if not isinstance(reference, str) or _SHA256_RE.fullmatch(reference) is None:
            raise _error("review view evidence keys must be SHA-256 IDs")
        bindings[reference] = _validate_binding(binding, reference=reference)
    claims: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, ...]] = set()
    referenced: set[str] = set()
    for index, row in enumerate(raw_claims):
        normalized = _validate_claim_row(row, index=index)
        key = normalized["key"]
        if key in seen_keys:
            raise _error(f"duplicate review claim key: {key}")
        seen_keys.add(key)
        references = normalized["claim"]["evidence"].get("binding_references", [])
        for reference in references:
            if reference not in bindings:
                raise _error(f"review claim references missing evidence binding: {reference}")
            referenced.add(reference)
        restored = _copy(normalized["claim"])
        restored["evidence"].pop("binding_references", None)
        restored["evidence"]["bindings"] = [bindings[ref] for ref in references]
        validator = sm.jsonschema.Draft202012Validator(sm._schema_for("claim"))
        error = next(validator.iter_errors(restored), None)
        if error is not None:
            raise _error(f"review claim {index} is invalid: {error.message}")
        sm._validate_claim_semantics(restored, worklist_item=None)
        claims.append(normalized)
    orphaned = set(bindings) - referenced
    if orphaned:
        raise _error("review view contains unreferenced evidence binding")
    authority_rows = _validate_view_authority_rows(value.get("authority_comparisons", []))
    return claims, bindings, authority_rows


def _validate_view_authority_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise _error("review authority_comparisons must be an array")
    result: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for index, row in enumerate(value):
        if not isinstance(row, Mapping):
            raise _error(f"review authority comparison {index} must be an object")
        required = {"subject", "field", "scope", "authority", "evidence_references"}
        if not required.issubset(row) or set(row) - _AUTHORITY_VIEW_KEYS:
            raise _error(f"review authority comparison {index} has unsupported or missing keys")
        subject = _subject(row["subject"], label=f"review authority comparison {index} subject")
        field = row["field"]
        if not isinstance(field, str) or not field:
            raise _error(f"review authority comparison {index} field must be nonempty")
        scope = _scope(row["scope"], label=f"review authority comparison {index} scope")
        refs = row["evidence_references"]
        if not isinstance(refs, list) or not refs:
            raise _error(f"review authority comparison {index} requires evidence references")
        if any(not isinstance(ref, str) or _SHA256_RE.fullmatch(ref) is None for ref in refs):
            raise _error(f"review authority comparison {index} evidence references are invalid")
        if len(set(refs)) != len(refs):
            raise _error(f"review authority comparison {index} evidence references are duplicated")
        authority = row["authority"]
        if not isinstance(authority, Mapping):
            raise _error(f"review authority comparison {index} authority must be an object")
        if set(authority) != _AUTHORITY_SNAPSHOT_KEYS:
            raise _error(f"review authority comparison {index} authority snapshot is incomplete")
        path = _relative_path(authority["path"], label=f"review authority comparison {index} path")
        selector = authority["selector"]
        if not isinstance(selector, str) or not selector:
            raise _error(f"review authority comparison {index} selector must be nonempty")
        if type(authority["path_available"]) is not bool or type(authority["selector_available"]) is not bool:
            raise _error(f"review authority comparison {index} availability flags must be boolean")
        if authority["availability"] not in {"available", "unavailable"}:
            raise _error(f"review authority comparison {index} availability is invalid")
        raw_sha = authority["raw_sha256"]
        if raw_sha is not None:
            _digest(raw_sha, label=f"review authority comparison {index} raw_sha256")
        byte_count = authority["bytes"]
        if byte_count is not None and (type(byte_count) is not int or byte_count < 0):
            raise _error(f"review authority comparison {index} bytes must be a nonnegative integer")
        reason = authority["reason"]
        if reason is not None and reason not in _UNAVAILABLE_REASONS:
            raise _error(f"review authority comparison {index} reason is invalid")
        if not authority["path_available"] and (
            raw_sha is not None or byte_count is not None or authority["selector_available"]
        ):
            raise _error(f"review authority comparison {index} unavailable path snapshot is inconsistent")
        if authority["path_available"] and (raw_sha is None or byte_count is None):
            raise _error(f"review authority comparison {index} available path lacks identity")
        if authority["selector_available"] and (
            not authority["path_available"] or authority["availability"] != "available" or reason is not None
        ):
            raise _error(f"review authority comparison {index} available selector is inconsistent")
        if not authority["selector_available"] and authority["availability"] != "unavailable":
            raise _error(f"review authority comparison {index} unavailable selector is inconsistent")
        if authority["availability"] == "available" and not authority["selector_available"]:
            raise _error(f"review authority comparison {index} available snapshot is inconsistent")
        if authority["availability"] == "unavailable" and reason is None:
            raise _error(f"review authority comparison {index} unavailable snapshot lacks a reason")
        normalized_authority = _copy(dict(authority))
        normalized_authority["path"] = path
        identity = sm.canonical_bytes({
            "subject": subject,
            "field": field,
            "scope": scope,
            "authority": normalized_authority,
            "evidence_references": refs,
        })
        if identity in seen:
            raise _error(f"duplicate review authority comparison {index}")
        seen.add(identity)
        result.append({
            "subject": subject,
            "field": field,
            "scope": scope,
            "authority": normalized_authority,
            "evidence_references": list(refs),
            "mapped_claim": _copy(row.get("mapped_claim")),
        })
    return result


def _validate_receipt_authority_rows(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = receipt.get("authority_comparisons", [])
    if not isinstance(value, list):
        raise _error("receipt authority_comparisons must be an array")
    result: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        try:
            normalized = review._validate_authority_comparison_receipt_row(row, index=index)
        except (KeyError, TypeError, ValueError, sm.MetadataError) as exc:
            raise _error(f"receipt authority comparison {index} is malformed") from exc
        result.append(_copy(normalized))
    return result


def _filter_paths(root: Path, paths: Iterable[str | Path] | None) -> tuple[bool, set[str], set[str]]:
    if paths is None:
        return False, set(), set()
    values = list(paths)
    lexical: set[str] = set()
    resolved: set[str] = set()
    for value in values:
        if isinstance(value, Path):
            raw = str(value)
        elif isinstance(value, str):
            raw = value
        else:
            raise _error("paths must contain strings or filesystem paths")
        if not raw:
            raise _error("path filter cannot be empty")
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                resolved.add(str(candidate.resolve()))
            except (OSError, RuntimeError) as exc:
                raise _error(f"path filter cannot be resolved: {raw}") from exc
        else:
            lexical.add(_relative_path(raw, label="path filter"))
    return True, lexical, resolved


def _selected(path_text: str, resolved_path: Path, *, lexical: set[str], resolved: set[str]) -> bool:
    return path_text in lexical or str(resolved_path) in resolved


def _target_check(root: Path, target: Mapping[str, Any]) -> dict[str, Any]:
    path_text = target["path"]
    try:
        path = sm._resolve(root, path_text, field="adoption target")
    except (sm.MetadataError, sm.EvidenceError) as exc:
        return {
            "kind": "adoption_target",
            "path": path_text,
            "status": "unverifiable",
            "historical": _copy(target),
            "current": None,
            "changes": [],
            "reason": str(exc),
        }
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {
            "kind": "adoption_target",
            "path": path_text,
            "status": "missing",
            "historical": _copy(target),
            "current": None,
            "changes": ["path_missing"],
            "reason": "adoption target path is missing",
        }
    except OSError as exc:
        return {
            "kind": "adoption_target",
            "path": path_text,
            "status": "unverifiable",
            "historical": _copy(target),
            "current": {"path": str(path)},
            "changes": [],
            "reason": f"adoption target path cannot be read: {exc}",
        }
    current_sha = sm.sha256_bytes(raw)
    current: dict[str, Any] = {"path": path_text, "resolved_path": str(path), "sha256": current_sha, "bytes": len(raw)}
    changes: list[str] = []
    if current_sha != target["current_raw_sha256"]:
        changes.append("file_hash")
    selector = target["selector"]
    try:
        if selector.startswith("/"):
            actual = sm._read_packet_value(raw, selector)
        else:
            text = raw.decode("utf-8")
            if selector not in text:
                raise KeyError(selector)
            actual = selector
    except (UnicodeDecodeError, KeyError, IndexError, TypeError, ValueError, sm.MetadataError) as exc:
        return {
            "kind": "adoption_target",
            "path": path_text,
            "status": "unverifiable",
            "historical": _copy(target),
            "current": current,
            "changes": changes,
            "reason": f"current target selector cannot be verified: {exc}",
        }
    current["selector_value"] = _copy(actual)
    if not sm._json_equal(actual, target["expected_value"]):
        changes.append("selector_value")
    return {
        "kind": "adoption_target",
        "path": path_text,
        "status": "changed" if changes else "unchanged",
        "historical": _copy(target),
        "current": current,
        "changes": changes,
        "selector_status": "unchanged" if sm._json_equal(actual, target["expected_value"]) else "changed",
    }


def _authority_claim_match(
    row: Mapping[str, Any], claims: Sequence[dict[str, Any]], bindings: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    subject_key = _subject_key(row["subject"], label="authority comparison subject")
    scope = row["scope"]
    refs = set(row["evidence_references"])
    candidates: list[dict[str, Any]] = []
    mapped_claim = row.get("mapped_claim")
    for candidate in claims:
        if _subject_key(candidate["subject"]) != subject_key or candidate["claim"]["scope"] != scope:
            continue
        candidate_refs = set(candidate["claim"]["evidence"].get("binding_references", []))
        if not refs <= candidate_refs:
            continue
        if isinstance(mapped_claim, Mapping):
            if mapped_claim.get("claim_id") != candidate["claim"]["claim_id"]:
                continue
            if mapped_claim.get("worklist_item_id") != candidate["claim"]["worklist_item_id"]:
                continue
        candidates.append(candidate)
    if len(candidates) != 1:
        raise _error("authority comparison does not map to exactly one review claim")
    for reference in refs:
        if reference not in bindings:
            raise _error(f"authority comparison references missing evidence binding: {reference}")
    return candidates[0]


def _authority_check(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    authority = row["authority"]
    path_text = authority["path"]
    selector = authority["selector"]
    try:
        path = sm._resolve(root, path_text, field="authority path")
    except sm.MetadataError as exc:
        return {
            "kind": "authority_comparison",
            "path": path_text,
            "selector": selector,
            "status": "unverifiable",
            "historical": _copy(authority),
            "current": None,
            "changes": [],
            "reason": str(exc),
        }
    current = review._read_authority(path, path_text=path_text, selector=selector)
    if not current["path_available"]:
        return {
            "kind": "authority_comparison",
            "path": path_text,
            "selector": selector,
            "status": "missing",
            "historical": _copy(authority),
            "current": _copy(current),
            "changes": ["path_missing"],
            "reason": "authority path is missing",
        }
    if not current["selector_available"]:
        return {
            "kind": "authority_comparison",
            "path": path_text,
            "selector": selector,
            "status": "unverifiable",
            "historical": _copy(authority),
            "current": _copy(current),
            "changes": [],
            "reason": str(current.get("reason") or "authority selector is unavailable"),
        }
    changes: list[str] = []
    historical_sha = authority.get("raw_sha256")
    historical_bytes = authority.get("bytes")
    if historical_sha != current.get("raw_sha256"):
        changes.append("file_hash")
    if historical_bytes != current.get("bytes"):
        changes.append("file_bytes")
    if "resolved_path" in authority and authority["resolved_path"] != current.get("resolved_path"):
        changes.append("resolved_path")
    if not sm._json_equal(authority.get("value"), current.get("value")):
        changes.append("selector_value")
    return {
        "kind": "authority_comparison",
        "path": path_text,
        "selector": selector,
        "status": "changed" if changes else "unchanged",
        "historical": _copy(authority),
        "current": _copy(current),
        "changes": changes,
        "selector_status": "unchanged" if "selector_value" not in changes else "changed",
    }


def _claim_identifier(record: Mapping[str, Any]) -> dict[str, Any]:
    claim = record["claim"]
    return {
        "subject": _copy(record["subject"]),
        "dimension": record["dimension"],
        "claim_id": claim["claim_id"],
        "worklist_item_id": claim["worklist_item_id"],
        "scope": _copy(claim["scope"]),
    }


def _merge_status(checks: Sequence[Mapping[str, Any]]) -> str:
    if not checks:
        return "unverifiable"
    statuses = {check["status"] for check in checks}
    for status in ("missing", "unverifiable", "changed", "unchanged"):
        if status in statuses:
            return status
    return "unverifiable"


def _authority_rows(
    view_rows: Sequence[Mapping[str, Any]], receipt_rows: Sequence[Mapping[str, Any]],
    *, receipt_present: bool = False,
) -> list[dict[str, Any]]:
    """Join physical snapshots to the same immutable public view and claim map."""

    def identity(row: Mapping[str, Any]) -> bytes:
        return sm.canonical_bytes({
            "subject": row["subject"], "field": row["field"], "scope": row["scope"],
            "path": row["authority"]["path"], "selector": row["authority"]["selector"],
            "evidence_references": row["evidence_references"],
        })

    views = {identity(row): row for row in view_rows}
    receipts = {identity(row): row for row in receipt_rows}
    if len(views) != len(view_rows) or len(receipts) != len(receipt_rows):
        raise _error("duplicate authority comparison identity")
    if not receipt_present:
        return [_copy(dict(row)) for row in view_rows]
    if views.keys() != receipts.keys():
        raise _error("receipt authority comparisons do not match retained review")
    result = []
    for key, view_row in views.items():
        receipt_row = receipts[key]
        if not sm._json_equal(review._public_authority_snapshot(receipt_row["authority"]), view_row["authority"]):
            raise _error("receipt authority snapshot differs from retained review")
        combined = _copy(dict(receipt_row))
        combined["mapped_claim"] = _copy(view_row.get("mapped_claim"))
        result.append(combined)
    return result


def recheck_claim_evidence(
    root: Path | str,
    review_view: Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
    *,
    paths: Iterable[str | Path] | None = None,
) -> dict[str, Any]:
    """Recheck the exact evidence referenced by a generated review view.

    ``paths`` selects logical evidence/authority paths.  A selected claim is
    checked only through checks whose path is selected, so unrelated changes do
    not affect a filtered result.  ``receipt`` adds authority comparison
    snapshots and a separate ``receipt_issues`` integrity report.
    """

    try:
        root_path = Path(root).resolve()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise _error(f"root cannot be resolved: {root!r}") from exc
    claims, bindings, view_authorities = _validate_review_view(review_view)
    receipt_issues: list[dict[str, str]] = []
    receipt_authorities: list[dict[str, Any]] = []
    if receipt is not None:
        if not isinstance(receipt, Mapping):
            raise _error("receipt must be a JSON object")
        # The maintained receipt verifier checks both artifact identities and
        # authority snapshot shape.  Drift is evidence for the coordinator,
        # while malformed structure remains a fail-closed input error.
        receipt_issues = _copy(review.verify_receipt(receipt))
        view_identity = receipt["artifacts"].get("review.json")
        if view_identity is None:
            raise _error("receipt must bind its generated review.json before impact comparison")
        bound_view = sm.load_json(Path(view_identity["path"]))
        if not sm._json_equal(bound_view, review_view):
            raise _error("supplied review view does not match receipt review.json")
        receipt_authorities = _validate_receipt_authority_rows(receipt)
    filter_active, lexical_paths, resolved_paths = _filter_paths(root_path, paths)
    authority_rows = _authority_rows(view_authorities, receipt_authorities, receipt_present=receipt is not None)

    checks_by_claim: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    binding_checks: dict[str, dict[str, Any]] = {}
    for record in claims:
        checks: list[dict[str, Any]] = []
        claim = record["claim"]
        for reference in claim["evidence"].get("binding_references", []):
            binding = bindings[reference]
            try:
                resolved = sm._resolve(root_path, binding["path"], field="evidence path")
            except (sm.MetadataError, sm.EvidenceError):
                resolved = root_path / binding["path"]
            if filter_active and not _selected(binding["path"], resolved, lexical=lexical_paths, resolved=resolved_paths):
                continue
            if reference not in binding_checks:
                binding_checks[reference] = _binding_check(root_path, binding, reference)
            checks.append(_copy(binding_checks[reference]))
        target = claim.get("adoption", {}).get("target")
        if isinstance(target, Mapping):
            try:
                resolved = sm._resolve(root_path, target["path"], field="adoption target")
            except (sm.MetadataError, sm.EvidenceError):
                resolved = root_path / target["path"]
            if not filter_active or _selected(target["path"], resolved, lexical=lexical_paths, resolved=resolved_paths):
                checks.append(_target_check(root_path, target))
        checks_by_claim[record["key"]] = checks

    for row in authority_rows:
        record = _authority_claim_match(row, claims, bindings)
        try:
            resolved = sm._resolve(root_path, row["authority"]["path"], field="authority path")
        except (sm.MetadataError, sm.EvidenceError):
            resolved = root_path / row["authority"]["path"]
        if filter_active and not _selected(row["authority"]["path"], resolved, lexical=lexical_paths, resolved=resolved_paths):
            continue
        checks_by_claim[record["key"]].append(_authority_check(root_path, row))

    checked_records: list[dict[str, Any]] = []
    for record in claims:
        checks = checks_by_claim[record["key"]]
        if filter_active and not checks:
            continue
        if not checks:
            checks = [{
                "kind": "claim_evidence",
                "status": "unverifiable",
                "changes": [],
                "reason": "claim has no bound source, target, or authority evidence",
            }]
        status = _merge_status(checks)
        checked_records.append({
            **_claim_identifier(record),
            "status": status,
            "evidence_references": list(record["claim"]["evidence"].get("binding_references", [])),
            "checks": _copy(checks),
        })
    checked_records.sort(key=lambda row: (
        row["subject"]["kind"],
        row["subject"]["id"],
        row["dimension"],
        row["claim_id"],
        sm.canonical_bytes(row["scope"]),
    ))
    grouped = {
        status: [
            _copy(row)
            for row in checked_records
            if row["status"] == status
        ]
        for status in _STATUS_ORDER
    }
    checked_paths = sorted({
        check["path"]
        for row in checked_records
        for check in row["checks"]
        if isinstance(check.get("path"), str)
    })
    requested_paths = sorted(lexical_paths | resolved_paths)
    unmatched_paths = sorted(set(lexical_paths) - set(checked_paths))
    total_bindings = len(bindings)
    checked_binding_refs = {
        check["reference"]
        for row in checked_records
        for check in row["checks"]
        if check.get("kind") == "evidence_binding" and isinstance(check.get("reference"), str)
    }
    return {
        "schema_version": IMPACT_SCHEMA_VERSION,
        "notice": "Read-only evidence recheck; statuses do not renew semantic approval or alter historical bindings.",
        "scope": {
            "filtered": filter_active,
            "requested_paths": requested_paths,
            "checked_paths": checked_paths,
            "unmatched_paths": unmatched_paths,
            "total_claims": len(claims),
            "unchecked_claims": len(claims) - len(checked_records),
        },
        "claims": _copy(checked_records),
        "unchanged": grouped["unchanged"],
        "changed": grouped["changed"],
        "missing": grouped["missing"],
        "unverifiable": grouped["unverifiable"],
        "receipt_issues": receipt_issues,
        "counts": {
            "total_claims": len(claims),
            "checked_claims": len(checked_records),
            "unchecked_claims": len(claims) - len(checked_records),
            "checked_bindings": len(checked_binding_refs),
            "total_bindings": total_bindings,
            "unchanged": len(grouped["unchanged"]),
            "changed": len(grouped["changed"]),
            "missing": len(grouped["missing"]),
            "unverifiable": len(grouped["unverifiable"]),
            "receipt_issues": len(receipt_issues),
        },
    }


__all__ = ["IMPACT_SCHEMA_VERSION", "recheck_claim_evidence"]
