"""Work-specific faithful TEI route for the retained JPS JSON witness."""

from __future__ import annotations

import hashlib
import json
from xml.etree import ElementTree as ET


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
SOURCE_PATH = "raw/bible_databases/formats/json/JPS.json"
SOURCE_ID = "jps-retained-json-20260919"
SOURCE_MARKER = "JPS: Jewish Publication Society Old Testament"
EXPECTED_COUNTS = {"books": 39, "chapters": 929, "verses": 23_213, "empty_text": 19}

_EXPECTED_EMPTY = {
    ("Exodus", 20, 24),
    ("Exodus", 20, 25),
    ("Exodus", 20, 26),
    ("Leviticus", 6, 22),
    ("Deuteronomy", 5, 31),
    ("Deuteronomy", 5, 32),
    ("Deuteronomy", 5, 33),
    ("I Samuel", 20, 42),
    ("I Kings", 22, 43),
    ("Malachi", 3, 19),
    ("Malachi", 3, 20),
    ("Malachi", 3, 21),
    ("Malachi", 3, 22),
    ("Malachi", 3, 23),
    ("Malachi", 3, 24),
    ("Psalms", 64, 10),
    ("Psalms", 70, 6),
    ("Psalms", 81, 1),
    ("I Chronicles", 12, 4),
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _decode_object(content: bytes, label: str) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JPS duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(content.decode("utf-8"), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JPS {label} is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JPS {label} must be an object")
    return value


def _field(
    fields: list[dict[str, object]],
    pointer: str,
    value: object,
    target: str,
    attribute: str | None = None,
) -> None:
    fields.append(
        {
            "pointer": pointer,
            "value_sha256": _sha(_canonical(value)),
            "target": target,
            "attribute": attribute,
            "disposition": "preserved",
        }
    )


def _inventory(
    source: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], dict[str, int]]:
    """Inventory JSON fields and array boundaries before constructing TEI."""
    if list(source) != ["translation", "books"]:
        raise ValueError("JPS root envelope or key order")
    if source["translation"] != SOURCE_MARKER:
        raise ValueError("JPS retained translation marker mismatch")
    books = source["books"]
    if not isinstance(books, list) or len(books) != EXPECTED_COUNTS["books"]:
        raise ValueError("JPS book envelope")

    fields: list[dict[str, object]] = []
    containers: list[dict[str, object]] = []
    empty_locations: list[str] = []
    empty_carriers: set[tuple[str, int, int]] = set()
    counts = {"books": len(books), "chapters": 0, "verses": 0, "empty_text": 0}
    _field(fields, "/translation", source["translation"], "jps-source-label")
    containers.append({"pointer": "/books", "length": len(books)})

    names: set[str] = set()
    for book_index, book in enumerate(books):
        book_pointer = f"/books/{book_index}"
        if not isinstance(book, dict) or list(book) != ["name", "chapters"]:
            raise ValueError(f"JPS book object shape/order {book_index}")
        name = book["name"]
        chapters = book["chapters"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError(f"JPS book name identity {book_index}")
        names.add(name)
        if not isinstance(chapters, list) or not chapters:
            raise ValueError(f"JPS chapter array {book_index}")
        book_id = f"jps-b{book_index + 1}"
        _field(fields, f"{book_pointer}/name", name, f"{book_id}-title")
        containers.append(
            {"pointer": f"{book_pointer}/chapters", "length": len(chapters)}
        )

        for chapter_index, chapter in enumerate(chapters):
            chapter_pointer = f"{book_pointer}/chapters/{chapter_index}"
            if not isinstance(chapter, dict) or list(chapter) != ["chapter", "verses"]:
                raise ValueError(
                    f"JPS chapter object shape/order {book_index}/{chapter_index}"
                )
            number = chapter["chapter"]
            verses = chapter["verses"]
            if type(number) is not int or number != chapter_index + 1:
                raise ValueError(f"JPS chapter numbering {book_index}/{chapter_index}")
            if not isinstance(verses, list) or not verses:
                raise ValueError(f"JPS verse array {book_index}/{chapter_index}")
            chapter_id = f"{book_id}-c{number}"
            _field(fields, f"{chapter_pointer}/chapter", number, chapter_id, "n")
            containers.append(
                {"pointer": f"{chapter_pointer}/verses", "length": len(verses)}
            )
            counts["chapters"] += 1

            for verse_index, verse in enumerate(verses):
                verse_pointer = f"{chapter_pointer}/verses/{verse_index}"
                if not isinstance(verse, dict) or list(verse) != ["verse", "text"]:
                    raise ValueError(
                        f"JPS verse object shape/order {book_index}/{chapter_index}/{verse_index}"
                    )
                verse_number = verse["verse"]
                text = verse["text"]
                if type(verse_number) is not int or verse_number != verse_index + 1:
                    raise ValueError(
                        f"JPS verse numbering {book_index}/{chapter_index}/{verse_index}"
                    )
                if not isinstance(text, str):
                    raise ValueError(
                        f"JPS verse text type {book_index}/{chapter_index}/{verse_index}"
                    )
                verse_id = f"{chapter_id}-v{verse_number}"
                _field(fields, f"{verse_pointer}/verse", verse_number, verse_id, "n")
                _field(fields, f"{verse_pointer}/text", text, verse_id)
                counts["verses"] += 1
                if text == "":
                    counts["empty_text"] += 1
                    empty_carriers.add((name, number, verse_number))
                    empty_locations.append(f"{name} {number}:{verse_number}")

    if counts != EXPECTED_COUNTS or empty_carriers != _EXPECTED_EMPTY:
        raise ValueError(
            "JPS complete source counts or explicit empty-carrier set mismatch"
        )
    return fields, containers, empty_locations, counts


def reconstruct(source_bytes: bytes) -> tuple[bytes, bytes]:
    """Return readable TEI and field/container accounting without writing files."""
    source = _decode_object(source_bytes, "source")
    fields, containers, empty_locations, counts = _inventory(source)
    books = source["books"]

    ET.register_namespace("", TEI_NS)

    def add(
        parent: ET.Element, local: str, text: str | None = None, **attrs: str
    ) -> ET.Element:
        node = ET.SubElement(parent, f"{{{TEI_NS}}}{local}", attrs)
        node.text = text
        return node

    root = ET.Element(f"{{{TEI_NS}}}TEI", {f"{{{XML_NS}}}id": "jps"})
    header = add(root, "teiHeader")
    file_desc = add(header, "fileDesc")
    title_stmt = add(file_desc, "titleStmt")
    title = add(title_stmt, "title", source["translation"])
    title.set(f"{{{XML_NS}}}id", "jps-source-label")
    publication_stmt = add(file_desc, "publicationStmt")
    add(
        publication_stmt,
        "p",
        "Nonaccepted route output; candidate and publication authorization remain pending.",
    )
    source_desc = add(file_desc, "sourceDesc")
    source_sha = _sha(source_bytes)
    add(
        source_desc,
        "p",
        f"Exact retained source: {SOURCE_PATH} (sha256:{source_sha}). The /translation value is preserved as a source label only; work, textual form, edition, rights, and print-edition completeness are not established.",
    )

    body = add(add(root, "text"), "body")
    for book_index, book in enumerate(books, start=1):
        book_id = f"jps-b{book_index}"
        book_node = add(body, "div", type="book", n=str(book_index))
        book_node.set(f"{{{XML_NS}}}id", book_id)
        head = add(book_node, "head", book["name"])
        head.set(f"{{{XML_NS}}}id", f"{book_id}-title")
        for chapter in book["chapters"]:
            chapter_number = chapter["chapter"]
            chapter_id = f"{book_id}-c{chapter_number}"
            chapter_node = add(book_node, "div", type="chapter", n=str(chapter_number))
            chapter_node.set(f"{{{XML_NS}}}id", chapter_id)
            for verse in chapter["verses"]:
                verse_id = f"{chapter_id}-v{verse['verse']}"
                verse_node = add(
                    chapter_node,
                    "ab",
                    verse["text"],
                    type="verse",
                    n=str(verse["verse"]),
                )
                verse_node.set(f"{{{XML_NS}}}id", verse_id)
                verse_node.set(f"{{{XML_NS}}}space", "preserve")

    accountability = {
        "contract": "ocd-37c236-source-accountability-v1",
        "source_sha256": source_sha,
        "selector": "/books",
        "source_label_selector": "/translation",
        "counts": counts,
        "containers": containers,
        "fields": fields,
        "empty_text_carriers": empty_locations,
        "excluded": [],
    }
    return (
        ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n",
        _canonical(accountability),
    )


def _unresolved_bytes(source_sha: str) -> bytes:
    rows = [
        {
            "question_id": "jps-work-textual-form-edition",
            "status": "unresolved",
            "observation": SOURCE_MARKER,
            "question": "The retained translation marker does not independently establish catalog work identity, textual form, edition, publication date, or constituent-volume scope.",
            "next_evidence": "Work-specific primary-source title and edition evidence; do not infer from local config or provider label.",
            "source_sha256": source_sha,
        },
        {
            "question_id": "jps-rights-and-attribution",
            "status": "unresolved",
            "question": "The upstream repository has an MIT LICENSE and its inspection report says licenses vary by translation; the JPS JSON has no translation-specific rights statement. Applicability to this text is not established.",
            "next_evidence": "Human rights review of the exact JPS textual witness and any required attribution deliverable before distribution.",
            "source_sha256": source_sha,
        },
        {
            "question_id": "jps-print-edition-completeness",
            "status": "unresolved",
            "question": "The JSON envelope exposes only a translation label, book/chapter/verse numbering, and verse strings; it contains no print-edition front matter or apparatus.",
            "next_evidence": "Primary-source witness evidence for any broader edition or print completeness claim.",
            "source_sha256": source_sha,
        },
    ]
    return b"".join(_canonical(row) for row in rows)


def _source_readme(manifest, source_sha: str) -> bytes:
    license_text = (
        manifest.authority_path("jps-upstream-license").read_bytes().decode("utf-8")
    )
    readme = (
        "# Retained JPS JSON source notes\n\n"
        f"Source: `{SOURCE_PATH}`; SHA-256 `{source_sha}`.\n\n"
        f"The retained `/translation` value is `{SOURCE_MARKER}` and is reproduced as a source label only. "
        "This route does not establish bibliographic work identity, textual form, edition/date, rights, "
        "print-edition completeness, human acceptance, or authorization to publish.\n\n"
        "The retained upstream repository README lists this translation label. Its inspection report says "
        "license status varies by translation; the JPS JSON itself has no translation-specific rights field. "
        "The upstream repository-level MIT license below is preserved as evidence, but its applicability to "
        "the JPS text is unresolved. If rights review finds it applicable to distributed material, retain "
        "the required notice.\n\n"
        "## Retained upstream repository LICENSE text\n\n"
    )
    return readme.encode("utf-8") + license_text.encode("utf-8")


def convert(manifest) -> dict[str, bytes]:
    """Supported candidate-converter seam; callers own when a package is generated."""
    manifest.verify()
    record = manifest.record
    if (
        record.get("ticket_id") != "37c-236"
        or record.get("work_id") != "jps"
        or record.get("source_id") != SOURCE_ID
    ):
        raise ValueError("JPS source manifest identity mismatch")

    source_bytes = manifest.authority_path("jps-source").read_bytes()
    config = _decode_object(
        manifest.authority_path("jps-work-config").read_bytes(), "work config"
    )
    if config.get("resource_id") != "jps" or config.get("source_file") != SOURCE_PATH:
        raise ValueError("JPS work-config route identity mismatch")
    profile = _decode_object(
        manifest.authority_path("jps-profile").read_bytes(), "profile"
    )
    if (
        profile.get("profile_id") != "jps-retained-json-complete-v1"
        or profile.get("source_member", {}).get("sha256") != _sha(source_bytes)
        or profile.get("source_selector", {}).get("content_pointer") != "/books"
    ):
        raise ValueError("JPS source profile binding mismatch")

    tei_bytes, accounting_bytes = reconstruct(source_bytes)
    source_sha = _sha(source_bytes)
    authority_bindings = {
        str(entry["name"]): str(entry["sha256"]) for entry in record["authorities"]
    }
    provenance = {
        "source_manifest_sha256": manifest.sha256,
        "authorities": authority_bindings,
        "converter": dict(record["converter"]),
        "scope": "complete exact JPS.json /books selector plus /translation source label; no edition, rights, or print-completeness claim",
    }
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": accounting_bytes,
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": _unresolved_bytes(source_sha),
        "README.source.md": _source_readme(manifest, source_sha),
    }


convert.converter_id = "ocd-lib023-jps-json-to-tei"
convert.converter_version = "1"
