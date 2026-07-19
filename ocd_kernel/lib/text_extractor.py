"""Resource-neutral text extraction for review-warning producers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ocd_kernel.lib.schema_enums import resolve_schema_path


ExtractedText = tuple[str, str, str, str | None, list]


def effective_resource_type(record: dict[str, Any], schemas_dir: Path) -> str:
    """Return the record's effective resource type."""
    meta = record.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("record.meta must be an object")
    override = meta.get("resource_type")
    if isinstance(override, str) and override:
        return override

    schema_type = meta.get("schema_type")
    if not isinstance(schema_type, str) or not schema_type:
        raise ValueError("record.meta.schema_type must be a non-empty string")
    schema_path = schemas_dir / f"{schema_type}.schema.json"
    if not schema_path.exists():
        schema_path = resolve_schema_path(schema_type)
    with schema_path.open(encoding="utf-8") as handle:
        schema = json.load(handle)
    default_resource_type = schema.get("x-ocd-default-resource-type")
    if not isinstance(default_resource_type, str) or not default_resource_type:
        raise ValueError(f"{schema_path} has no x-ocd-default-resource-type")
    return default_resource_type


def extract_text(record: dict[str, Any], schemas_dir: Path) -> Iterator[ExtractedText]:
    """Yield text fields as entry_id, field_path, text, lang_hint, lang_spans tuples."""
    try:
        resource_type = effective_resource_type(record, schemas_dir)
    except ValueError:
        # Schema has no x-ocd-default-resource-type (e.g. reconciled_record).
        # Text extraction is not defined for this schema type — yield nothing.
        return
    if resource_type == "commentary":
        yield from _extract_commentary(record)
        return
    if resource_type == "encyclopedia":
        yield from _extract_encyclopedia(record)
        return
    raise ValueError(f"Unsupported resource_type: {resource_type}")


def _extract_commentary(record: dict[str, Any]) -> Iterator[ExtractedText]:
    default_lang_hint = _record_lang_hint(record)
    for entry in _entries(record):
        entry_id = _entry_id(entry)
        text = entry.get("commentary_text")
        if isinstance(text, str):
            yield (entry_id, "commentary_text", text, *_language_metadata(record, entry, "commentary_text", default_lang_hint))


def _extract_encyclopedia(record: dict[str, Any]) -> Iterator[ExtractedText]:
    default_lang_hint = _record_lang_hint(record)
    for entry in _entries(record):
        entry_id = _entry_id(entry)
        term = entry.get("term")
        if isinstance(term, str):
            yield (entry_id, "term", term, *_language_metadata(record, entry, "term", default_lang_hint))
        alt_terms = entry.get("alt_terms")
        if isinstance(alt_terms, list):
            for index, value in enumerate(alt_terms):
                if isinstance(value, str):
                    field_path = f"alt_terms.{index}"
                    yield (entry_id, field_path, value, *_language_metadata(record, entry, field_path, default_lang_hint))
        definition_blocks = entry.get("definition_blocks")
        if isinstance(definition_blocks, list):
            for index, block in enumerate(definition_blocks):
                field_path = f"definition_blocks.{index}"
                if isinstance(block, str):
                    yield (entry_id, field_path, block, *_language_metadata(record, entry, field_path, default_lang_hint))
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    yield (entry_id, field_path, block["text"], *_language_metadata(record, entry, field_path, default_lang_hint))


def _entries(record: dict[str, Any]) -> Iterator[dict[str, Any]]:
    data = record.get("data")
    if not isinstance(data, list):
        return
    for entry in data:
        if isinstance(entry, dict):
            yield entry


def _entry_id(entry: dict[str, Any]) -> str:
    entry_id = entry.get("entry_id")
    if isinstance(entry_id, str) and entry_id:
        return entry_id
    return ""


def _record_lang_hint(record: dict[str, Any]) -> str | None:
    meta = record.get("meta")
    if not isinstance(meta, dict):
        return None
    language = meta.get("language")
    return language if isinstance(language, str) and language else None


def _language_metadata(
    record: dict[str, Any],
    entry: dict[str, Any],
    field_path: str,
    default_lang_hint: str | None,
) -> tuple[str | None, list]:
    lang_hint = _field_value(record, entry, "lang_hints", field_path)
    if not isinstance(lang_hint, str):
        lang_hint = entry.get("lang_hint") if isinstance(entry.get("lang_hint"), str) else default_lang_hint

    lang_spans = _field_value(record, entry, "lang_spans", field_path)
    if not isinstance(lang_spans, list):
        lang_spans = entry.get("lang_spans") if isinstance(entry.get("lang_spans"), list) else []
    return lang_hint, lang_spans


def _field_value(record: dict[str, Any], entry: dict[str, Any], key: str, field_path: str) -> Any:
    entry_values = entry.get(key)
    if isinstance(entry_values, dict) and field_path in entry_values:
        return entry_values[field_path]
    meta = record.get("meta")
    meta_values = meta.get(key) if isinstance(meta, dict) else None
    if isinstance(meta_values, dict) and field_path in meta_values:
        return meta_values[field_path]
    return None
