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
TOKEN_ID = "ot-sha256:" + "1" * 64


def _schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.schema.json"
    assert path.exists(), f"{path.name} is missing"
    return json.loads(path.read_text(encoding="utf-8"))


def _accepts(schema: dict, instance: dict) -> None:
    jsonschema.validate(instance=instance, schema=schema)


def _rejects(schema: dict, instance: dict) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


def _valid_gold_record() -> dict:
    return {
        "schema_version": "gold-record-v1",
        "gold_id": "gold-vol01-page0001-token0001",
        "volume": 1,
        "unit": "token",
        "verification": "verified",
        "output_status": "recognised_from_page",
        "manifest_id": "sm-vol01-tesseract",
        "rendering_id": "ia-tesseract/schaff/vol01",
        "page_native_id": "1",
        "page_sequence": 1,
        "block_id": "block-0001",
        "observation_token_id": TOKEN_ID,
        "ground_truth_text": "Grace",
        "provenance": {
            "actor_id": "reviewer-1",
            "timestamp": "2026-05-29T00:00:00Z",
            "source_basis": "scan leaf and Schaff-Herzog 1908 edition",
        },
    }


def _valid_gold_sample_manifest() -> dict:
    return {
        "schema_version": "gold-sample-manifest-v1",
        "sample_id": "gold-sample-vol01-dominant-failure",
        "volume": 1,
        "sample_role": "dominant_failure",
        "created_at": "2026-05-29T00:00:00Z",
        "strata_definition": {
            "dimensions": [
                {
                    "name": "zone_type",
                    "source": "sidecar blocks[].block_type",
                    "availability": "derived_at_s1",
                    "buckets": ["text", "diagnostic"],
                }
            ]
        },
        "strata": [
            {
                "stratum_key": {"zone_type": "text"},
                "target_count": 2,
                "actual_count": 2,
                "selected_pages": [
                    "reports/gold/vol_01/pages/page_0001.json",
                    "reports/gold/vol_01/pages/page_0002.json",
                ],
                "coverage_flag": "covered",
            }
        ],
    }


def test_verified_gold_record_with_non_empty_text_validates() -> None:
    _accepts(_schema("gold-record-v1"), _valid_gold_record())


def test_verified_gold_record_missing_or_empty_text_rejected() -> None:
    schema = _schema("gold-record-v1")
    missing = copy.deepcopy(_valid_gold_record())
    del missing["ground_truth_text"]
    _rejects(schema, missing)

    empty = copy.deepcopy(_valid_gold_record())
    empty["ground_truth_text"] = ""
    _rejects(schema, empty)

    whitespace = copy.deepcopy(_valid_gold_record())
    whitespace["ground_truth_text"] = "   \t"
    _rejects(schema, whitespace)


def test_unverifiable_gold_record_with_null_text_and_reason_validates() -> None:
    record = copy.deepcopy(_valid_gold_record())
    record["verification"] = "unverifiable"
    record["output_status"] = "unresolved"
    record["ground_truth_text"] = None
    record["unverifiable_reason"] = "scan is unreadable at this token"

    _accepts(_schema("gold-record-v1"), record)


def test_unverifiable_gold_record_with_non_null_text_rejected() -> None:
    record = copy.deepcopy(_valid_gold_record())
    record["verification"] = "unverifiable"
    record["output_status"] = "unresolved"
    record["ground_truth_text"] = "guessed text"
    record["unverifiable_reason"] = "scan is unreadable at this token"

    _rejects(_schema("gold-record-v1"), record)


def test_gold_sample_manifest_validates() -> None:
    _accepts(_schema("gold-sample-manifest-v1"), _valid_gold_sample_manifest())


def test_gold_sample_manifest_rejects_absolute_selected_page_path() -> None:
    manifest = _valid_gold_sample_manifest()
    manifest["strata"][0]["selected_pages"] = ["C:/absolute/page_0001.json"]

    _rejects(_schema("gold-sample-manifest-v1"), manifest)
