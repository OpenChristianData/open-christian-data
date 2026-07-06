"""Diff sparse text layers without positional drift."""

from __future__ import annotations

from typing import Any, Mapping, TypedDict


class LayerDiffOp(TypedDict):
    field_path: str
    layer_a_value: str | None
    layer_b_value: str | None
    op: str


def _is_layer_entry(value: Any) -> bool:
    return isinstance(value, Mapping) and "structured" in value and "display" in value


def _entry_value(value: Any) -> str | None:
    if value is None:
        return None
    if _is_layer_entry(value):
        return str(value.get("display"))
    return str(value)


def _walk(layer: Mapping[str, Any]) -> dict[str, str]:
    paths: dict[str, str] = {}
    if "commentary_text" in layer:
        value = _entry_value(layer.get("commentary_text"))
        if value is not None:
            paths["commentary_text"] = value

    if "term" in layer:
        value = _entry_value(layer.get("term"))
        if value is not None:
            paths["term"] = value

    alt_terms = layer.get("alt_terms")
    if isinstance(alt_terms, Mapping):
        for key in sorted(alt_terms, key=_natural_key):
            value = _entry_value(alt_terms.get(key))
            if value is not None:
                paths[f"alt_terms.{key}"] = value

    definition_blocks = layer.get("definition_blocks")
    if isinstance(definition_blocks, Mapping):
        for key in sorted(definition_blocks):
            value = _entry_value(definition_blocks.get(key))
            if value is not None:
                paths[f"definition_blocks.{key}"] = value
    return paths


def _natural_key(value: Any) -> tuple[int, str]:
    text = str(value)
    return (int(text), text) if text.isdigit() else (10**9, text)


def diff_layers(layer_a: dict, layer_b: dict) -> list[LayerDiffOp]:
    """Return field-path keyed differences between two layer dictionaries."""
    values_a = _walk(layer_a)
    values_b = _walk(layer_b)
    ops: list[LayerDiffOp] = []
    for path in sorted(set(values_a) | set(values_b)):
        a_value = values_a.get(path)
        b_value = values_b.get(path)
        if a_value is None:
            op = "added"
        elif b_value is None:
            op = "removed"
        elif a_value == b_value:
            op = "equal"
        else:
            op = "changed"
        ops.append(
            {
                "field_path": path,
                "layer_a_value": a_value,
                "layer_b_value": b_value,
                "op": op,
            }
        )
    return ops


__all__ = ["LayerDiffOp", "diff_layers"]
