"""schema_enums.py
Read enum values from JSON schema files at module load time.

For import-time constants, prefer build.lib._generated_enums and regenerate it
with build/tools/generate_schema_enums.py. Use get_enum() when code needs an
ad hoc schema lookup that should still resolve directly from schemas/v1/.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# schemas/v1/ is two levels above build/lib/
_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas" / "v1"


@lru_cache(maxsize=None)
def _load_schema(schema_name: str) -> dict:
    """Load and cache a JSON schema by name (reads the file once per process).

    Args:
        schema_name: Schema filename without the ``.schema.json`` extension.

    Returns:
        Parsed JSON as a dict.  The dict is shared across callers — do not mutate.
    """
    path = _SCHEMAS_DIR / f"{schema_name}.schema.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_ref(schema: dict, node: dict) -> dict:
    """If node is a JSON Schema $ref pointing within the same document, resolve it."""
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/"):
            parts = ref[2:].split("/")
            result: dict = schema
            for part in parts:
                result = result[part]
            return result
    return node


def get_enum(schema_name: str, *path: str) -> frozenset[str]:
    """Return the enum values for a nested property path in a JSON schema.

    Walks ``properties.path[0].properties.path[1]...`` and returns the enum
    at the leaf.  Handles both ``{"enum": [...]}`` directly on the property
    and ``{"items": {"enum": [...]}}`` for array properties.  ``null`` values
    are excluded from the result.

    Args:
        schema_name: Schema filename without the ``.schema.json`` extension
                     (e.g. ``"structured_text"``).
        *path:       Property keys to walk in order
                     (e.g. ``"meta"``, ``"tradition"``).

    Returns:
        frozenset of non-null string enum values.

    Raises:
        FileNotFoundError: If the schema file does not exist.
        KeyError: If the path does not resolve to an enum in the schema,
                  with a message naming the schema and the failing key.

    Examples:
        >>> get_enum("structured_text", "meta", "tradition")
        frozenset({'reformed', 'lutheran', ...})
        >>> get_enum("structured_text", "data", "work_kind")
        frozenset({'theological-work', 'treatise', ...})
    """
    schema = _load_schema(schema_name)
    node: dict = schema
    walked: list[str] = []

    for key in path:
        node = _resolve_ref(schema, node)
        # For array nodes (type: array), descend into items before looking for properties.
        if "properties" not in node and "items" in node and isinstance(node["items"], dict):
            node = _resolve_ref(schema, node["items"])
        if "properties" not in node:
            raise KeyError(
                f"Schema '{schema_name}': node at path {walked!r} has no "
                f"'properties' block (attempting to reach key '{key}'). "
                f"Node keys: {sorted(node.keys())}"
            )
        props = node["properties"]
        if key not in props:
            raise KeyError(
                f"Schema '{schema_name}': key '{key}' not found in properties "
                f"at path {walked!r}. "
                f"Available keys: {sorted(props.keys())}"
            )
        node = _resolve_ref(schema, props[key])
        walked.append(key)

    # Leaf: direct enum
    if "enum" in node:
        return frozenset(v for v in node["enum"] if v is not None)

    # Leaf: array with items enum
    if "items" in node and isinstance(node["items"], dict) and "enum" in node["items"]:
        return frozenset(v for v in node["items"]["enum"] if v is not None)

    raise KeyError(
        f"Schema '{schema_name}': path {path!r} does not lead to an enum. "
        f"Leaf node keys: {sorted(node.keys())}"
    )

