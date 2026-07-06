"""Source page coverage warning producer."""

from __future__ import annotations

from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "source_page_coverage"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "SOURCE_PAGE_COVERAGE_MISSING": {
        "severity": "warning",
        "description": "A block lacks source-page coverage for the record PD anchor.",
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
    pd_anchor = record.get("meta", {}).get("pd_anchor")
    for block in _blocks(record):
        source_pages = block.get("source_pages")
        if not _covers_anchor(source_pages, pd_anchor):
            block_id = _block_id(block)
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="SOURCE_PAGE_COVERAGE_MISSING",
                    entry_id=block_id,
                    field_path="source_pages",
                    message=f"{block_id}: source_pages lacks coverage for the PD anchor.",
                    evidence={"pd_anchor": pd_anchor},
                )
            )
    return {"warnings": warnings}


def _covers_anchor(value: Any, pd_anchor: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    if not isinstance(pd_anchor, str) or not pd_anchor:
        return True
    return any(isinstance(page, dict) and page.get("rendering_id") == pd_anchor for page in value)


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
