"""Deterministic source-bound TEI producer for ticket 37c-087 / LIB-024."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


TICKET_ID = "37c-087"
WORK_ID = "bsb"
SOURCE_ID = "ocd-37c087-bsb-retained-native-json-v1"
CONVERTER_ID = "ocd-37c087-bsb-json-to-tei"
CONVERTER_VERSION = "1"
PROFILE_ID = "bsb-native-json-complete-v1"
POLICY_ID = "bsb-native-json-complete-v1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} has duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _authority_record(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("BSB source authorities are invalid")
    found = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(found) != 1:
        raise ValueError(f"BSB requires exactly one {name} authority")
    return found[0]


def _authority_bytes(source_manifest: SourceManifest, name: str) -> bytes:
    return source_manifest.authority_path(name).read_bytes()


def _profile(source_manifest: SourceManifest) -> dict[str, object]:
    value = _strict_json(
        _authority_bytes(source_manifest, "reconstruction-profile"),
        "BSB reconstruction profile",
    )
    if value.get("contract") != "ocd-37c087-reconstruction-profile-v1":
        raise ValueError("BSB reconstruction profile contract drifted")
    if value.get("profile_id") != PROFILE_ID:
        raise ValueError("BSB reconstruction profile identity drifted")
    return value


def _policy(source_manifest: SourceManifest) -> dict[str, object]:
    value = _strict_json(
        _authority_bytes(source_manifest, "validation-policy"),
        "BSB validation policy",
    )
    if value.get("contract") != "ocd-37c087-validation-policy-v1":
        raise ValueError("BSB validation policy contract drifted")
    if value.get("policy_id") != POLICY_ID:
        raise ValueError("BSB validation policy identity drifted")
    return value


def _assert_manifest(source_manifest: SourceManifest) -> None:
    record = source_manifest.record
    if (
        record.get("contract") != "ocd-source-manifest-v1"
        or record.get("ticket_id") != TICKET_ID
        or record.get("work_id") != WORK_ID
        or record.get("source_id") != SOURCE_ID
    ):
        raise ValueError("BSB source manifest identity drifted")
    scope = record.get("scope")
    if not isinstance(scope, Mapping):
        raise ValueError("BSB source manifest scope is missing")
    if (
        scope.get("kind") != "complete-json-document"
        or scope.get("assigned_work") != WORK_ID
        or scope.get("source_member") != "retained-bsb-json"
        or scope.get("excluded_top_level_fields") != ()
        or scope.get("excluded_source_members") != ()
    ):
        raise ValueError("BSB source manifest scope drifted")
    source = _authority_record(source_manifest, "retained-bsb-json")
    if source.get("role") != "primary-source":
        raise ValueError("BSB retained source role drifted")
    config = _strict_json(_authority_bytes(source_manifest, "work-config"), "BSB config")
    if (
        config.get("resource_id") != WORK_ID
        or config.get("title") != "Berean Standard Bible"
        or config.get("source_file") != source.get("path")
        or config.get("source_format") != "JSON"
        or config.get("license") != "cc0-1.0"
    ):
        raise ValueError("BSB work configuration binding drifted")


def _validate_payload(
    payload: Mapping[str, object], profile: Mapping[str, object]
) -> tuple[str, list[Mapping[str, object]]]:
    if list(payload) != ["translation", "books"]:
        raise ValueError("BSB top-level key order or envelope drifted")
    translation = payload.get("translation")
    books = payload.get("books")
    if not isinstance(translation, str) or not translation:
        raise ValueError("BSB translation marker is invalid")
    if not isinstance(books, list) or len(books) != 66:
        raise ValueError("BSB book envelope is incomplete")
    envelope = profile.get("source_envelope")
    if not isinstance(envelope, Mapping):
        raise ValueError("BSB profile source envelope is missing")
    expected_names = envelope.get("book_names_in_source_order")
    if not isinstance(expected_names, list) or [
        item.get("name") if isinstance(item, Mapping) else None for item in books
    ] != expected_names:
        raise ValueError("BSB book order or names drifted")

    chapter_count = 0
    verse_count = 0
    empty_count = 0
    locations: list[list[object]] = []
    for book_index, book in enumerate(books):
        if not isinstance(book, Mapping) or list(book) != ["name", "chapters"]:
            raise ValueError(f"BSB book {book_index} shape drifted")
        name = book.get("name")
        chapters = book.get("chapters")
        if not isinstance(name, str) or not isinstance(chapters, list):
            raise ValueError(f"BSB book {book_index} is invalid")
        for chapter_index, chapter in enumerate(chapters, 1):
            if not isinstance(chapter, Mapping) or list(chapter) != [
                "chapter",
                "verses",
            ]:
                raise ValueError(f"BSB chapter {book_index}/{chapter_index} shape drifted")
            if chapter.get("chapter") != chapter_index:
                raise ValueError(f"BSB chapter numbering drifted at {name}")
            verses = chapter.get("verses")
            if not isinstance(verses, list):
                raise ValueError(f"BSB chapter verses are invalid at {name}")
            chapter_count += 1
            for verse_index, verse in enumerate(verses, 1):
                if not isinstance(verse, Mapping) or list(verse) != ["verse", "text"]:
                    raise ValueError(
                        f"BSB verse {book_index}/{chapter_index}/{verse_index} shape drifted"
                    )
                if verse.get("verse") != verse_index or not isinstance(
                    verse.get("text"), str
                ):
                    raise ValueError(
                        f"BSB verse numbering or text drifted at {name} {chapter_index}:{verse_index}"
                    )
                verse_count += 1
                if verse["text"] == "":
                    empty_count += 1
                    locations.append([name, chapter_index, verse_index])
    if (
        chapter_count != envelope.get("chapter_count")
        or verse_count != envelope.get("verse_row_count")
        or verse_count - empty_count != envelope.get("nonempty_verse_row_count")
        or empty_count != envelope.get("empty_verse_row_count")
        or locations != envelope.get("empty_verse_locations")
    ):
        raise ValueError("BSB source census drifted")
    return translation, books


def _qname(local: str) -> str:
    return f"{{{TEI_NS}}}{local}"


def _element(
    parent: etree._Element,
    local: str,
    *,
    text: str | None = None,
    attributes: Mapping[str, str] | None = None,
) -> etree._Element:
    node = etree.SubElement(parent, _qname(local), dict(attributes or {}))
    if text is not None:
        node.text = text
    return node


def _build_tei(
    source_manifest: SourceManifest,
    config: Mapping[str, object],
    source_bytes: bytes,
    translation: str,
    books: list[Mapping[str, object]],
) -> bytes:
    source_path = str(_authority_record(source_manifest, "retained-bsb-json")["path"])
    source_sha = _sha(source_bytes)
    root = etree.Element(_qname("TEI"), nsmap={None: TEI_NS})
    root.set(XML_ID, "bsb-candidate")
    header = _element(root, "teiHeader")
    file_desc = _element(header, "fileDesc")
    title_stmt = _element(file_desc, "titleStmt")
    _element(title_stmt, "title", text=str(config["title"]))
    publication = _element(file_desc, "publicationStmt")
    _element(publication, "publisher", text="Open Christian Data")
    availability = _element(
        publication, "availability", attributes={"status": "restricted"}
    )
    _element(
        availability,
        "p",
        text=(
            "Nonaccepted candidate only; publication is not authorized while "
            "metadata, rights, visual review, and human acceptance remain open."
        ),
    )
    source_desc = _element(file_desc, "sourceDesc")
    bibl = _element(
        source_desc,
        "bibl",
        attributes={XML_ID: "bsb-retained-source"},
    )
    _element(bibl, "title", text=translation, attributes={"type": "translation-marker"})
    _element(
        bibl,
        "note",
        text=translation,
        attributes={XML_ID: "bsb-translation", "type": "translation-marker"},
    )
    _element(bibl, "ptr", attributes={"target": str(config["source_url"])})
    _element(bibl, "idno", text=source_sha, attributes={"type": "sha256"})
    _element(
        bibl,
        "num",
        text=str(len(source_bytes)),
        attributes={"type": "bytes"},
    )
    _element(
        bibl,
        "note",
        text=(
            "The retained native JSON document contains the complete 66-book "
            "source envelope; downstream per-book JSON files are segmentation only."
        ),
        attributes={"type": "scope"},
    )
    encoding = _element(header, "encodingDesc")
    _element(
        encoding,
        "p",
        text=(
            "Source JSON object order, book/chapter/verse list order, numeric "
            "identifiers, and exact verse strings are preserved. Empty source text "
            "is represented by an empty verse carrier; no verse is silently skipped."
        ),
    )
    text = _element(
        root,
        "text",
        attributes={XML_ID: "bsb-text", "type": "bible"},
    )
    body = _element(text, "body", attributes={XML_ID: "bsb-body"})
    for book_index, book in enumerate(books, 1):
        book_id = f"bsb-book-{book_index:02d}"
        book_div = _element(
            body,
            "div",
            attributes={"type": "book", "n": str(book_index), XML_ID: book_id},
        )
        _element(book_div, "head", text=str(book["name"]))
        chapters = book["chapters"]
        assert isinstance(chapters, list)
        for chapter_index, chapter in enumerate(chapters, 1):
            chapter_number = chapter["chapter"]
            chapter_id = f"{book_id}-chapter-{chapter_index:03d}"
            chapter_div = _element(
                book_div,
                "div",
                attributes={
                    "type": "chapter",
                    "n": str(chapter_number),
                    XML_ID: chapter_id,
                },
            )
            _element(chapter_div, "head", text=str(chapter_number))
            verses = chapter["verses"]
            assert isinstance(verses, list)
            for verse_index, verse in enumerate(verses, 1):
                verse_number = verse["verse"]
                verse_id = f"{chapter_id}-verse-{verse_index:03d}"
                verse_text = verse["text"]
                assert isinstance(verse_text, str)
                _element(
                    chapter_div,
                    "ab",
                    text=verse_text if verse_text else None,
                    attributes={
                        "type": "verse",
                        "n": str(verse_number),
                        XML_ID: verse_id,
                    },
                )
    return etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )


def _crosswalk(
    translation: str, books: list[Mapping[str, object]]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {
            "id": "bsb-translation",
            "kind": "top-level-field",
            "source_path": "/translation",
            "source_field": "translation",
            "source_index": 0,
            "value": translation,
            "target": "#bsb-translation",
            "status": "represented",
        },
        {
            "id": "bsb-books",
            "kind": "top-level-field",
            "source_path": "/books",
            "source_field": "books",
            "source_index": 1,
            "value": len(books),
            "target": "#bsb-text",
            "status": "represented",
        },
    ]
    for book_index, book in enumerate(books):
        book_id = f"bsb-book-{book_index + 1:02d}"
        name = book["name"]
        assert isinstance(name, str)
        rows.append(
            {
                "id": book_id,
                "kind": "book",
                "source_path": f"/books/{book_index}",
                "source_field": "name",
                "source_index": book_index,
                "book_index": book_index,
                "book_name": name,
                "value": name,
                "target": f"#{book_id}",
                "status": "represented",
            }
        )
        chapters = book["chapters"]
        assert isinstance(chapters, list)
        for chapter_index, chapter in enumerate(chapters):
            chapter_number = chapter["chapter"]
            assert isinstance(chapter_number, int)
            chapter_id = f"{book_id}-chapter-{chapter_index + 1:03d}"
            rows.append(
                {
                    "id": chapter_id,
                    "kind": "chapter",
                    "source_path": f"/books/{book_index}/chapters/{chapter_index}",
                    "source_field": "chapter",
                    "source_index": chapter_index,
                    "book_index": book_index,
                    "chapter_index": chapter_index,
                    "book_name": name,
                    "chapter_number": chapter_number,
                    "value": chapter_number,
                    "target": f"#{chapter_id}",
                    "status": "represented",
                }
            )
            verses = chapter["verses"]
            assert isinstance(verses, list)
            for verse_index, verse in enumerate(verses):
                verse_number = verse["verse"]
                verse_text = verse["text"]
                assert isinstance(verse_number, int) and isinstance(verse_text, str)
                verse_id = f"{chapter_id}-verse-{verse_index + 1:03d}"
                rows.append(
                    {
                        "id": verse_id,
                        "kind": "verse",
                        "source_path": (
                            f"/books/{book_index}/chapters/{chapter_index}/verses/{verse_index}"
                        ),
                        "source_field": "text",
                        "source_index": verse_index,
                        "book_index": book_index,
                        "chapter_index": chapter_index,
                        "verse_index": verse_index,
                        "book_name": name,
                        "chapter_number": chapter["chapter"],
                        "verse_number": verse_number,
                        "value": verse_text,
                        "target": f"#{verse_id}",
                        "status": "represented",
                    }
                )
    return rows


def _unresolved(source_path: str, source_sha: str, config: Mapping[str, object]) -> bytes:
    rows = (
        {
            "id": "bsb-work-boundary",
            "subject": {"type": "work-id", "value": WORK_ID},
            "question": "Does the complete 66-book retained JSON witness establish the same standalone work boundary as catalog entry bsb?",
            "blocking_scope": "work-identity-and-acceptance",
            "escalation": "human-review",
            "consequence": "candidate remains nonaccepted",
            "evidence": [{"type": "retained-source", "path": source_path, "sha256": source_sha}],
        },
        {
            "id": "bsb-textual-form-and-contributor",
            "subject": {"type": "work-id", "value": WORK_ID},
            "question": "Which work-specific translation or revision statement and translator/contributor assignment should be adopted? The retained JSON marker names BSB but contains no contributor field.",
            "blocking_scope": "textual-form-and-metadata-adoption",
            "escalation": "metadata-owner-and-human-review",
            "consequence": "translator remains unrecorded rather than inferred",
            "evidence": [{"type": "retained-source", "path": source_path, "sha256": source_sha}, {"type": "work-config", "value": config.get("tradition_notes")}],
        },
        {
            "id": "bsb-edition-and-rights",
            "subject": {"type": "work-id", "value": WORK_ID},
            "question": "Does primary source or repository evidence confirm the source-edition claim Berean Standard Bible (2020) and the local CC0 claim separately from this technical reconstruction?",
            "blocking_scope": "edition-rights-and-publication",
            "escalation": "human-review",
            "consequence": "publication remains not-authorized",
            "evidence": [{"type": "work-config", "source_edition": config.get("source_edition"), "license": config.get("license")}, {"type": "retained-source", "path": source_path, "sha256": source_sha}],
        },
        {
            "id": "bsb-visual-review",
            "subject": {"type": "work-id", "value": WORK_ID},
            "question": "Complete declared CVW visual comparison of the exact source/candidate pair, including opening and ending books and representative ordinary and boundary verses.",
            "blocking_scope": "visual-review-and-human-acceptance",
            "escalation": "supported-cvw-review",
            "consequence": "visual review remains pending",
            "evidence": [{"type": "candidate-boundary", "value": "technical candidate only"}],
        },
    )
    return b"".join(_canonical(row) for row in rows)


def _provenance(
    source_manifest: SourceManifest,
    config: Mapping[str, object],
    source_bytes: bytes,
    translation: str,
) -> bytes:
    source_authority = _authority_record(source_manifest, "retained-bsb-json")
    config_authority = _authority_record(source_manifest, "work-config")
    record = {
        "contract": "ocd-37c087-bsb-candidate-provenance-v1",
        "status": "nonaccepted",
        "ticket_id": TICKET_ID,
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_manifest": {
            "path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(),
            "sha256": source_manifest.sha256,
        },
        "work_config": {
            "path": str(config_authority["path"]),
            "bytes": config_authority["bytes"],
            "sha256": config_authority["sha256"],
            "title": config["title"],
            "source_edition": config["source_edition"],
            "license": config["license"],
        },
        "source": {
            "path": str(source_authority["path"]),
            "bytes": len(source_bytes),
            "sha256": _sha(source_bytes),
            "translation": translation,
            "books": 66,
            "chapters": 1189,
            "verses": 31102,
        },
        "authority_boundary": (
            "The retained native JSON member is textual authority. The existing "
            "native bible-text parser and data/bible-text/bsb outputs are diagnostics "
            "and downstream segmentation, not TEI authority."
        ),
        "candidate_boundary": {
            "acceptance_status": "nonaccepted",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
    }
    return _canonical(record)


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    """Read the exact retained JSON and emit the five candidate members."""

    source_manifest.verify()
    _assert_manifest(source_manifest)
    source_bytes = _authority_bytes(source_manifest, "retained-bsb-json")
    payload = _strict_json(source_bytes, "retained BSB JSON")
    profile = _profile(source_manifest)
    _policy(source_manifest)
    config = _strict_json(_authority_bytes(source_manifest, "work-config"), "BSB config")
    translation, books = _validate_payload(payload, profile)
    rows = _crosswalk(translation, books)
    source_sha = _sha(source_bytes)
    accountability = {
        "contract": "ocd-37c087-bsb-source-accountability-v1",
        "ticket_id": TICKET_ID,
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_sha256": source_sha,
        "source_bytes": len(source_bytes),
        "source_top_level_keys": ["translation", "books"],
        "source_envelope": {
            "books": 66,
            "chapters": 1189,
            "verses": 31102,
            "nonempty_verses": 31086,
            "empty_verses": 16,
        },
        "observation_counts": {
            "top_level_fields": 2,
            "books": 66,
            "chapters": 1189,
            "verses": 31102,
            "represented": len(rows),
            "omitted": 0,
            "duplicate": 0,
            "invented": 0,
        },
        "excluded": [],
        "crosswalk": rows,
    }
    readme = _authority_bytes(source_manifest, "source-attribution-readme")
    return {
        "content.tei.xml": _build_tei(
            source_manifest, config, source_bytes, translation, books
        ),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _provenance(
            source_manifest, config, source_bytes, translation
        ),
        "unresolved.jsonl": _unresolved(
            str(_authority_record(source_manifest, "retained-bsb-json")["path"]),
            source_sha,
            config,
        ),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__ = (
    "CONVERTER_ID",
    "CONVERTER_VERSION",
    "_convert",
)
