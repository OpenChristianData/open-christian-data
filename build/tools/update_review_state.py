"""Writer CLI for sidecar review state.

Subcommands:

* ``acknowledge``       record an entry's warning as confirmed/expected/etc.
* ``dismiss``           record an entry's warning as dismissed.
* ``set-confidence-axis`` set one of the three confidence axes on the sidecar.

All writes go through ``build.lib.atomic_io.write_json_atomic`` and are
validated against the current ``review_state.schema.json`` before
``os.replace``. Sidecars whose ``schema_version`` is older than the current
writer schema are refused with ``sidecar_schema_too_old`` and a pointer to
``python -m build.tools.migrate_sidecars <path>``. Each successful invocation
appends one event to ``review/audit.jsonl`` via the atomic-IO line-validated
appender.

The CLI never touches ``data/``; the pre-commit gate's writer-manifest rules
are out of scope here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib import review_state, sidecar_migrations  # noqa: E402
from build.lib.atomic_io import (  # noqa: E402
    SchemaValidationError,
    append_jsonl_atomic,
)
from build.lib.paths import REPO_ROOT  # noqa: E402


AUDIT_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "audit_event.schema.json"
REVIEW_STATE_SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "review_state.schema.json"


CONFIDENCE_AXES = ("structural_fidelity", "text_fidelity", "edition_provenance")
CONFIDENCE_TIERS = (
    "unverified",
    "machine-checked",
    "witness-compared",
    "human-reviewed",
    "reference-grade",
)
DECISION_REASONS = ("confirmed", "expected", "false_positive", "wont_fix", "other")


class SidecarSchemaTooOld(Exception):
    """Raised when a sidecar's schema_version is older than the writer's."""


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _resolve_sidecar_path(record_path: Path, repo_root: Path) -> Path:
    if "data" not in record_path.parts:
        raise SystemExit(
            f"record path {record_path} is not under data/; pass the canonical record path"
        )
    return review_state.derive_sidecar_path(record_path, repo_root=repo_root)


def _resource_id_of_record(record_path: Path) -> str:
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    meta = payload.get("meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        raise SystemExit(f"record {record_path} has no meta object")
    rid = meta.get("id")
    if not isinstance(rid, str) or not rid:
        raise SystemExit(f"record {record_path} has no meta.id")
    return rid


def _record_checksum(record_path: Path) -> str:
    return hashlib.sha256(record_path.read_bytes()).hexdigest()


def _load_or_init_sidecar(
    *,
    record_path: Path,
    sidecar_path: Path,
    repo_root: Path,
    parser_version_seen: str | None,
) -> dict:
    if sidecar_path.exists():
        on_disk = json.loads(sidecar_path.read_text(encoding="utf-8"))
        version = on_disk.get("schema_version")
        if version != sidecar_migrations.CURRENT_VERSION:
            raise SidecarSchemaTooOld(
                f"sidecar at {sidecar_path} declares schema_version {version!r} "
                f"but writer requires {sidecar_migrations.CURRENT_VERSION!r}. "
                f"Run: python -m build.tools.migrate_sidecars {sidecar_path}"
            )
        # Re-validate before returning so a tampered file is caught here, not
        # silently after we mutate in memory.
        return review_state.load_sidecar(sidecar_path)
    if parser_version_seen is None:
        parser_version_seen = "unknown@unknown"
    return review_state.empty_sidecar(
        record_path=str(record_path.relative_to(repo_root)).replace("\\", "/"),
        record_resource_id=_resource_id_of_record(record_path),
        record_checksum_sha256=_record_checksum(record_path),
        parser_version_seen=parser_version_seen,
    )


def _ensure_entry(sidecar: dict, entry_id: str) -> dict:
    entry = sidecar["entries"].get(entry_id)
    if entry is None:
        entry = {"warnings_acknowledged": [], "warnings_dismissed": []}
        sidecar["entries"][entry_id] = entry
    return entry


def _record_decision(
    *,
    sidecar: dict,
    entry_id: str,
    bucket: str,  # "warnings_acknowledged" | "warnings_dismissed"
    decision: dict,
    reviewer: str,
) -> None:
    entry = _ensure_entry(sidecar, entry_id)
    # Idempotency: replace existing decision with the same (producer, code, signature).
    sig_key = (decision["producer"], decision["code"], decision["signature"])
    entry[bucket] = [
        d
        for d in entry[bucket]
        if (d.get("producer"), d.get("code"), d.get("signature")) != sig_key
    ]
    entry[bucket].append(decision)
    # Remove the same signature from the opposite bucket so a dismiss after an
    # acknowledge (or vice versa) reflects the latest decision.
    other = "warnings_dismissed" if bucket == "warnings_acknowledged" else "warnings_acknowledged"
    entry[other] = [
        d
        for d in entry.get(other, [])
        if (d.get("producer"), d.get("code"), d.get("signature")) != sig_key
    ]
    entry["last_reviewed_at"] = _utc_now_iso()
    entry["last_reviewer"] = reviewer


def _emit_audit(
    *,
    event_type: str,
    repo_root: Path,
    payload: dict,
) -> None:
    audit_path = repo_root / "review" / "audit.jsonl"
    schema = json.loads(AUDIT_SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = {"schema_version": "1.0.0", "event_type": event_type, **payload}
    append_jsonl_atomic(audit_path, payload, schema)


def _cmd_decision(args: argparse.Namespace, *, bucket: str, event_type: str) -> int:
    repo_root = Path(args.repo_root).resolve()
    record_path = Path(args.record).resolve()
    sidecar_path = _resolve_sidecar_path(record_path, repo_root)
    try:
        sidecar = _load_or_init_sidecar(
            record_path=record_path,
            sidecar_path=sidecar_path,
            repo_root=repo_root,
            parser_version_seen=args.parser_version,
        )
    except SidecarSchemaTooOld as exc:
        print(f"sidecar_schema_too_old: {exc}", file=sys.stderr)
        return 3

    decision = {
        "producer": args.producer,
        "code": args.code,
        "signature": args.signature,
        "signature_version": args.signature_version,
        "reason": args.reason,
    }
    if args.note:
        decision["note"] = args.note

    _record_decision(
        sidecar=sidecar,
        entry_id=args.entry,
        bucket=bucket,
        decision=decision,
        reviewer=args.reviewer,
    )

    try:
        review_state.save_sidecar(sidecar_path, sidecar)
    except SchemaValidationError as exc:
        print(f"sidecar validation failed; nothing written: {exc}", file=sys.stderr)
        return 4

    audit_payload = {
        "timestamp_utc": _utc_now_iso(),
        "actor": args.reviewer,
        "resource_id": sidecar["record_resource_id"],
        "record_path": sidecar["record_path"],
        "entry_id": args.entry,
        "warning_producer": args.producer,
        "warning_code": args.code,
        "warning_signature": args.signature,
        "decision_reason": args.reason,
    }
    if args.note:
        audit_payload["note"] = args.note
    _emit_audit(event_type=event_type, repo_root=repo_root, payload=audit_payload)
    print(
        f"{event_type}: {args.producer}/{args.code} on {args.entry} (sidecar={sidecar_path})"
    )
    return 0


def _cmd_acknowledge(args: argparse.Namespace) -> int:
    return _cmd_decision(args, bucket="warnings_acknowledged", event_type="acknowledge")


def _cmd_dismiss(args: argparse.Namespace) -> int:
    return _cmd_decision(args, bucket="warnings_dismissed", event_type="dismiss")


def _cmd_set_confidence_axis(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    record_path = Path(args.record).resolve()
    sidecar_path = _resolve_sidecar_path(record_path, repo_root)
    try:
        sidecar = _load_or_init_sidecar(
            record_path=record_path,
            sidecar_path=sidecar_path,
            repo_root=repo_root,
            parser_version_seen=args.parser_version,
        )
    except SidecarSchemaTooOld as exc:
        print(f"sidecar_schema_too_old: {exc}", file=sys.stderr)
        return 3

    if args.tier == "reference-grade" and not args.promote:
        print(
            "reference-grade requires --promote (the explicit promotion flag).",
            file=sys.stderr,
        )
        return 5

    sidecar["confidence"][args.axis] = args.tier
    try:
        review_state.save_sidecar(sidecar_path, sidecar)
    except SchemaValidationError as exc:
        print(f"sidecar validation failed; nothing written: {exc}", file=sys.stderr)
        return 4

    audit_payload = {
        "timestamp_utc": _utc_now_iso(),
        "actor": args.reviewer,
        "resource_id": sidecar["record_resource_id"],
        "record_path": sidecar["record_path"],
        "confidence_axis": args.axis,
        "confidence_tier": args.tier,
        "promote_explicit": bool(args.promote),
    }
    _emit_audit(
        event_type="set_confidence_axis",
        repo_root=repo_root,
        payload=audit_payload,
    )
    print(f"set_confidence_axis: {args.axis}={args.tier} (sidecar={sidecar_path})")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m build.tools.update_review_state",
        description="Writer CLI for sidecar review state.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (defaults to the OCD repo containing this script).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_decision_args(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--record", type=Path, required=True, help="Path to data/<record>.json")
        sp.add_argument("--entry", required=True, help="entry_id within the record")
        sp.add_argument("--producer", required=True)
        sp.add_argument("--code", required=True)
        sp.add_argument("--signature", required=True)
        sp.add_argument("--signature-version", default="v1.0.0")
        sp.add_argument(
            "--reason",
            choices=DECISION_REASONS,
            required=True,
        )
        sp.add_argument("--note", default=None)
        sp.add_argument("--reviewer", required=True)
        sp.add_argument(
            "--parser-version",
            default=None,
            help="Optional 'build/parsers/<name>.py@<version>' tag for new sidecars.",
        )

    ack = sub.add_parser("acknowledge", help="Acknowledge a warning on an entry.")
    _add_decision_args(ack)
    ack.set_defaults(func=_cmd_acknowledge)

    dis = sub.add_parser("dismiss", help="Dismiss a warning on an entry.")
    _add_decision_args(dis)
    dis.set_defaults(func=_cmd_dismiss)

    sca = sub.add_parser(
        "set-confidence-axis",
        help="Set one of the three confidence axes on a record's sidecar.",
    )
    sca.add_argument("--record", type=Path, required=True)
    sca.add_argument("--axis", choices=CONFIDENCE_AXES, required=True)
    sca.add_argument("--tier", choices=CONFIDENCE_TIERS, required=True)
    sca.add_argument("--reviewer", required=True)
    sca.add_argument(
        "--parser-version",
        default=None,
        help="Optional parser-version tag for new sidecars.",
    )
    sca.add_argument(
        "--promote",
        action="store_true",
        help="Required explicit flag when setting tier='reference-grade'.",
    )
    sca.set_defaults(func=_cmd_set_confidence_axis)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
