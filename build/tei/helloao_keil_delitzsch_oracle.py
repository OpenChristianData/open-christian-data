"""Independent oracle for the complete retained HelloAO Keil-Delitzsch witness."""

from __future__ import annotations

import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import sys
from xml.parsers import expat
from collections.abc import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest


ORACLE_ID = "ocd-helloao-keil-delitzsch-source-to-tei-oracle"
ORACLE_VERSION = "1"
_PROFILE_ID = "helloao-keil-delitzsch-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/keil-delitzsch/"
_STRUCTURE_INVENTORY_AUTHORITY = "structure-inventory"
_STRUCTURE_INVENTORY_CONTRACT = "ocd-source-structure-inventory-v1"
_STRUCTURE_POLICY_CHECK = (
    "exact-source-double-newline-paragraph-segmentation-and-pinned-book-introduction-headings"
)
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
_CANONICAL_XML_DECLARATION = b"<?xml version='1.0' encoding='UTF-8'?>\n"
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
_CHAPTER_WITH_INTRO = {"content", "introduction", "number"}
_CHAPTER_WITHOUT_INTRO = {"content", "number"}


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
        value = json.loads(content.decode("utf-8"), object_pairs_hook=reject)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _primary_members(source_manifest: SourceManifest) -> tuple[dict[str, object], ...]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Keil-Delitzsch oracle received invalid source authorities")
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
            or type(size) is not int
            or not isinstance(digest, str)
        ):
            raise ValueError("Keil-Delitzsch oracle primary authority is malformed")
        relative = path.removeprefix(_SOURCE_PREFIX)
        if (
            not relative
            or Path(relative).as_posix() != relative
            or ".." in Path(relative).parts
        ):
            raise ValueError("Keil-Delitzsch oracle primary path is not normalized")
        members.append(
            {
                "name": name,
                "path": path,
                "bytes": size,
                "sha256": digest,
                "relative_path": relative,
            }
        )
    members.sort(key=lambda item: (str(item["path"]), str(item["name"])))
    if len(members) != 911 or sum(int(item["bytes"]) for item in members) != 47_103_116:
        raise ValueError(
            "Keil-Delitzsch oracle census is not 911 members/47103116 bytes"
        )
    relative = [str(item["relative_path"]) for item in members]
    if len(set(relative)) != 911:
        raise ValueError("Keil-Delitzsch oracle primary paths are duplicated")
    metadata = {"books.json", "profiles.json"}
    if (
        set(relative) & metadata != metadata
        or len([item for item in relative if item not in metadata]) != 909
    ):
        raise ValueError("Keil-Delitzsch oracle metadata/chapter member split drifted")
    root = (source_manifest.repository_root / _SOURCE_PREFIX.removesuffix("/")).resolve(
        strict=True
    )
    actual = {
        item.relative_to(root).as_posix() for item in root.rglob("*") if item.is_file()
    }
    if actual != set(relative):
        raise ValueError(
            "Keil-Delitzsch oracle detected an unbound or missing retained member"
        )
    for member in members:
        content = source_manifest.authority_path(str(member["name"])).read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError(
                f"Keil-Delitzsch oracle source bytes drifted at {member['relative_path']}"
            )
    return tuple(members)


def _resolve_pointer(value: object, pointer: str) -> object:
    current = value
    for token in pointer.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError(
                f"Keil-Delitzsch structure inventory pointer escaped carrier: {pointer}"
            )
    return current


def _load_structure_inventory(
    source_manifest: SourceManifest,
    members: tuple[dict[str, object], ...],
) -> tuple[
    dict[tuple[str, str], dict[str, object]],
    set[tuple[str, str]],
    dict[str, object],
]:
    inventory_bytes = source_manifest.authority_path(
        _STRUCTURE_INVENTORY_AUTHORITY
    ).read_bytes()
    inventory = _json(inventory_bytes, _STRUCTURE_INVENTORY_AUTHORITY)
    if (
        inventory.get("contract") != _STRUCTURE_INVENTORY_CONTRACT
        or inventory.get("version") != 1
        or inventory.get("work_id") != "keil-delitzsch"
        or inventory.get("source_id")
        != "helloao-keil-delitzsch-complete-retained-json"
        or inventory.get("source_root") != _SOURCE_PREFIX.removesuffix("/")
    ):
        raise ValueError("Keil-Delitzsch structure inventory identity drifted")
    scope = inventory.get("scope")
    entries = inventory.get("entries")
    if not isinstance(scope, dict) or not isinstance(entries, list):
        raise ValueError("Keil-Delitzsch structure inventory shape is invalid")
    paragraph_policy = scope.get("paragraph_policy")
    if (
        not isinstance(paragraph_policy, dict)
        or paragraph_policy.get("contract")
        != "ocd-source-paragraph-segmentation-v1"
        or paragraph_policy.get("delimiter") != "\n\n"
        or paragraph_policy.get("mode") != "split-every-exact-double-newline"
        or paragraph_policy.get("carrier_total_count") != 6_949
        or paragraph_policy.get("carrier_count_with_delimiter") != 594
        or paragraph_policy.get("delimiter_count") != 1_826
    ):
        raise ValueError("Keil-Delitzsch source paragraph policy drifted")
    primary_by_path = {str(item["path"]): item for item in members}
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    rendered_keys: set[tuple[str, str]] = set()
    span_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Keil-Delitzsch structure inventory entry is invalid")
        source_path = entry.get("source_path")
        pointer = entry.get("json_pointer")
        if (
            not isinstance(source_path, str)
            or not source_path.startswith(_SOURCE_PREFIX)
            or not isinstance(pointer, str)
            or not pointer.startswith("/")
        ):
            raise ValueError("Keil-Delitzsch structure inventory carrier is invalid")
        key = (source_path, pointer)
        if key in by_key:
            raise ValueError("Keil-Delitzsch structure inventory duplicates a carrier")
        primary = primary_by_path.get(source_path)
        if primary is None:
            raise ValueError(
                f"Keil-Delitzsch structure inventory references an unbound carrier: {source_path}"
            )
        source_bytes = source_manifest.authority_path(str(primary["name"])).read_bytes()
        if (
            entry.get("source_file_bytes") != len(source_bytes)
            or entry.get("source_file_sha256") != _sha(source_bytes)
        ):
            raise ValueError(
                f"Keil-Delitzsch structure inventory source file drifted: {source_path}"
            )
        carrier_text = _resolve_pointer(_json(source_bytes, source_path), pointer)
        if not isinstance(carrier_text, str):
            raise ValueError(
                f"Keil-Delitzsch structure inventory carrier is not text: {key}"
            )
        if (
            entry.get("carrier_utf8_bytes") != len(carrier_text.encode("utf-8"))
            or entry.get("carrier_codepoint_length") != len(carrier_text)
            or entry.get("carrier_sha256") != _sha(carrier_text.encode("utf-8"))
        ):
            raise ValueError(
                f"Keil-Delitzsch structure inventory carrier text drifted: {key}"
            )
        headings = entry.get("headings")
        if not isinstance(headings, list) or not headings:
            raise ValueError(
                f"Keil-Delitzsch structure inventory headings are missing: {key}"
            )
        previous_end = -1
        for heading in headings:
            if not isinstance(heading, dict):
                raise ValueError("Keil-Delitzsch structure inventory heading is invalid")
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
                or end > len(carrier_text)
                or start < previous_end
                or carrier_text[start:end] != label
            ):
                raise ValueError(
                    f"Keil-Delitzsch structure inventory heading span drifted: {key}"
                )
            expected_before = (
                "start"
                if start == 0
                else "blank-line"
                if carrier_text[start - 2 : start] == "\n\n"
                else "inline"
            )
            expected_after = (
                "blank-line"
                if carrier_text[end : end + 2] == "\n\n"
                else "inline-space-hyphen"
                if carrier_text[end : end + 3] == " - "
                else "end"
                if end == len(carrier_text)
                else "other"
            )
            if before != expected_before or after != expected_after:
                raise ValueError(
                    f"Keil-Delitzsch structure inventory boundary drifted: {key}"
                )
            previous_end = end
            span_count += 1
        by_key[key] = entry
        if entry.get("rendered_carrier") is True:
            rendered_keys.add(key)
    if (
        scope.get("carrier_count") != 85
        or scope.get("rendered_carrier_count") != 4
        or scope.get("evidence_only_carrier_count") != 81
        or scope.get("heading_span_count") != 421
        or len(entries) != 85
        or len(rendered_keys) != 4
        or span_count != 421
    ):
        raise ValueError("Keil-Delitzsch structure inventory census drifted")
    return (
        by_key,
        rendered_keys,
        {
            "authority": _STRUCTURE_INVENTORY_AUTHORITY,
            "sha256": _sha(inventory_bytes),
            "carrier_count": len(entries),
            "rendered_carrier_count": len(rendered_keys),
            "evidence_only_carrier_count": len(entries) - len(rendered_keys),
            "heading_span_count": span_count,
            "paragraph_policy": dict(paragraph_policy),
        },
    )


