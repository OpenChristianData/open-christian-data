"""Semantic guards for corrected-page and canonical composed readings.

JSON Schema owns field shape. These guards own cross-field obligations from
ADR-0014: provenance length, source-type membership, and route eligibility.
"""

from __future__ import annotations

import unicodedata
from typing import Iterable

from build.lib.schema_enums import get_enum


DERIVATION_LEVELS = get_enum(
    "corrected-page-v1", "positions", "derivable_readings", "derivation_level"
)
ORIGIN_KINDS = get_enum(
    "corrected-page-v1", "positions", "derivable_readings", "origin_kind"
)
CHARACTER_SOURCE_TYPES = get_enum(
    "corrected-page-v1",
    "positions",
    "derivable_readings",
    "character_provenance",
    "source_type",
)

_LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
_LEVEL_ALLOWED_SOURCE_TYPES = {
    "L1": {"engine_family"},
    "L2": {"engine_family", "confusion_rule", "lexicon"},
    "L3": {"engine_family", "confusion_rule", "lexicon", "language_model", "human"},
}


class CorrectedPageSemanticError(ValueError):
    """A corrected-page or canonical reading violates ADR-0014 semantics."""


def graphemes(text: str) -> list[str]:
    """Return a small Unicode grapheme approximation based on combining marks."""
    clusters: list[str] = []
    for char in text:
        if clusters and unicodedata.combining(char):
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def validate_reading_provenance(reading: dict, *, label: str = "reading") -> None:
    """Validate one derivable/canonical reading.

    L0 observed readings may omit character_provenance. L1-L3 released readings
    require complete provenance, one entry per grapheme.
    """
    level = reading.get("derivation_level", reading.get("canonical_derivation_level"))
    origin = reading.get("origin_kind", reading.get("canonical_origin_kind"))
    text = reading.get("text", reading.get("canonical_text"))

    if level not in DERIVATION_LEVELS:
        raise CorrectedPageSemanticError(f"{label} has invalid derivation level {level!r}")
    if origin not in ORIGIN_KINDS:
        raise CorrectedPageSemanticError(f"{label} has invalid origin kind {origin!r}")
    if not isinstance(text, str):
        raise CorrectedPageSemanticError(f"{label} text must be a string")

    provenance = reading.get("character_provenance")
    if level == "L0":
        if origin not in {"observed", "human_amended"}:
            raise CorrectedPageSemanticError(
                f"{label} L0 origin must be observed or human_amended"
            )
        if provenance is None:
            return
    else:
        if origin != "machine_composed":
            raise CorrectedPageSemanticError(
                f"{label} {level} origin must be machine_composed"
            )
        if not isinstance(provenance, list) or not provenance:
            raise CorrectedPageSemanticError(
                f"{label} {level} requires character_provenance"
            )

    assert provenance is not None
    expected = graphemes(text)
    if len(provenance) != len(expected):
        raise CorrectedPageSemanticError(
            f"{label} provenance length {len(provenance)} != grapheme count {len(expected)}"
        )

    allowed_sources = _LEVEL_ALLOWED_SOURCE_TYPES.get(level, CHARACTER_SOURCE_TYPES)
    for index, (entry, grapheme) in enumerate(zip(provenance, expected, strict=True)):
        source_type = entry.get("source_type") if isinstance(entry, dict) else None
        if source_type not in CHARACTER_SOURCE_TYPES:
            raise CorrectedPageSemanticError(
                f"{label} provenance[{index}] has invalid source_type {source_type!r}"
            )
        if source_type not in allowed_sources:
            raise CorrectedPageSemanticError(
                f"{label} {level} cannot use source_type {source_type!r}"
            )
        if entry.get("grapheme") != grapheme:
            raise CorrectedPageSemanticError(
                f"{label} provenance[{index}] grapheme {entry.get('grapheme')!r} "
                f"!= text grapheme {grapheme!r}"
            )


def validate_released_readings(readings: Iterable[dict]) -> None:
    """Ship-blocking gate for released canonical readings."""
    for index, reading in enumerate(readings):
        validate_reading_provenance(reading, label=f"released_readings[{index}]")


def validate_corrected_page(page: dict) -> None:
    """Validate corrected-page cross-field invariants."""
    for position_index, position in enumerate(page.get("positions", [])):
        readings = position.get("derivable_readings", [])
        if not isinstance(readings, list):
            raise CorrectedPageSemanticError(
                f"positions[{position_index}].derivable_readings must be a list"
            )
        for reading_index, reading in enumerate(readings):
            validate_reading_provenance(
                reading,
                label=f"positions[{position_index}].derivable_readings[{reading_index}]",
            )

        chosen_index = position.get("chosen_reading_index")
        if chosen_index is not None and not 0 <= chosen_index < len(readings):
            raise CorrectedPageSemanticError(
                f"positions[{position_index}].chosen_reading_index is out of range"
            )

        chosen_action = position.get("chosen_action")
        if chosen_action == "release_observed" and chosen_index is not None:
            chosen_level = readings[chosen_index]["derivation_level"]
            if chosen_level != "L0":
                raise CorrectedPageSemanticError(
                    "release_observed requires an L0 chosen reading"
                )
