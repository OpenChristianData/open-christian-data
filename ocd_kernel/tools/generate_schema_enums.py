"""Generate schema enum constants from one or more schemas/v1 directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from ocd_kernel.lib.schema_enums import kernel_schemas_dir, resolve_schemas_dir  # noqa: E402

KERNEL_ROOT = Path(__file__).resolve().parents[1]
KERNEL_SCHEMAS_DIR = kernel_schemas_dir()
OUTPUT_PATH = KERNEL_ROOT / "lib" / "_generated_enums.py"
SCHEMA_GLOB = "*.schema.json"
RESOURCE_TYPE_ORDER = [
    "commentary",
    "encyclopedia",
    "bible_text",
    "catechism_qa",
    "church_fathers",
    "devotional",
    "doctrinal_document",
    "hymn_collection",
    "prayer",
    "sermon",
    "structured_text",
    "topical_reference",
]
COVERAGE_STRATEGIES = ["scriptural_canon", "entry_inventory", "none"]
TEXT_LAYER_SHAPES = ["single_field", "multi_field"]


def _constantize(*parts: str) -> str:
    cleaned = []
    for part in parts:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", part).strip("_")
        cleaned.append(normalized.upper())
    return "__".join(cleaned)


def _schema_name(schema_path: Path) -> str:
    return schema_path.name.removesuffix(".schema.json")


def _enum_values(node: dict) -> list[str] | None:
    if "enum" in node and isinstance(node["enum"], list):
        return sorted(value for value in node["enum"] if value is not None)
    items = node.get("items")
    if isinstance(items, dict) and "enum" in items and isinstance(items["enum"], list):
        return sorted(value for value in items["enum"] if value is not None)
    return None


def _walk_properties(node: dict, path_parts: tuple[str, ...], constants: dict[str, list[str]]) -> None:
    enum_values = _enum_values(node)
    if enum_values is not None and path_parts:
        constants[_constantize(*path_parts)] = enum_values

    properties = node.get("properties")
    if isinstance(properties, dict):
        for key, child in sorted(properties.items()):
            if isinstance(child, dict):
                _walk_properties(child, path_parts + (key,), constants)

    defs = node.get("$defs")
    if isinstance(defs, dict):
        for key, child in sorted(defs.items()):
            if isinstance(child, dict):
                _walk_properties(child, path_parts + ("defs", key), constants)

    items = node.get("items")
    if isinstance(items, dict):
        item_props = items.get("properties")
        if isinstance(item_props, dict):
            for key, child in sorted(item_props.items()):
                if isinstance(child, dict):
                    _walk_properties(child, path_parts + (key,), constants)
        item_defs = items.get("$defs")
        if isinstance(item_defs, dict):
            for key, child in sorted(item_defs.items()):
                if isinstance(child, dict):
                    _walk_properties(child, path_parts + ("defs", key), constants)


def _default_schemas_dirs() -> list[Path]:
    if KERNEL_SCHEMAS_DIR.is_dir():
        return [KERNEL_SCHEMAS_DIR]
    return [resolve_schemas_dir()]


def _normalise_schema_dirs(
    schemas_dirs: list[Path] | tuple[Path, ...] | None = None,
    *,
    schemas_dir: Path | None = None,
) -> list[Path]:
    if schemas_dirs is not None and schemas_dir is not None:
        raise ValueError("Pass either schemas_dirs or schemas_dir, not both.")
    if schemas_dir is not None:
        return [schemas_dir]
    if schemas_dirs is None:
        return _default_schemas_dirs()
    return list(schemas_dirs)


def collect_generated_constants(
    schemas_dirs: list[Path] | tuple[Path, ...] | None = None,
    *,
    schemas_dir: Path | None = None,
) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    constants: dict[str, list[str]] = {}
    schema_hashes: list[tuple[str, str]] = []
    resource_types: set[str] = set()
    seen_schema_names: dict[str, Path] = {}
    for current_schemas_dir in _normalise_schema_dirs(schemas_dirs, schemas_dir=schemas_dir):
        for schema_path in sorted(current_schemas_dir.glob(SCHEMA_GLOB)):
            if "_defs" in schema_path.parts:
                continue
            schema_name = _schema_name(schema_path)
            previous = seen_schema_names.get(schema_name)
            if previous is not None:
                raise ValueError(
                    f"Duplicate schema name {schema_name!r}: {previous} and {schema_path}"
                )
            seen_schema_names[schema_name] = schema_path
            schema_text = schema_path.read_text(encoding="utf-8")
            schema_bytes = schema_text.encode("utf-8")
            schema_hashes.append((schema_path.name, hashlib.sha256(schema_bytes).hexdigest()))
            schema = json.loads(schema_text)
            default_resource_type = schema.get("x-ocd-default-resource-type")
            if isinstance(default_resource_type, str):
                resource_types.add(default_resource_type)
            local_constants: dict[str, list[str]] = {}
            _walk_properties(schema, (schema_name,), local_constants)
            for constant_name, enum_values in sorted(local_constants.items()):
                constants[constant_name] = enum_values
    if resource_types:
        ordered_resource_types = [value for value in RESOURCE_TYPE_ORDER if value in resource_types]
        ordered_resource_types.extend(sorted(resource_types.difference(ordered_resource_types)))
        constants["RESOURCE_TYPES"] = ordered_resource_types
    constants["COVERAGE_STRATEGIES"] = COVERAGE_STRATEGIES
    constants["TEXT_LAYER_SHAPES"] = TEXT_LAYER_SHAPES
    return constants, schema_hashes


def render_generated_module(
    constants: dict[str, list[str]],
    schema_hashes: list[tuple[str, str]],
) -> str:
    lines = [
        '"""GENERATED DO NOT EDIT.',
        "",
        "Schema sha256s:",
    ]
    for schema_name, digest in schema_hashes:
        lines.append(f"  - {schema_name}: {digest}")
    lines.extend(
        [
            '"""',
            "",
            "from __future__ import annotations",
            "",
        ]
    )

    for constant_name, enum_values in sorted(constants.items()):
        lines.append(f"{constant_name} = frozenset({enum_values!r})")

    lines.append("")
    return "\n".join(lines)


def write_generated_module(
    output_path: Path = OUTPUT_PATH,
    schemas_dirs: list[Path] | tuple[Path, ...] | None = None,
    *,
    schemas_dir: Path | None = None,
) -> None:
    constants, schema_hashes = collect_generated_constants(
        schemas_dirs=schemas_dirs,
        schemas_dir=schemas_dir,
    )
    rendered = render_generated_module(constants, schema_hashes)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Path to the generated Python module.",
    )
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        action="append",
        help="Directory containing *.schema.json files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write_generated_module(output_path=args.output, schemas_dirs=args.schemas_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
