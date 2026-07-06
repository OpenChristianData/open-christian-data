"""Language confidence warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "language_confidence"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "LANG_BLOCK_NEEDS_REVIEW": {
        "severity": "warning",
        "description": "A block language assignment is undefined or below confidence floor.",
        "signature_fields": ["code", "entry_id"],
    },
    "LANG_RECORD_NEEDS_REVIEW": {
        "severity": "warning",
        "description": "At least one block language assignment needs review.",
        "signature_fields": ["code", "resource_id"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"
CONFIDENCE_FLOOR = 0.60


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    warnings: list[dict[str, Any]] = []
    for block in _blocks(record):
        language = block.get("language")
        confidence = block.get("language_confidence")
        if language == "und" or (isinstance(confidence, int | float) and confidence < CONFIDENCE_FLOOR):
            block_id = _block_id(block)
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="LANG_BLOCK_NEEDS_REVIEW",
                    entry_id=block_id,
                    field_path="language_confidence",
                    message=f"{block_id}: language assignment needs review.",
                    evidence={"language": language, "language_confidence": confidence},
                )
            )
    if warnings:
        resource_id = meta.get("resource_id") or record.get("meta", {}).get("id")
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="LANG_RECORD_NEEDS_REVIEW",
                entry_id=None,
                field_path="blocks.language_confidence",
                message="Record contains blocks whose language assignment needs review.",
                evidence={"resource_id": resource_id, "flagged_blocks": len(warnings)},
                signature_values={"resource_id": resource_id},
            )
        )
    return {"warnings": warnings}


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
