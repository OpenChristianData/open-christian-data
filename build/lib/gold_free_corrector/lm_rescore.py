"""Language-model rescoring for gold-free derivable readings."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult
from build.lib.gold_free_corrector.lexicon.build_lexicon import ConsensusLexicon
from build.lib.gold_free_corrector.lm_train import (
    LanguageModel,
    train_l0_language_model_from_results,
)


def score_readings(
    result: ColumnVoteResult,
    model: LanguageModel,
) -> ColumnVoteResult:
    """Return a result with every derivable reading annotated by LM score."""
    corrected_position = copy.deepcopy(result.corrected_position)
    for reading in corrected_position.get("derivable_readings", []):
        scores = dict(reading.get("scores", {}))
        scores["lm_score"] = float(model.score(str(reading["text"])))
        reading["scores"] = scores
    return ColumnVoteResult(
        corrected_position=corrected_position,
        columns=copy.deepcopy(result.columns),
        agreement_score=result.agreement_score,
        route_reason=result.route_reason,
    )


def lm_rescore(
    result: ColumnVoteResult,
    model: LanguageModel,
    lexicon: ConsensusLexicon,
    *,
    emit_l3: bool = True,
) -> ColumnVoteResult:
    """Annotate readings and optionally append one explicit L3 LM reading."""
    rescored = score_readings(result, model)
    if not emit_l3:
        return rescored

    readings = rescored.corrected_position.get("derivable_readings", [])
    if any(reading.get("derivation_level") == "L0" for reading in readings):
        return rescored

    best = _best_l3_substitution(readings, model, lexicon)
    if best is None:
        return rescored

    original, corrected, lm_score = best
    l3 = {
        "derivation_level": "L3",
        "origin_kind": "lm_authorship",
        "method": "lm",
        "text": corrected,
        "scores": {"lm_score": lm_score},
        "character_provenance": [
            {
                "grapheme": char,
                "source_type": "lm" if char != original[index] else "original",
                "families": [],
            }
            for index, char in enumerate(corrected)
        ],
    }

    corrected_position = copy.deepcopy(rescored.corrected_position)
    corrected_position.setdefault("derivable_readings", []).append(l3)
    return ColumnVoteResult(
        corrected_position=corrected_position,
        columns=copy.deepcopy(rescored.columns),
        agreement_score=rescored.agreement_score,
        route_reason=rescored.route_reason,
    )


def _rescore_batch_from_results(
    results: list,
    *,
    char_order: int = 5,
    add_k: float = 0.5,
    lexicon: ConsensusLexicon,
) -> list[ColumnVoteResult]:
    """Train through M7's HR7 gate, then rescore each result with that model."""
    trainer_inputs = [_result_mapping(result) for result in results]
    model = train_l0_language_model_from_results(
        trainer_inputs,
        char_order=char_order,
        add_k=add_k,
    )
    return [
        lm_rescore(_column_vote_result_from(result), model, lexicon)
        for result in results
    ]


def _best_l3_substitution(
    readings: list[dict[str, Any]],
    model: LanguageModel,
    lexicon: ConsensusLexicon,
) -> tuple[str, str, float] | None:
    best: tuple[str, str, float] | None = None
    for reading in readings:
        if reading.get("derivation_level") != "L1":
            continue
        original = str(reading["text"])
        original_score = float(model.score(original))
        for candidate in _single_char_lexicon_candidates(original, lexicon):
            candidate_score = float(model.score(candidate))
            if candidate_score <= original_score:
                continue
            if best is None or (candidate_score, candidate) > (best[2], best[1]):
                best = (original, candidate, candidate_score)
    return best


def _single_char_lexicon_candidates(original: str, lexicon: ConsensusLexicon) -> list[str]:
    return [
        word
        for word in sorted(lexicon.words)
        if len(word) == len(original)
        and word != original
        and lexicon.is_word(word)
        and sum(left != right for left, right in zip(original, word)) == 1
    ]


def _result_mapping(result: object) -> Mapping[str, Any]:
    if isinstance(result, ColumnVoteResult):
        return {"corrected_position": result.corrected_position}
    if isinstance(result, Mapping):
        return result
    raise TypeError("result must be a ColumnVoteResult or mapping")


def _column_vote_result_from(result: object) -> ColumnVoteResult:
    if isinstance(result, ColumnVoteResult):
        return result
    if not isinstance(result, Mapping):
        raise TypeError("result must be a ColumnVoteResult or mapping")
    return ColumnVoteResult(
        corrected_position=copy.deepcopy(result["corrected_position"]),
        columns=copy.deepcopy(result.get("columns", [])),
        agreement_score=float(result.get("agreement_score", 0.0)),
        route_reason=result.get("route_reason"),
    )
