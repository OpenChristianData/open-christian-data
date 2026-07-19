"""Tests for match_explanations schema compliance (discriminated union).

These tests use jsonschema directly against the locked schema. They do NOT
require the reconcile module and should PASS in the RED phase.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ocd_kernel.lib.schema_enums import resolve_schema_path

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas" / "v1"
RECONCILED_SCHEMA = json.loads(resolve_schema_path("reconciled_record").read_text(encoding="utf-8"))
ME_SCHEMA = RECONCILED_SCHEMA["$defs"]["match_explanation"]


def _validate(instance):
    jsonschema.validate(instance=instance, schema=ME_SCHEMA, resolver=jsonschema.RefResolver(
        base_uri=RECONCILED_SCHEMA.get("$id", ""), referrer=RECONCILED_SCHEMA
    ))


def _rejects(instance):
    with pytest.raises(jsonschema.ValidationError):
        _validate(instance)


def test_match_explanation_edge_match_schema_valid():
    """Valid edge_match match_explanation validates against schema."""
    _validate({
        "match_explanation_id": "mx_a1b2c3d4",
        "scope": "block_pair_edge",
        "block_id_pair": ["b_0001", "b_0002"],
        "signals": [
            {"name": "text_similarity", "raw_score": 0.95, "weight": 25, "contribution": 23},
            {"name": "annotation_key", "raw_score": 1.0, "weight": 30, "contribution": 30},
        ],
        "total_score": 53,
        "decision": {
            "kind": "edge_match",
            "bucket": "mid_low",
            "score_range": "45-59",
            "action": "no_cluster",
            "surface": "required",
        },
    })


def test_match_explanation_edge_match_rejects_extra_field():
    """Extra field surface_reason on edge_match decision is rejected (additionalProperties: false)."""
    _rejects({
        "match_explanation_id": "mx_a1b2c3d4",
        "scope": "block_pair_edge",
        "block_id_pair": ["b_0001", "b_0002"],
        "signals": [],
        "total_score": 53,
        "decision": {
            "kind": "edge_match",
            "bucket": "mid_low",
            "score_range": "45-59",
            "action": "no_cluster",
            "surface": "required",
            "surface_reason": "footnote",  # NOT in schema
        },
    })


def test_match_explanation_reading_score_schema_valid():
    """Valid reading_score match_explanation validates."""
    _validate({
        "match_explanation_id": "mx_r1s2t3u4",
        "scope": "disagreement",
        "block_id": "b_0042",
        "signals": [
            {"name": "pd_anchor_base", "raw_score": 4.0, "weight": 1, "contribution": 4},
        ],
        "total_score": 4,
        "decision": {
            "kind": "reading_score",
            "pd_only_gap": 1.0,
            "winning_has_pd_support": True,
            "classification": "ocr_noise",
            "advisory_score": 0.5,
        },
    })


def test_match_explanation_structural_rule_schema_valid():
    """Valid structural_rule match_explanation validates."""
    _validate({
        "match_explanation_id": "mx_s1t2r3u4",
        "scope": "structural_disagreement",
        "block_id": "b_0099",
        "signals": [],
        "total_score": 0,
        "decision": {
            "kind": "structural_rule",
            "rule_applied": "anchor_wins_n2",
            "outcome": "anchor_structure_canonical",
        },
    })


def test_match_explanation_wrong_kind_rejected():
    """Unknown decision kind fails oneOf validation."""
    _rejects({
        "match_explanation_id": "mx_bad",
        "scope": "disagreement",
        "block_id": "b_0001",
        "signals": [],
        "total_score": 0,
        "decision": {"kind": "bogus_kind", "some_field": "value"},
    })
