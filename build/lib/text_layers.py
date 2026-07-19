"""Helpers for Phase C sparse text layers and surface-field checks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from ocd_kernel.lib.block_id import block_id


SOURCE_RAW_ORIGINS = frozenset({"observed", "unavailable", "reconstructed"})
LAYER_VALUE_KEYS = ("source_raw", "normalised", "structured", "display")


class SurfaceFieldInvariantViolation(ValueError):
    """Raised when a record's visible field no longer matches its display layer."""


def sparse_layer_entry(
    *,
    source_raw: str,
    normalised: str,
    structured: str,
    display: str | None = None,
    source_raw_origin: str = "observed",
) -> dict[str, str] | None:
    """Return a layer entry only when sparse-storage requires one.

    The surface field remains canonical when all layer values agree with
    ``structured``. In that common case this returns ``None``.
    """
    if source_raw_origin not in SOURCE_RAW_ORIGINS:
        raise ValueError(f"unknown source_raw_origin: {source_raw_origin!r}")
    effective_display = structured if display is None else display
    values = {
        "source_raw": source_raw,
        "normalised": normalised,
        "structured": structured,
        "display": effective_display,
        "source_raw_origin": source_raw_origin,
    }
    if (
        values["source_raw"] == structured
        and values["normalised"] == structured
        and values["display"] == structured
    ):
        return None
    return values


def definition_block_ids(normalised_blocks: list[str]) -> list[str]:
    """Return stable content-hash ids for ``normalised_blocks`` in order."""
    seen: dict[str, int] = defaultdict(int)
    ids: list[str] = []
    for text in normalised_blocks:
        occurrence = seen[text]
        seen[text] += 1
        ids.append(block_id(text, occurrence))
    return ids


def build_single_field_layers(
    *,
    source_raw: str,
    normalised: str,
    structured: str,
    display: str | None = None,
    source_raw_origin: str = "observed",
) -> dict[str, dict[str, str]]:
    """Build sparse ``layers`` for a commentary entry."""
    layer = sparse_layer_entry(
        source_raw=source_raw,
        normalised=normalised,
        structured=structured,
        display=display,
        source_raw_origin=source_raw_origin,
    )
    return {"commentary_text": layer} if layer is not None else {}


def build_reference_layers(
    *,
    term: str,
    definition_blocks: list[str],
    alt_terms: list[str] | None = None,
    source_raw_term: str | None = None,
    normalised_term: str | None = None,
    display_term: str | None = None,
    source_raw_blocks: list[str] | None = None,
    normalised_blocks: list[str] | None = None,
    display_blocks: list[str] | None = None,
    source_raw_alt_terms: list[str] | None = None,
    normalised_alt_terms: list[str] | None = None,
    display_alt_terms: list[str] | None = None,
    source_raw_origin: str = "observed",
) -> dict[str, Any]:
    """Build sparse ``layers`` for a reference-entry record."""
    layers: dict[str, Any] = {}
    term_layer = sparse_layer_entry(
        source_raw=source_raw_term if source_raw_term is not None else term,
        normalised=normalised_term if normalised_term is not None else term,
        structured=term,
        display=display_term,
        source_raw_origin=source_raw_origin,
    )
    if term_layer is not None:
        layers["term"] = term_layer

    alt_values = alt_terms or []
    alt_source = source_raw_alt_terms or alt_values
    alt_norm = normalised_alt_terms or alt_values
    alt_display = display_alt_terms or alt_values
    alt_layers: dict[str, dict[str, str]] = {}
    for idx, structured in enumerate(alt_values):
        layer = sparse_layer_entry(
            source_raw=alt_source[idx] if idx < len(alt_source) else structured,
            normalised=alt_norm[idx] if idx < len(alt_norm) else structured,
            structured=structured,
            display=alt_display[idx] if idx < len(alt_display) else structured,
            source_raw_origin=source_raw_origin,
        )
        if layer is not None:
            alt_layers[str(idx)] = layer
    if alt_layers:
        layers["alt_terms"] = alt_layers

    block_norm = normalised_blocks or definition_blocks
    block_source = source_raw_blocks or definition_blocks
    block_display = display_blocks or definition_blocks
    block_layer_entries: list[tuple[str, dict[str, str] | None, dict[str, str]]] = []
    for idx, layer_key in enumerate(definition_block_ids(definition_blocks)):
        structured = definition_blocks[idx]
        source_raw = block_source[idx] if idx < len(block_source) else structured
        normalised = block_norm[idx] if idx < len(block_norm) else structured
        display = block_display[idx] if idx < len(block_display) else structured
        layer = sparse_layer_entry(
            source_raw=source_raw,
            normalised=normalised,
            structured=structured,
            display=display,
            source_raw_origin=source_raw_origin,
        )
        full_layer = {
            "source_raw": source_raw,
            "normalised": normalised,
            "structured": structured,
            "display": display,
            "source_raw_origin": source_raw_origin,
        }
        block_layer_entries.append((layer_key, layer, full_layer))
    block_layers: dict[str, dict[str, str]] = {}
    if any(layer is not None for _, layer, _ in block_layer_entries):
        block_layers = {
            layer_key: layer if layer is not None else full_layer
            for layer_key, layer, full_layer in block_layer_entries
        }
    if block_layers:
        layers["definition_blocks"] = block_layers
    return layers


