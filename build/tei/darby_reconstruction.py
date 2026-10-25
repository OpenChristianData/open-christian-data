"""Source-bound retained-JSON reconstruction for LIB-023 Darby only."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from xml.etree import ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_PATH = "raw/bible_databases/formats/json/Darby.json"
SOURCE_AUTHORITY = "darby-source"
PROFILE_AUTHORITY = "darby-profile"
POLICY_AUTHORITY = "darby-policy"

SOURCE_SELECTION = {
    "authority": SOURCE_AUTHORITY,
    "json_pointer": "",
    "selected_root_fields": ["/translation", "/books"],
    "selection": "the complete single retained JSON document",
}

EXPECTED_EMPTY_REFERENCES = {
    ("Matthew", 23, 14),
    ("Acts", 8, 37),
    ("Acts", 15, 34),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _strict_object(data: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Darby {label} duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Darby {label} contains non-JSON constant {value}")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Darby {label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Darby {label} must be a JSON object")
    return value


def _require_keys(record: dict[str, object], expected: list[str], pointer: str) -> None:
    if list(record) != expected:
        location = pointer or "/"
        raise ValueError(f"Darby source keys/order drift at {location}")


def _selector_matches(value: object) -> bool:
    return isinstance(value, Mapping) and (
        value.get("authority") == SOURCE_SELECTION["authority"]
        and value.get("json_pointer") == SOURCE_SELECTION["json_pointer"]
        and tuple(value.get("selected_root_fields", ()))
        == tuple(SOURCE_SELECTION["selected_root_fields"])
        and value.get("selection") == SOURCE_SELECTION["selection"]
    )


def _identifier(kind: str, **values: int) -> str:
    if kind == "book":
        return f"darby-book-{values['position']:03d}"
    if kind == "chapter":
        return (
            f"darby-book-{values['position']:03d}-"
            f"chapter-{values['chapter']:03d}"
        )
    return (
        f"darby-book-{values['position']:03d}-"
        f"chapter-{values['chapter']:03d}-verse-{values['verse']:03d}"
    )


def _load_bound_inputs(manifest):
    manifest.verify()
    record = manifest.record
    if record.get("work_id") != "darby" or record.get("source_id") != "darby-retained-json":
        raise ValueError("Darby manifest work/source identity drift")
    if not _selector_matches(record.get("source_selection")):
        raise ValueError("Darby manifest source selector drift")

    source_bytes = manifest.authority_path(SOURCE_AUTHORITY).read_bytes()
    profile = _strict_object(
        manifest.authority_path(PROFILE_AUTHORITY).read_bytes(), "profile"
    )
    policy = _strict_object(
        manifest.authority_path(POLICY_AUTHORITY).read_bytes(), "policy"
    )
    source_member = {
        "path": SOURCE_PATH,
        "bytes": len(source_bytes),
        "sha256": _sha(source_bytes),
    }
    if (
        profile.get("contract") != "ocd-darby-reconstruction-profile-v1"
        or profile.get("work_id") != "darby"
        or profile.get("source_member") != source_member
        or profile.get("source_selector") != SOURCE_SELECTION
        or policy.get("contract") != "ocd-darby-independent-validation-policy-v1"
        or policy.get("work_id") != "darby"
        or policy.get("source_member") != source_member
        or policy.get("source_selector") != SOURCE_SELECTION
    ):
        raise ValueError("Darby source/profile/policy binding drift")
    return source_bytes, profile, policy


def _account_source(
    source_bytes: bytes, profile: dict[str, object]
) -> tuple[
    dict[str, object],
    dict[str, object],
    list[tuple[dict[str, object], int, str]],
]:
    source = _strict_object(source_bytes, "source")
    _require_keys(source, ["translation", "books"], "")
    translation = source["translation"]
    books = source["books"]
    if not isinstance(translation, str) or not translation:
        raise ValueError("Darby /translation must be a present nonempty string")
    translation_profile = profile.get("translation_field")
    if not isinstance(translation_profile, dict) or translation_profile.get(
        "value"
    ) != translation:
        raise ValueError("Darby exact /translation value differs from the profile")
    if not isinstance(books, list) or not books:
        raise ValueError("Darby /books must be a nonempty array")

    field_states = {
        "missing": 0,
        "null": 0,
        "empty_string": 0,
        "zero_integer": 0,
        "false_boolean": 0,
        "empty_array": 0,
        "nonempty_string": 1,
        "positive_integer": 0,
    }
    book_inventory: list[dict[str, object]] = []
    chapter_inventory: list[dict[str, object]] = []
    verse_carriers: list[dict[str, object]] = []
    empty_text_carriers: list[dict[str, object]] = []
    chapter_total = 0
    verse_total = 0
    nonempty_text_total = 0
    leading_whitespace_total = 0
    trailing_ascii_space_total = 0
    observed_empty: set[tuple[str, int, int]] = set()
    tei_books: list[tuple[dict[str, object], int, str]] = []

    for book_position, book in enumerate(books, start=1):
        book_pointer = f"/books/{book_position - 1}"
        if not isinstance(book, dict):
            raise ValueError(f"Darby book carrier is not an object at {book_pointer}")
        _require_keys(book, ["name", "chapters"], book_pointer)
        name = book["name"]
        chapters = book["chapters"]
        if not isinstance(name, str) or not name:
            raise ValueError(f"Darby book name is invalid at {book_pointer}/name")
        if not isinstance(chapters, list) or not chapters:
            raise ValueError(f"Darby chapters array is empty at {book_pointer}")
        field_states["nonempty_string"] += 1
        book_verse_total = 0
        book_inventory.append(
            {
                "position": book_position,
                "name": name,
                "chapter_count": len(chapters),
                "verse_carrier_count": 0,
            }
        )
        tei_books.append((book, book_position, _identifier("book", position=book_position)))

        for chapter_position, chapter in enumerate(chapters, start=1):
            chapter_pointer = f"{book_pointer}/chapters/{chapter_position - 1}"
            if not isinstance(chapter, dict):
                raise ValueError(
                    f"Darby chapter carrier is not an object at {chapter_pointer}"
                )
            _require_keys(chapter, ["chapter", "verses"], chapter_pointer)
            chapter_number = chapter["chapter"]
            verses = chapter["verses"]
            if type(chapter_number) is not int or chapter_number != chapter_position:
                raise ValueError(
                    f"Darby chapter number/order drift at {chapter_pointer}/chapter"
                )
            if not isinstance(verses, list) or not verses:
                raise ValueError(f"Darby verses array is empty at {chapter_pointer}")
            field_states["positive_integer"] += 1
            chapter_inventory.append(
                {
                    "book_position": book_position,
                    "book": name,
                    "position": chapter_position,
                    "number": chapter_number,
                    "verse_carrier_count": len(verses),
                }
            )
            chapter_total += 1

            for verse_position, verse in enumerate(verses, start=1):
                verse_pointer = f"{chapter_pointer}/verses/{verse_position - 1}"
                if not isinstance(verse, dict):
                    raise ValueError(
                        f"Darby verse carrier is not an object at {verse_pointer}"
                    )
                _require_keys(verse, ["verse", "text"], verse_pointer)
                verse_number = verse["verse"]
                text = verse["text"]
                if type(verse_number) is not int or verse_number != verse_position:
                    raise ValueError(
                        f"Darby verse number/order drift at {verse_pointer}/verse"
                    )
                if not isinstance(text, str):
                    raise ValueError(f"Darby text is not a string at {verse_pointer}/text")
                text_state = "empty_string" if text == "" else "nonempty_string"
                text_digest = _sha(text.encode("utf-8"))
                field_states[text_state] += 1
                field_states["positive_integer"] += 1
                if text:
                    nonempty_text_total += 1
                    leading_whitespace_total += int(text[0].isspace())
                    trailing_ascii_space_total += int(text.endswith(" "))

                carrier = {
                    "json_pointer": verse_pointer,
                    "identity": {
                        "book_position": book_position,
                        "book": name,
                        "chapter": chapter_number,
                        "verse": verse_number,
                    },
                    "carrier_state": "present",
                    "text_field_state": "present",
                    "text_value_state": text_state,
                    "text_value_sha256": text_digest,
                }
                verse_carriers.append(carrier)
                if text == "":
                    reference = (name, chapter_number, verse_number)
                    observed_empty.add(reference)
                    empty_text_carriers.append(
                        {
                            "reference": f"{name} {chapter_number}:{verse_number}",
                            "book_position": book_position,
                            "chapter": chapter_number,
                            "verse": verse_number,
                            "json_pointer": verse_pointer,
                            "carrier_state": "present",
                            "text_field_state": "present",
                            "text_value_state": "empty_string",
                            "text_value_sha256": text_digest,
                        }
                    )
                if (name, chapter_number, verse_number) == ("Genesis", 1, 1):
                    if text != profile["source_text_example"]["exact_value"]:
                        raise ValueError("Darby Genesis 1:1 exact source value drift")
                verse_total += 1
                book_verse_total += 1
        book_inventory[-1]["verse_carrier_count"] = book_verse_total

    object_key_orders = [
        {"shape": "root", "keys": ["translation", "books"], "occurrences": 1},
        {"shape": "book", "keys": ["name", "chapters"], "occurrences": len(books)},
        {
            "shape": "chapter",
            "keys": ["chapter", "verses"],
            "occurrences": chapter_total,
        },
        {
            "shape": "verse",
            "keys": ["verse", "text"],
            "occurrences": verse_total,
        },
    ]
    counts = {
        "source_members": 1,
        "books": len(books),
        "chapters": chapter_total,
        "verse_carriers": verse_total,
        "nonempty_text_values": nonempty_text_total,
        "empty_text_values": len(empty_text_carriers),
        "missing_text_fields": 0,
        "null_text_fields": 0,
        "unknown_object_keys": 0,
        "scalar_fields": 1 + len(books) + chapter_total + (verse_total * 2),
        "ordered_arrays": 1 + len(books) + chapter_total,
        "leading_whitespace_text_values": leading_whitespace_total,
        "trailing_ascii_space_text_values": trailing_ascii_space_total,
    }
    if counts != profile.get("expected"):
        raise ValueError("Darby complete source counts differ from the profile")
    if field_states != profile.get("field_states"):
        raise ValueError("Darby source field-state counts differ from the profile")
    if object_key_orders != profile.get("object_key_orders"):
        raise ValueError("Darby source object-key inventory differs from the profile")
    if observed_empty != EXPECTED_EMPTY_REFERENCES:
        raise ValueError("Darby present empty-text carrier set differs from policy")
    if empty_text_carriers != profile.get("empty_text_carriers"):
        raise ValueError("Darby present empty-text carrier locations differ from profile")

    source_member = {
        "path": SOURCE_PATH,
        "bytes": len(source_bytes),
        "sha256": _sha(source_bytes),
    }
    accounting = {
        "contract": "ocd-darby-source-accountability-v1",
        "work_id": "darby",
        "source_member": source_member,
        "source_selection": SOURCE_SELECTION,
        "translation_field": {
            "json_pointer": "/translation",
            "value": translation,
            "field_state": "present_nonempty_string",
            "value_sha256": _sha(translation.encode("utf-8")),
        },
        "counts": counts,
        "field_states": field_states,
        "object_key_orders": object_key_orders,
        "book_inventory": book_inventory,
        "chapter_inventory": chapter_inventory,
        "verse_carriers": verse_carriers,
        "empty_text_carriers": empty_text_carriers,
        "downstream_segmentation_diagnostic_only": profile[
            "downstream_segmentation_diagnostic_only"
        ],
        "excluded": [],
    }
    return source, accounting, tei_books


def _tei_bytes(
    source: dict[str, object],
    tei_books: list[tuple[dict[str, object], int, str]],
    profile: dict[str, object],
    policy: dict[str, object],
) -> bytes:
    ET.register_namespace("", TEI)

    def add(parent, local: str, text: str | None = None, attributes=None):
        node = ET.SubElement(parent, f"{{{TEI}}}{local}", attributes or {})
        node.text = text
        return node

    identities = profile["tei_identity"]
    root = ET.Element(
        f"{{{TEI}}}TEI", {f"{{{XML}}}id": str(identities["root_xml_id"])}
    )
    header = add(root, "teiHeader")
    file_desc = add(header, "fileDesc")
    title_stmt = add(file_desc, "titleStmt")
    add(title_stmt, "title", str(policy["candidate"]["title"]))
    publication = add(file_desc, "publicationStmt")
    add(publication, "p", str(policy["candidate"]["publication_notice"]))
    notes = add(file_desc, "notesStmt")
    add(
        notes,
        "note",
        str(policy["candidate"]["source_note"]),
        {"type": "source-label-limitation"},
    )
    source_desc = add(file_desc, "sourceDesc")
    label = add(
        source_desc,
        "bibl",
        str(source["translation"]),
        {"type": "retained-translation-label"},
    )
    label.set(f"{{{XML}}}id", "darby-translation-label")

    text_node = add(root, "text")
    body = add(text_node, "body")
    for book, position, book_id in tei_books:
        book_node = add(
            body,
            "div",
            attributes={"type": "book", "n": str(position)},
        )
        book_node.set(f"{{{XML}}}id", book_id)
        head = add(book_node, "head", str(book["name"]))
        head.set(f"{{{XML}}}id", f"{book_id}-title")
        for chapter in book["chapters"]:
            chapter_number = chapter["chapter"]
            chapter_node = add(
                book_node,
                "div",
                attributes={
                    "type": "chapter",
                    "n": str(chapter_number),
                },
            )
            chapter_node.set(
                f"{{{XML}}}id",
                _identifier(
                    "chapter", position=position, chapter=chapter_number
                ),
            )
            for verse in chapter["verses"]:
                verse_node = add(
                    chapter_node,
                    "ab",
                    str(verse["text"]),
                    {
                        "type": "verse",
                        "n": str(verse["verse"]),
                    },
                )
                verse_node.set(
                    f"{{{XML}}}id",
                    _identifier(
                        "verse",
                        position=position,
                        chapter=chapter_number,
                        verse=verse["verse"],
                    ),
                )
                verse_node.set(f"{{{XML}}}space", "preserve")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def convert(manifest):
    """Return the five standard candidate members without packaging them."""

    source_bytes, profile, policy = _load_bound_inputs(manifest)
    source, accounting, tei_books = _account_source(source_bytes, profile)
    candidate_policy = policy["candidate"]
    authorities = {
        str(authority["name"]): str(authority["sha256"])
        for authority in manifest.record["authorities"]
    }
    provenance = {
        "contract": "ocd-darby-provenance-v1",
        "source_manifest_sha256": manifest.sha256,
        "authorities": authorities,
        "converter": dict(manifest.record["converter"]),
        "scope": str(candidate_policy["scope"]),
    }
    unresolved = b"".join(
        _canonical(item) for item in candidate_policy["unresolved"]
    )
    return {
        "README.source.md": str(candidate_policy["readme"]).encode("utf-8"),
        "content.tei.xml": _tei_bytes(source, tei_books, profile, policy),
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accounting),
        "unresolved.jsonl": unresolved,
    }


convert.converter_id = "ocd-lib023-darby-json-to-tei"
convert.converter_version = "1"
