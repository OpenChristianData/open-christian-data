"""Faithful reconstruction of the complete retained HelloAO Adam Clarke JSON witness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-helloao-adam-clarke-json-to-tei"
CONVERTER_VERSION = "2"
_PROFILE_ID = "helloao-adam-clarke-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/adam-clarke/"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_BOOKS_ROOT_KEYS = ("commentary", "books")
_PROFILES_ROOT_KEYS = ("commentary", "profiles")
_COMMENTARY_KEYS = (
    "id",
    "name",
    "website",
    "licenseUrl",
    "licenseNotes",
    "englishName",
    "language",
    "textDirection",
    "sha256",
    "availableFormats",
    "listOfBooksApiLink",
    "listOfProfilesApiLink",
    "numberOfBooks",
    "totalNumberOfChapters",
    "totalNumberOfVerses",
    "totalNumberOfProfiles",
    "languageName",
    "languageEnglishName",
)
_BOOK_KEYS = (
    "id",
    "commentaryId",
    "name",
    "commonName",
    "introduction",
    "order",
    "numberOfChapters",
    "sha256",
    "firstChapterNumber",
    "firstChapterApiLink",
    "lastChapterNumber",
    "lastChapterApiLink",
    "totalNumberOfVerses",
)
_CHAPTER_ENVELOPE_KEYS = (
    "commentary",
    "book",
    "chapter",
    "thisChapterLink",
    "nextChapterApiLink",
    "previousChapterApiLink",
    "numberOfVerses",
)
_CHAPTER_KEYS_WITH_INTRODUCTION = ("number", "content", "introduction")
_CHAPTER_KEYS_WITHOUT_INTRODUCTION = ("number", "content")
_OCCURRENCE_KEYS = ("type", "number", "content")


def _require_key_order(
    record: dict[str, object], expected: tuple[str, ...], label: str
) -> None:
    if tuple(record) != expected:
        raise ValueError(f"Adam Clarke source field key order drifted at {label}")


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _el(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    normalized: dict[str, str] = {}
    for key, value in (attributes or {}).items():
        if key == "xml:id":
            normalized[_XML_ID] = value
        elif key == "xml:lang":
            normalized[_XML_LANG] = value
        else:
            normalized[key] = value
    result = etree.Element(
        f"{{{_TEI_NS}}}{name}",
        normalized,
        nsmap={None: _TEI_NS} if name == "TEI" else None,
    )
    result.text = text
    return result


def _primary_members(source_manifest: SourceManifest) -> tuple[dict[str, object], ...]:
    raw = source_manifest.record.get("authorities")
    if not isinstance(raw, tuple):
        raise ValueError("Adam Clarke source authorities are invalid")
    records: list[dict[str, object]] = []
    for authority in raw:
        if (
            not isinstance(authority, Mapping)
            or authority.get("role") != "primary-source"
        ):
            continue
        path = authority.get("path")
        name = authority.get("name")
        size = authority.get("bytes")
        digest = authority.get("sha256")
        if (
            not isinstance(path, str)
            or not path.startswith(_SOURCE_PREFIX)
            or not isinstance(name, str)
            or not isinstance(size, int)
            or not isinstance(digest, str)
        ):
            raise ValueError("Adam Clarke primary-source authority is malformed")
        records.append(
            {
                "name": name,
                "path": path,
                "bytes": size,
                "sha256": digest,
                "relative_path": path.removeprefix(_SOURCE_PREFIX),
            }
        )
    records.sort(key=lambda item: str(item["path"]))
    if len(records) != 856 or sum(int(item["bytes"]) for item in records) != 28_421_263:
        raise ValueError(
            "Adam Clarke retained member census differs from 856/28,421,263"
        )
    relative = [str(item["relative_path"]) for item in records]
    if len(set(relative)) != 856:
        raise ValueError("Adam Clarke retained member paths are not unique")
    if set(relative) & {"books.json", "profiles.json"} != {
        "books.json",
        "profiles.json",
    }:
        raise ValueError("Adam Clarke retained metadata members are missing")
    chapter_paths = [
        item for item in relative if item not in {"books.json", "profiles.json"}
    ]
    if len(chapter_paths) != 854 or any(path.count("/") != 1 for path in chapter_paths):
        raise ValueError("Adam Clarke chapter member paths are incomplete")
    return tuple(records)


def _source_set_digest(records: tuple[dict[str, object], ...]) -> str:
    members = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in records
    ]
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": members})
    )


def _authority_json(source_manifest: SourceManifest, name: str) -> dict[str, object]:
    return _strict_json(source_manifest.authority_path(name).read_bytes(), name)


def _canonical_editorial_correction_boundary(
    source_manifest: SourceManifest,
    chapters: list[dict[str, object]],
) -> dict[str, object]:
    ledger_bytes = source_manifest.authority_path(
        "canonical-editorial-correction-ledger"
    ).read_bytes()
    ledger_lines = ledger_bytes.splitlines()
    if len(ledger_lines) != 1:
        raise ValueError("Adam Clarke correction ledger must contain exactly one row")
    ledger = _strict_json(ledger_lines[0], "canonical editorial correction ledger")
    receipt_bytes = source_manifest.authority_path(
        "canonical-editorial-correction-writer-receipt"
    ).read_bytes()
    receipt = _strict_json(
        receipt_bytes, "canonical editorial correction writer receipt"
    )
    expected_ledger = {
        "correction_id": "correction_13dda1f028ab491e",
        "resource_id": "adam-clarke",
        "record_path": "data/commentaries/adam-clarke/2-john.json",
        "entry_id": "adam-clarke.2John.1.9",
        "field_path": "commentary_text",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "hath",
        "after_text": "has",
        "status": "applied",
        "proposed_by": "phase-g-seed",
        "approved_by": "phase-g-seed",
        "applier_run_id": "cacafa053b054c0a97a8b31dd64fcd4f",
    }
    if any(ledger.get(key) != value for key, value in expected_ledger.items()):
        raise ValueError("Adam Clarke canonical correction ledger semantics drifted")
    expected_receipt = {
        "schema_version": "1.0.0",
        "writer": "applier",
        "writer_version": "build/tools/apply_correction.py@v1.0.0",
        "writer_identity": "correction_applier",
        "run_id": ledger["applier_run_id"],
        "data_paths": [ledger["record_path"]],
        "checksums": {
            ledger["record_path"]: {
                "before_sha256": "c0e296e9b193b005df9da1e666096358a1dc644d1b221478e666b8ee25d4aa6a",
                "after_sha256": "12157d1d851552dda296bf6e2015e467880bb3905e1cfc9d574f3ec3294ee37f",
            }
        },
        "expected_delta_counts": {
            ledger["record_path"]: {"entries_changed": 1, "fields_changed": 1}
        },
        "allowed_field_paths": ["/data/*/layers/commentary_text/display"],
        "partial_completion_policy": "all_or_nothing",
        "renames": [],
    }
    if any(receipt.get(key) != value for key, value in expected_receipt.items()):
        raise ValueError("Adam Clarke correction writer receipt semantics drifted")
    chapter = next(
        (item for item in chapters if item["relative_path"] == "2JN/1.json"), None
    )
    if chapter is None:
        raise ValueError("Adam Clarke retained correction anchor is absent")
    occurrences = chapter["chapter"]["content"]
    if not isinstance(occurrences, list) or len(occurrences) < 9:
        raise ValueError("Adam Clarke retained correction anchor shape drifted")
    occurrence = occurrences[8]
    if (
        not isinstance(occurrence, dict)
        or occurrence.get("type") != "verse"
        or occurrence.get("number") != 9
        or not isinstance(occurrence.get("content"), list)
        or len(occurrence["content"]) != 1
        or not isinstance(occurrence["content"][0], str)
        or occurrence["content"][0].count("hath not God") != 1
        or "has not God" in occurrence["content"][0]
    ):
        raise ValueError("Adam Clarke retained hath reading drifted")
    return {
        "ledger_authority_sha256": _sha(ledger_bytes),
        "writer_receipt_authority_sha256": _sha(receipt_bytes),
        "correction_id": ledger["correction_id"],
        "writer_run_id": receipt["run_id"],
        "retained_source_path": "raw/helloao_local/api/c/adam-clarke/2JN/1.json",
        "retained_occurrence_ordinal": 9,
        "retained_occurrence_number": 9,
        "retained_reading": ledger["before_text"],
        "canonical_record_path": ledger["record_path"],
        "canonical_entry_id": ledger["entry_id"],
        "canonical_field_path": ledger["field_path"],
        "canonical_display_reading": ledger["after_text"],
        "allowed_canonical_field_path": receipt["allowed_field_paths"][0],
        "disposition": "separate-display-layer-editorial-correction-not-applied-to-retained-source-tei",
    }


def _load_corpus(
    source_manifest: SourceManifest, records: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, object]:
        item = by_relative.get(relative)
        if item is None:
            raise ValueError(f"Adam Clarke manifest omits {relative}")
        return _strict_json(
            source_manifest.authority_path(str(item["name"])).read_bytes(), relative
        )

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    _require_key_order(books_record, _BOOKS_ROOT_KEYS, "books.json")
    _require_key_order(profiles_record, _PROFILES_ROOT_KEYS, "profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("Adam Clarke books.json shape is invalid")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError("Adam Clarke profiles metadata disagrees with books metadata")
    _require_key_order(commentary, _COMMENTARY_KEYS, "books.json commentary")
    profiles_commentary = profiles_record.get("commentary")
    if not isinstance(profiles_commentary, dict):
        raise ValueError("Adam Clarke profiles commentary is invalid")
    _require_key_order(
        profiles_commentary, _COMMENTARY_KEYS, "profiles.json commentary"
    )
    expected_commentary = {
        "id": "adam-clarke",
        "name": "Adam Clarke Bible Commentary",
        "website": "https://en.wikipedia.org/wiki/Adam_Clarke",
        "licenseUrl": "https://creativecommons.org/publicdomain/mark/1.0/",
        "licenseNotes": None,
        "englishName": "Adam Clarke Bible Commentary",
        "language": "eng",
        "textDirection": "rtl",
        "sha256": "92e28c9363c876d215e296f2fe04abb3ab7e34a2aacebdf06bd62ae79c6e3dba",
        "availableFormats": ["json"],
        "listOfBooksApiLink": "/api/c/adam-clarke/books.json",
        "listOfProfilesApiLink": "/api/c/adam-clarke/profiles.json",
        "numberOfBooks": 57,
        "totalNumberOfChapters": 854,
        "totalNumberOfVerses": 13318,
        "totalNumberOfProfiles": 0,
        "languageName": "English",
        "languageEnglishName": "English",
    }
    if commentary != expected_commentary:
        raise ValueError("Adam Clarke retained commentary identity or census drifted")
    if len(books) != 57:
        raise ValueError("Adam Clarke books.json must contain 57 books")

    chapters: list[dict[str, object]] = []
    seen_paths = {"books.json", "profiles.json"}
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict):
            raise ValueError("Adam Clarke book metadata is invalid")
        _require_key_order(
            raw_book, _BOOK_KEYS, f"books.json book ordinal {retained_ordinal}"
        )
        book_id = raw_book.get("id")
        chapter_count = raw_book.get("numberOfChapters")
        first = raw_book.get("firstChapterNumber")
        last = raw_book.get("lastChapterNumber")
        if (
            not isinstance(book_id, str)
            or not isinstance(raw_book.get("order"), int)
            or int(raw_book["order"]) <= previous_order
            or not isinstance(chapter_count, int)
            or first != 1
            or last != chapter_count
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                f"Adam Clarke book metadata drifted at retained ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        for chapter_number in range(1, chapter_count + 1):
            relative = f"{book_id}/{chapter_number}.json"
            chapter_record = load(relative)
            seen_paths.add(relative)
            _require_key_order(
                chapter_record, _CHAPTER_ENVELOPE_KEYS, f"chapter envelope {relative}"
            )
            chapter = chapter_record.get("chapter")
            if (
                chapter_record.get("commentary") != commentary
                or chapter_record.get("book") != raw_book
                or not isinstance(chapter, dict)
                or chapter.get("number") != chapter_number
                or not isinstance(chapter.get("content"), list)
            ):
                raise ValueError(f"Adam Clarke chapter envelope drifted at {relative}")
            expected_chapter_keys = (
                _CHAPTER_KEYS_WITH_INTRODUCTION
                if "introduction" in chapter
                else _CHAPTER_KEYS_WITHOUT_INTRODUCTION
            )
            _require_key_order(chapter, expected_chapter_keys, f"chapter {relative}")
            if "introduction" in chapter and not isinstance(
                chapter["introduction"], str
            ):
                raise ValueError(
                    f"Adam Clarke chapter introduction is invalid at {relative}"
                )
            for occurrence in chapter["content"]:
                if (
                    not isinstance(occurrence, dict)
                    or tuple(occurrence) != _OCCURRENCE_KEYS
                    or occurrence.get("type") != "verse"
                    or not isinstance(occurrence.get("number"), int)
                    or not isinstance(occurrence.get("content"), list)
                    or len(occurrence["content"]) != 1
                    or not isinstance(occurrence["content"][0], str)
                ):
                    raise ValueError(
                        f"Adam Clarke commentary occurrence is invalid at {relative}"
                    )
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "chapter": chapter,
                    "envelope": chapter_record,
                }
            )
    if seen_paths != set(by_relative) or len(chapters) != 854:
        raise ValueError(
            "Adam Clarke retained member coverage is incomplete or contains extras"
        )
    expected_links = [
        f"/api/c/adam-clarke/{item['book']['id']}/{item['chapter']['number']}.json"
        for item in chapters
    ]
    for ordinal, item in enumerate(chapters):
        envelope = item["envelope"]
        chapter = item["chapter"]
        relative = item["relative_path"]
        assert isinstance(envelope, dict) and isinstance(chapter, dict)
        expected_previous = expected_links[ordinal - 1] if ordinal else None
        expected_next = (
            expected_links[ordinal + 1] if ordinal + 1 < len(expected_links) else None
        )
        if (
            envelope["thisChapterLink"] != expected_links[ordinal]
            or envelope["previousChapterApiLink"] != expected_previous
            or envelope["nextChapterApiLink"] != expected_next
            or envelope["numberOfVerses"] != len(chapter["content"])
        ):
            raise ValueError(
                f"Adam Clarke source field accounting drifted at chapter envelope {relative}"
            )
    for raw_book in books:
        assert isinstance(raw_book, dict)
        book_id = str(raw_book["id"])
        book_chapters = [item for item in chapters if item["book"]["id"] == book_id]
        if (
            raw_book["commentaryId"] != commentary["id"]
            or raw_book["numberOfChapters"] != len(book_chapters)
            or raw_book["firstChapterNumber"] != 1
            or raw_book["firstChapterApiLink"] != f"/api/c/adam-clarke/{book_id}/1.json"
            or raw_book["lastChapterNumber"] != len(book_chapters)
            or raw_book["lastChapterApiLink"]
            != f"/api/c/adam-clarke/{book_id}/{len(book_chapters)}.json"
            or raw_book["totalNumberOfVerses"]
            != sum(int(item["envelope"]["numberOfVerses"]) for item in book_chapters)
        ):
            raise ValueError(
                f"Adam Clarke source field accounting drifted at book {book_id}"
            )
    if (
        commentary["numberOfBooks"] != len(books)
        or commentary["totalNumberOfChapters"] != len(chapters)
        or commentary["totalNumberOfVerses"]
        != sum(int(item["envelope"]["numberOfVerses"]) for item in chapters)
        or commentary["totalNumberOfProfiles"] != len(profiles_record["profiles"])
    ):
        raise ValueError(
            "Adam Clarke source field accounting drifted at commentary census"
        )
    return books_record, profiles_record, chapters


def _build_tei(
    books_record: dict[str, object],
    chapters: list[dict[str, object]],
    source_digest: str,
) -> bytes:
    commentary = books_record["commentary"]
    books = books_record["books"]
    assert isinstance(commentary, dict) and isinstance(books, list)
    by_book: dict[str, list[dict[str, object]]] = {}
    for item in chapters:
        raw_book = item["book"]
        assert isinstance(raw_book, dict) and isinstance(raw_book["id"], str)
        by_book.setdefault(raw_book["id"], []).append(item)

    tei = _el("TEI")
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text=str(commentary["name"])))
    title_stmt.append(_el("author", text="Adam Clarke"))
    file_desc.append(title_stmt)
    publication_stmt = _el("publicationStmt")
    publication_stmt.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "restricted"})
    availability.append(
        _el(
            "p",
            text=(
                "Retained HelloAO metadata applies the Public Domain Mark 1.0; "
                "the source config's CC0 label is recorded as drift and is not substituted."
            ),
        )
    )
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    notes_stmt = _el("notesStmt")
    header_notes = (
        ("commentary-id", commentary["id"]),
        ("english-name", commentary["englishName"]),
        ("website", commentary["website"]),
        ("license-url", commentary["licenseUrl"]),
        ("language", commentary["language"]),
        ("language-name", commentary["languageName"]),
        ("language-english-name", commentary["languageEnglishName"]),
        ("text-direction", commentary["textDirection"]),
        ("source-reported-sha256", commentary["sha256"]),
        ("book-count", str(commentary["numberOfBooks"])),
        ("chapter-count", str(commentary["totalNumberOfChapters"])),
        ("commentary-occurrence-count", str(commentary["totalNumberOfVerses"])),
        ("profile-count", str(commentary["totalNumberOfProfiles"])),
    )
    for kind, value in header_notes:
        notes_stmt.append(_el("note", {"type": kind}, str(value)))
    file_desc.append(notes_stmt)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("ptr", {"target": str(commentary["listOfBooksApiLink"])}))
    bibl.append(_el("idno", {"type": "sha256"}, source_digest))
    bibl.append(
        _el("note", {"type": "source-witness"}, "retained HelloAO JSON snapshot")
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    tei.append(header)

    text = _el("text", {"xml:lang": "eng"})
    body = _el("body")
    for raw_book in books:
        assert isinstance(raw_book, dict) and isinstance(raw_book["id"], str)
        book_id = raw_book["id"]
        book_div = _el(
            "div",
            {
                "type": "book",
                "n": book_id,
                "xml:id": f"book-{book_id}",
                "corresp": f"{_SOURCE_PREFIX}books.json",
            },
        )
        book_div.append(_el("head", text=str(raw_book["name"])))
        book_div.append(
            _el("note", {"type": "common-name"}, str(raw_book["commonName"]))
        )
        book_intro = _el(
            "div", {"type": "book-introduction", "xml:id": f"book-intro-{book_id}"}
        )
        book_intro.append(_el("p", text=str(raw_book["introduction"])))
        book_div.append(book_intro)
        for chapter_item in by_book[book_id]:
            chapter = chapter_item["chapter"]
            relative = chapter_item["relative_path"]
            assert isinstance(chapter, dict) and isinstance(relative, str)
            number = int(chapter["number"])
            chapter_div = _el(
                "div",
                {
                    "type": "chapter",
                    "n": str(number),
                    "xml:id": f"chapter-{book_id}-{number:03d}",
                    "corresp": f"{_SOURCE_PREFIX}{relative}",
                },
            )
            if "introduction" in chapter:
                chapter_intro = _el(
                    "div",
                    {
                        "type": "chapter-introduction",
                        "xml:id": f"chapter-intro-{book_id}-{number:03d}",
                    },
                )
                chapter_intro.append(_el("p", text=str(chapter["introduction"])))
                chapter_div.append(chapter_intro)
            content = chapter["content"]
            assert isinstance(content, list)
            for ordinal, raw_occurrence in enumerate(content, start=1):
                assert isinstance(raw_occurrence, dict)
                occurrence = _el(
                    "div",
                    {
                        "type": "commentary-occurrence",
                        "subtype": "verse",
                        "n": str(raw_occurrence["number"]),
                        "xml:id": f"commentary-{book_id}-{number:03d}-{ordinal:04d}",
                    },
                )
                occurrence.append(_el("p", text=str(raw_occurrence["content"][0])))
                chapter_div.append(occurrence)
            book_div.append(chapter_div)
        body.append(book_div)
    text.append(body)
    tei.append(text)
    return etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )


def _content_digests(
    books_record: dict[str, object], chapters: list[dict[str, object]]
) -> dict[str, str]:
    books = books_record["books"]
    assert isinstance(books, list)
    chapter_order: list[object] = []
    book_introductions: list[object] = []
    chapter_introductions: list[object] = []
    occurrences: list[object] = []
    for raw_book in books:
        assert isinstance(raw_book, dict)
        book_introductions.append(
            [
                raw_book["id"],
                raw_book["order"],
                _sha(str(raw_book["introduction"]).encode("utf-8")),
            ]
        )
    for item in chapters:
        chapter = item["chapter"]
        relative = item["relative_path"]
        assert isinstance(chapter, dict) and isinstance(relative, str)
        chapter_order.append([relative, chapter["number"]])
        chapter_introductions.append(
            [
                relative,
                "present" if "introduction" in chapter else "absent",
                _sha(str(chapter["introduction"]).encode("utf-8"))
                if "introduction" in chapter
                else None,
            ]
        )
        content = chapter["content"]
        assert isinstance(content, list)
        for ordinal, occurrence in enumerate(content, start=1):
            assert isinstance(occurrence, dict)
            occurrences.append(
                [
                    relative,
                    ordinal,
                    occurrence["number"],
                    _sha(str(occurrence["content"][0]).encode("utf-8")),
                ]
            )
    return {
        "book_order_sha256": _sha(
            _canonical([item["id"] for item in books if isinstance(item, dict)])
        ),
        "book_introductions_sha256": _sha(_canonical(book_introductions)),
        "chapter_order_sha256": _sha(_canonical(chapter_order)),
        "chapter_introductions_sha256": _sha(_canonical(chapter_introductions)),
        "commentary_occurrences_sha256": _sha(_canonical(occurrences)),
    }


def _field_dispositions() -> list[dict[str, str]]:
    object_fields = (
        ("books-envelope", _BOOKS_ROOT_KEYS),
        ("profiles-envelope", _PROFILES_ROOT_KEYS),
        ("commentary", _COMMENTARY_KEYS),
        ("book", _BOOK_KEYS),
        ("chapter-envelope", _CHAPTER_ENVELOPE_KEYS),
        ("chapter", _CHAPTER_KEYS_WITH_INTRODUCTION),
        ("commentary-occurrence", _OCCURRENCE_KEYS),
    )
    derived_commentary = {
        "listOfBooksApiLink",
        "listOfProfilesApiLink",
        "numberOfBooks",
        "totalNumberOfChapters",
        "totalNumberOfVerses",
        "totalNumberOfProfiles",
    }
    derived_book = {
        "commentaryId",
        "numberOfChapters",
        "firstChapterNumber",
        "firstChapterApiLink",
        "lastChapterNumber",
        "lastChapterApiLink",
        "totalNumberOfVerses",
    }
    navigation = {
        "thisChapterLink",
        "nextChapterApiLink",
        "previousChapterApiLink",
        "numberOfVerses",
    }
    records: list[dict[str, str]] = []
    for object_name, fields in object_fields:
        for field in fields:
            if object_name == "commentary":
                disposition = (
                    "preserved-in-accountability-and-recomputed"
                    if field in derived_commentary
                    else "preserved-in-accountability"
                )
                evidence = f"retained_metadata.{field}"
            elif object_name == "book":
                disposition = (
                    "preserved-in-accountability-and-recomputed"
                    if field in derived_book
                    else "preserved-in-accountability"
                )
                evidence = f"book_metadata[].{field}"
            elif object_name == "chapter-envelope" and field in navigation:
                disposition = "preserved-in-accountability-and-recomputed"
                evidence = f"chapter_navigation[].{field}"
            elif object_name in {"chapter", "commentary-occurrence"}:
                disposition = "projected-exactly-to-tei"
                evidence = f"content.tei.xml:{object_name}.{field}"
            elif object_name == "chapter-envelope" and field == "chapter":
                disposition = "projected-exactly-to-tei"
                evidence = "content.tei.xml:chapter"
            elif object_name == "profiles-envelope" and field == "profiles":
                disposition = "preserved-in-accountability"
                evidence = "profiles"
            elif object_name == "books-envelope" and field == "books":
                disposition = "preserved-in-accountability"
                evidence = "book_metadata"
            else:
                disposition = "verified-exact-repetition"
                evidence = f"retained source object:{object_name}.{field}"
            records.append(
                {
                    "object": object_name,
                    "field": field,
                    "disposition": disposition,
                    "evidence": evidence,
                }
            )
    return records


def _source_field_accounting(
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
) -> dict[str, object]:
    books = books_record["books"]
    assert isinstance(books, list)
    return {
        "contract": "ocd-helloao-adam-clarke-source-field-accounting-v1",
        "object_shapes": [
            {
                "object": "books-envelope",
                "instances": 1,
                "key_orders": [{"keys": list(_BOOKS_ROOT_KEYS), "instances": 1}],
            },
            {
                "object": "profiles-envelope",
                "instances": 1,
                "key_orders": [{"keys": list(_PROFILES_ROOT_KEYS), "instances": 1}],
            },
            {
                "object": "commentary",
                "instances": 856,
                "key_orders": [{"keys": list(_COMMENTARY_KEYS), "instances": 856}],
            },
            {
                "object": "book",
                "instances": 911,
                "key_orders": [{"keys": list(_BOOK_KEYS), "instances": 911}],
            },
            {
                "object": "chapter-envelope",
                "instances": 854,
                "key_orders": [
                    {"keys": list(_CHAPTER_ENVELOPE_KEYS), "instances": 854}
                ],
            },
            {
                "object": "chapter",
                "instances": 854,
                "key_orders": [
                    {
                        "keys": list(_CHAPTER_KEYS_WITH_INTRODUCTION),
                        "instances": 831,
                    },
                    {
                        "keys": list(_CHAPTER_KEYS_WITHOUT_INTRODUCTION),
                        "instances": 23,
                    },
                ],
            },
            {
                "object": "commentary-occurrence",
                "instances": 13_318,
                "key_orders": [{"keys": list(_OCCURRENCE_KEYS), "instances": 13_318}],
            },
        ],
        "field_dispositions": _field_dispositions(),
        "book_metadata": books,
        "profiles": profiles_record["profiles"],
        "chapter_navigation": [
            {
                "path": item["relative_path"],
                "thisChapterLink": item["envelope"]["thisChapterLink"],
                "nextChapterApiLink": item["envelope"]["nextChapterApiLink"],
                "previousChapterApiLink": item["envelope"]["previousChapterApiLink"],
                "numberOfVerses": item["envelope"]["numberOfVerses"],
            }
            for item in chapters
        ],
    }


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = _authority_json(source_manifest, "reconstruction-profile")
    policy = _authority_json(source_manifest, "validation-policy")
    config = _authority_json(source_manifest, "source-config")
    alternate = _authority_json(source_manifest, "alternate-witness-evidence")
    if (
        profile.get("contract") != "ocd-helloao-adam-clarke-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or policy.get("contract") != "ocd-helloao-adam-clarke-validation-policy-v1"
    ):
        raise ValueError("Adam Clarke reconstruction profile or policy mismatch")
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_corpus(source_manifest, records)
    correction_boundary = _canonical_editorial_correction_boundary(
        source_manifest, chapters
    )
    if profile.get("canonical_editorial_correction_boundary") != {
        "ledger_authority": "canonical-editorial-correction-ledger",
        "writer_receipt_authority": "canonical-editorial-correction-writer-receipt",
        "correction_id": correction_boundary["correction_id"],
        "retained_source_path": correction_boundary["retained_source_path"],
        "retained_occurrence_ordinal": 9,
        "retained_occurrence_number": 9,
        "retained_reading": "hath",
        "canonical_record_path": correction_boundary["canonical_record_path"],
        "canonical_entry_id": correction_boundary["canonical_entry_id"],
        "canonical_field_path": "commentary_text",
        "canonical_display_reading": "has",
        "disposition": correction_boundary["disposition"],
    }:
        raise ValueError("Adam Clarke correction boundary profile drifted")
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    source_digest = _source_set_digest(records)
    tei_bytes = _build_tei(books_record, chapters, source_digest)

    present_intros = sum("introduction" in item["chapter"] for item in chapters)
    occurrences = sum(len(item["chapter"]["content"]) for item in chapters)
    member_ledger = [
        {
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "disposition": "included",
            "reason": (
                "retained collection metadata"
                if item["relative_path"] in {"books.json", "profiles.json"}
                else "retained chapter commentary"
            ),
        }
        for item in records
    ]
    accountability = {
        "contract": "ocd-helloao-adam-clarke-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "source_root": _SOURCE_PREFIX.removesuffix("/"),
        "source_member_set_sha256": source_digest,
        "member_count": len(records),
        "total_bytes": sum(int(item["bytes"]) for item in records),
        "included_member_count": len(records),
        "excluded_member_count": 0,
        "members": member_ledger,
        "census": {
            "books": len(books_record["books"]),
            "chapters": len(chapters),
            "commentary_occurrences": occurrences,
            "book_introductions": len(books_record["books"]),
            "chapter_introductions_present": present_intros,
            "chapter_introductions_absent": len(chapters) - present_intros,
            "profiles": len(profiles_record["profiles"]),
        },
        "content_digests": _content_digests(books_record, chapters),
        "retained_metadata": commentary,
        "profiles": profiles_record["profiles"],
        "source_field_accounting": _source_field_accounting(
            books_record, profiles_record, chapters
        ),
        "config_drift": {
            "config_license": config.get("license"),
            "retained_license_url": commentary.get("licenseUrl"),
            "disposition": "retained PDM metadata governs this witness; CC0 is not substituted",
        },
        "alternate_witness": {
            "authority_sha256": _sha(
                source_manifest.authority_path(
                    "alternate-witness-evidence"
                ).read_bytes()
            ),
            "witness_id": alternate["witnesses"][0]["witness_id"],
            "disposition": "separate identity evidence; not merged",
        },
        "canonical_editorial_correction_boundary": correction_boundary,
    }
    provenance = {
        "contract": "ocd-helloao-adam-clarke-candidate-provenance-v1",
        "status": "nonaccepted",
        "identity": {
            "work_id": "adam-clarke",
            "retained_title": commentary["name"],
            "author": "Adam Clarke",
            "edition": None,
            "original_publication_year": None,
            "digital_witness": "retained HelloAO JSON snapshot",
        },
        "scope": {
            "complete_for_retained_witness": True,
            "book_count": 57,
            "canonical_bible_complete": False,
            "missing_canonical_books": profile["scope"]["missing_canonical_books"],
        },
        "rights": {
            "retained_mark": "PDM 1.0",
            "retained_license_url": commentary["licenseUrl"],
            "config_value_not_applied": config.get("license"),
            "attribution_ask": None,
        },
        "source_anomalies": {"retained_text_direction": commentary["textDirection"]},
        "alternate_witness": {
            "witness_id": alternate["witnesses"][0]["witness_id"],
            "edition": alternate["witnesses"][0]["edition"],
            "checksum_sha256": alternate["witnesses"][0]["checksum_sha256"],
            "merged": False,
        },
        "canonical_editorial_correction_boundary": correction_boundary,
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
        "human_decision": None,
    }
    unresolved = [
        {
            "id": "adam-clarke-rights-config-drift",
            "question": "Should any later acceptance describe the retained PDM mark differently from the source config's CC0 value?",
            "evidence": ["books.json:commentary.licenseUrl", "source-config:license"],
            "consequence": "candidate preserves PDM and does not assert CC0",
            "escalation": "human-review-only-if-acceptance-is-considered",
        },
        {
            "id": "adam-clarke-edition-and-alternate-witness-identity",
            "question": "What edition does the HelloAO JSON witness represent, and how does it relate to the separate 1836 Tegg volume-II scan?",
            "evidence": ["alternate-witness-evidence", "retained HelloAO metadata"],
            "consequence": "edition remains unset and witnesses are not merged",
            "escalation": "human-review-only-if-identity-is-decided",
        },
        {
            "id": "adam-clarke-retained-text-direction-anomaly",
            "question": "Is the retained rtl textDirection value an upstream metadata error?",
            "evidence": ["books.json:commentary.textDirection"],
            "consequence": "rtl remains explicit evidence and is not applied to the English TEI text",
            "escalation": "upstream-or-human-review",
        },
    ]
    readme = (
        "# Adam Clarke retained HelloAO witness\n\n"
        "This nonaccepted candidate faithfully represents all 856 retained JSON members under "
        "`raw/helloao_local/api/c/adam-clarke`: `books.json`, `profiles.json`, and 854 chapter files in 57 book directories.\n\n"
        "The retained witness contains 57 books, not all 66 books of the Protestant canon. It contains 13,318 ordered commentary occurrences. Occurrences are not sorted or merged; both distinct verse-27 occurrences in 2 Samuel 14 remain present. No Bible or BSB verse text is added.\n\n"
        "HelloAO metadata links the Public Domain Mark 1.0. The existing source config says CC0; this candidate records that drift and does not replace the retained PDM statement. PDM contains no attribution request, but HelloAO is identified as the retained API provider.\n\n"
        "The separate 1836 Tegg volume-II scan is identity evidence only and is not merged with this JSON witness. Edition identity, the rights-description drift, and retained `textDirection: rtl` anomaly remain localized questions. Accepted IR is `not_accepted`; publication is `not_ready`.\n"
        "\nThe retained 2 John 1:9 source and TEI preserve `hath not God`. Canonical display text uses `has not God` only through the separately bound applied correction ledger and historical applier receipt; that editorial display correction is not source evidence and is not applied to this retained-source TEI.\n"
    ).encode("utf-8")
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
