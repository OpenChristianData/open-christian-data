"""test_contributor_schema.py
Validates the Contributor $def and its use in v1 schemas.

Five invariants:
  1. A well-formed contributor object (name + role) passes validation
  2. A bare string (old format) fails validation
  3. An object missing the required 'name' field fails validation
  4. An empty contributors list is valid
  5. A contributor object with all optional fields passes
"""
import json
from pathlib import Path

import pytest
import jsonschema
from referencing import Registry, Resource
import referencing.jsonschema

from ocd_kernel.lib.schema_enums import kernel_schemas_dir, resolve_schema_path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_V1 = REPO_ROOT / "schemas" / "v1"
KERNEL_SCHEMAS_V1 = kernel_schemas_dir()
CONTRIBUTOR_DEF_PATH = SCHEMAS_V1 / "_defs" / "contributor.schema.json"
KERNEL_CONTRIBUTOR_DEF_PATH = KERNEL_SCHEMAS_V1 / "_defs" / "contributor.schema.json"
STRUCTURED_TEXT_PATH = resolve_schema_path("structured_text")


def _build_registry() -> Registry:
    """Build a Registry containing the contributor def and all v1 schemas."""
    resources = []
    contributor_def = json.loads(KERNEL_CONTRIBUTOR_DEF_PATH.read_text(encoding="utf-8"))
    resources.append(
        Resource.from_contents(
            contributor_def, default_specification=referencing.jsonschema.DRAFT202012
        )
    )
    for schema_file in SCHEMAS_V1.glob("*.schema.json"):
        schema = json.loads(schema_file.read_text(encoding="utf-8"))
        resources.append(
            Resource.from_contents(
                schema, default_specification=referencing.jsonschema.DRAFT202012
            )
        )
    return Registry().with_resources([(r.id(), r) for r in resources])


def test_contributor_def_copies_are_byte_identical() -> None:
    assert CONTRIBUTOR_DEF_PATH.read_bytes() == KERNEL_CONTRIBUTOR_DEF_PATH.read_bytes()


def _make_minimal_structured_text(contributors: list) -> dict:
    """Build the minimal valid structured_text record for testing contributors.

    Matches schemas/v1/structured_text.schema.json exactly:
    - meta required: id, title, author, language, tradition, license,
      schema_type, schema_version, completeness, provenance
    - provenance required (additionalProperties: false): source_url, source_format,
      source_edition, download_date, source_hash, processing_method,
      processing_script_version, processing_date
    - data required: work_id, work_kind, sections (minItems: 1)
    - section required: section_type
    """
    return {
        "meta": {
            "id": "test-resource-id",
            "title": "Test Title",
            "author": "Test Author",
            "author_id": None,
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": contributors,
            "original_publication_year": None,
            "language": "en",
            "original_language": None,
            "tradition": ["reformed"],
            "tradition_notes": None,
            "era": None,
            "audience": None,
            "license": "cc0-1.0",
            "schema_type": "structured_text",
            "schema_version": "1.0.0",
            "completeness": "full",
            "provenance": {
                "source_url": "https://example.com/source",
                "source_format": "text/plain",
                "source_edition": "1st edition",
                "download_date": "2026-01-01",
                "source_hash": "sha256:" + "a" * 64,
                "processing_method": "manual",
                "processing_script_version": "1.0.0",
                "processing_date": "2026-01-01",
                "notes": None,
            },
        },
        "data": {
            "work_id": "test-work",
            "work_kind": "theological-work",
            "sections": [
                {
                    "section_type": "chapter",
                    "label": None,
                    "title": None,
                    "content_blocks": ["Sample paragraph text."],
                    "scripture_references": [],
                    "children": [],
                }
            ],
        },
    }


@pytest.fixture(scope="module")
def registry() -> Registry:
    return _build_registry()


@pytest.fixture(scope="module")
def structured_text_schema() -> dict:
    return json.loads(STRUCTURED_TEXT_PATH.read_text(encoding="utf-8"))


def test_contributor_object_passes(registry, structured_text_schema):
    """A well-formed contributor object {name, role} validates successfully."""
    record = _make_minimal_structured_text([{"name": "Jane Doe", "role": "translator"}])
    validator = jsonschema.Draft202012Validator(structured_text_schema, registry=registry)
    validator.validate(record)  # must not raise


def test_contributor_string_fails(registry, structured_text_schema):
    """A bare string contributor (old string[] format) fails validation."""
    record = _make_minimal_structured_text(["Jane Doe"])
    validator = jsonschema.Draft202012Validator(structured_text_schema, registry=registry)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(record)


def test_contributor_missing_name_fails(registry, structured_text_schema):
    """A contributor object missing the required 'name' field fails validation."""
    record = _make_minimal_structured_text([{"role": "translator"}])
    validator = jsonschema.Draft202012Validator(structured_text_schema, registry=registry)
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(record)


def test_contributor_empty_list_passes(registry, structured_text_schema):
    """An empty contributors list is valid (contributors is optional)."""
    record = _make_minimal_structured_text([])
    validator = jsonschema.Draft202012Validator(structured_text_schema, registry=registry)
    validator.validate(record)  # must not raise


def test_contributor_full_object_passes(registry, structured_text_schema):
    """A contributor object with all optional fields (name/role/affiliation/url) passes."""
    record = _make_minimal_structured_text(
        [
            {
                "name": "Emmett O'Donnell",
                "role": "transcriber",
                "affiliation": "SpurgeonGems (spurgeongems.org)",
                "url": "http://www.spurgeongems.org/",
            }
        ]
    )
    validator = jsonschema.Draft202012Validator(structured_text_schema, registry=registry)
    validator.validate(record)  # must not raise
