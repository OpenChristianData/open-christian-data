"""Kernel-safe warning producer helpers and shared producers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

WARNING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "severity": {"type": "string"},
                    "entry_id": {"type": ["string", "null"]},
                    "field_path": {"type": ["string", "null"]},
                    "message": {"type": "string"},
                    "evidence": {"type": ["object", "null"]},
                    "signature": {"type": "string"},
                    "ephemeral": {"type": "boolean"},
                },
                "required": [
                    "code",
                    "severity",
                    "entry_id",
                    "field_path",
                    "message",
                    "evidence",
                    "signature",
                    "ephemeral",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["warnings"],
    "additionalProperties": False,
}


def build_warning(
    producer: Any,
    code: str,
    *,
    entry_id: str | None,
    field_path: str | None,
    message: str,
    evidence: dict[str, Any] | None = None,
    signature_values: Mapping[str, Any] | None = None,
    ephemeral: bool = False,
) -> dict[str, Any]:
    """Build a canonical producer warning with a stable signature."""
    code_contract = producer.WARNING_CODES[code]
    values: dict[str, Any] = {
        "code": code,
        "entry_id": entry_id,
        "field_path": field_path,
        "resource_id": None,
        "entry_index": None,
        "surface": None,
        "normalised": None,
        "declared_type": None,
        "schema_default": None,
    }
    if evidence:
        values.update(evidence)
    if signature_values:
        values.update(signature_values)
    signature = warning_signature(code_contract["signature_fields"], values)
    return {
        "code": code,
        "severity": code_contract["severity"],
        "entry_id": entry_id,
        "field_path": field_path,
        "message": message,
        "evidence": evidence,
        "signature": signature,
        "ephemeral": ephemeral,
    }


def warning_signature(signature_fields: Iterable[str], values: Mapping[str, Any]) -> str:
    pairs = sorted((field, values[field]) for field in signature_fields)
    payload = json.dumps(pairs, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:16]
