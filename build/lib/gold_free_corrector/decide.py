"""Decision policy for gold-free correction results."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult

LEVEL_ORDER = ("L0", "L1", "L2", "L3")
_LEVEL_RANK = {level: index for index, level in enumerate(LEVEL_ORDER)}
_ROUTE = "route_human_review"
_FLAG = "release_flagged"
_ACCEPT = "release_accepted"


def decide(
    result: ColumnVoteResult,
    thresholds: dict,
    *,
    region_class: str,
) -> ColumnVoteResult:
    corrected_position = copy.deepcopy(result.corrected_position)

    if corrected_position.get("protected_class") != "none":
        corrected_position["chosen_action"] = _ROUTE
        corrected_position["chosen_reading_index"] = None
        corrected_position["derivation_method"] = None
        return _with_corrected_position(result, corrected_position)

    readings = list(corrected_position.get("derivable_readings", []))
    if not readings:
        corrected_position["chosen_action"] = _ROUTE
        corrected_position["chosen_reading_index"] = None
        corrected_position["derivation_method"] = None
        return _with_corrected_position(result, corrected_position)

    eligible_indexes = [
        index
        for index, reading in enumerate(readings)
        if _accept_eligible(reading, thresholds, region_class)
    ]
    if eligible_indexes:
        chosen_index = _preferred_index(readings, eligible_indexes)
        corrected_position["chosen_action"] = _ACCEPT
    else:
        chosen_index = _preferred_index(readings, range(len(readings)))
        corrected_position["chosen_action"] = _FLAG

    chosen_level = str(readings[chosen_index]["derivation_level"])
    corrected_position["chosen_reading_index"] = chosen_index
    corrected_position["derivation_method"] = chosen_level
    return _with_corrected_position(result, corrected_position)


def load_thresholds(
    thresholds_path: Path,
    rates_path: Path | None = None,
) -> dict:
    thresholds = _read_json_object(thresholds_path)
    rates = _read_json_object(rates_path) if rates_path is not None else {}

    loaded: dict[str, dict[str, dict[str, Any]]] = {}
    for region_class, region_entries in thresholds.items():
        if region_class == "_comment":
            continue
        if not isinstance(region_entries, Mapping):
            raise ValueError(f"threshold region {region_class} must be an object")
        loaded[region_class] = {}
        rate_region = rates.get(region_class, {})
        if rate_region is None:
            rate_region = {}
        if not isinstance(rate_region, Mapping):
            raise ValueError(f"rate region {region_class} must be an object")
        for level, entry in region_entries.items():
            if not isinstance(entry, Mapping):
                raise ValueError(f"threshold entry {region_class}.{level} must be an object")
            if not isinstance(entry.get("auto_accept_enabled"), bool):
                raise ValueError(
                    f"threshold entry {region_class}.{level} must define auto_accept_enabled bool"
                )
            merged = dict(entry)
            rate_entry = rate_region.get(level, {})
            if rate_entry is None:
                rate_entry = {}
            if not isinstance(rate_entry, Mapping):
                raise ValueError(f"rate entry {region_class}.{level} must be an object")
            merged["measured_real_word_error_rate"] = rate_entry.get(
                "measured_real_word_error_rate"
            )
            loaded[region_class][level] = merged
    return loaded


def _accept_eligible(reading: dict[str, Any], thresholds: dict, region_class: str) -> bool:
    level = str(reading["derivation_level"])
    entry = thresholds.get(region_class, {}).get(level, {"auto_accept_enabled": False})
    if entry.get("auto_accept_enabled", False) is not True:
        return False

    max_rwe = entry.get("max_real_word_error_rate")
    measured_rwe = entry.get("measured_real_word_error_rate")
    return max_rwe is None or measured_rwe is None or measured_rwe <= max_rwe


def _preferred_index(readings: list[dict[str, Any]], indexes: range | list[int]) -> int:
    return min(
        indexes,
        key=lambda index: (
            _LEVEL_RANK.get(str(readings[index]["derivation_level"]), len(_LEVEL_RANK)),
            index,
        ),
    )


def _with_corrected_position(
    result: ColumnVoteResult,
    corrected_position: dict[str, Any],
) -> ColumnVoteResult:
    return ColumnVoteResult(
        corrected_position=corrected_position,
        columns=copy.deepcopy(result.columns),
        agreement_score=result.agreement_score,
        route_reason=result.route_reason,
    )


def _read_json_object(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return loaded
