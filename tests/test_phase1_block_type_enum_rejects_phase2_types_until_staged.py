"""R35 — Phase 1 block_type enum must exclude Phase 2 confession/catechism types.

article, question, answer re-enter the enum in the same change that ships
corpus + producer + consumer + tests for Phase 2 confession/catechism work
(ADR-0010 amended staged-introduction rule).  Until then the Phase 1 schema
must actively reject them.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


_BASE_BLOCK = {
    "block_id": "b_0001aaaa",
    "block_id_history": [],
    "block_type": "paragraph",
    "language": "en",
    "language_confidence": 0.99,
    "language_alternates": [],
    "language_segments": [],
    "original_text": "Text.",
    "modern_text": "Text.",
    "annotations": {},
    "source_pages": [],
    "attested_by": ["ccel/test/work/1900/thml"],
    "disagreements": [],
    "structural_disagreements": [],
    "modernisations": [],
}

_BASE_META = {
    "id": "test.work.1900",
    "title": "Test Work",
    "author_slug": "test",
    "author_display_name": "Test Author",
    "author_birth_year": None,
    "author_death_year": None,
    "original_publication_year": 1900,
    "language": "en",
    "tradition": ["evangelical"],
    "license": "public-domain",
    "schema_type": "reconciled_record",
    "schema_version": "3.0.0",
    "edition": "1900",
    "pd_anchor": "ccel/test/work/1900/thml",
    "modernisation_ruleset_version": None,
    "attestation_summary": {
        "block_count": 1,
        "fully_attested_blocks": 1,
        "blocks_with_disagreements": 0,
        "blocks_with_structural_disagreements": 0,
    },
}

_PHASE1_VALID_TYPES = [
    "paragraph",
    "heading",
    "lemma",
    "list_item",
    "footnote",
    "verse_line",
    "headword",
    "quote",
    "table_row",
]

_PHASE2_TYPES = ["article", "question", "answer"]


@pytest.mark.parametrize("block_type", _PHASE1_VALID_TYPES)
def test_phase1_block_types_accepted(block_type: str) -> None:
    schema = _schema("reconciled_record")
    instance = {
        "meta": _BASE_META,
        "blocks": [{**_BASE_BLOCK, "block_type": block_type}],
        "match_explanations": [],
    }
    jsonschema.validate(instance=instance, schema=schema)


@pytest.mark.parametrize("block_type", _PHASE2_TYPES)
def test_phase2_block_types_rejected_in_phase1(block_type: str) -> None:
    schema = _schema("reconciled_record")
    instance = {
        "meta": _BASE_META,
        "blocks": [{**_BASE_BLOCK, "block_type": block_type}],
        "match_explanations": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)
