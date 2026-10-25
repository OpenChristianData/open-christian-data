"""Faithful reconstruction of the complete retained HelloAO Keil-Delitzsch witness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from lxml import etree

from ocd_kernel.reconstruction import SourceManifest


CONVERTER_ID = "ocd-helloao-keil-delitzsch-json-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "helloao-keil-delitzsch-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/keil-delitzsch/"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_STRUCTURE_INVENTORY_AUTHORITY = "structure-inventory"
_STRUCTURE_INVENTORY_CONTRACT = "ocd-source-structure-inventory-v1"
_STRUCTURE_POLICY_CHECK = (
    "exact-source-double-newline-paragraph-segmentation-and-pinned-book-introduction-headings"
)
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
        raise ValueError("Keil-Delitzsch source authorities are invalid")
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
            raise ValueError("Keil-Delitzsch primary-source authority is malformed")
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
    if len(members) != 911 or sum(int(item["bytes"]) for item in members) != 47_103_116:
        raise ValueError(
            "Keil-Delitzsch retained member census differs from 911/47,103,116"
        )
    relative_paths = [str(item["relative_path"]) for item in members]
    if len(set(relative_paths)) != 911:
        raise ValueError("Keil-Delitzsch retained member paths are not unique")
    chapter_paths = [
        path for path in relative_paths if path not in {"books.json", "profiles.json"}
    ]
    if (
        set(relative_paths) & {"books.json", "profiles.json"}
        != {"books.json", "profiles.json"}
        or len(chapter_paths) != 909
        or any(
            path.count("/") != 1 or not path.endswith(".json") for path in chapter_paths
        )
    ):
        raise ValueError("Keil-Delitzsch retained member paths are incomplete")
    raw_root = (
        source_manifest.repository_root / _SOURCE_PREFIX.removesuffix("/")
    ).resolve(strict=True)
    actual_paths = {
        path.relative_to(raw_root).as_posix()
        for path in raw_root.rglob("*")
        if path.is_file()
    }
    if actual_paths != set(relative_paths):
        raise ValueError(
            "Keil-Delitzsch retained root has an unbound or missing member"
        )
    for member in members:
        path = source_manifest.authority_path(str(member["name"]))
        content = path.read_bytes()
        if len(content) != member["bytes"] or _sha(content) != member["sha256"]:
            raise ValueError(
                f"Keil-Delitzsch retained member bytes drifted: {member['path']}"
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


def _verify_catalog_lineage(
    source_manifest: SourceManifest, source_digest: str
) -> None:
    lineage = source_manifest.record.get("catalog_claim_lineage")
    if (
        not isinstance(lineage, Mapping)
        or lineage.get("contract") != "ocd-catalog-claim-lineage-v1"
        or lineage.get("work_id") != "keil-delitzsch"
        or lineage.get("retained_source_sha256") != source_digest
    ):
        raise ValueError("Keil-Delitzsch catalog lineage binding drifted")
    claims = lineage.get("claims")
    if (
        not isinstance(claims, tuple)
        or lineage.get("claim_count") != 38
        or len(claims) != 38
    ):
        raise ValueError("Keil-Delitzsch catalog claim census drifted")
    rows: list[tuple[str, str]] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("Keil-Delitzsch catalog claim is malformed")
        path = claim.get("source_path")
        digest = claim.get("legacy_source_sha256")
        if (
            not isinstance(path, str)
            or not path.startswith("commentaries/keil-delitzsch/")
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("Keil-Delitzsch catalog claim is malformed")
        rows.append((path, digest))
    if rows != sorted(rows) or len({path for path, _ in rows}) != 38:
        raise ValueError("Keil-Delitzsch catalog claims are reordered or duplicated")


def _authority_json(source_manifest: SourceManifest, name: str) -> dict[str, Any]:
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
            raise ValueError(
                f"Keil-Delitzsch structure inventory pointer escaped its carrier: {pointer}"
            )
    return current


def _load_structure_inventory(
    source_manifest: SourceManifest,
    records: tuple[dict[str, object], ...],
) -> tuple[
    dict[tuple[str, str], dict[str, object]],
    set[tuple[str, str]],
    dict[str, object],
]:
    inventory_bytes = source_manifest.authority_path(
        _STRUCTURE_INVENTORY_AUTHORITY
    ).read_bytes()
    inventory = _strict_json(inventory_bytes, _STRUCTURE_INVENTORY_AUTHORITY)
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
    primary_by_path = {str(item["path"]): item for item in records}
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
        carrier_text = _resolve_pointer(
            _strict_json(source_bytes, source_path), pointer
        )
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
    headings = [] if inventory_entry is None else inventory_entry.get("headings")
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


def _validate_profile_policy(profile: dict[str, Any], policy: dict[str, Any]) -> None:
    if (
        profile.get("contract") != "ocd-helloao-keil-delitzsch-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or profile.get("work_id") != "keil-delitzsch"
        or policy.get("contract") != "ocd-helloao-keil-delitzsch-validation-policy-v1"
        or _STRUCTURE_POLICY_CHECK not in policy.get("required_checks", [])
    ):
        raise ValueError("Keil-Delitzsch reconstruction profile or policy mismatch")
    required = {
        "source_members": 911,
        "source_bytes": 47_103_116,
        "books": 39,
        "chapters": 909,
        "commentary_occurrences": 6_516,
        "book_introductions": 39,
        "chapter_introductions_present": 394,
        "chapter_introductions_absent": 515,
    }
    if policy.get("required_counts") != required:
        raise ValueError("Keil-Delitzsch validation policy counts drifted")
    if profile.get("scope", {}).get("member_count") != 911:
        raise ValueError("Keil-Delitzsch reconstruction profile member count drifted")
    if policy.get("required_unresolved_ids") != [
        "keil-delitzsch-retained-vs-configured-title",
        "keil-delitzsch-config-cc0-vs-retained-pdm",
        "keil-delitzsch-configured-source-endpoint",
        "keil-delitzsch-retained-rtl-anomaly",
        "keil-delitzsch-edition-and-original-date",
    ]:
        raise ValueError("Keil-Delitzsch validation policy unresolved IDs drifted")


def _load_corpus(
    source_manifest: SourceManifest,
    records: tuple[dict[str, object], ...],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, Any]:
        item = by_relative.get(relative)
        if item is None:
            raise ValueError(f"Keil-Delitzsch manifest omits {relative}")
        return _strict_json(
            source_manifest.authority_path(str(item["name"])).read_bytes(), relative
        )

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("Keil-Delitzsch books.json shape is invalid")
    if set(commentary) != _COMMENTARY_KEYS or set(profiles_record) != {
        "commentary",
        "profiles",
    }:
        raise ValueError("Keil-Delitzsch collection metadata shape drifted")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError(
            "Keil-Delitzsch profiles metadata disagrees with books metadata"
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
            "Keil-Delitzsch retained commentary identity or census drifted"
        )
    if len(books) != 39:
        raise ValueError("Keil-Delitzsch books.json must contain 39 books")

    chapters: list[dict[str, Any]] = []
    seen_paths = {"books.json", "profiles.json"}
    chapter_paths_by_book: dict[str, list[tuple[int, str]]] = {}
    for relative in by_relative:
        if relative in seen_paths:
            continue
        book_id, filename = relative.split("/", 1)
        try:
            chapter_number = int(filename.removesuffix(".json"))
        except ValueError as exc:
            raise ValueError(
                f"Keil-Delitzsch chapter path is invalid: {relative}"
            ) from exc
        chapter_paths_by_book.setdefault(book_id, []).append((chapter_number, relative))
    previous_order = 0
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict) or set(raw_book) != _BOOK_KEYS:
            raise ValueError(
                f"Keil-Delitzsch book metadata is invalid at ordinal {retained_ordinal}"
            )
        book_id = raw_book.get("id")
        chapter_count = raw_book.get("numberOfChapters")
        if (
            not isinstance(book_id, str)
            or raw_book.get("commentaryId") != commentary["id"]
            or not isinstance(raw_book.get("order"), int)
            or int(raw_book["order"]) <= previous_order
            or not isinstance(chapter_count, int)
            or not isinstance(raw_book.get("introduction"), str)
        ):
            raise ValueError(
                f"Keil-Delitzsch book metadata drifted at retained ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
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
                raise ValueError("Keil-Delitzsch zero-chapter Song of Solomon drifted")
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
                f"Keil-Delitzsch retained chapter range drifted at {book_id}"
            )
        for chapter_number, relative in book_paths:
            chapter_record = load(relative)
            seen_paths.add(relative)
            if set(chapter_record) != _ENVELOPE_KEYS:
                raise ValueError(
                    f"Keil-Delitzsch chapter envelope shape drifted at {relative}"
                )
            chapter = chapter_record.get("chapter")
            embedded_book = chapter_record.get("book")
            expected_embedded_variant_paths = {
                *(f"HOS/{number}.json" for number in range(1, 15)),
                *(f"JOL/{number}.json" for number in range(1, 4)),
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
                chapter_record.get("commentary") != commentary
                or not isinstance(embedded_book, dict)
                or set(embedded_book) != _BOOK_KEYS
                or embedded_book.get("id") != book_id
                or (
                    embedded_differences
                    != (
                        {"introduction"}
                        if relative in expected_embedded_variant_paths
                        else set()
                    )
                )
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
                raise ValueError(
                    f"Keil-Delitzsch chapter envelope drifted at {relative}"
                )
            if not isinstance(chapter_record.get("thisChapterLink"), str):
                raise ValueError(
                    f"Keil-Delitzsch chapter link is invalid at {relative}"
                )
            if chapter_record.get(
                "previousChapterApiLink"
            ) is not None and not isinstance(
                chapter_record.get("previousChapterApiLink"), str
            ):
                raise ValueError(
                    f"Keil-Delitzsch previous chapter link is invalid at {relative}"
                )
            if chapter_record.get("nextChapterApiLink") is not None and not isinstance(
                chapter_record.get("nextChapterApiLink"), str
            ):
                raise ValueError(
                    f"Keil-Delitzsch next chapter link is invalid at {relative}"
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
                        f"Keil-Delitzsch commentary occurrence is invalid at {relative}"
                    )
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "embedded_book": embedded_book,
                    "chapter": chapter,
                    "envelope": chapter_record,
                }
            )
    if chapter_paths_by_book or seen_paths != set(by_relative) or len(chapters) != 909:
        raise ValueError(
            "Keil-Delitzsch retained member coverage is incomplete or contains extras"
        )
    for index, item in enumerate(chapters):
        relative = str(item["relative_path"])
        envelope = item["envelope"]
        if not isinstance(envelope, dict):
            raise ValueError("Keil-Delitzsch chapter envelope model is invalid")
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
            raise ValueError(f"Keil-Delitzsch chapter navigation drifted at {relative}")
    return books_record, profiles_record, chapters


def _content_digests(
    books_record: dict[str, Any],
    profiles_record: dict[str, Any],
    chapters: list[dict[str, Any]],
) -> dict[str, str]:
    books = books_record["books"]
    if not isinstance(books, list):
        raise ValueError("Keil-Delitzsch books metadata is invalid")
    book_order = [item["id"] for item in books]
    book_introductions = [
        [item["id"], _sha(str(item["introduction"]).encode("utf-8"))] for item in books
    ]
    chapter_order: list[list[object]] = []
    chapter_introductions: list[list[object]] = []
    chapter_envelopes: list[list[object]] = []
    chapter_embedded_books: list[list[object]] = []
    chapter_embedded_commentaries: list[list[object]] = []
    occurrences: list[list[object]] = []
    for item in chapters:
        relative = item["relative_path"]
        chapter = item["chapter"]
        envelope = item["envelope"]
        embedded_book = item["embedded_book"]
        if (
            not isinstance(relative, str)
            or not isinstance(chapter, dict)
            or not isinstance(envelope, dict)
            or not isinstance(embedded_book, dict)
        ):
            raise ValueError("Keil-Delitzsch chapter model is invalid")
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
        chapter_embedded_books.append([relative, embedded_book])
        chapter_embedded_commentaries.append([relative, envelope["commentary"]])
        content = chapter["content"]
        if not isinstance(content, list):
            raise ValueError("Keil-Delitzsch chapter content is invalid")
        for ordinal, occurrence in enumerate(content, start=1):
            if not isinstance(occurrence, dict):
                raise ValueError("Keil-Delitzsch occurrence is invalid")
            occurrence_content = occurrence["content"]
            if not isinstance(occurrence_content, list) or len(occurrence_content) != 1:
                raise ValueError("Keil-Delitzsch occurrence content is invalid")
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
        "chapter_embedded_books_sha256": _sha(_canonical(chapter_embedded_books)),
        "chapter_embedded_commentaries_sha256": _sha(
            _canonical(chapter_embedded_commentaries)
        ),
        "chapter_introductions_sha256": _sha(_canonical(chapter_introductions)),
        "commentary_occurrences_sha256": _sha(_canonical(occurrences)),
    }


def _object_key_order_census(
    books_record: dict[str, Any],
    profiles_record: dict[str, Any],
    chapters: list[dict[str, Any]],
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
        raise ValueError("Keil-Delitzsch JSON object/key-order census drifted")
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
            raise ValueError("Keil-Delitzsch anomaly model is invalid")
        if "introduction" not in chapter:
            absent_introductions.append(relative)
        if envelope["previousChapterApiLink"] is None:
            null_previous.append(relative)
        if envelope["nextChapterApiLink"] is None:
            null_next.append(relative)
        content = chapter["content"]
        if not isinstance(content, list):
            raise ValueError("Keil-Delitzsch content is invalid")
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
        raise ValueError("Keil-Delitzsch chapter link is not a string or null")
    return _el("note", attributes, value)


def _build_tei(
    books_record: dict[str, Any],
    profiles_record: dict[str, Any],
    chapters: list[dict[str, Any]],
    source_digest: str,
    structure_by_key: dict[tuple[str, str], dict[str, object]],
    rendered_structure_keys: set[tuple[str, str]],
) -> bytes:
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if not isinstance(commentary, dict) or not isinstance(books, list):
        raise ValueError("Keil-Delitzsch source metadata is invalid")
    chapters_by_book: dict[str, list[dict[str, Any]]] = {}
    for item in chapters:
        raw_book = item.get("book")
        if not isinstance(raw_book, dict) or not isinstance(raw_book.get("id"), str):
            raise ValueError("Keil-Delitzsch chapter book metadata is invalid")
        chapters_by_book.setdefault(str(raw_book["id"]), []).append(item)

    tei = _el("TEI")
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text=str(commentary["name"])))
    title_stmt.append(_el("author", text="Carl Friedrich Keil and Franz Delitzsch"))
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
    used_structure_keys: set[tuple[str, str]] = set()
    for book_index, raw_book in enumerate(books):
        if not isinstance(raw_book, dict) or not isinstance(raw_book.get("id"), str):
            raise ValueError("Keil-Delitzsch book metadata is invalid")
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
        book_key = (_SOURCE_PREFIX + "books.json", f"/books/{book_index}/introduction")
        book_entry = structure_by_key.get(book_key)
        if book_entry is not None:
            used_structure_keys.add(book_key)
        _append_source_text(
            book_intro,
            str(raw_book["introduction"]),
            book_entry,
            label=f"books.json#/books/{book_index}/introduction",
        )
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
                raise ValueError("Keil-Delitzsch chapter model is invalid")
            number = chapter.get("number")
            if not isinstance(number, int):
                raise ValueError("Keil-Delitzsch chapter number is invalid")
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
                _append_source_text(
                    chapter_intro,
                    str(chapter["introduction"]),
                    None,
                    label=f"{relative}#/chapter/introduction",
                )
                chapter_div.append(chapter_intro)
            content = chapter.get("content")
            if not isinstance(content, list):
                raise ValueError("Keil-Delitzsch chapter content is invalid")
            for ordinal, raw_occurrence in enumerate(content, start=1):
                if not isinstance(raw_occurrence, dict):
                    raise ValueError("Keil-Delitzsch occurrence is invalid")
                occurrence_content = raw_occurrence.get("content")
                if (
                    not isinstance(occurrence_content, list)
                    or len(occurrence_content) != 1
                ):
                    raise ValueError("Keil-Delitzsch occurrence content is invalid")
                occurrence = _el(
                    "div",
                    {
                        "type": "commentary-occurrence",
                        "subtype": str(raw_occurrence["type"]),
                        "n": str(raw_occurrence["number"]),
                        "xml:id": f"commentary-{book_id}-{number:03d}-{ordinal:05d}",
                    },
                )
                occurrence_text = str(occurrence_content[0])
                _append_source_text(
                    occurrence,
                    occurrence_text,
                    None,
                    label=f"{relative}#/chapter/content/{ordinal - 1}/content/0",
                )
                chapter_div.append(occurrence)
            book_div.append(chapter_div)
        body.append(book_div)
    if used_structure_keys != rendered_structure_keys:
        missing = sorted(rendered_structure_keys - used_structure_keys)
        extra = sorted(used_structure_keys - rendered_structure_keys)
        raise ValueError(
            "Keil-Delitzsch rendered structure carrier census drifted: "
            f"missing={missing!r}, extra={extra!r}"
        )
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
        "contract": "ocd-helloao-keil-delitzsch-source-accountability-v1",
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
            "object_key_order_census": _object_key_order_census(
                books_record, profiles_record, chapters
            ),
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


def _readme(source_digest: str, config: dict[str, Any]) -> str:
    return f"""# Keil-Delitzsch retained HelloAO source

