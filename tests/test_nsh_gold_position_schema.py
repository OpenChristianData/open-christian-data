from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
PAGE_SHA256 = "sha256:" + "1" * 64
TOKEN_ID = "ot-sha256:" + "2" * 64


def _schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    assert path.exists(), f"{path.name} is missing"
    return json.loads(path.read_text(encoding="utf-8"))


def _accepts(schema: dict, instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=schema)


def _rejects(schema: dict, instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


def _valid_pending_position() -> dict:
    return {
        "schema_version": "nsh-gold-position-v1",
        "page_image_sha256": PAGE_SHA256,
        "bbox": {"x": 120, "y": 340, "w": 52, "h": 18},
        "edition_page_key": {"section": "body", "anchor": 100, "ordinal": 0},
        "volume": 5,
        "canonical_leaf_id": 122,
        "position_id": "vol_05:page_0100:body:c1:l012:p004",
        "derived_observation_token_ids": [TOKEN_ID],
        "context_window": {"left_reading": "the", "right_reading": None},
        "crop_ref": "crops/vol_05/page_0100/p004.png",
        "stratum": "degraded",
        "script": "latin",
        "token_class": "proper_name",
        "baseline_candidates": {
            "tesseract": "modem",
            "ia-abbyy-v1": "modern",
            "kraken": None,
        },
        "alternate_candidates": {"ia-abbyy-haucgoog-v1": "modern"},
        "prefilled_true_reading": "modern",
        "review_status": "pending",
    }


def test_pending_position_without_truth_or_provenance_validates() -> None:
    _accepts(_schema("nsh-gold-position-v1"), _valid_pending_position())


def test_verified_position_with_truth_and_provenance_validates() -> None:
    position = copy.deepcopy(_valid_pending_position())
    position["review_status"] = "verified"
    position["true_reading"] = "modern"
    position["provenance"] = {
        "actor_id": "reviewer-1",
        "timestamp": "2026-07-02T00:00:00Z",
        "source_basis": "page_image_crop",
    }

    _accepts(_schema("nsh-gold-position-v1"), position)


def test_unverifiable_position_with_null_truth_and_reason_validates() -> None:
    position = copy.deepcopy(_valid_pending_position())
    position["review_status"] = "unverifiable"
    position["true_reading"] = None
    position["unverifiable_reason"] = "scan is unreadable at this crop"
    position["provenance"] = {
        "actor_id": "reviewer-1",
        "timestamp": "2026-07-02T00:00:00Z",
        "source_basis": "page_image_crop",
    }

    _accepts(_schema("nsh-gold-position-v1"), position)


def test_verified_position_with_empty_truth_rejected() -> None:
    position = copy.deepcopy(_valid_pending_position())
    position["review_status"] = "verified"
    position["true_reading"] = ""
    position["provenance"] = {
        "actor_id": "reviewer-1",
        "timestamp": "2026-07-02T00:00:00Z",
        "source_basis": "page_image_crop",
    }

    _rejects(_schema("nsh-gold-position-v1"), position)


def test_unverifiable_position_with_non_null_truth_rejected() -> None:
    position = copy.deepcopy(_valid_pending_position())
    position["review_status"] = "unverifiable"
    position["true_reading"] = "modern"
    position["unverifiable_reason"] = "scan is unreadable at this crop"
    position["provenance"] = {
        "actor_id": "reviewer-1",
        "timestamp": "2026-07-02T00:00:00Z",
        "source_basis": "page_image_crop",
    }

    _rejects(_schema("nsh-gold-position-v1"), position)


def test_bad_token_class_rejected() -> None:
    position = _valid_pending_position()
    position["token_class"] = "scripture_reference"

    _rejects(_schema("nsh-gold-position-v1"), position)


def test_missing_page_image_sha256_rejected() -> None:
    position = _valid_pending_position()
    del position["page_image_sha256"]

    _rejects(_schema("nsh-gold-position-v1"), position)


def test_unknown_top_level_property_rejected() -> None:
    position = _valid_pending_position()
    position["unexpected"] = True

    _rejects(_schema("nsh-gold-position-v1"), position)
