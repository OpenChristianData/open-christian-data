"""attested_by reference-resolution warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "attested_by_reference_resolution"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "ATTESTED_BY_REFERENCE_UNRESOLVED": {
        "severity": "error",
        "description": "A block attested_by value does not resolve to the rendering catalog.",
        "signature_fields": ["code", "entry_id", "rendering_id"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    catalog_ids = _catalog_rendering_ids(meta.get("catalog"))
    if not catalog_ids:
        return {"warnings": []}
    warnings: list[dict[str, Any]] = []
    for block in _blocks(record):
        block_id = _block_id(block)
        attested_by = block.get("attested_by")
        if not isinstance(attested_by, list):
            continue
        for rendering_id in attested_by:
            if isinstance(rendering_id, str) and rendering_id not in catalog_ids:
                warnings.append(
                    build_warning(
                        producer=__import__(__name__, fromlist=[""]),
                        code="ATTESTED_BY_REFERENCE_UNRESOLVED",
                        entry_id=block_id,
                        field_path="attested_by",
                        message=f"{block_id}: attested_by references unknown rendering {rendering_id}.",
                        evidence={"rendering_id": rendering_id},
                    )
                )
    return {"warnings": warnings}


def _catalog_rendering_ids(catalog: Any) -> set[str]:
    if not isinstance(catalog, dict):
        return set()
    renderings = catalog.get("renderings")
    if not isinstance(renderings, list):
        return set()
    return {
        rendering.get("rendering_id")
        for rendering in renderings
        if isinstance(rendering, dict) and isinstance(rendering.get("rendering_id"), str)
    }


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
