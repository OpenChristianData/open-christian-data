"""Source-bound retained-JSON reconstruction for the LIB-023 Webster route."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from xml.etree import ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_PATH = "raw/bible_databases/formats/json/Webster.json"
SOURCE_SELECTION = {
    "authority": "webster-source",
    "json_pointer": "",
    "selected_root_fields": ["/translation", "/books"],
    "selection": "the complete single retained JSON document",
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _object(data: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Webster {label} duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Webster {label} contains non-JSON constant {value}")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Webster {label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Webster {label} must be an object")
    return value


def _require_keys(record: dict[str, object], expected: list[str], pointer: str) -> None:
    if list(record) != expected:
        raise ValueError(f"Webster source keys/order drift at {pointer or '/'}")


def _identifier(kind: str, **values: int) -> str:
    if kind == "book":
        return f"webster-book-{values['position']:03d}"
    if kind == "chapter":
        return f"webster-book-{values['position']:03d}-chapter-{values['chapter']:03d}"
    return f"webster-book-{values['position']:03d}-chapter-{values['chapter']:03d}-verse-{values['verse']:03d}"


def _selector_matches(value: object) -> bool:
    return isinstance(value, Mapping) and value.get("authority") == SOURCE_SELECTION["authority"] and value.get("json_pointer") == "" and tuple(value.get("selected_root_fields", ())) == tuple(SOURCE_SELECTION["selected_root_fields"]) and value.get("selection") == SOURCE_SELECTION["selection"]


def _load_inputs(manifest):
    manifest.verify()
    if manifest.record.get("work_id") != "webster" or manifest.record.get("source_id") != "webster-retained-json":
        raise ValueError("Webster manifest work/source identity drift")
    if not _selector_matches(manifest.record.get("source_selection")):
        raise ValueError("Webster manifest source selector drift")
    source_bytes = manifest.authority_path("webster-source").read_bytes()
    profile = _object(manifest.authority_path("webster-profile").read_bytes(), "profile")
    policy = _object(manifest.authority_path("webster-policy").read_bytes(), "policy")
    config = _object(manifest.authority_path("webster-config").read_bytes(), "config")
    member = {"path": SOURCE_PATH, "bytes": len(source_bytes), "sha256": _digest(source_bytes)}
    if (
        profile.get("contract") != "ocd-webster-reconstruction-profile-v1"
        or policy.get("contract") != "ocd-webster-independent-validation-policy-v1"
        or profile.get("work_id") != "webster"
        or policy.get("work_id") != "webster"
        or profile.get("source_member") != member
        or policy.get("source_member") != {"path": SOURCE_PATH, "sha256": member["sha256"]}
        or profile.get("source_selector") != SOURCE_SELECTION
        or policy.get("source_selection") != SOURCE_SELECTION
        or config.get("resource_id") != "webster"
        or config.get("source_file") != SOURCE_PATH
        or config.get("source_format") != "JSON"
    ):
        raise ValueError("Webster source/profile/policy/config binding drift")
    return source_bytes, profile, policy


def _account_source(source_bytes: bytes, profile: dict[str, object]):
    source = _object(source_bytes, "source")
    _require_keys(source, ["translation", "books"], "")
    translation = source["translation"]
    books = source["books"]
    if not isinstance(translation, str) or not translation:
        raise ValueError("Webster /translation must be a present nonempty string")
    translation_profile = profile["translation_field"]
    if not isinstance(translation_profile, dict) or translation_profile.get("value") != translation:
        raise ValueError("Webster exact /translation value differs from profile")
    if not isinstance(books, list) or not books:
        raise ValueError("Webster /books must be a nonempty array")

    states = {name: 0 for name in ("missing", "null", "empty_string", "zero_integer", "false_boolean", "empty_array", "nonempty_string", "positive_integer")}
    states["nonempty_string"] = 1
    book_inventory: list[dict[str, object]] = []
    chapter_inventory: list[dict[str, object]] = []
    verse_carriers: list[dict[str, object]] = []
    tei_books: list[tuple[dict[str, object], int, str]] = []
    chapter_total = verse_total = nonempty_text_total = 0
    leading_total = trailing_total = 0

    for book_position, book in enumerate(books, 1):
        book_pointer = f"/books/{book_position - 1}"
        if not isinstance(book, dict):
            raise ValueError(f"Webster book carrier is not an object at {book_pointer}")
        _require_keys(book, ["name", "chapters"], book_pointer)
        name, chapters = book["name"], book["chapters"]
        if not isinstance(name, str) or not name or not isinstance(chapters, list) or not chapters:
            raise ValueError(f"Webster book identity/chapters invalid at {book_pointer}")
        states["nonempty_string"] += 1
        book_verse_total = 0
        tei_books.append((book, book_position, _identifier("book", position=book_position)))
        for chapter_position, chapter in enumerate(chapters, 1):
            chapter_pointer = f"{book_pointer}/chapters/{chapter_position - 1}"
            if not isinstance(chapter, dict):
                raise ValueError(f"Webster chapter carrier is not an object at {chapter_pointer}")
            _require_keys(chapter, ["chapter", "verses"], chapter_pointer)
            number, verses = chapter["chapter"], chapter["verses"]
            if type(number) is not int or number != chapter_position or not isinstance(verses, list) or not verses:
                raise ValueError(f"Webster chapter sequence/list drift at {chapter_pointer}")
            states["positive_integer"] += 1
            chapter_inventory.append({"book_position": book_position, "book": name, "position": chapter_position, "number": number, "verse_carrier_count": len(verses)})
            chapter_total += 1
            for verse_position, verse in enumerate(verses, 1):
                verse_pointer = f"{chapter_pointer}/verses/{verse_position - 1}"
                if not isinstance(verse, dict):
                    raise ValueError(f"Webster verse carrier is not an object at {verse_pointer}")
                _require_keys(verse, ["verse", "text"], verse_pointer)
                verse_number, text = verse["verse"], verse["text"]
                if type(verse_number) is not int or verse_number != verse_position:
                    raise ValueError(f"Webster verse sequence drift at {verse_pointer}/verse")
                if not isinstance(text, str) or not text:
                    raise ValueError(f"Webster text must be a nonempty string at {verse_pointer}/text")
                states["positive_integer"] += 1
                states["nonempty_string"] += 1
                nonempty_text_total += 1
                leading_total += int(text[0].isspace())
                trailing_total += int(text.endswith(" "))
                verse_carriers.append({"json_pointer": verse_pointer, "identity": {"book_position": book_position, "book": name, "chapter": number, "verse": verse_number}, "carrier_state": "present", "text_field_state": "present", "text_value_state": "nonempty_string", "text_value_sha256": _digest(text.encode("utf-8"))})
                verse_total += 1
                book_verse_total += 1
        book_inventory.append({"position": book_position, "name": name, "chapter_count": len(chapters), "verse_carrier_count": book_verse_total})

    orders = [
        {"shape": "root", "keys": ["translation", "books"], "occurrences": 1},
        {"shape": "book", "keys": ["name", "chapters"], "occurrences": len(books)},
        {"shape": "chapter", "keys": ["chapter", "verses"], "occurrences": chapter_total},
        {"shape": "verse", "keys": ["verse", "text"], "occurrences": verse_total},
    ]
    counts = {"source_members": 1, "books": len(books), "chapters": chapter_total, "verse_carriers": verse_total, "nonempty_text_values": nonempty_text_total, "empty_text_values": 0, "missing_text_fields": 0, "null_text_fields": 0, "unknown_object_keys": 0, "scalar_fields": 1 + len(books) + chapter_total + verse_total * 2, "ordered_arrays": 1 + len(books) + chapter_total, "leading_whitespace_text_values": leading_total, "trailing_ascii_space_text_values": trailing_total}
    expected_inventory = [{"position": row["position"], "name": row["name"], "chapters": row["chapter_count"], "verses": row["verse_carrier_count"]} for row in book_inventory]
    if counts != profile["expected"] or states != profile["field_states"] or orders != profile["object_key_orders"] or expected_inventory != profile["ordered_book_envelope"] or [leading_total, trailing_total] != [0, 0]:
        raise ValueError("Webster complete source profile/accounting drift")
    accounting = {"contract": "ocd-webster-source-accountability-v1", "work_id": "webster", "source_member": {"path": SOURCE_PATH, "bytes": len(source_bytes), "sha256": _digest(source_bytes)}, "source_selection": SOURCE_SELECTION, "translation_field": {"json_pointer": "/translation", "value": translation, "field_state": "present_nonempty_string", "value_sha256": _digest(translation.encode("utf-8"))}, "counts": counts, "field_states": states, "object_key_orders": orders, "book_inventory": book_inventory, "chapter_inventory": chapter_inventory, "verse_carriers": verse_carriers, "empty_text_carriers": [], "downstream_segmentation_diagnostic_only": profile["downstream_segmentation_diagnostic_only"], "excluded": []}
    return source, accounting, tei_books


def _tei_bytes(source: dict[str, object], tei_books, profile: dict[str, object], policy: dict[str, object]) -> bytes:
    ET.register_namespace("", TEI)

    def add(parent, local: str, text: str | None = None, attributes=None):
        node = ET.SubElement(parent, f"{{{TEI}}}{local}", attributes or {})
        node.text = text
        return node

    root = ET.Element(f"{{{TEI}}}TEI", {f"{{{XML}}}id": "webster"})
    header = add(root, "teiHeader")
    file_desc = add(header, "fileDesc")
    title_stmt = add(file_desc, "titleStmt")
    add(title_stmt, "title", str(policy["candidate"]["title"]))
    publication = add(file_desc, "publicationStmt")
    add(publication, "p", str(policy["candidate"]["publication_notice"]))
    notes = add(file_desc, "notesStmt")
    add(notes, "note", str(policy["candidate"]["source_note"]), {"type": "source-label-limitation"})
    source_desc = add(file_desc, "sourceDesc")
    label = add(source_desc, "bibl", str(source["translation"]), {"type": "retained-translation-label"})
    label.set(f"{{{XML}}}id", "webster-translation-label")
    body = add(add(root, "text"), "body")
    for book, position, book_id in tei_books:
        book_node = add(body, "div", attributes={"type": "book", "n": str(position)})
        book_node.set(f"{{{XML}}}id", book_id)
        head = add(book_node, "head", str(book["name"]))
        head.set(f"{{{XML}}}id", f"{book_id}-title")
        for chapter in book["chapters"]:
            number = chapter["chapter"]
            chapter_node = add(book_node, "div", attributes={"type": "chapter", "n": str(number)})
            chapter_node.set(f"{{{XML}}}id", _identifier("chapter", position=position, chapter=number))
            for verse in chapter["verses"]:
                verse_node = add(chapter_node, "ab", str(verse["text"]), {"type": "verse", "n": str(verse["verse"])})
                verse_node.set(f"{{{XML}}}id", _identifier("verse", position=position, chapter=number, verse=verse["verse"]))
                verse_node.set(f"{{{XML}}}space", "preserve")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def convert(manifest):
    source_bytes, profile, policy = _load_inputs(manifest)
    source, accounting, tei_books = _account_source(source_bytes, profile)
    authorities = {str(row["name"]): str(row["sha256"]) for row in manifest.record["authorities"]}
    candidate_policy = policy["candidate"]
    provenance = {"contract": "ocd-webster-provenance-v1", "source_manifest_sha256": manifest.sha256, "authorities": authorities, "converter": dict(manifest.record["converter"]), "scope": str(candidate_policy["scope"])}
    unresolved = b"".join(_canonical(item) for item in candidate_policy["unresolved"])
    return {"README.source.md": str(candidate_policy["readme"]).encode("utf-8"), "content.tei.xml": _tei_bytes(source, tei_books, profile, policy), "provenance.json": _canonical(provenance), "source-accountability.json": _canonical(accounting), "unresolved.jsonl": unresolved}


convert.converter_id = "ocd-lib023-webster-json-to-tei"
convert.converter_version = "1"
