from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult  # noqa: E402
from build.lib.gold_free_corrector.lexicon.build_lexicon import ConsensusLexicon  # noqa: E402
from build.lib.gold_free_corrector.lm_rescore import (  # noqa: E402
    _rescore_batch_from_results,
    lm_rescore,
    score_readings,
)
from build.lib.gold_free_corrector.lm_train import L0TrainingViolation  # noqa: E402


class FixtureModel:
    backend_name = "fixture"

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self._scores = scores or {}

    def char_logprob(self, context: str, char: str) -> float:
        return -1.0

    def word_logprob(self, prev: str, word: str) -> float:
        return -1.0

    def score(self, token: str) -> float:
        return self._scores.get(token, -float(len(token)))


def _result(readings: list[dict[str, object]]) -> ColumnVoteResult:
    return ColumnVoteResult(
        corrected_position={
            "position_id": "pos_001",
            "derivable_readings": readings,
            "chosen_reading_index": None,
            "chosen_action": "route_human_review",
        },
        columns=[],
        agreement_score=0.0,
    )


def _reading(text: str, level: str = "L1") -> dict[str, object]:
    return {
        "derivation_level": level,
        "origin_kind": "observed" if level == "L0" else "machine_composed",
        "text": text,
        "scores": {"confidence": 1.0},
        "character_provenance": [
            {"grapheme": char, "source_type": "engine_family", "families": ["byz"]}
            for char in text
        ],
    }


def _lexicon(words: set[str]) -> ConsensusLexicon:
    return ConsensusLexicon(
        words=frozenset(words),
        languages=(),
        dictionary_source=None,
        dictionary_word_count=0,
    )


def _readings(result: ColumnVoteResult) -> list[dict[str, object]]:
    return result.corrected_position["derivable_readings"]


def test_lm_trains_wct_l0_only_excludes_current_run() -> None:
    result = {
        "corrected_position": {
            "derivable_readings": [
                {"derivation_level": "L1", "text": "alphe", "scores": {}},
            ],
        },
    }

    with pytest.raises(L0TrainingViolation, match="L1"):
        _rescore_batch_from_results([result], lexicon=_lexicon({"alpha"}))


def test_lm_score_added_to_all_derivable_readings() -> None:
    result = _result([_reading("alpha", "L0"), _reading("alphe", "L1")])

    rescored = score_readings(result, FixtureModel({"alpha": -1.25, "alphe": -2.5}))

    scores = [reading["scores"]["lm_score"] for reading in _readings(rescored)]
    assert scores == [-1.25, -2.5]
    assert all(isinstance(score, float) for score in scores)
    assert all(math.isfinite(score) for score in scores)
    assert "lm_score" not in result.corrected_position["derivable_readings"][0]["scores"]


def test_l3_single_char_on_lexicon_word_only() -> None:
    result = _result([_reading("alphe")])

    rescored = lm_rescore(
        result,
        FixtureModel({"alphe": -10.0, "alpha": -1.0}),
        _lexicon({"alpha"}),
    )

    l3 = [reading for reading in _readings(rescored) if reading["derivation_level"] == "L3"]
    assert len(l3) == 1
    assert l3[0]["text"] == "alpha"
    assert len(l3[0]["text"]) == len("alphe")


def test_l3_tagged_method_lm() -> None:
    result = _result([_reading("alphe")])

    rescored = lm_rescore(
        result,
        FixtureModel({"alphe": -10.0, "alpha": -1.0}),
        _lexicon({"alpha"}),
    )

    l3 = [reading for reading in _readings(rescored) if reading["derivation_level"] == "L3"][0]
    assert l3["method"] == "lm"
    assert l3["origin_kind"] == "lm_authorship"
    assert all(entry["families"] == [] for entry in l3["character_provenance"])
    assert l3["character_provenance"][4]["source_type"] == "lm"


def test_no_l3_when_l0_present() -> None:
    result = _result([_reading("alpha", "L0"), _reading("alphe")])

    rescored = lm_rescore(
        result,
        FixtureModel({"alphe": -10.0, "alpha": -1.0}),
        _lexicon({"alpha"}),
    )

    assert [reading["derivation_level"] for reading in _readings(rescored)] == ["L0", "L1"]
    assert all("lm_score" in reading["scores"] for reading in _readings(rescored))


def test_no_l3_when_no_lexicon_landing() -> None:
    result = _result([_reading("alphe")])

    rescored = lm_rescore(
        result,
        FixtureModel({"alphe": -10.0, "alpha": -1.0}),
        _lexicon({"omega"}),
    )

    assert [reading["derivation_level"] for reading in _readings(rescored)] == ["L1"]


def test_emit_l3_false_suppresses_l3() -> None:
    result = _result([_reading("alphe")])

    rescored = lm_rescore(
        result,
        FixtureModel({"alphe": -10.0, "alpha": -1.0}),
        _lexicon({"alpha"}),
        emit_l3=False,
    )

    assert [reading["derivation_level"] for reading in _readings(rescored)] == ["L1"]
    assert "lm_score" in _readings(rescored)[0]["scores"]
