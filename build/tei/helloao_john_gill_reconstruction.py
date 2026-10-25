"""Faithful reconstruction of the complete retained HelloAO John Gill witness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from lxml import etree

from ocd_kernel.lib.storage_topology import resolve_repo_path
from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-helloao-john-gill-json-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "helloao-john-gill-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/john-gill/"
_STRUCTURE_INVENTORY_AUTHORITY = "structure-inventory"
_STRUCTURE_INVENTORY_CONTRACT = "ocd-source-structure-inventory-v1"
_STRUCTURE_POLICY_CHECK = (
    "exact-source-double-newline-paragraph-segmentation-without-inferred-heading-semantics"
)
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_COMMENTARY_KEYS = {
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
}
_BOOK_KEYS = {
    "id",
    "commentaryId",
    "name",
    "commonName",
    "introduction",
    "firstChapterApiLink",
    "firstChapterNumber",
    "lastChapterApiLink",
    "lastChapterNumber",
    "numberOfChapters",
    "order",
    "sha256",
    "totalNumberOfVerses",
}
_ENVELOPE_KEYS = {
    "book",
    "chapter",
    "commentary",
    "nextChapterApiLink",
    "numberOfVerses",
    "previousChapterApiLink",
    "thisChapterLink",
}
_CHAPTER_KEYS_WITH_INTRODUCTION = {"content", "introduction", "number"}
_CHAPTER_KEYS_WITHOUT_INTRODUCTION = {"content", "number"}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, Any]:
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
        elif key == "xml:space":
            normalized[_XML_SPACE] = value
        else:
            normalized[key] = value
    element = etree.Element(
        f"{{{_TEI_NS}}}{name}",
        normalized,
        nsmap={None: _TEI_NS} if name == "TEI" else None,
    )
    element.text = text
    return element


def _primary_members(source_manifest: SourceManifest) -> tuple[dict[str, object], ...]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("John Gill source authorities are invalid")
    members: list[dict[str, object]] = []
    for authority in authorities:
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
            raise ValueError("John Gill primary-source authority is malformed")
        members.append(
            {
                "name": name,
                "path": path,
                "bytes": size,
                "sha256": digest,
                "relative_path": path.removeprefix(_SOURCE_PREFIX),
            }
        )
    members.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    if (
        len(members) != 1191
        or sum(int(item["bytes"]) for item in members) != 54_866_016
    ):
        raise ValueError(
            "John Gill retained member census differs from 1191/54,866,016"
        )
    relative_paths = [str(item["relative_path"]) for item in members]
    if len(set(relative_paths)) != 1191:
        raise ValueError("John Gill retained member paths are not unique")
    if set(relative_paths) != {"books.json", "profiles.json"} | {
        f"{book}/{chapter}.json"
        for book in {path.split("/", 1)[0] for path in relative_paths if "/" in path}
        for chapter in range(
            1,
            max(
                int(path.rsplit("/", 1)[1].removesuffix(".json"))
                for path in relative_paths
                if path.startswith(f"{book}/")
            )
            + 1,
        )
    }:
        raise ValueError("John Gill retained member paths are incomplete")
    raw_root = resolve_repo_path(
        source_manifest.repository_root, _SOURCE_PREFIX.removesuffix("/")
    ).resolve(strict=True)
    actual_paths = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*")
        if path.is_file()
    }
    if actual_paths != set(relative_paths):
        raise ValueError("John Gill retained root has an unbound or missing member")
    for member in members:
        path = source_manifest.authority_path(str(member["name"]))
        content = path.read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError(
                f"John Gill retained member bytes drifted: {member['path']}"
            )
    return tuple(members)


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


def _authority_json(source_manifest: SourceManifest, name: str) -> dict[str, Any]:
    return _strict_json(source_manifest.authority_path(name).read_bytes(), name)


def _load_structure_inventory(
    source_manifest: SourceManifest,
    books_record: dict[str, Any],
    chapters: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str], dict[str, object]], set[tuple[str, str]], dict[str, object]]:
    inventory_bytes = source_manifest.authority_path(
        _STRUCTURE_INVENTORY_AUTHORITY
    ).read_bytes()
    inventory = _strict_json(inventory_bytes, _STRUCTURE_INVENTORY_AUTHORITY)
    if (
        inventory.get("contract") != _STRUCTURE_INVENTORY_CONTRACT
        or inventory.get("version") != 1
        or inventory.get("work_id") != "john-gill"
        or inventory.get("source_id")
        != "helloao-john-gill-complete-retained-json"
        or inventory.get("source_root") != _SOURCE_PREFIX.removesuffix("/")
    ):
        raise ValueError("John Gill structure inventory identity drifted")
    scope = inventory.get("scope")
    entries = inventory.get("entries")
    if not isinstance(scope, dict) or not isinstance(entries, list) or entries:
        raise ValueError("John Gill structure inventory shape is invalid")
    paragraph_policy = scope.get("paragraph_policy")
    if (
        not isinstance(paragraph_policy, dict)
        or paragraph_policy.get("contract")
        != "ocd-source-paragraph-segmentation-v1"
        or paragraph_policy.get("delimiter") != "\n\n"
        or paragraph_policy.get("mode") != "split-every-exact-double-newline"
        or paragraph_policy.get("carrier_total_count") != 29_552
        or paragraph_policy.get("carrier_count_with_delimiter") != 29_389
        or paragraph_policy.get("delimiter_count") != 85_387
    ):
        raise ValueError("John Gill source paragraph policy drifted")
    carriers: list[str] = []
    books = books_record.get("books")
    if not isinstance(books, list):
        raise ValueError("John Gill structure census books are invalid")
    for book in books:
        if not isinstance(book, dict) or not isinstance(book.get("introduction"), str):
            raise ValueError("John Gill structure census book introduction is invalid")
        carriers.append(str(book["introduction"]))
    for item in chapters:
        chapter = item.get("chapter")
        if not isinstance(chapter, dict):
            raise ValueError("John Gill structure census chapter is invalid")
        if "introduction" in chapter:
            if not isinstance(chapter["introduction"], str):
                raise ValueError("John Gill structure census chapter introduction is invalid")
            carriers.append(str(chapter["introduction"]))
        content = chapter.get("content")
        if not isinstance(content, list):
            raise ValueError("John Gill structure census content is invalid")
        for occurrence in content:
            if (
                not isinstance(occurrence, dict)
                or not isinstance(occurrence.get("content"), list)
                or len(occurrence["content"]) != 1
                or not isinstance(occurrence["content"][0], str)
            ):
                raise ValueError("John Gill structure census occurrence is invalid")
            carriers.append(str(occurrence["content"][0]))
    delimiter_count = sum(text.count("\n\n") for text in carriers)
    if (
        len(carriers) != paragraph_policy["carrier_total_count"]
        or sum("\n\n" in text for text in carriers)
        != paragraph_policy["carrier_count_with_delimiter"]
        or delimiter_count != paragraph_policy["delimiter_count"]
    ):
        raise ValueError("John Gill source paragraph census drifted")
    if scope.get("carrier_count") != 0 or scope.get("rendered_carrier_count") != 0:
        raise ValueError("John Gill structure heading census drifted")
    return (
        {},
        set(),
        {
            "authority": _STRUCTURE_INVENTORY_AUTHORITY,
            "sha256": _sha(inventory_bytes),
            "carrier_count": 0,
            "rendered_carrier_count": 0,
            "evidence_only_carrier_count": 0,
            "heading_span_count": 0,
            "paragraph_policy": dict(paragraph_policy),
        },
    )


def _append_paragraphs(parent: etree._Element, text: str) -> None:
    parent.text = ""
    segments: list[str] = []
    cursor = 0
    while True:
        separator = text.find("\n\n", cursor)
        if separator < 0:
            tail = text[cursor:]
            if tail or not segments:
                segments.append(tail)
            break
        segment = text[cursor : separator + 2]
        if segment or not segments:
            segments.append(segment)
        cursor = separator + 2
        if cursor == len(text):
            break
    for segment in segments:
        attributes: dict[str, str] = {}
        if segment == "":
            attributes["ana"] = "empty-string"
        elif not segment.strip():
            attributes["xml:space"] = "preserve"
        paragraph = _el("p", attributes or None, segment)
        paragraph.tail = ""
        parent.append(paragraph)


def _validate_profile_policy(profile: dict[str, Any], policy: dict[str, Any]) -> None:
    if (
        profile.get("contract") != "ocd-helloao-john-gill-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or profile.get("work_id") != "john-gill"
        or policy.get("contract") != "ocd-helloao-john-gill-validation-policy-v1"
        or _STRUCTURE_POLICY_CHECK not in policy.get("required_checks", [])
    ):
        raise ValueError("John Gill reconstruction profile or policy mismatch")
    required = {
        "source_members": 1191,
        "source_bytes": 54_866_016,
        "books": 66,
        "chapters": 1189,
        "commentary_occurrences": 28_300,
        "book_introductions": 66,
        "chapter_introductions_present": 1186,
        "chapter_introductions_absent": 3,
    }
    if policy.get("required_counts") != required:
        raise ValueError("John Gill validation policy counts drifted")
    if profile.get("scope", {}).get("member_count") != 1191:
        raise ValueError("John Gill reconstruction profile member count drifted")
    if policy.get("required_unresolved_ids") != [
        "john-gill-retained-vs-configured-title",
        "john-gill-config-cc0-vs-retained-pdm",
        "john-gill-configured-source-endpoint",
        "john-gill-retained-rtl-anomaly",
        "john-gill-edition-and-original-date",
    ]:
        raise ValueError("John Gill validation policy unresolved IDs drifted")


def _load_corpus(
    source_manifest: SourceManifest,
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, Any]:
        item = by_relative.get(relative)
        if item is None:
            raise ValueError(f"John Gill manifest omits {relative}")
        return _strict_json(
            source_manifest.authority_path(str(item["name"])).read_bytes(), relative
        )

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("John Gill books.json shape is invalid")
    if set(commentary) != _COMMENTARY_KEYS or set(profiles_record) != {
        "commentary",
        "profiles",
    }:
        raise ValueError("John Gill collection metadata shape drifted")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError("John Gill profiles metadata disagrees with books metadata")
    expected_commentary = {
        "id": "john-gill",
        "name": "John Gill Bible Commentary",
        "englishName": "John Gill Bible Commentary",
        "language": "eng",
        "textDirection": "rtl",
        "licenseUrl": "https://creativecommons.org/publicdomain/mark/1.0/",
        "numberOfBooks": 66,
        "totalNumberOfChapters": 1189,
        "totalNumberOfVerses": 28_300,
        "totalNumberOfProfiles": 0,
    }
    if any(commentary.get(key) != value for key, value in expected_commentary.items()):
        raise ValueError("John Gill retained commentary identity or census drifted")
    if len(books) != 66:
        raise ValueError("John Gill books.json must contain 66 books")

    chapters: list[dict[str, Any]] = []
    seen_paths = {"books.json", "profiles.json"}
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict) or set(raw_book) != _BOOK_KEYS:
            raise ValueError(
                f"John Gill book metadata is invalid at ordinal {retained_ordinal}"
            )
        book_id = raw_book.get("id")
        chapter_count = raw_book.get("numberOfChapters")
        if (
            not isinstance(book_id, str)
            or raw_book.get("commentaryId") != commentary["id"]
            or not isinstance(raw_book.get("order"), int)
            or int(raw_book["order"]) <= previous_order
            or not isinstance(chapter_count, int)
            or raw_book.get("firstChapterNumber") != 1
            or raw_book.get("lastChapterNumber") != chapter_count
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                f"John Gill book metadata drifted at retained ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        for chapter_number in range(1, chapter_count + 1):
            relative = f"{book_id}/{chapter_number}.json"
            chapter_record = load(relative)
            seen_paths.add(relative)
            if set(chapter_record) != _ENVELOPE_KEYS:
                raise ValueError(
                    f"John Gill chapter envelope shape drifted at {relative}"
                )
            chapter = chapter_record.get("chapter")
            if (
                chapter_record.get("commentary") != commentary
                or chapter_record.get("book") != raw_book
                or not isinstance(chapter, dict)
                or set(chapter)
                not in (
                    _CHAPTER_KEYS_WITH_INTRODUCTION,
                    _CHAPTER_KEYS_WITHOUT_INTRODUCTION,
                )
                or chapter.get("number") != chapter_number
                or not isinstance(chapter.get("content"), list)
                or chapter_record.get("numberOfVerses") != len(chapter["content"])
            ):
                raise ValueError(f"John Gill chapter envelope drifted at {relative}")
            if not isinstance(chapter_record.get("thisChapterLink"), str):
                raise ValueError(f"John Gill chapter link is invalid at {relative}")
            if chapter_record.get(
                "previousChapterApiLink"
            ) is not None and not isinstance(
                chapter_record.get("previousChapterApiLink"), str
            ):
                raise ValueError(
                    f"John Gill previous chapter link is invalid at {relative}"
                )
            if chapter_record.get("nextChapterApiLink") is not None and not isinstance(
                chapter_record.get("nextChapterApiLink"), str
            ):
                raise ValueError(
                    f"John Gill next chapter link is invalid at {relative}"
                )
            for occurrence in chapter["content"]:
                if (
                    not isinstance(occurrence, dict)
                    or set(occurrence) != {"type", "number", "content"}
                    or occurrence.get("type") != "verse"
                    or not isinstance(occurrence.get("number"), int)
                    or not isinstance(occurrence.get("content"), list)
                    or len(occurrence["content"]) != 1
                    or not isinstance(occurrence["content"][0], str)
                ):
                    raise ValueError(
                        f"John Gill commentary occurrence is invalid at {relative}"
                    )
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "chapter": chapter,
                    "envelope": chapter_record,
                }
            )
    if seen_paths != set(by_relative) or len(chapters) != 1189:
        raise ValueError(
            "John Gill retained member coverage is incomplete or contains extras"
        )
    return books_record, profiles_record, chapters


def _content_digests(
    books_record: dict[str, Any],
    profiles_record: dict[str, Any],
    chapters: list[dict[str, Any]],
) -> dict[str, str]:
    books = books_record["books"]
    if not isinstance(books, list):
        raise ValueError("John Gill books metadata is invalid")
    book_order = [item["id"] for item in books]
    book_introductions = [
        [item["id"], _sha(str(item["introduction"]).encode("utf-8"))] for item in books
    ]
    chapter_order: list[list[object]] = []
    chapter_introductions: list[list[object]] = []
    chapter_envelopes: list[list[object]] = []
    occurrences: list[list[object]] = []
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        envelope = item["envelope"]
        if (
            not isinstance(relative, str)
            or not isinstance(chapter, dict)
            or not isinstance(envelope, dict)
        ):
            raise ValueError("John Gill chapter model is invalid")
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
        chapter_envelopes.append(
            [
                relative,
                envelope["previousChapterApiLink"],
                envelope["nextChapterApiLink"],
                envelope["thisChapterLink"],
                envelope["numberOfVerses"],
            ]
        )
        content = chapter["content"]
        if not isinstance(content, list):
            raise ValueError("John Gill chapter content is invalid")
        for ordinal, occurrence in enumerate(content, start=1):
            if not isinstance(occurrence, dict):
                raise ValueError("John Gill occurrence is invalid")
            occurrence_content = occurrence["content"]
            if not isinstance(occurrence_content, list) or len(occurrence_content) != 1:
                raise ValueError("John Gill occurrence content is invalid")
            occurrences.append(
                [
                    relative,
                    ordinal,
                    occurrence["type"],
                    occurrence["number"],
                    _sha(str(occurrence_content[0]).encode("utf-8")),
                ]
            )
    return {
        "commentary_metadata_sha256": _sha(_canonical(books_record["commentary"])),
        "profiles_metadata_sha256": _sha(_canonical(profiles_record)),
        "book_order_sha256": _sha(_canonical(book_order)),
        "book_metadata_sha256": _sha(_canonical(books)),
        "book_introductions_sha256": _sha(_canonical(book_introductions)),
        "chapter_order_sha256": _sha(_canonical(chapter_order)),
        "chapter_envelopes_sha256": _sha(_canonical(chapter_envelopes)),
        "chapter_introductions_sha256": _sha(_canonical(chapter_introductions)),
        "commentary_occurrences_sha256": _sha(_canonical(occurrences)),
    }


def _anomalies(chapters: list[dict[str, Any]]) -> dict[str, object]:
    nonmonotonic: list[str] = []
    duplicate_numbers: list[dict[str, object]] = []
    absent_introductions: list[str] = []
    null_previous: list[str] = []
    null_next: list[str] = []
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        envelope = item["envelope"]
        if (
            not isinstance(relative, str)
            or not isinstance(chapter, dict)
            or not isinstance(envelope, dict)
        ):
            raise ValueError("John Gill anomaly model is invalid")
        if "introduction" not in chapter:
            absent_introductions.append(relative)
        if envelope["previousChapterApiLink"] is None:
            null_previous.append(relative)
        if envelope["nextChapterApiLink"] is None:
            null_next.append(relative)
        content = chapter["content"]
        if not isinstance(content, list):
            raise ValueError("John Gill content is invalid")
        numbers = [entry["number"] for entry in content if isinstance(entry, dict)]
        if numbers != sorted(numbers):
            nonmonotonic.append(relative)
        counts: dict[int, int] = {}
        for number in numbers:
            counts[number] = counts.get(number, 0) + 1
        for number, count in sorted(counts.items()):
            if count > 1:
                duplicate_numbers.append(
                    {"path": relative, "number": number, "count": count}
                )
    return {
        "nonmonotonic_occurrence_paths": nonmonotonic,
        "duplicate_occurrence_numbers": duplicate_numbers,
        "chapter_introduction_absent_paths": absent_introductions,
        "null_previous_chapter_link_paths": null_previous,
        "null_next_chapter_link_paths": null_next,
        "retained_text_direction": "rtl",
    }


def _link_note(subtype: str, value: object) -> etree._Element:
    attributes = {"type": "chapter-link", "subtype": subtype}
    if value is None:
        attributes["ana"] = "null"
        return _el("note", attributes)
    if not isinstance(value, str):
        raise ValueError("John Gill chapter link is not a string or null")
    return _el("note", attributes, value)


def _build_tei(
    books_record: dict[str, Any],
    profiles_record: dict[str, Any],
    chapters: list[dict[str, Any]],
    source_digest: str,
) -> bytes:
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("John Gill source metadata is invalid")
    chapters_by_book: dict[str, list[dict[str, Any]]] = {}
    for item in chapters:
        raw_book = item.get("book")
        if not isinstance(raw_book, dict) or not isinstance(raw_book.get("id"), str):
            raise ValueError("John Gill chapter book metadata is invalid")
        chapters_by_book.setdefault(str(raw_book["id"]), []).append(item)

    tei = _el("TEI")
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text=str(commentary["name"])))
    title_stmt.append(_el("author", text="John Gill"))
    file_desc.append(title_stmt)
    publication_stmt = _el("publicationStmt")
    publication_stmt.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "restricted"})
    availability.append(
        _el(
            "p",
            text=(
                "Retained HelloAO metadata identifies the Public Domain Mark 1.0; "
                "the source config's CC0 label is recorded as drift and is not substituted."
            ),
        )
    )
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    notes_stmt = _el("notesStmt")
    notes_stmt.append(
        _el(
            "note",
            {"type": "commentary-metadata", "xml:space": "preserve"},
            json.dumps(commentary, ensure_ascii=False, separators=(",", ":")),
        )
    )
    notes_stmt.append(
        _el(
            "note",
            {"type": "profiles-metadata", "xml:space": "preserve"},
            json.dumps(profiles_record, ensure_ascii=False, separators=(",", ":")),
        )
    )
    notes_stmt.append(_el("note", {"type": "source-member-set-sha256"}, source_digest))
    notes_stmt.append(_el("note", {"type": "retained-text-direction"}, "rtl"))
    file_desc.append(notes_stmt)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("ptr", {"target": str(commentary["listOfBooksApiLink"])}))
    bibl.append(_el("ptr", {"target": str(commentary["listOfProfilesApiLink"])}))
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
        if not isinstance(raw_book, dict) or not isinstance(raw_book.get("id"), str):
            raise ValueError("John Gill book metadata is invalid")
        book_id = str(raw_book["id"])
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
        book_div.append(
            _el(
                "note",
                {"type": "book-metadata", "xml:space": "preserve"},
                json.dumps(raw_book, ensure_ascii=False, separators=(",", ":")),
            )
        )
        book_intro = _el(
            "div",
            {"type": "book-introduction", "xml:id": f"book-intro-{book_id}"},
        )
        _append_paragraphs(book_intro, str(raw_book["introduction"]))
        book_div.append(book_intro)
        for chapter_item in chapters_by_book.get(book_id, []):
            chapter = chapter_item.get("chapter")
            relative = chapter_item.get("relative_path")
            envelope = chapter_item.get("envelope")
            if (
                not isinstance(chapter, dict)
                or not isinstance(relative, str)
                or not isinstance(envelope, dict)
            ):
                raise ValueError("John Gill chapter model is invalid")
            number = chapter.get("number")
            if not isinstance(number, int):
                raise ValueError("John Gill chapter number is invalid")
            chapter_div = _el(
                "div",
                {
                    "type": "chapter",
                    "n": str(number),
                    "xml:id": f"chapter-{book_id}-{number:03d}",
                    "corresp": f"{_SOURCE_PREFIX}{relative}",
                },
            )
            chapter_div.append(
                _el(
                    "note",
                    {"type": "number-of-verses"},
                    str(envelope["numberOfVerses"]),
                )
            )
            chapter_div.append(
                _link_note("previous", envelope["previousChapterApiLink"])
            )
            chapter_div.append(_link_note("next", envelope["nextChapterApiLink"]))
            chapter_div.append(_link_note("this", envelope["thisChapterLink"]))
            if "introduction" in chapter:
                chapter_intro = _el(
                    "div",
                    {
                        "type": "chapter-introduction",
                        "xml:id": f"chapter-intro-{book_id}-{number:03d}",
                    },
                )
                _append_paragraphs(chapter_intro, str(chapter["introduction"]))
                chapter_div.append(chapter_intro)
            content = chapter.get("content")
            if not isinstance(content, list):
                raise ValueError("John Gill chapter content is invalid")
            for ordinal, raw_occurrence in enumerate(content, start=1):
                if not isinstance(raw_occurrence, dict):
                    raise ValueError("John Gill occurrence is invalid")
                occurrence_content = raw_occurrence.get("content")
                if (
                    not isinstance(occurrence_content, list)
                    or len(occurrence_content) != 1
                ):
                    raise ValueError("John Gill occurrence content is invalid")
                occurrence = _el(
                    "div",
                    {
                        "type": "commentary-occurrence",
                        "subtype": str(raw_occurrence["type"]),
                        "n": str(raw_occurrence["number"]),
                        "xml:id": f"commentary-{book_id}-{number:03d}-{ordinal:05d}",
                    },
                )
                _append_paragraphs(occurrence, str(occurrence_content[0]))
                chapter_div.append(occurrence)
            book_div.append(chapter_div)
        body.append(book_div)
    text.append(body)
    tei.append(text)
    return etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )


def _unresolved(
    config: dict[str, Any], commentary: dict[str, Any]
) -> list[dict[str, object]]:
    return [
        {
            "id": "john-gill-retained-vs-configured-title",
            "scope": "work",
            "kind": "identity",
            "question": "Which title should a human use for the work identity?",
            "evidence": {
                "retained_commentary_name": commentary["name"],
                "retained_english_name": commentary["englishName"],
                "configured_title": config.get("title"),
            },
        },
        {
            "id": "john-gill-config-cc0-vs-retained-pdm",
            "scope": "work",
            "kind": "rights",
            "question": "Should the config's CC0 label be replaced after rights review?",
            "evidence": {
                "retained_license_url": commentary["licenseUrl"],
                "retained_license_notes": commentary["licenseNotes"],
                "configured_license": config.get("license"),
                "configured_helloao_license": config.get("helloao_license"),
            },
        },
        {
            "id": "john-gill-configured-source-endpoint",
            "scope": "source",
            "kind": "witness",
            "question": "Confirm the canonical upstream endpoint for this retained snapshot.",
            "evidence": {
                "retained_books_link": commentary["listOfBooksApiLink"],
                "retained_profiles_link": commentary["listOfProfilesApiLink"],
                "configured_source_base_url": config.get("source_base_url"),
            },
        },
        {
            "id": "john-gill-retained-rtl-anomaly",
            "scope": "work",
            "kind": "editorial",
            "question": "Review the retained rtl direction marker on English commentary.",
            "evidence": {
                "retained_language": commentary["language"],
                "retained_text_direction": commentary["textDirection"],
            },
        },
        {
            "id": "john-gill-edition-and-original-date",
            "scope": "work",
            "kind": "identity",
            "question": "Identify the edition and original publication date represented by this digital witness.",
            "evidence": {
                "retained_witness": "HelloAO JSON snapshot",
                "configured_original_publication_year": config.get(
                    "original_publication_year"
                ),
                "retained_source_date": None,
            },
        },
    ]


def _accountability(
    records: tuple[dict[str, object], ...],
    books_record: dict[str, Any],
    profiles_record: dict[str, Any],
    chapters: list[dict[str, Any]],
    source_digest: str,
    structure_summary: dict[str, object],
) -> dict[str, object]:
    present_intros = sum(
        isinstance(item["chapter"], dict) and "introduction" in item["chapter"]
        for item in chapters
    )
    occurrences = sum(
        len(item["chapter"]["content"])
        for item in chapters
        if isinstance(item["chapter"], dict)
        and isinstance(item["chapter"].get("content"), list)
    )
    members = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
            "disposition": "included",
            "reason": (
                "retained collection metadata"
                if item["relative_path"] in {"books.json", "profiles.json"}
                else "retained chapter envelope and commentary occurrences"
            ),
        }
        for item in records
    ]
    return {
        "contract": "ocd-helloao-john-gill-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "source_root": _SOURCE_PREFIX.removesuffix("/"),
        "source_member_set_sha256": source_digest,
        "member_count": len(records),
        "total_bytes": sum(int(item["bytes"]) for item in records),
        "included_member_count": len(records),
        "excluded_member_count": 0,
        "members": members,
        "excluded_members": [],
        "source_shapes": {
            "collection_metadata_members": ["books.json", "profiles.json"],
            "commentary_metadata_keys": sorted(_COMMENTARY_KEYS),
            "book_metadata_keys": sorted(_BOOK_KEYS),
            "chapter_envelope_keys": sorted(_ENVELOPE_KEYS),
            "chapter_keys_with_introduction": sorted(_CHAPTER_KEYS_WITH_INTRODUCTION),
            "chapter_keys_without_introduction": sorted(
                _CHAPTER_KEYS_WITHOUT_INTRODUCTION
            ),
            "occurrence_keys": ["content", "number", "type"],
            "occurrence_content_shape": "list[str] of length 1",
        },
        "census": {
            "books": len(books_record["books"]),
            "chapters": len(chapters),
            "commentary_occurrences": occurrences,
            "book_introductions": len(books_record["books"]),
            "chapter_introductions_present": present_intros,
            "chapter_introductions_absent": len(chapters) - present_intros,
            "profiles": len(profiles_record["profiles"]),
        },
        "content_digests": _content_digests(books_record, profiles_record, chapters),
        "meaningful_structure": structure_summary,
        "anomalies": _anomalies(chapters),
        "retained_metadata": books_record["commentary"],
        "profiles_metadata": profiles_record,
    }


def _provenance(
    source_manifest: SourceManifest,
    commentary: dict[str, Any],
    config: dict[str, Any],
    source_digest: str,
) -> dict[str, object]:
    return {
        "contract": "ocd-helloao-john-gill-candidate-provenance-v1",
        "status": "nonaccepted",
        "identity": {
            "work_id": "john-gill",
            "retained_title": commentary["name"],
            "configured_title": config.get("title"),
            "author": "John Gill",
            "author_evidence": "retained commentary id john-gill and retained John Gill website link",
            "edition": None,
            "original_publication_year": None,
            "digital_witness": "retained HelloAO JSON snapshot",
        },
        "scope": {
            "complete_for_retained_witness": True,
            "book_count": 66,
            "chapter_count": 1189,
            "commentary_occurrence_count": 28_300,
            "canonical_bible_complete": True,
            "missing_canonical_books": [],
            "profiles": 0,
        },
        "rights": {
            "retained_mark": "PDM 1.0",
            "retained_license_url": commentary["licenseUrl"],
            "retained_license_notes": commentary["licenseNotes"],
            "config_value_not_applied": config.get("license"),
            "attribution_ask": None,
        },
        "source_identity": {
            "source_manifest_sha256": source_manifest.sha256,
            "source_member_set_sha256": source_digest,
            "commentary_id": commentary["id"],
            "source_reported_metadata_sha256": commentary["sha256"],
            "retained_books_link": commentary["listOfBooksApiLink"],
            "retained_profiles_link": commentary["listOfProfilesApiLink"],
        },
        "source_anomalies": {
            "retained_language": commentary["language"],
            "retained_text_direction": commentary["textDirection"],
            "configured_source_base_url": config.get("source_base_url"),
        },
        "alternate_witness": {"status": "none supplied", "merged": False},
        "accepted_ir": "not_accepted",
        "publication": "not_ready",
        "human_decision": None,
    }


def _readme(source_digest: str, config: dict[str, Any]) -> str:
    return f"""# John Gill retained HelloAO source

