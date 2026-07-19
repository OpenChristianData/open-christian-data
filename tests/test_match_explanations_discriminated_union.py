"""ADR-0013 — match_explanations[] decision.kind discriminated union.

The decision field is a discriminated union keyed on decision.kind:
  - edge_match     (block-pair edge alignment decision)
  - reading_score  (disagreement reading selection)
  - structural_rule (structural disagreement resolution)

Any other kind must fail schema validation.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ocd_kernel.lib.schema_enums import resolve_schema_path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads(resolve_schema_path(name).read_text(encoding="utf-8"))


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

_EDGE_MATCH_EXPLANATION = {
    "match_explanation_id": "mx_a1b2c3d4",
    "scope": "block_pair_edge",
    "block_id_pair": ["b_0001aaaa", "b_0002bbbb"],
    "signals": [
        {"name": "annotation_key", "raw_score": 1.0, "weight": 30, "contribution": 30},
        {"name": "text_similarity", "raw_score": 0.92, "weight": 25, "contribution": 23},
    ],
    "total_score": 53,
    "decision": {
        "kind": "edge_match",
        "bucket": "high",
        "score_range": ">=78",
        "action": "cluster",
        "surface": "silent",
    },
}

_READING_SCORE_EXPLANATION = {
    "match_explanation_id": "mx_b2c3d4e5",
    "scope": "disagreement",
    "block_id": "b_0001aaaa",
    "signals": [
        {"name": "pd_anchor_base", "raw_score": 4.0, "weight": 1.0, "contribution": 4.0},
        {"name": "pd_attestor_base", "raw_score": 3.0, "weight": 1.0, "contribution": 3.0},
    ],
    "total_score": 7.0,
    "decision": {
        "kind": "reading_score",
        "pd_only_gap": 1.0,
        "winning_has_pd_support": True,
        "classification": "ocr_noise",
        "advisory_score": 0.0,
    },
}

_STRUCTURAL_RULE_EXPLANATION = {
    "match_explanation_id": "mx_c3d4e5f6",
    "scope": "structural_disagreement",
    "block_id": "b_0001aaaa",
    "signals": [],
    "total_score": 0,
    "decision": {
        "kind": "structural_rule",
        "rule_applied": "2_of_3_keeps_split",
        "outcome": "accepted",
    },
}


def _make_record(match_explanations: list) -> dict:
    return {
        "meta": _BASE_META,
        "blocks": [_BASE_BLOCK],
        "match_explanations": match_explanations,
    }


def test_edge_match_explanation_accepted() -> None:
    schema = _schema("reconciled_record")
    jsonschema.validate(instance=_make_record([_EDGE_MATCH_EXPLANATION]), schema=schema)


def test_reading_score_explanation_accepted() -> None:
    schema = _schema("reconciled_record")
    jsonschema.validate(instance=_make_record([_READING_SCORE_EXPLANATION]), schema=schema)


def test_structural_rule_explanation_accepted() -> None:
    schema = _schema("reconciled_record")
    jsonschema.validate(instance=_make_record([_STRUCTURAL_RULE_EXPLANATION]), schema=schema)


def test_unknown_decision_kind_rejected() -> None:
    schema = _schema("reconciled_record")
    bad_explanation = {
        **_EDGE_MATCH_EXPLANATION,
        "decision": {**_EDGE_MATCH_EXPLANATION["decision"], "kind": "magic_wand"},
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_make_record([bad_explanation]), schema=schema)


def test_missing_decision_kind_rejected() -> None:
    schema = _schema("reconciled_record")
    bad_decision = {k: v for k, v in _EDGE_MATCH_EXPLANATION["decision"].items() if k != "kind"}
    bad_explanation = {**_EDGE_MATCH_EXPLANATION, "decision": bad_decision}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_make_record([bad_explanation]), schema=schema)