def _source_digest(members: tuple[dict[str, object], ...]) -> str:
    records = [
        {
            "name": item["name"],
            "path": item["path"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in members
    ]
    return _sha(
        _canonical({"contract": "ocd-source-member-set-v1", "members": records})
    )


def _verify_lineage(source_manifest: SourceManifest, source_digest: str) -> None:
    lineage = source_manifest.record.get("catalog_claim_lineage")
    if (
        not isinstance(lineage, Mapping)
        or lineage.get("contract") != "ocd-catalog-claim-lineage-v1"
        or lineage.get("work_id") != "keil-delitzsch"
        or lineage.get("retained_source_sha256") != source_digest
    ):
        raise ValueError("Keil-Delitzsch oracle catalog lineage binding drifted")
    claims = lineage.get("claims")
    if (
        not isinstance(claims, tuple)
        or lineage.get("claim_count") != 38
        or len(claims) != 38
    ):
        raise ValueError("Keil-Delitzsch oracle catalog claim count drifted")
    rows: list[tuple[str, str]] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("Keil-Delitzsch oracle catalog claim is malformed")
        path = claim.get("source_path")
        digest = claim.get("legacy_source_sha256")
        if (
            not isinstance(path, str)
            or not path.startswith("commentaries/keil-delitzsch/")
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("Keil-Delitzsch oracle catalog claim is malformed")
        rows.append((path, digest))
    if rows != sorted(rows) or len({path for path, _ in rows}) != 38:
        raise ValueError(
            "Keil-Delitzsch oracle catalog claims are reordered or duplicated"
        )


def _load_retained(
    source_manifest: SourceManifest, members: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    by_relative = {str(item["relative_path"]): item for item in members}

    def load(relative: str) -> dict[str, object]:
        member = by_relative.get(relative)
        if member is None:
            raise ValueError(f"Keil-Delitzsch oracle manifest omits {relative}")
        content = source_manifest.authority_path(str(member["name"])).read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError(
                f"Keil-Delitzsch oracle retained bytes drifted at {relative}"
            )
        return _json(content, relative)

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("Keil-Delitzsch oracle books.json shape is invalid")
    if set(commentary) != _COMMENTARY_KEYS:
        raise ValueError("Keil-Delitzsch oracle commentary metadata keys drifted")
    if set(profiles_record) != {"commentary", "profiles"}:
        raise ValueError("Keil-Delitzsch oracle profiles.json keys drifted")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError(
            "Keil-Delitzsch oracle profiles metadata disagrees with books metadata"
        )
    expected_commentary = {
        "id": "keil-delitzsch",
        "name": "Carl Friedrich Keil and Franz Delitzsch Old Testament Commentary",
        "englishName": "Carl Friedrich Keil and Franz Delitzsch Old Testament Commentary",
        "language": "eng",
        "textDirection": "rtl",
        "licenseUrl": "https://creativecommons.org/publicdomain/mark/1.0/",
        "numberOfBooks": 39,
        "totalNumberOfChapters": 909,
        "totalNumberOfVerses": 6_516,
        "totalNumberOfProfiles": 0,
    }
    if any(commentary.get(key) != value for key, value in expected_commentary.items()):
        raise ValueError(
            "Keil-Delitzsch oracle retained commentary identity/census drifted"
        )
    if len(books) != 39:
        raise ValueError("Keil-Delitzsch oracle did not find exactly 39 books")

    chapters: list[dict[str, object]] = []
    covered = {"books.json", "profiles.json"}
    chapter_paths_by_book: dict[str, list[tuple[int, str]]] = {}
    for relative in by_relative:
        if relative in covered:
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            raise ValueError(f"Keil-Delitzsch oracle chapter path drifted: {relative}")
        try:
            number = int(parts[1].removesuffix(".json"))
        except ValueError as exc:
            raise ValueError(
                f"Keil-Delitzsch oracle chapter path drifted: {relative}"
            ) from exc
        chapter_paths_by_book.setdefault(parts[0], []).append((number, relative))
    previous_book_order = 0
    for book_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict) or set(raw_book) != _BOOK_KEYS:
            raise ValueError(
                f"Keil-Delitzsch oracle book metadata drifted at ordinal {book_ordinal}"
            )
        book_id = raw_book.get("id")
        chapter_count = raw_book.get("numberOfChapters")
        order = raw_book.get("order")
        if (
            not isinstance(book_id, str)
            or type(chapter_count) is not int
            or type(order) is not int
            or order <= previous_book_order
            or raw_book.get("commentaryId") != commentary["id"]
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                f"Keil-Delitzsch oracle book order/range drifted at {book_id!r}"
            )
        previous_book_order = order
        book_paths = sorted(chapter_paths_by_book.pop(book_id, []))
        expected_gaps = {
            "EXO": [37, 38],
            "NUM": [17],
            "JOB": [25],
            "PSA": [101, 117, 131, 133],
            "EZK": [4, 5, 36],
        }.get(book_id, [])
        first = raw_book.get("firstChapterNumber")
        last = raw_book.get("lastChapterNumber")
        if chapter_count == 0:
            if book_id != "SNG" or first is not None or last is not None or book_paths:
                raise ValueError(
                    "Keil-Delitzsch oracle zero-chapter Song of Solomon drifted"
                )
        elif (
            first != 1
            or not isinstance(last, int)
            or len(book_paths) != chapter_count
            or [
                number
                for number in range(first, last + 1)
                if number not in {item[0] for item in book_paths}
            ]
            != expected_gaps
        ):
            raise ValueError(
                f"Keil-Delitzsch oracle chapter range drifted at {book_id}"
            )
        for chapter_number, relative in book_paths:
            envelope = load(relative)
            covered.add(relative)
            chapter = envelope.get("chapter")
            embedded_book = envelope.get("book")
            expected_embedded_variant_paths = {
                *(f"HOS/{item}.json" for item in range(1, 15)),
                *(f"JOL/{item}.json" for item in range(1, 4)),
            }
            embedded_differences = (
                {
                    key
                    for key in _BOOK_KEYS
                    if isinstance(embedded_book, dict)
                    and embedded_book.get(key) != raw_book.get(key)
                }
                if isinstance(embedded_book, dict)
                else set()
            )
            if (
                set(envelope) != _ENVELOPE_KEYS
                or not isinstance(embedded_book, dict)
                or set(embedded_book) != _BOOK_KEYS
                or embedded_book.get("id") != book_id
                or embedded_differences
                != (
                    {"introduction"}
                    if relative in expected_embedded_variant_paths
                    else set()
                )
                or envelope.get("commentary") != commentary
                or not isinstance(chapter, dict)
                or set(chapter) not in (_CHAPTER_WITH_INTRO, _CHAPTER_WITHOUT_INTRO)
                or chapter.get("number") != chapter_number
                or not isinstance(chapter.get("content"), list)
                or type(envelope.get("numberOfVerses")) is not int
                or envelope["numberOfVerses"] != len(chapter["content"])
                or not isinstance(envelope.get("thisChapterLink"), str)
                or (
                    envelope.get("previousChapterApiLink") is not None
                    and not isinstance(envelope.get("previousChapterApiLink"), str)
                )
                or (
                    envelope.get("nextChapterApiLink") is not None
                    and not isinstance(envelope.get("nextChapterApiLink"), str)
                )
            ):
                raise ValueError(
                    f"Keil-Delitzsch oracle chapter envelope drifted at {relative}"
                )
            for ordinal, occurrence in enumerate(chapter["content"], start=1):
                if (
                    not isinstance(occurrence, dict)
                    or set(occurrence) != {"content", "number", "type"}
                    or occurrence.get("type") != "verse"
                    or type(occurrence.get("number")) is not int
                    or not isinstance(occurrence.get("content"), list)
                    or len(occurrence["content"]) != 1
                    or not isinstance(occurrence["content"][0], str)
                ):
                    raise ValueError(
                        f"Keil-Delitzsch oracle occurrence drifted at {relative}#{ordinal}"
                    )
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "embedded_book": embedded_book,
                    "chapter": chapter,
                    "envelope": envelope,
                }
            )
    if chapter_paths_by_book or covered != set(by_relative) or len(chapters) != 909:
        raise ValueError("Keil-Delitzsch oracle retained member coverage is incomplete")
    for index, item in enumerate(chapters):
        relative = str(item["relative_path"])
        envelope = item["envelope"]
        assert isinstance(envelope, dict)
        expected_self = f"/api/c/keil-delitzsch/{relative}"
        expected_previous = (
            None
            if index == 0
            else f"/api/c/keil-delitzsch/{chapters[index - 1]['relative_path']}"
        )
        expected_next = (
            None
            if index + 1 == len(chapters)
            else f"/api/c/keil-delitzsch/{chapters[index + 1]['relative_path']}"
        )
        if (
            envelope["thisChapterLink"] != expected_self
            or envelope["previousChapterApiLink"] != expected_previous
            or envelope["nextChapterApiLink"] != expected_next
        ):
            raise ValueError(f"Keil-Delitzsch oracle navigation drifted at {relative}")
    return books_record, profiles_record, chapters


def _content_digests(
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
) -> dict[str, str]:
    books = books_record["books"]
    assert isinstance(books, list)
    book_order = [item["id"] for item in books if isinstance(item, dict)]
    book_intros = [
        [item["id"], _sha(str(item["introduction"]).encode("utf-8"))]
        for item in books
        if isinstance(item, dict)
    ]
    chapter_order: list[list[object]] = []
    chapter_intros: list[list[object]] = []
    envelopes: list[list[object]] = []
    embedded_books: list[list[object]] = []
    embedded_commentaries: list[list[object]] = []
    occurrences: list[list[object]] = []
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        envelope = item["envelope"]
        embedded_book = item["embedded_book"]
        assert (
            isinstance(relative, str)
            and isinstance(chapter, dict)
            and isinstance(envelope, dict)
            and isinstance(embedded_book, dict)
        )
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
        envelopes.append(
            [
                relative,
                envelope["previousChapterApiLink"],
                envelope["nextChapterApiLink"],
                envelope["thisChapterLink"],
                envelope["numberOfVerses"],
            ]
        )
        embedded_books.append([relative, embedded_book])
        embedded_commentaries.append([relative, envelope["commentary"]])
        content = chapter["content"]
        assert isinstance(content, list)
        for ordinal, occurrence in enumerate(content, start=1):
            assert isinstance(occurrence, dict)
            occurrences.append(
                [
                    relative,
                    ordinal,
                    occurrence["type"],
                    occurrence["number"],
                    _sha(str(occurrence["content"][0]).encode("utf-8")),
                ]
            )
    return {
        "commentary_metadata_sha256": _sha(_canonical(books_record["commentary"])),
        "profiles_metadata_sha256": _sha(_canonical(profiles_record)),
        "book_order_sha256": _sha(_canonical(book_order)),
        "book_metadata_sha256": _sha(_canonical(books)),
        "book_introductions_sha256": _sha(_canonical(book_intros)),
        "chapter_order_sha256": _sha(_canonical(chapter_order)),
        "chapter_envelopes_sha256": _sha(_canonical(envelopes)),
        "chapter_embedded_books_sha256": _sha(_canonical(embedded_books)),
        "chapter_embedded_commentaries_sha256": _sha(_canonical(embedded_commentaries)),
        "chapter_introductions_sha256": _sha(_canonical(chapter_intros)),
        "commentary_occurrences_sha256": _sha(_canonical(occurrences)),
    }


def _object_key_order_census(
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
) -> dict[str, object]:
    counts: dict[tuple[str, ...], int] = {}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            order = tuple(value)
            counts[order] = counts.get(order, 0) + 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(books_record)
    walk(profiles_record)
    for item in chapters:
        walk(item["envelope"])
    object_count = sum(counts.values())
    if object_count != 10_195 or len(counts) != 8:
        raise ValueError("Keil-Delitzsch oracle JSON object/key-order census drifted")
    return {
        "object_count": object_count,
        "variant_count": len(counts),
        "variants": [
            {"keys": list(keys), "count": count}
            for keys, count in sorted(
                counts.items(), key=lambda item: (len(item[0]), item[0])
            )
        ],
    }


def _anomalies(chapters: list[dict[str, object]]) -> dict[str, object]:
    nonmonotonic: list[str] = []
    duplicates: list[dict[str, object]] = []
    absent: list[str] = []
    null_previous: list[str] = []
    null_next: list[str] = []
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        envelope = item["envelope"]
        assert (
            isinstance(relative, str)
            and isinstance(chapter, dict)
            and isinstance(envelope, dict)
        )
        if "introduction" not in chapter:
            absent.append(relative)
        if envelope["previousChapterApiLink"] is None:
            null_previous.append(relative)
        if envelope["nextChapterApiLink"] is None:
            null_next.append(relative)
        content = chapter["content"]
        assert isinstance(content, list)
        numbers = [item["number"] for item in content if isinstance(item, dict)]
        if numbers != sorted(numbers):
            nonmonotonic.append(relative)
        counts: dict[int, int] = {}
        for number in numbers:
            counts[number] = counts.get(number, 0) + 1
        duplicates.extend(
            {"path": relative, "number": number, "count": count}
            for number, count in sorted(counts.items())
            if count > 1
        )
    return {
        "nonmonotonic_occurrence_paths": nonmonotonic,
        "duplicate_occurrence_numbers": duplicates,
        "chapter_introduction_absent_paths": absent,
        "null_previous_chapter_link_paths": null_previous,
        "null_next_chapter_link_paths": null_next,
        "retained_text_direction": "rtl",
    }


def _verify_profile_policy(
    profile: dict[str, object], policy: dict[str, object]
) -> None:
    expected_counts = {
        "source_members": 911,
        "source_bytes": 47_103_116,
        "books": 39,
        "chapters": 909,
        "commentary_occurrences": 6_516,
        "book_introductions": 39,
        "chapter_introductions_present": 394,
        "chapter_introductions_absent": 515,
    }
    expected_ids = [
        "keil-delitzsch-retained-vs-configured-title",
        "keil-delitzsch-config-cc0-vs-retained-pdm",
        "keil-delitzsch-configured-source-endpoint",
        "keil-delitzsch-retained-rtl-anomaly",
        "keil-delitzsch-edition-and-original-date",
    ]
    scope = profile.get("scope")
    if (
        profile.get("contract") != "ocd-helloao-keil-delitzsch-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or profile.get("work_id") != "keil-delitzsch"
        or not isinstance(scope, dict)
        or scope.get("member_count") != 911
        or scope.get("total_bytes") != 47_103_116
        or scope.get("book_count") != 39
        or scope.get("chapter_count") != 909
        or scope.get("commentary_occurrence_count") != 6_516
        or scope.get("chapter_introduction_absent_count") != 515
        or scope.get("null_previous_link_paths") != ["GEN/1.json"]
        or scope.get("null_next_link_paths") != ["MAL/4.json"]
        or scope.get("nonmonotonic_chapters")
        != ["JDG/12.json", "2KI/10.json", "ISA/38.json"]
        or scope.get("duplicate_occurrence_numbers")
        != [{"path": "ISA/38.json", "number": 21, "count": 2}]
        or policy.get("contract") != "ocd-helloao-keil-delitzsch-validation-policy-v1"
        or policy.get("required_counts") != expected_counts
        or policy.get("required_unresolved_ids") != expected_ids
        or _STRUCTURE_POLICY_CHECK not in policy.get("required_checks", [])
    ):
        raise ValueError("Keil-Delitzsch oracle profile or validation policy drifted")


def _expected_accountability(
    members: tuple[dict[str, object], ...],
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
    structure_summary: dict[str, object],
) -> dict[str, object]:
    books = books_record["books"]
    assert isinstance(books, list)
    present = sum(
        isinstance(item["chapter"], dict) and "introduction" in item["chapter"]
        for item in chapters
    )
    occurrences = sum(
        len(item["chapter"]["content"])
        for item in chapters
        if isinstance(item["chapter"], dict)
        and isinstance(item["chapter"].get("content"), list)
    )
    expected_members = [
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
        for item in members
    ]
    return {
        "contract": "ocd-helloao-keil-delitzsch-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "source_root": _SOURCE_PREFIX.removesuffix("/"),
        "source_member_set_sha256": _source_digest(members),
        "member_count": 911,
        "total_bytes": 47_103_116,
        "included_member_count": 911,
        "excluded_member_count": 0,
        "members": expected_members,
        "excluded_members": [],
        "source_shapes": {
            "collection_metadata_members": ["books.json", "profiles.json"],
            "commentary_metadata_keys": sorted(_COMMENTARY_KEYS),
            "book_metadata_keys": sorted(_BOOK_KEYS),
            "chapter_envelope_keys": sorted(_ENVELOPE_KEYS),
            "chapter_keys_with_introduction": sorted(_CHAPTER_WITH_INTRO),
            "chapter_keys_without_introduction": sorted(_CHAPTER_WITHOUT_INTRO),
            "occurrence_keys": ["content", "number", "type"],
            "occurrence_content_shape": "list[str] of length 1",
            "object_key_order_census": _object_key_order_census(
                books_record, profiles_record, chapters
            ),
        },
        "census": {
            "books": 39,
            "chapters": 909,
            "commentary_occurrences": occurrences,
            "book_introductions": 39,
            "chapter_introductions_present": present,
            "chapter_introductions_absent": 909 - present,
            "profiles": len(profiles_record["profiles"]),
        },
        "content_digests": _content_digests(books_record, profiles_record, chapters),
        "meaningful_structure": structure_summary,
        "anomalies": _anomalies(chapters),
        "retained_metadata": books_record["commentary"],
        "profiles_metadata": profiles_record,
    }


def _element_children(node: etree._Element) -> list[etree._Element]:
    children = list(node)
    if any(not isinstance(child.tag, str) for child in children):
        raise ValueError(
            "Keil-Delitzsch TEI contains an unaccounted comment or instruction"
        )
    return children


def _assert_element(
    node: etree._Element,
    name: str,
    attributes: Mapping[str, str],
    text: str | None,
    label: str,
) -> None:
    observed = {
        (
            "xml:id"
            if key == f"{{{_XML_NS}}}id"
            else "xml:lang"
            if key == f"{{{_XML_NS}}}lang"
            else "xml:space"
            if key == f"{{{_XML_NS}}}space"
            else key
        ): value
        for key, value in node.attrib.items()
    }
    if (
        etree.QName(node).localname != name
        or etree.QName(node).namespace != _TEI_NS
        or observed != dict(attributes)
        or node.text != text
        or node.tail is not None
    ):
        raise ValueError(f"Keil-Delitzsch TEI {label} drifted")


def _assert_leaf(
    node: etree._Element,
    name: str,
    attributes: Mapping[str, str],
    text: str | None,
    label: str,
) -> None:
    _assert_element(node, name, attributes, text, label)
    if len(node) != 0:
        raise ValueError(f"Keil-Delitzsch TEI {label} contains unaccounted descendants")


def _paragraph_segments(text: str) -> list[str]:
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
    return segments


def _assert_paragraphs(
    parent: etree._Element,
    source_text: str,
    label: str,
) -> None:
    expected = _paragraph_segments(source_text)
    observed = _element_children(parent)
    if len(observed) != len(expected):
        raise ValueError(f"Keil-Delitzsch paragraph segmentation drifted: {label}")
    for ordinal, (node, segment) in enumerate(zip(observed, expected, strict=True), 1):
        attributes = (
            {"ana": "empty-string"}
            if segment == ""
            else {"xml:space": "preserve"}
            if not segment.strip()
            else {}
        )
        _assert_leaf(
            node,
            "p",
            attributes,
            None if segment == "" else segment,
            f"{label}/paragraph-{ordinal}",
        )


def _assert_source_text(
    parent: etree._Element,
    source_text: str,
    inventory_entry: dict[str, object] | None,
    label: str,
) -> None:
    headings = [] if inventory_entry is None else inventory_entry.get("headings")
    if not isinstance(headings, list) or not headings:
        _assert_paragraphs(parent, source_text, label)
        return
    parent_id = parent.get(f"{{{_XML_NS}}}id")
    if not isinstance(parent_id, str):
        raise ValueError(f"Keil-Delitzsch structured carrier has no xml:id: {label}")
    observed = _element_children(parent)
    position = 0
    cursor = 0
    for ordinal, heading in enumerate(headings, start=1):
        if not isinstance(heading, dict):
            raise ValueError(f"Keil-Delitzsch structure heading is invalid: {label}")
        start = int(heading["start"])
        end = int(heading["end"])
        heading_text = str(heading["text"])
        if (
            start < cursor
            or source_text[start:end] != heading_text
            or source_text[start - 2 : start] != "\n\n"
            if start > 0
            else False
        ):
            raise ValueError(f"Keil-Delitzsch structure span drifted: {label}")
        prefix = source_text[cursor:start]
        prefix_segments = _paragraph_segments(prefix) if prefix else []
        for segment in prefix_segments:
            if position >= len(observed):
                raise ValueError(f"Keil-Delitzsch structure omitted prefix: {label}")
            node = observed[position]
            attributes = (
                {"ana": "empty-string"}
                if segment == ""
                else {"xml:space": "preserve"}
                if not segment.strip()
                else {}
            )
            _assert_leaf(
                node,
                "p",
                attributes,
                None if segment == "" else segment,
                f"{label}/prefix",
            )
            position += 1
        if position >= len(observed):
            raise ValueError(f"Keil-Delitzsch structure omitted heading: {label}")
        section = observed[position]
        _assert_element(
            section,
            "div",
            {
                "type": "commentary-section",
                "xml:id": f"{parent_id}-section-{ordinal:03d}",
            },
            None,
            f"{label}/section-{ordinal}",
        )
        section_children = _element_children(section)
        if not section_children:
            raise ValueError(f"Keil-Delitzsch section has no head: {label}")
        _assert_leaf(
            section_children[0],
            "head",
            {},
            heading_text,
            f"{label}/section-{ordinal}/head",
        )
        next_start = (
            int(headings[ordinal]["start"])
            if ordinal < len(headings)
            else len(source_text)
        )
        remainder = source_text[end:next_start]
        remainder_segments = _paragraph_segments(remainder) if remainder else []
        if len(section_children) - 1 != len(remainder_segments):
            raise ValueError(
                f"Keil-Delitzsch section paragraph count drifted: {label}/section-{ordinal}"
            )
        for segment, node in zip(
            remainder_segments, section_children[1:], strict=True
        ):
            attributes = (
                {"ana": "empty-string"}
                if segment == ""
                else {"xml:space": "preserve"}
                if not segment.strip()
                else {}
            )
            _assert_leaf(
                node,
                "p",
                attributes,
                None if segment == "" else segment,
                f"{label}/section-{ordinal}/paragraph",
            )
        position += 1
        cursor = next_start
    if cursor != len(source_text) or position != len(observed):
        raise ValueError(f"Keil-Delitzsch structured carrier has unaccounted text: {label}")


def _header_element(
    name: str,
    attributes: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    normalized = {
        f"{{{_XML_NS}}}space" if key == "xml:space" else key: value
        for key, value in (attributes or {}).items()
    }
    element = etree.Element(f"{{{_TEI_NS}}}{name}", normalized)
    element.text = text
    return element


def _expected_header(
    commentary: dict[str, object],
    profiles_record: dict[str, object],
    config: dict[str, object],
    source_digest: str,
) -> etree._Element:
    if (
        config.get("license") != "cc0-1.0"
        or config.get("helloao_license")
        != "PDM 1.0 (https://creativecommons.org/publicdomain/mark/1.0/)"
    ):
        raise ValueError("Keil-Delitzsch source-config rights authority drifted")
    header = _header_element("teiHeader")
    file_desc = _header_element("fileDesc")
    title_stmt = _header_element("titleStmt")
    title_stmt.append(_header_element("title", text=str(commentary["name"])))
    title_stmt.append(
        _header_element("author", text="Carl Friedrich Keil and Franz Delitzsch")
    )
    file_desc.append(title_stmt)
    publication_stmt = _header_element("publicationStmt")
    publication_stmt.append(_header_element("publisher", text="Open Christian Data"))
    availability = _header_element("availability", {"status": "restricted"})
    availability.append(
        _header_element(
            "p",
            text=(
                "Retained HelloAO metadata identifies the Public Domain Mark 1.0; "
                "the source config's CC0 label is recorded as drift and is not substituted."
            ),
        )
    )
    publication_stmt.append(availability)
    file_desc.append(publication_stmt)
    notes_stmt = _header_element("notesStmt")
    notes_stmt.append(
        _header_element(
            "note",
            {"type": "commentary-metadata", "xml:space": "preserve"},
            json.dumps(commentary, ensure_ascii=False, separators=(",", ":")),
        )
    )
    notes_stmt.append(
        _header_element(
            "note",
            {"type": "profiles-metadata", "xml:space": "preserve"},
            json.dumps(profiles_record, ensure_ascii=False, separators=(",", ":")),
        )
    )
    notes_stmt.append(
        _header_element("note", {"type": "source-member-set-sha256"}, source_digest)
    )
    notes_stmt.append(
        _header_element("note", {"type": "retained-text-direction"}, "rtl")
    )
    file_desc.append(notes_stmt)
    source_desc = _header_element("sourceDesc")
    bibl = _header_element("bibl")
    bibl.append(
        _header_element("ptr", {"target": str(commentary["listOfBooksApiLink"])})
    )
    bibl.append(
        _header_element("ptr", {"target": str(commentary["listOfProfilesApiLink"])})
    )
    bibl.append(_header_element("idno", {"type": "sha256"}, source_digest))
    bibl.append(
        _header_element(
            "note", {"type": "source-witness"}, "retained HelloAO JSON snapshot"
        )
    )
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


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
        raise ValueError(f"Keil-Delitzsch TEI {label} drifted")
    for index, (observed_child, expected_child) in enumerate(
        zip(observed, expected, strict=True), start=1
    ):
        _assert_exact_tree(observed_child, expected_child, f"{label}/{index}")


def _verify_namespace_declarations(tei_bytes: bytes) -> None:
    element_ordinal = 0

    def start_element(_name: str, attributes: dict[str, str]) -> None:
        nonlocal element_ordinal
        element_ordinal += 1
        observed = {
            name: value
            for name, value in attributes.items()
            if name == "xmlns" or name.startswith("xmlns:")
        }
        expected = {"xmlns": _TEI_NS} if element_ordinal == 1 else {}
        if observed != expected:
            raise ValueError(
                "Keil-Delitzsch TEI namespace declarations drifted at "
                f"element {element_ordinal}"
            )

    parser = expat.ParserCreate()
    parser.StartElementHandler = start_element
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(tei_bytes, True)
    except expat.ExpatError as exc:
        raise ValueError(
            "Keil-Delitzsch candidate is not safe well-formed XML"
        ) from exc


def _verify_tei(
    tei_bytes: bytes,
    source_manifest: SourceManifest,
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
    source_digest: str,
    structure_by_key: dict[tuple[str, str], dict[str, object]],
    rendered_structure_keys: set[tuple[str, str]],
) -> None:
    if not tei_bytes.startswith(_CANONICAL_XML_DECLARATION):
        raise ValueError("Keil-Delitzsch TEI XML declaration drifted")
    document = tei_bytes.removeprefix(_CANONICAL_XML_DECLARATION)
    if not document.startswith(b"<TEI") or not document.endswith(b"</TEI>\n"):
        raise ValueError("Keil-Delitzsch TEI lexical document shell drifted")
    try:
        tree = etree.parse(
            BytesIO(tei_bytes),
            etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                huge_tree=True,
                remove_blank_text=True,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError(
            "Keil-Delitzsch candidate is not safe well-formed XML"
        ) from exc
    root = tree.getroot()
    if tree.docinfo.doctype:
        raise ValueError("Keil-Delitzsch TEI contains an unaccounted document type")
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError(
            "Keil-Delitzsch TEI contains an unaccounted document-level node"
        )
    _verify_namespace_declarations(tei_bytes)
    ns = {"tei": _TEI_NS}
    _assert_element(root, "TEI", {}, None, "root")
    root_children = _element_children(root)
    if [etree.QName(item).localname for item in root_children] != ["teiHeader", "text"]:
        raise ValueError("Keil-Delitzsch TEI root child order drifted")
    commentary = books_record["commentary"]
    books = books_record["books"]
    assert isinstance(commentary, dict) and isinstance(books, list)
    config = _json(
        source_manifest.authority_path("source-config").read_bytes(), "source config"
    )
    _assert_exact_tree(
        root_children[0],
        _expected_header(commentary, profiles_record, config, source_digest),
        "header",
    )
    expected_rights = (
        "Retained HelloAO metadata identifies the Public Domain Mark 1.0; "
        "the source config's CC0 label is recorded as drift and is not substituted."
    )
    expected_header = {
        "title": commentary["name"],
        "author": "Carl Friedrich Keil and Franz Delitzsch",
        "publisher": "Open Christian Data",
        "availability": "restricted",
        "rights": expected_rights,
        "source": commentary["listOfBooksApiLink"],
        "digest": source_digest,
        "witness": "retained HelloAO JSON snapshot",
    }
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
            "string(tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:ptr[1]/@target)",
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
    if observed_header != expected_header:
        raise ValueError("Keil-Delitzsch TEI title, rights, or source metadata drifted")
    notes = root.xpath(
        "tei:teiHeader/tei:fileDesc/tei:notesStmt/tei:note", namespaces=ns
    )
    expected_notes = [
        (
            "commentary-metadata",
            json.dumps(commentary, ensure_ascii=False, separators=(",", ":")),
        ),
        (
            "profiles-metadata",
            json.dumps(profiles_record, ensure_ascii=False, separators=(",", ":")),
        ),
        ("source-member-set-sha256", source_digest),
        ("retained-text-direction", "rtl"),
    ]
    if [(str(node.get("type")), node.text or "") for node in notes] != expected_notes:
        raise ValueError("Keil-Delitzsch retained metadata notes drifted")
    bibl_children = root.xpath(
        "tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/*", namespaces=ns
    )
    bibl_shape = [
        (etree.QName(item).localname, item.get("type"), item.get("target"), item.text)
        for item in bibl_children
    ]
    if bibl_shape != [
        ("ptr", None, commentary["listOfBooksApiLink"], None),
        ("ptr", None, commentary["listOfProfilesApiLink"], None),
        ("idno", "sha256", None, source_digest),
        ("note", "source-witness", None, "retained HelloAO JSON snapshot"),
    ]:
        raise ValueError("Keil-Delitzsch TEI source description drifted")
    text_node = root_children[1]
    _assert_element(text_node, "text", {"xml:lang": "eng"}, None, "text")
    body_children = _element_children(text_node)
    if len(body_children) != 1:
        raise ValueError("Keil-Delitzsch TEI text/body structure drifted")
    body = body_children[0]
    _assert_element(body, "body", {}, None, "body")
    book_nodes = _element_children(body)
    if len(book_nodes) != 39:
        raise ValueError("Keil-Delitzsch TEI book count drifted")
    by_book: dict[str, list[dict[str, object]]] = {}
    for item in chapters:
        raw_book = item["book"]
        assert isinstance(raw_book, dict)
        by_book.setdefault(str(raw_book["id"]), []).append(item)
    ids: set[str] = set()
    occurrence_count = 0
    chapter_intro_count = 0
    book_intro_count = 0
    used_structure_keys: set[tuple[str, str]] = set()
    for book_index, (raw_book, book_node) in enumerate(zip(books, book_nodes, strict=True)):
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
        book_id_value = book_node.get(f"{{{_XML_NS}}}id")
        if not isinstance(book_id_value, str) or book_id_value in ids:
            raise ValueError("Keil-Delitzsch TEI duplicate book xml:id")
        ids.add(book_id_value)
        children = _element_children(book_node)
        expected_chapters = by_book.get(book_id, [])
        if len(children) != 4 + len(expected_chapters):
            raise ValueError(
                f"Keil-Delitzsch TEI book child count drifted for {book_id}"
            )
        _assert_leaf(
            children[0], "head", {}, str(raw_book["name"]), f"book {book_id} name"
        )
        _assert_leaf(
            children[1],
            "note",
            {"type": "common-name"},
            str(raw_book["commonName"]),
            f"book {book_id} common name",
        )
        _assert_leaf(
            children[2],
            "note",
            {"type": "book-metadata", "xml:space": "preserve"},
            json.dumps(raw_book, ensure_ascii=False, separators=(",", ":")),
            f"book {book_id} metadata",
        )
        _assert_element(
            children[3],
            "div",
            {"type": "book-introduction", "xml:id": f"book-intro-{book_id}"},
            None,
            f"book {book_id} introduction",
        )
        book_intro_count += 1
        book_key = (_SOURCE_PREFIX + "books.json", f"/books/{book_index}/introduction")
        book_entry = structure_by_key.get(book_key)
        if book_entry is not None:
            used_structure_keys.add(book_key)
        _assert_source_text(
            children[3],
            str(raw_book["introduction"]),
            book_entry,
            f"book {book_id} introduction text",
        )
        for source_item, chapter_node in zip(
            expected_chapters, children[4:], strict=True
        ):
            chapter = source_item["chapter"]
            envelope = source_item["envelope"]
            relative = source_item["relative_path"]
            assert (
                isinstance(chapter, dict)
                and isinstance(envelope, dict)
                and isinstance(relative, str)
            )
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
            chapter_id = chapter_node.get(f"{{{_XML_NS}}}id")
            if not isinstance(chapter_id, str) or chapter_id in ids:
                raise ValueError(
                    f"Keil-Delitzsch TEI duplicate chapter xml:id at {relative}"
                )
            ids.add(chapter_id)
            chapter_children = _element_children(chapter_node)
            intro_offset = 4
            expected_intro = "introduction" in chapter
            if expected_intro:
                if (
                    not chapter_children
                    or chapter_children[0].get("type") != "number-of-verses"
                ):
                    raise ValueError(
                        f"Keil-Delitzsch TEI omitted envelope metadata at {relative}"
                    )
            if len(chapter_children) < 3:
                raise ValueError(
                    f"Keil-Delitzsch TEI chapter is missing envelope nodes at {relative}"
                )
            _assert_leaf(
                chapter_children[0],
                "note",
                {"type": "number-of-verses"},
                str(envelope["numberOfVerses"]),
                f"chapter count {relative}",
            )
            for offset, (subtype, value) in enumerate(
                [
                    ("previous", envelope["previousChapterApiLink"]),
                    ("next", envelope["nextChapterApiLink"]),
                    ("this", envelope["thisChapterLink"]),
                ],
                start=1,
            ):
                attrs = {"type": "chapter-link", "subtype": subtype}
                text = value if isinstance(value, str) else None
                if value is None:
                    attrs["ana"] = "null"
                _assert_leaf(
                    chapter_children[offset],
                    "note",
                    attrs,
                    text,
                    f"chapter {subtype} link {relative}",
                )
            if expected_intro:
                intro = chapter_children[4]
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
                intro_id = intro.get(f"{{{_XML_NS}}}id")
                if not isinstance(intro_id, str) or intro_id in ids:
                    raise ValueError(
                        f"Keil-Delitzsch TEI duplicate chapter-intro xml:id at {relative}"
                    )
                ids.add(intro_id)
                _assert_source_text(
                    intro,
                    str(chapter["introduction"]),
                    None,
                    f"chapter introduction text {relative}",
                )
                chapter_intro_count += 1
                intro_offset = 5
            content = chapter["content"]
            assert isinstance(content, list)
            occurrences = chapter_children[intro_offset:]
            if len(occurrences) != len(content):
                raise ValueError(
                    f"Keil-Delitzsch TEI occurrence omission/invention at {relative}"
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
                        "xml:id": f"commentary-{book_id}-{number:03d}-{ordinal:05d}",
                    },
                    None,
                    f"commentary occurrence {relative}#{ordinal}",
                )
                occurrence_id = observed.get(f"{{{_XML_NS}}}id")
                if not isinstance(occurrence_id, str) or occurrence_id in ids:
                    raise ValueError(
                        f"Keil-Delitzsch TEI duplicate occurrence xml:id at {relative}#{ordinal}"
                    )
                ids.add(occurrence_id)
                occurrence_text = str(raw_occurrence["content"][0])
                _assert_source_text(
                    observed,
                    occurrence_text,
                    None,
                    f"commentary text {relative}#{ordinal}",
                )
                occurrence_count += 1
    if used_structure_keys != rendered_structure_keys:
        missing = sorted(rendered_structure_keys - used_structure_keys)
        extra = sorted(used_structure_keys - rendered_structure_keys)
        raise ValueError(
            "Keil-Delitzsch rendered structure carrier census drifted: "
            f"missing={missing!r}, extra={extra!r}"
        )
    if (book_intro_count, chapter_intro_count, occurrence_count) != (39, 394, 6_516):
        raise ValueError("Keil-Delitzsch TEI final content census drifted")
    xsd_path = source_manifest.authority_path("tei-p5-xsd")
    try:
        schema = etree.XMLSchema(etree.parse(str(xsd_path)))
        schema.assertValid(root)
    except (OSError, etree.XMLSyntaxError, etree.DocumentInvalid) as exc:
        raise ValueError("Keil-Delitzsch candidate fails TEI P5 validation") from exc


def _expected_provenance(
    source_manifest: SourceManifest,
    commentary: dict[str, object],
    config: dict[str, object],
    source_digest: str,
) -> dict[str, object]:
    return {
        "contract": "ocd-helloao-keil-delitzsch-candidate-provenance-v1",
        "status": "nonaccepted",
        "identity": {
            "work_id": "keil-delitzsch",
            "retained_title": commentary["name"],
            "configured_title": config.get("title"),
            "author": "Carl Friedrich Keil and Franz Delitzsch",
            "author_evidence": "retained commentary name and website identify Carl Friedrich Keil and Franz Delitzsch",
            "edition": None,
            "original_publication_year": None,
            "digital_witness": "retained HelloAO JSON snapshot",
        },
        "scope": {
            "complete_for_retained_witness": True,
            "book_count": 39,
            "chapter_count": 909,
            "commentary_occurrence_count": 6_516,
            "canonical_old_testament_book_set_complete": True,
            "retained_zero_chapter_books": ["SNG"],
            "retained_internal_chapter_gaps": {
                "EXO": [37, 38],
                "NUM": [17],
                "JOB": [25],
                "PSA": [101, 117, 131, 133],
                "EZK": [4, 5, 36],
            },
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


def _expected_unresolved(
    commentary: dict[str, object], config: dict[str, object]
) -> list[dict[str, object]]:
    return [
        {
            "id": "keil-delitzsch-retained-vs-configured-title",
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
            "id": "keil-delitzsch-config-cc0-vs-retained-pdm",
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
            "id": "keil-delitzsch-configured-source-endpoint",
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
            "id": "keil-delitzsch-retained-rtl-anomaly",
            "scope": "work",
            "kind": "editorial",
            "question": "Review the retained rtl direction marker on English commentary.",
            "evidence": {
                "retained_language": commentary["language"],
                "retained_text_direction": commentary["textDirection"],
            },
        },
        {
            "id": "keil-delitzsch-edition-and-original-date",
            "scope": "work",
            "kind": "identity",
            "question": "Identify the edition and original publication date represented by this digital witness.",
            "evidence": {
                "retained_witness": "HelloAO JSON snapshot",
                "configured_original_publication_year": config.get(
                    "original_publication_year"
                ),
                "configured_notes": config.get("notes"),
                "retained_source_date": None,
            },
        },
    ]


def _expected_readme(
    commentary: dict[str, object],
    profiles_record: dict[str, object],
    config: dict[str, object],
    profile: dict[str, object],
    policy: dict[str, object],
    source_digest: str,
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
        or [item["id"] for item in unresolved] != policy.get("required_unresolved_ids")
        or identity.get("retained_license_url") != commentary.get("licenseUrl")
        or identity.get("retained_license_notes") != commentary.get("licenseNotes")
        or identity.get("configured_license") != config.get("license")
        or identity.get("configured_helloao_license") != commentary.get("licenseUrl")
        or config.get("helloao_license")
        != "PDM 1.0 (https://creativecommons.org/publicdomain/mark/1.0/)"
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
    ):
        raise ValueError("Keil-Delitzsch README authority inputs drifted")
    member_count = counts["source_members"]
    total_bytes = counts["source_bytes"]
    book_count = counts["books"]
    chapter_count = counts["chapters"]
    occurrence_count = counts["commentary_occurrences"]
    present_introductions = counts["chapter_introductions_present"]
    absent_introductions = counts["chapter_introductions_absent"]
    absent_introductions_label = str(absent_introductions)
    return f"""# Keil-Delitzsch retained HelloAO source

This candidate is a deterministic, nonaccepted TEI reconstruction of the complete retained
HelloAO JSON witness at `raw/helloao_local/api/c/keil-delitzsch`.

- The retained census is exactly {member_count:,} members and {total_bytes:,} bytes.
- It contains {book_count} books, {chapter_count:,} chapters, and {occurrence_count:,} ordered commentary occurrences.
- All {book_count} book introductions, {present_introductions:,} present chapter introductions, and {absent_introductions_label} absent
  `introduction` properties are accounted for.
- Song of Solomon's complete retained book introduction and book SHA-256 are preserved even
  though it declares zero chapters and has no chapter member.
- Eleven internal chapter numbers are absent across EXO, NUM, JOB, PSA, and EZK. The retained
  paths and exact global navigation links across those gaps are preserved without invention.
- JDG 12, 2KI 10, and ISA 38 have nonmonotonic occurrence numbers. Their order is preserved;
  ISA 38's two distinct number-21 occurrences remain separate.
- The retained English metadata says `textDirection: {identity["retained_text_direction"]}`; that anomaly is preserved and
  localized for human review.
- No Bible or BSB verse text, inferred ranges, modernized wording, or second witness was added.
- The formal retained member-set identity is `{source_digest}`.
- The retained source identifies the Public Domain Mark 1.0 at
  `{config["helloao_license"]}`. The config's `{identity["configured_license"]}` value is recorded as a rights
  question and is not applied.
- A source-attribution ask was not present in the retained metadata; no extra attribution
  README is required by this witness.

The candidate remains `{candidate_model["candidate_status"]}`, `accepted_ir: {candidate_model["accepted_ir"]}`, and `publication: {candidate_model["publication"]}`.
The configured title, endpoint, CC0 label, retained direction marker, and edition/date identity
are surfaced in `unresolved.jsonl`; they require human review and are not silently resolved.
""".encode("utf-8")


def _verify_provenance(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    profile: dict[str, object],
    policy: dict[str, object],
    source_digest: str,
) -> None:
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    config = _json(
        source_manifest.authority_path("source-config").read_bytes(), "source config"
    )
    observed = _json(candidate.member_bytes("provenance.json"), "provenance.json")
    if observed != _expected_provenance(
        source_manifest, commentary, config, source_digest
    ):
        raise ValueError("Keil-Delitzsch provenance, rights, scope, or status drifted")
    unresolved = [
        _json(line + b"\n", f"unresolved line {number}")
        for number, line in enumerate(
            candidate.member_bytes("unresolved.jsonl").splitlines(), start=1
        )
    ]
    if unresolved != _expected_unresolved(commentary, config):
        raise ValueError("Keil-Delitzsch unresolved evidence drifted or is incomplete")
    expected_readme = _expected_readme(
        commentary,
        profiles_record,
        config,
        profile,
        policy,
        source_digest,
    )
    if candidate.member_bytes("README.source.md") != expected_readme:
        raise ValueError(
            "Keil-Delitzsch source README drifted, is incomplete, or is invented"
        )


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
        raise ValueError("Keil-Delitzsch oracle closure has invalid relative import")
    base = package[: len(package) - trim] if trim else package
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base)


def _closure_records(root: Path, policy: dict[str, object]) -> list[dict[str, str]]:
    raw_forbidden = policy.get("forbidden_import_prefixes", [])
    if not isinstance(raw_forbidden, list) or any(
        not isinstance(item, str) for item in raw_forbidden
    ):
        raise ValueError("Keil-Delitzsch forbidden import policy is invalid")
    forbidden = tuple(raw_forbidden)
    entry_name = "build.tei.helloao_keil_delitzsch_oracle"
    entry = _resolve_first_party_module(root, entry_name)
    if entry is None:
        raise ValueError("Keil-Delitzsch oracle is absent from the repository root")
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
                    "Keil-Delitzsch oracle closure contains dynamic execution"
                )
        for name in imports:
            if any(
                name == prefix or name.startswith(prefix + ".") for prefix in forbidden
            ):
                raise ValueError(
                    f"Keil-Delitzsch oracle closure contains forbidden import {name}"
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
    expected_source_manifest = {
        "path": source_manifest.path.relative_to(root).as_posix(),
        "sha256": source_manifest.sha256,
    }
    expected_converter = source_manifest.record["converter"]
    expected_schema = source_manifest.record["package_schema"]
    if (
        candidate.manifest.get("source_id") != source_manifest.record.get("source_id")
        or candidate.manifest.get("source_manifest") != expected_source_manifest
        or candidate.manifest.get("converter") != expected_converter
        or candidate.manifest.get("package_schema") != expected_schema
        or candidate.manifest.get("status") != "nonaccepted"
    ):
        raise ValueError("Keil-Delitzsch candidate weakened an authority binding")
    members = _primary_members(source_manifest)
    source_digest = _source_digest(members)
    _verify_lineage(source_manifest, source_digest)
    books_record, profiles_record, chapters = _load_retained(source_manifest, members)
    structure_by_key, rendered_structure_keys, structure_summary = _load_structure_inventory(
        source_manifest, members
    )
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _json(profile_bytes, "reconstruction profile")
    policy = _json(policy_bytes, "validation policy")
    _verify_profile_policy(profile, policy)
    accountability = _json(
        candidate.member_bytes("source-accountability.json"),
        "source-accountability.json",
    )
    if accountability != _expected_accountability(
        members, books_record, profiles_record, chapters, structure_summary
    ):
        raise ValueError("Keil-Delitzsch accountability omission, inclusion, or drift")
    _verify_tei(
        candidate.member_bytes("content.tei.xml"),
        source_manifest,
        books_record,
        profiles_record,
        chapters,
        source_digest,
        structure_by_key,
        rendered_structure_keys,
    )
    _verify_provenance(
        source_manifest,
        candidate,
        books_record,
        profiles_record,
        profile,
        policy,
        source_digest,
    )
    implementation = Path(__file__).resolve()
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(implementation.read_bytes()),
        "import_closure_sha256": _closure_digest(root, policy),
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
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
