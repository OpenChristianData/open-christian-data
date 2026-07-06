from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline.abbyy_lineage_value_study import wilson_ci  # noqa: E402
from build.tools.ocr_pipeline.nsh_gold_consumers import (  # noqa: E402
    m15_false_correction_proxy,
    score_abbyy_lineage,
    track_c_agreement,
)

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"
PAGE_SHA256 = "sha256:" + "1" * 64


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _base_record(position: int) -> dict:
    return {
        "schema_version": "nsh-gold-position-v1",
        "page_image_sha256": PAGE_SHA256,
        "bbox": {"x": position * 10, "y": 20, "w": 8, "h": 12},
        "edition_page_key": {"section": "body", "anchor": 10, "ordinal": 0},
        "volume": 2,
        "position_id": f"vol_02:page_0010:body:c1:l001:p{position:03d}",
        "crop_ref": f"crops/vol_02/page_0010/p{position:03d}.png",
        "stratum": "clean",
        "script": "latin",
        "token_class": "none",
        "baseline_candidates": {},
        "alternate_candidates": {},
        "review_status": "pending",
    }


def _verified(
    position: int,
    *,
    true_reading: str,
    token_class: str,
    script: str,
    baseline_candidates: dict[str, str | None],
    alternate_candidates: dict[str, str | None] | None = None,
) -> dict:
    record = _base_record(position)
    record.update(
        {
            "script": script,
            "token_class": token_class,
            "baseline_candidates": baseline_candidates,
            "alternate_candidates": alternate_candidates or {},
            "review_status": "verified",
            "true_reading": true_reading,
            "provenance": {
                "actor_id": "reviewer-1",
                "timestamp": "2026-07-02T00:00:00Z",
                "source_basis": "page_image_crop",
            },
        }
    )
    return record


def _fixture_records() -> list[dict]:
    pending = _base_record(90)
    pending["baseline_candidates"] = {"tesseract": "wrong", "azure": "wrong"}

    unverifiable = _base_record(91)
    unverifiable.update(
        {
            "review_status": "unverifiable",
            "true_reading": None,
            "unverifiable_reason": "scan is unreadable at this crop",
            "provenance": {
                "actor_id": "reviewer-1",
                "timestamp": "2026-07-02T00:00:00Z",
                "source_basis": "page_image_crop",
            },
        }
    )

    return [
        _verified(
            1,
            true_reading="modern",
            token_class="proper_name",
            script="latin",
            baseline_candidates={
                "tesseract": "modem",
                "azure": "modem",
                "kraken": None,
            },
            alternate_candidates={"ia-abbyy-haucgoog-v1": "modern"},
        ),
        _verified(
            2,
            true_reading="church",
            token_class="proper_name",
            script="latin",
            baseline_candidates={
                "tesseract": "church",
                "azure": "church",
                "kraken": "clurch",
            },
            alternate_candidates={"ia-abbyy-haucgoog-v1": "church"},
        ),
        _verified(
            3,
            true_reading="42",
            token_class="number",
            script="latin",
            baseline_candidates={
                "tesseract": "42",
                "azure": None,
                "kraken": "43",
            },
            alternate_candidates={"ia-abbyy-haucgoog-v1": "44"},
        ),
        _verified(
            4,
            true_reading="logos",
            token_class="greek",
            script="greek",
            baseline_candidates={
                "tesseract": "logos",
                "azure": "log0s",
                "kraken": "logos",
            },
        ),
        pending,
        unverifiable,
    ]


def test_fixture_records_validate_against_schema() -> None:
    schema = _schema("nsh-gold-position-v1")

    for record in _fixture_records():
        jsonschema.validate(instance=record, schema=schema)


def test_score_abbyy_lineage_counts_verified_records_only() -> None:
    result = score_abbyy_lineage(_fixture_records())

    assert result == {
        "n": 4,
        "unique_recovery": 1,
        "redundant_recovery": 1,
        "noise_added": 1,
        "unique_recovery_rate": 0.25,
        "unique_recovery_ci": wilson_ci(1, 4),
    }


def test_track_c_agreement_groups_by_token_class_and_script() -> None:
    result = track_c_agreement(_fixture_records())

    assert result == {
        "__overall__": {"n": 4, "engine_agrees": 3, "agreement_rate": 0.75},
        "greek|greek": {"n": 1, "engine_agrees": 1, "agreement_rate": 1.0},
        "number|latin": {"n": 1, "engine_agrees": 1, "agreement_rate": 1.0},
        "proper_name|latin": {"n": 2, "engine_agrees": 1, "agreement_rate": 0.5},
    }


def test_m15_false_correction_proxy_uses_consensus_and_abstains_on_ties() -> None:
    result = m15_false_correction_proxy(_fixture_records())

    assert result == {
        "__overall__": {
            "n": 4,
            "false_corrections": 1,
            "false_correction_rate": 0.25,
            "false_correction_ci": wilson_ci(1, 4),
        },
        "greek": {
            "n": 1,
            "false_corrections": 0,
            "false_correction_rate": 0.0,
            "false_correction_ci": wilson_ci(0, 1),
        },
        "number": {
            "n": 1,
            "false_corrections": 0,
            "false_correction_rate": 0.0,
            "false_correction_ci": wilson_ci(0, 1),
        },
        "proper_name": {
            "n": 2,
            "false_corrections": 1,
            "false_correction_rate": 0.5,
            "false_correction_ci": wilson_ci(1, 2),
        },
    }


def test_m15_false_correction_proxy_accepts_actual_chosen_reading_callable() -> None:
    records = copy.deepcopy(_fixture_records())

    result = m15_false_correction_proxy(
        records,
        chosen_reading=lambda record: record["true_reading"]
        if record["position_id"].endswith("p001")
        else None,
    )

    assert result["__overall__"]["n"] == 4
    assert result["__overall__"]["false_corrections"] == 0
    assert result["proper_name"]["false_corrections"] == 0
