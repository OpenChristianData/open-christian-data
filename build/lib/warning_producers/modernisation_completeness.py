"""Modernisation completeness warning producer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning


PRODUCER_ID = "modernisation_completeness"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    "MOD_STALE_RULESET": {
        "severity": "info",
        "description": "A modernised record was produced with an older ruleset.",
        "signature_fields": ["code", "resource_id"],
    },
    "MOD_SPAN_INCONSISTENT": {
        "severity": "error",
        "description": "A modernisation span does not match stored original or modern tokens.",
        "signature_fields": ["code", "entry_id", "field_path"],
    },
    "MOD_TRANSLIT_INCONSISTENT": {
        "severity": "error",
        "description": "A modernisation conflicts with transliteration segment invariants.",
        "signature_fields": ["code", "entry_id"],
    },
    "MOD_RULE_GONE": {
        "severity": "error",
        "description": "A modernisation references a missing or disabled rule.",
        "signature_fields": ["code", "entry_id", "rule_id"],
    },
    "MOD_DELTA_UNRECONSTRUCTABLE": {
        "severity": "error",
        "description": "Stored modernisations do not reconstruct modern_text.",
        "signature_fields": ["code", "entry_id"],
    },
    "MOD_RECORD_NEEDS_REVIEW": {
        "severity": "warning",
        "description": "A modernised record has block-level modernisation warnings.",
        "signature_fields": ["code", "resource_id"],
    },
}
APPLIES_TO_RESOURCE_TYPES = ["modernised_record"]
REQUIRES_CAPABILITIES = {}
CONSUMES = []
PRODUCES_SCHEMA = WARNING_OUTPUT_SCHEMA
SCOPE = "record_local"
RULESET_DIR = Path(__file__).resolve().parents[1] / "modernisation" / "rulesets"


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    if record.get("meta", {}).get("schema_type") != "modernised_record":
        return {"warnings": []}
    warnings: list[dict[str, Any]] = []
    _append_stale_ruleset_warning(warnings, record, meta)
    enabled_rule_ids, known_rule_ids = _ruleset_rule_ids(record)
    for block in _blocks(record):
        block_warnings_before = len(warnings)
        _append_span_warnings(warnings, block)
        _append_transliteration_warnings(warnings, block, meta)
        _append_rule_warnings(warnings, block, enabled_rule_ids, known_rule_ids)
        _append_delta_warning(warnings, block)
        if len(warnings) > block_warnings_before:
            continue
    if any(warning["code"] != "MOD_RECORD_NEEDS_REVIEW" for warning in warnings):
        resource_id = meta.get("resource_id") or record.get("meta", {}).get("id")
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="MOD_RECORD_NEEDS_REVIEW",
                entry_id=None,
                field_path="blocks.modernisations",
                message="Record contains modernisation warnings.",
                evidence={"resource_id": resource_id},
                signature_values={"resource_id": resource_id},
            )
        )
    return {"warnings": warnings}


def _append_stale_ruleset_warning(warnings: list[dict[str, Any]], record: dict, meta: dict) -> None:
    record_meta = record.get("meta", {})
    language = record_meta.get("language")
    current = record_meta.get("modernisation_ruleset_version")
    head = None
    versions = meta.get("ruleset_versions")
    if isinstance(versions, dict) and isinstance(language, str):
        head = versions.get(language)
    if head is None and isinstance(language, str):
        head = _head_ruleset_version(language)
    if isinstance(current, str) and isinstance(head, str) and current != head:
        resource_id = meta.get("resource_id") or record_meta.get("id")
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="MOD_STALE_RULESET",
                entry_id=None,
                field_path="meta.modernisation_ruleset_version",
                message=f"Modernisation ruleset {current} is not the current head {head}.",
                evidence={"resource_id": resource_id, "current": current, "head": head},
                signature_values={"resource_id": resource_id},
            )
        )


def _append_span_warnings(warnings: list[dict[str, Any]], block: dict[str, Any]) -> None:
    original_tokens = _tokens(block.get("original_text"))
    modern_tokens = _tokens(block.get("modern_text"))
    previous_end = -1
    for index, modernisation in enumerate(_modernisations(block)):
        span = modernisation.get("span")
        start = span.get("start_token") if isinstance(span, dict) else None
        end = span.get("end_token") if isinstance(span, dict) else None
        bad = not isinstance(start, int) or not isinstance(end, int) or start < previous_end or end <= start
        if not bad:
            original = " ".join(original_tokens[start:end])
            modern = " ".join(modern_tokens[start:end])
            bad = original != modernisation.get("original") or modern != modernisation.get("modern")
        if bad:
            block_id = _block_id(block)
            field_path = f"modernisations.{index}.span"
            warnings.append(
                build_warning(
                    producer=__import__(__name__, fromlist=[""]),
                    code="MOD_SPAN_INCONSISTENT",
                    entry_id=block_id,
                    field_path=field_path,
                    message=f"{block_id}: modernisation span {index} does not match stored tokens.",
                    evidence={"modernisation_index": index},
                    signature_values={"field_path": field_path},
                )
            )
        if isinstance(end, int):
            previous_end = end


def _append_transliteration_warnings(warnings: list[dict[str, Any]], block: dict[str, Any], meta: dict) -> None:
    original_tokens = _tokens(block.get("original_text"))
    modern_tokens = _tokens(block.get("modern_text"))
    for segment in _segments(block):
        span = segment.get("span")
        start = span.get("start_token") if isinstance(span, dict) else None
        end = span.get("end_token") if isinstance(span, dict) else None
        transliteration = segment.get("transliteration")
        if not isinstance(start, int) or not isinstance(end, int) or not isinstance(transliteration, str):
            _append_translit_warning(warnings, block, "invalid_segment")
            return
        if " ".join(original_tokens[start:end]) != transliteration or " ".join(modern_tokens[start:end]) != transliteration:
            _append_translit_warning(warnings, block, "segment_text_mismatch")
            return
        for modernisation in _modernisations(block):
            mod_span = modernisation.get("span")
            mod_start = mod_span.get("start_token") if isinstance(mod_span, dict) else None
            mod_end = mod_span.get("end_token") if isinstance(mod_span, dict) else None
            if isinstance(mod_start, int) and isinstance(mod_end, int) and max(start, mod_start) < min(end, mod_end):
                _append_translit_warning(warnings, block, "modernisation_intersects_segment")
                return
    paired = meta.get("paired_record")
    if isinstance(paired, dict):
        paired_block = _paired_block(paired, _block_id(block))
        if paired_block is not None and _segment_identity(block.get("language_segments")) != _segment_identity(paired_block.get("language_segments")):
            _append_translit_warning(warnings, block, "paired_segment_mismatch")


def _append_translit_warning(warnings: list[dict[str, Any]], block: dict[str, Any], reason: str) -> None:
    block_id = _block_id(block)
    warnings.append(
        build_warning(
            producer=__import__(__name__, fromlist=[""]),
            code="MOD_TRANSLIT_INCONSISTENT",
            entry_id=block_id,
            field_path="language_segments",
            message=f"{block_id}: transliteration segment consistency failed.",
            evidence={"reason": reason},
        )
    )


def _append_rule_warnings(
    warnings: list[dict[str, Any]],
    block: dict[str, Any],
    enabled_rule_ids: set[str],
    known_rule_ids: set[str],
) -> None:
    for modernisation in _modernisations(block):
        rule_id = modernisation.get("rule_id")
        if rule_id is None:
            continue
        if isinstance(rule_id, str) and rule_id in known_rule_ids and rule_id in enabled_rule_ids:
            continue
        block_id = _block_id(block)
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="MOD_RULE_GONE",
                entry_id=block_id,
                field_path="modernisations.rule_id",
                message=f"{block_id}: modernisation references missing or disabled rule {rule_id}.",
                evidence={"rule_id": rule_id},
            )
        )


def _append_delta_warning(warnings: list[dict[str, Any]], block: dict[str, Any]) -> None:
    original_tokens = _tokens(block.get("original_text"))
    reconstructed = list(original_tokens)
    offset = 0
    for modernisation in _modernisations(block):
        span = modernisation.get("span")
        start = span.get("start_token") if isinstance(span, dict) else None
        end = span.get("end_token") if isinstance(span, dict) else None
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        replacement = _tokens(modernisation.get("modern"))
        adjusted_start = start + offset
        adjusted_end = end + offset
        reconstructed[adjusted_start:adjusted_end] = replacement
        offset += len(replacement) - (end - start)
    if " ".join(reconstructed) != block.get("modern_text"):
        block_id = _block_id(block)
        warnings.append(
            build_warning(
                producer=__import__(__name__, fromlist=[""]),
                code="MOD_DELTA_UNRECONSTRUCTABLE",
                entry_id=block_id,
                field_path="modernisations",
                message=f"{block_id}: modernisations do not reconstruct modern_text.",
                evidence={"reconstructed": " ".join(reconstructed)},
            )
        )


def _ruleset_rule_ids(record: dict) -> tuple[set[str], set[str]]:
    language = record.get("meta", {}).get("language")
    if not isinstance(language, str):
        return set(), set()
    path = RULESET_DIR / f"{language}.yaml"
    if not path.exists():
        return set(), set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules")
    if not isinstance(rules, list):
        return set(), set()
    known = {rule.get("id") for rule in rules if isinstance(rule, dict) and isinstance(rule.get("id"), str)}
    enabled = {
        rule.get("id")
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("id"), str) and rule.get("enabled", True)
    }
    return enabled, known


def _head_ruleset_version(language: str) -> str | None:
    path = RULESET_DIR / f"{language}.yaml"
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    version = data.get("version")
    return f"{language}@{version}" if isinstance(version, str) and version else None


def _tokens(value: Any) -> list[str]:
    return value.split() if isinstance(value, str) else []


def _blocks(record: dict) -> list[dict[str, Any]]:
    blocks = record.get("blocks")
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def _modernisations(block: dict[str, Any]) -> list[dict[str, Any]]:
    value = block.get("modernisations")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _segments(block: dict[str, Any]) -> list[dict[str, Any]]:
    value = block.get("language_segments")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _paired_block(record: dict, block_id: str) -> dict[str, Any] | None:
    return next((block for block in _blocks(record) if block.get("block_id") == block_id), None)


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


def _block_id(block: dict[str, Any]) -> str:
    value = block.get("block_id")
    return value if isinstance(value, str) and value else "unknown"
