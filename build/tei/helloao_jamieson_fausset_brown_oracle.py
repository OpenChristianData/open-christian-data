"""Producer-independent oracle for the complete retained Jamieson-Fausset-Brown JSON witness."""

from __future__ import annotations

import ast
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-helloao-jamieson-fausset-brown-source-to-tei-oracle"
ORACLE_VERSION = "1"
_PROFILE_ID = "helloao-jamieson-fausset-brown-complete-retained-json-v1"
_SOURCE_PREFIX = "raw/helloao_local/api/c/jamieson-fausset-brown/"
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
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
                f"Jamieson-Fausset-Brown structure inventory pointer escaped its carrier: {pointer}"
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
    inventory = _json(inventory_bytes, _STRUCTURE_INVENTORY_AUTHORITY)
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
        raise ValueError("Jamieson-Fausset-Brown source paragraph policy drifted")
    primary_by_path = {str(item["path"]): item for item in records}
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    rendered_keys: set[tuple[str, str]] = set()
    span_count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Jamieson-Fausset-Brown structure inventory entry is invalid")
        source_path = entry.get("source_path")
        pointer = entry.get("json_pointer")
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
                f"Jamieson-Fausset-Brown structure inventory references an unbound carrier: {source_path}"
            )
        source_bytes = source_manifest.authority_path(str(primary["name"])).read_bytes()
        if (
            entry.get("source_file_bytes") != len(source_bytes)
            or entry.get("source_file_sha256") != _sha(source_bytes)
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory source file drifted: {source_path}"
            )
        carrier_text = _resolve_pointer(
            _json(source_bytes, source_path), pointer
        )
        if not isinstance(carrier_text, str):
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory carrier is not text: {key}"
            )
        if (
            entry.get("carrier_utf8_bytes") != len(carrier_text.encode("utf-8"))
            or entry.get("carrier_codepoint_length") != len(carrier_text)
            or entry.get("carrier_sha256") != _sha(carrier_text.encode("utf-8"))
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown structure inventory carrier text drifted: {key}"
            )
        headings = entry.get("headings")
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
                or end > len(carrier_text)
                or start < previous_end
                or carrier_text[start:end] != label
            ):
                raise ValueError(
                    f"Jamieson-Fausset-Brown structure inventory heading span drifted: {key}"
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
                    f"Jamieson-Fausset-Brown structure inventory boundary drifted: {key}"
                )
            previous_end = end
            span_count += 1
        by_key[key] = entry
        if entry.get("rendered_carrier") is not True:
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
            "sha256": _sha(inventory_bytes),
            "carrier_count": len(entries),
            "rendered_carrier_count": len(rendered_keys),
            "heading_span_count": span_count,
            "paragraph_policy": dict(paragraph_policy),
        },
    )


def _primary_members(source_manifest: SourceManifest) -> tuple[dict[str, object], ...]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("Jamieson-Fausset-Brown source authorities are invalid")
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
                "Jamieson-Fausset-Brown primary-source path escaped the retained root"
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
        len(records) != 1_189
        or len(set(relative)) != 1_189
        or sum(int(item["bytes"]) for item in records) != 22_377_675
        or set(relative) & {"books.json", "profiles.json"}
        != {"books.json", "profiles.json"}
        or len(
            [path for path in relative if path not in {"books.json", "profiles.json"}]
        )
        != 1_187
    ):
        raise ValueError("Jamieson-Fausset-Brown exact retained member census failed")
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


