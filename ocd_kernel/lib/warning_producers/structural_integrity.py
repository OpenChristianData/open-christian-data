"""Universal structural integrity warning producer."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ocd_kernel.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "structural_integrity"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "duplicate_entry_id": {
        "severity": "error",
        "description": "The same entry_id appears more than once.",
        "signature_fields": ["entry_id", "code"],
    },
    "missing_entry_id": {
        "severity": "error",
        "description": "An entry is missing entry_id.",
        "signature_fields": ["entry_index", "code"],
    },
    "cross_references_shape": {
        "severity": "warning",
        "description": "cross_references is not a list of strings.",
        "signature_fields": ["entry_id", "field_path", "code"],
    },
    "related_terms_shape": {
        "severity": "warning",
        "description": "related_terms is not a list of strings.",
        "signature_fields": ["entry_id", "field_path", "code"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    warnings: list[dict[str, Any]] = []
    entries = record.get("data")
    if not isinstance(entries, list):
        return {"warnings": warnings}

    entry_ids = [_entry_id(entry) for entry in entries if isinstance(entry, dict)]
    counts = Counter(entry_id for entry_id in entry_ids if entry_id)
    for entry_id, count in sorted(counts.items()):
        if count > 1:
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="duplicate_entry_id",
                    entry_id=entry_id,
                    field_path="entry_id",
                    message=f"Duplicate entry_id: {entry_id}",
                    evidence={"count": count},
                )
            )

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        entry_id = _entry_id(entry)
        if not entry_id:
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="missing_entry_id",
                    entry_id=None,
                    field_path="entry_id",
                    message=f"Entry {index + 1} is missing entry_id.",
                    evidence={"entry_index": index},
                    signature_values={"entry_index": index},
                )
            )
        _append_shape_warning(warnings, entry, entry_id, "cross_references", "cross_references_shape")
        _append_shape_warning(warnings, entry, entry_id, "related_terms", "related_terms_shape")
    return {"warnings": warnings}


def _append_shape_warning(
    warnings: list[dict[str, Any]],
    entry: dict[str, Any],
    entry_id: str | None,
    field_path: str,
    code: str,
) -> None:
    value = entry.get(field_path)
    if value is None:
        return
    if not isinstance(value, list):
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code=code,
                entry_id=entry_id,
                field_path=field_path,
                message=f"{_label(entry_id)}: {field_path} is present but is not a list.",
                evidence={"actual_type": type(value).__name__},
            )
        )
        return
    if any(not isinstance(item, str) for item in value):
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code=code,
                entry_id=entry_id,
                field_path=field_path,
                message=f"{_label(entry_id)}: {field_path} contains a non-string value.",
                evidence={"actual_type": "mixed"},
            )
        )


def _entry_id(entry: dict[str, Any]) -> str | None:
    entry_id = entry.get("entry_id")
    if isinstance(entry_id, str) and entry_id.strip():
        return entry_id
    return None


def _label(entry_id: str | None) -> str:
    return entry_id or "Entry"
