from __future__ import annotations

import json
from pathlib import Path

from build.tools.render_schema_reference import (
    SchemaIndex,
    collect_enum_rows,
    collect_field_rows,
    load_schema_sources,
    render_html,
    sample_value,
    top_level_sources,
)


def _write_schema(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_collect_field_rows_resolves_external_refs(tmp_path: Path) -> None:
    schemas_dir = tmp_path / "schemas"
    _write_schema(
        schemas_dir / "_defs" / "person.schema.json",
        {
            "$id": "https://example.test/person.schema.json",
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
            "additionalProperties": False,
        },
    )
    _write_schema(
        schemas_dir / "thing.schema.json",
        {
            "$id": "https://example.test/thing.schema.json",
            "title": "Thing",
            "type": "object",
            "required": ["owner"],
            "properties": {
                "owner": {"$ref": "https://example.test/person.schema.json"}
            },
        },
    )

    sources = load_schema_sources(schemas_dir)
    top_source = top_level_sources(sources, schemas_dir)[0]
    rows = collect_field_rows(top_source.schema, SchemaIndex(sources), top_source.schema)

    assert ("$.owner.name", True, "string") in {
        (row.path, row.required, row.type_label) for row in rows
    }


def test_collect_enum_rows_finds_array_item_enums(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": ["source", "review"]},
            }
        },
    }

    rows = collect_enum_rows(schema, SchemaIndex([]), schema)

    assert rows[0].path == "$.tags"
    assert rows[0].values == ("source", "review")


def test_sample_value_prefers_required_fields_and_consts(tmp_path: Path) -> None:
    schema = {
        "type": "object",
        "required": ["schema_version", "count"],
        "properties": {
            "schema_version": {"const": "sample-v1"},
            "count": {"type": "integer", "minimum": 1},
            "optional": {"type": "string"},
        },
    }

    sample = sample_value(schema, SchemaIndex([]), schema)

    assert sample == {
        "schema_version": "sample-v1",
        "count": 1,
        "optional": "string",
    }


def test_render_html_includes_schema_names_and_search(tmp_path: Path) -> None:
    schema_path = tmp_path / "schemas" / "sample.schema.json"
    _write_schema(
        schema_path,
        {
            "$id": "https://example.test/sample.schema.json",
            "title": "Sample Schema",
            "description": "Readable shape.",
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}},
        },
    )
    sources = load_schema_sources(tmp_path / "schemas")

    html = render_html(top_level_sources(sources, tmp_path / "schemas"), SchemaIndex(sources), tmp_path)

    assert "Sample Schema" in html
    assert "schemaSearch" in html
    assert "sample.schema.json" in html
