"""paired_with reference-resolution warning producer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "paired_with_reference_resolution"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "PAIRED_WITH_REFERENCE_UNRESOLVED": {
        "severity": "error",
        "description": "A paired_with reference is missing or not reciprocal.",
        "signature_fields": ["code", "resource_id", "paired_with"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    paired_with = record.get("meta", {}).get("paired_with")
    if not isinstance(paired_with, str) or not paired_with:
        return {"warnings": []}
    paired_path = Path(paired_with)
    record_path = str(meta.get("record_path") or record.get("meta", {}).get("record_path") or "")
    if not paired_path.exists():
        return {"warnings": [_warning(meta, paired_with, "paired record file does not exist")]}
    try:
        sibling = json.loads(paired_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"warnings": [_warning(meta, paired_with, "paired record file is not valid JSON")]}
    sibling_paired_with = sibling.get("meta", {}).get("paired_with")
    if record_path and sibling_paired_with != record_path:
        return {"warnings": [_warning(meta, paired_with, "paired record does not point back to this record")]}
    return {"warnings": []}


def _warning(meta: dict, paired_with: str, reason: str) -> dict[str, Any]:
    resource_id = meta.get("resource_id")
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code="PAIRED_WITH_REFERENCE_UNRESOLVED",
        entry_id=None,
        field_path="meta.paired_with",
        message=f"paired_with reference is unresolved: {reason}.",
        evidence={"resource_id": resource_id, "paired_with": paired_with, "reason": reason},
        signature_values={"resource_id": resource_id, "paired_with": paired_with},
    )
