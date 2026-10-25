"""Faithful reconstruction of the complete retained HelloAO Jamieson-Fausset-Brown JSON witness."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-helloao-jamieson-fausset-brown-json-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "helloao-jamieson-fausset-brown-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/jamieson-fausset-brown/"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_EXPECTED_TEI_PROLOG = b"<?xml version='1.0' encoding='UTF-8'?>\n"
_STRUCTURE_INVENTORY_AUTHORITY = "structure-inventory"
_STRUCTURE_INVENTORY_CONTRACT = "ocd-source-structure-inventory-v1"
_STRUCTURE_POLICY_CHECK = (
    "exact-source-double-newline-paragraph-segmentation-and-pinned-heading-inventory"
)
_MOJIBAKE_SIGNATURES = (
    ("U+00C3 followed by literal &brvbr", "\u00c3&brvbr"),
    ("U+00C5 U+201C", "\u00c5\u201c"),
    ("U+00C3 U+2020", "\u00c3\u2020"),
    ("U+00C2 U+00A3", "\u00c2\u00a3"),
)


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
        elif key == "xml:space":
            normalized[_XML_SPACE] = value
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
        raise ValueError("Jamieson-Fausset-Brown source authorities are invalid")
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
            raise ValueError(
                "Jamieson-Fausset-Brown primary-source authority is malformed"
            )
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
        len(records) != 1_189
        or sum(int(item["bytes"]) for item in records) != 22_377_675
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown retained member census differs from 1,189/22,377,675"
        )
    relative = [str(item["relative_path"]) for item in records]
    if len(set(relative)) != 1_189:
        raise ValueError("Jamieson-Fausset-Brown retained member paths are not unique")
    if set(relative) & {"books.json", "profiles.json"} != {
        "books.json",
        "profiles.json",
    }:
        raise ValueError("Jamieson-Fausset-Brown retained metadata members are missing")
    chapter_paths = [
        item for item in relative if item not in {"books.json", "profiles.json"}
    ]
    if len(chapter_paths) != 1_187 or any(
        path.count("/") != 1 for path in chapter_paths
    ):
        raise ValueError("Jamieson-Fausset-Brown chapter member paths are incomplete")
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


def _verify_catalog_lineage(
    source_manifest: SourceManifest, source_digest: str
) -> None:
    lineage = source_manifest.record.get("catalog_claim_lineage")
    if not isinstance(lineage, Mapping) or (
        lineage.get("contract") != "ocd-catalog-claim-lineage-v1"
        or lineage.get("work_id") != "jamieson-fausset-brown"
        or lineage.get("retained_source_sha256") != source_digest
    ):
        raise ValueError("Jamieson-Fausset-Brown catalog lineage is stale")
    claims = lineage.get("claims")
    if (
        not isinstance(claims, tuple)
        or lineage.get("claim_count") != 66
        or len(claims) != 66
    ):
        raise ValueError("Jamieson-Fausset-Brown catalog claim census drifted")
    paths: list[str] = []
    hashes: list[str] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("Jamieson-Fausset-Brown catalog claim is malformed")
        path = claim.get("source_path")
        digest = claim.get("legacy_source_sha256")
        if (
            not isinstance(path, str)
            or not path.startswith("commentaries/jamieson-fausset-brown/")
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("Jamieson-Fausset-Brown catalog claim is malformed")
        paths.append(path)
        hashes.append(digest)
    if paths != sorted(paths) or len(set(paths)) != 66 or len(set(hashes)) != 66:
        raise ValueError(
            "Jamieson-Fausset-Brown catalog claims are reordered or duplicated"
        )


def _authority_json(source_manifest: SourceManifest, name: str) -> dict[str, object]:
    return _strict_json(source_manifest.authority_path(name).read_bytes(), name)


def _resolve_pointer(value: object, pointer: str) -> object:
    current = value
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError(f"structure inventory pointer escaped its JSON carrier: {pointer}")
    return current


def _load_structure_inventory(
    source_manifest: SourceManifest,
    records: tuple[dict[str, object], ...],
) -> tuple[
    dict[tuple[str, str], dict[str, object]],
    set[tuple[str, str]],
    dict[str, object],
]:
    content = source_manifest.authority_path(_STRUCTURE_INVENTORY_AUTHORITY).read_bytes()
    inventory = _strict_json(content, _STRUCTURE_INVENTORY_AUTHORITY)
    if (
        inventory.get("contract") != _STRUCTURE_INVENTORY_CONTRACT
        or inventory.get("version") != 1
        or inventory.get("work_id") != "jamieson-fausset-brown"
        or inventory.get("source_id")
        != "helloao-jamieson-fausset-brown-complete-retained-json"
        or inventory.get("source_root") != _SOURCE_PREFIX.removesuffix("/")
    ):
        raise ValueError("Jamieson-Fausset-Brown structure inventory identity drifted")
    scope = inventory.get("scope")
    entries = inventory.get("entries")
    if not isinstance(scope, dict) or not isinstance(entries, list):
        raise ValueError("Jamieson-Fausset-Brown structure inventory shape is invalid")
    paragraph_policy = scope.get("paragraph_policy")
    if (
        not isinstance(paragraph_policy, dict)
        or paragraph_policy.get("contract")
        != "ocd-source-paragraph-segmentation-v1"
        or paragraph_policy.get("delimiter") != "\n\n"
        or paragraph_policy.get("mode") != "split-every-exact-double-newline"
        or paragraph_policy.get("carrier_total_count") != 18_300
        or paragraph_policy.get("carrier_count_with_delimiter") != 17_771
        or paragraph_policy.get("delimiter_count") != 42_598
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown source paragraph policy drifted"
        )
    primary_by_path = {str(item["path"]): item for item in records}
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    rendered_keys: set[tuple[str, str]] = set()
    span_count = 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Jamieson-Fausset-Brown structure inventory entry is invalid")
        source_path = item.get("source_path")
        pointer = item.get("json_pointer")
        if (
            not isinstance(source_path, str)
            or not source_path.startswith(_SOURCE_PREFIX)
            or not isinstance(pointer, str)
            or not pointer.startswith("/")
        ):
            raise ValueError("Jamieson-Fausset-Brown structure inventory carrier is invalid")
        key = (source_path, pointer)
        if key in by_key:
            raise ValueError("Jamieson-Fausset-Brown structure inventory duplicates a carrier")
        primary = primary_by_path.get(source_path)
        if primary is None:
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory references unbound carrier {source_path}"
            )
        source_bytes = source_manifest.authority_path(str(primary["name"])).read_bytes()
        if (
            item.get("source_file_bytes") != len(source_bytes)
            or item.get("source_file_sha256") != _sha(source_bytes)
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory source file drifted: {source_path}"
            )
        carrier_value = _resolve_pointer(
            _strict_json(source_bytes, source_path), pointer
        )
        if not isinstance(carrier_value, str):
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory carrier is not text: {key}"
            )
        if (
            item.get("carrier_utf8_bytes") != len(carrier_value.encode("utf-8"))
            or item.get("carrier_codepoint_length") != len(carrier_value)
            or item.get("carrier_sha256") != _sha(carrier_value.encode("utf-8"))
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory carrier text drifted: {key}"
            )
        headings = item.get("headings")
        if not isinstance(headings, list) or not headings:
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory headings are missing: {key}"
            )
        previous_end = -1
        for heading in headings:
            if not isinstance(heading, dict):
                raise ValueError("Jamieson-Fausset-Brown structure inventory heading is invalid")
            start = heading.get("start")
            end = heading.get("end")
            label = heading.get("text")
            before = heading.get("boundary_before")
            after = heading.get("boundary_after")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or not isinstance(label, str)
                or not isinstance(before, str)
                or not isinstance(after, str)
                or start < 0
                or end <= start
                or end > len(carrier_value)
                or start < previous_end
                or carrier_value[start:end] != label
            ):
                raise ValueError(
                    f"Jamieson-Fausset-Brown structure inventory heading span drifted: {key}"
                )
            expected_before = (
                "start"
                if start == 0
                else "blank-line"
                if carrier_value[start - 2 : start] == "\n\n"
                else "inline"
            )
            expected_after = (
                "blank-line"
                if carrier_value[end : end + 2] == "\n\n"
                else "inline-space-hyphen"
                if carrier_value[end : end + 3] == " - "
                else "end"
                if end == len(carrier_value)
                else "other"
            )
            if before != expected_before or after != expected_after:
                raise ValueError(
                    f"Jamieson-Fausset-Brown structure inventory boundary drifted: {key}"
                )
            previous_end = end
            span_count += 1
        by_key[key] = item
        if item.get("rendered_carrier") is not True:
            raise ValueError(
                "Jamieson-Fausset-Brown structure inventory contains an unrendered carrier"
            )
        rendered_keys.add(key)
    if (
        scope.get("carrier_count") != 5
        or scope.get("rendered_carrier_count") != 5
        or scope.get("heading_span_count") != 6
        or len(entries) != 5
        or len(rendered_keys) != 5
        or span_count != 6
    ):
        raise ValueError("Jamieson-Fausset-Brown structure inventory census drifted")
    return (
        by_key,
        rendered_keys,
        {
            "authority": _STRUCTURE_INVENTORY_AUTHORITY,
            "sha256": _sha(content),
            "carrier_count": len(entries),
            "rendered_carrier_count": len(rendered_keys),
            "heading_span_count": span_count,
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


def _append_source_text(
    parent: etree._Element,
    text: str,
    inventory_entry: dict[str, object] | None,
    *,
    label: str,
) -> None:
    headings = [] if inventory_entry is None else inventory_entry["headings"]
    if not isinstance(headings, list) or not headings:
        _append_paragraphs(parent, text)
        return
    parent.text = ""
    parent_id = parent.get(_XML_ID)
    if not isinstance(parent_id, str):
        raise ValueError(f"structured source carrier has no xml:id: {label}")
    cursor = 0
    for ordinal, heading in enumerate(headings, start=1):
        if not isinstance(heading, dict):
            raise ValueError(f"structured source heading is invalid: {label}")
        start = int(heading["start"])
        end = int(heading["end"])
        if start < cursor or text[start:end] != heading["text"]:
            raise ValueError(f"structured source span drifted: {label}")
        prefix = text[cursor:start]
        if prefix:
            _append_paragraphs(parent, prefix)
        section = _el(
            "div",
            {
                "type": "commentary-section",
                "xml:id": f"{parent_id}-section-{ordinal:03d}",
            },
        )
        section.text = ""
        section.tail = ""
        head = _el("head", text=str(heading["text"]))
        head.tail = ""
        section.append(head)
        next_start = (
            int(headings[ordinal]["start"])
            if ordinal < len(headings)
            else len(text)
        )
        remainder = text[end:next_start]
        if remainder:
            _append_paragraphs(section, remainder)
        parent.append(section)
        cursor = next_start
    if cursor != len(text):
        raise ValueError(f"structured source text was not fully consumed: {label}")


def _load_corpus(
    source_manifest: SourceManifest, records: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, object]:
        item = by_relative.get(relative)
        if item is None:
            raise ValueError(f"Jamieson-Fausset-Brown manifest omits {relative}")
        return _strict_json(
            source_manifest.authority_path(str(item["name"])).read_bytes(), relative
        )

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("Jamieson-Fausset-Brown books.json shape is invalid")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown profiles metadata disagrees with books metadata"
        )
    expected_commentary = {
        "id": "jamieson-fausset-brown",
        "name": "Jamieson-Fausset-Brown Bible Commentary",
        "englishName": "Jamieson-Fausset-Brown Bible Commentary",
        "language": "eng",
        "textDirection": "rtl",
        "licenseUrl": "https://creativecommons.org/publicdomain/mark/1.0/",
        "numberOfBooks": 66,
        "totalNumberOfChapters": 1187,
        "totalNumberOfVerses": 17056,
        "totalNumberOfProfiles": 0,
    }
    if any(commentary.get(key) != value for key, value in expected_commentary.items()):
        raise ValueError(
            "Jamieson-Fausset-Brown retained commentary identity or census drifted"
        )
    if set(commentary) != {
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
    }:
        raise ValueError("Jamieson-Fausset-Brown retained commentary fields drifted")
    if len(books) != 66:
        raise ValueError("Jamieson-Fausset-Brown books.json must contain 66 books")

    chapter_paths_by_book: dict[str, list[tuple[int, str]]] = {}
    for relative in by_relative:
        if relative in {"books.json", "profiles.json"}:
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            raise ValueError(
                f"Jamieson-Fausset-Brown chapter path is invalid: {relative}"
            )
        try:
            number = int(parts[1].removesuffix(".json"))
        except ValueError as exc:
            raise ValueError(
                f"Jamieson-Fausset-Brown chapter path is invalid: {relative}"
            ) from exc
        if number < 1:
            raise ValueError(
                f"Jamieson-Fausset-Brown chapter number is invalid: {relative}"
            )
        chapter_paths_by_book.setdefault(parts[0], []).append((number, relative))

    chapters: list[dict[str, object]] = []
    seen_paths = {"books.json", "profiles.json"}
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict):
            raise ValueError("Jamieson-Fausset-Brown book metadata is invalid")
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
            or set(raw_book)
            != {
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
            }
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown book metadata drifted at retained ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        book_paths = sorted(chapter_paths_by_book.pop(book_id, []))
        if len(book_paths) != chapter_count:
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter count disagrees at {book_id}"
            )
        observed_numbers = [number for number, _ in book_paths]
        expected_gap = {"MRK": [15], "PSA": [146]}.get(book_id, [])
        if not isinstance(first, int) or not isinstance(last, int):
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter path coverage drifted at {book_id}"
            )
        full_range = list(range(first, last + 1))
        if (
            first != 1
            or not isinstance(last, int)
            or [number for number in full_range if number not in observed_numbers]
            != expected_gap
            or any(number not in full_range for number in observed_numbers)
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter path coverage drifted at {book_id}"
            )
        for chapter_number, relative in book_paths:
            chapter_record = load(relative)
            seen_paths.add(relative)
            chapter = chapter_record.get("chapter")
            if (
                chapter_record.get("commentary") != commentary
                or chapter_record.get("book") != raw_book
                or not isinstance(chapter, dict)
                or chapter.get("number") != chapter_number
                or not isinstance(chapter.get("content"), list)
                or set(chapter)
                not in (
                    {"number", "content"},
                    {"number", "content", "introduction"},
                )
                or set(chapter_record)
                != {
                    "commentary",
                    "book",
                    "chapter",
                    "thisChapterLink",
                    "nextChapterApiLink",
                    "previousChapterApiLink",
                    "numberOfVerses",
                }
                or chapter_record.get("numberOfVerses") != len(chapter["content"])
                or not isinstance(chapter_record.get("thisChapterLink"), str)
                or not isinstance(
                    chapter_record.get("nextChapterApiLink"), (str, type(None))
                )
                or not isinstance(
                    chapter_record.get("previousChapterApiLink"), (str, type(None))
                )
            ):
                raise ValueError(
                    f"Jamieson-Fausset-Brown chapter envelope drifted at {relative}"
                )
            if "introduction" in chapter and not isinstance(
                chapter["introduction"], str
            ):
                raise ValueError(
                    f"Jamieson-Fausset-Brown chapter introduction is invalid at {relative}"
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
                        f"Jamieson-Fausset-Brown commentary occurrence is invalid at {relative}"
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
        or len(chapters) != 1_187
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown retained member coverage is incomplete or contains extras"
        )
    return books_record, profiles_record, chapters


def _build_tei(
    books_record: dict[str, object],
    chapters: list[dict[str, object]],
    source_digest: str,
    structure_by_key: dict[tuple[str, str], dict[str, object]],
    rendered_structure_keys: set[tuple[str, str]],
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
        ("license-notes", json.dumps(commentary["licenseNotes"])),
        ("language", commentary["language"]),
        ("language-name", commentary["languageName"]),
        ("language-english-name", commentary["languageEnglishName"]),
        ("text-direction", commentary["textDirection"]),
        ("source-reported-sha256", commentary["sha256"]),
        ("available-formats", json.dumps(commentary["availableFormats"])),
        ("books-api-link", commentary["listOfBooksApiLink"]),
        ("profiles-api-link", commentary["listOfProfilesApiLink"]),
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
    used_structure_keys: set[tuple[str, str]] = set()
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
        _append_source_text(
            book_intro,
            str(raw_book["introduction"]),
            None,
            label=f"book introduction {book_id}",
        )
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
                chapter_intro_key = (
                    f"{_SOURCE_PREFIX}{relative}",
                    "/chapter/introduction",
                )
                chapter_intro_entry = structure_by_key.get(chapter_intro_key)
                if chapter_intro_entry is not None:
                    used_structure_keys.add(chapter_intro_key)
                _append_source_text(
                    chapter_intro,
                    str(chapter["introduction"]),
                    chapter_intro_entry,
                    label=f"chapter introduction {relative}",
                )
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
                occurrence_key = (
                    f"{_SOURCE_PREFIX}{relative}",
                    f"/chapter/content/{ordinal - 1}/content/0",
                )
                occurrence_entry = structure_by_key.get(occurrence_key)
                if occurrence_entry is not None:
                    used_structure_keys.add(occurrence_key)
                _append_source_text(
                    occurrence,
                    str(raw_occurrence["content"][0]),
                    occurrence_entry,
                    label=f"commentary occurrence {relative}#{ordinal}",
                )
                chapter_div.append(occurrence)
            book_div.append(chapter_div)
        body.append(book_div)
    if used_structure_keys != rendered_structure_keys:
        raise ValueError(
            "Jamieson-Fausset-Brown structure inventory rendered carrier census drifted"
        )
    text.append(body)
    tei.append(text)
    content = etree.tostring(
        tei, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )
    if not content.startswith(_EXPECTED_TEI_PROLOG + b"<TEI "):
        raise ValueError("Jamieson-Fausset-Brown TEI document prolog drifted")
    return content


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


def _mojibake_census(
    books_record: dict[str, object], chapters: list[dict[str, object]]
) -> dict[str, object]:
    """Census retained suspected mojibake without interpreting or correcting it."""

    books = books_record["books"]
    assert isinstance(books, list)
    carriers: list[tuple[str, str, str]] = []
    for raw_book in books:
        assert isinstance(raw_book, dict)
        carriers.append(
            (
                "book-introduction",
                f"books.json#/books/{raw_book['id']}/introduction",
                str(raw_book["introduction"]),
            )
        )
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        assert isinstance(relative, str) and isinstance(chapter, dict)
        if "introduction" in chapter:
            carriers.append(
                (
                    "chapter-introduction",
                    f"{relative}#/chapter/introduction",
                    str(chapter["introduction"]),
                )
            )
        content = chapter["content"]
        assert isinstance(content, list)
        for ordinal, occurrence in enumerate(content, start=1):
            assert isinstance(occurrence, dict)
            carriers.append(
                (
                    "commentary-occurrence",
                    f"{relative}#/chapter/content/{ordinal}/content/0",
                    str(occurrence["content"][0]),
                )
            )

    affected: list[tuple[str, str]] = []
    signature_counts: list[dict[str, object]] = []
    examples: list[dict[str, object]] = []
    for label, signature in _MOJIBAKE_SIGNATURES:
        count = 0
        example: dict[str, object] | None = None
        for kind, carrier, text in carriers:
            occurrences = text.count(signature)
            if not occurrences:
                continue
            count += occurrences
            affected.append((kind, carrier))
            if example is None:
                example = {
                    "carrier": carrier,
                    "offset": text.index(signature),
                    "retained_sequence": signature,
                }
        if example is None:
            raise ValueError(
                f"Jamieson-Fausset-Brown retained {label} example disappeared"
            )
        signature_counts.append(
            {"signature": label, "retained_sequence": signature, "count": count}
        )
        examples.append(example)

    unique_affected = sorted(set(affected), key=lambda item: (item[0], item[1]))
    affected_members = sorted(
        {carrier.split("#", 1)[0] for _, carrier in unique_affected}
    )
    by_kind: dict[str, dict[str, int]] = {}
    for kind in ("book-introduction", "chapter-introduction", "commentary-occurrence"):
        kind_carriers = {
            carrier
            for observed_kind, carrier in unique_affected
            if observed_kind == kind
        }
        by_kind[kind] = {
            "sequence_count": sum(
                text.count(signature)
                for observed_kind, _, text in carriers
                if observed_kind == kind
                for _, signature in _MOJIBAKE_SIGNATURES
            ),
            "carrier_count": len(kind_carriers),
        }
    census = {
        "sequence_count": sum(int(item["count"]) for item in signature_counts),
        "carrier_count": len({carrier for _, carrier in unique_affected}),
        "source_member_count": len(affected_members),
        "signatures": signature_counts,
        "affected_carriers": by_kind,
        "affected_carriers_sha256": _sha(_canonical(unique_affected)),
        "affected_source_members_sha256": _sha(_canonical(affected_members)),
        "examples": examples,
        "tei_disposition": "preserved byte-for-codepoint; no silent correction",
        "correction_authority_required": (
            "exact source or correction authority for each affected reading"
        ),
    }
    if (
        census["sequence_count"] != 539
        or census["carrier_count"] != 374
        or census["source_member_count"] != 229
        or by_kind
        != {
            "book-introduction": {"sequence_count": 85, "carrier_count": 33},
            "chapter-introduction": {"sequence_count": 53, "carrier_count": 39},
            "commentary-occurrence": {"sequence_count": 401, "carrier_count": 302},
        }
    ):
        raise ValueError("Jamieson-Fausset-Brown retained mojibake census drifted")
    return census


def _source_readme(mojibake: dict[str, object]) -> bytes:
    examples = mojibake["examples"]
    assert isinstance(examples, list)
    example_text = ", ".join(
        f"`{item['carrier']}` at offset {int(item['offset']):,}"
        for item in examples
        if isinstance(item, dict)
    )
    return (
        "# Jamieson-Fausset-Brown retained HelloAO witness\n\n"
        "This nonaccepted candidate faithfully represents all 1,189 retained JSON members under "
        "`raw/helloao_local/api/c/jamieson-fausset-brown`: `books.json`, `profiles.json`, and 1,187 chapter files in 66 book directories.\n\n"
        "The retained witness contains 17,056 ordered commentary occurrences. Occurrences are not sorted or merged; both distinct verse-7 occurrences in Hebrews 13 remain present. The retained books-index ranges omit `MRK/15.json` and `PSA/146.json`; those source gaps are explicit and no chapters or Bible text are inferred. All 101 introduction-only chapters and all nine chapters without an introduction property remain structurally distinct.\n\n"
        "## Localized substantive-reading question\n\n"
        "An independent census finds exactly 539 suspected mojibake sequences in 374 retained semantic text carriers across 229 source members. The affected carriers are 33 book introductions (85 sequences), 39 chapter introductions (53 sequences), and 302 commentary occurrences (401 sequences). Signature counts are 281 for `U+00C3` followed by literal `&brvbr`, 114 for `U+00C5 U+201C`, 93 for `U+00C3 U+2020`, and 51 for `U+00C2 U+00A3`. Exact localized examples are "
        f"{example_text}.\n\n"
        "Every affected string is preserved byte-for-codepoint in the TEI. No guessed normalization is authorized: each replacement requires exact source or correction authority for the affected reading, followed by regeneration and review. Unaffected technical reconstruction may continue.\n\n"
        "HelloAO metadata links the Public Domain Mark 1.0. The existing source config says CC0; this candidate records that drift and does not replace the retained PDM statement. PDM contains no attribution request, but HelloAO is identified as the retained API provider.\n\n"
        "Edition and exact bibliographic identity, the rights-description drift, retained `textDirection: rtl` anomaly, and localized suspected-mojibake readings remain unresolved. Accepted IR is `not_accepted`; publication is `not_ready`.\n"
    ).encode("utf-8")


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile = _authority_json(source_manifest, "reconstruction-profile")
    policy = _authority_json(source_manifest, "validation-policy")
    config = _authority_json(source_manifest, "source-config")
    if (
        profile.get("contract") != "ocd-helloao-jamieson-fausset-brown-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or policy.get("contract")
        != "ocd-helloao-jamieson-fausset-brown-validation-policy-v1"
        or _STRUCTURE_POLICY_CHECK not in policy.get("checks", [])
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown reconstruction profile or policy mismatch"
        )
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_corpus(source_manifest, records)
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    source_digest = _source_set_digest(records)
    _verify_catalog_lineage(source_manifest, source_digest)
    structure_by_key, rendered_structure_keys, structure_summary = (
        _load_structure_inventory(source_manifest, records)
    )
    tei_bytes = _build_tei(
        books_record,
        chapters,
        source_digest,
        structure_by_key,
        rendered_structure_keys,
    )
    mojibake = _mojibake_census(books_record, chapters)

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
        "contract": "ocd-helloao-jamieson-fausset-brown-source-accountability-v1",
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
            "introduction_only_chapters": sum(
                "introduction" in item["chapter"] and not item["chapter"]["content"]
                for item in chapters
            ),
            "profiles": len(profiles_record["profiles"]),
        },
        "content_digests": _content_digests(books_record, chapters),
        "meaningful_structure": structure_summary,
        "retained_metadata": commentary,
        "profiles": profiles_record["profiles"],
        "retained_books": books_record["books"],
        "chapter_envelopes": [
            {
                "path": item["relative_path"],
                "thisChapterLink": item["envelope"]["thisChapterLink"],
                "nextChapterApiLink": item["envelope"]["nextChapterApiLink"],
                "previousChapterApiLink": item["envelope"]["previousChapterApiLink"],
                "numberOfVerses": item["envelope"]["numberOfVerses"],
            }
            for item in chapters
        ],
        "config_drift": {
            "config_license": config.get("license"),
            "retained_license_url": commentary.get("licenseUrl"),
            "disposition": "retained PDM metadata governs this witness; CC0 is not substituted",
        },
        "retained_chapter_gaps": {
            "MRK": [15],
            "PSA": [146],
            "disposition": "preserved exact books-index range gaps; no chapters inferred",
        },
        "retained_mojibake": mojibake,
    }
    provenance = {
        "contract": "ocd-helloao-jamieson-fausset-brown-candidate-provenance-v1",
        "status": "nonaccepted",
        "identity": {
            "work_id": "jamieson-fausset-brown",
            "retained_title": commentary["name"],
            "author": None,
            "edition": None,
            "original_publication_year": None,
            "digital_witness": "retained HelloAO JSON snapshot",
        },
        "scope": {
            "complete_for_retained_witness": True,
            "book_count": 66,
            "canonical_book_set_complete": True,
            "chapter_count": 1187,
            "retained_chapter_gaps": profile["scope"]["retained_chapter_gaps"],
        },
        "rights": {
            "retained_mark": "PDM 1.0",
            "retained_license_url": commentary["licenseUrl"],
            "config_value_not_applied": config.get("license"),
            "attribution_ask": None,
        },
        "source_anomalies": {
            "retained_text_direction": commentary["textDirection"],
            "retained_mojibake": mojibake,
        },
        "accepted_ir": "not_accepted",
        "human_review": "required",
        "publication": "not_ready",
        "human_decision": None,
    }
    unresolved = [
        {
            "id": "jamieson-fausset-brown-rights-config-drift",
            "question": "Should any later acceptance describe the retained PDM mark differently from the source config's CC0 value?",
            "evidence": ["books.json:commentary.licenseUrl", "source-config:license"],
            "consequence": "candidate preserves PDM and does not assert CC0",
            "escalation": "human-review-only-if-acceptance-is-considered",
        },
        {
            "id": "jamieson-fausset-brown-edition-and-bibliographic-identity",
            "question": "Which edition and exact author statement does the retained HelloAO JSON witness represent?",
            "evidence": ["retained HelloAO metadata", "source-config"],
            "consequence": "edition, author statement, and original publication year remain unset",
            "escalation": "human-review-only-if-identity-is-decided",
        },
        {
            "id": "jamieson-fausset-brown-retained-text-direction-anomaly",
            "question": "Is the retained rtl textDirection value an upstream metadata error?",
            "evidence": ["books.json:commentary.textDirection"],
            "consequence": "rtl remains explicit evidence and is not applied to the English TEI text",
            "escalation": "upstream-or-human-review",
        },
        {
            "id": "jamieson-fausset-brown-localized-suspected-mojibake-readings",
            "question": "What source-backed readings, if any, should replace the 539 localized suspected-mojibake sequences?",
            "evidence": {
                "census": mojibake,
                "authority_boundary": (
                    "exact source or correction authority is required for each affected reading"
                ),
            },
            "consequence": (
                "all 539 sequences remain byte-for-codepoint in the TEI; unaffected technical "
                "reconstruction may continue, but the affected readings cannot be silently corrected"
            ),
            "escalation": "source-or-correction-authority-before-editorial-normalization",
        },
    ]
    readme = _source_readme(mojibake)
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
