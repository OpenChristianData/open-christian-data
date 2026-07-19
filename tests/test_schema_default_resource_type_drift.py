from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib._generated_enums import RESOURCE_TYPES
from ocd_kernel.lib.schema_enums import resolve_schema_path


SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"
CONTENT_SCHEMAS = [
    "commentary",
    "reference_entry",
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


@pytest.mark.parametrize("schema_name", CONTENT_SCHEMAS)
def test_content_schema_declares_default_resource_type(schema_name: str) -> None:
    with resolve_schema_path(schema_name).open(encoding="utf-8") as handle:
        schema = json.load(handle)

    assert schema["x-ocd-default-resource-type"] in RESOURCE_TYPES
