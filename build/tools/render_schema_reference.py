"""Render a human-readable reference for schemas/v1/*.schema.json.

The JSON Schema files remain the source of truth. This tool creates a static
HTML page that is easier to scan during design and review.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402

SCHEMAS_DIR = REPO_ROOT / "schemas" / "v1"
OUTPUT_PATH = REPO_ROOT / "docs" / "schema-reference.html"
SCHEMA_GLOB = "*.schema.json"
MAX_SAMPLE_DEPTH = 5
MAX_OPTIONAL_SAMPLE_FIELDS = 4


@dataclass(frozen=True)
class SchemaSource:
    path: Path
    name: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class FieldRow:
    path: str
    required: bool
    type_label: str
    rules: str
    description: str


@dataclass(frozen=True)
class EnumRow:
    path: str
    values: tuple[str, ...]


class SchemaIndex:
    """Small resolver for local and repo URL JSON Schema refs."""

    def __init__(self, sources: Sequence[SchemaSource]) -> None:
        self.by_name = {source.path.name: source.schema for source in sources}
        self.by_id = {
            schema_id: source.schema
            for source in sources
            if isinstance((schema_id := source.schema.get("$id")), str)
        }

    def resolve(self, ref: str, root: Mapping[str, Any]) -> Any:
        if ref.startswith("#"):
            return _resolve_pointer(root, ref[1:])

        base, _, fragment = ref.partition("#")
        schema = self.by_id.get(base)
        if schema is None:
            schema = self.by_name.get(Path(base).name)
        if schema is None:
            return {"description": f"Unresolved ref: {ref}"}
        if fragment:
            return _resolve_pointer(schema, fragment)
        return schema


def _resolve_pointer(document: Mapping[str, Any], pointer: str) -> Any:
    if pointer in ("", "/"):
        return document
    node: Any = document
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or part not in node:
            return {"description": f"Unresolved pointer: {pointer}"}
        node = node[part]
    return node


def _schema_name(schema_path: Path) -> str:
    return schema_path.name.removesuffix(".schema.json")


def load_schema_sources(schemas_dir: Path = SCHEMAS_DIR) -> list[SchemaSource]:
    sources: list[SchemaSource] = []
    for schema_path in sorted(schemas_dir.rglob(SCHEMA_GLOB)):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        sources.append(
            SchemaSource(
                path=schema_path,
                name=_schema_name(schema_path),
                schema=schema,
            )
        )
    return sources


def top_level_sources(sources: Sequence[SchemaSource], schemas_dir: Path = SCHEMAS_DIR) -> list[SchemaSource]:
    return [
        source
        for source in sources
        if source.path.parent.resolve() == schemas_dir.resolve()
    ]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _scalar_type_label(value: Any) -> str:
    if isinstance(value, str):
        return value
    return type(value).__name__


def type_label(node: Mapping[str, Any], index: SchemaIndex, root: Mapping[str, Any]) -> str:
    if "$ref" in node and isinstance(node["$ref"], str):
        ref = node["$ref"]
        resolved = index.resolve(ref, root)
        if isinstance(resolved, Mapping):
            label = type_label(resolved, index, root)
            ref_name = ref.rsplit("/", 1)[-1].removesuffix(".schema.json")
            return f"{ref_name} ({label})"
        return ref

    if "const" in node:
        return f"const {node['const']!r}"

    if "enum" in node and isinstance(node["enum"], list):
        enum_values = [value for value in node["enum"] if value is not None]
        if len(enum_values) <= 3:
            return "enum " + " | ".join(repr(value) for value in enum_values)
        return f"enum ({len(enum_values)} values)"

    if "oneOf" in node:
        return f"oneOf ({len(_as_list(node.get('oneOf')))} options)"
    if "anyOf" in node:
        return f"anyOf ({len(_as_list(node.get('anyOf')))} options)"
    if "allOf" in node:
        return f"allOf ({len(_as_list(node.get('allOf')))} parts)"

    node_type = node.get("type")
    if isinstance(node_type, list):
        return " | ".join(_scalar_type_label(value) for value in node_type)
    if isinstance(node_type, str):
        if node_type == "array" and isinstance(node.get("items"), Mapping):
            return f"array<{type_label(node['items'], index, root)}>"
        return node_type

    if "properties" in node:
        return "object"
    if "items" in node:
        return "array"
    return "any"


def _format_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True)


def _rule_parts(node: Mapping[str, Any]) -> list[str]:
    parts: list[str] = []
    if node.get("additionalProperties") is False:
        parts.append("no extra fields")
    if "minItems" in node:
        parts.append(f"minItems {node['minItems']}")
    if "maxItems" in node:
        parts.append(f"maxItems {node['maxItems']}")
    if "minimum" in node:
        parts.append(f"min {node['minimum']}")
    if "maximum" in node:
        parts.append(f"max {node['maximum']}")
    if "minLength" in node:
        parts.append(f"minLength {node['minLength']}")
    if "maxLength" in node:
        parts.append(f"maxLength {node['maxLength']}")
    if "pattern" in node:
        parts.append(f"pattern {node['pattern']}")
    if "format" in node:
        parts.append(f"format {node['format']}")
    if "oneOf" in node:
        parts.append(f"oneOf {len(_as_list(node.get('oneOf')))}")
    if "anyOf" in node:
        parts.append(f"anyOf {len(_as_list(node.get('anyOf')))}")
    if "allOf" in node:
        parts.append(f"allOf {len(_as_list(node.get('allOf')))}")
    if "const" in node:
        parts.append(f"const {_format_value(node['const'])}")
    return parts


def _enum_values(node: Mapping[str, Any]) -> tuple[str, ...]:
    if "enum" in node and isinstance(node["enum"], list):
        return tuple(_format_value(value) for value in node["enum"])
    items = node.get("items")
    if isinstance(items, Mapping) and isinstance(items.get("enum"), list):
        return tuple(_format_value(value) for value in items["enum"])
    return ()


def collect_field_rows(
    node: Mapping[str, Any],
    index: SchemaIndex,
    root: Mapping[str, Any],
    path: str = "$",
    required: bool = True,
    seen_refs: frozenset[str] = frozenset(),
) -> list[FieldRow]:
    if "$ref" in node and isinstance(node["$ref"], str):
        ref = node["$ref"]
        if ref in seen_refs:
            return [
                FieldRow(
                    path=path,
                    required=required,
                    type_label=ref,
                    rules="recursive ref",
                    description=str(node.get("description", "")),
                )
            ]
        resolved = index.resolve(ref, root)
        if isinstance(resolved, Mapping):
            return collect_field_rows(
                resolved,
                index,
                root,
                path=path,
                required=required,
                seen_refs=seen_refs | {ref},
            )

    rows = [
        FieldRow(
            path=path,
            required=required,
            type_label=type_label(node, index, root),
            rules=", ".join(_rule_parts(node)),
            description=str(node.get("description", "")),
        )
    ]

    properties = node.get("properties")
    required_fields = set(node.get("required", []))
    if isinstance(properties, Mapping):
        for key, child in properties.items():
            if isinstance(child, Mapping):
                rows.extend(
                    collect_field_rows(
                        child,
                        index,
                        root,
                        path=f"{path}.{key}",
                        required=key in required_fields,
                        seen_refs=seen_refs,
                    )
                )

    items = node.get("items")
    if isinstance(items, Mapping):
        rows.extend(
            collect_field_rows(
                items,
                index,
                root,
                path=f"{path}[]",
                required=required,
                seen_refs=seen_refs,
            )
        )

    return rows


def collect_enum_rows(
    node: Mapping[str, Any],
    index: SchemaIndex,
    root: Mapping[str, Any],
    path: str = "$",
    seen_refs: frozenset[str] = frozenset(),
) -> list[EnumRow]:
    if "$ref" in node and isinstance(node["$ref"], str):
        ref = node["$ref"]
        if ref in seen_refs:
            return []
        resolved = index.resolve(ref, root)
        if isinstance(resolved, Mapping):
            return collect_enum_rows(resolved, index, root, path, seen_refs | {ref})

    rows: list[EnumRow] = []
    values = _enum_values(node)
    if values:
        rows.append(EnumRow(path=path, values=values))
    if "const" in node:
        rows.append(EnumRow(path=path, values=(_format_value(node["const"]),)))

    properties = node.get("properties")
    if isinstance(properties, Mapping):
        for key, child in properties.items():
            if isinstance(child, Mapping):
                rows.extend(collect_enum_rows(child, index, root, f"{path}.{key}", seen_refs))

    items = node.get("items")
    if isinstance(items, Mapping):
        rows.extend(collect_enum_rows(items, index, root, f"{path}[]", seen_refs))

    defs = node.get("$defs")
    if isinstance(defs, Mapping):
        for key, child in defs.items():
            if isinstance(child, Mapping):
                rows.extend(collect_enum_rows(child, index, root, f"#/$defs/{key}", seen_refs))

    return rows


def _string_sample(node: Mapping[str, Any]) -> str:
    if "const" in node:
        return str(node["const"])
    enum_values = _enum_values(node)
    if enum_values:
        return enum_values[0]
    if "pattern" in node:
        pattern = str(node["pattern"])
        if "sha256" in pattern or "{64}" in pattern:
            return "0" * 64
        if "[a-z]{2,3}" in pattern:
            return "en"
    if node.get("format") == "date-time":
        return "2026-07-07T00:00:00+00:00"
    if node.get("format") == "date":
        return "2026-07-07"
    return "string"


def sample_value(
    node: Mapping[str, Any],
    index: SchemaIndex,
    root: Mapping[str, Any],
    depth: int = 0,
    seen_refs: frozenset[str] = frozenset(),
) -> Any:
    if depth >= MAX_SAMPLE_DEPTH:
        return "..."

    if "$ref" in node and isinstance(node["$ref"], str):
        ref = node["$ref"]
        if ref in seen_refs:
            return "recursive-ref"
        resolved = index.resolve(ref, root)
        if isinstance(resolved, Mapping):
            return sample_value(resolved, index, root, depth + 1, seen_refs | {ref})
        return ref

    for keyword in ("oneOf", "anyOf", "allOf"):
        options = node.get(keyword)
        if isinstance(options, list) and options and isinstance(options[0], Mapping):
            return sample_value(options[0], index, root, depth + 1, seen_refs)

    if "const" in node:
        return node["const"]
    values = _enum_values(node)
    if values:
        return values[0]

    node_type = node.get("type")
    if isinstance(node_type, list):
        non_null = [value for value in node_type if value != "null"]
        node_type = non_null[0] if non_null else "null"

    if node_type == "object" or "properties" in node:
        properties = node.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        required_fields = [key for key in node.get("required", []) if key in properties]
        optional_fields = [
            key
            for key in properties.keys()
            if key not in required_fields
        ][:MAX_OPTIONAL_SAMPLE_FIELDS]
        keys = required_fields + optional_fields
        return {
            key: sample_value(properties[key], index, root, depth + 1, seen_refs)
            for key in keys
            if isinstance(properties[key], Mapping)
        }

    if node_type == "array" or "items" in node:
        items = node.get("items")
        if isinstance(items, Mapping):
            return [sample_value(items, index, root, depth + 1, seen_refs)]
        return []

    if node_type == "integer":
        return 1
    if node_type == "number":
        return 1.0
    if node_type == "boolean":
        return True
    if node_type == "null":
        return None
    return _string_sample(node)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _schema_badges(schema: Mapping[str, Any]) -> list[str]:
    badges: list[str] = []
    if isinstance(schema.get("x-ocd-schema-version"), str):
        badges.append(f"version {schema['x-ocd-schema-version']}")
    if isinstance(schema.get("x-ocd-default-resource-type"), str):
        badges.append(f"resource {schema['x-ocd-default-resource-type']}")
    if schema.get("additionalProperties") is False:
        badges.append("closed object")
    if "oneOf" in schema:
        badges.append(f"oneOf {len(_as_list(schema.get('oneOf')))}")
    return badges


def _html_table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def render_schema_section(source: SchemaSource, index: SchemaIndex, repo_root: Path) -> str:
    schema = source.schema
    field_rows = collect_field_rows(schema, index, schema)
    enum_rows = collect_enum_rows(schema, index, schema)
    sample = sample_value(schema, index, schema)
    rel_path = source.path.relative_to(repo_root).as_posix()
    title = str(schema.get("title") or source.name)
    schema_id = str(schema.get("$id", ""))
    slug = _slug(source.name)
    badges = "".join(f"<span>{escape(badge)}</span>" for badge in _schema_badges(schema))

    field_table = _html_table(
        ("Path", "Required", "Type", "Rules", "Description"),
        (
            (
                f"<code>{escape(row.path)}</code>",
                "yes" if row.required else "",
                escape(row.type_label),
                escape(row.rules),
                escape(row.description),
            )
            for row in field_rows
        ),
    )

    enum_table = _html_table(
        ("Path", "Values"),
        (
            (
                f"<code>{escape(row.path)}</code>",
                "<span class=\"enum-list\">" + escape(", ".join(row.values)) + "</span>",
            )
            for row in enum_rows
        ),
    ) if enum_rows else "<p class=\"muted\">No enum or const fields found.</p>"

    return f"""