def _verify_lineage(source_manifest: SourceManifest, source_digest: str) -> None:
    lineage = source_manifest.record.get("catalog_claim_lineage")
    if not isinstance(lineage, Mapping):
        raise ValueError("Jamieson-Fausset-Brown catalog lineage is missing")
    if (
        lineage.get("contract") != "ocd-catalog-claim-lineage-v1"
        or lineage.get("work_id") != "jamieson-fausset-brown"
        or lineage.get("retained_source_sha256") != source_digest
    ):
        raise ValueError("Jamieson-Fausset-Brown catalog lineage binding drifted")
    claims = lineage.get("claims")
    if (
        not isinstance(claims, tuple)
        or len(claims) != 66
        or lineage.get("claim_count") != 66
    ):
        raise ValueError("Jamieson-Fausset-Brown catalog claim count drifted")
    rows: list[tuple[str, str]] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ValueError("Jamieson-Fausset-Brown catalog claim shape drifted")
        path = claim.get("source_path")
        digest = claim.get("legacy_source_sha256")
        if (
            not isinstance(path, str)
            or not path.startswith("commentaries/jamieson-fausset-brown/")
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("Jamieson-Fausset-Brown catalog claim shape drifted")
        rows.append((path, digest))
    if (
        rows != sorted(rows)
        or len({path for path, _ in rows}) != 66
        or len({digest for _, digest in rows}) != 66
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown catalog claims are reordered or duplicated"
        )


def _load_retained(
    source_manifest: SourceManifest, records: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    by_relative = {str(item["relative_path"]): item for item in records}

    def load(relative: str) -> dict[str, object]:
        item = by_relative.get(relative)
        if item is None or not isinstance(item.get("name"), str):
            raise ValueError(f"Jamieson-Fausset-Brown manifest lacks {relative}")
        content = source_manifest.authority_path(str(item["name"])).read_bytes()
        if len(content) != item["bytes"] or _sha(content) != item["sha256"]:
            raise ValueError(
                f"Jamieson-Fausset-Brown retained bytes drifted at {relative}"
            )
        return _json(content, relative)

    books_record = load("books.json")
    profiles_record = load("profiles.json")
    commentary = books_record.get("commentary")
    books = books_record.get("books")
    if (
        not isinstance(commentary, dict)
        or not isinstance(books, list)
        or len(books) != 66
    ):
        raise ValueError("Jamieson-Fausset-Brown retained books metadata is invalid")
    if (
        profiles_record.get("commentary") != commentary
        or profiles_record.get("profiles") != []
    ):
        raise ValueError("Jamieson-Fausset-Brown retained profiles metadata is invalid")
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
        raise ValueError("Jamieson-Fausset-Brown retained commentary identity drifted")
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
    chapters: list[dict[str, object]] = []
    covered = {"books.json", "profiles.json"}
    previous_order = 0
    chapter_paths_by_book: dict[str, list[tuple[int, str]]] = {}
    for relative in by_relative:
        if relative in covered:
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter path drifted: {relative}"
            )
        try:
            number = int(parts[1][:-5])
        except ValueError as exc:
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter path drifted: {relative}"
            ) from exc
        if number < 1:
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter path drifted: {relative}"
            )
        chapter_paths_by_book.setdefault(parts[0], []).append((number, relative))
    for retained_ordinal, raw_book in enumerate(books, start=1):
        if not isinstance(raw_book, dict):
            raise ValueError("Jamieson-Fausset-Brown retained book is not an object")
        book_id = raw_book.get("id")
        count = raw_book.get("numberOfChapters")
        if (
            not isinstance(book_id, str)
            or not isinstance(count, int)
            or not isinstance(raw_book.get("order"), int)
            or int(raw_book["order"]) <= previous_order
            or raw_book.get("firstChapterNumber") != 1
            or not isinstance(raw_book.get("introduction"), str)
            or len(raw_book) != 13
        ):
            raise ValueError(
                "Jamieson-Fausset-Brown retained book order or structure drifted "
                f"at ordinal {retained_ordinal}"
            )
        previous_order = int(raw_book["order"])
        book_paths = sorted(chapter_paths_by_book.pop(book_id, []))
        first = raw_book.get("firstChapterNumber")
        last = raw_book.get("lastChapterNumber")
        if not isinstance(first, int) or not isinstance(last, int):
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter range drifted at {book_id}"
            )
        observed_numbers = [number for number, _ in book_paths]
        expected_gaps = {"MRK": [15], "PSA": [146]}.get(book_id, [])
        if (
            len(book_paths) != count
            or first != 1
            or [
                number
                for number in range(first, last + 1)
                if number not in observed_numbers
            ]
            != expected_gaps
            or any(number < first or number > last for number in observed_numbers)
        ):
            raise ValueError(
                f"Jamieson-Fausset-Brown retained chapter range drifted at {book_id}"
            )
        for number, relative in book_paths:
            envelope = load(relative)
            covered.add(relative)
            chapter = envelope.get("chapter")
            if (
                envelope.get("commentary") != commentary
                or envelope.get("book") != raw_book
                or not isinstance(chapter, dict)
                or chapter.get("number") != number
                or not isinstance(chapter.get("content"), list)
                or len(chapter) not in {2, 3}
                or set(chapter)
                not in (
                    {"number", "content"},
                    {"number", "content", "introduction"},
                )
                or len(envelope) != 7
                or envelope.get("numberOfVerses") != len(chapter["content"])
                or not isinstance(envelope.get("thisChapterLink"), str)
                or not isinstance(envelope.get("nextChapterApiLink"), (str, type(None)))
                or not isinstance(
                    envelope.get("previousChapterApiLink"), (str, type(None))
                )
            ):
                raise ValueError(
                    f"Jamieson-Fausset-Brown chapter envelope drifted at {relative}"
                )
            if "introduction" in chapter and not isinstance(
                chapter["introduction"], str
            ):
                raise ValueError(
                    f"Jamieson-Fausset-Brown chapter introduction drifted at {relative}"
                )
            for occurrence in chapter["content"]:
                if (
                    not isinstance(occurrence, dict)
                    or list(occurrence) != ["type", "number", "content"]
                    or occurrence.get("type") != "verse"
                    or not isinstance(occurrence.get("number"), int)
                    or not isinstance(occurrence.get("content"), list)
                    or len(occurrence["content"]) != 1
                    or not isinstance(occurrence["content"][0], str)
                ):
                    raise ValueError(
                        f"Jamieson-Fausset-Brown occurrence drifted at {relative}"
                    )
            chapters.append(
                {
                    "relative_path": relative,
                    "book": raw_book,
                    "chapter": chapter,
                    "envelope": envelope,
                }
            )
    if chapter_paths_by_book or covered != set(by_relative) or len(chapters) != 1_187:
        raise ValueError(
            "Jamieson-Fausset-Brown member inclusion/exclusion accounting failed"
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


def _mojibake_census(
    books_record: dict[str, object], chapters: list[dict[str, object]]
) -> dict[str, object]:
    """Independently census localized suspect sequences in retained semantic text."""

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


def _expected_unresolved(mojibake: dict[str, object]) -> list[dict[str, object]]:
    return [
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


def _verify_accountability(
    source_manifest: SourceManifest,
    records: tuple[dict[str, object], ...],
    books_record: dict[str, object],
    profiles_record: dict[str, object],
    chapters: list[dict[str, object]],
    accountability: dict[str, object],
    mojibake: dict[str, object],
    structure_summary: dict[str, object],
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
        "contract": "ocd-helloao-jamieson-fausset-brown-source-accountability-v1",
        "profile_id": _PROFILE_ID,
        "source_root": _SOURCE_PREFIX.removesuffix("/"),
        "source_member_set_sha256": _source_digest(records),
        "member_count": 1_189,
        "total_bytes": 22_377_675,
        "included_member_count": 1_189,
        "excluded_member_count": 0,
        "members": expected_members,
        "census": {
            "books": 66,
            "chapters": 1187,
            "commentary_occurrences": sum(
                len(item["chapter"]["content"]) for item in chapters
            ),
            "book_introductions": 66,
            "chapter_introductions_present": present,
            "chapter_introductions_absent": 1187 - present,
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
    if accountability != expected:
        raise ValueError(
            "Jamieson-Fausset-Brown source accountability omission, exclusion, or drift"
        )


def _element_children(node: etree._Element) -> list[etree._Element]:
    children = list(node)
    if any(not isinstance(child.tag, str) for child in children):
        raise ValueError(
            "Jamieson-Fausset-Brown TEI contains an unaccounted comment or instruction"
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
            else "xml:space"
            if key == f"{{{_XML_NS}}}space"
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
        raise ValueError(f"Jamieson-Fausset-Brown TEI {label} drifted")


def _assert_leaf(
    node: etree._Element,
    name: str,
    attributes: Mapping[str, str],
    text: str | None,
    label: str,
) -> None:
    _assert_element(node, name, attributes, text, label)
    if len(node) != 0:
        raise ValueError(
            f"Jamieson-Fausset-Brown TEI {label} contains unaccounted descendants"
        )


def _assert_source_text(
    parent: etree._Element,
    source_text: str,
    inventory_entry: dict[str, object] | None,
    label: str,
) -> None:
    def expected_paragraphs(text: str) -> list[str]:
        if "\n\n" not in text:
            return [text]
        paragraphs: list[str] = []
        cursor = 0
        while True:
            separator = text.find("\n\n", cursor)
            if separator < 0:
                tail = text[cursor:]
                if tail or not paragraphs:
                    paragraphs.append(tail)
                break
            segment = text[cursor : separator + 2]
            if segment or not paragraphs:
                paragraphs.append(segment)
            cursor = separator + 2
            if cursor == len(text):
                break
        return paragraphs

    def assert_paragraphs(
        node: etree._Element, text: str, child_label: str
    ) -> None:
        paragraphs = _element_children(node)
        assert_paragraph_sequence(paragraphs, text, child_label)

    def assert_paragraph_sequence(
        paragraphs: list[etree._Element], text: str, child_label: str
    ) -> None:
        expected = expected_paragraphs(text)
        if len(paragraphs) != len(expected):
            raise ValueError(f"Jamieson-Fausset-Brown {child_label} paragraph count drifted")
        for paragraph, segment in zip(paragraphs, expected, strict=True):
            attributes: dict[str, str] = {}
            if segment == "":
                attributes["ana"] = "empty-string"
            elif not segment.strip():
                attributes["xml:space"] = "preserve"
            _assert_leaf(
                paragraph,
                "p",
                attributes,
                None if segment == "" else segment,
                child_label,
            )

    headings = [] if inventory_entry is None else inventory_entry.get("headings")
    if not isinstance(headings, list) or not headings:
        assert_paragraphs(parent, source_text, label)
        return
    parent_id = parent.get(f"{{{_XML_NS}}}id")
    if not isinstance(parent_id, str):
        raise ValueError(f"Jamieson-Fausset-Brown {label} has no xml:id")
    children = _element_children(parent)
    if len(children) != len(list(parent)):
        raise ValueError(f"Jamieson-Fausset-Brown {label} contains unaccounted body nodes")
    cursor = 0
    for ordinal, heading in enumerate(headings, start=1):
        if not isinstance(heading, dict):
            raise ValueError(f"Jamieson-Fausset-Brown {label} inventory heading is invalid")
        start = int(heading["start"])
        end = int(heading["end"])
        if start < cursor or source_text[start:end] != heading["text"]:
            raise ValueError(f"Jamieson-Fausset-Brown {label} inventory span drifted")
        prefix = source_text[cursor:start]
        next_start = (
            int(headings[ordinal]["start"])
            if ordinal < len(headings)
            else len(source_text)
        )
        cursor = next_start
    if cursor != len(source_text):
        raise ValueError(f"Jamieson-Fausset-Brown {label} source span is incomplete")
    cursor = 0
    child_index = 0
    for ordinal, heading in enumerate(headings, start=1):
        assert isinstance(heading, dict)
        start = int(heading["start"])
        end = int(heading["end"])
        prefix = source_text[cursor:start]
        if prefix:
            prefix_count = len(expected_paragraphs(prefix))
            if child_index + prefix_count > len(children):
                raise ValueError(f"Jamieson-Fausset-Brown {label} prefix drifted")
            for child in children[child_index : child_index + prefix_count]:
                if etree.QName(child).localname != "p":
                    raise ValueError(f"Jamieson-Fausset-Brown {label} prefix drifted")
            assert_paragraph_sequence(
                children[child_index : child_index + prefix_count],
                prefix,
                f"{label} prefix",
            )
            child_index += prefix_count
        if child_index >= len(children):
            raise ValueError(
                f"Jamieson-Fausset-Brown {label} omitted section {ordinal}"
            )
        section = children[child_index]
        _assert_element(
            section,
            "div",
            {
                "type": "commentary-section",
                "xml:id": f"{parent_id}-section-{ordinal:03d}",
            },
            None,
            f"{label} section",
        )
        section_children = _element_children(section)
        if len(section_children) != len(list(section)):
            raise ValueError(f"Jamieson-Fausset-Brown {label} section contains body nodes")
        next_start = (
            int(headings[ordinal]["start"])
            if ordinal < len(headings)
            else len(source_text)
        )
        remainder = source_text[end:next_start]
        expected_remainder_count = len(expected_paragraphs(remainder))
        if len(section_children) != 1 + expected_remainder_count:
            raise ValueError(
                f"Jamieson-Fausset-Brown {label} section child count drifted"
            )
        _assert_leaf(
            section_children[0],
            "head",
            {},
            str(heading["text"]),
            f"{label} heading",
        )
        if remainder:
            expected_remainder = expected_paragraphs(remainder)
            observed_remainder = section_children[1:]
            assert_paragraph_sequence(
                observed_remainder,
                remainder,
                f"{label} section text",
            )
        child_index += 1
        cursor = next_start
    if child_index != len(children) or "".join(parent.itertext()) != source_text:
        raise ValueError(f"Jamieson-Fausset-Brown {label} source text or attachment drifted")


def _verify_tei(
    tei_bytes: bytes,
    books_record: dict[str, object],
    chapters: list[dict[str, object]],
    source_digest: str,
    structure_by_key: dict[tuple[str, str], dict[str, object]],
    rendered_structure_keys: set[tuple[str, str]],
) -> None:
    if not tei_bytes.startswith(_EXPECTED_TEI_PROLOG):
        raise ValueError("Jamieson-Fausset-Brown TEI document prolog drifted")
    if tei_bytes[len(_EXPECTED_TEI_PROLOG) : len(_EXPECTED_TEI_PROLOG) + 1] != b"<":
        raise ValueError("Jamieson-Fausset-Brown TEI document prolog drifted")
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
        raise ValueError(
            "Jamieson-Fausset-Brown candidate is not safe well-formed XML"
        ) from exc
    if tree.docinfo.doctype:
        raise ValueError("Jamieson-Fausset-Brown TEI document prolog drifted")
    root = tree.getroot()
    if root.getprevious() is not None or root.getnext() is not None:
        raise ValueError(
            "Jamieson-Fausset-Brown TEI contains an unaccounted document-level node"
        )
    ns = {"tei": _TEI_NS, "xml": _XML_NS}
    if (
        etree.QName(root).localname != "TEI"
        or etree.QName(root).namespace != _TEI_NS
        or root.attrib
        or root.text is not None
        or root.tail is not None
    ):
        raise ValueError("Jamieson-Fausset-Brown TEI root drifted")
    root_children = _element_children(root)
    if [etree.QName(item).localname for item in root_children] != ["teiHeader", "text"]:
        raise ValueError("Jamieson-Fausset-Brown TEI root member order drifted")
    commentary = books_record["commentary"]
    books = books_record["books"]
    assert isinstance(commentary, dict) and isinstance(books, list)
    observed_header = {
        "title": root.xpath(
            "string(tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title)", namespaces=ns
        ),
        "author_count": int(
            root.xpath(
                "count(tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author)",
                namespaces=ns,
            )
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
        "author_count": 0,
        "publisher": "Open Christian Data",
        "availability": "restricted",
        "rights": "Retained HelloAO metadata applies the Public Domain Mark 1.0; the source config's CC0 label is recorded as drift and is not substituted.",
        "source": commentary["listOfBooksApiLink"],
        "digest": source_digest,
        "witness": "retained HelloAO JSON snapshot",
    }
    if observed_header != expected_header:
        raise ValueError(
            "Jamieson-Fausset-Brown TEI metadata, rights, or source binding drifted"
        )
    expected_notes = [
        ("commentary-id", str(commentary["id"])),
        ("english-name", str(commentary["englishName"])),
        ("website", str(commentary["website"])),
        ("license-url", str(commentary["licenseUrl"])),
        ("license-notes", json.dumps(commentary["licenseNotes"])),
        ("language", str(commentary["language"])),
        ("language-name", str(commentary["languageName"])),
        ("language-english-name", str(commentary["languageEnglishName"])),
        ("text-direction", str(commentary["textDirection"])),
        ("source-reported-sha256", str(commentary["sha256"])),
        ("available-formats", json.dumps(commentary["availableFormats"])),
        ("books-api-link", str(commentary["listOfBooksApiLink"])),
        ("profiles-api-link", str(commentary["listOfProfilesApiLink"])),
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
        raise ValueError("Jamieson-Fausset-Brown retained header metadata drifted")
    text = root_children[1]
    _assert_element(text, "text", {"xml:lang": "eng"}, None, "text root")
    text_children = _element_children(text)
    if len(text_children) != 1 or etree.QName(text_children[0]).localname != "body":
        raise ValueError("Jamieson-Fausset-Brown TEI body structure drifted")
    body = text_children[0]
    book_nodes = _element_children(body)
    if len(book_nodes) != 66:
        raise ValueError("Jamieson-Fausset-Brown TEI falsely changed the 66-book scope")
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
                f"Jamieson-Fausset-Brown TEI book child census drifted for {book_id}"
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
        _assert_source_text(
            children[2],
            str(raw_book["introduction"]),
            None,
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
                        f"Jamieson-Fausset-Brown TEI omitted chapter introduction at {relative}"
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
                intro_key = (
                    f"{_SOURCE_PREFIX}{relative}",
                    "/chapter/introduction",
                )
                _assert_source_text(
                    intro,
                    str(chapter["introduction"]),
                    structure_by_key.get(intro_key),
                    f"chapter introduction text {relative}",
                )
                offset = 1
            content = chapter["content"]
            assert isinstance(content, list)
            occurrences = chapter_children[offset:]
            if len(occurrences) != len(content):
                raise ValueError(
                    f"Jamieson-Fausset-Brown occurrence omission or invention at {relative}"
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
                occurrence_key = (
                    f"{_SOURCE_PREFIX}{relative}",
                    f"/chapter/content/{ordinal - 1}/content/0",
                )
                _assert_source_text(
                    observed,
                    str(raw_occurrence["content"][0]),
                    structure_by_key.get(occurrence_key),
                    f"commentary text {relative}#{ordinal}",
                )
                occurrence_count += 1
    if occurrence_count != 17_056 or present_intro_count != 1_178:
        raise ValueError("Jamieson-Fausset-Brown TEI final content census drifted")
    used_structure_keys = {
        (
            f"{_SOURCE_PREFIX}{item['relative_path']}",
            "/chapter/introduction",
        )
        for item in chapters
        if "introduction" in item["chapter"]
    }
    used_structure_keys |= {
        (
            f"{_SOURCE_PREFIX}{item['relative_path']}",
            f"/chapter/content/{ordinal - 1}/content/0",
        )
        for item in chapters
        for ordinal, _ in enumerate(item["chapter"]["content"], start=1)
    }
    if (used_structure_keys & set(structure_by_key)) != rendered_structure_keys:
        raise ValueError(
            "Jamieson-Fausset-Brown structure inventory rendered carrier census drifted"
        )
    try:
        compiled_schema().assertValid(root)
    except etree.DocumentInvalid as exc:
        raise ValueError(
            "Jamieson-Fausset-Brown candidate fails TEI P5 validation"
        ) from exc


def _verify_provenance(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    books_record: dict[str, object],
    profile: dict[str, object],
    mojibake: dict[str, object],
) -> None:
    commentary = books_record["commentary"]
    assert isinstance(commentary, dict)
    config = _json(
        source_manifest.authority_path("source-config").read_bytes(), "source config"
    )
    expected = {
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
    provenance = _json(candidate.member_bytes("provenance.json"), "provenance.json")
    if provenance != expected:
        raise ValueError(
            "Jamieson-Fausset-Brown metadata, rights, scope, or witness identity drifted"
        )
    unresolved = [
        _json(line + b"\n", f"unresolved line {number}")
        for number, line in enumerate(
            candidate.member_bytes("unresolved.jsonl").splitlines(), start=1
        )
    ]
    if unresolved != _expected_unresolved(mojibake):
        raise ValueError("Jamieson-Fausset-Brown unresolved evidence contract drifted")
    if candidate.member_bytes("README.source.md") != _source_readme(mojibake):
        raise ValueError("Jamieson-Fausset-Brown inspectable source README drifted")


def _closure_digest(root: Path, policy: dict[str, object]) -> str:
    paths = {
        Path(__file__).resolve(),
        (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True),
        (root / "ocd_kernel/tei/validate.py").resolve(strict=True),
    }
    forbidden = tuple(policy.get("forbidden_import_prefixes", []))
    records = []
    for path in sorted(paths, key=lambda item: item.as_posix()):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"__import__", "eval", "exec"}
            ):
                raise ValueError(
                    "Jamieson-Fausset-Brown oracle closure contains dynamic execution"
                )
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in forbidden
                ):
                    raise ValueError(
                        f"Jamieson-Fausset-Brown oracle closure contains forbidden import {name}"
                    )
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path.read_bytes()),
            }
        )
    return _sha(_canonical(records))


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
        raise ValueError(
            "Jamieson-Fausset-Brown candidate weakened a source authority binding"
        )
    records = _primary_members(source_manifest)
    books_record, profiles_record, chapters = _load_retained(source_manifest, records)
    mojibake = _mojibake_census(books_record, chapters)
    profile_bytes = source_manifest.authority_path(
        "reconstruction-profile"
    ).read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _json(profile_bytes, "Jamieson-Fausset-Brown reconstruction profile")
    policy = _json(policy_bytes, "Jamieson-Fausset-Brown validation policy")
    if (
        profile.get("contract") != "ocd-helloao-jamieson-fausset-brown-profile-v1"
        or profile.get("profile_id") != _PROFILE_ID
        or profile.get("candidate_model", {}).get("document_shell")
        != {
            "xml_declaration": "<?xml version='1.0' encoding='UTF-8'?>\n",
            "doctype": None,
            "pre_root_nodes": 0,
            "post_root_nodes": 0,
        }
        or policy.get("contract")
        != "ocd-helloao-jamieson-fausset-brown-validation-policy-v1"
        or "exact-canonical-xml-declaration-no-doctype-no-document-level-siblings"
        not in policy.get("checks", [])
        or _STRUCTURE_POLICY_CHECK not in policy.get("checks", [])
        or policy.get("required_counts")
        != {
            "source_members": 1189,
            "source_bytes": 22_377_675,
            "books": 66,
            "chapters": 1187,
            "commentary_occurrences": 17_056,
            "book_introductions": 66,
            "chapter_introductions_present": 1178,
            "chapter_introductions_absent": 9,
            "introduction_only_chapters": 101,
            "suspected_mojibake_sequences": 539,
            "suspected_mojibake_carriers": 374,
            "suspected_mojibake_source_members": 229,
        }
    ):
        raise ValueError(
            "Jamieson-Fausset-Brown bound profile or validation policy drifted"
        )
    source_digest = _source_digest(records)
    _verify_lineage(source_manifest, source_digest)
    structure_by_key, rendered_structure_keys, structure_summary = (
        _load_structure_inventory(source_manifest, records)
    )
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
        mojibake,
        structure_summary,
    )
    tei_bytes = candidate.member_bytes("content.tei.xml")
    _verify_tei(
        tei_bytes,
        books_record,
        chapters,
        source_digest,
        structure_by_key,
        rendered_structure_keys,
    )
    _verify_provenance(source_manifest, candidate, books_record, profile, mojibake)
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
