"""Transliteration completeness warning producer."""

from __future__ import annotations

import re
from typing import Any

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "transliteration_completeness"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "TRANSLITERATION_INCOMPLETE": {
        "severity": "warning",
        "description": "A block contains source script text without a language segment.",
        "signature_fields": ["code", "entry_id"],
    },
}
APPLIES_TO_RESOURCE_TYPES = None
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"
SOURCE_SCRIPT_RE = re.compile(r"[\u0370-\u03ff\u1f00-\u1fff\u0590-\u05ff]+")


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    warnings: list[dict[str, Any]] = []
    for block in _blocks(record):
        text = block.get("original_text")
        if not isinstance(text, str) or not SOURCE_SCRIPT_RE.search(text):
            continue
        segments = block.get("language_segments")
        if _has_source_script_segment(segments):
            continue
        block_id = _block_id(block)
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="TRANSLITERATION_INCOMPLETE",
                entry_id=block_id,
                field_path="language_segments",
                message=f"{block_id}: source script text is not represented in language_segments.",
                evidence={"matched_script": SOURCE_SCRIPT_RE.search(text).group(0)},
            )
        )
    return {"warnings": warnings}


def _has_source_script_segment(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for segment in value:
        if not isinstance(segment, dict):
            continue
        if segment.get("original_script") or segment.get("transliterated_from"):
            return True
    return False


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
