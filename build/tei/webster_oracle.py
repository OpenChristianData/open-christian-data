"""Independent source-byte oracle for the LIB-023 Webster route.

The oracle does not import the producer. It derives the complete JSON ledger
from the retained bytes and compares the actual candidate TEI tree directly.
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
SOURCE_PATH = "raw/bible_databases/formats/json/Webster.json"
SOURCE_SELECTION = {"authority": "webster-source", "json_pointer": "", "selected_root_fields": ["/translation", "/books"], "selection": "the complete single retained JSON document"}
ACCOUNTABILITY_SCHEMA_PATH = "sources/bible-text/webster/webster.source-accountability.schema.json"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _decode(data: bytes, label: str) -> object:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Webster oracle duplicate {label} key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Webster oracle {label} contains non-JSON constant {value}")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Webster oracle {label} is not strict UTF-8 JSON") from exc


def _object(data: bytes, label: str) -> dict[str, object]:
    value = _decode(data, label)
    if not isinstance(value, dict):
        raise ValueError(f"Webster oracle {label} must be an object")
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_keys(record: dict[str, object], expected: tuple[str, ...], pointer: str) -> None:
    if tuple(record) != expected:
        raise ValueError(f"Webster oracle source keys/order drift at {pointer or '/'}")


def _selector_matches(value: object) -> bool:
    return isinstance(value, Mapping) and value.get("authority") == SOURCE_SELECTION["authority"] and value.get("json_pointer") == "" and tuple(value.get("selected_root_fields", ())) == tuple(SOURCE_SELECTION["selected_root_fields"]) and value.get("selection") == SOURCE_SELECTION["selection"]


def _authority_map(manifest) -> dict[str, Mapping[str, object]]:
    rows = manifest.record.get("authorities")
    if not isinstance(rows, tuple):
        raise ValueError("Webster oracle manifest authority set is invalid")
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("name"), str) or row["name"] in result:
            raise ValueError("Webster oracle manifest authority names are invalid")
        result[str(row["name"])] = row
    return result


def _check_authorities(manifest, profile, policy) -> dict[str, str]:
    authorities = _authority_map(manifest)
    expected = {
        "webster-source": (SOURCE_PATH, "primary-source"),
        "webster-config": ("sources/bible-text/webster/config.json", "work-identity-config"),
        "webster-profile": ("sources/bible-text/webster/webster.reconstruction-profile.json", "complete-source-feature-profile"),
        "webster-policy": ("sources/bible-text/webster/webster.validation-policy.json", "independent-validation-policy"),
        "webster-accountability-schema": (ACCOUNTABILITY_SCHEMA_PATH, "source-accountability-schema"),
        "tei-p5-xsd": ("ocd_kernel/tei/vendor/xsd/tei_all.xsd", "tei-validation-schema"),
        "tei-xml-xsd": ("ocd_kernel/tei/vendor/xsd/tei_all_xml.xsd", "tei-validation-schema-import"),
        "tei-teix-xsd": ("ocd_kernel/tei/vendor/xsd/tei_all_teix.xsd", "tei-validation-schema-import"),
        "candidate-package-schema": ("ocd_kernel/reconstruction/schemas/candidate-package-v1.schema.json", "candidate-package-schema"),
        "candidate-cli": ("build/tools/reconstruct_candidate.py", "route-runtime-dependency"),
        "build-package-init": ("build/__init__.py", "route-runtime-dependency"),
        "reconstruction-contract": ("ocd_kernel/reconstruction/contract.py", "route-runtime-dependency"),
        "reconstruction-verifier": ("ocd_kernel/reconstruction/verifier.py", "route-runtime-dependency"),
        "destination-policy": ("ocd_kernel/reconstruction/destination_policy.py", "route-runtime-dependency"),
        "kernel-init": ("ocd_kernel/__init__.py", "route-runtime-dependency"),
        "reconstruction-init": ("ocd_kernel/reconstruction/__init__.py", "route-runtime-dependency"),
    }
    if set(authorities) != set(expected):
        raise ValueError("Webster oracle manifest authority inventory drift")
    digests = {}
    for name, (path, role) in expected.items():
        row = authorities[name]
        # Resolve logical raw/ paths through the configured storage topology.
        resolved = manifest.authority_path(name)
        content = resolved.read_bytes()
        if row.get("path") != path or row.get("role") != role or row.get("bytes") != len(content) or row.get("sha256") != _digest(content):
            raise ValueError(f"Webster oracle authority binding drift: {name}")
        digests[name] = _digest(content)
    if policy["accountability"]["schema_path"] != ACCOUNTABILITY_SCHEMA_PATH or policy["accountability"]["schema_sha256"] != digests["webster-accountability-schema"]:
        raise ValueError("Webster oracle accountability schema binding drift")
    for key, policy_key in (("tei-p5-xsd", "tei_p5"), ("tei-xml-xsd", "tei_xml_import"), ("tei-teix-xsd", "tei_teix_import"), ("candidate-package-schema", "candidate_package")):
        if policy["schema"][policy_key] != {"path": expected[key][0], "sha256": digests[key]}:
            raise ValueError(f"Webster oracle schema binding drift: {key}")
    for binding, name, ident, path in ((manifest.record["converter"], "converter", "ocd-lib023-webster-json-to-tei", "build/tei/webster_reconstruction.py"), (manifest.record["validator"], "validator", "ocd-lib023-webster-independent-oracle", "build/tei/webster_oracle.py")):
        if binding.get("id") != ident or binding.get("version") != "1" or binding.get("callable") not in {"convert", "oracle"} or binding.get("implementation_path") != path or binding.get("implementation_sha256") != _digest((manifest.repository_root / path).read_bytes()):
            raise ValueError(f"Webster oracle {name} binding drift")
    package_schema = manifest.record["package_schema"]
    if package_schema != {"path": expected["candidate-package-schema"][0], "sha256": digests["candidate-package-schema"]}:
        raise ValueError("Webster oracle candidate package schema binding drift")
    return digests


def _derive_source_accountability(source_bytes: bytes, profile: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    decoded = _decode(source_bytes, "source")
    if not isinstance(decoded, dict):
        raise ValueError("Webster oracle source root is not an object")
    source = decoded
    _require_keys(source, ("translation", "books"), "")
    label, books = source["translation"], source["books"]
    if not isinstance(label, str) or not label or label != profile["translation_field"]["value"]:
        raise ValueError("Webster oracle retained translation field differs from profile")
    if not isinstance(books, list) or not books:
        raise ValueError("Webster oracle books array is absent or empty")
    states = {name: 0 for name in ("missing", "null", "empty_string", "zero_integer", "false_boolean", "empty_array", "nonempty_string", "positive_integer")}
    states["nonempty_string"] = 1
    book_inventory: list[dict[str, object]] = []
    chapter_inventory: list[dict[str, object]] = []
    verse_carriers: list[dict[str, object]] = []
    chapter_count = verse_count = nonempty_count = leading_count = trailing_count = 0
    for book_position, book in enumerate(books, 1):
        p_book = f"/books/{book_position - 1}"
        if not isinstance(book, dict):
            raise ValueError(f"Webster oracle book is not an object at {p_book}")
        _require_keys(book, ("name", "chapters"), p_book)
        name, chapters = book["name"], book["chapters"]
        if not isinstance(name, str) or not name or not isinstance(chapters, list) or not chapters:
            raise ValueError(f"Webster oracle book is invalid at {p_book}")
        states["nonempty_string"] += 1
        book_verses = 0
        for chapter_position, chapter in enumerate(chapters, 1):
            p_chapter = f"{p_book}/chapters/{chapter_position - 1}"
            if not isinstance(chapter, dict):
                raise ValueError(f"Webster oracle chapter is not an object at {p_chapter}")
            _require_keys(chapter, ("chapter", "verses"), p_chapter)
            number, verses = chapter["chapter"], chapter["verses"]
            if type(number) is not int or number != chapter_position or not isinstance(verses, list) or not verses:
                raise ValueError(f"Webster oracle chapter sequence/list drift at {p_chapter}")
            states["positive_integer"] += 1
            chapter_inventory.append({"book_position": book_position, "book": name, "position": chapter_position, "number": number, "verse_carrier_count": len(verses)})
            chapter_count += 1
            for verse_position, verse in enumerate(verses, 1):
                p_verse = f"{p_chapter}/verses/{verse_position - 1}"
                if not isinstance(verse, dict):
                    raise ValueError(f"Webster oracle verse is not an object at {p_verse}")
                _require_keys(verse, ("verse", "text"), p_verse)
                number_v, text = verse["verse"], verse["text"]
                if type(number_v) is not int or number_v != verse_position or not isinstance(text, str) or not text:
                    raise ValueError(f"Webster oracle verse/value drift at {p_verse}")
                states["positive_integer"] += 1
                states["nonempty_string"] += 1
                nonempty_count += 1
                leading_count += int(text[0].isspace())
                trailing_count += int(text.endswith(" "))
                verse_carriers.append({"json_pointer": p_verse, "identity": {"book_position": book_position, "book": name, "chapter": number, "verse": number_v}, "carrier_state": "present", "text_field_state": "present", "text_value_state": "nonempty_string", "text_value_sha256": _digest(text.encode("utf-8"))})
                verse_count += 1
                book_verses += 1
        book_inventory.append({"position": book_position, "name": name, "chapter_count": len(chapters), "verse_carrier_count": book_verses})
    orders = [{"shape": "root", "keys": ["translation", "books"], "occurrences": 1}, {"shape": "book", "keys": ["name", "chapters"], "occurrences": len(books)}, {"shape": "chapter", "keys": ["chapter", "verses"], "occurrences": chapter_count}, {"shape": "verse", "keys": ["verse", "text"], "occurrences": verse_count}]
    counts = {"source_members": 1, "books": len(books), "chapters": chapter_count, "verse_carriers": verse_count, "nonempty_text_values": nonempty_count, "empty_text_values": 0, "missing_text_fields": 0, "null_text_fields": 0, "unknown_object_keys": 0, "scalar_fields": 1 + len(books) + chapter_count + verse_count * 2, "ordered_arrays": 1 + len(books) + chapter_count, "leading_whitespace_text_values": leading_count, "trailing_ascii_space_text_values": trailing_count}
    if counts != profile["expected"] or states != profile["field_states"] or orders != profile["object_key_orders"]:
        raise ValueError("Webster oracle complete source counts/profile drift")
    member = {"path": SOURCE_PATH, "bytes": len(source_bytes), "sha256": _digest(source_bytes)}
    accounting = {"contract": "ocd-webster-source-accountability-v1", "work_id": "webster", "source_member": member, "source_selection": SOURCE_SELECTION, "translation_field": {"json_pointer": "/translation", "value": label, "field_state": "present_nonempty_string", "value_sha256": _digest(label.encode("utf-8"))}, "counts": counts, "field_states": states, "object_key_orders": orders, "book_inventory": book_inventory, "chapter_inventory": chapter_inventory, "verse_carriers": verse_carriers, "empty_text_carriers": [], "downstream_segmentation_diagnostic_only": profile["downstream_segmentation_diagnostic_only"], "excluded": []}
    return source, accounting


def _check_tree(source: dict[str, object], tei_bytes: bytes, policy: dict[str, object]) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, remove_blank_text=False)
    try:
        root = etree.fromstring(tei_bytes, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError("Webster oracle candidate is not well-formed XML") from exc
    q = lambda local: f"{{{TEI}}}{local}"
    xml_id, xml_space = f"{{{XML}}}id", f"{{{XML}}}space"
    if root.tag != q("TEI") or dict(root.attrib) != {xml_id: "webster"} or [node.tag for node in root] != [q("teiHeader"), q("text")]:
        raise ValueError("Webster oracle TEI root structure/identity drift")
    header, text_node = list(root)
    if [node.tag for node in header] != [q("fileDesc")]:
        raise ValueError("Webster oracle TEI header structure drift")
    file_desc = header[0]
    if [node.tag for node in file_desc] != [q("titleStmt"), q("publicationStmt"), q("notesStmt"), q("sourceDesc")]:
        raise ValueError("Webster oracle TEI file description structure drift")
    title_stmt, publication_stmt, notes_stmt, source_desc = list(file_desc)
    if len(title_stmt) != 1 or title_stmt[0].tag != q("title") or title_stmt[0].text != policy["candidate"]["title"]:
        raise ValueError("Webster oracle generic title mismatch")
    if len(publication_stmt) != 1 or publication_stmt[0].tag != q("p") or publication_stmt[0].text != policy["candidate"]["publication_notice"]:
        raise ValueError("Webster oracle publication notice mismatch")
    if len(notes_stmt) != 1 or notes_stmt[0].tag != q("note") or dict(notes_stmt[0].attrib) != {"type": "source-label-limitation"} or notes_stmt[0].text != policy["candidate"]["source_note"]:
        raise ValueError("Webster oracle source limitation note mismatch")
    if len(source_desc) != 1 or source_desc[0].tag != q("bibl") or dict(source_desc[0].attrib) != {"type": "retained-translation-label", xml_id: "webster-translation-label"} or source_desc[0].text != source["translation"]:
        raise ValueError("Webster oracle retained translation label mismatch")
    if len(text_node) != 1 or text_node[0].tag != q("body"):
        raise ValueError("Webster oracle TEI body structure drift")
    body = text_node[0]
    books = source["books"]
    observed_books = list(body)
    if len(observed_books) != len(books) or len(books) != 66:
        raise ValueError("Webster oracle book carrier count mismatch")
    chapter_total = verse_total = 0
    for position, (source_book, book_node) in enumerate(zip(books, observed_books, strict=True), 1):
        book_id = f"webster-book-{position:03d}"
        if book_node.tag != q("div") or dict(book_node.attrib) != {"type": "book", "n": str(position), xml_id: book_id}:
            raise ValueError(f"Webster oracle book order/identity mismatch at position {position}")
        children = list(book_node)
        if not children or children[0].tag != q("head") or children[0].text != source_book["name"] or dict(children[0].attrib) != {xml_id: f"{book_id}-title"}:
            raise ValueError(f"Webster oracle book heading mismatch at position {position}")
        chapter_nodes = children[1:]
        if len(chapter_nodes) != len(source_book["chapters"]):
            raise ValueError(f"Webster oracle chapter carrier count mismatch at {source_book['name']}")
        for source_chapter, chapter_node in zip(source_book["chapters"], chapter_nodes, strict=True):
            number = source_chapter["chapter"]
            chapter_id = f"{book_id}-chapter-{number:03d}"
            if chapter_node.tag != q("div") or dict(chapter_node.attrib) != {"type": "chapter", "n": str(number), xml_id: chapter_id}:
                raise ValueError(f"Webster oracle chapter order/identity mismatch at {source_book['name']} {number}")
            verse_nodes = list(chapter_node)
            if len(verse_nodes) != len(source_chapter["verses"]):
                raise ValueError(f"Webster oracle verse carrier count mismatch at {source_book['name']} {number}")
            chapter_total += 1
            for source_verse, verse_node in zip(source_chapter["verses"], verse_nodes, strict=True):
                verse_number = source_verse["verse"]
                expected = {"type": "verse", "n": str(verse_number), xml_id: f"{chapter_id}-verse-{verse_number:03d}", xml_space: "preserve"}
                observed_text = "" if verse_node.text is None else verse_node.text
                if verse_node.tag != q("ab") or dict(verse_node.attrib) != expected or observed_text != source_verse["text"] or len(verse_node) != 0 or verse_node.tail is not None:
                    raise ValueError(f"Webster oracle verse carrier/order/value mismatch at {source_book['name']} {number}:{verse_number}")
                verse_total += 1
    if chapter_total != 1189 or verse_total != 31102:
        raise ValueError("Webster oracle complete chapter/verse count mismatch")


def _verify_descriptor(manifest, candidate) -> None:
    record = _thaw(candidate.manifest)
    schema = _object(manifest.authority_path("candidate-package-schema").read_bytes(), "package schema")
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=lambda item: list(item.path))
    if errors:
        raise ValueError(f"Webster oracle candidate manifest schema failure: {errors[0].message}")
    expected_path = manifest.path.relative_to(manifest.repository_root).as_posix()
    if record.get("contract") != "ocd-candidate-package-v1" or record.get("status") != "nonaccepted" or record.get("source_id") != "webster-retained-json" or record.get("source_manifest") != {"path": expected_path, "sha256": manifest.sha256} or record.get("converter") != _thaw(manifest.record["converter"]) or record.get("package_schema") != _thaw(manifest.record["package_schema"]):
        raise ValueError("Webster oracle candidate manifest source binding drift")
    members = record.get("members")
    expected_names = {"README.source.md", "content.tei.xml", "provenance.json", "source-accountability.json", "unresolved.jsonl"}
    if not isinstance(members, list) or {row.get("name") for row in members if isinstance(row, dict)} != expected_names or len(members) != 5:
        raise ValueError("Webster oracle candidate member inventory is incomplete")
    for row in members:
        content = candidate.member_bytes(row["name"])
        if row.get("bytes") != len(content) or row.get("sha256") != _digest(content):
            raise ValueError(f"Webster oracle candidate member binding drift: {row['name']}")


def _closure_digest(policy: dict[str, object], repository_root: Path) -> str:
    inventory = {path: _digest((repository_root / path).read_bytes()) for path in policy["route_dependencies"]["oracle_import_closure"]}
    return _digest(_canonical(inventory))


def oracle(source_manifest, candidate):
    source_manifest.verify()
    candidate.verify_integrity()
    if source_manifest.record.get("work_id") != "webster" or source_manifest.record.get("source_id") != "webster-retained-json" or not _selector_matches(source_manifest.record.get("source_selection")):
        raise ValueError("Webster oracle source manifest identity/selector drift")
    profile = _object(source_manifest.authority_path("webster-profile").read_bytes(), "profile")
    policy = _object(source_manifest.authority_path("webster-policy").read_bytes(), "policy")
    if not _selector_matches(profile.get("source_selector")) or not _selector_matches(policy.get("source_selection")):
        raise ValueError("Webster oracle profile/policy selector drift")
    authorities = _check_authorities(source_manifest, profile, policy)
    source_bytes = source_manifest.authority_path("webster-source").read_bytes()
    source, expected_accounting = _derive_source_accountability(source_bytes, profile)
    observed_accounting = _object(candidate.member_bytes("source-accountability.json"), "accountability")
    schema = _object(source_manifest.authority_path("webster-accountability-schema").read_bytes(), "accountability schema")
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(observed_accounting), key=lambda item: list(item.path))
    if errors:
        raise ValueError(f"Webster oracle accountability schema failure: {errors[0].message}")
    if observed_accounting != expected_accounting:
        raise ValueError("Webster oracle source carrier/field accounting differs from source")
    _check_tree(source, candidate.member_bytes("content.tei.xml"), policy)
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd")), parser))
    try:
        xsd.assertValid(etree.fromstring(candidate.member_bytes("content.tei.xml"), parser))
    except etree.DocumentInvalid as exc:
        raise ValueError("Webster oracle TEI P5 schema validation failed") from exc
    candidate_policy = policy["candidate"]
    if candidate.member_bytes("README.source.md") != str(candidate_policy["readme"]).encode("utf-8"):
        raise ValueError("Webster oracle candidate README differs from policy")
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canonical(item) for item in candidate_policy["unresolved"]):
        raise ValueError("Webster oracle unresolved-question inventory differs from policy")
    provenance = _object(candidate.member_bytes("provenance.json"), "provenance")
    expected_provenance = {"contract": "ocd-webster-provenance-v1", "source_manifest_sha256": source_manifest.sha256, "authorities": {name: str(row["sha256"]) for name, row in _authority_map(source_manifest).items()}, "converter": _thaw(source_manifest.record["converter"]), "scope": str(candidate_policy["scope"])}
    if provenance != expected_provenance:
        raise ValueError("Webster oracle provenance binding differs")
    _verify_descriptor(source_manifest, candidate)
    runtime = policy["runtime"]
    version = lambda parts: ".".join(str(part) for part in parts[:3])
    if version(etree.LXML_VERSION) != runtime["lxml"] or version(etree.LIBXML_VERSION) != runtime["libxml2_runtime"] or version(etree.LIBXML_COMPILED_VERSION) != runtime["libxml2_compiled"] or importlib.metadata.version("jsonschema") != runtime["jsonschema"]:
        raise ValueError("Webster oracle XML/schema runtime differs from policy")
    closure = _closure_digest(policy, source_manifest.repository_root)
    if closure != source_manifest.record["validator"]["import_closure_sha256"]:
        raise ValueError("Webster oracle import-closure digest differs from manifest")
    facts = MechanicalFacts(validator_implementation_sha256=_digest(Path(__file__).read_bytes()), validator_import_closure_sha256=closure, source_sha256=authorities["webster-source"], profile_sha256=authorities["webster-profile"], package_schema_sha256=authorities["candidate-package-schema"], xsd_sha256=authorities["tei-p5-xsd"], policy_sha256=authorities["webster-policy"], findings=())
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


oracle.oracle_id = "ocd-lib023-webster-independent-oracle"
oracle.oracle_version = "1"
