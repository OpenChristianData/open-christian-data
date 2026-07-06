from __future__ import annotations

import pytest

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult
from build.lib.gold_free_corrector.lexicon.build_lexicon import ConsensusLexicon
from build.lib.gold_free_corrector.lexicality import LANGUAGE_SCOPE, lexicality_rescore


def _lexicon(*words: str) -> ConsensusLexicon:
    return ConsensusLexicon(
        words=frozenset(words),
        languages=LANGUAGE_SCOPE,
        dictionary_source="test-fixture",
        dictionary_word_count=len(words),
    )


def _result(*readings: dict, chosen_action: str = "route_human_review") -> ColumnVoteResult:
    return ColumnVoteResult(
        corrected_position={
            "position_id": "pos_001",
            "derivable_readings": list(readings),
            "chosen_action": chosen_action,
        },
        columns=[{"winner": {"grapheme": "c"}}],
        agreement_score=0.75,
        route_reason="test-route",
    )


def _reading(
    text: str,
    derivation_level: str = "L1",
    scores: dict | None = None,
    origin_kind: str = "machine_composed",
) -> dict:
    return {
        "derivation_level": derivation_level,
        "origin_kind": origin_kind,
        "text": text,
        "scores": scores or {"confidence": 0.5},
    }


def test_l2_fix_tagged_confusion_lexicon_no_engine_family() -> None:
    rescored = lexicality_rescore(_result(_reading("com")), _lexicon("corn"))
    l2_reading = rescored.corrected_position["derivable_readings"][-1]

    assert l2_reading["derivation_level"] == "L2"
    assert l2_reading["origin_kind"] == "confusion_lexicon"
    assert l2_reading["text"] == "corn"
    assert l2_reading["character_provenance"] == [
        {"grapheme": "c", "source_type": "confusion_lexicon", "families": []},
        {"grapheme": "o", "source_type": "confusion_lexicon", "families": []},
        {"grapheme": "r", "source_type": "confusion_lexicon", "families": []},
        {"grapheme": "n", "source_type": "confusion_lexicon", "families": []},
    ]


def test_language_load_scope_explicit() -> None:
    assert LANGUAGE_SCOPE == ("en", "la")


def test_lexicality_does_not_auto_accept_realword() -> None:
    result = _result(_reading("corn"), chosen_action="route_human_review")

    rescored = lexicality_rescore(result, _lexicon("corn"))

    assert rescored.corrected_position["chosen_action"] == "route_human_review"


def test_l0_passthrough_gets_lexicality_score() -> None:
    l0 = _reading("corn", derivation_level="L0", origin_kind="observed")
    result = _result(l0)

    rescored = lexicality_rescore(result, _lexicon("corn"))
    rescored_l0 = rescored.corrected_position["derivable_readings"][0]

    assert rescored_l0["scores"]["lexicality"] == 1.0
    assert {key: value for key, value in rescored_l0.items() if key != "scores"} == {
        key: value for key, value in l0.items() if key != "scores"
    }
    assert rescored_l0["scores"]["confidence"] == 0.5


def test_no_l2_when_reading_already_exact_lexicon_word() -> None:
    rescored = lexicality_rescore(_result(_reading("corn")), _lexicon("corn"))

    assert [
        reading["derivation_level"]
        for reading in rescored.corrected_position["derivable_readings"]
    ] == ["L1"]


def test_l2_appended_when_within_distance() -> None:
    rescored = lexicality_rescore(_result(_reading("com")), _lexicon("corn"))
    readings = rescored.corrected_position["derivable_readings"]

    assert [reading["derivation_level"] for reading in readings] == ["L1", "L2"]
    assert readings[-1]["text"] == "corn"
    assert readings[-1]["scores"]["lexicality"] == pytest.approx(0.9375)
    assert readings[-1]["scores"]["lexicality"] < 1.0


def test_lexicality_score_zero_when_beyond_bound() -> None:
    rescored = lexicality_rescore(_result(_reading("alpha")), _lexicon("corn"))

    assert rescored.corrected_position["derivable_readings"][0]["scores"]["lexicality"] == 0.0
