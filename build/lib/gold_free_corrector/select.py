"""Active-learning selection for gold-free correction review queues."""

from __future__ import annotations

from math import log2
from typing import Any

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult

_LEVEL_PENALTY = {"L0": 0.25, "L1": 0.5, "L2": 0.75, "L3": 1.0}


def select_for_review(
    reviewer_queue: list[dict],
    corrected_positions: list[ColumnVoteResult],
) -> list[dict]:
    """Return reviewer_queue sorted by informativeness descending."""
    cvr_by_pid = {
        cvr.corrected_position["position_id"]: cvr
        for cvr in corrected_positions
    }

    annotated = []
    for item in reviewer_queue:
        cvr = cvr_by_pid.get(item.get("position_id"))
        features, informativeness = _review_features(cvr)
        annotated.append(
            (
                features["is_protected"],
                informativeness,
                {
                    **item,
                    "review_features": features,
                },
            )
        )

    selected = sorted(annotated, key=lambda item: (-int(item[0]), -item[1]))
    return [item for _, _, item in selected]


def _review_features(cvr: ColumnVoteResult | None) -> tuple[dict[str, Any], float]:
    agreement_score = cvr.agreement_score if cvr is not None else 0.5
    entropy = _family_disagreement_entropy(cvr.columns if cvr is not None else [])
    level_penalty = _level_penalty(cvr)
    is_protected = _is_protected(cvr)
    informativeness = (1 - agreement_score) * entropy * level_penalty

    return (
        {
            "informativeness_score": round(informativeness, 6),
            "agreement_score": round(agreement_score, 4),
            "family_disagreement_entropy": round(entropy, 6),
            "level_penalty": level_penalty,
            "is_protected": is_protected,
        },
        informativeness,
    )


def _family_disagreement_entropy(columns: list[dict[str, Any]]) -> float:
    if not columns:
        return 0.0

    entropies = [_column_entropy(column) for column in columns]
    return sum(entropies) / len(entropies)


def _column_entropy(column: dict[str, Any]) -> float:
    tallies = column.get("tallies", {})
    total_families = sum(tally["family_count"] for tally in tallies.values())
    if not tallies or total_families == 0:
        return 0.0

    return -sum(
        (family_count / total_families) * log2(family_count / total_families)
        for tally in tallies.values()
        for family_count in [tally["family_count"]]
    )


def _level_penalty(cvr: ColumnVoteResult | None) -> float:
    if cvr is None:
        return 0.5
    derivation_method = cvr.corrected_position.get("derivation_method")
    return _LEVEL_PENALTY.get(derivation_method, 0.5)


def _is_protected(cvr: ColumnVoteResult | None) -> bool:
    if cvr is None:
        return False
    return cvr.corrected_position.get("protected_class", "none") != "none"