This candidate is a deterministic, nonaccepted TEI reconstruction of the complete retained
HelloAO JSON witness at `raw/helloao_local/api/c/keil-delitzsch`.

- The retained census is exactly 911 members and 47,103,116 bytes.
- It contains 39 books, 909 chapters, and 6,516 ordered commentary occurrences.
- All 39 book introductions, 394 present chapter introductions, and 515 absent
  `introduction` properties are accounted for.
- Song of Solomon's complete retained book introduction and book SHA-256 are preserved even
  though it declares zero chapters and has no chapter member.
- Eleven internal chapter numbers are absent across EXO, NUM, JOB, PSA, and EZK. The retained
  paths and exact global navigation links across those gaps are preserved without invention.
- JDG 12, 2KI 10, and ISA 38 have nonmonotonic occurrence numbers. Their order is preserved;
  ISA 38's two distinct number-21 occurrences remain separate.
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
    source_digest = _source_set_digest(records)
    _verify_catalog_lineage(source_manifest, source_digest)
    books_record, profiles_record, chapters = _load_corpus(source_manifest, records)
    structure_by_key, rendered_structure_keys, structure_summary = _load_structure_inventory(
        source_manifest, records
    )
    commentary = books_record.get("commentary")
    if not isinstance(commentary, dict):
        raise ValueError("Keil-Delitzsch commentary metadata is invalid")
    return {
        "content.tei.xml": _build_tei(
            books_record,
            profiles_record,
            chapters,
            source_digest,
            structure_by_key,
            rendered_structure_keys,
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
