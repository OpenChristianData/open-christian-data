"""Disagreement classification warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "disagreement_classification"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "DISAGREEMENT_UNCLASSIFIED": {
        "severity": "warning",
        "description": "A disagreement still needs classification.",
        "signature_fields": ["code", "entry_id", "field_path"],
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
        block_id = _block_id(block)
        disagreements = block.get("disagreements")
        if not isinstance(disagreements, list):
            continue
        for index, disagreement in enumerate(disagreements):
            if isinstance(disagreement, dict) and disagreement.get("kind") == "unclassified":
                field_path = f"blocks.{block_id}.disagreements.{index}.kind"
                warnings.append(
                    build_warning(
                        producer=__import__(__name__, fromlist=[""]),
                        code="DISAGREEMENT_UNCLASSIFIED",
                        entry_id=block_id,
                        field_path=field_path,
                        message=f"{block_id}: disagreement {index} is unclassified.",
                        evidence={"disagreement_index": index},
                        signature_values={"field_path": field_path},
                    )
                )
    return {"warnings": warnings}


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
