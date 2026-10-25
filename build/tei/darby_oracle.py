"""Independent source-byte oracle for the LIB-023 Darby route.

This module does not import or call the producer. It independently inventories
the retained JSON and compares the resulting expectations to the actual TEI
tree and accountability member.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from collections.abc import Mapping
from pathlib import Path

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_PATH = "raw/bible_databases/formats/json/Darby.json"
ACCOUNTABILITY_SCHEMA_PATH = (
    "sources/bible-text/darby/darby.source-accountability.schema.json"
)

_EXPECTED_AUTHORITIES = (
    ("darby-source", SOURCE_PATH, "primary-source"),
    (
        "darby-profile",
        "sources/bible-text/darby/darby.reconstruction-profile.json",
        "complete-source-feature-profile",
    ),
    (
        "darby-policy",
        "sources/bible-text/darby/darby.validation-policy.json",
        "independent-validation-policy",
    ),
    (
        "darby-accountability-schema",
        ACCOUNTABILITY_SCHEMA_PATH,
        "source-accountability-schema",
    ),
    (
        "tei-p5-xsd",
        "ocd_kernel/tei/vendor/xsd/tei_all.xsd",
        "tei-validation-schema",
    ),
    (
        "tei-xml-xsd",
        "ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd",
        "tei-validation-schema-import",
    ),
    (
        "tei-teix-xsd",
        "ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd",
        "tei-validation-schema-import",
    ),
    (
        "candidate-package-schema",
        "ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json",
        "candidate-package-schema",
    ),
    (
        "candidate-cli",
        "build/tools/reconstruct_candidate.py",
        "route-runtime-dependency",
    ),
    ("build-package-init", "build/__init__.py", "route-runtime-dependency"),
    (
        "reconstruction-contract",
        "ocd_kernel/reconstruction/contract.py",
        "route-runtime-dependency",
    ),
    (
        "reconstruction-verifier",
        "ocd_kernel/reconstruction/verifier.py",
        "route-runtime-dependency",
    ),
    (
        "destination-policy",
        "ocd_kernel/reconstruction/destination_policy.py",
        "route-runtime-dependency",
    ),
    ("kernel-init", "ocd_kernel/__init__.py", "route-runtime-dependency"),
    (
        "reconstruction-init",
        "ocd_kernel/reconstruction/__init__.py",
        "route-runtime-dependency",
    ),
)

_EXPECTED_EMPTY = {
    ("Matthew", 23, 14): (40, "/books/39/chapters/22/verses/13"),
    ("Acts", 8, 37): (44, "/books/43/chapters/7/verses/36"),
    ("Acts", 15, 34): (44, "/books/43/chapters/14/verses/33"),
}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _decode(data: bytes, label: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Darby oracle duplicate {label} key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Darby oracle {label} contains non-JSON constant {value}")

    try:
        return json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Darby oracle {label} is not strict UTF-8 JSON") from exc


def _object(data: bytes, label: str) -> dict[str, object]:
    value = _decode(data, label)
    if not isinstance(value, dict):
        raise ValueError(f"Darby oracle {label} must be an object")
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _authority_map(source_manifest) -> dict[str, Mapping[str, object]]:
    rows = source_manifest.record.get("authorities")
    if not isinstance(rows, tuple):
        raise ValueError("Darby oracle manifest authority set is invalid")
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Darby oracle manifest authority row is invalid")
        name = row.get("name")
        if not isinstance(name, str) or not name or name in result:
            raise ValueError("Darby oracle manifest authority names are invalid")
        result[name] = row
    return result


def _selector_matches(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("authority") == "darby-source"
        and value.get("json_pointer") == ""
        and tuple(value.get("selected_root_fields", ()))
        == ("/translation", "/books")
        and value.get("selection") == "the complete single retained JSON document"
    )


def _check_authorities(source_manifest, profile, policy):
    authorities = _authority_map(source_manifest)
    if set(authorities) != {row[0] for row in _EXPECTED_AUTHORITIES}:
        raise ValueError("Darby oracle manifest authority inventory drift")

    digests: dict[str, str] = {}
    for name, path, role in _EXPECTED_AUTHORITIES:
        row = authorities[name]
        if row.get("path") != path or row.get("role") != role:
            raise ValueError(f"Darby oracle authority path/role drift: {name}")
        # Resolve logical raw/ paths through the configured storage topology.
        resolved = source_manifest.authority_path(name)
        content = resolved.read_bytes()
        if (
            row.get("bytes") != len(content)
            or row.get("sha256") != _digest(content)
        ):
            raise ValueError(f"Darby oracle authority bytes drift: {name}")
        digests[name] = _digest(content)

    source = authorities["darby-source"]
    if source.get("path") != SOURCE_PATH:
        raise ValueError("Darby oracle retained-source path mismatch")
    schemas = {
        "tei-p5-xsd": policy["schema"]["tei_p5"],
        "tei-xml-xsd": policy["schema"]["tei_xml_import"],
        "tei-teix-xsd": policy["schema"]["tei_teix_import"],
        "candidate-package-schema": policy["schema"]["candidate_package"],
        "darby-accountability-schema": {
            "path": policy["accountability"]["schema_path"],
            "sha256": policy["accountability"]["schema_sha256"],
        },
    }
    for name, expected in schemas.items():
        row = authorities[name]
        expected_path = expected.get("path")
        expected_digest = expected.get("sha256")
        if row.get("path") != expected_path or row.get("sha256") != expected_digest:
            raise ValueError(f"Darby oracle schema binding mismatch: {name}")

    route = policy["route_dependencies"]
    route_authorities = {
        "candidate-cli": route["candidate_cli"],
        "build-package-init": route["build_package_init"],
        "reconstruction-contract": route["contract"],
        "reconstruction-verifier": route["verifier"],
        "destination-policy": route["destination_policy"],
        "kernel-init": "ocd_kernel/__init__.py",
        "reconstruction-init": "ocd_kernel/reconstruction/__init__.py",
    }
    for name, expected_path in route_authorities.items():
        if authorities[name].get("path") != expected_path:
            raise ValueError(f"Darby oracle runtime authority mismatch: {name}")

    source_selection = source_manifest.record.get("source_selection")
    if not _selector_matches(source_selection):
        raise ValueError("Darby oracle manifest source selector drift")
    converter = source_manifest.record.get("converter")
    validator = source_manifest.record.get("validator")
    if not isinstance(converter, Mapping) or not isinstance(validator, Mapping):
        raise ValueError("Darby oracle callable bindings are invalid")
    expected_converter = {
        "id": "ocd-lib023-darby-json-to-tei",
        "version": "1",
        "callable": "convert",
        "implementation_path": "build/tei/darby_reconstruction.py",
    }
    expected_validator = {
        "id": "ocd-lib023-darby-independent-oracle",
        "version": "1",
        "callable": "oracle",
        "implementation_path": "build/tei/darby_oracle.py",
    }
    if any(converter.get(key) != value for key, value in expected_converter.items()):
        raise ValueError("Darby oracle converter binding drift")
    if any(validator.get(key) != value for key, value in expected_validator.items()):
        raise ValueError("Darby oracle validator binding drift")
    for binding, name in (
        (converter, "darby_reconstruction"),
        (validator, "darby_oracle"),
    ):
        path = source_manifest.repository_root / str(binding["implementation_path"])
        if binding.get("implementation_sha256") != _digest(path.read_bytes()):
            raise ValueError(f"Darby oracle {name} implementation digest drift")

    package_schema = source_manifest.record.get("package_schema")
    schema_authority = authorities["candidate-package-schema"]
    if (
        not isinstance(package_schema, Mapping)
        or package_schema.get("path") != schema_authority.get("path")
        or package_schema.get("sha256") != schema_authority.get("sha256")
    ):
        raise ValueError("Darby oracle candidate package schema binding drift")
    return digests


def _expect_keys(record: dict[str, object], expected: tuple[str, ...], pointer: str) -> None:
    if tuple(record) != expected:
        location = pointer or "/"
        raise ValueError(f"Darby oracle source keys/order drift at {location}")


def _derive_source_accountability(source_bytes, profile):
    decoded = _decode(source_bytes, "source")
    if not isinstance(decoded, dict):
        raise ValueError("Darby oracle source root is not an object")
    source = decoded
    _expect_keys(source, ("translation", "books"), "")
    label = source["translation"]
    books = source["books"]
    source_label_profile = profile["translation_field"]
    if (
        not isinstance(label, str)
        or not label
        or label != source_label_profile["value"]
        or source_label_profile["json_pointer"] != "/translation"
    ):
        raise ValueError("Darby oracle retained translation field differs from profile")
    if not isinstance(books, list) or not books:
        raise ValueError("Darby oracle books array is absent or empty")

    states = {
        "missing": 0,
        "null": 0,
        "empty_string": 0,
        "zero_integer": 0,
        "false_boolean": 0,
        "empty_array": 0,
        "nonempty_string": 1,
        "positive_integer": 0,
    }
    books_seen: list[dict[str, object]] = []
    chapters_seen: list[dict[str, object]] = []
    verses_seen: list[dict[str, object]] = []
    empties_seen: list[dict[str, object]] = []
    expected_empty_seen: set[tuple[str, int, int]] = set()
    chapter_count = 0
    verse_count = 0
    nonempty_text_count = 0
    leading_count = 0
    trailing_count = 0

    for ordinal_book, book in enumerate(books, 1):
        p_book = f"/books/{ordinal_book - 1}"
        if not isinstance(book, dict):
            raise ValueError(f"Darby oracle book is not an object at {p_book}")
        _expect_keys(book, ("name", "chapters"), p_book)
        book_name = book["name"]
        book_chapters = book["chapters"]
        if not isinstance(book_name, str) or not book_name:
            raise ValueError(f"Darby oracle book name is invalid at {p_book}/name")
        if not isinstance(book_chapters, list) or not book_chapters:
            raise ValueError(f"Darby oracle book has no chapter list at {p_book}")
        states["nonempty_string"] += 1
        book_verse_count = 0

        for ordinal_chapter, chapter in enumerate(book_chapters, 1):
            p_chapter = f"{p_book}/chapters/{ordinal_chapter - 1}"
            if not isinstance(chapter, dict):
                raise ValueError(f"Darby oracle chapter is not an object at {p_chapter}")
            _expect_keys(chapter, ("chapter", "verses"), p_chapter)
            chapter_label = chapter["chapter"]
            chapter_verses = chapter["verses"]
            if type(chapter_label) is not int or chapter_label != ordinal_chapter:
                raise ValueError(f"Darby oracle chapter sequence drift at {p_chapter}")
            if not isinstance(chapter_verses, list) or not chapter_verses:
                raise ValueError(f"Darby oracle verse list is empty at {p_chapter}")
            states["positive_integer"] += 1
            chapters_seen.append(
                {
                    "book_position": ordinal_book,
                    "book": book_name,
                    "position": ordinal_chapter,
                    "number": chapter_label,
                    "verse_carrier_count": len(chapter_verses),
                }
            )
            chapter_count += 1

            for ordinal_verse, verse in enumerate(chapter_verses, 1):
                p_verse = f"{p_chapter}/verses/{ordinal_verse - 1}"
                if not isinstance(verse, dict):
                    raise ValueError(f"Darby oracle verse is not an object at {p_verse}")
                _expect_keys(verse, ("verse", "text"), p_verse)
                verse_label = verse["verse"]
                verse_text = verse["text"]
                if type(verse_label) is not int or verse_label != ordinal_verse:
                    raise ValueError(f"Darby oracle verse sequence drift at {p_verse}")
                if not isinstance(verse_text, str):
                    raise ValueError(f"Darby oracle text field is not a string at {p_verse}")
                text_state = "empty_string" if verse_text == "" else "nonempty_string"
                text_digest = _digest(verse_text.encode("utf-8"))
                states[text_state] += 1
                states["positive_integer"] += 1
                if verse_text:
                    nonempty_text_count += 1
                    leading_count += int(verse_text[0].isspace())
                    trailing_count += int(verse_text.endswith(" "))

                identity = {
                    "book_position": ordinal_book,
                    "book": book_name,
                    "chapter": chapter_label,
                    "verse": verse_label,
                }
                verses_seen.append(
                    {
                        "json_pointer": p_verse,
                        "identity": identity,
                        "carrier_state": "present",
                        "text_field_state": "present",
                        "text_value_state": text_state,
                        "text_value_sha256": text_digest,
                    }
                )
                if verse_text == "":
                    location = (book_name, chapter_label, verse_label)
                    expected_locator = _EXPECTED_EMPTY.get(location)
                    if expected_locator is None or expected_locator[1] != p_verse:
                        raise ValueError(
                            f"Darby oracle found an unlisted empty text at {p_verse}"
                        )
                    expected_empty_seen.add(location)
                    empties_seen.append(
                        {
                            "reference": f"{book_name} {chapter_label}:{verse_label}",
                            "book_position": ordinal_book,
                            "chapter": chapter_label,
                            "verse": verse_label,
                            "json_pointer": p_verse,
                            "carrier_state": "present",
                            "text_field_state": "present",
                            "text_value_state": "empty_string",
                            "text_value_sha256": text_digest,
                        }
                    )
                verse_count += 1
                book_verse_count += 1

        books_seen.append(
            {
                "position": ordinal_book,
                "name": book_name,
                "chapter_count": len(book_chapters),
                "verse_carrier_count": book_verse_count,
            }
        )

    if expected_empty_seen != set(_EXPECTED_EMPTY):
        raise ValueError("Darby oracle did not find all three present empty-text carriers")
    if source.get("translation") != profile["translation_field"]["value"]:
        raise ValueError("Darby oracle translation label mismatch")
    if source["books"][0]["chapters"][0]["verses"][0]["text"] != profile[
        "source_text_example"
    ]["exact_value"]:
        raise ValueError("Darby oracle exact Genesis 1:1 source value mismatch")

    counts = {
        "source_members": 1,
        "books": len(books_seen),
        "chapters": chapter_count,
        "verse_carriers": verse_count,
        "nonempty_text_values": nonempty_text_count,
        "empty_text_values": len(empties_seen),
        "missing_text_fields": 0,
        "null_text_fields": 0,
        "unknown_object_keys": 0,
        "scalar_fields": 1 + len(books_seen) + chapter_count + verse_count * 2,
        "ordered_arrays": 1 + len(books_seen) + chapter_count,
        "leading_whitespace_text_values": leading_count,
        "trailing_ascii_space_text_values": trailing_count,
    }
    if counts != profile["expected"]:
        raise ValueError("Darby oracle complete source counts differ from profile")
    if states != profile["field_states"]:
        raise ValueError("Darby oracle source field states differ from profile")
    orders = [
        {"shape": "root", "keys": ["translation", "books"], "occurrences": 1},
        {"shape": "book", "keys": ["name", "chapters"], "occurrences": len(books_seen)},
        {"shape": "chapter", "keys": ["chapter", "verses"], "occurrences": chapter_count},
        {"shape": "verse", "keys": ["verse", "text"], "occurrences": verse_count},
    ]
    if orders != profile["object_key_orders"]:
        raise ValueError("Darby oracle object-key order differs from profile")

    member = profile["source_member"]
    selector = profile["source_selector"]
    accounting = {
        "contract": "ocd-darby-source-accountability-v1",
        "work_id": "darby",
        "source_member": member,
        "source_selection": selector,
        "translation_field": {
            "json_pointer": "/translation",
            "value": label,
            "field_state": "present_nonempty_string",
            "value_sha256": _digest(label.encode("utf-8")),
        },
        "counts": counts,
        "field_states": states,
        "object_key_orders": orders,
        "book_inventory": books_seen,
        "chapter_inventory": chapters_seen,
        "verse_carriers": verses_seen,
        "empty_text_carriers": empties_seen,
        "downstream_segmentation_diagnostic_only": profile[
            "downstream_segmentation_diagnostic_only"
        ],
        "excluded": [],
    }
    return source, accounting


def _check_tree(source, tei_bytes: bytes, policy) -> None:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_blank_text=False,
    )
    try:
        root = etree.fromstring(tei_bytes, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Darby oracle candidate is not well-formed XML") from exc

    def q(local: str) -> str:
        return f"{{{TEI}}}{local}"

    xml_id = f"{{{XML}}}id"
    xml_space = f"{{{XML}}}space"
    if root.tag != q("TEI") or dict(root.attrib) != {xml_id: "darby"}:
        raise ValueError("Darby oracle TEI root identity/attributes drift")
    if root.getroottree().docinfo.doctype:
        raise ValueError("Darby oracle does not permit a TEI document type")
    if [node.tag for node in root] != [q("teiHeader"), q("text")]:
        raise ValueError("Darby oracle TEI root structure drift")

    header, text_node = list(root)
    if [node.tag for node in header] != [q("fileDesc")]:
        raise ValueError("Darby oracle TEI header structure drift")
    file_desc = header[0]
    if [node.tag for node in file_desc] != [
        q("titleStmt"),
        q("publicationStmt"),
        q("notesStmt"),
        q("sourceDesc"),
    ]:
        raise ValueError("Darby oracle TEI file description structure drift")
    title_stmt, publication_stmt, notes_stmt, source_desc = list(file_desc)
    if (
        len(title_stmt) != 1
        or title_stmt[0].tag != q("title")
        or title_stmt[0].text != policy["candidate"]["title"]
    ):
        raise ValueError("Darby oracle TEI generic title mismatch")
    if (
        len(publication_stmt) != 1
        or publication_stmt[0].tag != q("p")
        or publication_stmt[0].text != policy["candidate"]["publication_notice"]
    ):
        raise ValueError("Darby oracle TEI publication notice mismatch")
    if (
        len(notes_stmt) != 1
        or notes_stmt[0].tag != q("note")
        or dict(notes_stmt[0].attrib) != {"type": "source-label-limitation"}
        or notes_stmt[0].text != policy["candidate"]["source_note"]
        or notes_stmt[0].tail is not None
    ):
        raise ValueError("Darby oracle retained-label limitation note mismatch")
    if [node.tag for node in source_desc] != [q("bibl")]:
        raise ValueError("Darby oracle TEI source description structure drift")
    source_label = source_desc[0]
    if (
        dict(source_label.attrib)
        != {"type": "retained-translation-label", xml_id: "darby-translation-label"}
        or source_label.text != source["translation"]
        or source_label.tail is not None
    ):
        raise ValueError("Darby oracle retained translation label mismatch")

    if [node.tag for node in text_node] != [q("body")]:
        raise ValueError("Darby oracle TEI text/body structure drift")
    body = text_node[0]
    observed_books = list(body)
    if len(observed_books) != len(source["books"]) or len(source["books"]) != 66:
        raise ValueError("Darby oracle book carrier count mismatch")
    if len(observed_books) != 66:
        raise ValueError("Darby oracle retained source book count is not 66")

    chapter_total = 0
    verse_total = 0
    for position, (source_book, book_node) in enumerate(
        zip(source["books"], observed_books, strict=True), start=1
    ):
        book_id = f"darby-book-{position:03d}"
        if book_node.tag != q("div") or dict(book_node.attrib) != {
            "type": "book",
            "n": str(position),
            xml_id: book_id,
        }:
            raise ValueError(f"Darby oracle book order/identity mismatch at position {position}")
        children = list(book_node)
        if not children or children[0].tag != q("head"):
            raise ValueError(f"Darby oracle book heading missing at position {position}")
        if (
            children[0].text != source_book["name"]
            or dict(children[0].attrib) != {xml_id: f"{book_id}-title"}
            or children[0].tail is not None
        ):
            raise ValueError(f"Darby oracle book name/order mismatch at position {position}")
        chapter_nodes = children[1:]
        if len(chapter_nodes) != len(source_book["chapters"]):
            raise ValueError(f"Darby oracle chapter carrier count mismatch in {source_book['name']}")

        for source_chapter, chapter_node in zip(
            source_book["chapters"], chapter_nodes, strict=True
        ):
            chapter_number = source_chapter["chapter"]
            chapter_id = f"{book_id}-chapter-{chapter_number:03d}"
            if chapter_node.tag != q("div") or dict(chapter_node.attrib) != {
                "type": "chapter",
                "n": str(chapter_number),
                xml_id: chapter_id,
            }:
                raise ValueError(
                    f"Darby oracle chapter order/identity mismatch at {source_book['name']} {chapter_number}"
                )
            verse_nodes = list(chapter_node)
            if len(verse_nodes) != len(source_chapter["verses"]):
                raise ValueError(
                    f"Darby oracle verse carrier count mismatch at {source_book['name']} {chapter_number}"
                )
            chapter_total += 1

            for source_verse, verse_node in zip(
                source_chapter["verses"], verse_nodes, strict=True
            ):
                verse_number = source_verse["verse"]
                verse_id = (
                    f"{chapter_id}-verse-{verse_number:03d}"
                )
                expected_attributes = {
                    "type": "verse",
                    "n": str(verse_number),
                    xml_id: verse_id,
                    xml_space: "preserve",
                }
                observed_text = "" if verse_node.text is None else verse_node.text
                if (
                    verse_node.tag != q("ab")
                    or dict(verse_node.attrib) != expected_attributes
                    or observed_text != source_verse["text"]
                    or len(verse_node) != 0
                    or verse_node.tail is not None
                ):
                    raise ValueError(
                        f"Darby oracle verse carrier/order/value mismatch at "
                        f"{source_book['name']} {chapter_number}:{verse_number}"
                    )
                verse_total += 1

    if chapter_total != 1189 or verse_total != 31102:
        raise ValueError("Darby oracle complete chapter/verse count mismatch")


def _validate_runtime(policy) -> None:
    expected = policy["runtime"]

    def version(values: tuple[int, ...]) -> str:
        return ".".join(str(part) for part in values[:3])

    if (
        version(etree.LXML_VERSION) != expected["lxml"]
        or version(etree.LIBXML_VERSION) != expected["libxml2_runtime"]
        or version(etree.LIBXML_COMPILED_VERSION) != expected["libxml2_compiled"]
        or importlib.metadata.version("jsonschema") != expected["jsonschema"]
    ):
        raise ValueError("Darby oracle XML/schema runtime differs from policy")


def _closure_digest(policy, repository_root: Path) -> str:
    paths = policy["route_dependencies"]["oracle_import_closure"]
    inventory = {
        path: _digest((repository_root / path).read_bytes()) for path in paths
    }
    return _digest(_canonical(inventory))


def _verify_candidate_descriptor(source_manifest, candidate, policy) -> None:
    record = _thaw(candidate.manifest)
    if not isinstance(record, dict):
        raise ValueError("Darby oracle candidate manifest is invalid")
    package_schema_path = source_manifest.authority_path(
        "candidate-package-schema"
    )
    package_schema = _object(package_schema_path.read_bytes(), "package schema")
    errors = sorted(
        Draft202012Validator(package_schema).iter_errors(record),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ValueError(f"Darby oracle candidate manifest schema failure: {errors[0].message}")

    expected_converter = _thaw(source_manifest.record["converter"])
    expected_package_schema = _thaw(source_manifest.record["package_schema"])
    expected_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if (
        record.get("contract") != "ocd-candidate-package-v1"
        or record.get("status") != "nonaccepted"
        or record.get("source_id") != source_manifest.record.get("source_id")
        or record.get("source_manifest")
        != {"path": expected_path, "sha256": source_manifest.sha256}
        or record.get("converter") != expected_converter
        or record.get("package_schema") != expected_package_schema
    ):
        raise ValueError("Darby oracle candidate manifest source binding drift")
    member_records = record.get("members")
    if not isinstance(member_records, list) or len(member_records) != 5:
        raise ValueError("Darby oracle candidate member inventory is incomplete")
    expected_names = {
        "README.source.md",
        "content.tei.xml",
        "provenance.json",
        "source-accountability.json",
        "unresolved.jsonl",
    }
    names = [row.get("name") for row in member_records if isinstance(row, dict)]
    if set(names) != expected_names or len(names) != len(expected_names):
        raise ValueError("Darby oracle candidate member names are invalid")
    for row in member_records:
        name = row["name"]
        content = candidate.member_bytes(name)
        if row.get("bytes") != len(content) or row.get("sha256") != _digest(content):
            raise ValueError(f"Darby oracle candidate member binding drift: {name}")


def oracle(source_manifest, candidate):
    """Check candidate members against an independent traversal of source bytes."""

    source_manifest.verify()
    candidate.verify_integrity()
    record = source_manifest.record
    if record.get("contract") != "ocd-source-manifest-v1":
        raise ValueError("Darby oracle source manifest contract mismatch")
    if record.get("work_id") != "darby" or record.get("source_id") != "darby-retained-json":
        raise ValueError("Darby oracle source manifest work identity drift")

    authorities = _authority_map(source_manifest)
    profile = _object(
        source_manifest.authority_path("darby-profile").read_bytes(), "profile"
    )
    policy = _object(
        source_manifest.authority_path("darby-policy").read_bytes(), "policy"
    )
    if (
        profile.get("contract") != "ocd-darby-reconstruction-profile-v1"
        or policy.get("contract") != "ocd-darby-independent-validation-policy-v1"
        or profile.get("work_id") != "darby"
        or policy.get("work_id") != "darby"
        or profile.get("source_member") != policy.get("source_member")
        or profile.get("source_selector") != policy.get("source_selector")
        or not _selector_matches(record.get("source_selection"))
    ):
        raise ValueError("Darby oracle profile/policy/selector identity drift")
    authority_digests = _check_authorities(source_manifest, profile, policy)

    source_bytes = source_manifest.authority_path("darby-source").read_bytes()
    expected_member = {
        "path": SOURCE_PATH,
        "bytes": len(source_bytes),
        "sha256": _digest(source_bytes),
    }
    if (
        expected_member != profile["source_member"]
        or expected_member != policy["source_member"]
        or authority_digests["darby-source"] != expected_member["sha256"]
    ):
        raise ValueError("Darby oracle exact retained source bytes/hash mismatch")

    source, expected_accountability = _derive_source_accountability(
        source_bytes, profile
    )
    observed_accountability = _object(
        candidate.member_bytes("source-accountability.json"), "accountability"
    )
    schema = _object(
        source_manifest.authority_path("darby-accountability-schema").read_bytes(),
        "accountability schema",
    )
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(observed_accountability),
        key=lambda item: list(item.path),
    )
    if errors:
        raise ValueError(f"Darby oracle accountability schema failure: {errors[0].message}")
    if observed_accountability != expected_accountability:
        raise ValueError("Darby oracle source carrier/field accounting differs from source")

    _check_tree(source, candidate.member_bytes("content.tei.xml"), policy)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    xsd = etree.XMLSchema(
        etree.parse(
            str(source_manifest.authority_path("tei-p5-xsd")),
            parser,
        )
    )
    tei_root = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    try:
        xsd.assertValid(tei_root)
    except etree.DocumentInvalid as exc:
        raise ValueError("Darby oracle TEI P5 schema validation failed") from exc

    candidate_policy = policy["candidate"]
    if candidate.member_bytes("README.source.md") != str(
        candidate_policy["readme"]
    ).encode("utf-8"):
        raise ValueError("Darby oracle candidate README differs from policy")
    expected_unresolved = b"".join(
        _canonical(item) for item in candidate_policy["unresolved"]
    )
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("Darby oracle unresolved-question inventory differs from policy")
    provenance = _object(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {
        "contract": "ocd-darby-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "authorities": {
            name: str(row["sha256"]) for name, row in authorities.items()
        },
        "converter": _thaw(record["converter"]),
        "scope": str(candidate_policy["scope"]),
    }
    if provenance != expected_provenance:
        raise ValueError("Darby oracle provenance binding differs")
    _verify_candidate_descriptor(source_manifest, candidate, policy)
    _validate_runtime(policy)

    closure = _closure_digest(policy, source_manifest.repository_root)
    validator = record["validator"]
    if closure != validator["import_closure_sha256"]:
        raise ValueError("Darby oracle import-closure digest differs from manifest")
    facts = MechanicalFacts(
        validator_implementation_sha256=_digest(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=expected_member["sha256"],
        profile_sha256=authority_digests["darby-profile"],
        package_schema_sha256=authority_digests["candidate-package-schema"],
        xsd_sha256=authority_digests["tei-p5-xsd"],
        policy_sha256=authority_digests["darby-policy"],
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = "ocd-lib023-darby-independent-oracle"
oracle.oracle_version = "1"
