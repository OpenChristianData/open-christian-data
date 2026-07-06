from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Live vol_01 WCT is gitignored and was quarantined in R-final.3 (stale content);
# the full WCT rebuild restores it. Real-page tests skip when it is absent.
_WCT_PAGE = REPO_ROOT / "reports" / "wct" / "vol_01" / "page_0010.json"

from build.lib.corrected_page_semantic_validator import validate_corrected_page  # noqa: E402
from build.lib.gold_free_corrector.column_vote import correct_position  # noqa: E402

SCHEMA_DIR = REPO_ROOT / "schemas" / "v1"


def _schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _candidate(
    candidate_id: str,
    text: str,
    families: list[str],
    engines: list[str] | None = None,
) -> dict:
    return {
        "candidate_id": candidate_id,
        "raw_reading": text,
        "candidate_key": text,
        "normalisation_applied": ["unicode_nfkc"],
        "attesting_engines": engines or [f"{family}-engine" for family in families],
        "attesting_families": families,
    }


def _position(candidates: list[dict], spans: list[dict] | None = None) -> dict:
    return {
        "position_id": "pos_001",
        "script": {"text_level": {"label": "latin"}},
        "candidate_set": candidates,
        "span_records": spans or [],
    }


def test_plurality_character_vote_uses_distinct_families() -> None:
    result = correct_position(
        _position(
            [
                _candidate("cand_001", "word", ["abbyy", "surya", "tesseract"]),
                _candidate("cand_002", "ward", ["kraken"]),
            ]
        )
    )

    reading = result.corrected_position["derivable_readings"][-1]

    assert reading["derivation_level"] == "L1"
    assert reading["text"] == "word"
    assert result.columns[1]["winner"]["grapheme"] == "o"
    assert result.columns[1]["winner"]["family_count"] == 3
    assert result.columns[1]["tallies"]["a"]["families"] == ["kraken"]


def test_abelard_triangle_glyph_is_filtered_with_losing_candidate_provenance() -> None:
    if not _WCT_PAGE.exists():
        pytest.skip("vol_01 WCT quarantined (R-final.3); restored by the full WCT rebuild")
    wct_page = json.loads(_WCT_PAGE.read_text(encoding="utf-8"))
    position = next(
        item
        for item in wct_page["positions"]
        if item["position_id"] == "vol_01:page_0010:body:c1:l000:p000"
    )

    result = correct_position(position)

    assert result.corrected_position["derivable_readings"][-1]["text"] == "Abelard"
    assert result.columns[0]["winner"]["grapheme"] == "A"
    assert result.columns[0]["filtered"] == [
        {
            "candidate_id": "cand_002",
            "grapheme": "\u25b2",
            "families": ["abbyy"],
            "method": "impossible_filtered",
        }
    ]


def test_one_vs_one_alphabetic_tie_routes_without_l1_auto_pick() -> None:
    result = correct_position(
        _position(
            [
                _candidate("cand_001", "cat", ["abbyy"]),
                _candidate("cand_002", "cot", ["tesseract"]),
            ]
        )
    )

    assert [reading["derivation_level"] for reading in result.corrected_position["derivable_readings"]] == []
    assert result.corrected_position["chosen_action"] == "route_human_review"
    assert result.route_reason == "one-vs-one-alphabetic-no-plurality"


def test_every_voted_character_carries_complete_engine_family_provenance() -> None:
    result = correct_position(
        _position(
            [
                _candidate("cand_001", "word", ["abbyy", "surya", "tesseract"]),
                _candidate("cand_002", "ward", ["kraken"]),
            ]
        )
    )
    reading = result.corrected_position["derivable_readings"][-1]

    assert len(reading["character_provenance"]) == len(reading["text"])
    for entry in reading["character_provenance"]:
        assert entry["source_type"] == "engine_family"
        assert entry["source_id"]
        assert entry["wct_candidate_id"]


def test_kraken_and_kraken_greek_count_as_one_family() -> None:
    result = correct_position(
        _position(
            [
                _candidate(
                    "cand_001",
                    "this",
                    ["kraken"],
                    engines=["kraken-py312-v1", "kraken-greek-py312-v1"],
                ),
                _candidate("cand_002", "thus", ["abbyy", "tesseract"]),
            ]
        )
    )

    assert result.columns[2]["tallies"]["i"]["family_count"] == 1
    assert result.columns[2]["tallies"]["u"]["family_count"] == 2
    assert result.corrected_position["derivable_readings"][-1]["text"] == "thus"


def test_family_count_tie_is_deterministic_across_hash_seeds() -> None:
    script = """
from build.lib.gold_free_corrector.column_vote import correct_position
def candidate(candidate_id, text, families):
    return {
        "candidate_id": candidate_id,
        "raw_reading": text,
        "candidate_key": text,
        "normalisation_applied": ["unicode_nfkc"],
        "attesting_engines": [f"{family}-engine" for family in families],
        "attesting_families": families,
    }
position = {
    "position_id": "pos_001",
    "script": {"text_level": {"label": "latin"}},
    "candidate_set": [
        candidate("cand_001", "cat", ["abbyy", "surya"]),
        candidate("cand_002", "cot", ["kraken", "tesseract"]),
    ],
    "span_records": [],
}
print(correct_position(position).corrected_position["derivable_readings"][-1]["text"])
"""
    outputs = []
    for seed in ("0", "1"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        outputs.append(completed.stdout.strip())

    assert outputs == ["cat", "cat"]


def test_emitted_corrected_position_validates_against_corrected_page_v1() -> None:
    result = correct_position(
        _position(
            [
                _candidate("cand_001", "word", ["abbyy", "surya", "tesseract"]),
                _candidate("cand_002", "ward", ["kraken"]),
            ]
        )
    )
    page = {
        "schema_type": "corrected_page",
        "schema_version": "corrected-page-v1",
        "work_id": "work",
        "volume_id": "vol",
        "page_id": "page",
        "source_wct_page": {"path": "reports/wct/vol_01/page_0010.json"},
        "positions": [result.corrected_position],
    }

    jsonschema.validate(instance=page, schema=_schema("corrected-page-v1"))
    validate_corrected_page(page)
