"""Small Phase C safety helpers for parser-regeneration tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from build.lib.text_layers import build_reference_layers, build_single_field_layers


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _has_correction(
    corrections: set[tuple[str, str]],
    *,
    entry_id: str,
    field_path: str,
) -> bool:
    return (entry_id, field_path) in corrections


def merge_single_field_regen(
    *,
    previous_entry: Mapping[str, Any] | None,
    parsed_entry: dict[str, Any],
    corrections: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Merge parser output with existing display when an applied correction exists."""
    correction_set = corrections or set()
    entry_id = str(parsed_entry["entry_id"])
    structured = str(parsed_entry["commentary_text"])
    display = structured
    if previous_entry and _has_correction(
        correction_set,
        entry_id=entry_id,
        field_path="commentary_text",
    ):
        display = str(previous_entry.get("commentary_text", structured))
    parsed_entry["commentary_text"] = display
    layers = build_single_field_layers(
        source_raw=structured,
        normalised=structured,
        structured=structured,
        display=display,
        source_raw_origin="observed",
    )
    if layers:
        parsed_entry["layers"] = layers
    else:
        parsed_entry.pop("layers", None)
    event = {
        "event_type": "parser_regenerated_field",
        "timestamp_utc": _utc_now_iso(),
        "entry_id": entry_id,
        "field_path": "commentary_text",
        "display": display,
    }
    return parsed_entry, [event]


def merge_definition_block_regen(
    *,
    previous_entry: Mapping[str, Any] | None,
    parsed_entry: dict[str, Any],
    corrections: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Merge definition blocks while preserving corrected display values."""
    correction_set = corrections or set()
    entry_id = str(parsed_entry["entry_id"])
    structured_blocks = [str(value) for value in parsed_entry.get("definition_blocks", [])]
    display_blocks = list(structured_blocks)
    if previous_entry:
        previous_blocks = [str(value) for value in previous_entry.get("definition_blocks", [])]
        for idx, value in enumerate(previous_blocks):
            field_path = f"definition_blocks.{idx}"
            if idx < len(display_blocks) and _has_correction(
                correction_set,
                entry_id=entry_id,
                field_path=field_path,
            ):
                display_blocks[idx] = value
    parsed_entry["definition_blocks"] = display_blocks
    layers = build_reference_layers(
        term=str(parsed_entry["term"]),
        alt_terms=[str(value) for value in parsed_entry.get("alt_terms", [])],
        definition_blocks=structured_blocks,
        display_blocks=display_blocks,
        source_raw_origin="observed",
    )
    if layers:
        parsed_entry["layers"] = layers
    else:
        parsed_entry.pop("layers", None)
    events = [
        {
            "event_type": "parser_regenerated_field",
            "timestamp_utc": _utc_now_iso(),
            "entry_id": entry_id,
            "field_path": f"definition_blocks.{idx}",
            "display": display,
        }
        for idx, display in enumerate(display_blocks)
    ]
    return parsed_entry, events


__all__ = ["merge_definition_block_regen", "merge_single_field_regen"]