This candidate is a deterministic, nonaccepted TEI reconstruction of the complete retained
HelloAO JSON witness at `raw/helloao_local/api/c/john-gill`.

- The retained census is exactly 1,191 members and 54,866,016 bytes.
- It contains 66 books, 1,189 chapters, and 28,300 ordered commentary occurrences.
- All 66 book introductions, 1,186 present chapter introductions, and three absent
  `introduction` properties are accounted for.
- The source reports 19 chapters whose occurrence numbers are nonmonotonic. Their order is
  preserved. No duplicate occurrence numbers were found.
- The retained English metadata says `textDirection: rtl`; that anomaly is preserved and
  localized for human review.
- No Bible or BSB verse text, inferred ranges, modernized wording, or second witness was added.
- The formal retained member-set identity is `{source_digest}`.
- The retained source identifies the Public Domain Mark 1.0 at
  `{config.get("helloao_license")}`. The config's `cc0-1.0` value is recorded as a rights
  question and is not applied.
- A source-attribution ask was not present in the retained metadata; no extra attribution
  README is required by this witness.

The candidate remains `nonaccepted`, `accepted_ir: not_accepted`, and `publication: not_ready`.
The configured title, endpoint, CC0 label, retained direction marker, and edition/date identity
are surfaced in `unresolved.jsonl`; they require human review and are not silently resolved.
"""


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = _authority_json(source_manifest, "reconstruction-profile")
    policy = _authority_json(source_manifest, "validation-policy")
    config = _authority_json(source_manifest, "source-config")
    _validate_profile_policy(profile, policy)
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_corpus(source_manifest, records)
    _structure_by_key, _rendered_structure_keys, structure_summary = _load_structure_inventory(
        source_manifest, books_record, chapters
    )
    commentary = books_record.get("commentary")
    if not isinstance(commentary, dict):
        raise ValueError("John Gill commentary metadata is invalid")
    source_digest = _source_set_digest(records)
    return {
        "content.tei.xml": _build_tei(
            books_record,
            profiles_record,
            chapters,
            source_digest,
        ),
        "source-accountability.json": _canonical(
            _accountability(
                records,
                books_record,
                profiles_record,
                chapters,
                source_digest,
                structure_summary,
            )
        ),
        "provenance.json": _canonical(
            _provenance(source_manifest, commentary, config, source_digest)
        ),
        "unresolved.jsonl": b"".join(
            _canonical(item) for item in _unresolved(config, commentary)
        ),
        "README.source.md": _readme(source_digest, config).encode("utf-8"),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION


__all__: tuple[str, ...] = ()
