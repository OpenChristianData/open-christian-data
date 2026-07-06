"""Coverage warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.coverage_strategies import CoverageStrategyError, dispatch, register_record_strategy
from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "coverage"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "coverage_strategy_unset": {
        "severity": "info",
        "description": "The record does not declare a coverage strategy.",
        "signature_fields": ["code", "resource_id"],
    },
    "coverage_pair_invalid": {
        "severity": "error",
        "description": "The configured coverage strategy is not valid for this resource type.",
        "signature_fields": ["code", "resource_id", "resource_type", "strategy"],
    },
    "coverage_parameter_provenance_missing": {
        "severity": "error",
        "description": "A coverage strategy parameter lacks required provenance.",
        "signature_fields": ["code", "resource_id", "strategy"],
    },
    "missing_chapter": {
        "severity": "warning",
        "description": "A canonical chapter has no coverage entry.",
        "signature_fields": ["code", "resource_id", "book", "chapter"],
    },
    "missing_verse_range": {
        "severity": "warning",
        "description": "A verse range within a covered chapter has no coverage entry.",
        "signature_fields": ["code", "resource_id", "book", "chapter", "verse_range"],
    },
    "entry_count_out_of_range": {
        "severity": "warning",
        "description": "The entry count is outside the expected inventory range.",
        "signature_fields": ["code", "resource_id", "entry_count", "low", "high"],
    },
    "alphabetical_gap": {
        "severity": "warning",
        "description": "An expected initial letter has no entries.",
        "signature_fields": ["code", "resource_id", "letter"],
    },
    "duplicate_headword": {
        "severity": "warning",
        "description": "Two or more entries share the same normalised headword.",
        "signature_fields": ["code", "resource_id", "term"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    record_meta = record.get("meta")
    coverage = record_meta.get("coverage") if isinstance(record_meta, dict) else None
    strategy = coverage.get("strategy") if isinstance(coverage, dict) else None
    if strategy is not None:
        resource_type = meta.get("resource_type")
        parameters = coverage.get("parameters") if isinstance(coverage, dict) else {}
        try:
            register_record_strategy(str(resource_type), str(strategy), _parameters(parameters))
        except CoverageStrategyError as exc:
            if "not allowed" in str(exc) or "Unknown coverage strategy" in str(exc):
                return {"warnings": [_coverage_pair_invalid(meta, str(resource_type), str(strategy), str(exc))]}
            return {"warnings": [_coverage_parameter_invalid(meta, str(strategy), str(exc))]}
        return {"warnings": dispatch(str(resource_type), str(strategy), _parameters(parameters), record)}
    resource_id = meta.get("resource_id")
    return {
        "warnings": [
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="coverage_strategy_unset",
                entry_id=None,
                field_path="meta.coverage.strategy",
                message="Coverage strategy is not set.",
                evidence={"resource_id": resource_id},
                signature_values={"resource_id": resource_id},
                ephemeral=True,
            )
        ]
    }


def _parameters(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coverage_pair_invalid(meta: dict, resource_type: str, strategy: str, reason: str) -> dict:
    resource_id = meta.get("resource_id")
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code="coverage_pair_invalid",
        entry_id=None,
        field_path="meta.coverage.strategy",
        message=f"Coverage strategy {strategy!r} is not valid for resource_type {resource_type!r}.",
        evidence={
            "resource_id": resource_id,
            "resource_type": resource_type,
            "strategy": strategy,
            "reason": reason,
        },
        signature_values={"resource_id": resource_id, "resource_type": resource_type, "strategy": strategy},
    )


def _coverage_parameter_invalid(meta: dict, strategy: str, reason: str) -> dict:
    resource_id = meta.get("resource_id")
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code="coverage_parameter_provenance_missing",
        entry_id=None,
        field_path="meta.coverage.parameters",
        message="Coverage strategy parameters are missing required provenance.",
        evidence={"resource_id": resource_id, "strategy": strategy, "reason": reason},
        signature_values={"resource_id": resource_id, "strategy": strategy},
    )
