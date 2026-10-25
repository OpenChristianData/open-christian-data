"""Producer-independent oracle for the complete retained Adam Clarke JSON witness."""

from __future__ import annotations

import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import sys
from typing import Mapping
from xml.parsers import expat

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-helloao-adam-clarke-source-to-tei-oracle"
ORACLE_VERSION = "2"
_PROFILE_ID = "helloao-adam-clarke-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/adam-clarke/"
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
        raise ValueError(f"Adam Clarke source field key order drifted at {label}")


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


def _canonical_editorial_correction_boundary(
    source_manifest: SourceManifest,
    chapters: list[dict[str, object]],
) -> dict[str, object]:
    ledger_bytes = source_manifest.authority_path(
        "canonical-editorial-correction-ledger"
    ).read_bytes()
    rows = ledger_bytes.splitlines()
    if len(rows) != 1:
        raise ValueError("Adam Clarke correction ledger row count drifted")
    ledger = _json(rows[0], "canonical editorial correction ledger")
    receipt_bytes = source_manifest.authority_path(
        "canonical-editorial-correction-writer-receipt"
    ).read_bytes()
    receipt = _json(receipt_bytes, "canonical editorial correction writer receipt")
    semantic_ledger = {
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
    if any(ledger.get(key) != value for key, value in semantic_ledger.items()):
        raise ValueError("Adam Clarke correction ledger meaning drifted")
    semantic_receipt = {
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
    if any(receipt.get(key) != value for key, value in semantic_receipt.items()):
        raise ValueError("Adam Clarke correction receipt meaning drifted")
    anchor = [item for item in chapters if item["relative_path"] == "2JN/1.json"]
    if len(anchor) != 1:
        raise ValueError("Adam Clarke retained correction anchor path drifted")
    occurrences = anchor[0]["chapter"]["content"]
    if not isinstance(occurrences, list) or len(occurrences) < 9:
        raise ValueError("Adam Clarke retained correction anchor shape drifted")
    occurrence = occurrences[8]
    content = occurrence.get("content") if isinstance(occurrence, dict) else None
    if (
        not isinstance(occurrence, dict)
        or occurrence.get("type") != "verse"
        or occurrence.get("number") != 9
        or not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], str)
        or content[0].count("hath not God") != 1
        or "has not God" in content[0]
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


def _primary_members(source_manifest: SourceManifest) -> tuple[dict[str, object], ...]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Adam Clarke source authorities are invalid")
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
                "Adam Clarke primary-source path escaped the retained root"
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
        len(records) != 856
        or len(set(relative)) != 856
        or sum(int(item["bytes"]) for item in records) != 28_421_263
        or set(relative) & {"books.json", "profiles.json"}
        != {"books.json", "profiles.json"}
        or len(
            [path for path in relative if path not in {"books.json", "profiles.json"}]
        )
        != 854
    ):
        raise ValueError("Adam Clarke exact retained member census failed")
    retained_root = resolve_repo_path(
        source_manifest.repository_root, _SOURCE_PREFIX.removesuffix("/")
    ).resolve(strict=True)
    actual = {
        path.relative_to(retained_root).as_posix()
        for path in retained_root.rglob("*")
        if path.is_file()
    }
    if actual != set(relative):
        raise ValueError(
            "Adam Clarke retained root contains an unbound or missing member"
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
            raise ValueError(f"Adam Clarke manifest lacks {relative}")
        content = source_manifest.authority_path(str(item["name"])).read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(f"Adam Clarke retained bytes drifted at {relative}")
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
        or len(books) != 57
    ):
        raise ValueError("Adam Clarke retained books metadata is invalid")
    _require_key_order(commentary, _COMMENTARY_KEYS, "books.json commentary")
    profiles_commentary = profiles_record.get("commentary")
    if not isinstance(profiles_commentary, dict):
        raise ValueError("Adam Clarke profiles commentary is invalid")
    _require_key_order(
        profiles_commentary, _COMMENTARY_KEYS, "profiles.json commentary"
    )
    if commentary != {
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
        "totalNumberOfVerses": 13_318,
        "totalNumberOfProfiles": 0,
        "languageName": "English",
        "languageEnglishName": "English",
    }:
        raise ValueError("Adam Clarke retained commentary source fields drifted")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError("Adam Clarke retained profiles metadata is invalid")
    chapters: list[dict[str, object]] = []
    covered = {"books.json", "profiles.json"}
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict):
            raise ValueError("Adam Clarke retained book is not an object")
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
            or raw_book.get("lastChapterNumber") != count
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                "Adam Clarke retained book order or structure drifted "
                f"at ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        for number in range(1, count + 1):
            relative = f"{book_id}/{number}.json"
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
                    f"Adam Clarke chapter introduction drifted at {relative}"
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
                    raise ValueError(f"Adam Clarke occurrence drifted at {relative}")
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "chapter": chapter,
                    "envelope": envelope,
                }
            )
    if covered != set(by_relative) or len(chapters) != 854:
        raise ValueError("Adam Clarke member inclusion/exclusion accounting failed")
    expected_links = [
        f"/api/c/adam-clarke/{item['book']['id']}/{item['chapter']['number']}.json"
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
    alternate_bytes = source_manifest.authority_path(
        "alternate-witness-evidence"
    ).read_bytes()
    alternate = _json(alternate_bytes, "alternate witness evidence")
    correction_boundary = _canonical_editorial_correction_boundary(
        source_manifest, chapters
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
        "contract": "ocd-helloao-adam-clarke-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "source_root": _SOURCE_PREFIX.removesuffix("/"),
        "source_member_set_sha256": _source_digest(records),
        "member_count": 856,
        "total_bytes": 28_421_263,
        "included_member_count": 856,
        "excluded_member_count": 0,
        "members": expected_members,
        "census": {
            "books": 57,
            "chapters": 854,
            "commentary_occurrences": sum(
                len(item["chapter"]["content"]) for item in chapters
            ),
            "book_introductions": 57,
            "chapter_introductions_present": present,
            "chapter_introductions_absent": 854 - present,
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
        "alternate_witness": {
            "authority_sha256": _sha(alternate_bytes),
            "witness_id": alternate["witnesses"][0]["witness_id"],
            "disposition": "separate identity evidence; not merged",
        },
        "canonical_editorial_correction_boundary": correction_boundary,
    }
    if accountability != expected:
        raise ValueError(
            "Adam Clarke source accountability omission, exclusion, or drift"
        )


def _element_children(node: etree._Element) -> list[etree._Element]:
    children = list(node)
    if any(not isinstance(child.tag, str) for child in children):
        raise ValueError(
            "Adam Clarke TEI contains an unaccounted comment or instruction"
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
        raise ValueError(f"Adam Clarke TEI {label} drifted")


def _assert_leaf(
    node: etree._Element,
    name: str,
    attributes: Mapping[str, str],
    text: str | None,
    label: str,
) -> None:
    _assert_element(node, name, attributes, text, label)
    if len(node) != 0:
        raise ValueError(f"Adam Clarke TEI {label} contains unaccounted descendants")


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
    title_stmt.append(_expected_element("author", text="Adam Clarke"))
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
        raise ValueError(f"Adam Clarke TEI {label} tree drifted")
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
                "Adam Clarke TEI namespace declarations drifted at "
                f"element {element_ordinal}"
            )

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(tei_bytes, True)
    except expat.ExpatError as exc:
        raise ValueError("Adam Clarke candidate is not safe well-formed XML") from exc


def _parse_candidate_tei(tei_bytes: bytes) -> etree._ElementTree:
    if not tei_bytes.startswith(_EXPECTED_TEI_PROLOG):
        raise ValueError("Adam Clarke TEI document prolog drift")
    if tei_bytes[len(_EXPECTED_TEI_PROLOG) : len(_EXPECTED_TEI_PROLOG) + 1] != b"<":
        raise ValueError("Adam Clarke TEI document prolog drift")
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
        raise ValueError("Adam Clarke candidate is not safe well-formed XML") from exc
    if tree.docinfo.doctype:
        raise ValueError("Adam Clarke TEI document prolog drift")
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
        raise ValueError("Adam Clarke TEI contains an unaccounted document-level node")
    _verify_namespace_declarations(tei_bytes)
    ns = {"tei": _TEI_NS, "xml": _XML_NS}
    if (
        etree.QName(root).localname != "TEI"
        or etree.QName(root).namespace != _TEI_NS
        or root.attrib
        or root.text is not None
        or root.tail is not None
    ):
        raise ValueError("Adam Clarke TEI root drifted")
    root_children = _element_children(root)
    if [etree.QName(item).localname for item in root_children] != ["teiHeader", "text"]:
        raise ValueError("Adam Clarke TEI root member order drifted")
    commentary = books_record["commentary"]
    books = books_record["books"]
    assert isinstance(commentary, dict) and isinstance(books, list)
    try:
        _assert_exact_tree(
            root_children[0], _expected_header(commentary, source_digest), "header"
        )
    except ValueError as exc:
        raise ValueError("Adam Clarke TEI header tree drifted") from exc
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
        "author": "Adam Clarke",
        "publisher": "Open Christian Data",
        "availability": "restricted",
        "rights": "Retained HelloAO metadata applies the Public Domain Mark 1.0; the source config's CC0 label is recorded as drift and is not substituted.",
        "source": commentary["listOfBooksApiLink"],
        "digest": source_digest,
        "witness": "retained HelloAO JSON snapshot",
    }
    if observed_header != expected_header:
        raise ValueError("Adam Clarke TEI metadata, rights, or source binding drifted")
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
        raise ValueError("Adam Clarke retained header metadata drifted")
    text = root_children[1]
    _assert_element(text, "text", {"xml:lang": "eng"}, None, "text root")
    text_children = _element_children(text)
    if len(text_children) != 1 or etree.QName(text_children[0]).localname != "body":
        raise ValueError("Adam Clarke TEI body structure drifted")
    body = text_children[0]
    try:
        _assert_exact_tree(body, _expected_body(books_record, chapters), "body")
    except ValueError as exc:
        raise ValueError("Adam Clarke TEI body tree drifted") from exc
    book_nodes = _element_children(body)
    if len(book_nodes) != 57:
        raise ValueError("Adam Clarke TEI falsely changed the 57-book scope")
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
            raise ValueError(f"Adam Clarke TEI book child census drifted for {book_id}")
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
                f"Adam Clarke TEI book introduction wrapper drifted for {book_id}"
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
                        f"Adam Clarke TEI omitted chapter introduction at {relative}"
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
                        f"Adam Clarke chapter introduction wrapper drifted at {relative}"
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
                    f"Adam Clarke occurrence omission or invention at {relative}"
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
                        f"Adam Clarke occurrence structure drifted at {relative}#{ordinal}"
                    )
                _assert_element(
                    paragraphs[0],
                    "p",
                    {},
                    str(raw_occurrence["content"][0]),
                    f"commentary text {relative}#{ordinal}",
                )
                occurrence_count += 1
    if occurrence_count != 13_318 or present_intro_count != 831:
        raise ValueError("Adam Clarke TEI final content census drifted")
    if tei_bytes != _expected_tei_bytes(books_record, chapters, source_digest):
        raise ValueError("Adam Clarke TEI exact document bytes drifted")
    try:
        compiled_schema().assertValid(tree)
    except etree.DocumentInvalid as exc:
        raise ValueError("Adam Clarke candidate fails TEI P5 validation") from exc


