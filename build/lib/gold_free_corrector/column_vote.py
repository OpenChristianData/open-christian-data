"""Character-column voting for WCT candidate sets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from build.lib.wct_builder import confusion_distance, weighted_edit_backtrace


@dataclass(frozen=True)
class ColumnVoteResult:
    corrected_position: dict[str, Any]
    columns: list[dict[str, Any]]
    agreement_score: float
    route_reason: str | None = None


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    key: str
    raw_reading: str
    families: frozenset[str]
    span_by_family: dict[str, str]


def correct_position(position: dict[str, Any]) -> ColumnVoteResult:
    """Build an L0/L1 corrected-position candidate from one WCT position."""
    candidates = _candidates(position)
    corrected_position = {
        "position_id": position["position_id"],
        "protected_class": "none",
        "derivable_readings": [],
        "chosen_reading_index": None,
        "chosen_action": "route_human_review",
    }
    if not candidates:
        return ColumnVoteResult(corrected_position, [], 0.0, "no-candidates")

    columns = _align_columns(candidates)
    voted_columns = [_vote_column(column, candidates) for column in columns]
    agreement_score = _agreement_score(voted_columns)

    l0 = _l0_reading(candidates)
    if l0 is not None:
        corrected_position["derivable_readings"].append(l0)

    route_reason = _route_reason(voted_columns, candidates)
    if route_reason is None:
        text = "".join(
            column["winner"]["grapheme"]
            for column in voted_columns
            if column.get("winner") is not None
        )
        provenance = [
            _engine_family_provenance(column)
            for column in voted_columns
            if column.get("winner") is not None
        ]
        corrected_position["derivable_readings"].append(
            {
                "derivation_level": "L1",
                "origin_kind": "machine_composed",
                "text": text,
                "scores": {
                    "confidence": round(agreement_score, 4),
                    "character_vote_score": round(agreement_score, 4),
                },
                "character_provenance": provenance,
            }
        )
        corrected_position["chosen_reading_index"] = len(corrected_position["derivable_readings"]) - 1
        corrected_position["chosen_action"] = "release_flagged"

    return ColumnVoteResult(
        corrected_position=corrected_position,
        columns=voted_columns,
        agreement_score=agreement_score,
        route_reason=route_reason,
    )


def _candidates(position: dict[str, Any]) -> list[_Candidate]:
    span_lookup = _span_lookup(position.get("span_records", []))
    candidates = []
    for candidate in position.get("candidate_set", []):
        candidate_id = str(candidate["candidate_id"])
        families = frozenset(str(family) for family in candidate.get("attesting_families", []))
        candidates.append(
            _Candidate(
                candidate_id=candidate_id,
                key=str(candidate.get("candidate_key") or candidate.get("raw_reading") or ""),
                raw_reading=str(candidate.get("raw_reading") or candidate.get("candidate_key") or ""),
                families=families,
                span_by_family=span_lookup.get(candidate_id, {}),
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.candidate_id)


def _span_lookup(span_records: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    lookup: dict[str, dict[str, str]] = {}
    for span in span_records:
        candidate_id = span.get("candidate_id")
        family = span.get("family")
        span_record_id = span.get("span_record_id")
        if candidate_id and family and span_record_id:
            lookup.setdefault(str(candidate_id), {})[str(family)] = str(span_record_id)
    return lookup


def _align_columns(candidates: list[_Candidate]) -> list[dict[str, Any]]:
    base = candidates[0]
    columns = [
        {"base_index": index, "cells": {base.candidate_id: char}}
        for index, char in enumerate(base.key)
    ]
    next_insert_offset = 0
    for candidate in candidates[1:]:
        _, ops = weighted_edit_backtrace(base.key, candidate.key)
        base_index = 0
        for op in ops:
            source = op["source"]
            target = op["target"]
            max_len = max(len(source), len(target))
            for offset in range(max_len):
                source_char = source[offset] if offset < len(source) else ""
                target_char = target[offset] if offset < len(target) else ""
                if source_char:
                    column = _column_for_base_index(columns, base_index)
                    base_index += 1
                else:
                    column = {
                        "base_index": base_index - 0.5 + (next_insert_offset / 1000),
                        "cells": {},
                    }
                    next_insert_offset += 1
                    columns.append(column)
                    columns.sort(key=lambda item: item["base_index"])
                column["cells"][candidate.candidate_id] = target_char or None
    return columns


def _column_for_base_index(columns: list[dict[str, Any]], base_index: int) -> dict[str, Any]:
    for column in columns:
        if column["base_index"] == base_index:
            return column
    raise ValueError(f"alignment referenced missing base column {base_index}")


def _vote_column(column: dict[str, Any], candidates: list[_Candidate]) -> dict[str, Any]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    entries = []
    for candidate_id, grapheme in column["cells"].items():
        if not grapheme:
            continue
        candidate = candidate_by_id[candidate_id]
        entries.append({"candidate": candidate, "grapheme": grapheme})

    all_families = sorted(
        {
            family
            for entry in entries
            for family in entry["candidate"].families
        }
    )
    filtered = []
    alpha_column = any(str(entry["grapheme"]).isalpha() for entry in entries)
    kept_entries = []
    for entry in entries:
        grapheme = str(entry["grapheme"])
        if alpha_column and not grapheme.isalpha():
            filtered.append(
                {
                    "candidate_id": entry["candidate"].candidate_id,
                    "grapheme": grapheme,
                    "families": sorted(entry["candidate"].families),
                    "method": "impossible_filtered",
                }
            )
        else:
            kept_entries.append(entry)

    tallies: dict[str, dict[str, Any]] = {}
    for entry in kept_entries:
        grapheme = str(entry["grapheme"])
        tally = tallies.setdefault(
            grapheme,
            {
                "families": set(),
                "candidate_ids": set(),
                "support": set(),
                "proximity": 0.0,
            },
        )
        tally["families"].update(entry["candidate"].families)
        tally["candidate_ids"].add(entry["candidate"].candidate_id)
        for family in entry["candidate"].families:
            tally["support"].add(
                (
                    family,
                    entry["candidate"].candidate_id,
                    entry["candidate"].span_by_family.get(family),
                )
            )

    for grapheme, tally in tallies.items():
        tally["family_count"] = len(tally["families"])
        tally["families"] = sorted(tally["families"])
        tally["candidate_ids"] = sorted(tally["candidate_ids"])
        tally["support"] = [
            {
                "family": family,
                "candidate_id": candidate_id,
                "span_record_id": span_record_id,
            }
            for family, candidate_id, span_record_id in sorted(tally["support"])
        ]
        tally["proximity"] = round(
            sum(confusion_distance(grapheme, other) for other in tallies if other != grapheme),
            6,
        )

    winner = None
    if tallies:
        winner_grapheme = sorted(
            tallies,
            key=lambda grapheme: (
                -tallies[grapheme]["family_count"],
                tallies[grapheme]["proximity"],
                grapheme,
            ),
        )[0]
        winner = {
            "grapheme": winner_grapheme,
            "family_count": tallies[winner_grapheme]["family_count"],
            "families": tallies[winner_grapheme]["families"],
            "candidate_ids": tallies[winner_grapheme]["candidate_ids"],
            "support": tallies[winner_grapheme]["support"],
        }

    return {
        "cells": {
            candidate_id: grapheme
            for candidate_id, grapheme in sorted(column["cells"].items())
            if grapheme
        },
        "tallies": tallies,
        "filtered": filtered,
        "winner": winner,
        "distinct_families": all_families,
    }


def _agreement_score(columns: list[dict[str, Any]]) -> float:
    scores = []
    for column in columns:
        winner = column.get("winner")
        denominator = len(column["distinct_families"])
        if winner is not None and denominator:
            scores.append(winner["family_count"] / denominator)
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def _l0_reading(candidates: list[_Candidate]) -> dict[str, Any] | None:
    family_agreed = [candidate for candidate in candidates if len(candidate.families) > 1]
    if len(family_agreed) != 1:
        return None
    candidate = family_agreed[0]
    return {
        "derivation_level": "L0",
        "origin_kind": "observed",
        "text": candidate.raw_reading,
        "scores": {"confidence": 1.0},
    }


def _route_reason(columns: list[dict[str, Any]], candidates: list[_Candidate]) -> str | None:
    if not columns:
        return "no-voted-columns"
    if any(column.get("winner") is None for column in columns):
        return "unvoted-column"

    if _one_vs_one_alphabetic_without_filter(candidates, columns):
        return "one-vs-one-alphabetic-no-plurality"

    return None


def _one_vs_one_alphabetic_without_filter(
    candidates: list[_Candidate],
    columns: list[dict[str, Any]],
) -> bool:
    if len(candidates) != 2:
        return False
    if any(len(candidate.families) != 1 for candidate in candidates):
        return False
    if any(column["filtered"] for column in columns):
        return False
    return all(candidate.key.isalpha() for candidate in candidates)


def _engine_family_provenance(column: dict[str, Any]) -> dict[str, Any]:
    assert column["winner"] is not None
    support = column["winner"]["support"][0]
    entry = {
        "grapheme": column["winner"]["grapheme"],
        "source_type": "engine_family",
        "source_id": support["family"],
        "wct_candidate_id": support["candidate_id"],
    }
    if support["span_record_id"] is not None:
        entry["wct_span_record_id"] = support["span_record_id"]
    return entry
