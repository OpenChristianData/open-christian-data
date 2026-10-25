"""Independent source-led oracle for ticket 37c-087 / LIB-024."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction import CandidatePackage, SourceManifest
from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-37c087-bsb-independent-oracle"
ORACLE_VERSION = "1"
TICKET_ID = "37c-087"
WORK_ID = "bsb"
SOURCE_ID = "ocd-37c087-bsb-retained-native-json-v1"
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


def _authority_by_role(source_manifest: SourceManifest, role: str) -> Mapping[str, object]:
    authorities = source_manifest.record.get("authorities")
    if not isinstance(authorities, tuple):
        raise ValueError("BSB authority inventory is invalid")
    matches = [
        item
        for item in authorities
        if isinstance(item, Mapping) and item.get("role") == role
    ]
    if len(matches) != 1:
        raise ValueError(f"BSB requires exactly one {role} authority")
    return matches[0]


def _role_bytes(source_manifest: SourceManifest, role: str) -> bytes:
    authority = _authority_by_role(source_manifest, role)
    return source_manifest.authority_path(str(authority["name"])).read_bytes()


def _check_manifest_identity(source_manifest: SourceManifest) -> None:
    record = source_manifest.record
    if (
        record.get("ticket_id") != TICKET_ID
        or record.get("work_id") != WORK_ID
        or record.get("source_id") != SOURCE_ID
    ):
        raise ValueError("BSB oracle source identity drifted")
    source = _authority_by_role(source_manifest, "primary-source")
    if source.get("name") != "retained-bsb-json":
        raise ValueError("BSB primary-source authority drifted")
    scope = record.get("scope")
    if not isinstance(scope, Mapping) or scope.get("source_member") != "retained-bsb-json":
        raise ValueError("BSB source scope drifted")


def _read_native_source(
    source_manifest: SourceManifest,
) -> tuple[bytes, dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    _check_manifest_identity(source_manifest)
    source_bytes = _role_bytes(source_manifest, "primary-source")
    payload = _strict_json(source_bytes, "retained BSB JSON")
    config = _strict_json(_role_bytes(source_manifest, "local-metadata-claim-evidence"), "BSB config")
    profile = _strict_json(
        _role_bytes(source_manifest, "complete-source-feature-profile"),
        "BSB reconstruction profile",
    )
    policy = _strict_json(
        _role_bytes(source_manifest, "independent-validation-policy"),
        "BSB validation policy",
    )
    if (
        profile.get("contract") != "ocd-37c087-reconstruction-profile-v1"
        or profile.get("profile_id") != PROFILE_ID
        or policy.get("contract") != "ocd-37c087-validation-policy-v1"
        or policy.get("policy_id") != POLICY_ID
        or config.get("resource_id") != WORK_ID
        or config.get("source_file") != "raw/bible_databases/formats/json/BSB.json"
    ):
        raise ValueError("BSB source-local authority identity drifted")
    if _sha(source_bytes) != str(_authority_by_role(source_manifest, "primary-source")["sha256"]):
        raise ValueError("BSB retained source digest drifted")
    return source_bytes, payload, config, profile, policy


def _enumerate_source(
    payload: Mapping[str, object], profile: Mapping[str, object], policy: Mapping[str, object]
) -> tuple[str, list[Mapping[str, object]], int, int, list[list[object]]]:
    if list(payload) != ["translation", "books"]:
        raise ValueError("BSB native JSON envelope or key order drifted")
    marker = payload.get("translation")
    books = payload.get("books")
    if not isinstance(marker, str) or not marker or not isinstance(books, list):
        raise ValueError("BSB native JSON root values are invalid")
    envelope = profile.get("source_envelope")
    required = policy.get("required_counts")
    if not isinstance(envelope, Mapping) or not isinstance(required, Mapping):
        raise ValueError("BSB source census authority is missing")
    names = envelope.get("book_names_in_source_order")
    if not isinstance(names, list) or len(books) != int(required["books"]):
        raise ValueError("BSB book count authority is invalid")
    if [book.get("name") if isinstance(book, Mapping) else None for book in books] != names:
        raise ValueError("BSB book names or source order drifted")

    chapters_seen = 0
    verses_seen = 0
    empties: list[list[object]] = []
    for b_index in range(len(books)):
        book = books[b_index]
        if not isinstance(book, Mapping) or list(book) != ["name", "chapters"]:
            raise ValueError(f"BSB book carrier {b_index} is invalid")
        chapters = book["chapters"]
        if not isinstance(chapters, list):
            raise ValueError(f"BSB chapter collection {b_index} is invalid")
        for c_index in range(len(chapters)):
            chapter = chapters[c_index]
            if not isinstance(chapter, Mapping) or list(chapter) != ["chapter", "verses"]:
                raise ValueError(f"BSB chapter carrier {b_index}/{c_index} is invalid")
            if type(chapter["chapter"]) is not int or chapter["chapter"] != c_index + 1:
                raise ValueError(f"BSB chapter number drifted at {b_index}/{c_index}")
            verses = chapter["verses"]
            if not isinstance(verses, list):
                raise ValueError(f"BSB verse collection {b_index}/{c_index} is invalid")
            chapters_seen += 1
            for v_index in range(len(verses)):
                verse = verses[v_index]
                if not isinstance(verse, Mapping) or list(verse) != ["verse", "text"]:
                    raise ValueError(f"BSB verse carrier {b_index}/{c_index}/{v_index} is invalid")
                if type(verse["verse"]) is not int or verse["verse"] != v_index + 1:
                    raise ValueError(f"BSB verse number drifted at {b_index}/{c_index}/{v_index}")
                if not isinstance(verse["text"], str):
                    raise ValueError(f"BSB verse text is not a string at {b_index}/{c_index}/{v_index}")
                verses_seen += 1
                if verse["text"] == "":
                    empties.append([book["name"], c_index + 1, v_index + 1])
    if (
        chapters_seen != int(required["chapters"])
        or verses_seen != int(required["verses"])
        or verses_seen - len(empties) != int(required["nonempty_verses"])
        or len(empties) != int(required["empty_verses"])
        or chapters_seen != int(envelope["chapter_count"])
        or verses_seen != int(envelope["verse_row_count"])
        or empties != envelope["empty_verse_locations"]
    ):
        raise ValueError("BSB source carrier census drifted")
    return marker, books, chapters_seen, verses_seen, empties


def _tag(local: str) -> str:
    return f"{{{TEI_NS}}}{local}"


def _child(parent: etree._Element, local: str) -> etree._Element:
    children = [item for item in parent if item.tag == _tag(local)]
    if len(children) != 1:
        raise ValueError(f"BSB candidate expected one {local} child")
    return children[0]


def _children_in_order(parent: etree._Element, names: list[str]) -> list[etree._Element]:
    children = list(parent)
    if [item.tag for item in children] != [_tag(name) for name in names]:
        raise ValueError(f"BSB candidate child topology drifted under {etree.QName(parent).localname}")
    return children


def _verify_candidate_tei(
    source_manifest: SourceManifest,
    candidate: CandidatePackage,
    config: Mapping[str, object],
    marker: str,
    books: list[Mapping[str, object]],
    source_bytes: bytes,
) -> None:
    try:
        root = etree.fromstring(
            candidate.member_bytes("content.tei.xml"),
            parser=etree.XMLParser(resolve_entities=False, remove_blank_text=False),
        )
    except etree.XMLSyntaxError as exc:
        raise ValueError("BSB candidate TEI is not well-formed") from exc
    schema = etree.XMLSchema(
        etree.parse(str(_role_path(source_manifest, "tei-validation-schema")))
    )
    if not schema.validate(root):
        raise ValueError(f"BSB candidate TEI schema failure: {schema.error_log}")
    if root.tag != _tag("TEI") or root.attrib != {XML_ID: "bsb-candidate"}:
        raise ValueError("BSB candidate root drifted")
    for node in root.iter():
        if node.tail is not None and node.tail.strip():
            raise ValueError("BSB candidate has an unexpected non-whitespace tail")

    # Keep the path checks explicit so a structurally valid but semantically
    # displaced header cannot satisfy this oracle.
    header, _ = _children_in_order(root, ["teiHeader", "text"])
    file_desc, encoding_desc = _children_in_order(header, ["fileDesc", "encodingDesc"])
    title_stmt, publication_stmt, source_desc = _children_in_order(
        file_desc, ["titleStmt", "publicationStmt", "sourceDesc"]
    )
    title = _child(title_stmt, "title")
    if title.attrib or title.text != config["title"]:
        raise ValueError("BSB candidate title metadata drifted")
    publisher, availability = _children_in_order(
        publication_stmt, ["publisher", "availability"]
    )
    if publisher.attrib or publisher.text != "Open Christian Data":
        raise ValueError("BSB candidate publisher metadata drifted")
    if availability.attrib != {"status": "restricted"}:
        raise ValueError("BSB candidate availability metadata drifted")
    _child(availability, "p")
    bibl = _child(source_desc, "bibl")
    if bibl.attrib != {XML_ID: "bsb-retained-source"}:
        raise ValueError("BSB candidate source binding drifted")
    bibl_children = _children_in_order(
        bibl, ["title", "note", "ptr", "idno", "num", "note"]
    )
    if (
        bibl_children[0].attrib != {"type": "translation-marker"}
        or bibl_children[0].text != marker
        or bibl_children[1].attrib != {XML_ID: "bsb-translation", "type": "translation-marker"}
        or bibl_children[1].text != marker
        or bibl_children[2].attrib != {"target": config["source_url"]}
        or bibl_children[3].attrib != {"type": "sha256"}
        or bibl_children[3].text != _sha(source_bytes)
        or bibl_children[4].attrib != {"type": "bytes"}
        or bibl_children[4].text != str(len(source_bytes))
        or bibl_children[5].attrib != {"type": "scope"}
    ):
        raise ValueError("BSB candidate source description drifted")
    if _children_in_order(encoding_desc, ["p"])[0].text is None:
        raise ValueError("BSB candidate mapping description is missing")

    text_node = _child(root, "text")
    if text_node.attrib != {XML_ID: "bsb-text", "type": "bible"}:
        raise ValueError("BSB candidate text binding drifted")
    body = _child(text_node, "body")
    if body.attrib != {XML_ID: "bsb-body"}:
        raise ValueError("BSB candidate body binding drifted")
    book_nodes = list(body)
    if len(book_nodes) != len(books) or any(node.tag != _tag("div") for node in book_nodes):
        raise ValueError("BSB candidate book census drifted")
    for b_index, (book_node, source_book) in enumerate(zip(book_nodes, books), 1):
        book_id = f"bsb-book-{b_index:02d}"
        if book_node.attrib != {"type": "book", "n": str(b_index), XML_ID: book_id}:
            raise ValueError(f"BSB candidate book binding drifted at {b_index}")
        children = list(book_node)
        if not children or children[0].tag != _tag("head"):
            raise ValueError(f"BSB candidate book head missing at {b_index}")
        if children[0].attrib or children[0].text != source_book["name"]:
            raise ValueError(f"BSB candidate book name drifted at {b_index}")
        source_chapters = source_book["chapters"]
        assert isinstance(source_chapters, list)
        if len(children) != len(source_chapters) + 1:
            raise ValueError(f"BSB candidate chapter census drifted at {b_index}")
        for c_index, (chapter_node, source_chapter) in enumerate(
            zip(children[1:], source_chapters), 1
        ):
            if chapter_node.tag != _tag("div"):
                raise ValueError(f"BSB candidate chapter topology drifted at {b_index}/{c_index}")
            chapter_id = f"{book_id}-chapter-{c_index:03d}"
            if chapter_node.attrib != {
                "type": "chapter",
                "n": str(source_chapter["chapter"]),
                XML_ID: chapter_id,
            }:
                raise ValueError(f"BSB candidate chapter binding drifted at {b_index}/{c_index}")
            chapter_children = list(chapter_node)
            if not chapter_children or chapter_children[0].tag != _tag("head"):
                raise ValueError(f"BSB candidate chapter head missing at {b_index}/{c_index}")
            if chapter_children[0].attrib or chapter_children[0].text != str(source_chapter["chapter"]):
                raise ValueError(f"BSB candidate chapter number drifted at {b_index}/{c_index}")
            source_verses = source_chapter["verses"]
            assert isinstance(source_verses, list)
            if len(chapter_children) != len(source_verses) + 1:
                raise ValueError(f"BSB candidate verse census drifted at {b_index}/{c_index}")
            for v_index, (verse_node, source_verse) in enumerate(
                zip(chapter_children[1:], source_verses), 1
            ):
                verse_id = f"{chapter_id}-verse-{v_index:03d}"
                if verse_node.tag != _tag("ab") or verse_node.attrib != {
                    "type": "verse",
                    "n": str(source_verse["verse"]),
                    XML_ID: verse_id,
                }:
                    raise ValueError(f"BSB candidate verse binding drifted at {b_index}/{c_index}/{v_index}")
                observed = verse_node.text if verse_node.text is not None else ""
                if observed != source_verse["text"]:
                    raise ValueError(f"BSB candidate verse text drifted at {b_index}/{c_index}/{v_index}")


def _role_path(source_manifest: SourceManifest, role: str) -> Path:
    authority = _authority_by_role(source_manifest, role)
    return source_manifest.authority_path(str(authority["name"]))


def _expected_accountability(
    marker: str, books: list[Mapping[str, object]], source_manifest: SourceManifest, source_bytes: bytes
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    rows.append(
        {
            "id": "bsb-translation",
            "kind": "top-level-field",
            "source_path": "/translation",
            "source_field": "translation",
            "source_index": 0,
            "value": marker,
            "target": "#bsb-translation",
            "status": "represented",
        }
    )
    rows.append(
        {
            "id": "bsb-books",
            "kind": "top-level-field",
            "source_path": "/books",
            "source_field": "books",
            "source_index": 1,
            "value": len(books),
            "target": "#bsb-text",
            "status": "represented",
        }
    )
    for b_index, book in enumerate(books):
        book_id = f"bsb-book-{b_index + 1:02d}"
        book_name = book["name"]
        assert isinstance(book_name, str)
        rows.append(
            {
                "id": book_id,
                "kind": "book",
                "source_path": f"/books/{b_index}",
                "source_field": "name",
                "source_index": b_index,
                "book_index": b_index,
                "book_name": book_name,
                "value": book_name,
                "target": f"#{book_id}",
                "status": "represented",
            }
        )
        chapters = book["chapters"]
        assert isinstance(chapters, list)
        for c_index, chapter in enumerate(chapters):
            chapter_id = f"{book_id}-chapter-{c_index + 1:03d}"
            chapter_number = chapter["chapter"]
            assert isinstance(chapter_number, int)
            rows.append(
                {
                    "id": chapter_id,
                    "kind": "chapter",
                    "source_path": f"/books/{b_index}/chapters/{c_index}",
                    "source_field": "chapter",
                    "source_index": c_index,
                    "book_index": b_index,
                    "chapter_index": c_index,
                    "book_name": book_name,
                    "chapter_number": chapter_number,
                    "value": chapter_number,
                    "target": f"#{chapter_id}",
                    "status": "represented",
                }
            )
            verses = chapter["verses"]
            assert isinstance(verses, list)
            for v_index, verse in enumerate(verses):
                verse_id = f"{chapter_id}-verse-{v_index + 1:03d}"
                verse_number = verse["verse"]
                verse_text = verse["text"]
                assert isinstance(verse_number, int) and isinstance(verse_text, str)
                rows.append(
                    {
                        "id": verse_id,
                        "kind": "verse",
                        "source_path": f"/books/{b_index}/chapters/{c_index}/verses/{v_index}",
                        "source_field": "text",
                        "source_index": v_index,
                        "book_index": b_index,
                        "chapter_index": c_index,
                        "verse_index": v_index,
                        "book_name": book_name,
                        "chapter_number": chapter_number,
                        "verse_number": verse_number,
                        "value": verse_text,
                        "target": f"#{verse_id}",
                        "status": "represented",
                    }
                )
    return {
        "contract": "ocd-37c087-bsb-source-accountability-v1",
        "ticket_id": TICKET_ID,
        "work_id": WORK_ID,
        "source_id": SOURCE_ID,
        "source_sha256": _sha(source_bytes),
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


def _expected_provenance(
    source_manifest: SourceManifest,
    config: Mapping[str, object],
    source_bytes: bytes,
    marker: str,
) -> dict[str, object]:
    source_authority = _authority_by_role(source_manifest, "primary-source")
    config_authority = _authority_by_role(
        source_manifest, "local-metadata-claim-evidence"
    )
    return {
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
            "path": config_authority["path"],
            "bytes": config_authority["bytes"],
            "sha256": config_authority["sha256"],
            "title": config["title"],
            "source_edition": config["source_edition"],
            "license": config["license"],
        },
        "source": {
            "path": source_authority["path"],
            "bytes": len(source_bytes),
            "sha256": _sha(source_bytes),
            "translation": marker,
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


def _expected_unresolved(source_manifest: SourceManifest, config: Mapping[str, object]) -> bytes:
    source_authority = _authority_by_role(source_manifest, "primary-source")
    source_path = str(source_authority["path"])
    source_sha = str(source_authority["sha256"])
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


def _closure_digest(root: Path) -> str:
    relative_paths = (
        "build/tei/bsb_oracle.py",
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
    )
    records = [
        {"path": relative, "sha256": _sha((root / relative).read_bytes())}
        for relative in relative_paths
    ]
    return _sha(_canonical(records))


def _oracle(
    source_manifest: SourceManifest, candidate: CandidatePackage
) -> Mapping[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    source_bytes, payload, config, profile, policy = _read_native_source(source_manifest)
    marker, books, _, _, _ = _enumerate_source(payload, profile, policy)
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("BSB candidate acceptance boundary drifted")
    expected_manifest_path = source_manifest.path.relative_to(
        source_manifest.repository_root
    ).as_posix()
    if candidate.manifest.get("source_manifest") != {
        "path": expected_manifest_path,
        "sha256": source_manifest.sha256,
    }:
        raise ValueError("BSB candidate manifest binding drifted")
    converter = source_manifest.record.get("converter")
    if not isinstance(converter, Mapping) or candidate.manifest.get("converter") != dict(converter):
        raise ValueError("BSB candidate converter binding drifted")
    package_schema = source_manifest.record.get("package_schema")
    if not isinstance(package_schema, Mapping) or candidate.manifest.get("package_schema") != dict(package_schema):
        raise ValueError("BSB candidate package-schema binding drifted")

    _verify_candidate_tei(source_manifest, candidate, config, marker, books, source_bytes)
    account_bytes = candidate.member_bytes("source-accountability.json")
    account = _strict_json(account_bytes, "BSB source accountability")
    account_schema = _strict_json(
        _role_bytes(source_manifest, "source-accountability-schema"),
        "BSB source-accountability schema",
    )
    schema_errors = sorted(Draft202012Validator(account_schema).iter_errors(account), key=str)
    if schema_errors:
        raise ValueError(f"BSB source-accountability schema failure: {schema_errors[0].message}")
    expected_account = _expected_accountability(marker, books, source_manifest, source_bytes)
    if account != expected_account or account_bytes != _canonical(expected_account):
        raise ValueError("BSB source accountability drifted")
    expected_provenance = _expected_provenance(
        source_manifest, config, source_bytes, marker
    )
    provenance_bytes = candidate.member_bytes("provenance.json")
    if _strict_json(provenance_bytes, "BSB provenance") != expected_provenance or provenance_bytes != _canonical(expected_provenance):
        raise ValueError("BSB candidate provenance drifted")
    if candidate.member_bytes("unresolved.jsonl") != _expected_unresolved(
        source_manifest, config
    ):
        raise ValueError("BSB unresolved evidence drifted")
    if candidate.member_bytes("README.source.md") != _role_bytes(
        source_manifest, "source-attribution-readme"
    ):
        raise ValueError("BSB source README drifted")

    closure = _closure_digest(source_manifest.repository_root)
    validator = source_manifest.record.get("validator")
    if not isinstance(validator, Mapping) or validator.get("import_closure_sha256") != closure:
        raise ValueError("BSB oracle import closure drifted")
    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=closure,
        source_sha256=_sha(source_bytes),
        profile_sha256=str(_authority_by_role(source_manifest, "complete-source-feature-profile")["sha256"]),
        package_schema_sha256=str(_authority_by_role(source_manifest, "candidate-package-schema")["sha256"]),
        xsd_sha256=str(_authority_by_role(source_manifest, "tei-validation-schema")["sha256"]),
        policy_sha256=str(_authority_by_role(source_manifest, "independent-validation-policy")["sha256"]),
        findings=(),
    )
    return verify_mechanical_facts(source_manifest, candidate, facts).as_record()


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION


__all__ = (
    "ORACLE_ID",
    "ORACLE_VERSION",
    "_closure_digest",
    "_oracle",
)
