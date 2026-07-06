"""Semantic validation for rendering-v1 records.

JSON Schema cannot express the cross-reference rules for derived join spans.
This module checks those rules without selecting a truth value or comparing
engines.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _iter_words(rendering: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for page in rendering.get("pages", []):
        for block in page.get("blocks", []):
            for line in block.get("lines", []):
                words.extend(line.get("words", []))
    return words


def _iter_derived_spans(rendering: dict[str, Any]) -> dict[str, dict[str, Any]]:
    spans: dict[str, dict[str, Any]] = {}
    by_block = rendering.get("derived_spans_by_block", {})
    if not isinstance(by_block, dict):
        return spans
    for block_id, block_spans in by_block.items():
        if not isinstance(block_spans, list):
            continue
        for span in block_spans:
            if not isinstance(span, dict):
                continue
            span_id = span.get("derived_span_id")
            if isinstance(span_id, str):
                enriched = dict(span)
                enriched["_rendering_block_id"] = block_id
                spans[span_id] = enriched
    return spans


def validate_rendering(rendering: dict[str, Any]) -> list[str]:
    """Return rendering-v1 semantic invariant violations (empty = ok)."""
    errors: list[str] = []
    words = _iter_words(rendering)
    token_ids = [word.get("observation_token_id") for word in words]
    token_counts = Counter(token_id for token_id in token_ids if isinstance(token_id, str))
    token_set = set(token_counts)

    for token_id, count in sorted(token_counts.items()):
        if count != 1:
            errors.append(
                "derived_span_referential_mismatch: "
                f"observation_token_id {token_id!r} appears {count} times"
            )

    spans = _iter_derived_spans(rendering)
    for span_id, span in sorted(spans.items()):
        contributor_ids = span.get("contributor_observation_token_ids", [])
        if not isinstance(contributor_ids, list):
            errors.append(
                "derived_span_referential_mismatch: "
                f"derived span {span_id!r} contributors are not a list"
            )
            continue
        seen_contributors = Counter(
            contributor_id for contributor_id in contributor_ids if isinstance(contributor_id, str)
        )
        for contributor_id, count in sorted(seen_contributors.items()):
            if count != 1:
                errors.append(
                    "derived_span_referential_mismatch: "
                    f"derived span {span_id!r} repeats contributor {contributor_id!r}"
                )
            if contributor_id not in token_set:
                errors.append(
                    "derived_span_referential_mismatch: "
                    f"derived span {span_id!r} references missing word {contributor_id!r}"
                )

    for word in words:
        token_id = word.get("observation_token_id")
        participates = word.get("in_derived_join_span")
        span_id = word.get("derived_join_span_id")
        if participates is True:
            if not isinstance(span_id, str) or span_id not in spans:
                errors.append(
                    "derived_span_referential_mismatch: "
                    f"word {token_id!r} marks derived-span participation without a matching span"
                )
                continue
            contributor_ids = spans[span_id].get("contributor_observation_token_ids", [])
            if token_id not in contributor_ids:
                errors.append(
                    "derived_span_referential_mismatch: "
                    f"word {token_id!r} points to derived span {span_id!r} but is not a contributor"
                )
        elif span_id is not None:
            errors.append(
                "derived_span_referential_mismatch: "
                f"word {token_id!r} has derived_join_span_id while not marked as participating"
            )
    return errors


__all__ = ["validate_rendering"]
