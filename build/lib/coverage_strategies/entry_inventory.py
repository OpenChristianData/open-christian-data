"""Entry-inventory coverage checks for encyclopedia resources."""

from __future__ import annotations

import re
from collections import Counter

from build.lib.warning_producers import build_warning


APPLIES_TO_RESOURCE_TYPES = ["encyclopedia"]


def run(record: dict, parameters: dict) -> list[dict]:
    data = record.get("data")
    entries = data if isinstance(data, list) else []
    warnings: list[dict] = []
    warnings.extend(_entry_count_warnings(record, entries, parameters))
    warnings.extend(_alphabetical_gap_warnings(record, entries, parameters))
    warnings.extend(_duplicate_headword_warnings(record, entries))
    return warnings


def _entry_count_warnings(record: dict, entries: list, parameters: dict) -> list[dict]:
    range_parameter = parameters.get("expected_entry_count_range", {})
    expected_range = range_parameter.get("value")
    if not isinstance(expected_range, list) or len(expected_range) != 2:
        return []
    low, high = expected_range
    if not isinstance(low, int) or not isinstance(high, int):
        return []
    entry_count = len(entries)
    if low <= entry_count <= high:
        return []
    from build.lib.warning_producers import coverage as producer

    resource_id = record.get("meta", {}).get("id")
    return [
        build_warning(
            producer=producer,
            code="entry_count_out_of_range",
            entry_id=None,
            field_path="data",
            message=f"Entry count {entry_count} is outside expected range {low}-{high}.",
            evidence={"resource_id": resource_id, "entry_count": entry_count, "low": low, "high": high},
            signature_values={"resource_id": resource_id, "entry_count": entry_count, "low": low, "high": high},
        )
    ]


def _alphabetical_gap_warnings(record: dict, entries: list, parameters: dict) -> list[dict]:
    alphabetical_parameter = parameters.get("alphabetical_completeness", {})
    expected_letters = alphabetical_parameter.get("expected_letters")
    if not isinstance(expected_letters, str) or not expected_letters:
        return []
    present = {
        term[0].upper()
        for entry in entries
        if isinstance(entry, dict)
        for term in [entry.get("term")]
        if isinstance(term, str) and term
    }
    from build.lib.warning_producers import coverage as producer

    resource_id = record.get("meta", {}).get("id")
    warnings: list[dict] = []
    for letter in expected_letters:
        if letter.upper() in present:
            continue
        warnings.append(
            build_warning(
                producer=producer,
                code="alphabetical_gap",
                entry_id=None,
                field_path="data",
                message=f"No entries start with {letter}.",
                evidence={"resource_id": resource_id, "letter": letter},
                signature_values={"resource_id": resource_id, "letter": letter},
            )
        )
    return warnings


def _duplicate_headword_warnings(record: dict, entries: list) -> list[dict]:
    terms = [
        _normalise_term(entry.get("term"))
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("term"), str)
    ]
    counts = Counter(term for term in terms if term)
    duplicates = sorted(term for term, count in counts.items() if count > 1)
    from build.lib.warning_producers import coverage as producer

    resource_id = record.get("meta", {}).get("id")
    return [
        build_warning(
            producer=producer,
            code="duplicate_headword",
            entry_id=None,
            field_path="data",
            message=f"Duplicate headword: {term}.",
            evidence={"resource_id": resource_id, "term": term},
            signature_values={"resource_id": resource_id, "term": term},
        )
        for term in duplicates
    ]


def _normalise_term(term: str) -> str:
    return re.sub(r"\s+", " ", term).strip().casefold()
