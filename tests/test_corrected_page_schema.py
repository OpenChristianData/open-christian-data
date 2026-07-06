from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.corrected_page_semantic_validator import (  # noqa: E402
    CorrectedPageSemanticError,
    validate_corrected_page,
    validate_released_readings,
)
from build.lib.schema_enums import get_enum  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _engine_provenance(text: str, source_id: str = "abbyy") -> list[dict]:
    return [
        {
            "grapheme": char,
            "source_type": "engine_family",
            "source_id": source_id,
        }
        for char in text
    ]


def _l0_reading(text: str) -> dict:
    return {
        "derivation_level": "L0",
        "origin_kind": "observed",
        "text": text,
        "scores": {"confidence": 1.0},
    }


def _l1_reading(text: str) -> dict:
    return {
        "derivation_level": "L1",
        "origin_kind": "machine_composed",
        "text": text,
        "scores": {"confidence": 0.9, "character_vote_score": 0.9},
        "character_provenance": _engine_provenance(text),
    }


def _sidecar_from_wct_page() -> dict:
    wct_path = REPO_ROOT / "reports" / "wct" / "vol_01" / "page_0010.json"
    if not wct_path.exists():
        # Live vol_01 WCT quarantined in R-final.3 (stale); restored by full WCT rebuild.
        pytest.skip("vol_01 WCT quarantined (R-final.3); restored by the full WCT rebuild")
    wct_page = json.loads(wct_path.read_text(encoding="utf-8"))
    positions = []
    for position in wct_page["positions"]:
        if not position["candidate_set"]:
            reading = _l0_reading("")
            chosen_index = 0
        else:
            reading = _l0_reading(position["candidate_set"][0]["raw_reading"])
            chosen_index = 0
        positions.append(
            {
                "position_id": position["position_id"],
                "protected_class": "none",
                "derivable_readings": [reading],
                "chosen_reading_index": chosen_index,
                "chosen_action": "release_observed",
            }
        )
    return {
        "schema_type": "corrected_page",
        "schema_version": "corrected-page-v1",
        "work_id": wct_page["work_id"],
        "volume_id": wct_page["volume_id"],
        "page_id": wct_page["page_id"],
        "source_wct_page": {"path": "reports/wct/vol_01/page_0010.json"},
        "positions": positions,
    }


def test_corrected_page_sidecar_built_from_vol01_page0010_validates() -> None:
    sidecar = _sidecar_from_wct_page()
    jsonschema.validate(instance=sidecar, schema=_schema("corrected-page-v1"))
    validate_corrected_page(sidecar)
    assert len(sidecar["positions"]) == 1142


def test_released_l1_without_character_provenance_fails_l0_observed_passes() -> None:
    validate_released_readings(
        [
            {
                "canonical_derivation_level": "L0",
                "canonical_origin_kind": "observed",
                "canonical_text": "Grace",
            }
        ]
    )

    missing = {
        "canonical_derivation_level": "L1",
        "canonical_origin_kind": "machine_composed",
        "canonical_text": "Grace",
    }
    with pytest.raises(CorrectedPageSemanticError, match="requires character_provenance"):
        validate_released_readings([missing])

    malformed = {
        "canonical_derivation_level": "L1",
        "canonical_origin_kind": "machine_composed",
        "canonical_text": "Grace",
        "character_provenance": [{"source_type": "engine_family"}],
    }
    with pytest.raises(CorrectedPageSemanticError, match="provenance length"):
        validate_released_readings([malformed])


def test_character_provenance_length_must_equal_grapheme_count() -> None:
    sidecar = _sidecar_from_wct_page()
    sidecar["positions"][0]["derivable_readings"] = [_l1_reading("Abelard")]
    sidecar["positions"][0]["chosen_action"] = "release_flagged"
    validate_corrected_page(sidecar)

    broken = copy.deepcopy(sidecar)
    broken["positions"][0]["derivable_readings"][0]["character_provenance"].pop()
    with pytest.raises(CorrectedPageSemanticError, match="grapheme count"):
        validate_corrected_page(broken)


def test_get_enum_returns_corrector_enums_and_freshness_check_passes() -> None:
    assert get_enum(
        "corrected-page-v1", "positions", "derivable_readings", "derivation_level"
    ) == frozenset({"L0", "L1", "L2", "L3"})
    assert get_enum(
        "corrected-page-v1", "positions", "derivable_readings", "origin_kind"
    ) == frozenset({"observed", "machine_composed", "human_amended"})
    assert get_enum(
        "reconciled_record", "blocks", "canonical_positions", "canonical_origin_kind"
    ) == frozenset({"observed", "machine_composed", "human_amended"})

    result = subprocess.run(
        [sys.executable, "build/tools/check_schema_enums_fresh.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
