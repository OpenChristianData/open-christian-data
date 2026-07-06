"""Scriptural canon coverage checks for commentary resources."""

from __future__ import annotations

import re
from typing import Iterable

from build.lib.scripture_canon import book_chapter_count, book_verse_count
from build.lib.warning_producers import build_warning


APPLIES_TO_RESOURCE_TYPES = ["commentary"]

_VERSE_RANGE_RE = re.compile(r"^(?P<start>\d+)(?:-(?P<end>\d+))?$")


def run(record: dict, parameters: dict) -> list[dict]:
    books_parameter = parameters.get("books", {})
    books = books_parameter.get("value", [])
    if not isinstance(books, list):
        return []
    intent = _coverage_intent(record)
    warnings: list[dict] = []
    for book in books:
        if not isinstance(book, str):
            continue
        by_chapter = _covered_verses_by_chapter(record, book)
        chapter_count = book_chapter_count(book)
        for chapter in range(1, chapter_count + 1):
            covered_verses = by_chapter.get(chapter)
            if not covered_verses:
                warnings.append(_missing_chapter_warning(record, book, chapter))
                continue
            if intent == "exhaustive":
                verse_count = book_verse_count(book, chapter)
                missing_ranges = _contiguous_ranges(
                    verse for verse in range(1, verse_count + 1) if verse not in covered_verses
                )
                for start, end in missing_ranges:
                    warnings.append(_missing_verse_range_warning(record, book, chapter, start, end))
    return warnings


def _coverage_intent(record: dict) -> str:
    coverage = record.get("meta", {}).get("coverage", {})
    intent = coverage.get("intent") if isinstance(coverage, dict) else None
    if intent in {"exhaustive", "selective", "thematic"}:
        return intent
    return "exhaustive"


def _covered_verses_by_chapter(record: dict, book: str) -> dict[int, set[int]]:
    by_chapter: dict[int, set[int]] = {}
    data = record.get("data")
    if not isinstance(data, list):
        return by_chapter
    for entry in data:
        if not isinstance(entry, dict) or entry.get("book_osis") != book:
            continue
        chapter = entry.get("chapter")
        verse_range = entry.get("verse_range")
        if not isinstance(chapter, int) or chapter < 1 or not isinstance(verse_range, str):
            continue
        verses = _parse_verse_range(verse_range)
        if verses:
            by_chapter.setdefault(chapter, set()).update(verses)
    return by_chapter


def _parse_verse_range(value: str) -> set[int]:
    match = _VERSE_RANGE_RE.match(value)
    if not match:
        return set()
    start = int(match.group("start"))
    end = int(match.group("end") or start)
    if end < start:
        return set()
    return set(range(start, end + 1))


def _contiguous_ranges(values: Iterable[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    previous: int | None = None
    for value in values:
        if start is None:
            start = value
            previous = value
            continue
        if previous is not None and value == previous + 1:
            previous = value
            continue
        ranges.append((start, previous if previous is not None else start))
        start = value
        previous = value
    if start is not None:
        ranges.append((start, previous if previous is not None else start))
    return ranges


def _missing_chapter_warning(record: dict, book: str, chapter: int) -> dict:
    from build.lib.warning_producers import coverage as producer

    resource_id = record.get("meta", {}).get("id")
    return build_warning(
        producer=producer,
        code="missing_chapter",
        entry_id=None,
        field_path="data",
        message=f"{book} chapter {chapter} has no coverage entry.",
        evidence={"resource_id": resource_id, "book": book, "chapter": chapter},
        signature_values={"resource_id": resource_id, "book": book, "chapter": chapter},
    )


def _missing_verse_range_warning(record: dict, book: str, chapter: int, start: int, end: int) -> dict:
    from build.lib.warning_producers import coverage as producer

    verse_range = str(start) if start == end else f"{start}-{end}"
    resource_id = record.get("meta", {}).get("id")
    return build_warning(
        producer=producer,
        code="missing_verse_range",
        entry_id=None,
        field_path="data",
        message=f"{book} {chapter}:{verse_range} has no coverage entry.",
        evidence={
            "resource_id": resource_id,
            "book": book,
            "chapter": chapter,
            "verse_range": verse_range,
        },
        signature_values={
            "resource_id": resource_id,
            "book": book,
            "chapter": chapter,
            "verse_range": verse_range,
        },
    )
