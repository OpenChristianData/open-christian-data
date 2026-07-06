"""OCR scanner warning producer."""

from __future__ import annotations

import json
import math
import re
from datetime import timezone
from typing import Any

from build.lib.paths import REPO_ROOT
from build.lib.warning_producers import WARNING_OUTPUT_SCHEMA, build_warning, warning_signature
from build.tools.ocr_scanner import scanner
from build.tools.ocr_scanner.models import REASON_CODES
from build.tools.ocr_scanner.patterns import DictionaryStack


PRODUCER_ID = "ocr_scanner"
SIGNATURE_VERSION = 1
WARNING_CODES = {
    reason: {
        "severity": "warning" if tier <= 2 else "info",
        "description": f"OCR scanner candidate: {reason}.",
        "signature_fields": ["entry_id", "field_path", "code", "surface", "suggestion"],
    }
    for reason, tier in REASON_CODES.items()
}
APPLIES_TO_RESOURCE_TYPES = ["encyclopedia", "commentary", "sermon_collection", "anthology"]
REQUIRES_CAPABILITIES = {"text_layer_shape": ["single_field", "multi_field"]}
CONSUMES = []
SCOPE = "record_local"

CONFIGS_DIR = REPO_ROOT / "build" / "tools" / "ocr_scanner" / "configs"

_WARNING_ITEM_SCHEMA = WARNING_OUTPUT_SCHEMA["properties"]["warnings"]["items"]
_CANDIDATE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "tier": {"type": "integer"},
        "reason": {"type": "string"},
        "source_id": {"type": "string"},
        "entry_id": {"type": "string"},
        "field_path": {"type": "string"},
        "value": {"type": "string"},
        "suggestion": {"type": ["string", "null"]},
        "suggestion_source": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
        "context_before": {"type": "string"},
        "context_after": {"type": "string"},
        "occurrences": {"type": "integer"},
        "signature": {"type": "string"},
        "snippet": {"type": "string", "maxLength": 120},
    },
    "required": [
        "id",
        "tier",
        "reason",
        "source_id",
        "entry_id",
        "field_path",
        "value",
        "suggestion",
        "suggestion_source",
        "confidence",
        "context_before",
        "context_after",
        "occurrences",
        "signature",
        "snippet",
    ],
    "additionalProperties": False,
}
PRODUCES_SCHEMA = {
    "type": "object",
    "properties": {
        "warnings": {"type": "array", "items": _WARNING_ITEM_SCHEMA},
        "candidates": {"type": "array", "items": _CANDIDATE_SCHEMA},
        "scanned_at": {"type": "string"},
        "entries_scanned": {"type": "integer"},
        "pattern_set": {"type": "string"},
        "pattern_set_version": {"type": "string"},
        "truncated": {"type": "boolean"},
        "truncated_reason": {"type": ["string", "null"]},
        "silenced_by_threshold": {"type": "integer"},
    },
    "required": [
        "warnings",
        "candidates",
        "scanned_at",
        "entries_scanned",
        "pattern_set",
        "pattern_set_version",
        "truncated",
        "truncated_reason",
        "silenced_by_threshold",
    ],
    "additionalProperties": False,
}


def run(record: dict, meta: dict, upstream_outputs: dict) -> dict:
    config_stem = _resolve_config_stem(record, meta)
    if config_stem is None:
        return _empty_output()

    config = scanner.load_config(config_stem)
    dictionary = _dictionary_for_record(record, config)
    result = scanner.scan_entries(
        list(record.get("data") or []),
        config,
        config["source_id"],
        dictionary,
        max_candidates=math.inf,
        timestamp_timezone=timezone.utc,
    )

    candidates = [_candidate_record(candidate) for candidate in result.candidates]
    warnings = [_warning(candidate) for candidate in candidates]
    return {
        "warnings": warnings,
        "candidates": candidates,
        "scanned_at": result.scanned_at,
        "entries_scanned": result.entries_scanned,
        "pattern_set": result.pattern_set,
        "pattern_set_version": result.pattern_set_version,
        "truncated": result.truncated,
        "truncated_reason": result.truncated_reason,
        "silenced_by_threshold": 0,
    }


