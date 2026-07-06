"""Work-level modernisation coverage consistency warning producer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "modernisation_coverage_consistency"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "MOD_COVERAGE_MISSING": {
        "severity": "error",
        "description": "Modernisation is intended but no modernised record files exist.",
        "signature_fields": ["code", "resource_id"],
    },
    "MOD_RECORD_ORPHAN_ORIGINAL": {
        "severity": "error",
        "description": "An original record lacks its expected modernised sibling.",
        "signature_fields": ["code", "record_path"],
    },
    "MOD_RECORD_ORPHAN_MODERNISED": {
        "severity": "error",
        "description": "A modernised record references an original record that is missing.",
        "signature_fields": ["code", "record_path"],
    },
    "MOD_UNEXPECTED_MODERNISED": {
        "severity": "error",
        "description": "A modernised record exists for a work marked not applicable.",
        "signature_fields": ["code", "record_path"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "resource_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    catalog = meta.get("catalog")
    intent = catalog.get("modernisation_intent") if isinstance(catalog, dict) else None
    original_records = _paths(meta.get("original_records"))
    modernised_records = _paths(meta.get("modernised_records"))
    work_dir_value = meta.get("work_dir")
    if not original_records and isinstance(work_dir_value, str):
        original_records = sorted((Path(work_dir_value) / "original").glob("*.json"))
    if not modernised_records and isinstance(work_dir_value, str):
        modernised_records = sorted((Path(work_dir_value) / "modernised").glob("*.json"))

    warnings: list[dict[str, Any]] = []
    if intent == "not_applicable":
        for path in modernised_records:
            warnings.append(_warning(meta, "MOD_UNEXPECTED_MODERNISED", path, "Unexpected modernised record exists."))
        return {"warnings": warnings}

    if intent != "intended":
        return {"warnings": []}
    if not original_records and not modernised_records and not isinstance(work_dir_value, str):
        return {"warnings": []}
    if not modernised_records:
        warnings.append(_warning(meta, "MOD_COVERAGE_MISSING", None, "Modernisation is intended but no modernised records exist."))
    modernised_names = {path.name for path in modernised_records}
    for original_path in original_records:
        if not original_path.exists() or original_path.name not in modernised_names:
            warnings.append(_warning(meta, "MOD_RECORD_ORPHAN_ORIGINAL", original_path, "Original record lacks modernised sibling."))
    for modernised_path in modernised_records:
        paired_path = _paired_path(modernised_path)
        if paired_path is not None and not paired_path.exists():
            warnings.append(_warning(meta, "MOD_RECORD_ORPHAN_MODERNISED", modernised_path, "Modernised record references missing original."))
        elif paired_path is None and original_records and modernised_path.name not in {path.name for path in original_records}:
            warnings.append(_warning(meta, "MOD_RECORD_ORPHAN_MODERNISED", modernised_path, "Modernised record lacks corresponding original."))
    return {"warnings": warnings}


def _paths(value: Any) -> list[Path]:
    if not isinstance(value, list):
        return []
    return [Path(item) for item in value if isinstance(item, str)]


def _paired_path(path: Path) -> Path | None:
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    paired_with = data.get("meta", {}).get("paired_with")
    return Path(paired_with) if isinstance(paired_with, str) and paired_with else None


def _warning(meta: dict, code: str, path: Path | None, message: str) -> dict[str, Any]:
    resource_id = meta.get("resource_id")
    record_path = str(path) if path is not None else None
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code=code,
        entry_id=None,
        field_path="modernisation_intent",
        message=message,
        evidence={"resource_id": resource_id, "record_path": record_path},
        signature_values={"resource_id": resource_id, "record_path": record_path},
    )
