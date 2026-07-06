"""Batch dismiss / acknowledge operations on review sidecars.

Bulk dismiss/acknowledge N warnings matched by code/producer/query in one
command. Emits one audit record per batch (event_type=bulk_dismissed or
bulk_acknowledged) covering all affected signatures.

Defaults to --dry-run; --confirm is required to actually write.

CLI:
    py -3 build/tools/bulk_review_writer.py dismiss \
        --resource data/reference/schaff-herzog-encyclopedia.json \
        --by-code possible_broken_hyphenation --reason wont_fix \
        --confirm

    py -3 build/tools/bulk_review_writer.py acknowledge \
        --resource data/commentaries/adam-clarke/2-john.json \
        --by-producer historical_lexicon --reason expected \
        --confirm
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.paths import REPO_ROOT  # noqa: E402
_SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"

from build.lib.atomic_io import (  # noqa: E402
    AtomicWriteError,
    append_jsonl_atomic,
    validate_payload,
    write_json_atomic,
)
from build.lib._generated_enums import REVIEW_STATE__DEFS__WARNING_DECISION__REASON  # noqa: E402

REVIEW_STATE_SCHEMA_PATH = _SCHEMAS_DIR / "review_state.schema.json"

# A-F3: sourced from review_state.schema.json via the generated enum constant
# so it cannot drift from the schema. Previously a hardcoded frozenset,
# violating AGENTS.md "Schema enums: Never hardcode frozensets".
ALLOWED_REASONS = REVIEW_STATE__DEFS__WARNING_DECISION__REASON


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _sidecar_path(record_path: Path) -> Path:
    rel = Path(record_path)
    if rel.is_absolute():
        # Find the first "data" segment
        parts = rel.parts
        try:
            idx = parts.index("data")
        except ValueError:
            return REPO_ROOT / "review" / "state" / Path(rel.name)
        rel = Path(*parts[idx + 1:])
    elif rel.parts and rel.parts[0] == "data":
        rel = Path(*rel.parts[1:])
    return REPO_ROOT / "review" / "state" / rel


def _warnings_from_producers(record_path: Path) -> list[dict[str, Any]]:
    """Run the producer registry over the record to get the current warning
    set. The bulk writer matches by producer + code + signature; without
    running producers we'd only know about warnings already in the sidecar."""
    from build.lib.warning_producers import discover_producers, run_all_producers  # noqa: WPS433
    from build.lib.text_extractor import effective_resource_type  # noqa: WPS433

    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    rtype = effective_resource_type(record, REPO_ROOT / "schemas" / "v1")
    meta = {
        "resource_id": record["meta"]["id"],
        "resource_type": rtype,
        "record_path": Path(record_path).as_posix(),
    }
    results = run_all_producers(record, meta, producers=discover_producers())
    warnings: list[dict[str, Any]] = []
    for producer_id, ws in results.items():
        for w in ws:
            w_copy = dict(w)
            w_copy.setdefault("producer", producer_id)
            warnings.append(w_copy)
    return warnings


def _match_predicate(
    *,
    by_code: str | None,
    by_producer: str | None,
    by_query: str | None,
) -> Callable[[dict[str, Any]], bool]:
    def predicate(w: dict[str, Any]) -> bool:
        if by_code is not None and w.get("code") != by_code:
            return False
        if by_producer is not None and w.get("producer") != by_producer:
            return False
        if by_query is not None:
            text = " ".join(
                str(v)
                for v in (
                    w.get("entry_id"),
                    w.get("message"),
                    (w.get("evidence") or {}).get("surface"),
                    w.get("field_path"),
                )
                if v
            )
            if by_query.lower() not in text.lower():
                return False
        return True

    return predicate


