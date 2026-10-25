"""Faithful reconstruction of the complete retained HelloAO Matthew Henry JSON witness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-helloao-matthew-henry-json-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "helloao-matthew-henry-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/matthew-henry/"
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
        raise ValueError(f"Matthew Henry source field key order drifted at {label}")


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
        raise ValueError("Matthew Henry source authorities are invalid")
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
            raise ValueError("Matthew Henry primary-source authority is malformed")
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
    if (
        len(records) != 1_169
        or sum(int(item["bytes"]) for item in records) != 41_160_630
    ):
        raise ValueError(
            "Matthew Henry retained member census differs from 1,169/41,160,630"
        )
    relative = [str(item["relative_path"]) for item in records]
    if len(set(relative)) != 1_169:
        raise ValueError("Matthew Henry retained member paths are not unique")
    if set(relative) & {"books.json", "profiles.json"} != {
        "books.json",
        "profiles.json",
    }:
        raise ValueError("Matthew Henry retained metadata members are missing")
    chapter_paths = [
        item for item in relative if item not in {"books.json", "profiles.json"}
    ]
    if len(chapter_paths) != 1_167 or any(
        path.count("/") != 1 for path in chapter_paths
    ):
        raise ValueError("Matthew Henry chapter member paths are incomplete")
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


def _load_corpus(
    source_manifest: SourceManifest, records: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, object]:
        item = by_relative.get(relative)
        if item is None:
            raise ValueError(f"Matthew Henry manifest omits {relative}")
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
        raise ValueError("Matthew Henry books.json shape is invalid")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError(
            "Matthew Henry profiles metadata disagrees with books metadata"
        )
    _require_key_order(commentary, _COMMENTARY_KEYS, "books.json commentary")
    profiles_commentary = profiles_record.get("commentary")
    if not isinstance(profiles_commentary, dict):
        raise ValueError("Matthew Henry profiles commentary is invalid")
    _require_key_order(
        profiles_commentary, _COMMENTARY_KEYS, "profiles.json commentary"
    )
    expected_commentary = {
        "id": "matthew-henry",
        "name": "Matthew Henry Bible Commentary",
        "website": "https://en.wikipedia.org/wiki/Matthew_Henry",
        "licenseUrl": "https://creativecommons.org/publicdomain/mark/1.0/",
        "licenseNotes": None,
        "englishName": "Matthew Henry Bible Commentary",
        "language": "eng",
        "textDirection": "rtl",
        "sha256": "ad2850450a1e5c0546c275f4bd09b9325ae47424d83311120ca7ced5724c4bc8",
        "availableFormats": ["json"],
        "listOfBooksApiLink": "/api/c/matthew-henry/books.json",
        "listOfProfilesApiLink": "/api/c/matthew-henry/profiles.json",
        "numberOfBooks": 65,
        "totalNumberOfChapters": 1167,
        "totalNumberOfVerses": 4124,
        "totalNumberOfProfiles": 0,
        "languageName": "English",
        "languageEnglishName": "English",
    }
    if commentary != expected_commentary:
        raise ValueError("Matthew Henry retained commentary identity or census drifted")
    if len(books) != 65:
        raise ValueError("Matthew Henry books.json must contain 65 books")

    chapter_paths_by_book: dict[str, list[tuple[int, str]]] = {}
    for relative in by_relative:
        if relative in {"books.json", "profiles.json"}:
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            raise ValueError(f"Matthew Henry chapter path is invalid: {relative}")
        try:
            number = int(parts[1].removesuffix(".json"))
        except ValueError as exc:
            raise ValueError(
                f"Matthew Henry chapter path is invalid: {relative}"
            ) from exc
        if number < 1:
            raise ValueError(f"Matthew Henry chapter number is invalid: {relative}")
        chapter_paths_by_book.setdefault(parts[0], []).append((number, relative))

    chapters: list[dict[str, object]] = []
    seen_paths = {"books.json", "profiles.json"}
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict):
            raise ValueError("Matthew Henry book metadata is invalid")
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
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                f"Matthew Henry book metadata drifted at retained ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        book_paths = sorted(chapter_paths_by_book.pop(book_id, []))
        if len(book_paths) != chapter_count:
            raise ValueError(
                f"Matthew Henry retained chapter count disagrees at {book_id}"
            )
        observed_numbers = [number for number, _ in book_paths]
        expected_missing = [67] if book_id == "ISA" else []
        if (
            not isinstance(last, int)
            or [
                number
                for number in range(first, last + 1)
                if number not in observed_numbers
            ]
            != expected_missing
            or any(number < first or number > last for number in observed_numbers)
        ):
            raise ValueError(
                f"Matthew Henry retained chapter range drifted at {book_id}"
            )
        for chapter_number, relative in book_paths:
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
                raise ValueError(
                    f"Matthew Henry chapter envelope drifted at {relative}"
                )
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
                    f"Matthew Henry chapter introduction is invalid at {relative}"
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
                        f"Matthew Henry commentary occurrence is invalid at {relative}"
                    )
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "chapter": chapter,
                    "envelope": chapter_record,
                }
            )
    if (
        chapter_paths_by_book
        or seen_paths != set(by_relative)
        or len(chapters) != 1_167
    ):
        raise ValueError(
            "Matthew Henry retained member coverage is incomplete or contains extras"
        )
    expected_links = [
        f"/api/c/matthew-henry/{item['book']['id']}/{item['chapter']['number']}.json"
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
                f"Matthew Henry source field accounting drifted at chapter envelope {relative}"
            )
    for raw_book in books:
        assert isinstance(raw_book, dict)
        book_id = str(raw_book["id"])
        book_chapters = [item for item in chapters if item["book"]["id"] == book_id]
        if (
            raw_book["commentaryId"] != commentary["id"]
            or raw_book["numberOfChapters"] != len(book_chapters)
            or raw_book["firstChapterNumber"] != 1
            or raw_book["firstChapterApiLink"]
            != f"/api/c/matthew-henry/{book_id}/1.json"
            or raw_book["lastChapterNumber"]
            != max(int(item["chapter"]["number"]) for item in book_chapters)
            or raw_book["lastChapterApiLink"]
            != f"/api/c/matthew-henry/{book_id}/{max(int(item['chapter']['number']) for item in book_chapters)}.json"
            or raw_book["totalNumberOfVerses"]
            != sum(int(item["envelope"]["numberOfVerses"]) for item in book_chapters)
        ):
            raise ValueError(
                f"Matthew Henry source field accounting drifted at book {book_id}"
            )
    if (
        commentary["numberOfBooks"] != len(books)
        or commentary["totalNumberOfChapters"] != len(chapters)
        or commentary["totalNumberOfVerses"]
        != sum(int(item["envelope"]["numberOfVerses"]) for item in chapters)
        or commentary["totalNumberOfProfiles"] != len(profiles_record["profiles"])
    ):
        raise ValueError(
            "Matthew Henry source field accounting drifted at commentary census"
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
        "contract": "ocd-helloao-matthew-henry-source-field-accounting-v1",
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
                "instances": 1_169,
                "key_orders": [{"keys": list(_COMMENTARY_KEYS), "instances": 1_169}],
            },
            {
                "object": "book",
                "instances": 1_232,
                "key_orders": [{"keys": list(_BOOK_KEYS), "instances": 1_232}],
            },
            {
                "object": "chapter-envelope",
                "instances": 1_167,
                "key_orders": [
                    {"keys": list(_CHAPTER_ENVELOPE_KEYS), "instances": 1_167}
                ],
            },
            {
                "object": "chapter",
                "instances": 1_167,
                "key_orders": [
                    {
                        "keys": list(_CHAPTER_KEYS_WITH_INTRODUCTION),
                        "instances": 1_156,
                    },
                    {
                        "keys": list(_CHAPTER_KEYS_WITHOUT_INTRODUCTION),
                        "instances": 11,
                    },
                ],
            },
            {
                "object": "commentary-occurrence",
                "instances": 4_124,
                "key_orders": [{"keys": list(_OCCURRENCE_KEYS), "instances": 4_124}],
            },
        ],
        "json_object_instances": 8_861,
        "json_field_instances": 61_093,
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
    if (
        profile.get("contract") != "ocd-helloao-matthew-henry-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or policy.get("contract") != "ocd-helloao-matthew-henry-validation-policy-v1"
    ):
        raise ValueError("Matthew Henry reconstruction profile or policy mismatch")
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_corpus(source_manifest, records)
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
        "contract": "ocd-helloao-matthew-henry-source-accountability-v1",
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
        "coverage_gaps": {
            "missing_canonical_books": ["SNG"],
            "partial_books": {"MAT": [*range(19, 29)], "JON": [2, 3, 4]},
            "retained_path_gaps": {"ISA": [67]},
            "introduction_only_chapters": [
                str(item["relative_path"])
                for item in chapters
                if not item["chapter"]["content"]
            ],
            "disposition": "preserved exactly; no absent or empty target is invented",
        },
    }
    provenance = {
        "contract": "ocd-helloao-matthew-henry-candidate-provenance-v1",
        "status": "nonaccepted",
        "identity": {
            "work_id": "matthew-henry-complete",
            "retained_title": commentary["name"],
            "author": None,
            "edition": None,
            "original_publication_year": None,
            "digital_witness": "retained HelloAO JSON snapshot",
        },
        "scope": {
            "complete_for_retained_witness": True,
            "book_count": 65,
            "canonical_bible_complete": False,
            "missing_canonical_books": profile["scope"]["missing_canonical_books"],
            "partial_canonical_books": profile["scope"]["partial_canonical_books"],
            "retained_path_gaps": profile["scope"]["retained_path_gaps"],
            "introduction_only_chapters": profile["scope"][
                "introduction_only_chapters"
            ],
        },
        "rights": {
            "retained_mark": "PDM 1.0",
            "retained_license_url": commentary["licenseUrl"],
            "config_value_not_applied": config.get("license"),
            "attribution_ask": None,
        },
        "source_anomalies": {"retained_text_direction": commentary["textDirection"]},
        "accepted_ir": "not_accepted",
        "human_review": "required",
        "publication": "not_ready",
        "human_decision": None,
    }
    unresolved = [
        {
            "id": "matthew-henry-rights-config-drift",
            "question": "Should any later acceptance describe the retained PDM mark differently from the source config's CC0 value?",
            "evidence": ["books.json:commentary.licenseUrl", "source-config:license"],
            "consequence": "candidate preserves PDM and does not assert CC0",
            "escalation": "human-review-only-if-acceptance-is-considered",
        },
        {
            "id": "matthew-henry-edition-and-authorship-identity",
            "question": "Which edition and exact author or posthumous-contributor statement does the retained HelloAO JSON witness represent?",
            "evidence": ["retained HelloAO metadata", "source-config"],
            "consequence": "edition, author statement, and original publication year remain unset",
            "escalation": "human-review-only-if-identity-is-decided",
        },
        {
            "id": "matthew-henry-retained-text-direction-anomaly",
            "question": "Is the retained rtl textDirection value an upstream metadata error?",
            "evidence": ["books.json:commentary.textDirection"],
            "consequence": "rtl remains explicit evidence and is not applied to the English TEI text",
            "escalation": "upstream-or-human-review",
        },
        {
            "id": "matthew-henry-retained-coverage-gaps-and-empty-targets",
            "question": "Do the absent Song of Solomon, Matthew 19-28, Jonah 2-4, ISA/67 target, and nine introduction-only retained targets reflect the intended witness or upstream extraction defects?",
            "evidence": [
                "books.json",
                "retained chapter path set",
                "source-config:known_coverage_gaps",
            ],
            "consequence": "the exact retained 65-book/1,167-member chapter scope is represented without filling gaps or empty targets",
            "escalation": "upstream-or-human-review-before-any-complete-canonical-bible-claim",
        },
    ]
    readme = (
        "# Matthew Henry retained HelloAO witness\n\n"
        "This nonaccepted candidate faithfully represents all 1,169 retained JSON members under "
        "`raw/helloao_local/api/c/matthew-henry`: `books.json`, `profiles.json`, and 1,167 chapter files in 65 book directories.\n\n"
        "The retained witness contains 4,124 ordered commentary occurrences. Occurrences are not sorted or merged; both distinct verse-1 occurrences in Ezekiel 40 remain present. Song of Solomon is absent; Matthew ends at chapter 18; Jonah ends at chapter 1; `ISA/67.json` is absent while `ISA/68.json` is retained; and nine retained chapters contain introductions but no commentary occurrences. These gaps and empty targets remain explicit. No chapter, range, or Bible text is inferred.\n\n"
        "HelloAO metadata links the Public Domain Mark 1.0. The existing source config says CC0; this candidate records that drift and does not replace the retained PDM statement. PDM contains no attribution request, but HelloAO is identified as the retained API provider.\n\n"
        "Edition and exact authorship or posthumous-contributor identity, the rights-description drift, retained `textDirection: rtl` anomaly, and retained coverage gaps remain localized questions. Accepted IR is `not_accepted`; human review is `required`; publication is `not_ready`.\n"
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
