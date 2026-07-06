from __future__ import annotations

import json

import pytest

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult
from build.lib.gold_free_corrector.decide import decide, load_thresholds


def _result(
    readings: list[dict],
    *,
    protected_class: str = "none",
    derivation_method: str | None = "stale",
) -> ColumnVoteResult:
    return ColumnVoteResult(
        corrected_position={
            "position_id": "pos-1",
            "protected_class": protected_class,
            "derivable_readings": readings,
            "chosen_reading_index": None,
            "chosen_action": "route_human_review",
            "derivation_method": derivation_method,
        },
        columns=[],
        agreement_score=0.0,
    )


def _reading(level: str, text: str = "word") -> dict:
    return {"derivation_level": level, "text": text, "scores": {}}


def test_protected_routes_before_scores() -> None:
    result = _result([_reading("L1")], protected_class="proper_name")
    thresholds = {"body": {"L1": {"auto_accept_enabled": True}}}

    decided = decide(result, thresholds, region_class="body")

    assert decided.corrected_position["chosen_action"] == "route_human_review"
    assert decided.corrected_position["chosen_reading_index"] is None
    assert decided.corrected_position["derivation_method"] is None


def test_route_until_measured_not_zero_sentinel() -> None:
    result = _result([_reading("L1")])
    thresholds = {
        "body": {
            "L1": {
                "auto_accept_enabled": False,
                "max_real_word_error_rate": 0.0,
                "measured_real_word_error_rate": 0.0,
            }
        }
    }

    decided = decide(result, thresholds, region_class="body")

    assert decided.corrected_position["chosen_action"] != "release_accepted"


def test_all_levels_evaluated_then_preference() -> None:
    result = _result([_reading("L0"), _reading("L1"), _reading("L2"), _reading("L3")])
    thresholds = {
        "body": {
            level: {"auto_accept_enabled": True}
            for level in ("L0", "L1", "L2", "L3")
        }
    }

    decided = decide(result, thresholds, region_class="body")

    assert decided.corrected_position["chosen_action"] == "release_accepted"
    assert decided.corrected_position["chosen_reading_index"] == 0
    assert decided.corrected_position["derivation_method"] == "L0"


def test_realword_bound_demotes_tier() -> None:
    result = _result([_reading("L1")])
    thresholds = {
        "body": {
            "L1": {
                "auto_accept_enabled": True,
                "max_real_word_error_rate": 0.05,
                "measured_real_word_error_rate": 0.08,
            }
        }
    }

    decided = decide(result, thresholds, region_class="body")

    assert decided.corrected_position["chosen_action"] != "release_accepted"


def test_derivation_method_on_every_decision() -> None:
    route = decide(_result([]), {"body": {}}, region_class="body")
    flagged = decide(
        _result([_reading("L1")]),
        {"body": {"L1": {"auto_accept_enabled": False}}},
        region_class="body",
    )
    accepted = decide(
        _result([_reading("L0")]),
        {"body": {"L0": {"auto_accept_enabled": True}}},
        region_class="body",
    )

    assert route.corrected_position["derivation_method"] is None
    assert flagged.corrected_position["derivation_method"] == "L1"
    assert accepted.corrected_position["derivation_method"] == "L0"


def test_release_accepted_when_tier_certified() -> None:
    result = _result([_reading("L1")])
    thresholds = {"body": {"L1": {"auto_accept_enabled": True, "max_real_word_error_rate": None}}}

    decided = decide(result, thresholds, region_class="body")

    assert decided.corrected_position["chosen_action"] == "release_accepted"
    assert decided.corrected_position["chosen_reading_index"] == 0
    assert decided.corrected_position["derivation_method"] == "L1"


def test_load_thresholds_validates_structure(tmp_path) -> None:
    thresholds_path = tmp_path / "corrector_thresholds.json"
    thresholds_path.write_text(
        json.dumps({"body": {"L1": {"max_real_word_error_rate": None}}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_thresholds(thresholds_path)

    thresholds_path.write_text(
        json.dumps(
            {
                "_comment": "test config",
                "body": {
                    "L0": {"auto_accept_enabled": False, "max_real_word_error_rate": None},
                    "L1": {"auto_accept_enabled": False, "max_real_word_error_rate": None},
                    "L2": {"auto_accept_enabled": False, "max_real_word_error_rate": None},
                    "L3": {"auto_accept_enabled": False, "max_real_word_error_rate": None},
                },
                "running_head": {
                    "L0": {"auto_accept_enabled": False, "max_real_word_error_rate": None}
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_thresholds(thresholds_path)

    assert loaded["body"]["L1"]["auto_accept_enabled"] is False
    assert loaded["body"]["L1"]["measured_real_word_error_rate"] is None
