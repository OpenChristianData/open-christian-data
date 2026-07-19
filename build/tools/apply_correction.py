"""Apply approved text corrections to data/<...>/<record>.json layers.

Phase G of the OCD text accuracy plan. Reads ledger entries with
status=approved AND correction_type=text from
review/corrections/<path>/<record>.jsonl, mutates
layers.<field>.display (NOT structured), promotes the ledger entry to
status=applied, emits a writer manifest pairing the data/ change with the
correction_applier writer identity, and emits an audit event.

Structural corrections (correction_type=structural) are explicitly deferred:
the applier rejects them with applier_deferred_reason=structural_deferred and
the ledger entry stays in status=approved until a future phase ships a
structural applier.

CLI:
    py -3 build/tools/apply_correction.py \
        --resource data/commentaries/adam-clarke/2-john.json \
        --ledger review/corrections/commentaries/adam-clarke/2-john.jsonl \
        --writer-manifest-out review/writer-manifests/apply_corrections_<run>.json \
        [--dry-run] [--correction-id <id>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from ocd_kernel.lib.atomic_io import (  # noqa: E402
    AtomicWriteError,
    append_jsonl_atomic,
    validate_payload,
    write_json_atomic,
)
from build.lib.paths import REPO_ROOT  # noqa: E402
from ocd_kernel.lib.schema_enums import resolve_schema_path  # noqa: E402

LEDGER_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "correction_ledger.schema.json"
WRITER_MANIFEST_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "writer_manifest.schema.json"
AUDIT_SCHEMA_PATH = resolve_schema_path("audit_event")
REVIEW_STATE_SCHEMA_PATH = resolve_schema_path("review_state")

WRITER_IDENTITY = "correction_applier"


class ApplierError(RuntimeError):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class StructuralCorrectionDeferred(ApplierError):
    def __init__(self, message: str, applier_deferred_reason: str = "structural_deferred"):
        super().__init__(message)
        self.applier_deferred_reason = applier_deferred_reason


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sidecar_path_for(record_path: str) -> Path:
    """data/commentaries/foo/bar.json -> review/state/commentaries/foo/bar.json."""
    rec = Path(record_path)
    if rec.parts and rec.parts[0] == "data":
        relative = Path(*rec.parts[1:])
    else:
        relative = rec
    return REPO_ROOT / "review" / "state" / relative


def _auto_acknowledge_warning(
    sidecar_path: Path,
    *,
    entry_id: str,
    producer_warning_signature: str | None,
) -> bool:
    """Append the warning signature to the sidecar's acknowledged set for entry_id.

    Returns True if the sidecar was updated. Silent no-op when the sidecar
    does not exist or when no producer_warning_signature is recorded on the
    correction.
    """
    if not producer_warning_signature or not sidecar_path.exists():
        return False
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    entries = sidecar.setdefault("entries", {})
    entry_state = entries.setdefault(
        entry_id, {"warnings_acknowledged": [], "warnings_dismissed": []}
    )
    entry_state.setdefault("warnings_acknowledged", [])
    entry_state.setdefault("warnings_dismissed", [])
    acknowledged = entry_state["warnings_acknowledged"]
    if any(
        isinstance(w, dict) and w.get("signature") == producer_warning_signature
        for w in acknowledged
    ):
        return False
    # Per the warning_decision schema, producer + code + signature_version are
    # required alongside signature + reason. Derive what we can from the
    # producer_warning_signature; the rest comes from the correction context.
    producer = ""
    code = ""
    parts = producer_warning_signature.split(".", 2)
    if len(parts) >= 2:
        producer = parts[0]
        code = parts[1]
    acknowledged.append(
        {
            "producer": producer or "correction_applier",
            "code": code or "auto_acknowledged",
            "signature": producer_warning_signature,
            "signature_version": "1",
            "reason": "other",
            "note": "auto_acknowledged_by_correction_applier",
        }
    )
    # A-F2: validate the mutated sidecar against review_state.schema.json
    # before the os.replace lands, so a malformed acknowledge entry never
    # silently corrupts the on-disk sidecar.
    review_state_schema = json.loads(REVIEW_STATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    write_json_atomic(sidecar_path, sidecar, review_state_schema)
    return True


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _rewrite_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    schema = json.loads(LEDGER_SCHEMA_PATH.read_text(encoding="utf-8"))
    for entry in entries:
        validate_payload(entry, schema)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    if entries:
        body += "\n"
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def _find_entry(record: dict[str, Any], entry_id: str) -> dict[str, Any] | None:
    for entry in record.get("data", []):
        if entry.get("entry_id") == entry_id:
            return entry
    return None


def _ensure_layers(entry: dict[str, Any], text_layer_shape: str) -> dict[str, Any]:
    layers = entry.setdefault("layers", {})
    if text_layer_shape == "single_field":
        return layers
    return layers


def _apply_to_layer(
    entry: dict[str, Any],
    field_path: str,
    before_text: str,
    after_text: str,
    text_layer_shape: str,
) -> dict[str, str]:
    """Replace before_text with after_text inside layers.<field>.display.

    Substring replacement, first occurrence only. Raises ApplierError if
    before_text is not present in the current display value.
    """
    def ensure_unambiguous_match(current_display: str, field_name: str) -> None:
        occurrence_count = current_display.count(before_text)
        if occurrence_count == 0:
            raise ApplierError(
                f"before_text {before_text!r} not present in current display for "
                f"{field_name}; cannot apply correction"
            )
        if occurrence_count > 1:
            raise ApplierError(
                f"before_text {before_text!r} occurs {occurrence_count} times in "
                f"current display for {field_name}; cannot safely apply correction",
                code="ambiguous_before_text_match",
            )

    parts = field_path.split(".")
    head = parts[0]
    rest = parts[1:]
    layers = _ensure_layers(entry, text_layer_shape)
    if not rest:
        # single_field path like "commentary_text" OR multi_field top-level "term"
        existing = layers.get(head)
        structured = existing["structured"] if existing else entry.get(head, "")
        current_display = (existing or {}).get("display", structured)
        ensure_unambiguous_match(current_display, head)
        new_display = current_display.replace(before_text, after_text, 1)
        layer_entry = existing or {
            "source_raw": entry.get(head, ""),
            "normalised": entry.get(head, ""),
            "structured": structured,
            "display": structured,
            "source_raw_origin": "observed",
        }
        layer_entry["display"] = new_display
        layers[head] = layer_entry
        entry[head] = new_display
        return {"before_display": current_display, "after_display": new_display}
    # nested: e.g. definition_blocks.<block_id> or alt_terms.<idx>
    container = layers.setdefault(head, {})
    key = rest[0]
    existing = container.get(key)
    if existing is None:
        raise ApplierError(
            f"layer entry missing for {head}.{key}; cannot apply correction without parser-emitted source_raw"
        )
    current_display = existing.get("display", existing.get("structured", ""))
    ensure_unambiguous_match(current_display, f"{head}.{key}")
    new_display = current_display.replace(before_text, after_text, 1)
    existing["display"] = new_display
    # Mirror the layer change back to the surface array; the Phase C surface-
    # field invariant requires entry[head][idx] == layer.display.
    surface_idx = _surface_index_for_nested_key(entry, head, key, current_display)
    if surface_idx is not None:
        surface_list = entry.get(head)
        if isinstance(surface_list, list) and 0 <= surface_idx < len(surface_list):
            surface_list[surface_idx] = new_display
    return {"before_display": current_display, "after_display": new_display}


def _surface_index_for_nested_key(
    entry: dict[str, Any],
    head: str,
    key: str,
    current_display: str,
) -> int | None:
    """Resolve the surface-array index for a nested layer key.

    ``alt_terms.<idx>`` is keyed by stringified index. ``definition_blocks.
    <block_id>`` is keyed by content hash; resolve via the layer's stored
    display value matching the current surface value.
    """
    if head == "alt_terms":
        try:
            return int(key)
        except (TypeError, ValueError):
            return None
    surface_list = entry.get(head)
    if not isinstance(surface_list, list):
        return None
    for idx, value in enumerate(surface_list):
        if value == current_display:
            return idx
    return None


def apply_correction(
    *,
    resource_record_path: Path,
    correction: dict[str, Any],
    writer_manifest_out: Path,
    run_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply a single approved text correction. Returns the updated ledger entry."""
    if correction["status"] != "approved":
        raise ApplierError(
            f"correction {correction['correction_id']} is in status {correction['status']}, "
            "applier only consumes approved entries"
        )
    if correction.get("correction_type", "text") == "structural":
        # Deferred per Phase G scope; ledger entry stays at approved.
        raise StructuralCorrectionDeferred(
            f"correction {correction['correction_id']} has correction_type=structural; "
            "deferred per Phase G scope (text-only)"
        )

    record = json.loads(resource_record_path.read_text(encoding="utf-8"))
    before_sha = _sha256(resource_record_path.read_bytes())
    text_layer_shape = record.get("meta", {}).get("text_layer_shape", "single_field")

    entry = _find_entry(record, correction["entry_id"])
    if entry is None:
        raise ApplierError(
            f"entry_id {correction['entry_id']} not found in {resource_record_path}"
        )

    layer_change = _apply_to_layer(
        entry,
        correction["field_path"],
        correction["before_text"],
        correction["after_text"],
        text_layer_shape,
    )

    updated = {**correction}
    updated["status"] = "applied"
    updated["applied_at"] = _utc_now_iso()
    updated["applier_run_id"] = run_id

    if dry_run:
        updated["status"] = "would_apply"
        return updated

    new_body = json.dumps(record, indent=2, ensure_ascii=False) + "\n"
    after_sha = _sha256(new_body.encode("utf-8"))

    # Atomic write: tmp + replace.
    tmp = resource_record_path.with_suffix(resource_record_path.suffix + ".tmp")
    tmp.write_text(new_body, encoding="utf-8")
    os.replace(tmp, resource_record_path)

    # Emit writer manifest
    manifest = {
        "schema_version": "1.0.0",
        "writer": "applier",
        "writer_version": "build/tools/apply_correction.py@v1.0.0",
        "writer_identity": WRITER_IDENTITY,
        "run_id": run_id,
        "started_at": _utc_now_iso(),
        "data_paths": [resource_record_path.as_posix().replace(REPO_ROOT.as_posix() + "/", "")
                       if resource_record_path.is_absolute()
                       else resource_record_path.as_posix()],
        "checksums": {
            (resource_record_path.as_posix().replace(REPO_ROOT.as_posix() + "/", "")
             if resource_record_path.is_absolute()
             else resource_record_path.as_posix()): {
                "before_sha256": before_sha,
                "after_sha256": after_sha,
            }
        },
        "expected_delta_counts": {
            (resource_record_path.as_posix().replace(REPO_ROOT.as_posix() + "/", "")
             if resource_record_path.is_absolute()
             else resource_record_path.as_posix()): {
                "entries_changed": 1,
                "fields_changed": 1,
            }
        },
        "allowed_field_paths": [
            f"/data/*/layers/{correction['field_path'].replace('.', '/')}/display",
        ],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }
    writer_manifest_out.parent.mkdir(parents=True, exist_ok=True)
    schema = json.loads(WRITER_MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    validate_payload(manifest, schema)
    writer_manifest_out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Audit event
    audit_event = {
        "schema_version": "1.0.0",
        "event_type": "correction_applied",
        "timestamp_utc": _utc_now_iso(),
        "actor": WRITER_IDENTITY,
        "resource_id": correction["resource_id"],
        "record_path": correction["record_path"],
        "entry_id": correction["entry_id"],
        "field_path": correction["field_path"],
        "correction_id": correction["correction_id"],
        "writer_manifest_run_id": run_id,
        "manifest_checksum_sha256": _sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")),
        "decision_reason": "applied",
        "note": (
            f"before={correction['before_text']!r} -> after={correction['after_text']!r}"
        ),
    }
    audit_schema = json.loads(AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    audit_path = REPO_ROOT / "review" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        append_jsonl_atomic(audit_path, audit_event, audit_schema)
    except AtomicWriteError as exc:
        logging.warning(
            "Atomic audit append failed for %s; falling back to direct append: %s",
            audit_path,
            exc,
        )
        validate_payload(audit_event, audit_schema)
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(audit_event, ensure_ascii=False) + "\n")

    # Auto-acknowledge the originating sidecar warning, if any.
    sidecar_path = _sidecar_path_for(correction["record_path"])
    _auto_acknowledge_warning(
        sidecar_path,
        entry_id=correction["entry_id"],
        producer_warning_signature=correction.get("producer_warning_signature"),
    )

    return updated


def apply_pending_corrections(
    *,
    ledger_path: Path,
    resource_record_path: Path,
    writer_manifest_out: Path,
    correction_id: str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    entries = _load_jsonl(ledger_path)
    if not entries:
        return []
    run_id = uuid.uuid4().hex
    updated_entries: list[dict[str, Any]] = []
    applied_changes: list[dict[str, Any]] = []
    for entry in entries:
        if correction_id is not None and entry.get("correction_id") != correction_id:
            updated_entries.append(entry)
            continue
        if entry.get("status") != "approved":
            updated_entries.append(entry)
            continue
        if entry.get("correction_type", "text") == "structural":
            entry = {**entry, "applier_deferred_reason": "structural_deferred"}
            updated_entries.append(entry)
            continue
        try:
            new_entry = apply_correction(
                resource_record_path=resource_record_path,
                correction=entry,
                writer_manifest_out=writer_manifest_out,
                run_id=run_id,
                dry_run=dry_run,
            )
            updated_entries.append(new_entry)
            applied_changes.append(new_entry)
        except StructuralCorrectionDeferred as exc:
            entry = {**entry, "applier_deferred_reason": exc.applier_deferred_reason}
            updated_entries.append(entry)
        except ApplierError as exc:
            # before_text not present, layer entry missing, etc. Leave the
            # ledger entry in approved status with a deferred reason and
            # surface for human review. Do not crash the run.
            entry = {**entry, "applier_deferred_reason": f"applier_skipped: {exc}"}
            updated_entries.append(entry)
    if not dry_run and applied_changes:
        _rewrite_jsonl(ledger_path, updated_entries)
    return applied_changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--writer-manifest-out", required=True, type=Path)
    parser.add_argument("--correction-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    applied = apply_pending_corrections(
        ledger_path=args.ledger,
        resource_record_path=args.resource,
        writer_manifest_out=args.writer_manifest_out,
        correction_id=args.correction_id,
        dry_run=args.dry_run,
    )
    print(json.dumps({"applied_count": len(applied), "applied": applied}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
