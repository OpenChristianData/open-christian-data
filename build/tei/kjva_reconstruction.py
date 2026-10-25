"""Source-bound retained-JSON reconstruction for LIB-023 KJVA only."""

from __future__ import annotations

import hashlib
import json
from xml.etree import ElementTree as ET


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_PATH = "raw/bible_databases/formats/json/KJVA.json"
SOURCE_AUTHORITY = "kjva-source"
PROFILE_AUTHORITY = "kjva-profile"
POLICY_AUTHORITY = "kjva-policy"
CONFIG_AUTHORITY = "kjva-config"


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
                raise ValueError(f"KJVA {label} duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"KJVA {label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"KJVA {label} must be a JSON object")
    return value


def _identifier(profile: dict[str, object], kind: str, **values: int) -> str:
    identities = profile["tei_identity"]
    assert isinstance(identities, dict)
    return str(identities[f"{kind}_id_pattern"]).format(**values)


def convert(manifest):
    manifest.verify()
    source_bytes = manifest.authority_path(SOURCE_AUTHORITY).read_bytes()
    profile_bytes = manifest.authority_path(PROFILE_AUTHORITY).read_bytes()
    policy_bytes = manifest.authority_path(POLICY_AUTHORITY).read_bytes()
    profile = _strict_object(profile_bytes, "profile")
    policy = _strict_object(policy_bytes, "policy")
    config = _strict_object(
        manifest.authority_path(CONFIG_AUTHORITY).read_bytes(), "work config"
    )
    if (
        profile.get("contract") != "ocd-kjva-reconstruction-profile-v1"
        or profile.get("work_id") != "kjva"
        or policy.get("contract") != "ocd-kjva-independent-validation-policy-v1"
        or policy.get("work_id") != "kjva"
    ):
        raise ValueError("KJVA profile or policy identity drift")
    expected_source = profile.get("source_member")
    policy_source = policy.get("source_member")
    if (
        expected_source
        != {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": _sha(source_bytes),
        }
        or policy_source
        != {"path": SOURCE_PATH, "sha256": _sha(source_bytes)}
        or config.get("resource_id") != "kjva"
        or config.get("source_file") != SOURCE_PATH
    ):
        raise ValueError("KJVA source/config/profile binding drift")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"KJVA source duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        source = json.loads(source_bytes.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("KJVA source is not strict UTF-8 JSON") from exc
    if not isinstance(source, dict) or list(source) != ["translation", "books"]:
        raise ValueError("KJVA source root keys/order drift")
    if source.get("translation") != profile.get("source_translation_label"):
        raise ValueError("KJVA source translation label drift")
    books = source.get("books")
    if not isinstance(books, list) or not books:
        raise ValueError("KJVA books array is missing or empty")

    expected_keys = {
        "book": ["name", "chapters"],
        "chapter": ["chapter", "verses"],
        "verse": ["verse", "text"],
    }
    states = {
        name: 0
        for name in (
            "missing",
            "null",
            "empty_string",
            "zero_integer",
            "false_boolean",
            "empty_array",
        )
    }
    key_counts = {name: 0 for name in ("root", "book", "chapter", "verse")}
    arrays = 1
    leading = trailing = chapters_total = verses_total = 0
    field_rows: list[dict[str, object]] = []
    carriers: list[dict[str, object]] = []

    def observe(value: object) -> str:
        if value is None:
            states["null"] += 1
            return "null"
        if isinstance(value, bool):
            if not value:
                states["false_boolean"] += 1
            return "boolean"
        if type(value) is int:
            if value == 0:
                states["zero_integer"] += 1
            return "integer"
        if isinstance(value, str):
            if not value:
                states["empty_string"] += 1
            return "string"
        if isinstance(value, list):
            if not value:
                states["empty_array"] += 1
                return "empty_array"
            return "nonempty_array"
        return "object" if isinstance(value, dict) else type(value).__name__

    def exact_keys(record: dict[str, object], shape: str, pointer: str) -> None:
        expected = expected_keys[shape] if shape != "root" else ["translation", "books"]
        states["missing"] += sum(key not in record for key in expected)
        if list(record) != expected:
            raise ValueError(f"KJVA {shape} keys/order drift at {pointer or '/'}")
        key_counts[shape] += 1

    def add_scalar(pointer: str, value: object, target: str, attribute: str | None) -> dict[str, object]:
        json_type = observe(value)
        if json_type == "string":
            if not isinstance(value, str) or not value:
                raise ValueError(f"KJVA empty text field at {pointer}")
            state = "nonempty_string"
        elif json_type == "integer":
            if type(value) is not int or value <= 0:
                raise ValueError(f"KJVA nonpositive/noninteger number at {pointer}")
            state = "positive_integer"
        else:
            raise ValueError(f"KJVA unsupported scalar state at {pointer}: {json_type}")
        row = {
            "pointer": pointer,
            "json_type": json_type,
            "state": state,
            "value_sha256": _sha(_canonical(value)),
            "target": target,
            "attribute": attribute,
            "disposition": "preserved",
        }
        field_rows.append(row)
        return {"name": pointer.rsplit("/", 1)[-1], "state": state, "value_sha256": row["value_sha256"]}

    exact_keys(source, "root", "")
    translation = source["translation"]
    root_fields = [
        add_scalar("/translation", translation, "kjva-source-label", None),
        {"name": "books", "state": observe(books), "length": len(books)},
    ]
    if not isinstance(translation, str) or not translation:
        raise ValueError("KJVA source translation label is not nonempty text")
    inventory: list[dict[str, object]] = []
    tei_books: list[tuple[dict[str, object], str, str]] = []
    for book_position, book in enumerate(books, start=1):
        book_pointer = f"/books/{book_position - 1}"
        if not isinstance(book, dict):
            raise ValueError(f"KJVA book record is not an object at {book_pointer}")
        exact_keys(book, "book", book_pointer)
        name = book["name"]
        chapter_list = book["chapters"]
        if not isinstance(name, str) or not name or not isinstance(chapter_list, list) or not chapter_list:
            raise ValueError(f"KJVA book identity/chapters invalid at {book_pointer}")
        arrays += 1
        if any(row["name"] == name for row in inventory):
            raise ValueError(f"KJVA duplicate book name at {book_pointer}")
        book_id = _identifier(profile, "book", position=book_position)
        book_title_id = f"{book_id}-title"
        book_fields = [
            add_scalar(f"{book_pointer}/name", name, book_title_id, None),
            {"name": "chapters", "state": observe(chapter_list), "length": len(chapter_list)},
        ]
        carriers.append(
            {
                "kind": "book",
                "pointer": book_pointer,
                "parent": "/books",
                "identity": {"position": book_position, "book": name},
                "keys": list(book),
                "fields": book_fields,
            }
        )
        chapter_count = len(chapter_list)
        verse_count = 0
        inventory.append(
            {"position": book_position, "name": name, "chapters": chapter_count, "verses": 0}
        )
        tei_books.append((book, book_id, book_title_id))
        for chapter_position, chapter in enumerate(chapter_list, start=1):
            chapter_pointer = f"{book_pointer}/chapters/{chapter_position - 1}"
            if not isinstance(chapter, dict):
                raise ValueError(f"KJVA chapter record is not an object at {chapter_pointer}")
            exact_keys(chapter, "chapter", chapter_pointer)
            number = chapter["chapter"]
            verse_list = chapter["verses"]
            if type(number) is not int or number != chapter_position:
                raise ValueError(f"KJVA chapter number/order drift at {chapter_pointer}")
            if not isinstance(verse_list, list) or not verse_list:
                raise ValueError(f"KJVA verse array missing or empty at {chapter_pointer}")
            arrays += 1
            chapter_id = _identifier(
                profile, "chapter", position=book_position, chapter=number
            )
            chapter_fields = [
                add_scalar(f"{chapter_pointer}/chapter", number, chapter_id, "n"),
                {"name": "verses", "state": observe(verse_list), "length": len(verse_list)},
            ]
            carriers.append(
                {
                    "kind": "chapter",
                    "pointer": chapter_pointer,
                    "parent": f"{book_pointer}/chapters",
                    "identity": {"book": name, "chapter": number},
                    "keys": list(chapter),
                    "fields": chapter_fields,
                }
            )
            chapters_total += 1
            for verse_position, verse in enumerate(verse_list, start=1):
                verse_pointer = f"{chapter_pointer}/verses/{verse_position - 1}"
                if not isinstance(verse, dict):
                    raise ValueError(f"KJVA verse record is not an object at {verse_pointer}")
                exact_keys(verse, "verse", verse_pointer)
                verse_number = verse["verse"]
                text = verse["text"]
                if type(verse_number) is not int or verse_number != verse_position:
                    raise ValueError(f"KJVA verse number/order drift at {verse_pointer}")
                if not isinstance(text, str) or not text:
                    raise ValueError(f"KJVA verse text is missing/empty at {verse_pointer}")
                verse_id = _identifier(
                    profile,
                    "verse",
                    position=book_position,
                    chapter=number,
                    verse=verse_number,
                )
                verse_fields = [
                    add_scalar(f"{verse_pointer}/verse", verse_number, verse_id, "n"),
                    add_scalar(f"{verse_pointer}/text", text, verse_id, None),
                ]
                carriers.append(
                    {
                        "kind": "verse",
                        "pointer": verse_pointer,
                        "parent": f"{chapter_pointer}/verses",
                        "identity": {
                            "book": name,
                            "chapter": number,
                            "verse": verse_number,
                        },
                        "keys": list(verse),
                        "fields": verse_fields,
                    }
                )
                verse_count += 1
                if text[0].isspace():
                    leading += 1
                if text[-1].isspace():
                    trailing += 1
        inventory[-1]["verses"] = verse_count
        if chapter_count == 0:
            raise ValueError(f"KJVA book has no chapters at {book_pointer}")
        verses_total += verse_count

    expected_counts = profile.get("expected")
    counts = {
        "members": 1,
        "books": len(books),
        "chapters": chapters_total,
        "verses": verses_total,
        "carriers": len(carriers),
        "scalar_fields": len(field_rows),
        "ordered_arrays": arrays,
    }
    expected_inventory = profile.get("ordered_book_envelope")
    if (
        inventory != expected_inventory
        or counts != expected_counts
        or states != profile.get("field_states")
        or key_counts
        != {"root": 1, "book": 80, "chapter": 1371, "verse": 36819}
        or [leading, trailing] != [23, 1466]
        or [chapters_total, verses_total] != [1371, 36819]
    ):
        raise ValueError("KJVA complete-envelope profile/accounting drift")
    expected_orders = [
        {"shape": "root", "keys": ["translation", "books"], "occurrences": 1},
        {"shape": "book", "keys": expected_keys["book"], "occurrences": key_counts["book"]},
        {"shape": "chapter", "keys": expected_keys["chapter"], "occurrences": key_counts["chapter"]},
        {"shape": "verse", "keys": expected_keys["verse"], "occurrences": key_counts["verse"]},
    ]
    if expected_orders != profile.get("object_key_orders"):
        raise ValueError("KJVA object key order profile drift")
    if profile.get("text_boundary_whitespace") != {
        "leading": leading,
        "trailing": trailing,
        "normalization": "none; preserve exact Unicode scalar sequence",
    }:
        raise ValueError("KJVA text boundary whitespace profile drift")
    partitions = profile.get("book_partitions")
    if partitions != {
        "kjv_portion_positions": [[1, 39], [54, 80]],
        "kjv_portion_books": 66,
        "apocrypha_positions": [[40, 53]],
        "apocrypha_books": 14,
    }:
        raise ValueError("KJVA book partition profile drift")

    candidate_policy = policy.get("candidate")
    if not isinstance(candidate_policy, dict):
        raise ValueError("KJVA candidate policy is invalid")
    ET.register_namespace("", TEI)

    def add(parent, local: str, text: str | None = None, **attributes):
        node = ET.SubElement(parent, f"{{{TEI}}}{local}", attributes)
        node.text = text
        return node

    root = ET.Element(f"{{{TEI}}}TEI", {f"{{{XML}}}id": "kjva"})
    header = add(root, "teiHeader")
    file_desc = add(header, "fileDesc")
    title_stmt = add(file_desc, "titleStmt")
    title = add(title_stmt, "title", str(candidate_policy["title"]))
    title.set(f"{{{XML}}}id", "kjva-title")
    publication = add(file_desc, "publicationStmt")
    add(publication, "p", str(candidate_policy["publication_notice"]))
    source_desc = add(file_desc, "sourceDesc")
    source_label = add(source_desc, "p", str(source["translation"]))
    source_label.set(f"{{{XML}}}id", "kjva-source-label")
    source_note = add(source_desc, "p", str(candidate_policy["source_note"]))
    source_note.set(f"{{{XML}}}id", "kjva-source-note")
    text_node = add(root, "text")
    body = add(text_node, "body")
    for book, book_id, title_id in tei_books:
        book_position = int(book_id.removeprefix("kjva-book-"))
        book_node = add(body, "div", type="book", n=str(book_position))
        book_node.set(f"{{{XML}}}id", book_id)
        head = add(book_node, "head", str(book["name"]))
        head.set(f"{{{XML}}}id", title_id)
        for chapter in book["chapters"]:
            chapter_number = chapter["chapter"]
            chapter_id = _identifier(
                profile,
                "chapter",
                position=book_position,
                chapter=chapter_number,
            )
            chapter_node = add(
                book_node, "div", type="chapter", n=str(chapter_number)
            )
            chapter_node.set(f"{{{XML}}}id", chapter_id)
            for verse in chapter["verses"]:
                verse_number = verse["verse"]
                verse_id = _identifier(
                    profile,
                    "verse",
                    position=book_position,
                    chapter=chapter_number,
                    verse=verse_number,
                )
                verse_node = add(
                    chapter_node,
                    "ab",
                    str(verse["text"]),
                    type="verse",
                    n=str(verse_number),
                )
                verse_node.set(f"{{{XML}}}id", verse_id)
                verse_node.set(f"{{{XML}}}space", "preserve")

    bindings = {
        authority["name"]: authority["sha256"]
        for authority in manifest.record["authorities"]
    }
    accounting = {
        "contract": "ocd-kjva-accounting-v1",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": _sha(source_bytes),
        },
        "counts": counts,
        "field_states": states,
        "root_fields": root_fields,
        "object_key_orders": expected_orders,
        "book_inventory": inventory,
        "carriers": carriers,
        "fields": field_rows,
        "excluded": [],
    }
    provenance = {
        "contract": "ocd-kjva-provenance-v1",
        "source_manifest_sha256": manifest.sha256,
        "authorities": bindings,
        "converter": dict(manifest.record["converter"]),
        "scope": str(candidate_policy["scope"]),
    }
    unresolved = b"".join(
        _canonical(row) for row in candidate_policy["unresolved"]
    )
    tei_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    return {
        "README.source.md": str(candidate_policy["readme"]).encode("utf-8"),
        "content.tei.xml": tei_bytes,
        "provenance.json": _canonical(provenance),
        "source-accountability.json": _canonical(accounting),
        "unresolved.jsonl": unresolved,
    }


convert.converter_id = "ocd-lib023-kjva-json-to-tei"
convert.converter_version = "1"
