"""Producer-independent oracle for the complete retained Matthew Henry JSON witness."""

from __future__ import annotations

import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Mapping
from xml.parsers import expat

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import (
    MechanicalFacts,
    verify_mechanical_facts,
)
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-helloao-matthew-henry-source-to-tei-oracle"
ORACLE_VERSION = "1"
_PROFILE_ID = "helloao-matthew-henry-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/matthew-henry/"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
_EXPECTED_TEI_PROLOG = b"<?xml version='1.0' encoding='UTF-8'?>\n"

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


def _json(content: bytes, label: str) -> dict[str, object]:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        result = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be a JSON object")
    return result


def _primary_members(source_manifest: SourceManifest) -> tuple[dict[str, object], ...]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Matthew Henry source authorities are invalid")
    records: list[dict[str, object]] = []
    for authority in authorities:
        if (
            not isinstance(authority, Mapping)
            or authority.get("role") != "primary-source"
        ):
            continue
        path = authority.get("path")
        if not isinstance(path, str) or not path.startswith(_SOURCE_PREFIX):
            raise ValueError(
                "Matthew Henry primary-source path escaped the retained root"
            )
        records.append(
            {
                "name": authority.get("name"),
                "path": path,
                "bytes": authority.get("bytes"),
                "sha256": authority.get("sha256"),
                "relative_path": path.removeprefix(_SOURCE_PREFIX),
            }
        )
    records.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    relative = [str(item["relative_path"]) for item in records]
    if (
        len(records) != 1_169
        or len(set(relative)) != 1_169
        or sum(int(item["bytes"]) for item in records) != 41_160_630
        or set(relative) & {"books.json", "profiles.json"}
        != {"books.json", "profiles.json"}
        or len(
            [path for path in relative if path not in {"books.json", "profiles.json"}]
        )
        != 1_167
    ):
        raise ValueError("Matthew Henry exact retained member census failed")
    retained_root = (
        source_manifest.repository_root / _SOURCE_PREFIX.removesuffix("/")
    ).resolve(strict=True)
    actual = {
        path.relative_to(retained_root).as_posix()
        for path in retained_root.rglob("*")
        if path.is_file()
    }
    if actual != set(relative):
        raise ValueError(
            "Matthew Henry retained root contains an unbound or missing member"
        )
    return tuple(records)


def _source_digest(records: tuple[dict[str, object], ...]) -> str:
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


