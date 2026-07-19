from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from ocd_kernel.lib.schema_enums import resolve_schema_path

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
TOKEN_ID = "ot-sha256:" + "1" * 64


def _schema(name: str) -> dict:
    path = resolve_schema_path(name)
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
