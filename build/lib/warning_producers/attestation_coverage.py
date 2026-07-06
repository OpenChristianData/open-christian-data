"""Attestation coverage warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "attestation_coverage"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "ATTESTATION_BELOW_THRESHOLD": {
        "severity": "warning",
        "description": "A structurally disputed block has too few attestations.",
        "signature_fields": ["code", "entry_id"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    warnings: list[dict[str, Any]] = []
    for block in _blocks(record):
        attested_by = block.get("attested_by")
        structural_disagreements = block.get("structural_disagreements")
        if isinstance(structural_disagreements, list) and structural_disagreements and len(attested_by or []) < 2:
            block_id = _block_id(block)
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="ATTESTATION_BELOW_THRESHOLD",
                    entry_id=block_id,
                    field_path="attested_by",
                    message=f"{block_id}: structural disagreement has fewer than two attestations.",
                    evidence={"attestation_count": len(attested_by or [])},
                )
            )
    return {"warnings": warnings}


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