def _load_retained(
    source_manifest: SourceManifest, records: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, object]:
        item = by_relative.get(relative)
        if item is None or not isinstance(item.get("name"), str):
            raise ValueError(f"Matthew Henry manifest lacks {relative}")
        content = source_manifest.authority_path(str(item["name"])).read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(f"Matthew Henry retained bytes drifted at {relative}")
        return _json(content, relative)

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    _require_key_order(books_record, _BOOKS_ROOT_KEYS, "books.json")
    _require_key_order(profiles_record, _PROFILES_ROOT_KEYS, "profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if (
        not isinstance(commentary, dict)
        or not isinstance(books, list)
        or len(books) != 65
    ):
        raise ValueError("Matthew Henry retained books metadata is invalid")
    _require_key_order(commentary, _COMMENTARY_KEYS, "books.json commentary")
    profiles_commentary = profiles_record.get("commentary")
    if not isinstance(profiles_commentary, dict):
        raise ValueError("Matthew Henry profiles commentary is invalid")
    _require_key_order(
        profiles_commentary, _COMMENTARY_KEYS, "profiles.json commentary"
    )
    if commentary != {
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
        "totalNumberOfChapters": 1_167,
        "totalNumberOfVerses": 4_124,
        "totalNumberOfProfiles": 0,
        "languageName": "English",
        "languageEnglishName": "English",
    }:
        raise ValueError("Matthew Henry retained commentary source fields drifted")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError("Matthew Henry retained profiles metadata is invalid")
    chapter_paths_by_book: dict[str, list[tuple[int, str]]] = {}
    for relative in by_relative:
        if relative in {"books.json", "profiles.json"}:
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            raise ValueError(f"Matthew Henry retained chapter path drifted: {relative}")
        try:
            number = int(parts[1].removesuffix(".json"))
        except ValueError as exc:
            raise ValueError(
                f"Matthew Henry retained chapter path drifted: {relative}"
            ) from exc
        if number < 1:
            raise ValueError(f"Matthew Henry retained chapter path drifted: {relative}")
        chapter_paths_by_book.setdefault(parts[0], []).append((number, relative))

    chapters: list[dict[str, object]] = []
    covered = {"books.json", "profiles.json"}
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict):
            raise ValueError("Matthew Henry retained book is not an object")
        _require_key_order(
            raw_book, _BOOK_KEYS, f"books.json book ordinal {retained_ordinal}"
        )
        book_id = raw_book.get("id")
        count = raw_book.get("numberOfChapters")
        if (
            not isinstance(book_id, str)
            or not isinstance(count, int)
            or not isinstance(raw_book.get("order"), int)
            or int(raw_book["order"]) <= previous_order
            or raw_book.get("firstChapterNumber") != 1
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                "Matthew Henry retained book order or structure drifted "
                f"at ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        book_paths = sorted(chapter_paths_by_book.pop(book_id, []))
        if len(book_paths) != count:
            raise ValueError(
                f"Matthew Henry retained chapter count drifted at {book_id}"
            )
        observed_numbers = [number for number, _ in book_paths]
        last = raw_book.get("lastChapterNumber")
        expected_missing = [67] if book_id == "ISA" else []
        if (
            not isinstance(last, int)
            or [
                number
                for number in range(1, last + 1)
                if number not in observed_numbers
            ]
            != expected_missing
            or any(number > last for number in observed_numbers)
        ):
            raise ValueError(
                f"Matthew Henry retained chapter range drifted at {book_id}"
            )
        for number, relative in book_paths:
            envelope = load(relative)
            covered.add(relative)
            _require_key_order(
                envelope, _CHAPTER_ENVELOPE_KEYS, f"chapter envelope {relative}"
            )
            chapter = envelope.get("chapter")
            if (
                envelope.get("commentary") != commentary
                or envelope.get("book") != raw_book
                or not isinstance(chapter, dict)
                or chapter.get("number") != number
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
                    f"Matthew Henry chapter introduction drifted at {relative}"
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
                    raise ValueError(f"Matthew Henry occurrence drifted at {relative}")
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "chapter": chapter,
                    "envelope": envelope,
                }
            )
    if chapter_paths_by_book or covered != set(by_relative) or len(chapters) != 1_167:
        raise ValueError("Matthew Henry member inclusion/exclusion accounting failed")
    expected_links = [
        f"/api/c/matthew-henry/{item['book']['id']}/{item['chapter']['number']}.json"
        for item in chapters
    ]
    for ordinal, item in enumerate(chapters):
        envelope = item["envelope"]
        chapter = item["chapter"]
        relative = item["relative_path"]
        assert isinstance(envelope, dict) and isinstance(chapter, dict)
        if (
            envelope["thisChapterLink"] != expected_links[ordinal]
            or envelope["previousChapterApiLink"]
            != (expected_links[ordinal - 1] if ordinal else None)
            or envelope["nextChapterApiLink"]
            != (
                expected_links[ordinal + 1]
                if ordinal + 1 < len(expected_links)
                else None
            )
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


def _content_digests(
    books_record: dict[str, object], chapters: list[dict[str, object]]
) -> dict[str, str]:
    books = books_record["books"]
    assert isinstance(books, list)
    book_intros: list[object] = []
    chapter_order: list[object] = []
    chapter_intros: list[object] = []
    occurrences: list[object] = []
    for raw_book in books:
        assert isinstance(raw_book, dict)
        book_intros.append(
            [
                raw_book["id"],
                raw_book["order"],
                _sha(str(raw_book["introduction"]).encode("utf-8")),
            ]
        )
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        assert isinstance(relative, str) and isinstance(chapter, dict)
        chapter_order.append([relative, chapter["number"]])
        chapter_intros.append(
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
        "book_introductions_sha256": _sha(_canonical(book_intros)),
        "chapter_order_sha256": _sha(_canonical(chapter_order)),
        "chapter_introductions_sha256": _sha(_canonical(chapter_intros)),
        "commentary_occurrences_sha256": _sha(_canonical(occurrences)),
    }


def _expected_field_dispositions() -> list[dict[str, str]]:
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
    result: list[dict[str, str]] = []
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
            result.append(
                {
                    "object": object_name,
                    "field": field,
                    "disposition": disposition,
                    "evidence": evidence,
                }
            )
    return result


def _expected_source_field_accounting(
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
) -> dict[str, object]:
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
        "field_dispositions": _expected_field_dispositions(),
        "book_metadata": books_record["books"],
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


def _verify_accountability(
    source_manifest: SourceManifest,
    records: tuple[dict[str, object], ...],
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
    accountability: dict[str, object],
) -> None:
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    config = _json(
        source_manifest.authority_path("source-config").read_bytes(), "source config"
    )
    expected_members = [
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
    present = sum("introduction" in item["chapter"] for item in chapters)
    expected = {
        "contract": "ocd-helloao-matthew-henry-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "source_root": _SOURCE_PREFIX.removesuffix("/"),
        "source_member_set_sha256": _source_digest(records),
        "member_count": 1_169,
        "total_bytes": 41_160_630,
        "included_member_count": 1_169,
        "excluded_member_count": 0,
        "members": expected_members,
        "census": {
            "books": 65,
            "chapters": 1_167,
            "commentary_occurrences": sum(
                len(item["chapter"]["content"]) for item in chapters
            ),
            "book_introductions": 65,
            "chapter_introductions_present": present,
            "chapter_introductions_absent": 1_167 - present,
            "profiles": len(profiles_record["profiles"]),
        },
        "content_digests": _content_digests(books_record, chapters),
        "retained_metadata": commentary,
        "profiles": profiles_record["profiles"],
        "source_field_accounting": _expected_source_field_accounting(
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
    if accountability != expected:
        raise ValueError(
            "Matthew Henry source accountability omission, exclusion, or drift"
        )


def _element_children(node: etree._Element) -> list[etree._Element]:
    children = list(node)
    if any(not isinstance(child.tag, str) for child in children):
        raise ValueError(
            "Matthew Henry TEI contains an unaccounted comment or instruction"
        )
    return children


def _assert_element(
    node: etree._Element,
    name: str,
    attributes: Mapping[str, str],
    text: str | None,
    label: str,
) -> None:
    observed_attributes = {
        (
            "xml:id"
            if key == f"{{{_XML_NS}}}id"
            else "xml:lang"
            if key == f"{{{_XML_NS}}}lang"
            else key
        ): value
        for key, value in node.attrib.items()
    }
    if (
        etree.QName(node).localname != name
        or etree.QName(node).namespace != _TEI_NS
        or observed_attributes != dict(attributes)
        or node.text != text
        or node.tail is not None
    ):
        raise ValueError(f"Matthew Henry TEI {label} drifted")


def _assert_leaf(
    node: etree._Element,
    name: str,
    attributes: Mapping[str, str],
    text: str | None,
    label: str,
) -> None:
    _assert_element(node, name, attributes, text, label)
    if len(node) != 0:
        raise ValueError(f"Matthew Henry TEI {label} contains unaccounted descendants")


def _expected_element(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    normalized: dict[str, str] = {}
    for key, value in (attributes or {}).items():
        if key == "xml:id":
            normalized[f"{{{_XML_NS}}}id"] = value
        elif key == "xml:lang":
            normalized[f"{{{_XML_NS}}}lang"] = value
        else:
            normalized[key] = value
    element = etree.Element(f"{{{_TEI_NS}}}{name}", normalized)
    element.text = text
    return element


def _expected_header(
    commentary: dict[str, object], source_digest: str
) -> etree._Element:
    header = _expected_element("teiHeader")
    file_desc = _expected_element("fileDesc")
    title_stmt = _expected_element("titleStmt")
    title_stmt.append(_expected_element("title", text=str(commentary["name"])))
    file_desc.append(title_stmt)
    publication_stmt = _expected_element("publicationStmt")
    publication_stmt.append(_expected_element("publisher", text="Open Christian Data"))
    availability = _expected_element("availability", {"status": "restricted"})
    availability.append(
        _expected_element(
            "p",
            text=(
                "Retained HelloAO metadata applies the Public Domain Mark 1.0; "
                "the source config's CC0 label is recorded as drift and is not substituted."
            ),
        )
    )
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    notes_stmt = _expected_element("notesStmt")
    notes = (
        ("commentary-id", commentary["id"]),
        ("english-name", commentary["englishName"]),
        ("website", commentary["website"]),
        ("license-url", commentary["licenseUrl"]),
        ("language", commentary["language"]),
        ("language-name", commentary["languageName"]),
        ("language-english-name", commentary["languageEnglishName"]),
        ("text-direction", commentary["textDirection"]),
        ("source-reported-sha256", commentary["sha256"]),
        ("book-count", commentary["numberOfBooks"]),
        ("chapter-count", commentary["totalNumberOfChapters"]),
        ("commentary-occurrence-count", commentary["totalNumberOfVerses"]),
        ("profile-count", commentary["totalNumberOfProfiles"]),
    )
    for kind, value in notes:
        notes_stmt.append(_expected_element("note", {"type": kind}, str(value)))
    file_desc.append(notes_stmt)
    source_desc = _expected_element("sourceDesc")
    bibl = _expected_element("bibl")
    bibl.append(
        _expected_element("ptr", {"target": str(commentary["listOfBooksApiLink"])})
    )
    bibl.append(_expected_element("idno", {"type": "sha256"}, source_digest))
    bibl.append(
        _expected_element(
            "note", {"type": "source-witness"}, "retained HelloAO JSON snapshot"
        )
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _expected_body(
    books_record: dict[str, object], chapters: list[dict[str, object]]
) -> etree._Element:
    books = books_record["books"]
    assert isinstance(books, list)
    by_book: dict[str, list[dict[str, object]]] = {}
    for item in chapters:
        raw_book = item["book"]
        assert isinstance(raw_book, dict)
        by_book.setdefault(str(raw_book["id"]), []).append(item)
    body = _expected_element("body")
    for raw_book in books:
        assert isinstance(raw_book, dict)
        book_id = str(raw_book["id"])
        book = _expected_element(
            "div",
            {
                "type": "book",
                "n": book_id,
                "xml:id": f"book-{book_id}",
                "corresp": f"{_SOURCE_PREFIX}books.json",
            },
        )
        book.append(_expected_element("head", text=str(raw_book["name"])))
        book.append(
            _expected_element(
                "note", {"type": "common-name"}, str(raw_book["commonName"])
            )
        )
        book_intro = _expected_element(
            "div", {"type": "book-introduction", "xml:id": f"book-intro-{book_id}"}
        )
        book_intro.append(_expected_element("p", text=str(raw_book["introduction"])))
        book.append(book_intro)
        for item in by_book[book_id]:
            chapter = item["chapter"]
            relative = item["relative_path"]
            assert isinstance(chapter, dict) and isinstance(relative, str)
            number = int(chapter["number"])
            chapter_node = _expected_element(
                "div",
                {
                    "type": "chapter",
                    "n": str(number),
                    "xml:id": f"chapter-{book_id}-{number:03d}",
                    "corresp": f"{_SOURCE_PREFIX}{relative}",
                },
            )
            if "introduction" in chapter:
                intro = _expected_element(
                    "div",
                    {
                        "type": "chapter-introduction",
                        "xml:id": f"chapter-intro-{book_id}-{number:03d}",
                    },
                )
                intro.append(_expected_element("p", text=str(chapter["introduction"])))
                chapter_node.append(intro)
            content = chapter["content"]
            assert isinstance(content, list)
            for ordinal, occurrence in enumerate(content, start=1):
                assert isinstance(occurrence, dict)
                occurrence_node = _expected_element(
                    "div",
                    {
                        "type": "commentary-occurrence",
                        "subtype": "verse",
                        "n": str(occurrence["number"]),
                        "xml:id": f"commentary-{book_id}-{number:03d}-{ordinal:04d}",
                    },
                )
                occurrence_node.append(
                    _expected_element("p", text=str(occurrence["content"][0]))
                )
                chapter_node.append(occurrence_node)
            book.append(chapter_node)
        body.append(book)
    return body


def _expected_tei_bytes(
    books_record: dict[str, object],
    chapters: list[dict[str, object]],
    source_digest: str,
) -> bytes:
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    root = etree.Element(f"{{{_TEI_NS}}}TEI", nsmap={None: _TEI_NS})
    root.append(_expected_header(commentary, source_digest))
    text = _expected_element("text", {"xml:lang": "eng"})
    text.append(_expected_body(books_record, chapters))
    root.append(text)
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def _assert_exact_tree(
    observed: etree._Element, expected: etree._Element, label: str
) -> None:
    if (
        observed.tag != expected.tag
        or dict(observed.attrib) != dict(expected.attrib)
        or observed.text != expected.text
        or observed.tail != expected.tail
        or len(observed) != len(expected)
    ):
        raise ValueError(f"Matthew Henry TEI {label} tree drifted")
    for index, (observed_child, expected_child) in enumerate(
        zip(observed, expected, strict=True), start=1
    ):
        _assert_exact_tree(observed_child, expected_child, f"{label}/{index}")


def _verify_namespace_declarations(tei_bytes: bytes) -> None:
    element_ordinal = 0

    def start_element(_name: str, attributes: dict[str, str]) -> None:
        nonlocal element_ordinal
        element_ordinal += 1
        declarations = {
            name: value
            for name, value in attributes.items()
            if name == "xmlns" or name.startswith("xmlns:")
        }
        expected = {"xmlns": _TEI_NS} if element_ordinal == 1 else {}
        if declarations != expected:
            raise ValueError(
                "Matthew Henry TEI namespace declarations drifted at "
                f"element {element_ordinal}"
            )

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(tei_bytes, True)
    except expat.ExpatError as exc:
        raise ValueError("Matthew Henry candidate is not safe well-formed XML") from exc


def _parse_candidate_tei(tei_bytes: bytes) -> etree._ElementTree:
    if not tei_bytes.startswith(_EXPECTED_TEI_PROLOG):
        raise ValueError("Matthew Henry TEI document prolog drift")
    if tei_bytes[len(_EXPECTED_TEI_PROLOG) : len(_EXPECTED_TEI_PROLOG) + 1] != b"<":
        raise ValueError("Matthew Henry TEI document prolog drift")
    try:
        tree = etree.parse(
            BytesIO(tei_bytes),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                huge_tree=True,
                remove_blank_text=True,
                remove_comments=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("Matthew Henry candidate is not safe well-formed XML") from exc
    if tree.docinfo.doctype:
        raise ValueError("Matthew Henry TEI document prolog drift")
    return tree


def _verify_tei(
    tei_bytes: bytes,
    books_record: dict[str, object],
    chapters: list[dict[str, object]],
    source_digest: str,
) -> None:
    tree = _parse_candidate_tei(tei_bytes)
    root = tree.getroot()
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError(
            "Matthew Henry TEI contains an unaccounted document-level node"
        )
    _verify_namespace_declarations(tei_bytes)
    ns = {"tei": _TEI_NS, "xml": _XML_NS}
    if (
        etree.QName(root).localname != "TEI"
        or etree.QName(root).namespace != _TEI_NS
        or root.attrib
        or root.text is not None
        or root.tail is not None
    ):
        raise ValueError("Matthew Henry TEI root drifted")
    root_children = _element_children(root)
    if [etree.QName(item).localname for item in root_children] != ["teiHeader", "text"]:
        raise ValueError("Matthew Henry TEI root member order drifted")
    commentary = books_record["commentary"]
    books = books_record["books"]
    assert isinstance(commentary, dict) and isinstance(books, list)
    try:
        _assert_exact_tree(
            root_children[0], _expected_header(commentary, source_digest), "header"
        )
    except ValueError as exc:
        raise ValueError("Matthew Henry TEI header tree drifted") from exc
    observed_header = {
        "title": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces=ns
        ),
        "author": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author)", namespaces=ns
        ),
        "publisher": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:publisher)",
            namespaces=ns,
        ),
        "availability": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/@status)",
            namespaces=ns,
        ),
        "rights": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability/tei:p)",
            namespaces=ns,
        ),
        "source": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr/@target)",
            namespaces=ns,
        ),
        "digest": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256'])",
            namespaces=ns,
        ),
        "witness": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:note[@type='source-witness'])",
            namespaces=ns,
        ),
    }
    expected_header = {
        "title": commentary["name"],
        "author": "",
        "publisher": "Open Christian Data",
        "availability": "restricted",
        "rights": "Retained HelloAO metadata applies the Public Domain Mark 1.0; the source config's CC0 label is recorded as drift and is not substituted.",
        "source": commentary["listOfBooksApiLink"],
        "digest": source_digest,
        "witness": "retained HelloAO JSON snapshot",
    }
    if observed_header != expected_header:
        raise ValueError(
            "Matthew Henry TEI metadata, rights, or source binding drifted"
        )
    expected_notes = [
        ("commentary-id", str(commentary["id"])),
        ("english-name", str(commentary["englishName"])),
        ("website", str(commentary["website"])),
        ("license-url", str(commentary["licenseUrl"])),
        ("language", str(commentary["language"])),
        ("language-name", str(commentary["languageName"])),
        ("language-english-name", str(commentary["languageEnglishName"])),
        ("text-direction", str(commentary["textDirection"])),
        ("source-reported-sha256", str(commentary["sha256"])),
        ("book-count", str(commentary["numberOfBooks"])),
        ("chapter-count", str(commentary["totalNumberOfChapters"])),
        ("commentary-occurrence-count", str(commentary["totalNumberOfVerses"])),
        ("profile-count", str(commentary["totalNumberOfProfiles"])),
    ]
    observed_notes = [
        (str(item.get("type")), item.text or "")
        for item in root.xpath(
            "tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note", namespaces=ns
        )
    ]
    if observed_notes != expected_notes:
        raise ValueError("Matthew Henry retained header metadata drifted")
    text = root_children[1]
    _assert_element(text, "text", {"xml:lang": "eng"}, None, "text root")
    text_children = _element_children(text)
    if len(text_children) != 1 or etree.QName(text_children[0]).localname != "body":
        raise ValueError("Matthew Henry TEI body structure drifted")
    body = text_children[0]
    try:
        _assert_exact_tree(body, _expected_body(books_record, chapters), "body")
    except ValueError as exc:
        raise ValueError("Matthew Henry TEI body tree drifted") from exc
    book_nodes = _element_children(body)
    if len(book_nodes) != 65:
        raise ValueError("Matthew Henry TEI falsely changed the 65-book scope")
    chapters_by_book: dict[str, list[dict[str, object]]] = {}
    for item in chapters:
        raw_book = item["book"]
        assert isinstance(raw_book, dict)
        chapters_by_book.setdefault(str(raw_book["id"]), []).append(item)
    occurrence_count = 0
    present_intro_count = 0
    for raw_book, book_node in zip(books, book_nodes, strict=True):
        assert isinstance(raw_book, dict)
        book_id = str(raw_book["id"])
        _assert_element(
            book_node,
            "div",
            {
                "type": "book",
                "n": book_id,
                "xml:id": f"book-{book_id}",
                "corresp": f"{_SOURCE_PREFIX}books.json",
            },
            None,
            f"book {book_id}",
        )
        children = _element_children(book_node)
        expected_chapters = chapters_by_book[book_id]
        if len(children) != 3 + len(expected_chapters):
            raise ValueError(
                f"Matthew Henry TEI book child census drifted for {book_id}"
            )
        _assert_element(
            children[0], "head", {}, str(raw_book["name"]), f"book {book_id} name"
        )
        _assert_element(
            children[1],
            "note",
            {"type": "common-name"},
            str(raw_book["commonName"]),
            f"book {book_id} common name",
        )
        _assert_element(
            children[2],
            "div",
            {"type": "book-introduction", "xml:id": f"book-intro-{book_id}"},
            None,
            f"book {book_id} introduction",
        )
        intro_children = _element_children(children[2])
        if len(intro_children) != 1:
            raise ValueError(
                f"Matthew Henry TEI book introduction wrapper drifted for {book_id}"
            )
        _assert_element(
            intro_children[0],
            "p",
            {},
            str(raw_book["introduction"]),
            f"book {book_id} introduction text",
        )
        for chapter_item, chapter_node in zip(
            expected_chapters, children[3:], strict=True
        ):
            chapter = chapter_item["chapter"]
            relative = chapter_item["relative_path"]
            assert isinstance(chapter, dict) and isinstance(relative, str)
            number = int(chapter["number"])
            _assert_element(
                chapter_node,
                "div",
                {
                    "type": "chapter",
                    "n": str(number),
                    "xml:id": f"chapter-{book_id}-{number:03d}",
                    "corresp": f"{_SOURCE_PREFIX}{relative}",
                },
                None,
                f"chapter {relative}",
            )
            chapter_children = _element_children(chapter_node)
            offset = 0
            if "introduction" in chapter:
                present_intro_count += 1
                if not chapter_children:
                    raise ValueError(
                        f"Matthew Henry TEI omitted chapter introduction at {relative}"
                    )
                intro = chapter_children[0]
                _assert_element(
                    intro,
                    "div",
                    {
                        "type": "chapter-introduction",
                        "xml:id": f"chapter-intro-{book_id}-{number:03d}",
                    },
                    None,
                    f"chapter introduction {relative}",
                )
                intro_paragraphs = _element_children(intro)
                if len(intro_paragraphs) != 1:
                    raise ValueError(
                        f"Matthew Henry chapter introduction wrapper drifted at {relative}"
                    )
                _assert_element(
                    intro_paragraphs[0],
                    "p",
                    {},
                    str(chapter["introduction"]),
                    f"chapter introduction text {relative}",
                )
                offset = 1
            content = chapter["content"]
            assert isinstance(content, list)
            occurrences = chapter_children[offset:]
            if len(occurrences) != len(content):
                raise ValueError(
                    f"Matthew Henry occurrence omission or invention at {relative}"
                )
            for ordinal, (raw_occurrence, observed) in enumerate(
                zip(content, occurrences, strict=True), start=1
            ):
                assert isinstance(raw_occurrence, dict)
                _assert_element(
                    observed,
                    "div",
                    {
                        "type": "commentary-occurrence",
                        "subtype": "verse",
                        "n": str(raw_occurrence["number"]),
                        "xml:id": f"commentary-{book_id}-{number:03d}-{ordinal:04d}",
                    },
                    None,
                    f"commentary occurrence {relative}#{ordinal}",
                )
                paragraphs = _element_children(observed)
                if len(paragraphs) != 1:
                    raise ValueError(
                        f"Matthew Henry occurrence structure drifted at {relative}#{ordinal}"
                    )
                _assert_element(
                    paragraphs[0],
                    "p",
                    {},
                    str(raw_occurrence["content"][0]),
                    f"commentary text {relative}#{ordinal}",
                )
                occurrence_count += 1
    if occurrence_count != 4_124 or present_intro_count != 1_156:
        raise ValueError("Matthew Henry TEI final content census drifted")
    if tei_bytes != _expected_tei_bytes(books_record, chapters, source_digest):
        raise ValueError("Matthew Henry TEI exact document bytes drifted")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("Matthew Henry candidate fails TEI P5 validation") from exc


