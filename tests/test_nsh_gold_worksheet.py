from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_pipeline.nsh_gold_worksheet import (  # noqa: E402
    build_worksheet_positions,
    select_hard_positions,
)

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _candidate(reading: str, families: list[str]) -> dict:
    return {
        "candidate_key": reading,
        "raw_reading": reading,
        "attesting_families": families,
    }


def _position(
    position_id: str,
    *,
    order: int,
    script: str,
    candidates: list[dict],
) -> dict:
    return {
        "position_id": position_id,
        "zone": {"zone_type": "body", "position_order": order},
        "script": {"text_level": {"label": script}},
        "reference_bbox": {
            "x": 100 + order * 10,
            "y": 200,
            "w": 40,
            "h": 18,
        },
        "candidate_set": candidates,
    }


def _wct_page() -> dict:
    return {
        "schema_version": "word-confusion-table-v1",
        "volume_id": "vol_02",
        "page_id": "page_0010",
        "source_image": {
            "path": "raw/je/vol_02/page_0010.jpg",
            "sha256": "a" * 64,
        },
        "positions": [
            _position(
                "vol_02:page_0010:body:c1:l001:p001",
                order=1,
                script="latin",
                candidates=[
                    _candidate("modern", ["tesseract", "abbyy"]),
                    _candidate("modem", ["azure-ai-vision"]),
                    _candidate("rnoden", ["kraken"]),
                    _candidate("ignored", ["tesseract"]),
                ],
            ),
            _position(
                "vol_02:page_0010:body:c1:l001:p002",
                order=2,
                script="latin",
                candidates=[
                    _candidate("church", ["tesseract", "azure-ai-vision"]),
                    _candidate("clurch", ["kraken"]),
                    _candidate("church", ["abbyy"]),
                ],
            ),
            _position(
                "vol_02:page_0010:body:c1:l001:p003",
                order=3,
                script="greek",
                candidates=[_candidate("logos", ["tesseract"])],
            ),
            _position(
                "vol_02:page_0010:body:c1:l001:p004",
                order=4,
                script="latin",
                candidates=[_candidate("42", ["tesseract", "azure-ai-vision", "abbyy"])],
            ),
        ],
    }


def test_build_worksheet_positions_maps_live_wct_shape_to_pending_schema() -> None:
    records = build_worksheet_positions(_wct_page(), volume=2)
    schema = _schema("nsh-gold-position-v1")

    assert len(records) == 4
    for record in records:
        jsonschema.validate(instance=record, schema=schema)
        assert record["review_status"] == "pending"
        assert "true_reading" not in record
        assert "provenance" not in record
        assert "context_window" not in record
        assert "prefilled_true_reading" not in record

    hard = records[0]
    assert hard["page_image_sha256"] == "sha256:" + "a" * 64
    assert hard["edition_page_key"] == {"section": "body", "anchor": 10, "ordinal": 0}
    assert hard["bbox"] == {"x": 110, "y": 200, "w": 40, "h": 18}
    assert hard["volume"] == 2
    assert hard["canonical_leaf_id"] is None
    assert hard["derived_observation_token_ids"] == []
    assert hard["script"] == "latin"
    assert hard["token_class"] == "none"
    assert hard["baseline_candidates"] == {
        "tesseract": "modern",
        "abbyy": "modern",
        "azure": "modem",
        "kraken": "rnoden",
    }
    assert hard["alternate_candidates"] == {}
    assert hard["stratum"] == "greek_hebrew"
    assert hard["crop_ref"] == (
        "crops/vol_02/page_0010/vol_02_page_0010_body_c1_l001_p001.png"
    )

    assert records[2]["script"] == "greek"
    assert records[2]["token_class"] == "greek"
    assert records[3]["token_class"] == "number"


def test_build_worksheet_positions_uses_clean_stratum_without_greek_or_hebrew() -> None:
    page = copy.deepcopy(_wct_page())
    page["positions"] = page["positions"][:2]

    records = build_worksheet_positions(page, volume=2)

    assert {record["stratum"] for record in records} == {"clean"}


def test_select_hard_positions_returns_only_non_abbyy_disagreements() -> None:
    records = build_worksheet_positions(_wct_page(), volume=2)

    hard_records = select_hard_positions(records)

    assert [record["position_id"] for record in hard_records] == [
        "vol_02:page_0010:body:c1:l001:p001",
        "vol_02:page_0010:body:c1:l001:p003",
    ]
