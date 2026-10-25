"""Opt-in batch review artifacts; never a metadata writer or semantic approver."""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from build.lib import source_metadata as sm
from build.lib import source_metadata_contract, source_metadata_evidence
from build.lib.source_metadata_evidence import extract_bindings as extract_bindings
from build.lib import source_metadata_alerts
from build.lib.source_metadata_alerts import semantic_alerts


_AUTHORITY_ROOT_NAMES = (
    ".git",
    "raw",
    "sources",
    "metadata",
    "data",
    "ir",
    "library",
    "schemas",
    "reports",
    "exports",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_AUTHORITY_COMPARISONS_VERSION = "source-metadata-authority-comparisons-v1"
_COMPARISON_SCOPE_KEYS = {"member", "entity", "predicate", "event_role"}
_COMPARISON_KEYS = {
    "subject", "field", "scope", "authority", "evidence_references", "review"
}
_COMPARISON_AUTHORITY_KEYS = {"path", "selector"}
_COMPARISON_REVIEW_KEYS = {"disposition", "note"}
_AUTHORITY_SNAPSHOT_KEYS = {
    "path", "selector", "resolved_path", "path_available", "selector_available",
    "availability", "value", "raw_sha256", "bytes", "reason",
}
_UNAVAILABLE_REASONS = {"path_unavailable", "json_unavailable", "selector_unavailable"}


def _path(value: Any, *, field: str) -> Path:
    """Coerce a path argument without leaking a TypeError to callers."""

    try:
        return Path(value)
    except (TypeError, ValueError) as exc:
        raise sm.MetadataError(f"{field} must be a filesystem path: {value!r}") from exc


def _resolved_path(value: Any, *, field: str) -> Path:
    path = _path(value, field=field)
    try:
        return path.resolve()
    except (OSError, RuntimeError) as exc:
        raise sm.MetadataError(f"{field} cannot be resolved: {path}: {exc}") from exc


def _identity_value(identity: Any, *, name: str) -> tuple[str, str, int]:
    """Validate the small identity contract used in review receipts."""

    if not isinstance(identity, Mapping) or set(identity) != {"path", "sha256", "bytes"}:
        raise sm.MetadataError(f"invalid receipt identity: {name}")
    path = identity["path"]
    if not isinstance(path, str) or not path or not _path(path, field=f"receipt path for {name}").is_absolute():
        raise sm.MetadataError(f"receipt path must be an absolute nonempty string: {name}")
    digest = identity["sha256"]
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise sm.MetadataError(f"receipt sha256 must be a lowercase 64-character hex string: {name}")
    size = identity["bytes"]
    if type(size) is not int or size < 0:
        raise sm.MetadataError(f"receipt bytes must be a nonnegative integer: {name}")
    return path, digest, size


def _artifact_identity(path: Any, *, name: str) -> dict[str, Any]:
    """Create an identity, turning missing runtime artifacts into MetadataError."""

    try:
        return file_identity(_path(path, field=f"{name} path"))
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise sm.MetadataError(f"cannot read {name} artifact: {path}: {exc}") from exc


def file_identity(path: Path, data: bytes | None = None) -> dict[str, Any]:
    path = _resolved_path(path, field="artifact path")
    if data is not None and not isinstance(data, bytes):
        raise sm.MetadataError("artifact identity data must be bytes")
    raw = path.read_bytes() if data is None else data
    return {"path": str(path), "sha256": sm.sha256_bytes(raw), "bytes": len(raw)}


def _snapshot(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _path(path, field="JSON input")
    try:
        raw = path.read_bytes()
    except (OSError, RuntimeError) as exc:
        raise sm.MetadataError(f"cannot read JSON input {path}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=sm._reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise sm.MetadataError(f"invalid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise sm.MetadataError(f"expected JSON object: {path}")
    return payload, file_identity(path, raw)


def _strict_json_pointer(value: Any) -> str:
    """Validate an RFC 6901 pointer before using the shared resolver."""

    if not isinstance(value, str) or not value.startswith("/"):
        raise sm.MetadataError("authority selector must be a nonempty JSON pointer")
    for token in value[1:].split("/"):
        for index, character in enumerate(token):
            if character == "~" and (
                index + 1 >= len(token) or token[index + 1] not in {"0", "1"}
            ):
                raise sm.MetadataError(
                    f"authority selector is not a valid RFC 6901 pointer: {value!r}"
                )
    return value


def _strict_pointer_value(document: Any, selector: str) -> Any:
    """Resolve a validated pointer while applying array-index syntax by node type."""

    value = document
    for token in sm._pointer_tokens(selector):
        if isinstance(value, Mapping):
            if token not in value:
                raise KeyError(token)
            value = value[token]
            continue
        if isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise KeyError(token)
            if not value:
                raise KeyError(token)
            last_index = str(len(value) - 1)
            if len(token) > len(last_index) or (
                len(token) == len(last_index) and token > last_index
            ):
                raise KeyError(token)
            index = int(token)
            value = value[index]
            continue
        raise KeyError(token)
    return value


def _comparison_scope(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _COMPARISON_SCOPE_KEYS:
        raise sm.MetadataError(
            "authority comparison scope requires exactly member, entity, predicate, and event_role"
        )
    if any(not isinstance(item, str) or not item for item in value.values()):
        raise sm.MetadataError("authority comparison scope values must be nonempty strings")
    return {key: value[key] for key in sorted(_COMPARISON_SCOPE_KEYS)}


def validate_authority_comparisons(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the compact, explicit authority-comparison input contract."""

    if not isinstance(payload, Mapping):
        raise sm.MetadataError("authority comparison input must be a JSON object")
    if set(payload) != {"schema_version", "comparisons"}:
        raise sm.MetadataError(
            "authority comparison input requires exactly schema_version and comparisons"
        )
    if payload.get("schema_version") != _AUTHORITY_COMPARISONS_VERSION:
        raise sm.MetadataError("unsupported authority comparison schema_version")
    rows = payload.get("comparisons")
    if not isinstance(rows, list) or not rows:
        raise sm.MetadataError("authority comparison input requires a nonempty comparisons array")
    result: list[dict[str, Any]] = []
    seen: set[bytes] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != _COMPARISON_KEYS:
            raise sm.MetadataError(
                "authority comparison requires exactly subject, field, scope, authority, "
                "evidence_references, and review"
            )
        subject = row["subject"]
        subject_key = _key(subject)
        field = row["field"]
        if not isinstance(field, str) or not field.strip():
            raise sm.MetadataError("authority comparison field must be a nonempty string")
        scope = _comparison_scope(row["scope"])
        authority = row["authority"]
        if not isinstance(authority, Mapping) or set(authority) != _COMPARISON_AUTHORITY_KEYS:
            raise sm.MetadataError("authority comparison authority requires exactly path and selector")
        path = authority["path"]
        sm._normal_relative(path, field="authority path")
        selector = _strict_json_pointer(authority["selector"])
        references = row["evidence_references"]
        if not isinstance(references, list) or not references:
            raise sm.MetadataError("authority comparison requires nonempty evidence_references")
        if any(not isinstance(reference, str) or _SHA256_RE.fullmatch(reference) is None for reference in references):
            raise sm.MetadataError("authority comparison evidence references must be sha256 IDs")
        if len(set(references)) != len(references):
            raise sm.MetadataError("authority comparison evidence references must be unique")
        review = row["review"]
        if not isinstance(review, Mapping) or not set(review) <= _COMPARISON_REVIEW_KEYS:
            raise sm.MetadataError("authority comparison review has unsupported keys")
        if "disposition" not in review or not isinstance(review["disposition"], str) or not review["disposition"].strip():
            raise sm.MetadataError("authority comparison review requires a nonempty disposition")
        if "note" in review and (not isinstance(review["note"], str) or not review["note"].strip()):
            raise sm.MetadataError("authority comparison review note must be a nonempty string")
        normalized = {
            "subject": {"kind": subject_key[0], "id": subject_key[1]},
            "field": field,
            "scope": scope,
            "authority": {"path": path, "selector": selector},
            "evidence_references": list(references),
            "review": {key: review[key] for key in ("disposition", "note") if key in review},
        }
        identity = sm.canonical_bytes(normalized)
        if identity in seen:
            raise sm.MetadataError("duplicate authority comparison")
        seen.add(identity)
        result.append(normalized)
    return result


def _read_authority(path: Path, *, path_text: str, selector: str) -> dict[str, Any]:
    """Read one authority path once and retain its availability state."""

    path = _resolved_path(path, field="authority path")
    snapshot: dict[str, Any] = {
        "path": path_text,
        "selector": selector,
        "resolved_path": str(path),
        "path_available": False,
        "selector_available": False,
        "availability": "unavailable",
        "value": None,
        "raw_sha256": None,
        "bytes": None,
        "reason": "path_unavailable",
    }
    try:
        raw = path.read_bytes()
    except (OSError, RuntimeError):
        return snapshot
    snapshot.update(path_available=True, raw_sha256=sm.sha256_bytes(raw), bytes=len(raw))
    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=sm._reject_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, sm.MetadataError):
        snapshot["reason"] = "json_unavailable"
        return snapshot
    try:
        value = _strict_pointer_value(document, selector)
    except (KeyError, sm.MetadataError):
        snapshot["reason"] = "selector_unavailable"
        return snapshot
    snapshot.update(
        selector_available=True,
        availability="available",
        value=copy.deepcopy(value),
        reason=None,
    )
    return snapshot


def _public_authority_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(snapshot[key])
        for key in sorted(_AUTHORITY_SNAPSHOT_KEYS)
        if key != "resolved_path"
    }


def _binding_reference(binding: Mapping[str, Any]) -> str:
    return sm.sha256_bytes(sm.canonical_bytes(binding))


def _comparison_claim(
    comparison: Mapping[str, Any], *, worklist: Mapping[str, Any], entries: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve one comparison to exactly one same-scope candidate claim."""

    subject_key = _key(comparison["subject"])
    field = comparison["field"]
    scope = comparison["scope"]
    references = set(comparison["evidence_references"])
    work_items = sm._worklist_items(worklist)
    matches: list[dict[str, Any]] = []
    for entry in entries:
        if _key(entry["subject"]) != subject_key:
            continue
        for dimension, payload in entry.get("dimensions", {}).items():
            for claim in payload.get("fields", []):
                item = work_items.get((*subject_key, claim["worklist_item_id"]))
                if item is None or item.get("field") != field or claim.get("scope") != scope:
                    continue
                binding_refs = {
                    _binding_reference(binding)
                    for binding in claim.get("evidence", {}).get("bindings", [])
                }
                if references <= binding_refs:
                    matches.append(claim)
    if len(matches) != 1:
        if not matches:
            raise sm.MetadataError(
                "authority comparison evidence references do not map to one same-scope claim"
            )
        raise sm.MetadataError("authority comparison mapping is ambiguous")
    claim = matches[0]
    if "value" not in claim.get("evidence", {}):
        raise sm.MetadataError("authority comparison mapped claim has no explicit evidence value")
    referenced_bindings = [
        binding
        for binding in claim.get("evidence", {}).get("bindings", [])
        if _binding_reference(binding) in references
    ]
    if not any(binding.get("role") == "primary" for binding in referenced_bindings):
        raise sm.MetadataError(
            "authority comparison requires a referenced primary retained-evidence binding"
        )
    return claim


def _evaluate_authority_comparisons(
    root: Path,
    comparisons: list[dict[str, Any]],
    *,
    worklist: Mapping[str, Any],
    entries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    receipt_rows: list[dict[str, Any]] = []
    for comparison in comparisons:
        claim = _comparison_claim(comparison, worklist=worklist, entries=entries)
        authority_input = comparison["authority"]
        authority_path = sm._resolve(root, authority_input["path"], field="authority path")
        authority = _read_authority(
            authority_path,
            path_text=authority_input["path"],
            selector=authority_input["selector"],
        )
        expected = copy.deepcopy(claim["evidence"]["value"])
        if authority["availability"] != "available":
            comparison_status = "unavailable"
            message = (
                "Current authority path or selector is unavailable; review the mapped "
                "evidence and disposition."
            )
        elif sm._json_equal(expected, authority["value"]):
            comparison_status = "match"
            message = (
                "Current authority value matches the explicitly mapped value; "
                "retain the human disposition."
            )
        else:
            comparison_status = "different"
            message = (
                "Current authority value differs from the explicitly mapped value; "
                "review the difference."
            )
        alert = {
            "kind": "authority_comparison",
            "subject": comparison["subject"],
            "field": comparison["field"],
            "scope": comparison["scope"],
            "status": comparison_status,
            "message": message,
        }
        row = {
            **copy.deepcopy(comparison),
            "mapped_value": expected,
            "mapped_claim": {
                "worklist_item_id": claim["worklist_item_id"],
                "claim_id": claim["claim_id"],
                "evidence_classification": claim["evidence"]["classification"],
            },
            "authority": _public_authority_snapshot(authority),
            "comparison": comparison_status,
            "alerts": [alert],
        }
        rows.append(row)
        receipt_rows.append(
            {
                "subject": copy.deepcopy(comparison["subject"]),
                "field": comparison["field"],
                "scope": copy.deepcopy(comparison["scope"]),
                "authority": authority,
                "evidence_references": list(comparison["evidence_references"]),
            }
        )
    return rows, receipt_rows


def _validate_authority_snapshot(snapshot: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping) or set(snapshot) != _AUTHORITY_SNAPSHOT_KEYS:
        raise sm.MetadataError(f"invalid authority comparison snapshot: {index}")
    path_text = snapshot["path"]
    sm._normal_relative(path_text, field=f"authority comparison snapshot path {index}")
    selector = _strict_json_pointer(snapshot["selector"])
    resolved_text = snapshot["resolved_path"]
    if not isinstance(resolved_text, str) or not resolved_text or not _path(
        resolved_text, field=f"authority comparison snapshot resolved path {index}"
    ).is_absolute():
        raise sm.MetadataError(
            f"authority comparison snapshot resolved path must be absolute: {index}"
        )
    path_available = snapshot["path_available"]
    selector_available = snapshot["selector_available"]
    if type(path_available) is not bool or type(selector_available) is not bool:
        raise sm.MetadataError(f"authority comparison snapshot availability must be boolean: {index}")
    availability = snapshot["availability"]
    if not isinstance(availability, str) or availability not in {"available", "unavailable"}:
        raise sm.MetadataError(f"invalid authority comparison availability: {index}")
    raw_sha256 = snapshot["raw_sha256"]
    if raw_sha256 is not None and (
        not isinstance(raw_sha256, str) or _SHA256_RE.fullmatch(raw_sha256) is None
    ):
        raise sm.MetadataError(f"invalid authority comparison raw sha256: {index}")
    size = snapshot["bytes"]
    if size is not None and (type(size) is not int or size < 0):
        raise sm.MetadataError(f"invalid authority comparison byte count: {index}")
    reason = snapshot["reason"]
    if reason is not None and (
        not isinstance(reason, str) or reason not in _UNAVAILABLE_REASONS
    ):
        raise sm.MetadataError(f"invalid authority comparison unavailable reason: {index}")
    if not path_available:
        if raw_sha256 is not None or size is not None or selector_available:
            raise sm.MetadataError(f"unavailable authority snapshot has inconsistent identity: {index}")
        if availability != "unavailable" or reason != "path_unavailable":
            raise sm.MetadataError(f"unavailable authority snapshot has inconsistent state: {index}")
    elif raw_sha256 is None or size is None:
        raise sm.MetadataError(f"available authority path lacks raw identity: {index}")
    if selector_available:
        if not path_available or availability != "available" or reason is not None:
            raise sm.MetadataError(f"available authority selector has inconsistent state: {index}")
    elif availability != "unavailable" or reason not in {"json_unavailable", "selector_unavailable", "path_unavailable"}:
        raise sm.MetadataError(f"unavailable authority selector has inconsistent state: {index}")
    if availability == "available" and (not path_available or not selector_available):
        raise sm.MetadataError(f"available authority snapshot has inconsistent availability: {index}")
    return {
        "path": path_text,
        "selector": selector,
        "resolved_path": str(_path(resolved_text, field="authority comparison resolved path")),
        "path_available": path_available,
        "selector_available": selector_available,
        "availability": availability,
        "value": copy.deepcopy(snapshot["value"]),
        "raw_sha256": raw_sha256,
        "bytes": size,
        "reason": reason,
    }


def _validate_authority_comparison_receipt_row(row: Any, *, index: int) -> dict[str, Any]:
    expected_keys = {"subject", "field", "scope", "authority", "evidence_references"}
    if not isinstance(row, Mapping) or set(row) != expected_keys:
        raise sm.MetadataError(f"invalid authority comparison receipt row: {index}")
    subject_key = _key(row["subject"])
    field = row["field"]
    if not isinstance(field, str) or not field.strip():
        raise sm.MetadataError(f"invalid authority comparison receipt field: {index}")
    scope = _comparison_scope(row["scope"])
    references = row["evidence_references"]
    if not isinstance(references, list) or not references or any(
        not isinstance(reference, str) or _SHA256_RE.fullmatch(reference) is None
        for reference in references
    ):
        raise sm.MetadataError(f"invalid authority comparison receipt evidence references: {index}")
    if len(set(references)) != len(references):
        raise sm.MetadataError(f"duplicate authority comparison receipt evidence reference: {index}")
    authority = _validate_authority_snapshot(row["authority"], index=index)
    return {
        "subject": {"kind": subject_key[0], "id": subject_key[1]},
        "field": field,
        "scope": scope,
        "authority": authority,
        "evidence_references": list(references),
    }


def _authority_snapshot_difference(expected: Mapping[str, Any], fresh: Mapping[str, Any]) -> str | None:
    if expected["resolved_path"] != fresh["resolved_path"]:
        return "authority resolved path changed"
    if (
        expected["path_available"] != fresh["path_available"]
        or expected["selector_available"] != fresh["selector_available"]
        or expected["availability"] != fresh["availability"]
        or expected["reason"] != fresh["reason"]
    ):
        return "authority availability changed"
    if expected["raw_sha256"] != fresh["raw_sha256"] or expected["bytes"] != fresh["bytes"]:
        return "authority raw identity changed"
    if not sm._json_equal(expected["value"], fresh["value"]):
        return "authority value changed"
    return None


def _verify_authority_comparison_receipt(value: Any, *, root: Path) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise sm.MetadataError("authority comparison receipt requires a nonempty array")
    root = _resolved_path(root, field="authority comparison root")
    issues: list[dict[str, str]] = []
    for index, row in enumerate(value):
        normalized = _validate_authority_comparison_receipt_row(row, index=index)
        expected = normalized["authority"]
        try:
            fresh_path = sm._resolve(root, expected["path"], field="authority path")
        except sm.MetadataError:
            issues.append(
                {"artifact": f"authority_comparison[{index}]", "message": "authority path resolution changed"}
            )
            continue
        if str(fresh_path) != expected["resolved_path"]:
            issues.append(
                {"artifact": f"authority_comparison[{index}]", "message": "authority resolved path changed"}
            )
            continue
        fresh = _read_authority(
            fresh_path,
            path_text=expected["path"],
            selector=expected["selector"],
        )
        difference = _authority_snapshot_difference(expected, fresh)
        if difference:
            issues.append({"artifact": f"authority_comparison[{index}]", "message": difference})
    return issues


def verify_receipt(receipt: Mapping[str, Any]) -> list[dict[str, str]]:
    """Rehash explicit input, verifier and generated-artifact identities."""
    if not isinstance(receipt, Mapping):
        raise sm.MetadataError("review receipt must be a JSON object")
    if receipt.get("format") not in {"source-metadata-review-receipt-v1", "source-metadata-review-receipt-v2", "source-metadata-review-receipt-v3"}:
        raise sm.MetadataError("unsupported review receipt format")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise sm.MetadataError("review receipt requires artifact identities")
    required = {"worklist", "candidate", "selection", "engine", "review_engine", "schema"}
    if receipt["format"] in {"source-metadata-review-receipt-v2", "source-metadata-review-receipt-v3"}:
        required.add("semantic_alert_engine")
    if receipt["format"] == "source-metadata-review-receipt-v3":
        required.update({"evidence_engine", "metadata_contract"})
    if not required <= set(artifacts):
        raise sm.MetadataError("review receipt is missing a required input or verifier identity")
    for name in artifacts:
        if not isinstance(name, str) or not name:
            raise sm.MetadataError("review receipt artifact names must be nonempty strings")
    issues = []
    for name, expected in sorted(artifacts.items()):
        path_text, _digest, _size = _identity_value(expected, name=name)
        try:
            actual = file_identity(Path(path_text))
            if actual != expected:
                issues.append({"artifact": name, "message": "artifact identity changed"})
        except (OSError, RuntimeError) as exc:
            issues.append({"artifact": name, "message": str(exc)})
    # Legacy receipts have no authority-comparison field and retain exactly the
    # historical artifact-only verification behavior.  Opt-in receipts also
    # bind every comparison input's fresh authority state.
    has_comparison_receipt = "authority_comparisons" in receipt
    has_comparison_root = "authority_comparison_root" in receipt
    has_comparison_artifact = "authority_comparisons" in artifacts
    if has_comparison_receipt:
        if "authority_comparisons" not in artifacts:
            raise sm.MetadataError(
                "authority comparison receipt is missing its input artifact identity"
            )
        root_text = receipt.get("authority_comparison_root")
        if not isinstance(root_text, str) or not root_text or not _path(
            root_text, field="authority comparison root"
        ).is_absolute():
            raise sm.MetadataError("authority comparison receipt requires an absolute root")
        issues.extend(
            _verify_authority_comparison_receipt(
                receipt["authority_comparisons"], root=Path(root_text)
            )
        )
    elif has_comparison_root or has_comparison_artifact:
        raise sm.MetadataError("incomplete authority comparison receipt")
    return issues


def _key(subject: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(subject, Mapping) or set(subject) != {"kind", "id"}:
        raise sm.MetadataError("selected subject requires exactly kind and id")
    sm._safe_subject(subject)
    return subject["kind"], subject["id"]


def _validate_selection(selection: Mapping[str, Any], worklist_sha256: str) -> list[tuple[str, str]]:
    """Validate the selection fields used by preflight while allowing plan metadata."""

    if not isinstance(selection, Mapping):
        raise sm.MetadataError("selection must be a JSON object")
    selected_rows = selection.get("subjects")
    if not isinstance(selected_rows, list) or not selected_rows:
        raise sm.MetadataError("selection requires a nonempty explicit subjects list")
    before_hashes = selection.get("before_hashes", {})
    if not isinstance(before_hashes, Mapping):
        raise sm.MetadataError("selection before_hashes must be an object")
    for name, digest in before_hashes.items():
        if not isinstance(name, str) or not name:
            raise sm.MetadataError("selection before_hashes keys must be nonempty strings")
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise sm.MetadataError(f"selection before_hashes entry is not a valid sha256: {name}")
    explicit_pin = selection.get("worklist_sha256")
    if explicit_pin is not None and (not isinstance(explicit_pin, str) or _SHA256_RE.fullmatch(explicit_pin) is None):
        raise sm.MetadataError("selection worklist_sha256 must be a lowercase 64-character hex string")
    pin = explicit_pin if "worklist_sha256" in selection else before_hashes.get("worklist.json")
    if pin != worklist_sha256:
        raise sm.MetadataError("selection must pin the exact worklist_sha256 (or before_hashes/worklist.json)")
    selected_keys = [_key(row) for row in selected_rows]
    if len(set(selected_keys)) != len(selected_keys):
        raise sm.MetadataError("duplicate selected subject")
    return selected_keys


def _claim_map(entries: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    result = {}
    for entry in entries:
        for dimension, payload in entry["dimensions"].items():
            for claim in payload["fields"]:
                # Scoped identity is required: claim_id alone need not be unique.
                key = (*_key(entry["subject"]), dimension, *sm._claim_identity(claim))
                if key in result:
                    raise sm.MetadataError(f"ambiguous review claim identity: {key}")
                result[key] = claim
    return result


def _structure(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for entry in entries:
        result.append({"subject": entry["subject"], "dimensions": {
            dimension: {k: v for k, v in payload.items() if k != "fields"}
            for dimension, payload in entry["dimensions"].items()
        }})
    return sorted(result, key=lambda entry: _key(entry["subject"]))


def claim_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """Full claim-object delta plus dimension/subject metadata changes."""
    old, new = _claim_map(before), _claim_map(after)
    common = old.keys() & new.keys()
    changed = sorted(key for key in common if sm.canonical_bytes(old[key]) != sm.canonical_bytes(new[key]))
    return {
        "added": [{"key": key, "after": new[key]} for key in sorted(new.keys() - old.keys())],
        "removed": [{"key": key, "before": old[key]} for key in sorted(old.keys() - new.keys())],
        "changed": [{"key": key, "before": old[key], "after": new[key]} for key in changed],
        "unchanged": [{"key": key, "sha256": sm.sha256_bytes(sm.canonical_bytes(old[key]))}
                      for key in sorted(common - set(changed))],
        "structure_changed": _structure(before) != _structure(after),
        "structure_before": _structure(before), "structure_after": _structure(after),
    }


def review_view(
    entries: list[dict[str, Any]],
    *,
    authority_comparisons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Lossless claim objects with identical evidence bindings displayed once."""
    evidence = {}
    claims = []
    alerts = []
    for key, original in sorted(_claim_map(entries).items()):
        claim = copy.deepcopy(original)
        bindings = claim["evidence"].pop("bindings", [])
        references = []
        for binding in bindings:
            identifier = _binding_reference(binding)
            evidence[identifier] = binding
            references.append(identifier)
        if "bindings" in original["evidence"]:
            claim["evidence"]["binding_references"] = references
        claims.append({"key": key, "claim": claim})
        value = original["evidence"].get("value")
        classification = original["evidence"]["classification"]
        reasons = semantic_alerts(original)
        if original["adoption"]["classification"] == "not_applicable" and original["requirement"]["classification"] != "not_applicable":
            reasons.append("applicability: not_applicable adoption on an applicable requirement")
        if classification == "supported" and isinstance(value, (dict, list)) and len(value) > 1:
            reasons.append("composite: check support for every asserted component")
        question = " ".join(str(original["evidence"].get(k, "")) for k in ("question", "evidence_needed"))
        if (original["worklist_item_id"].endswith(":assessment_scope") and classification == "unresolved"
                and re.search(r"which atomic|atomic facts|which .*facts apply|workflow|covered by", question, re.I)):
            reasons.append("scope_question: confirm this is a factual unknown, not completed workflow")
        excerpt = json.dumps([b["locator"]["expected"] for b in bindings], ensure_ascii=False)
        if classification == "supported" and re.fullmatch(r"\d{3,4}", str(value)) and re.search(r"\b(?:or|late|early|circa|about|approximately|later)\b|\d{3,4}\s*[-–]\s*\d{3,4}", excerpt, re.I):
            reasons.append("date_qualifier: compare scalar year with the complete source expression")
        if "\ufffd" in json.dumps(original, ensure_ascii=False):
            reasons.append("unicode: compare replacement character with retained bytes")
        alerts.extend({"key": key, "reason": reason} for reason in reasons)
    view = {
        "notice": "Generated review view, not writer input or semantic approval. Alerts require judgment.",
        "structure": _structure(entries), "claims": claims, "evidence": evidence, "alerts": alerts,
    }
    if authority_comparisons is not None:
        view["authority_comparisons"] = copy.deepcopy(authority_comparisons)
        view["alerts"].extend(
            copy.deepcopy(alert)
            for row in authority_comparisons
            for alert in row.get("alerts", [])
        )
    return view


def preflight(
    root: Path, *, worklist_path: Path, decisions_path: Path, selection_path: Path,
    predecessor_path: Path | None = None, notes: tuple[Path, ...] = (),
    authority_comparisons_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    """Check a complete-subject batch against an independently frozen selection.

    Inherited/unexamined selected dimensions fail. This opt-in rule does not
    alter the existing partial-pilot writer or its evidence-only write gate.
    """
    root = _path(root, field="data root")
    worklist, work_id = _snapshot(worklist_path)
    candidate, candidate_id = _snapshot(decisions_path)
    selection, selection_id = _snapshot(selection_path)
    sm.validate_worklist(worklist)
    selected = set(_validate_selection(selection, work_id["sha256"]))
    known = {_key(entry["subject"]) for entry in worklist["subjects"]}
    if selected - known:
        raise sm.MetadataError(f"selection contains unknown subjects: {sorted(selected - known)}")
    entries = sm.validate_decision_documents([candidate], worklist=worklist)
    decided = {_key(entry["subject"]) for entry in entries}
    bounded = {**worklist, "subjects": [e for e in worklist["subjects"] if _key(e["subject"]) in selected]}
    expected = {(*_key(e["subject"]), dimension, item["item_id"])
                for e in bounded["subjects"] for dimension, payload in e["dimensions"].items() for item in payload["items"]}
    represented = {(*_key(e["subject"]), dimension, claim["worklist_item_id"])
                   for e in entries for dimension, payload in e["dimensions"].items() for claim in payload["fields"]}
    issues = sm.verify_evidence(root, bounded, entries)
    report = sm.coverage_report(bounded, entries, evidence_issues=issues)
    failures = []
    for label, values in [("missing_subject", selected - decided), ("extra_subject", decided - selected),
                          ("missing_item", expected - represented), ("extra_item", represented - expected)]:
        failures.extend({"kind": label, "key": list(key)} for key in sorted(values))
    failures.extend({"kind": "missing_dimension", **row} for row in report["missing_dimensions"])
    failures.extend({"kind": "unexamined", **row} for row in report["inspection_unexamined"])
    failures.extend({"kind": "evidence", "detail": row} for row in issues)
    comparison_rows: list[dict[str, Any]] | None = None
    comparison_receipt_rows: list[dict[str, Any]] | None = None
    comparison_identity: dict[str, Any] | None = None
    if authority_comparisons_path is not None:
        comparison_input, comparison_identity = _snapshot(authority_comparisons_path)
        comparisons = validate_authority_comparisons(comparison_input)
        comparison_rows, comparison_receipt_rows = _evaluate_authority_comparisons(
            root,
            comparisons,
            worklist=bounded,
            entries=entries,
        )
    view = review_view(entries, authority_comparisons=comparison_rows)
    artifacts = {"worklist": work_id, "candidate": candidate_id, "selection": selection_id,
                 "engine": _artifact_identity(sm.__file__, name="engine"),
                 "evidence_engine": _artifact_identity(source_metadata_evidence.__file__, name="evidence engine"),
                 "metadata_contract": _artifact_identity(source_metadata_contract.__file__, name="metadata contract"),
                 "review_engine": _artifact_identity(__file__, name="review engine"),
                 "semantic_alert_engine": _artifact_identity(source_metadata_alerts.__file__, name="semantic alert engine"),
                 "schema": _artifact_identity(sm.SCHEMA_PATH, name="schema")}
    if comparison_identity is not None:
        artifacts["authority_comparisons"] = comparison_identity
    for i, path in enumerate(notes):
        artifacts[f"notes_{i}"] = _artifact_identity(path, name=f"notes_{i}")
    delta = None
    if predecessor_path is not None:
        predecessor, identity = _snapshot(predecessor_path)
        before = sm.validate_decision_documents([predecessor], worklist=worklist)
        delta = claim_diff(before, entries)
        delta["document_metadata_before"] = {k: v for k, v in predecessor.items() if k != "decisions"}
        delta["document_metadata_after"] = {k: v for k, v in candidate.items() if k != "decisions"}
        delta["document_metadata_changed"] = (
            sm.canonical_bytes(delta["document_metadata_before"])
            != sm.canonical_bytes(delta["document_metadata_after"])
        )
        artifacts["predecessor"] = identity
    receipt = {
        "format": "source-metadata-review-receipt-v3", "artifacts": artifacts,
        "runtime": {"executable": sys.executable, "python": sys.version,
                    "data_root": str(_resolved_path(root, field="data root"))},
        "mechanical_status": "fail" if failures else "pass", "semantic_review": "required",
        "selection_policy": "All five dimensions and all frozen items of each selected subject; unexamined fails.",
        "counts": {"selected_subjects": len(selected), "decided_subjects": len(decided),
                   "expected_items": len(expected), "represented_items": len(represented),
                   "claims": len(view["claims"]), "unique_bindings": len(view["evidence"]), "alerts": len(view["alerts"])},
        "axes": {k: report[k] for k in ["persistence", "inspection", "evidence", "required_repair", "optional_decision"]},
        "failures": failures, "alerts": view["alerts"],
    }
    if comparison_receipt_rows is not None:
        receipt["authority_comparisons"] = comparison_receipt_rows
        receipt["authority_comparison_root"] = str(_resolved_path(root, field="data root"))
        receipt["counts"]["authority_comparisons"] = len(comparison_receipt_rows)
    # A receipt describes the bytes actually read, never a later reread silently
    # substituted under the same name. Recheck immediately before publication too.
    drift = verify_receipt(receipt)
    if drift:
        raise sm.MetadataError(f"inputs changed during preflight: {drift}")
    return receipt, view, delta


def _safe_output_path(
    output: Any,
    root: Any,
    *,
    field: str,
    protected_paths: tuple[Any, ...] = (),
    ancestor_protected_paths: tuple[Any, ...] = (),
) -> Path:
    """Resolve a review output and reject repository authority or input paths."""

    output_path = _resolved_path(output, field=field)
    root_path = _resolved_path(root, field="data root")
    if output_path == root_path:
        raise sm.MetadataError(f"{field} cannot be the data root: {output_path}")
    for name in _AUTHORITY_ROOT_NAMES:
        authority = _resolved_path(root_path / name, field=f"authority directory {name}")
        if output_path == authority or output_path.is_relative_to(authority):
            raise sm.MetadataError(f"{field} cannot be inside authority directory: {name}")
    for protected in protected_paths:
        protected_path = _resolved_path(protected, field="protected input")
        if output_path == protected_path or output_path.is_relative_to(protected_path):
            raise sm.MetadataError(f"{field} cannot replace input path: {protected_path}")
    for protected in ancestor_protected_paths:
        protected_path = _resolved_path(protected, field="authority input")
        if (
            output_path == protected_path
            or output_path.is_relative_to(protected_path)
            or protected_path.is_relative_to(output_path)
        ):
            raise sm.MetadataError(f"{field} cannot collide with authority input path: {protected_path}")
    return output_path


def write_review(destination: Path, root: Path, receipt: dict[str, Any], view: dict[str, Any], delta: dict[str, Any] | None) -> None:
    """Create a new review directory, refusing overwrite and authority roots."""
    if not isinstance(receipt, dict):
        raise sm.MetadataError("review receipt must be a mutable JSON object")
    drift = verify_receipt(receipt)
    if drift:
        raise sm.MetadataError(f"inputs changed before writing review: {drift}")
    if not isinstance(receipt.get("artifacts"), dict):
        raise sm.MetadataError("review receipt artifacts must be a mutable JSON object")
    destination = _safe_output_path(
        destination,
        root,
        field="review output",
        protected_paths=tuple(
            [
                identity["path"]
                for identity in receipt.get("artifacts", {}).values()
                if isinstance(identity, Mapping) and isinstance(identity.get("path"), str)
            ]
            + [
                authority["resolved_path"]
                for row in receipt.get("authority_comparisons", [])
                if isinstance(row, Mapping)
                and isinstance((authority := row.get("authority")), Mapping)
                and isinstance(authority.get("resolved_path"), str)
            ]
        ),
        ancestor_protected_paths=tuple(
            authority["resolved_path"]
            for row in receipt.get("authority_comparisons", [])
            if isinstance(row, Mapping)
            and isinstance((authority := row.get("authority")), Mapping)
            and isinstance(authority.get("resolved_path"), str)
        ),
    )
    destination.mkdir(parents=True, exist_ok=False)
    generated = {"review.json": view}
    if delta is not None:
        generated["diff.json"] = delta
    for name, payload in generated.items():
        data = sm.canonical_bytes(payload)
        path = destination / name
        with path.open("xb") as stream:
            stream.write(data)
        receipt["artifacts"][name] = file_identity(path, data)
    markdown = render_review(view).encode("utf-8")
    markdown_path = destination / "review.md"
    with markdown_path.open("xb") as stream:
        stream.write(markdown)
    receipt["artifacts"]["review.md"] = file_identity(markdown_path, markdown)
    drift = verify_receipt(receipt)
    if drift:
        raise sm.MetadataError(f"generated review artifacts changed before receipt: {drift}")
    with (destination / "receipt.json").open("xb") as stream:
        stream.write(sm.canonical_bytes(receipt))


def render_review(view: Mapping[str, Any]) -> str:
    """Render complete claims and a shared evidence appendix without truncation."""
    def block(value: Any) -> str:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        fence = "`" * max(3, 1 + max((len(m) for m in re.findall(r"`+", text)), default=0))
        return f"{fence}json\n{text}\n{fence}\n"
    lines = ["# Generated metadata review\n", str(view["notice"]) + "\n", "## Subject and dimension states\n", block(view["structure"]), "## Claims\n"]
    for row in view["claims"]:
        lines.append(block(row))
    lines.append("## Evidence appendix\n")
    for identifier, binding in sorted(view["evidence"].items()):
        lines.extend([f"### {identifier}\n", block(binding)])
    if "authority_comparisons" in view:
        lines.extend(["## Current authority comparisons\n", block(view["authority_comparisons"])])
    lines.extend(["## Review alerts\n", block(view["alerts"])])
    return "\n".join(lines)
