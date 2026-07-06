"""Lexicality evidence for gold-free correction candidates."""

from __future__ import annotations

from typing import Any as _Any

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult as _ColumnVoteResult
from build.lib.gold_free_corrector.lexicon.build_lexicon import ConsensusLexicon as _ConsensusLexicon

LANGUAGE_SCOPE: tuple[str, ...] = ("en", "la")

__all__ = ["LANGUAGE_SCOPE", "lexicality_rescore"]

del annotations


def lexicality_rescore(
    result: _ColumnVoteResult,
    lexicon: _ConsensusLexicon,
    *,
    max_confusion_distance: float = 0.2,
) -> _ColumnVoteResult:
    corrected_position = dict(result.corrected_position)
    existing_readings = list(corrected_position.get("derivable_readings", []))
    rescored_readings = [
        _reading_with_lexicality(reading, lexicon, max_confusion_distance)
        for reading in existing_readings
    ]

    best_reading = _best_existing_reading(existing_readings)
    if best_reading is not None and not lexicon.is_word(str(best_reading["text"])):
        nearest = lexicon.nearest(str(best_reading["text"]), max_confusion_distance)
        if nearest:
            word, distance = nearest[0]
            rescored_readings.append(_l2_reading(word, distance))

    corrected_position["derivable_readings"] = rescored_readings
    return _ColumnVoteResult(
        corrected_position=corrected_position,
        columns=result.columns,
        agreement_score=result.agreement_score,
        route_reason=result.route_reason,
    )


def _reading_with_lexicality(
    reading: dict[str, _Any],
    lexicon: _ConsensusLexicon,
    max_confusion_distance: float,
) -> dict[str, _Any]:
    rescored = dict(reading)
    scores = dict(reading.get("scores", {}))
    scores["lexicality"] = _lexicality_score(
        str(reading["text"]),
        lexicon,
        max_confusion_distance,
    )
    rescored["scores"] = scores
    return rescored


def _lexicality_score(
    text: str,
    lexicon: _ConsensusLexicon,
    max_confusion_distance: float,
) -> float:
    if lexicon.is_word(text):
        return 1.0
    nearest = lexicon.nearest(text, max_confusion_distance)
    if not nearest:
        return 0.0
    return 1.0 - nearest[0][1]


def _best_existing_reading(readings: list[dict[str, _Any]]) -> dict[str, _Any] | None:
    if not readings:
        return None
    return max(readings, key=lambda reading: _derivation_rank(str(reading["derivation_level"])))


def _derivation_rank(derivation_level: str) -> int:
    if derivation_level.startswith("L") and derivation_level[1:].isdigit():
        return int(derivation_level[1:])
    return -1


def _l2_reading(text: str, distance: float) -> dict[str, _Any]:
    return {
        "derivation_level": "L2",
        "origin_kind": "confusion_lexicon",
        "text": text,
        "scores": {"lexicality": 1.0 - distance},
        "character_provenance": [
            {
                "grapheme": char,
                "source_type": "confusion_lexicon",
                "families": [],
            }
            for char in text
        ],
    }