def _load_sidecar(sidecar_path: Path, record_path: Path | None = None) -> dict[str, Any]:
    """Load an existing sidecar or build a fresh schema-conforming one.

    A-F4: fresh sidecars must satisfy the full review_state schema so the
    schema-validated atomic write in _write_sidecar succeeds.
    """
    if sidecar_path.exists():
        return json.loads(sidecar_path.read_text(encoding="utf-8"))
    from build.lib import review_state  # noqa: WPS433

    record_path_str = ""
    record_resource_id = ""
    record_checksum = "0" * 64
    parser_version = "unknown"
    if record_path is not None and Path(record_path).exists():
        rec = Path(record_path)
        record_path_str = rec.as_posix()
        try:
            record_bytes = rec.read_bytes()
            import hashlib
            record_checksum = hashlib.sha256(record_bytes).hexdigest()
            record = json.loads(record_bytes.decode("utf-8"))
            record_resource_id = str((record.get("meta") or {}).get("id") or "")
            parser_version = str(
                (record.get("meta") or {}).get("provenance", {}).get("processing_method") or "unknown"
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass
    return review_state.empty_sidecar(
        record_path=record_path_str,
        record_resource_id=record_resource_id,
        record_checksum_sha256=record_checksum,
        parser_version_seen=parser_version,
    )


def _write_sidecar(sidecar_path: Path, body: dict[str, Any]) -> None:
    """A-F4: validate against review_state.schema.json before os.replace so
    bulk operations cannot silently land a malformed sidecar at scale.
    """
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    review_state_schema = json.loads(REVIEW_STATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    write_json_atomic(sidecar_path, body, review_state_schema)


def _decision_record(warning: dict[str, Any], reason: str, note: str | None) -> dict[str, Any]:
    rec = {
        "producer": warning.get("producer", "unknown"),
        "code": warning.get("code", "unknown"),
        "signature": warning.get("signature", ""),
        "signature_version": str(warning.get("signature_version", "1")),
        "reason": reason,
    }
    if note:
        rec["note"] = note
    return rec


def _append_audit_event(
    *,
    record_path: Path,
    resource_id: str,
    event_type: str,
    affected: list[dict[str, Any]],
    reason: str,
) -> None:
    audit_schema = json.loads(
        (_SCHEMAS_DIR / "audit_event.schema.json").read_text(encoding="utf-8")
    )
    audit_path = REPO_ROOT / "review" / "audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "timestamp_utc": _utc_now_iso(),
        "actor": "bulk_review_writer",
        "resource_id": resource_id,
        "record_path": Path(record_path).as_posix(),
        "decision_reason": reason,
        "counts": {"affected": len(affected)},
        "note": f"bulk {event_type} via bulk_review_writer ({len(affected)} signatures)",
    }
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


def bulk_dismiss(
    *,
    record_path: Path,
    by_code: str | None = None,
    by_producer: str | None = None,
    by_query: str | None = None,
    reason: str = "wont_fix",
    note: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    return _bulk_apply(
        record_path=record_path,
        by_code=by_code,
        by_producer=by_producer,
        by_query=by_query,
        reason=reason,
        note=note,
        confirm=confirm,
        action="dismiss",
    )


def bulk_acknowledge(
    *,
    record_path: Path,
    by_code: str | None = None,
    by_producer: str | None = None,
    by_query: str | None = None,
    reason: str = "confirmed",
    note: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    return _bulk_apply(
        record_path=record_path,
        by_code=by_code,
        by_producer=by_producer,
        by_query=by_query,
        reason=reason,
        note=note,
        confirm=confirm,
        action="acknowledge",
    )


def _bulk_apply(
    *,
    record_path: Path,
    by_code: str | None,
    by_producer: str | None,
    by_query: str | None,
    reason: str,
    note: str | None,
    confirm: bool,
    action: str,
    warnings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record_path = Path(record_path)
    if warnings is None:
        warnings = _warnings_from_producers(record_path)
    predicate = _match_predicate(by_code=by_code, by_producer=by_producer, by_query=by_query)
    matched = [w for w in warnings if predicate(w)]
    if not matched:
        return {"action": action, "matched": 0, "written": False, "dry_run": not confirm}

    if not confirm:
        return {
            "action": action,
            "matched": len(matched),
            "written": False,
            "dry_run": True,
            "preview": [
                {
                    "entry_id": w.get("entry_id"),
                    "code": w.get("code"),
                    "signature": w.get("signature"),
                }
                for w in matched[:10]
            ],
        }

    # Apply: load sidecar, append decisions
    sidecar_path = _sidecar_path(record_path)
    sidecar = _load_sidecar(sidecar_path, record_path)
    sidecar.setdefault("entries", {})
    target_key = "warnings_dismissed" if action == "dismiss" else "warnings_acknowledged"
    for w in matched:
        entry_id = w.get("entry_id", "unknown")
        entry_state = sidecar["entries"].setdefault(
            entry_id, {"warnings_acknowledged": [], "warnings_dismissed": []}
        )
        entry_state.setdefault("warnings_acknowledged", [])
        entry_state.setdefault("warnings_dismissed", [])
        entry_state[target_key].append(_decision_record(w, reason, note))
    _write_sidecar(sidecar_path, sidecar)

    # Audit
    record_data = json.loads(record_path.read_text(encoding="utf-8"))
    resource_id = record_data.get("meta", {}).get("id", record_path.stem)
    _append_audit_event(
        record_path=record_path,
        resource_id=resource_id,
        event_type="bulk_dismissed" if action == "dismiss" else "bulk_acknowledged",
        affected=matched,
        reason=reason,
    )
    return {"action": action, "matched": len(matched), "written": True, "dry_run": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    for cmd in ("dismiss", "acknowledge"):
        sub = subparsers.add_parser(cmd)
        sub.add_argument("--resource", required=True, type=Path)
        sub.add_argument("--by-code", default=None)
        sub.add_argument("--by-producer", default=None)
        sub.add_argument("--by-query", default=None)
        sub.add_argument(
            "--reason",
            default="wont_fix" if cmd == "dismiss" else "confirmed",
            choices=tuple(sorted(ALLOWED_REASONS)),
        )
        sub.add_argument("--note", default=None)
        sub.add_argument("--confirm", action="store_true")
    args = parser.parse_args(argv)
    fn = bulk_dismiss if args.cmd == "dismiss" else bulk_acknowledge
    result = fn(
        record_path=args.resource,
        by_code=args.by_code,
        by_producer=args.by_producer,
        by_query=args.by_query,
        reason=args.reason,
        note=args.note,
        confirm=args.confirm,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
