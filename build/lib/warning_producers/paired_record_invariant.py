"""Modernised/original paired-record invariant warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "paired_record_invariant"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "PAIRED_RECORD_INVARIANT": {
        "severity": "error",
        "description": "A modernised record does not preserve required paired-record invariants.",
        "signature_fields": ["code", "resource_id", "reason"],
    },
}
APPLIES_TO_RESOURCE_TYPES = ["modernised_record"]
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    if record.get("meta", {}).get("schema_type") != "modernised_record":
        return {"warnings": []}
    paired_record = meta.get("paired_record")
    if not isinstance(paired_record, dict):
        return {"warnings": []}
    reasons: list[str] = []
    if not record.get("meta", {}).get("paired_with"):
        reasons.append("missing_paired_with")
    blocks = _blocks(record)
    paired_blocks = _blocks(paired_record)
    if len(blocks) != len(paired_blocks):
        reasons.append("block_count")
    if [block.get("block_id") for block in blocks] != [block.get("block_id") for block in paired_blocks]:
        reasons.append("block_ids")
    for index, (block, paired_block) in enumerate(zip(blocks, paired_blocks, strict=False)):
        if _segment_identity(block.get("language_segments")) != _segment_identity(paired_block.get("language_segments")):
            reasons.append(f"language_segments:{index}")
            break
    if not reasons:
        return {"warnings": []}
    return {"warnings": [_warning(meta, reasons)]}


def _warning(meta: dict, reasons: list[str]) -> dict[str, Any]:
    resource_id = meta.get("resource_id")
    reason = ",".join(reasons)
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code="PAIRED_RECORD_INVARIANT",
        entry_id=None,
        field_path="meta.paired_with",
        message="Modernised record violates paired-record invariants.",
        evidence={"resource_id": resource_id, "reason": reason},
        signature_values={"resource_id": resource_id, "reason": reason},
    )


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _segment_identity(value: Any) -> list[tuple[Any, Any, Any, Any]]:
    if not isinstance(value, list):
        return []
    return [
        (
            segment.get("language"),
            segment.get("original_script"),
            segment.get("transliteration"),
            segment.get("transliterated_from"),
        )
        for segment in value
        if isinstance(segment, dict)
    ]