<section class="schema-card" id="{escape(slug)}" data-schema-name="{escape(source.name)}">
  <h2>{escape(title)}</h2>
  <div class="meta-line"><code>{escape(rel_path)}</code></div>
  <p>{escape(str(schema.get("description", "")))}</p>
  <div class="badges">{badges}</div>
  <dl class="schema-meta">
    <dt>Schema id</dt><dd><code>{escape(schema_id)}</code></dd>
    <dt>Top-level required fields</dt><dd>{escape(", ".join(schema.get("required", [])) or "None")}</dd>
  </dl>
  <details open>
    <summary>Example shape</summary>
    <pre><code>{escape(json.dumps(sample, indent=2, ensure_ascii=True))}</code></pre>
  </details>
  <details>
    <summary>Field map ({len(field_rows)} rows)</summary>
    {field_table}
  </details>
  <details>
    <summary>Enums and constants ({len(enum_rows)} rows)</summary>
    {enum_table}
  </details>
</section>
"""


def render_html(
    sources: Sequence[SchemaSource],
    index: SchemaIndex,
    repo_root: Path = REPO_ROOT,
) -> str:
    nav_items = "\n".join(
        f'<a href="#{escape(_slug(source.name))}" data-schema-link="{escape(source.name)}">'
        f"{escape(source.name)}</a>"
        for source in sources
    )
    sections = "\n".join(render_schema_section(source, index, repo_root) for source in sources)
    schema_count = len(sources)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Open Christian Data Schema Reference</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1f2933;
      --muted: #5b6775;
      --line: #d7dde5;
      --panel: #ffffff;
      --back: #f5f7fa;
      --accent: #276749;
      --accent-soft: #e7f4ed;
      --code: #f0f3f7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--back);
      color: var(--ink);
      font: 15px/1.5 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: inherit; }}
    code, pre {{ font-family: "Cascadia Mono", Consolas, monospace; }}
    .layout {{
      display: grid;
      grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      overflow: auto;
      padding: 20px;
      border-right: 1px solid var(--line);
      background: #eef2f5;
    }}
    main {{ padding: 28px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; line-height: 1.1; }}
    h2 {{ margin: 0; font-size: 22px; line-height: 1.2; }}
    .intro {{ max-width: 860px; margin-bottom: 24px; color: var(--muted); }}
    .nav-title {{ margin: 0 0 12px; font-weight: 700; }}
    .search {{
      width: 100%;
      margin-bottom: 14px;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      font: inherit;
    }}
    nav {{ display: grid; gap: 4px; }}
    nav a {{
      padding: 7px 9px;
      border-radius: 6px;
      color: #344054;
      text-decoration: none;
      overflow-wrap: anywhere;
    }}
    nav a:hover {{ background: #dfe7ed; }}
    .schema-card {{
      margin: 0 0 22px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .meta-line, .muted {{ color: var(--muted); }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0; }}
    .badges span {{
      padding: 3px 8px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
    }}
    .schema-meta {{
      display: grid;
      grid-template-columns: 150px minmax(0, 1fr);
      gap: 4px 12px;
      margin: 12px 0;
    }}
    .schema-meta dt {{ color: var(--muted); }}
    .schema-meta dd {{ margin: 0; overflow-wrap: anywhere; }}
    details {{
      margin-top: 12px;
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
    }}
    pre {{
      max-height: 520px;
      overflow: auto;
      padding: 14px;
      border-radius: 6px;
      background: var(--code);
      font-size: 13px;
    }}
    table {{
      width: 100%;
      margin-top: 12px;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      padding: 8px;
      border: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }}
    th {{ background: #f6f8fa; }}
    td:first-child {{ width: 30%; }}
    .enum-list {{ overflow-wrap: anywhere; }}
    @media (max-width: 860px) {{
      .layout {{ display: block; }}
      aside {{
        position: static;
        height: auto;
        max-height: 50vh;
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }}
      main {{ padding: 18px; }}
      .schema-meta {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <p class="nav-title">Schemas ({schema_count})</p>
      <input class="search" id="schemaSearch" type="search" placeholder="Filter schemas">
      <nav id="schemaNav">{nav_items}</nav>
    </aside>
    <main>
      <h1>Open Christian Data Schema Reference</h1>
      <p class="intro">
        Generated from <code>schemas/v1/*.schema.json</code>. Use this page to review the
        shape, required fields, enum values, and sample payload structure without reading raw JSON Schema.
      </p>
      {sections}
    </main>
  </div>
  <script>
    const search = document.querySelector("#schemaSearch");
    const cards = [...document.querySelectorAll("[data-schema-name]")];
    const links = [...document.querySelectorAll("[data-schema-link]")];
    search.addEventListener("input", () => {{
      const needle = search.value.trim().toLowerCase();
      for (const card of cards) {{
        const match = card.dataset.schemaName.toLowerCase().includes(needle);
        card.hidden = !match;
      }}
      for (const link of links) {{
        const match = link.dataset.schemaLink.toLowerCase().includes(needle);
        link.hidden = !match;
      }}
    }});
  </script>
</body>
</html>
"""


def write_schema_reference(
    output_path: Path = OUTPUT_PATH,
    schemas_dir: Path = SCHEMAS_DIR,
) -> None:
    sources = load_schema_sources(schemas_dir)
    index = SchemaIndex(sources)
    rendered = render_html(top_level_sources(sources, schemas_dir), index)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Path to write the generated HTML reference.",
    )
    parser.add_argument(
        "--schemas-dir",
        type=Path,
        default=SCHEMAS_DIR,
        help="Directory containing schema files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    write_schema_reference(output_path=args.output, schemas_dir=args.schemas_dir)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