def apply_layers_to_entry(entry: dict[str, Any], *, text_layer_shape: str) -> None:
    """Attach sparse layers to an already-structured entry when absent."""
    if text_layer_shape == "single_field":
        structured = str(entry.get("commentary_text") or "")
        layers = build_single_field_layers(
            source_raw=structured,
            normalised=structured,
            structured=structured,
            display=structured,
            source_raw_origin="unavailable",
        )
    elif text_layer_shape == "multi_field":
        blocks = [str(value) for value in entry.get("definition_blocks", [])]
        layers = build_reference_layers(
            term=str(entry.get("term") or ""),
            alt_terms=[str(value) for value in entry.get("alt_terms", [])],
            definition_blocks=blocks,
            source_raw_origin="unavailable",
        )
    else:
        raise ValueError(f"unknown text_layer_shape: {text_layer_shape!r}")
    if layers:
        entry["layers"] = layers


def _layer_display_or_structured(layer: Mapping[str, str] | None, structured: str) -> str:
    if not layer:
        return structured
    return layer.get("display", structured)


def assert_surface_field_invariant(
    entry: Mapping[str, Any],
    *,
    text_layer_shape: str,
) -> None:
    """Validate that visible fields match their layer display values."""
    layers = entry.get("layers") if isinstance(entry.get("layers"), Mapping) else {}
    if text_layer_shape == "single_field":
        structured = str(entry.get("commentary_text") or "")
        layer = layers.get("commentary_text") if isinstance(layers, Mapping) else None
        expected = _layer_display_or_structured(layer, structured)
        if entry.get("commentary_text") != expected:
            raise SurfaceFieldInvariantViolation(
                f"{entry.get('entry_id', '<unknown>')}: commentary_text does not match display layer"
            )
        return

    if text_layer_shape != "multi_field":
        raise ValueError(f"unknown text_layer_shape: {text_layer_shape!r}")

    term = str(entry.get("term") or "")
    term_layer = layers.get("term") if isinstance(layers, Mapping) else None
    if entry.get("term") != _layer_display_or_structured(term_layer, term):
        raise SurfaceFieldInvariantViolation(
            f"{entry.get('entry_id', '<unknown>')}: term does not match display layer"
        )

    alt_layers = layers.get("alt_terms", {}) if isinstance(layers, Mapping) else {}
    for idx, value in enumerate(entry.get("alt_terms", []) or []):
        layer = alt_layers.get(str(idx)) if isinstance(alt_layers, Mapping) else None
        if value != _layer_display_or_structured(layer, str(value)):
            raise SurfaceFieldInvariantViolation(
                f"{entry.get('entry_id', '<unknown>')}: alt_terms.{idx} does not match display layer"
            )

    blocks = [str(value) for value in entry.get("definition_blocks", [])]
    block_layers = layers.get("definition_blocks", {}) if isinstance(layers, Mapping) else {}
    # A-F9: the invariant requires content-hash key match. The old code had
    # a display-equality fallback that silently accepted a layer keyed by
    # a wrong hash if its stored display happened to equal the current
    # block text. That weakened the whole point of stable block_ids:
    # parser drift could pass the gate without rekey_review_state running.
    for idx, layer_key in enumerate(definition_block_ids(blocks)):
        layer = block_layers.get(layer_key) if isinstance(block_layers, Mapping) else None
        if layer is None and block_layers:
            raise SurfaceFieldInvariantViolation(
                f"{entry.get('entry_id', '<unknown>')}: definition_blocks.{idx} has no layer for block_id {layer_key}"
            )
        if blocks[idx] != _layer_display_or_structured(layer, blocks[idx]):
            raise SurfaceFieldInvariantViolation(
                f"{entry.get('entry_id', '<unknown>')}: definition_blocks.{layer_key} does not match display layer"
            )


def assert_record_surface_field_invariant(record: Mapping[str, Any]) -> None:
    """Validate the surface-field invariant for every entry in a record.

    Records that pre-date Phase C have no meta.text_layer_shape and no layers
    field; the invariant is a no-op for them. Layer-bearing records without
    a declared shape still raise.
    """
    meta = record.get("meta", {})
    shape = meta.get("text_layer_shape") if isinstance(meta, Mapping) else None
    if not isinstance(shape, str):
        for entry in record.get("data", []) or []:
            if isinstance(entry, Mapping) and entry.get("layers"):
                raise SurfaceFieldInvariantViolation(
                    "record has layer-bearing entries but meta.text_layer_shape is missing"
                )
        return
    for entry in record.get("data", []) or []:
        assert_surface_field_invariant(entry, text_layer_shape=shape)


__all__ = [
    "SOURCE_RAW_ORIGINS",
    "SurfaceFieldInvariantViolation",
    "apply_layers_to_entry",
    "assert_record_surface_field_invariant",
    "assert_surface_field_invariant",
    "build_reference_layers",
    "build_single_field_layers",
    "definition_block_ids",
    "sparse_layer_entry",
]
