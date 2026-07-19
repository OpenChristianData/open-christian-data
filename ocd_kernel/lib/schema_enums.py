"""Read enum values from JSON schema files."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_SCHEMAS_ENV_VAR = "OCD_SCHEMAS_DIR"
_PACKAGE_KERNEL_SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"
_REGISTERED_SCHEMA_DIRS: list[Path] = []


def kernel_schemas_dir() -> Path:
    """Return the package-relative shared schema directory."""
    if _PACKAGE_KERNEL_SCHEMAS_DIR.is_dir():
        return _PACKAGE_KERNEL_SCHEMAS_DIR
    start = Path(__file__).resolve()
    for parent in start.parents:
        candidate = parent / "ocd_kernel" / "schemas" / "v1"
        if candidate.is_dir():
            return candidate
    return _PACKAGE_KERNEL_SCHEMAS_DIR


def register_schemas_dir(path: Path | str) -> None:
    """Register a consumer repository's schemas/v1 directory for future lookups."""
    candidate = Path(path).expanduser().resolve()
    if candidate not in _REGISTERED_SCHEMA_DIRS:
        _REGISTERED_SCHEMA_DIRS.append(candidate)


def _parent_walk_consumer_dir() -> Path | None:
    start = Path(__file__).resolve()
    kernel_dir = kernel_schemas_dir().resolve()
    for parent in (start.parent, *start.parents):
        candidate = (parent / "schemas" / "v1").resolve()
        if candidate == kernel_dir:
            continue
        if candidate.is_dir():
            return candidate
    return None


def _consumer_schema_dirs() -> list[Path]:
    env_value = os.environ.get(_SCHEMAS_ENV_VAR)
    if env_value:
        return [Path(env_value).expanduser().resolve()]

    candidates = [path for path in _REGISTERED_SCHEMA_DIRS]
    fallback = _parent_walk_consumer_dir()
    if fallback is not None:
        candidates.append(fallback)

    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_schemas_dir() -> Path:
    """Resolve the consumer repository schemas/v1 directory lazily."""
    for candidate in _consumer_schema_dirs():
        if candidate.is_dir():
            return candidate
    searched = ", ".join(str(path) for path in _consumer_schema_dirs()) or "<none>"
    raise RuntimeError(
        "Could not resolve consumer schemas/v1 for ocd_kernel. "
        f"Set {_SCHEMAS_ENV_VAR} to the consumer repository schemas/v1 directory. "
        f"Searched: {searched}"
    )


def resolve_schema_path(schema_name: str) -> Path:
    """Resolve a schema by name, searching kernel-shared schemas before consumer schemas."""
    normalized = schema_name.removesuffix(".schema.json")
    searched_dirs: list[Path] = []
    candidate_dirs = [kernel_schemas_dir(), *_consumer_schema_dirs()]
    for schema_dir in candidate_dirs:
        resolved_dir = schema_dir.resolve()
        if resolved_dir in searched_dirs:
            continue
        searched_dirs.append(resolved_dir)
        path = resolved_dir / f"{normalized}.schema.json"
        if path.exists():
            return path
    searched = ", ".join(str(path) for path in searched_dirs) or "<none>"
    raise FileNotFoundError(
        f"Schema {normalized!r} not found. Searched schemas/v1 directories: {searched}"
    )


def _legacy_default_schemas_dir() -> Path:
    """Return the pre-split single schema dir until the kernel schema dir exists."""
    kernel_dir = kernel_schemas_dir()
    if kernel_dir.is_dir():
        return kernel_dir
    try:
        return resolve_schemas_dir()
    except RuntimeError:
        return kernel_dir


@lru_cache(maxsize=None)
def _load_schema(schema_path: str) -> dict:
    """Load and cache a JSON schema by resolved absolute path string."""
    path = Path(schema_path)
    if not path.is_file():
        raise FileNotFoundError(path)
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
    schema_path = resolve_schema_path(schema_name).resolve()
    schema = _load_schema(str(schema_path))
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