def _expected_provenance(
    commentary: dict[str, object],
    config: dict[str, object],
    profile: dict[str, object],
    witness: dict[str, object],
    correction_boundary: dict[str, object],
) -> dict[str, object]:
    return {
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
            "witness_id": witness["witness_id"],
            "edition": witness["edition"],
            "checksum_sha256": witness["checksum_sha256"],
            "merged": False,
        },
        "canonical_editorial_correction_boundary": correction_boundary,
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
        "human_decision": None,
    }


def _expected_unresolved(
    commentary: dict[str, object],
    config: dict[str, object],
    witness: dict[str, object],
) -> list[dict[str, object]]:
    edition = witness.get("edition")
    if (
        commentary.get("licenseUrl")
        != "https://creativecommons.org/publicdomain/mark/1.0/"
        or commentary.get("textDirection") != "rtl"
        or config.get("license") != "cc0-1.0"
        or not isinstance(edition, dict)
        or edition.get("year") != 1836
        or edition.get("publisher") != "London : T. Tegg and Son"
        or edition.get("volume") != "II"
    ):
        raise ValueError("Adam Clarke unresolved authority inputs drifted")
    return [
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


def _expected_readme(
    commentary: dict[str, object],
    profiles_record: dict[str, object],
    config: dict[str, object],
    profile: dict[str, object],
    policy: dict[str, object],
    witness: dict[str, object],
    correction_boundary: dict[str, object],
) -> bytes:
    scope = profile.get("scope")
    identity = profile.get("identity_and_rights_policy")
    candidate_model = profile.get("candidate_model")
    counts = policy.get("required_counts")
    unresolved = _expected_unresolved(commentary, config, witness)
    if (
        not isinstance(scope, dict)
        or not isinstance(identity, dict)
        or not isinstance(candidate_model, dict)
        or not isinstance(counts, dict)
        or profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
        or scope.get("metadata_members") != ["books.json", "profiles.json"]
        or scope.get("missing_canonical_books")
        != ["DEU", "JDG", "PSA", "PRO", "ECC", "JER", "JOL", "MAL", "MAT"]
        or scope.get("duplicate_verse_occurrences") != {"2SA/14.json": [27]}
        or len(scope.get("nonmonotonic_chapters", [])) != 8
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
        or profile.get("canonical_editorial_correction_boundary")
        != {
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
        }
        or "retained-hath-and-separate-governed-canonical-has-correction"
        not in policy.get("checks", [])
    ):
        raise ValueError("Adam Clarke README authority inputs drifted")
    member_count = int(counts["source_members"])
    chapter_count = int(counts["chapters"])
    book_count = int(counts["books"])
    occurrence_count = int(counts["commentary_occurrences"])
    return (
        "# Adam Clarke retained HelloAO witness\n\n"
        f"This nonaccepted candidate faithfully represents all {member_count} retained JSON members under "
        f"`{profile['source_root']}`: `books.json`, `profiles.json`, and {chapter_count} chapter files in {book_count} book directories.\n\n"
        f"The retained witness contains {book_count} books, not all 66 books of the Protestant canon. It contains {occurrence_count:,} ordered commentary occurrences. Occurrences are not sorted or merged; both distinct verse-27 occurrences in 2 Samuel 14 remain present. No Bible or BSB verse text is added.\n\n"
        "HelloAO metadata links the Public Domain Mark 1.0. The existing source config says CC0; this candidate records that drift and does not replace the retained PDM statement. PDM contains no attribution request, but HelloAO is identified as the retained API provider.\n\n"
        "The separate 1836 Tegg volume-II scan is identity evidence only and is not merged with this JSON witness. Edition identity, the rights-description drift, and retained `textDirection: rtl` anomaly remain localized questions. "
        f"Accepted IR is `{candidate_model['accepted_ir']}`; publication is `{candidate_model['publication']}`.\n"
        "\nThe retained 2 John 1:9 source and TEI preserve `hath not God`. Canonical display text uses `has not God` only through the separately bound applied correction ledger and historical applier receipt; that editorial display correction is not source evidence and is not applied to this retained-source TEI.\n"
    ).encode("utf-8")


def _verify_provenance(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    profile: dict[str, object],
    policy: dict[str, object],
    chapters: list[dict[str, object]],
) -> None:
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    config = _json(
        source_manifest.authority_path("source-config").read_bytes(), "source config"
    )
    alternate = _json(
        source_manifest.authority_path("alternate-witness-evidence").read_bytes(),
        "alternate witness evidence",
    )
    witnesses = alternate.get("witnesses")
    if (
        not isinstance(witnesses, list)
        or len(witnesses) != 1
        or not isinstance(witnesses[0], dict)
    ):
        raise ValueError("Adam Clarke alternate witness authority drifted")
    witness = witnesses[0]
    correction_boundary = _canonical_editorial_correction_boundary(
        source_manifest, chapters
    )
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance.json")
    if provenance != _expected_provenance(
        commentary, config, profile, witness, correction_boundary
    ):
        raise ValueError(
            "Adam Clarke metadata, rights, scope, or witness identity drifted"
        )
    unresolved = [
        _json(line + b"\n", f"unresolved line {number}")
        for number, line in enumerate(
            candidate.member_bytes("unresolved.jsonl").splitlines(), start=1
        )
    ]
    if unresolved != _expected_unresolved(commentary, config, witness):
        raise ValueError("Adam Clarke unresolved evidence drift")
    if candidate.member_bytes("README.source.md") != _expected_readme(
        commentary,
        profiles_record,
        config,
        profile,
        policy,
        witness,
        correction_boundary,
    ):
        raise ValueError("Adam Clarke source README drift")


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
        raise ValueError("Adam Clarke oracle closure has invalid relative import")
    base = package[: len(package) - trim] if trim else package
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _closure_records(root: Path, policy: dict[str, object]) -> list[dict[str, str]]:
    raw_forbidden = policy.get("forbidden_import_prefixes", [])
    if not isinstance(raw_forbidden, list) or any(
        not isinstance(item, str) for item in raw_forbidden
    ):
        raise ValueError("Adam Clarke oracle forbidden import policy is invalid")
    forbidden = tuple(raw_forbidden)
    entry_name = "build.tei.helloao_adam_clarke_oracle"
    entry = _resolve_first_party_module(root, entry_name)
    if entry is None:
        raise ValueError(
            "Adam Clarke oracle implementation is absent from repository root"
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
                    "Adam Clarke oracle closure contains dynamic execution"
                )
        for name in imports:
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in forbidden
            ):
                raise ValueError(
                    f"Adam Clarke oracle closure contains forbidden import {name}"
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
        raise ValueError("Adam Clarke candidate weakened a source authority binding")
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_retained(source_manifest, records)
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _json(profile_bytes, "Adam Clarke reconstruction profile")
    policy = _json(policy_bytes, "Adam Clarke validation policy")
    if (
        profile.get("contract") != "ocd-helloao-adam-clarke-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or policy.get("contract") != "ocd-helloao-adam-clarke-validation-policy-v1"
        or policy.get("required_counts")
        != {
            "source_members": 856,
            "source_bytes": 28_421_263,
            "books": 57,
            "chapters": 854,
            "commentary_occurrences": 13_318,
            "book_introductions": 57,
            "chapter_introductions_present": 831,
            "chapter_introductions_absent": 23,
        }
    ):
        raise ValueError("Adam Clarke bound profile or validation policy drifted")
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
        chapters,
    )
    implementation = Path(__file__).resolve()
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": (
            f"{platform.python_implementation()} {platform.python_version()} "
            f"({Path(sys.executable).resolve(strict=True)})"
        ),
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(
            source_manifest.authority_path("candidate-package-schema").read_bytes()
        ),
        "source_sha256": source_digest,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