def _expected_provenance(
    commentary: dict[str, object],
    config: dict[str, object],
    profile: dict[str, object],
) -> dict[str, object]:
    return {
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


def _expected_unresolved(
    commentary: dict[str, object],
    config: dict[str, object],
) -> list[dict[str, object]]:
    if (
        commentary.get("licenseUrl")
        != "https://creativecommons.org/publicdomain/mark/1.0/"
        or commentary.get("textDirection") != "rtl"
        or config.get("license") != "cc0-1.0"
    ):
        raise ValueError("Matthew Henry unresolved authority inputs drifted")
    return [
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


def _expected_readme(
    commentary: dict[str, object],
    profiles_record: dict[str, object],
    config: dict[str, object],
    profile: dict[str, object],
    policy: dict[str, object],
) -> bytes:
    scope = profile.get("scope")
    identity = profile.get("identity_and_rights_policy")
    candidate_model = profile.get("candidate_model")
    counts = policy.get("required_counts")
    unresolved = _expected_unresolved(commentary, config)
    if (
        not isinstance(scope, dict)
        or not isinstance(identity, dict)
        or not isinstance(candidate_model, dict)
        or not isinstance(counts, dict)
        or profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
        or scope.get("metadata_members") != ["books.json", "profiles.json"]
        or scope.get("missing_canonical_books") != ["SNG"]
        or scope.get("partial_canonical_books")
        != {"MAT": [*range(19, 29)], "JON": [2, 3, 4]}
        or scope.get("retained_path_gaps") != {"ISA": [67]}
        or scope.get("introduction_only_chapters")
        != [
            "ISA/68.json",
            "JOS/22.json",
            "JOS/23.json",
            "NUM/31.json",
            "NUM/32.json",
            "NUM/33.json",
            "NUM/34.json",
            "NUM/35.json",
            "PSA/72.json",
        ]
        or scope.get("duplicate_verse_occurrences") != {"EZK/40.json": [1]}
        or scope.get("nonmonotonic_chapters") != ["EZK/40.json"]
        or counts.get("source_members") != scope.get("member_count")
        or counts.get("source_bytes") != scope.get("total_bytes")
        or counts.get("books") != scope.get("book_count")
        or counts.get("chapters") != scope.get("chapter_count")
        or counts.get("commentary_occurrences")
        != scope.get("commentary_occurrence_count")
        or counts.get("book_introductions") != scope.get("book_introduction_count")
        or counts.get("chapter_introductions_present")
        != scope.get("chapter_introduction_present_count")
        or counts.get("chapter_introductions_absent")
        != scope.get("chapter_introduction_absent_count")
        or [item["id"] for item in unresolved] != policy.get("required_unresolved_ids")
        or identity.get("retained_title") != commentary.get("name")
        or identity.get("retained_license_url") != commentary.get("licenseUrl")
        or identity.get("config_license_drift") != config.get("license")
        or identity.get("retained_text_direction") != commentary.get("textDirection")
        or candidate_model.get("status") != policy.get("candidate_status")
        or config.get("helloao_license")
        != "PDM 1.0 (https://creativecommons.org/publicdomain/mark/1.0/)"
    ):
        raise ValueError("Matthew Henry README authority inputs drifted")
    member_count = int(counts["source_members"])
    chapter_count = int(counts["chapters"])
    book_count = int(counts["books"])
    occurrence_count = int(counts["commentary_occurrences"])
    return (
        "# Matthew Henry retained HelloAO witness\n\n"
        f"This nonaccepted candidate faithfully represents all {member_count:,} retained JSON members under "
        f"`{profile['source_root']}`: `books.json`, `profiles.json`, and {chapter_count:,} chapter files in {book_count} book directories.\n\n"
        f"The retained witness contains {occurrence_count:,} ordered commentary occurrences. Occurrences are not sorted or merged; both distinct verse-1 occurrences in Ezekiel 40 remain present. Song of Solomon is absent; Matthew ends at chapter 18; Jonah ends at chapter 1; `ISA/67.json` is absent while `ISA/68.json` is retained; and nine retained chapters contain introductions but no commentary occurrences. These gaps and empty targets remain explicit. No chapter, range, or Bible text is inferred.\n\n"
        "HelloAO metadata links the Public Domain Mark 1.0. The existing source config says CC0; this candidate records that drift and does not replace the retained PDM statement. PDM contains no attribution request, but HelloAO is identified as the retained API provider.\n\n"
        "Edition and exact authorship or posthumous-contributor identity, the rights-description drift, retained `textDirection: rtl` anomaly, and retained coverage gaps remain localized questions. "
        f"Accepted IR is `{candidate_model['accepted_ir']}`; human review is `{candidate_model['human_review']}`; publication is `{candidate_model['publication']}`.\n"
    ).encode("utf-8")


def _verify_provenance(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    profile: dict[str, object],
    policy: dict[str, object],
) -> None:
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    config = _json(
        source_manifest.authority_path("source-config").read_bytes(), "source config"
    )
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance.json")
    if provenance != _expected_provenance(commentary, config, profile):
        raise ValueError(
            "Matthew Henry metadata, rights, scope, or witness identity drifted"
        )
    unresolved = [
        _json(line + b"\n", f"unresolved line {number}")
        for number, line in enumerate(
            candidate.member_bytes("unresolved.jsonl").splitlines(), start=1
        )
    ]
    if unresolved != _expected_unresolved(commentary, config):
        raise ValueError("Matthew Henry unresolved evidence drift")
    if candidate.member_bytes("README.source.md") != _expected_readme(
        commentary, profiles_record, config, profile, policy
    ):
        raise ValueError("Matthew Henry source README drift")


def _module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _resolve_first_party_module(root: Path, name: str) -> Path | None:
    relative = Path(*name.split("."))
    module = root / relative.with_suffix(".py")
    package = root / relative / "__init__.py"
    if module.is_file():
        return module.resolve(strict=True)
    if package.is_file():
        return package.resolve(strict=True)
    return None


def _package_initializers(root: Path, name: str) -> set[Path]:
    parts = name.split(".")
    result: set[Path] = set()
    for length in range(1, len(parts)):
        candidate = root / Path(*parts[:length]) / "__init__.py"
        if candidate.is_file():
            result.add(candidate.resolve(strict=True))
    return result


def _absolute_import_name(path: Path, root: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    current = _module_name(root, path)
    package = (
        current.split(".") if path.name == "__init__.py" else current.split(".")[:-1]
    )
    trim = node.level - 1
    if trim > len(package):
        raise ValueError("Matthew Henry oracle closure has invalid relative import")
    base = package[: len(package) - trim] if trim else package
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _closure_records(root: Path, policy: dict[str, object]) -> list[dict[str, str]]:
    raw_forbidden = policy.get("forbidden_import_prefixes", [])
    if not isinstance(raw_forbidden, list) or any(
        not isinstance(item, str) for item in raw_forbidden
    ):
        raise ValueError("Matthew Henry oracle forbidden import policy is invalid")
    forbidden = tuple(raw_forbidden)
    entry_name = "build.tei.helloao_matthew_henry_oracle"
    entry = _resolve_first_party_module(root, entry_name)
    if entry is None:
        raise ValueError(
            "Matthew Henry oracle implementation is absent from repository root"
        )
    paths = _package_initializers(root, entry_name) | {entry}
    pending = list(paths)
    inspected: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in inspected:
            continue
        inspected.add(path)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = _absolute_import_name(path, root, node)
                if base:
                    imports.append(base)
                    imports.extend(
                        f"{base}.{alias.name}"
                        for alias in node.names
                        if alias.name != "*"
                    )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError(
                    "Matthew Henry oracle closure contains dynamic execution"
                )
        for name in imports:
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in forbidden
            ):
                raise ValueError(
                    f"Matthew Henry oracle closure contains forbidden import {name}"
                )
            imported = _resolve_first_party_module(root, name)
            if imported is None:
                continue
            discovered = _package_initializers(root, name) | {imported}
            for discovered_path in discovered - paths:
                paths.add(discovered_path)
                pending.append(discovered_path)
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha(path.read_bytes()),
        }
        for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    ]


