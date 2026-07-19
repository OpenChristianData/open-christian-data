"""Resource taxonomy consistency warning producer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning
from ocd_kernel.lib.schema_enums import resolve_schema_path


PRODUCER_ID = "taxonomy_consistency"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "resource_type_overrides_default": {
        "severity": "info",
        "description": "meta.resource_type overrides the schema default resource type.",
        "signature_fields": ["code", "declared_type", "schema_default"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"
SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "schemas" / "v1"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    record_meta = record.get("meta")
    if not isinstance(record_meta, dict):
        return {"warnings": []}
    declared_type = record_meta.get("resource_type")
    if not isinstance(declared_type, str) or not declared_type:
        return {"warnings": []}
    schema_default = _schema_default(record_meta)
    if declared_type == schema_default:
        return {"warnings": []}
    return {
        "warnings": [
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="resource_type_overrides_default",
                entry_id=None,
                field_path="meta.resource_type",
                message=f"meta.resource_type {declared_type} overrides schema default {schema_default}.",
                evidence={"declared": declared_type, "schema_default": schema_default},
                signature_values={"declared_type": declared_type},
            )
        ]
    }


def _schema_default(record_meta: dict[str, Any]) -> str:
    schema_type = record_meta.get("schema_type")
    if not isinstance(schema_type, str) or not schema_type:
        raise ValueError("record.meta.schema_type must be a non-empty string")
    with resolve_schema_path(schema_type).open(encoding="utf-8") as handle:
        schema = json.load(handle)
    default = schema.get("x-ocd-default-resource-type")
    if not isinstance(default, str) or not default:
        raise ValueError(f"{schema_type}.schema.json has no x-ocd-default-resource-type")
    return default
