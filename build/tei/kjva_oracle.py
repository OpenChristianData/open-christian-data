"""Independent source-byte oracle for the LIB-023 KJVA route.

This module deliberately does not import the KJVA producer. It recursively
walks the retained JSON, inspects the actual TEI tree with lxml, and binds its
result to the manifest's exact source, policy, schemas, and runtime.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_PATH = "raw/bible_databases/formats/json/KJVA.json"


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
                raise ValueError(f"KJVA oracle duplicate {label} key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"KJVA oracle {label} is not strict UTF-8 JSON") from exc


def _object(data: bytes, label: str) -> dict[str, object]:
    value = _decode(data, label)
    if not isinstance(value, dict):
        raise ValueError(f"KJVA oracle {label} must be an object")
    return value


def _authority_map(source_manifest) -> dict[str, object]:
    rows = source_manifest.record.get("authorities")
    if not isinstance(rows, tuple):
        raise ValueError("KJVA oracle manifest authority set is invalid")
    return {str(row["name"]): row for row in rows}


def _check_authorities(source_manifest, profile, policy) -> dict[str, str]:
    authorities = _authority_map(source_manifest)
    required_names = {
        "kjva-source",
        "kjva-config",
        "kjva-profile",
        "kjva-policy",
        "tei-p5-xsd",
        "tei-xml-xsd",
        "tei-teix-xsd",
        "candidate-package-schema",
        "candidate-cli",
        "build-package-init",
        "reconstruction-contract",
        "reconstruction-verifier",
        "destination-policy",
        "kernel-init",
        "reconstruction-init",
    }
    if set(authorities) != required_names:
        raise ValueError("KJVA oracle manifest authority inventory drift")
    source = authorities["kjva-source"]
    if (
        source.get("path") != SOURCE_PATH
        or source.get("role") != "primary-source"
        or source.get("bytes") != profile["source_member"]["bytes"]
        or source.get("sha256") != profile["source_member"]["sha256"]
    ):
        raise ValueError("KJVA retained JSON source authority mismatch")
    for name, path in (
        ("kjva-config", "sources/bible-text/kjva/config.json"),
        ("kjva-profile", "sources/bible-text/kjva/kjva.reconstruction-profile.json"),
        ("kjva-policy", "sources/bible-text/kjva/kjva.validation-policy.json"),
    ):
        if authorities[name].get("path") != path:
            raise ValueError(f"KJVA oracle {name} path mismatch")

    schema_authorities = {
        "tei-p5-xsd": policy["schema"]["tei_p5"],
        "tei-xml-xsd": policy["schema"]["tei_xml_import"],
        "tei-teix-xsd": policy["schema"]["tei_teix_import"],
        "candidate-package-schema": policy["schema"]["candidate_package"],
    }
    for name, expected in schema_authorities.items():
        authority = authorities[name]
        if authority.get("path") != expected["path"] or authority.get("sha256") != expected["sha256"]:
            raise ValueError(f"KJVA oracle schema dependency mismatch: {name}")
    if (
        authorities["tei-p5-xsd"].get("role") != "tei-validation-schema"
        or authorities["tei-xml-xsd"].get("role") != "tei-validation-schema-import"
        or authorities["tei-teix-xsd"].get("role") != "tei-validation-schema-import"
        or authorities["candidate-package-schema"].get("role") != "candidate-package-schema"
    ):
        raise ValueError("KJVA oracle schema authority roles drifted")
    route = policy["route_dependencies"]
    route_bindings = {
        "candidate-cli": route["candidate_cli"],
        "build-package-init": route["build_package_init"],
        "reconstruction-contract": route["contract"],
        "reconstruction-verifier": route["verifier"],
        "destination-policy": route["destination_policy"],
        "kernel-init": "ocd_kernel/__init__.py",
        "reconstruction-init": "ocd_kernel/reconstruction/__init__.py",
    }
    for name, path in route_bindings.items():
        authority = authorities[name]
        if authority.get("path") != path or authority.get("role") != "route-runtime-dependency":
            raise ValueError(f"KJVA oracle route dependency mismatch: {name}")
    return {name: str(row["sha256"]) for name, row in authorities.items()}


def _field_state(value: object, states: dict[str, int]) -> str:
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
        return "positive_integer" if value > 0 else "zero_integer"
    if isinstance(value, str):
        if not value:
            states["empty_string"] += 1
            return "empty_string"
        return "nonempty_string"
    if isinstance(value, list):
        if not value:
            states["empty_array"] += 1
            return "empty_array"
        return "nonempty_array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _source_facts(source_bytes: bytes, profile: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    decoded = _decode(source_bytes, "source")
    if not isinstance(decoded, dict):
        raise ValueError("KJVA oracle source root is not an object")
    source = decoded
    if list(source) != ["translation", "books"]:
        raise ValueError("KJVA oracle root keys/order differ")
    if source.get("translation") != profile["source_translation_label"]:
        raise ValueError("KJVA oracle source label differs from profile")

    expected_shapes = {
        "root": ["translation", "books"],
        "book": ["name", "chapters"],
        "chapter": ["chapter", "verses"],
        "verse": ["verse", "text"],
    }
    states = {
        label: 0
        for label in (
            "missing",
            "null",
            "empty_string",
            "zero_integer",
            "false_boolean",
            "empty_array",
        )
    }
    shape_counts = {label: 0 for label in expected_shapes}
    arrays_seen: list[tuple[str, int]] = []
    scalar_values: list[tuple[str, object]] = []
    carriers: list[dict[str, object]] = []
    inventory: list[dict[str, object]] = []
    verse_text: list[str] = []

    def pointer_shape(pointer: str) -> tuple[str, re.Match[str] | None]:
        if pointer == "":
            return "root", None
        for label, pattern in (
            ("book", r"/books/(\d+)"),
            ("chapter", r"/books/(\d+)/chapters/(\d+)"),
            ("verse", r"/books/(\d+)/chapters/(\d+)/verses/(\d+)"),
        ):
            match = re.fullmatch(pattern, pointer)
            if match:
                return label, match
        raise ValueError(f"KJVA oracle unknown source object at {pointer}")

    def inspect(value: object, pointer: str) -> None:
        if isinstance(value, dict):
            shape, match = pointer_shape(pointer)
            keys = expected_shapes[shape]
            states["missing"] += sum(key not in value for key in keys)
            if list(value) != keys:
                raise ValueError(f"KJVA oracle object keys/order differ at {pointer or '/'}")
            shape_counts[shape] += 1
            if shape == "book":
                assert match is not None
                position = int(match.group(1)) + 1
                name = value["name"]
                chapter_array = value["chapters"]
                if not isinstance(name, str) or not name or not isinstance(chapter_array, list) or not chapter_array:
                    raise ValueError(f"KJVA oracle book identity/array invalid at {pointer}")
                if any(row["name"] == name for row in inventory):
                    raise ValueError(f"KJVA oracle duplicate book identity at {pointer}")
                inventory.append(
                    {"position": position, "name": name, "chapters": len(chapter_array), "verses": 0}
                )
                carriers.append(
                    {
                        "kind": "book",
                        "pointer": pointer,
                        "parent": "/books",
                        "identity": {"position": position, "book": name},
                        "keys": list(value),
                        "fields": [
                            {"name": "name", "state": _field_state(name, states), "value_sha256": _digest(_canonical(name))},
                            {"name": "chapters", "state": _field_state(chapter_array, states), "length": len(chapter_array)},
                        ],
                    }
                )
            elif shape == "chapter":
                assert match is not None
                book_position = int(match.group(1)) + 1
                chapter_position = int(match.group(2)) + 1
                number, verse_array = value["chapter"], value["verses"]
                if type(number) is not int or number != chapter_position or not isinstance(verse_array, list) or not verse_array:
                    raise ValueError(f"KJVA oracle chapter number/array invalid at {pointer}")
                book_name = str(source["books"][book_position - 1]["name"])
                chapter_id = f"kjva-book-{book_position:03d}-chapter-{chapter_position:03d}"
                carriers.append(
                    {
                        "kind": "chapter",
                        "pointer": pointer,
                        "parent": f"/books/{book_position - 1}/chapters",
                        "identity": {"book": book_name, "chapter": number},
                        "keys": list(value),
                        "fields": [
                            {"name": "chapter", "state": _field_state(number, states), "value_sha256": _digest(_canonical(number))},
                            {"name": "verses", "state": _field_state(verse_array, states), "length": len(verse_array)},
                        ],
                    }
                )
            elif shape == "verse":
                assert match is not None
                book_position = int(match.group(1)) + 1
                chapter_position = int(match.group(2)) + 1
                verse_position = int(match.group(3)) + 1
                number, wording = value["verse"], value["text"]
                if type(number) is not int or number != verse_position or not isinstance(wording, str) or not wording:
                    raise ValueError(f"KJVA oracle verse identity/text invalid at {pointer}")
                book_name = str(source["books"][book_position - 1]["name"])
                verse_id = (
                    f"kjva-book-{book_position:03d}-chapter-{chapter_position:03d}"
                    f"-verse-{verse_position:03d}"
                )
                carriers.append(
                    {
                        "kind": "verse",
                        "pointer": pointer,
                        "parent": f"/books/{book_position - 1}/chapters/{chapter_position - 1}/verses",
                        "identity": {"book": book_name, "chapter": chapter_position, "verse": number},
                        "keys": list(value),
                        "fields": [
                            {"name": "verse", "state": _field_state(number, states), "value_sha256": _digest(_canonical(number))},
                            {"name": "text", "state": _field_state(wording, states), "value_sha256": _digest(_canonical(wording))},
                        ],
                    }
                )
                verse_text.append(wording)
            for key, child in value.items():
                child_pointer = f"{pointer}/{key}"
                if shape == "root":
                    _field_state(child, states)
                inspect(child, child_pointer)
            return
        if isinstance(value, list):
            if not value:
                states["empty_array"] += 1
                raise ValueError(f"KJVA oracle empty array at {pointer}")
            if pointer not in {"/books"} and not re.fullmatch(r"/books/\d+/chapters|/books/\d+/chapters/\d+/verses", pointer):
                raise ValueError(f"KJVA oracle unknown source array at {pointer}")
            arrays_seen.append((pointer, len(value)))
            if pointer.endswith("/verses"):
                book_index = int(pointer.split("/")[2])
                inventory[book_index]["verses"] += len(value)
            for index, child in enumerate(value):
                inspect(child, f"{pointer}/{index}")
            return
        scalar_values.append((pointer, value))
        if isinstance(value, bool) or value is None or not isinstance(value, (str, int)):
            raise ValueError(f"KJVA oracle unsupported source scalar at {pointer}")
        if isinstance(value, str) and not value:
            raise ValueError(f"KJVA oracle empty source string at {pointer}")
        if type(value) is int and value <= 0:
            raise ValueError(f"KJVA oracle nonpositive source integer at {pointer}")

    inspect(source, "")
    books = source.get("books")
    if not isinstance(books, list):
        raise ValueError("KJVA oracle books member is not an array")
    leading = sum(1 for item in verse_text if item[0].isspace())
    trailing = sum(1 for item in verse_text if item[-1].isspace())
    expected_inventory = profile.get("ordered_book_envelope")
    expected_counts = profile.get("expected")
    observed_counts = {
        "members": 1,
        "books": len(books),
        "chapters": shape_counts["chapter"],
        "verses": shape_counts["verse"],
        "carriers": len(carriers),
        "scalar_fields": len(scalar_values),
        "ordered_arrays": len(arrays_seen),
    }
    if (
        inventory != expected_inventory
        or observed_counts != expected_counts
        or shape_counts != {"root": 1, "book": 80, "chapter": 1371, "verse": 36819}
        or states != profile.get("field_states")
        or leading != 23
        or trailing != 1466
    ):
        raise ValueError("KJVA oracle source envelope/accounting differs from profile")
    partitions = profile.get("book_partitions")
    if partitions != {
        "kjv_portion_positions": [[1, 39], [54, 80]],
        "kjv_portion_books": 66,
        "apocrypha_positions": [[40, 53]],
        "apocrypha_books": 14,
    }:
        raise ValueError("KJVA oracle book partition profile mismatch")

    fields: list[dict[str, object]] = []
    for pointer, value in scalar_values:
        attribute = None
        if pointer == "/translation":
            target = "kjva-source-label"
        else:
            match = re.fullmatch(r"/books/(\d+)/name", pointer)
            if match:
                target = f"kjva-book-{int(match.group(1)) + 1:03d}-title"
            else:
                chapter_match = re.fullmatch(r"/books/(\d+)/chapters/(\d+)/chapter", pointer)
                verse_match = re.fullmatch(r"/books/(\d+)/chapters/(\d+)/verses/(\d+)/(verse|text)", pointer)
                if chapter_match:
                    book_n, chapter_n = int(chapter_match.group(1)) + 1, int(chapter_match.group(2)) + 1
                    target = f"kjva-book-{book_n:03d}-chapter-{chapter_n:03d}"
                    attribute = "n"
                elif verse_match:
                    book_n = int(verse_match.group(1)) + 1
                    chapter_n = int(verse_match.group(2)) + 1
                    verse_n = int(verse_match.group(3)) + 1
                    target = f"kjva-book-{book_n:03d}-chapter-{chapter_n:03d}-verse-{verse_n:03d}"
                    if verse_match.group(4) == "verse":
                        attribute = "n"
                else:
                    raise ValueError(f"KJVA oracle unaccounted scalar at {pointer}")
        fields.append(
            {
                "pointer": pointer,
                "json_type": "integer" if type(value) is int else "string",
                "state": "positive_integer" if type(value) is int else "nonempty_string",
                "value_sha256": _digest(_canonical(value)),
                "target": target,
                "attribute": attribute,
                "disposition": "preserved",
            }
        )
    key_order_records = [
        {"shape": "root", "keys": expected_shapes["root"], "occurrences": shape_counts["root"]},
        *[
            {"shape": label, "keys": expected_shapes[label], "occurrences": shape_counts[label]}
            for label in ("book", "chapter", "verse")
        ],
    ]
    if key_order_records != profile.get("object_key_orders"):
        raise ValueError("KJVA oracle ordered object-shape inventory differs")
    if profile.get("text_boundary_whitespace") != {
        "leading": leading,
        "trailing": trailing,
        "normalization": "none; preserve exact Unicode scalar sequence",
    }:
        raise ValueError("KJVA oracle whitespace evidence differs")
    root_fields = [
        {
            "name": "translation",
            "state": "nonempty_string",
            "value_sha256": _digest(_canonical(source["translation"])),
        },
        {"name": "books", "state": "nonempty_array", "length": len(books)},
    ]
    accounting = {
        "contract": "ocd-kjva-accounting-v1",
        "source_member": {
            "path": SOURCE_PATH,
            "bytes": len(source_bytes),
            "sha256": _digest(source_bytes),
        },
        "counts": observed_counts,
        "field_states": states,
        "root_fields": root_fields,
        "object_key_orders": key_order_records,
        "book_inventory": inventory,
        "carriers": carriers,
        "fields": fields,
        "excluded": [],
    }
    return source, accounting


def _check_tree(source: dict[str, object], tei_bytes: bytes, policy: dict[str, object]) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    root = etree.fromstring(tei_bytes, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("KJVA oracle rejects a TEI document type")
    q = lambda local: f"{{{TEI}}}{local}"
    xid = f"{{{XML}}}id"
    if root.tag != q("TEI") or dict(root.attrib) != {xid: "kjva"}:
        raise ValueError("KJVA oracle TEI work identity mismatch")
    all_nodes = list(root.iter())
    if any(not isinstance(node.tag, str) for node in all_nodes):
        raise ValueError("KJVA oracle rejects XML comments and processing instructions")
    if any(node.tail is not None for node in all_nodes):
        raise ValueError("KJVA oracle found unaccounted TEI tail text")
    identities = [node.get(xid) for node in all_nodes if node.get(xid) is not None]
    if len(identities) != len(set(identities)):
        raise ValueError("KJVA oracle found duplicate xml:id values")
    if [node.tag for node in root] != [q("teiHeader"), q("text")]:
        raise ValueError("KJVA oracle TEI root topology mismatch")
    header, text_node = root[0], root[1]
    if root.text is not None or text_node.text is not None or header.text is not None:
        raise ValueError("KJVA oracle found unaccounted root/header prose")
    if len(header) != 1 or header[0].tag != q("fileDesc") or dict(header[0].attrib):
        raise ValueError("KJVA oracle TEI header topology mismatch")
    file_desc = header[0]
    if file_desc.text is not None or [node.tag for node in file_desc] != [
        q("titleStmt"), q("publicationStmt"), q("sourceDesc")
    ]:
        raise ValueError("KJVA oracle file-description placement mismatch")
    title_stmt, publication_stmt, source_desc = list(file_desc)
    candidate_policy = policy["candidate"]
    if (
        dict(title_stmt.attrib)
        or title_stmt.text is not None
        or len(title_stmt) != 1
        or title_stmt[0].tag != q("title")
        or dict(title_stmt[0].attrib) != {xid: "kjva-title"}
        or title_stmt[0].text != candidate_policy["title"]
        or len(title_stmt[0])
    ):
        raise ValueError("KJVA oracle TEI title placement/value mismatch")
    if (
        dict(publication_stmt.attrib)
        or publication_stmt.text is not None
        or len(publication_stmt) != 1
        or publication_stmt[0].tag != q("p")
        or dict(publication_stmt[0].attrib)
        or publication_stmt[0].text != candidate_policy["publication_notice"]
        or len(publication_stmt[0])
    ):
        raise ValueError("KJVA oracle TEI publication-status metadata mismatch")
    source_label = source_desc.find(q("p"))
    if (
        dict(source_desc.attrib)
        or source_desc.text is not None
        or len(source_desc) != 2
        or source_label is None
        or source_label.tag != q("p")
        or dict(source_label.attrib) != {xid: "kjva-source-label"}
        or source_label.text != source["translation"]
        or len(source_label)
        or source_desc[1].tag != q("p")
        or dict(source_desc[1].attrib) != {xid: "kjva-source-note"}
        or source_desc[1].text != candidate_policy["source_note"]
        or len(source_desc[1])
    ):
        raise ValueError("KJVA oracle source-label/note placement mismatch")
    if len(text_node) != 1 or text_node[0].tag != q("body") or dict(text_node.attrib) or dict(text_node[0].attrib):
        raise ValueError("KJVA oracle TEI body placement mismatch")
    body = text_node[0]
    if body.text is not None:
        raise ValueError("KJVA oracle found text outside a book carrier")

    books = source["books"]
    if not isinstance(books, list):
        raise ValueError("KJVA oracle source book array disappeared")
    expected_book_ids = [f"kjva-book-{position:03d}" for position in range(1, len(books) + 1)]
    if [node.get(xid) for node in body] != expected_book_ids:
        raise ValueError("KJVA source order/parent/omission mismatch at /books")
    for book_position, (source_book, book_node) in enumerate(zip(books, body, strict=True), 1):
        book_id = f"kjva-book-{book_position:03d}"
        if (
            book_node.tag != q("div")
            or dict(book_node.attrib) != {"type": "book", "n": str(book_position), xid: book_id}
            or book_node.text is not None
        ):
            raise ValueError(f"KJVA oracle book node identity/topology mismatch at position {book_position}")
        chapters = source_book["chapters"]
        expected_child_ids = [f"{book_id}-title"] + [
            f"{book_id}-chapter-{chapter_index:03d}"
            for chapter_index in range(1, len(chapters) + 1)
        ]
        if [node.get(xid) for node in book_node] != expected_child_ids:
            raise ValueError(f"KJVA source order/parent/omission mismatch at {book_id}")
        head = book_node[0]
        if (
            head.tag != q("head")
            or dict(head.attrib) != {xid: f"{book_id}-title"}
            or head.text != source_book["name"]
            or len(head)
        ):
            raise ValueError(f"KJVA oracle book-name placement/value mismatch at {book_id}")
        for chapter_position, (source_chapter, chapter_node) in enumerate(
            zip(chapters, book_node[1:], strict=True), 1
        ):
            chapter_id = f"{book_id}-chapter-{chapter_position:03d}"
            if (
                chapter_node.tag != q("div")
                or dict(chapter_node.attrib) != {"type": "chapter", "n": str(chapter_position), xid: chapter_id}
                or chapter_node.text is not None
            ):
                raise ValueError(f"KJVA oracle chapter placement/number mismatch at {chapter_id}")
            verses = source_chapter["verses"]
            expected_verse_ids = [
                f"{chapter_id}-verse-{verse_index:03d}"
                for verse_index in range(1, len(verses) + 1)
            ]
            if [node.get(xid) for node in chapter_node] != expected_verse_ids:
                raise ValueError(f"KJVA source order/parent/omission mismatch at {chapter_id}")
            for verse_position, (source_verse, verse_node) in enumerate(
                zip(verses, chapter_node, strict=True), 1
            ):
                verse_id = f"{chapter_id}-verse-{verse_position:03d}"
                if (
                    verse_node.tag != q("ab")
                    or dict(verse_node.attrib)
                    != {"type": "verse", "n": str(verse_position), xid: verse_id, f"{{{XML}}}space": "preserve"}
                    or verse_node.text != source_verse["text"]
                    or len(verse_node)
                ):
                    raise ValueError(f"KJVA oracle verse mapping/value mismatch at {verse_id}")


def _check_runtime(policy: dict[str, object]) -> None:
    expected = policy["runtime"]
    render = lambda values: ".".join(str(value) for value in values[:3])
    if (
        render(etree.LXML_VERSION) != expected["lxml"]
        or render(etree.LIBXML_VERSION) != expected["libxml2_runtime"]
        or render(etree.LIBXML_COMPILED_VERSION) != expected["libxml2_compiled"]
        or importlib.metadata.version("jsonschema") != expected["jsonschema"]
    ):
        raise ValueError("KJVA oracle parser/schema runtime differs from pinned policy")


def _closure_digest(policy: dict[str, object], repository_root: Path) -> str:
    names = policy["route_dependencies"]["oracle_import_closure"]
    inventory = {name: _digest((repository_root / name).read_bytes()) for name in names}
    return _digest(_canonical(inventory))


def oracle(source_manifest, candidate):
    source_manifest.verify()
    candidate.verify_integrity()
    repository_root = source_manifest.repository_root
    profile = _object(source_manifest.authority_path("kjva-profile").read_bytes(), "profile")
    policy = _object(source_manifest.authority_path("kjva-policy").read_bytes(), "policy")
    config = _object(source_manifest.authority_path("kjva-config").read_bytes(), "config")
    if (
        profile.get("contract") != "ocd-kjva-reconstruction-profile-v1"
        or profile.get("work_id") != "kjva"
        or policy.get("contract") != "ocd-kjva-independent-validation-policy-v1"
        or policy.get("work_id") != "kjva"
        or config.get("resource_id") != "kjva"
        or config.get("source_file") != SOURCE_PATH
    ):
        raise ValueError("KJVA oracle work/profile/policy/config identity drift")
    bindings = _check_authorities(source_manifest, profile, policy)
    source_bytes = source_manifest.authority_path("kjva-source").read_bytes()
    if (
        len(source_bytes) != profile["source_member"]["bytes"]
        or _digest(source_bytes) != profile["source_member"]["sha256"]
        or policy["source_member"] != {"path": SOURCE_PATH, "sha256": _digest(source_bytes)}
    ):
        raise ValueError("KJVA oracle exact source bytes/hash mismatch")
    source, expected_accounting = _source_facts(source_bytes, profile)
    observed_accounting = _object(candidate.member_bytes("source-accountability.json"), "accountability")
    if observed_accounting != expected_accounting:
        raise ValueError("KJVA oracle carrier/field accounting differs from independent source walk")

    tei_bytes = candidate.member_bytes("content.tei.xml")
    _check_tree(source, tei_bytes, policy)
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
    xsd.assertValid(etree.fromstring(tei_bytes, etree.XMLParser(resolve_entities=False, no_network=True)))

    package_schema = _object(source_manifest.authority_path("candidate-package-schema").read_bytes(), "candidate package schema")
    package_record = _object((candidate.path / "manifest.json").read_bytes(), "candidate manifest")
    package_validator = Draft202012Validator(package_schema)
    package_errors = sorted(package_validator.iter_errors(package_record), key=lambda error: list(error.path))
    if package_errors:
        raise ValueError(f"KJVA candidate package schema failure: {package_errors[0].message}")

    candidate_policy = policy["candidate"]
    expected_unresolved = b"".join(_canonical(row) for row in candidate_policy["unresolved"])
    if candidate.member_bytes("README.source.md") != str(candidate_policy["readme"]).encode("utf-8"):
        raise ValueError("KJVA candidate README scope/provenance differs from policy")
    if candidate.member_bytes("unresolved.jsonl") != expected_unresolved:
        raise ValueError("KJVA candidate unresolved-question inventory differs from policy")
    expected_provenance = {
        "contract": "ocd-kjva-provenance-v1",
        "source_manifest_sha256": source_manifest.sha256,
        "authorities": bindings,
        "converter": dict(source_manifest.record["converter"]),
        "scope": str(candidate_policy["scope"]),
    }
    provenance = _object(candidate.member_bytes("provenance.json"), "provenance")
    if provenance != expected_provenance:
        raise ValueError("KJVA candidate provenance binding differs")
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("KJVA candidate must remain nonaccepted")

    _check_runtime(policy)
    closure = _closure_digest(policy, repository_root)
    facts = MechanicalFacts(
        validator_implementation_sha256=_digest(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=_digest(source_bytes),
        profile_sha256=bindings["kjva-profile"],
        package_schema_sha256=bindings["candidate-package-schema"],
        xsd_sha256=bindings["tei-p5-xsd"],
        policy_sha256=bindings["kjva-policy"],
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = "ocd-lib023-kjva-independent-oracle"
oracle.oracle_version = "1"