def _closure_digest(root: Path, policy: dict[str, object]) -> str:
    return _sha(_canonical(_closure_records(root, policy)))


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    expected_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    if (
        candidate.manifest.get("source_manifest") != expected_manifest
        or candidate.manifest.get("converter") != source_manifest.record["converter"]
        or candidate.manifest.get("package_schema")
        != source_manifest.record["package_schema"]
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("Matthew Henry candidate weakened a source authority binding")
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_retained(source_manifest, records)
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _json(profile_bytes, "Matthew Henry reconstruction profile")
    policy = _json(policy_bytes, "Matthew Henry validation policy")
    if (
        profile.get("contract") != "ocd-helloao-matthew-henry-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or policy.get("contract") != "ocd-helloao-matthew-henry-validation-policy-v1"
        or policy.get("required_counts")
        != {
            "source_members": 1_169,
            "source_bytes": 41_160_630,
            "books": 65,
            "chapters": 1_167,
            "commentary_occurrences": 4_124,
            "book_introductions": 65,
            "chapter_introductions_present": 1_156,
            "chapter_introductions_absent": 11,
            "introduction_only_chapters": 9,
        }
    ):
        raise ValueError("Matthew Henry bound profile or validation policy drifted")
    accountability = _json(
        candidate.member_bytes("source-accountability.json"),
        "source-accountability.json",
    )
    _verify_accountability(
        source_manifest,
        records,
        books_record,
        profiles_record,
        chapters,
        accountability,
    )
    source_digest = _source_digest(records)
    tei_bytes = candidate.member_bytes("content.tei.xml")
    _verify_tei(tei_bytes, books_record, chapters, source_digest)
    _verify_provenance(
        source_manifest,
        candidate,
        books_record,
        profiles_record,
        profile,
        policy,
    )
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).resolve().read_bytes()),
        validator_import_closure_sha256=_closure_digest(root, policy),
        source_sha256=source_digest,
        profile_sha256=_sha(profile_bytes),
        package_schema_sha256=_sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        xsd_sha256=_sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        policy_sha256=_sha(policy_bytes),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
