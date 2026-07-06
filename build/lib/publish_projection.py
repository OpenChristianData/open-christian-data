from __future__ import annotations

import json, hashlib, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.atomic_io import write_json_atomic

AUDIT_ONLY_FIELDS = {
    "attestations",
    "evidence",
    "output_status",
    "internal_id",
    "internal_ids",
    "source_token_id",
    "observation_token_id",
    "span_record_id",
    "audit_trail",
}

_PUBLIC_FIELDS = {
    "record_id",
    "canonical_text",
    "title",
    "work_id",
    "volume",
    "page",
    "section",
    "metadata",
}


def _canonical_hash(obj: dict) -> str:
    blob = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_audit_artifact(records: list[dict]) -> dict:
    copied = [dict(record) for record in records]
    artifact = {
        "artifact_type": "s6-audit-private",
        "records": copied,
    }
    artifact["artifact_hash"] = _canonical_hash({"records": copied})
    return artifact


def build_slim_config(records: list[dict]) -> dict:
    slim_records = []
    for record in records:
        slim_record = {
            key: value
            for key, value in record.items()
            if key in _PUBLIC_FIELDS and key not in AUDIT_ONLY_FIELDS
        }
        slim_records.append(slim_record)
    slim = {
        "artifact_type": "s6-slim-public",
        "records": slim_records,
    }
    leaks = slim_leaks_audit_fields(slim)
    if leaks:
        raise ValueError(f"audit-only fields leaked into slim config: {leaks}")
    slim["artifact_hash"] = _canonical_hash({"records": slim_records})
    return slim


def slim_leaks_audit_fields(slim) -> list[str]:
    leaks: list[str] = []

    def visit(value) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in AUDIT_ONLY_FIELDS:
                    leaks.append(key)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(slim)
    return sorted(set(leaks))


__all__ = [
    "AUDIT_ONLY_FIELDS",
    "build_audit_artifact",
    "build_slim_config",
    "slim_leaks_audit_fields",
]