def _empty_output() -> dict[str, Any]:
    return {
        "warnings": [],
        "candidates": [],
        "scanned_at": "",
        "entries_scanned": 0,
        "pattern_set": "",
        "pattern_set_version": "",
        "truncated": False,
        "truncated_reason": None,
        "silenced_by_threshold": 0,
    }


def _resolve_config_stem(record: dict[str, Any], meta: dict[str, Any]) -> str | None:
    record_meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    scan_source = record_meta.get("scan_source") if isinstance(record_meta, dict) else None
    pattern_set = scan_source.get("pattern_set") if isinstance(scan_source, dict) else None
    if isinstance(pattern_set, str) and pattern_set:
        return _config_stem_for_pattern_set(pattern_set)

    resource_id = str(meta.get("resource_id") or record_meta.get("id") or "")
    fallback_stem = resource_id.removesuffix("-encyclopedia")
    if fallback_stem and (CONFIGS_DIR / f"{fallback_stem}.json").exists():
        return fallback_stem
    if resource_id == "schaff-herzog-encyclopedia":
        return "schaff-herzog"
    return None


def _config_stem_for_pattern_set(pattern_set: str) -> str | None:
    direct_path = CONFIGS_DIR / f"{pattern_set}.json"
    if direct_path.exists():
        return pattern_set
    for path in sorted(CONFIGS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if payload.get("pattern_set") == pattern_set or payload.get("source_id") == pattern_set:
            return path.stem
    return None


def _dictionary_for_record(record: dict[str, Any], config: dict[str, Any]) -> DictionaryStack:
    lexicon_terms: set[str] = set()
    for entry in record.get("data") or []:
        if not isinstance(entry, dict):
            continue
        term = entry.get("term")
        if isinstance(term, str):
            lexicon_terms.add(term)
        alt_terms = entry.get("alt_terms")
        if isinstance(alt_terms, list):
            lexicon_terms.update(value for value in alt_terms if isinstance(value, str))
    return DictionaryStack(
        whitelist_terms=set(config.get("whitelist_terms") or []),
        lexicon_terms=lexicon_terms,
        enable_enchant=False,
    )


def _candidate_record(candidate: Any) -> dict[str, Any]:
    record = candidate.to_dict()
    record["field_path"] = _normalise_field_path(record["field_path"])
    record["snippet"] = _snippet(record["context_before"], record["value"], record["context_after"])
    record["signature"] = _signature_for_candidate(record)
    return record


def _warning(candidate: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        "surface": candidate["value"],
        "snippet": candidate["snippet"],
        "suggestion": candidate["suggestion"],
        "tier": candidate["tier"],
        "confidence": candidate["confidence"],
        "candidate_signature": candidate["signature"],
    }
    return build_warning(
        producer=__import__(__name__, fromlist=[""]),
        code=candidate["reason"],
        entry_id=candidate["entry_id"] or None,
        field_path=candidate["field_path"],
        message=_message(candidate),
        evidence=evidence,
        signature_values={
            "surface": candidate["value"],
            "suggestion": candidate["suggestion"],
        },
    )


def _signature_for_candidate(candidate: dict[str, Any]) -> str:
    values = {
        "entry_id": candidate["entry_id"] or None,
        "field_path": candidate["field_path"],
        "code": candidate["reason"],
        "surface": candidate["value"],
        "suggestion": candidate["suggestion"],
    }
    return warning_signature(WARNING_CODES[candidate["reason"]]["signature_fields"], values)


def _message(candidate: dict[str, Any]) -> str:
    suggestion = candidate.get("suggestion")
    if suggestion:
        return f"{candidate['entry_id']}: OCR candidate {candidate['value']} -> {suggestion}."
    return f"{candidate['entry_id']}: OCR candidate {candidate['value']}."


def _snippet(before: str, surface: str, after: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", f"{before} {surface} {after}").strip()
    if len(text) <= limit:
        return text
    surface_index = text.find(surface)
    if surface_index < 0:
        return text[: limit - 3].rstrip() + "..."
    start = max(0, min(surface_index - 45, len(text) - limit))
    end = min(len(text), start + limit)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def _normalise_field_path(field_path: str) -> str:
    return re.sub(r"\[(\d+)\]", r".\1", field_path)
