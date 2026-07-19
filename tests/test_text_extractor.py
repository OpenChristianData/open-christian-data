from __future__ import annotations

from pathlib import Path

import pytest

from ocd_kernel.lib.text_extractor import effective_resource_type, extract_text


SCHEMAS_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _commentary_record(**meta_overrides):
    meta = {"schema_type": "commentary", "id": "sample"}
    meta.update(meta_overrides)
    return {
        "meta": meta,
        "data": [
            {"entry_id": "e1", "commentary_text": "First text."},
            {"entry_id": "e2", "commentary_text": "Second text."},
        ],
    }


def _reference_record(**meta_overrides):
    meta = {"schema_type": "reference_entry", "id": "sample"}
    meta.update(meta_overrides)
    return {
        "meta": meta,
        "data": [
            {
                "entry_id": "r1",
                "term": "Aaron",
                "alt_terms": ["Aharon"],
                "definition_blocks": ["Definition one.", {"text": "Definition two."}],
            }
        ],
    }


def test_commentary_record_yields_commentary_text_fields() -> None:
    assert list(extract_text(_commentary_record(), SCHEMAS_DIR)) == [
        ("e1", "commentary_text", "First text.", None, []),
        ("e2", "commentary_text", "Second text.", None, []),
    ]


def test_reference_entry_record_yields_reference_fields() -> None:
    extracted = list(extract_text(_reference_record(), SCHEMAS_DIR))

    assert ("r1", "term", "Aaron", None, []) in extracted
    assert ("r1", "alt_terms.0", "Aharon", None, []) in extracted
    assert ("r1", "definition_blocks.0", "Definition one.", None, []) in extracted
    assert ("r1", "definition_blocks.1", "Definition two.", None, []) in extracted


def test_unknown_resource_type_raises_value_error() -> None:
    with pytest.raises(ValueError):
        list(extract_text(_commentary_record(resource_type="unknown"), SCHEMAS_DIR))


def test_effective_resource_type_override_wins() -> None:
    assert effective_resource_type(_commentary_record(resource_type="encyclopedia"), SCHEMAS_DIR) == "encyclopedia"


def test_effective_resource_type_uses_schema_default_when_absent() -> None:
    assert effective_resource_type(_reference_record(), SCHEMAS_DIR) == "encyclopedia"
