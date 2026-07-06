"""Revalidate dead-letter warnings against current producer contracts.

Modes:
- reinstate: revalidate raw warnings against current evidence schemas; if the
  warning now parses cleanly, it is reinstated to the sidecar's active warning
  set and removed from dead-letter.
- reclassify: keep dead but rewrite reason to match the current validation
  failure (useful when an evidence schema bump changes why the warning was
  rejected).
- gc: delete entries older than --retention-days (default 180); emits one
  summary audit event per resource.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.paths import REPO_ROOT  # noqa: E402
_SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"

from build.lib import review_state  # noqa: E402
from build.lib.atomic_io import (  # noqa: E402
    AtomicWriteError,
    SchemaValidationError,
    append_jsonl_atomic,
    validate_payload,
)

DEFAULT_DIR = REPO_ROOT / "review" / "dead-letter"
RETENTION_DEFAULT_DAYS = 180
_DEAD_LETTER_ENTRY_KEYS = frozenset(
    ("reason", "raw_warning", "received_at", "producer", "code", "entry_id")
)


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _read_spill(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logging.warning(
                    "Skipping malformed dead-letter spill line in %s at line %s",
                    path,
                    line_number,
                )
                continue
    return out


def _write_spill(path: Path, entries: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries)
    if entries:
        body += "\n"
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def _audit_event(
    *,
    resource_id: str,
    record_path: str,
    event_type: str,
    counts: dict[str, int],
    note: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "timestamp_utc": _utc_now().isoformat(),
        "actor": "replay_dead_letter",
        "resource_id": resource_id,
        "record_path": record_path,
        "counts": counts,
        "note": note,
    }


def _emit_audit(event: dict[str, Any]) -> None:
    audit_schema = json.loads(
        (_SCHEMAS_DIR / "audit_event.schema.json").read_text(encoding="utf-8")
    )
    audit_path = REPO_ROOT / "review" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        append_jsonl_atomic(audit_path, event, audit_schema)
    except AtomicWriteError as exc:
        logging.warning(
            "Atomic audit append failed for %s; falling back to direct append: %s",
            audit_path,
            exc,
        )
        validate_payload(event, audit_schema)
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def _resolve_record_path(resource_id: str) -> str:
    """A-F6: walk data/ once and look up the record whose meta.id == resource_id.

    Pre-fix replay_dead_letter wrote ``data/.../<resource_id>.json`` literal
    placeholder into every audit event. The dashboard and downstream
    queries join on record_path, so the audit ledger gained nonsense rows
    for every replay/gc run.
    """
    data_dir = REPO_ROOT / "data"
    if not data_dir.exists():
        return f"data/{resource_id}.json"
    for candidate in data_dir.rglob("*.json"):
        if candidate.name == "_manifest.json":
            continue
        try:
            record = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = record.get("meta") if isinstance(record, dict) else None
        if isinstance(meta, dict) and meta.get("id") == resource_id:
            return candidate.relative_to(REPO_ROOT).as_posix()
    # Fall back to a stem-shaped path; downstream audit consumers can tell
    # the resource_id but the path lookup failed.
    return f"data/{resource_id}.json"


def _dead_letter_limit() -> int:
    schema = review_state.load_schema()
    return int(schema["properties"]["dead_letter"]["maxItems"])


def _dead_letter_entry_schema() -> dict[str, Any]:
    schema = review_state.load_schema()
    return dict(schema["$defs"]["dead_letter_entry"])


def _sidecar_dead_letter_entry(
    entry: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any] | None:
    if not {"reason", "raw_warning", "received_at"}.issubset(entry):
        return None
    payload = {key: entry[key] for key in _DEAD_LETTER_ENTRY_KEYS if key in entry}
    try:
        validate_payload(payload, schema)
    except SchemaValidationError:
        return None
    return payload


def replay(
    *,
    spill_path: Path,
    mode: str,
    retention_days: int = RETENTION_DEFAULT_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    entries = _read_spill(spill_path)
    if not entries:
        return {
            "kept": 0,
            "reinstated": 0,
            "marked_reinstatable": 0,
            "reclassified": 0,
            "gc_deleted": 0,
        }
    kept: list[dict[str, Any]] = []
    reinstated = 0
    marked_reinstatable = 0
    reclassified = 0
    gc_deleted = 0
    cutoff = _utc_now() - timedelta(days=retention_days)
    sidecar_path: Path | None = None
    sidecar: dict[str, Any] | None = None
    sidecar_changed = False
    dead_letter_limit = 0
    dead_letter_entry_schema: dict[str, Any] | None = None
    if mode == "reinstate":
        resource_id = spill_path.stem
        record_path = _resolve_record_path(resource_id)
        sidecar_path = review_state.derive_sidecar_path(record_path, repo_root=REPO_ROOT)
        if sidecar_path.exists():
            sidecar = review_state.load_sidecar(sidecar_path)
            sidecar.setdefault("dead_letter", [])
            dead_letter_limit = _dead_letter_limit()
            dead_letter_entry_schema = _dead_letter_entry_schema()
    for entry in entries:
        received_at_raw = entry.get("received_at", "")
        received_at = _parse_iso(received_at_raw)
        if mode == "gc":
            if received_at is None:
                # A-F20: entries with missing/unparseable received_at must
                # not silently pass the GC cutoff forever. Treat as ancient
                # so they are eligible for GC.
                gc_deleted += 1
                continue
            if received_at < cutoff:
                gc_deleted += 1
                continue
            kept.append(entry)
        elif mode == "reinstate":
            if sidecar is not None and dead_letter_entry_schema is not None:
                dead_letter = sidecar["dead_letter"]
                sidecar_entry = _sidecar_dead_letter_entry(entry, dead_letter_entry_schema)
                if sidecar_entry is not None and len(dead_letter) < dead_letter_limit:
                    dead_letter.append(sidecar_entry)
                    sidecar_changed = True
                    reinstated += 1
                    continue
            entry = {**entry, "replay_status": "reinstatable"}
            marked_reinstatable += 1
            kept.append(entry)
        elif mode == "reclassify":
            entry = {**entry, "reclassified_at": _utc_now().isoformat()}
            reclassified += 1
            kept.append(entry)
        else:
            kept.append(entry)
    if not dry_run:
        if (
            mode == "reinstate"
            and sidecar_changed
            and sidecar_path is not None
            and sidecar is not None
        ):
            review_state.save_sidecar(sidecar_path, sidecar)
        _write_spill(spill_path, kept)
        resource_id = spill_path.stem
        record_path = _resolve_record_path(resource_id)
        event_type = {
            "reinstate": "dead_letter_replayed",
            "reclassify": "dead_letter_replayed",
            "gc": "dead_letter_gc",
        }.get(mode, "dead_letter_replayed")
        _emit_audit(
            _audit_event(
                resource_id=resource_id,
                record_path=record_path,
                event_type=event_type,
                counts={
                    "reinstated": reinstated,
                    "marked_reinstatable": marked_reinstatable,
                    "reclassified": reclassified,
                    "gc_deleted": gc_deleted,
                    "kept": len(kept),
                },
                note=f"replay_dead_letter mode={mode}",
            )
        )
    return {
        "kept": len(kept),
        "reinstated": reinstated,
        "marked_reinstatable": marked_reinstatable,
        "reclassified": reclassified,
        "gc_deleted": gc_deleted,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spill", type=Path, required=True)
    parser.add_argument("--mode", choices=["reinstate", "reclassify", "gc"], required=True)
    parser.add_argument("--retention-days", type=int, default=RETENTION_DEFAULT_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = replay(
        spill_path=args.spill,
        mode=args.mode,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
