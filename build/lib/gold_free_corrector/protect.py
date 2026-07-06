from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

from build.lib.bible_ref_normalizer import extract_refs_from_text

ProtectedClass = Literal["proper_name", "number", "date", "scripture_ref", "greek", "hebrew"]

SCRIPTURE_SOURCE = "bible_ref_normalizer.extract_refs_from_text"
SCRIPT_SIGNAL_SOURCE = "script.text_level.label"

_DATE_RE = re.compile(
    r"""
    (?:
        (?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})
        |
        (?:(?:1[0-9]{3}|20[0-9]{2})(?:[-/](?:[0-9]{2}|[0-9]{4}))?)
        |
        (?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{2,4})
        |
        (?:\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?,?\s+\d{2,4})
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_NUMBER_RE = re.compile(r"(?:[+-]?\d+(?:,\d{3})*(?:\.\d+)?|[IVXLCDM]+)", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'.-]*")
_TRIM_RE = re.compile(r"^[^\w]+|[^\w]+$")
_COMMON_SENTENCE_STARTERS = frozenset(
    {
        "A",
        "An",
        "And",
        "As",
        "At",
        "But",
        "By",
        "For",
        "From",
        "If",
        "In",
        "It",
        "Nor",
        "Of",
        "On",
        "Only",
        "Or",
        "So",
        "The",
        "This",
        "To",
        "When",
        "Where",
        "With",
        "Yet",
    }
)


@dataclass(frozen=True)
class ProtectedClassSignal:
    protected_class: ProtectedClass | None
    source: str | None = None

    @property
    def is_protected(self) -> bool:
        return self.protected_class is not None

    @property
    def schema_label(self) -> str:
        if self.protected_class is None:
            return "none"
        if self.protected_class == "scripture_ref":
            return "scripture_reference"
        return self.protected_class


def protected_class_for_position(
    position: dict,
    *,
    reading: str | None = None,
    previous_position: dict | None = None,
    next_position: dict | None = None,
    gazetteer: set[str] | frozenset[str] | None = None,
) -> ProtectedClass | None:
    return protected_signal_for_position(
        position,
        reading=reading,
        previous_position=previous_position,
        next_position=next_position,
        gazetteer=gazetteer,
    ).protected_class


def protected_signal_for_position(
    position: dict,
    *,
    reading: str | None = None,
    previous_position: dict | None = None,
    next_position: dict | None = None,
    gazetteer: set[str] | frozenset[str] | None = None,
) -> ProtectedClassSignal:
    script_label = _script_label(position)
    if script_label in {"greek", "hebrew"}:
        return ProtectedClassSignal(script_label, SCRIPT_SIGNAL_SOURCE)

    raw_reading = reading if reading is not None else _best_reading(position)
    if not raw_reading:
        return ProtectedClassSignal(None)

    scripture_context = " ".join(
        token
        for token in (
            _best_reading(previous_position) if previous_position else "",
            raw_reading,
            _best_reading(next_position) if next_position else "",
        )
        if token
    )
    if _is_scripture_ref(scripture_context):
        return ProtectedClassSignal("scripture_ref", SCRIPTURE_SOURCE)

    clean = _trim(raw_reading)
    if _is_date(clean):
        return ProtectedClassSignal("date", "regex.date")
    if _is_number(clean):
        return ProtectedClassSignal("number", "regex.number")
    if _is_proper_name(clean, position, previous_position, gazetteer or frozenset()):
        return ProtectedClassSignal("proper_name", "capitalization.gazetteer")

    return ProtectedClassSignal(None)


def build_consensus_capitalized_gazetteer(
    positions: list[dict],
    *,
    min_occurrences: int = 2,
) -> frozenset[str]:
    counts: Counter[str] = Counter()
    for position in positions:
        seen_in_position: set[str] = set()
        for candidate in position.get("candidate_set", []):
            word = _trim(candidate.get("candidate_key") or candidate.get("raw_reading") or "")
            if _looks_capitalized_name(word):
                seen_in_position.add(word)
        counts.update(seen_in_position)
    return frozenset(word for word, count in counts.items() if count >= min_occurrences)


def _best_reading(position: dict | None) -> str:
    if not position:
        return ""
    for candidate in position.get("candidate_set", []):
        reading = candidate.get("raw_reading") or candidate.get("candidate_key")
        if reading:
            return str(reading)
    return str(position.get("raw_reading") or position.get("candidate_key") or "")


def _script_label(position: dict) -> str | None:
    script = position.get("script")
    if isinstance(script, str):
        return script.lower()
    if not isinstance(script, dict):
        return None
    text_label = script.get("text_level", {}).get("label")
    if text_label:
        return str(text_label).lower()
    image_label = script.get("image_level", {}).get("label")
    return str(image_label).lower() if image_label else None


def _trim(value: str) -> str:
    return _TRIM_RE.sub("", value.strip())


def _is_scripture_ref(value: str) -> bool:
    return bool(extract_refs_from_text(value))


def _is_date(value: str) -> bool:
    return bool(_DATE_RE.fullmatch(value))


def _is_number(value: str) -> bool:
    return bool(_NUMBER_RE.fullmatch(value))


def _is_proper_name(
    value: str,
    position: dict,
    previous_position: dict | None,
    gazetteer: set[str] | frozenset[str],
) -> bool:
    match = _WORD_RE.fullmatch(value)
    if not match or not _looks_capitalized_name(value):
        return False
    if value in gazetteer:
        return True
    if value in _COMMON_SENTENCE_STARTERS:
        return False
    if _is_sentence_initial(position, previous_position):
        return False
    return True


def _looks_capitalized_name(value: str) -> bool:
    return bool(value) and value[0].isupper() and any(char.islower() for char in value[1:])


def _is_sentence_initial(position: dict, previous_position: dict | None) -> bool:
    zone = position.get("zone")
    if isinstance(zone, dict) and zone.get("position_order") == 0:
        return True
    previous = _best_reading(previous_position)
    if previous and _trim(previous).endswith((".", "?", "!")):
        return True
    return False
