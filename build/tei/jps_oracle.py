"""Independent source-led oracle for the 37c-236 / LIB-023 JPS route."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from lxml import etree

from ocd_kernel.reconstruction.verifier import MechanicalFacts, verify_mechanical_facts


ORACLE_ID = "ocd-lib023-jps-independent-oracle"
ORACLE_VERSION = "1"
TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML_NS}}}id"
XML_SPACE = f"{{{XML_NS}}}space"
SOURCE_PATH = "raw/bible_databases/formats/json/JPS.json"
SOURCE_MARKER = "JPS: Jewish Publication Society Old Testament"
EXPECTED_SOURCE_SHA256 = (
    "cb698cfbf2e97843dd4357b725c96ac6e9b2f3f23c5e3e3f6a3cdb5912ca183a"
)
EXPECTED_COUNTS = {"books": 39, "chapters": 929, "verses": 23_213, "empty_text": 19}
EXPECTED_EMPTY = {
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


def _strict_json(content: bytes, label: str) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"JPS oracle: duplicate key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JPS oracle: {label} is not strict UTF-8 JSON") from exc


def _source_expectations(source_bytes: bytes):
    """Independently enumerate JSON objects, scalar leaves, and array edges."""
    source = _strict_json(source_bytes, "retained source")
    if not isinstance(source, dict) or list(source) != ["translation", "books"]:
        raise ValueError("JPS oracle: source root envelope/order")
    if source.get("translation") != SOURCE_MARKER:
        raise ValueError("JPS oracle: translation source label mismatch")
    books = source.get("books")
    if not isinstance(books, list):
        raise ValueError("JPS oracle: books is not an array")

    leaves: list[tuple[str, object]] = []
    arrays: list[tuple[str, int]] = []

    def descend(value: object, pointer: str) -> None:
        if isinstance(value, dict):
            if pointer == "":
                expected = ["translation", "books"]
            elif re.fullmatch(r"/books/\d+", pointer):
                expected = ["name", "chapters"]
            elif re.fullmatch(r"/books/\d+/chapters/\d+", pointer):
                expected = ["chapter", "verses"]
            elif re.fullmatch(r"/books/\d+/chapters/\d+/verses/\d+", pointer):
                expected = ["verse", "text"]
            else:
                raise ValueError(f"JPS oracle: unexpected source object at {pointer}")
            if list(value) != expected:
                raise ValueError(f"JPS oracle: source object fields/order at {pointer}")
            for key, child in value.items():
                descend(child, f"{pointer}/{key}")
        elif isinstance(value, list):
            if not value:
                raise ValueError(f"JPS oracle: empty source array at {pointer}")
            arrays.append((pointer, len(value)))
            for index, child in enumerate(value):
                descend(child, f"{pointer}/{index}")
        else:
            leaves.append((pointer, value))

    descend(source, "")
    chapter_arrays = [
        (pointer, size) for pointer, size in arrays if pointer.endswith("/chapters")
    ]
    verse_arrays = [
        (pointer, size) for pointer, size in arrays if pointer.endswith("/verses")
    ]
    empty: list[tuple[str, int, int]] = []
    for pointer, value in leaves:
        if pointer.endswith("/text") and value == "":
            parts = pointer.split("/")
            book = books[int(parts[2])]
            chapter = book["chapters"][int(parts[4])]
            verse = chapter["verses"][int(parts[6])]
            empty.append((book["name"], chapter["chapter"], verse["verse"]))

    counts = {
        "books": len(books),
        "chapters": sum(size for _, size in chapter_arrays),
        "verses": sum(size for _, size in verse_arrays),
        "empty_text": len(empty),
    }
    if counts != EXPECTED_COUNTS or set(empty) != EXPECTED_EMPTY:
        raise ValueError(
            "JPS oracle: complete source carrier counts or empty set mismatch"
        )
    if (
        len(chapter_arrays) != EXPECTED_COUNTS["books"]
        or len(verse_arrays) != EXPECTED_COUNTS["chapters"]
    ):
        raise ValueError("JPS oracle: source array boundary count mismatch")
    return source, leaves, arrays, empty, counts


def _expected_target(pointer: str) -> tuple[str, str | None]:
    parts = pointer.split("/")
    if pointer == "/translation":
        return "jps-source-label", None
    if parts[-1] == "name":
        return f"jps-b{int(parts[2]) + 1}-title", None
    book_id = f"jps-b{int(parts[2]) + 1}"
    chapter_position = int(parts[4]) + 1
    if parts[-1] == "chapter":
        chapter_id = f"{book_id}-c{chapter_position}"
        return chapter_id, "n"
    chapter_number = int(parts[4]) + 1
    verse_position = int(parts[6]) + 1
    verse_id = f"{book_id}-c{chapter_number}-v{verse_position}"
    return (verse_id, "n") if parts[-1] == "verse" else (verse_id, None)


def _expected_accountability(
    source_bytes: bytes, leaves, arrays, empty, counts
) -> dict[str, object]:
    fields = []
    for pointer, value in leaves:
        target, attribute = _expected_target(pointer)
        fields.append(
            {
                "pointer": pointer,
                "value_sha256": _sha(_canonical(value)),
                "target": target,
                "attribute": attribute,
                "disposition": "preserved",
            }
        )
    containers = [{"pointer": pointer, "length": size} for pointer, size in arrays]
    return {
        "contract": "ocd-37c236-source-accountability-v1",
        "source_sha256": _sha(source_bytes),
        "selector": "/books",
        "source_label_selector": "/translation",
        "counts": counts,
        "containers": containers,
        "fields": fields,
        "empty_text_carriers": [
            f"{book} {chapter}:{verse}" for book, chapter, verse in empty
        ],
        "excluded": [],
    }


def check_content(
    source_bytes: bytes, tei_bytes: bytes, accounting_bytes: bytes
) -> dict[str, int]:
    """Compare independent source expectations with the actual readable TEI tree."""
    if _sha(source_bytes) != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "JPS oracle: retained source digest is not the pinned JPS witness"
        )
    source, leaves, arrays, empty, counts = _source_expectations(source_bytes)
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, remove_blank_text=False
    )
    try:
        tree = etree.fromstring(tei_bytes, parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"JPS oracle: invalid XML: {exc}") from exc
    if tree.getroottree().docinfo.doctype:
        raise ValueError("JPS oracle: unexpected document type")
    for node in tree.iter():
        if not isinstance(node.tag, str):
            raise ValueError(
                "JPS oracle: unexpected XML comment or processing instruction"
            )
        if node.tail is not None:
            raise ValueError("JPS oracle: unexpected XML tail text")

    def q(name: str) -> str:
        return f"{{{TEI_NS}}}{name}"

    if tree.tag != q("TEI") or dict(tree.attrib) != {XML_ID: "jps"}:
        raise ValueError("JPS oracle: TEI root identity/attributes")
    if [node.tag for node in tree] != [q("teiHeader"), q("text")]:
        raise ValueError("JPS oracle: TEI root topology")
    if tree.text is not None or any(node.tail is not None for node in tree):
        raise ValueError("JPS oracle: unexpected root-level text")

    header = tree[0]
    if (
        header.attrib
        or header.text is not None
        or len(header) != 1
        or header[0].tag != q("fileDesc")
    ):
        raise ValueError("JPS oracle: header envelope")
    file_desc = header[0]
    if (
        file_desc.attrib
        or file_desc.text is not None
        or [node.tag for node in file_desc]
        != [q("titleStmt"), q("publicationStmt"), q("sourceDesc")]
    ):
        raise ValueError("JPS oracle: header section order/shape")
    title_stmt, publication_stmt, source_desc = file_desc
    if title_stmt.attrib or title_stmt.text is not None or len(title_stmt) != 1:
        raise ValueError("JPS oracle: title statement shape")
    title = title_stmt[0]
    if (
        title.tag != q("title")
        or dict(title.attrib) != {XML_ID: "jps-source-label"}
        or title.text != source["translation"]
        or len(title)
        or title.tail is not None
    ):
        raise ValueError("JPS oracle: source label drift")
    publication_text = "Nonaccepted route output; candidate and publication authorization remain pending."
    if (
        publication_stmt.attrib
        or publication_stmt.text is not None
        or len(publication_stmt) != 1
    ):
        raise ValueError("JPS oracle: publication statement shape")
    publication = publication_stmt[0]
    if (
        publication.tag != q("p")
        or publication.attrib
        or publication.text != publication_text
        or len(publication)
        or publication.tail is not None
    ):
        raise ValueError("JPS oracle: publication-status statement drift")
    source_text = (
        f"Exact retained source: {SOURCE_PATH} (sha256:{_sha(source_bytes)}). "
        "The /translation value is preserved as a source label only; work, textual form, edition, rights, and print-edition completeness are not established."
    )
    if source_desc.attrib or source_desc.text is not None or len(source_desc) != 1:
        raise ValueError("JPS oracle: source description shape")
    source_note = source_desc[0]
    if (
        source_note.tag != q("p")
        or source_note.attrib
        or source_note.text != source_text
        or len(source_note)
        or source_note.tail is not None
    ):
        raise ValueError("JPS oracle: source-scope qualification drift")

    text_node = tree[1]
    if (
        text_node.attrib
        or text_node.text is not None
        or len(text_node) != 1
        or text_node[0].tag != q("body")
    ):
        raise ValueError("JPS oracle: text/body topology")
    body = text_node[0]
    if body.attrib or body.text is not None or body.tail is not None:
        raise ValueError("JPS oracle: body attributes or surrounding text")

    seen_ids: set[str] = {"jps", "jps-source-label"}

    def identity(node, expected: str) -> None:
        observed = node.get(XML_ID)
        if observed != expected or observed in seen_ids:
            raise ValueError(
                f"JPS oracle: missing, duplicate, or wrong xml:id {expected}"
            )
        seen_ids.add(observed)

    books = source["books"]
    book_nodes = list(body)
    if len(book_nodes) != len(books):
        raise ValueError("JPS oracle: book omission, duplication, or invention")
    for book_index, (book, book_node) in enumerate(
        zip(books, book_nodes, strict=True), start=1
    ):
        book_id = f"jps-b{book_index}"
        if book_node.tag != q("div") or dict(book_node.attrib) != {
            "type": "book",
            "n": str(book_index),
            XML_ID: book_id,
        }:
            raise ValueError(f"JPS oracle: book order/identity/attributes {book_index}")
        identity(book_node, book_id)
        if book_node.text is not None or book_node.tail is not None:
            raise ValueError(f"JPS oracle: book wrapper text {book_index}")
        book_children = list(book_node)
        if len(book_children) != len(book["chapters"]) + 1:
            raise ValueError(
                f"JPS oracle: chapter omission/duplication/invention {book_index}"
            )
        head = book_children[0]
        if (
            head.tag != q("head")
            or dict(head.attrib) != {XML_ID: f"{book_id}-title"}
            or head.text != book["name"]
            or len(head)
            or head.tail is not None
        ):
            raise ValueError(f"JPS oracle: source book label {book_index}")
        identity(head, f"{book_id}-title")

        for chapter_index, (chapter, chapter_node) in enumerate(
            zip(book["chapters"], book_children[1:], strict=True), start=1
        ):
            chapter_number = chapter["chapter"]
            chapter_id = f"{book_id}-c{chapter_number}"
            if chapter_node.tag != q("div") or dict(chapter_node.attrib) != {
                "type": "chapter",
                "n": str(chapter_number),
                XML_ID: chapter_id,
            }:
                raise ValueError(
                    f"JPS oracle: chapter order/identity/number {book_index}/{chapter_index}"
                )
            identity(chapter_node, chapter_id)
            if chapter_node.text is not None or chapter_node.tail is not None:
                raise ValueError(
                    f"JPS oracle: chapter wrapper text {book_index}/{chapter_index}"
                )
            verse_nodes = list(chapter_node)
            if len(verse_nodes) != len(chapter["verses"]):
                raise ValueError(
                    f"JPS oracle: verse carrier omission/duplication/invention {book_index}/{chapter_index}"
                )
            for verse_index, (verse, verse_node) in enumerate(
                zip(chapter["verses"], verse_nodes, strict=True), start=1
            ):
                verse_id = f"{chapter_id}-v{verse['verse']}"
                expected_attrs = {
                    "type": "verse",
                    "n": str(verse["verse"]),
                    XML_ID: verse_id,
                    XML_SPACE: "preserve",
                }
                if (
                    verse_node.tag != q("ab")
                    or dict(verse_node.attrib) != expected_attrs
                ):
                    raise ValueError(
                        f"JPS oracle: verse order/identity/number {book_index}/{chapter_index}/{verse_index}"
                    )
                identity(verse_node, verse_id)
                if len(verse_node) or verse_node.tail is not None:
                    raise ValueError(
                        f"JPS oracle: nested or trailing verse content {book_index}/{chapter_index}/{verse_index}"
                    )
                expected_text = verse["text"]
                if expected_text == "":
                    if verse_node.text not in (None, ""):
                        raise ValueError(
                            f"JPS oracle: explicit empty verse text changed {book_index}/{chapter_index}/{verse_index}"
                        )
                elif verse_node.text != expected_text:
                    raise ValueError(
                        f"JPS oracle: source text changed {book_index}/{chapter_index}/{verse_index}"
                    )

    expected_ids = {"jps", "jps-source-label"}
    expected_ids.update(f"jps-b{book_index}" for book_index in range(1, len(books) + 1))
    for book_index, book in enumerate(books, start=1):
        book_id = f"jps-b{book_index}"
        expected_ids.add(f"{book_id}-title")
        for chapter in book["chapters"]:
            chapter_id = f"{book_id}-c{chapter['chapter']}"
            expected_ids.add(chapter_id)
            expected_ids.update(
                f"{chapter_id}-v{verse['verse']}" for verse in chapter["verses"]
            )
    if seen_ids != expected_ids:
        raise ValueError(
            "JPS oracle: actual TEI identity inventory differs from expected"
        )
    if any(not isinstance(node.tag, str) for node in tree.iter()):
        raise ValueError("JPS oracle: unexpected XML comment or processing instruction")

    observed_accountability = _strict_json(accounting_bytes, "source-accountability")
    expected_accountability = _expected_accountability(
        source_bytes, leaves, arrays, empty, counts
    )
    if observed_accountability != expected_accountability:
        raise ValueError("JPS oracle: source field/container accounting mismatch")
    return counts


def _closure_digest() -> str:
    root = Path(__file__).resolve().parents[2]
    paths = (
        "ocd_kernel/__init__.py",
        "ocd_kernel/reconstruction/__init__.py",
        "ocd_kernel/reconstruction/contract.py",
        "ocd_kernel/reconstruction/verifier.py",
    )
    members = {name: _sha((root / name).read_bytes()) for name in paths}
    return _sha(_canonical(members))


def _authority(manifest, name: str):
    matches = [item for item in manifest.record["authorities"] if item["name"] == name]
    if len(matches) != 1:
        raise ValueError(f"JPS oracle: expected exactly one {name} authority")
    return matches[0]


def _expected_unresolved(source_sha: str) -> bytes:
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


def _expected_readme(manifest, source_sha: str) -> bytes:
    license_text = manifest.authority_path("jps-upstream-license").read_bytes()
    prefix = (
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
    ).encode("utf-8")
    return prefix + license_text


def oracle(manifest, candidate):
    """Supported independent-checker seam for a coordinator-created package."""
    manifest.verify()
    candidate.verify_integrity()
    record = manifest.record
    if (
        record.get("ticket_id") != "37c-236"
        or record.get("work_id") != "jps"
        or record.get("source_id") != "jps-retained-json-20260919"
    ):
        raise ValueError("JPS oracle: manifest work identity mismatch")
    source_authority = _authority(manifest, "jps-source")
    if (
        source_authority.get("role") != "primary-source"
        or source_authority.get("path") != SOURCE_PATH
    ):
        raise ValueError("JPS oracle: retained source authority mismatch")
    source_bytes = manifest.authority_path("jps-source").read_bytes()
    profile = _strict_json(
        manifest.authority_path("jps-profile").read_bytes(), "reconstruction profile"
    )
    policy = _strict_json(
        manifest.authority_path("jps-policy").read_bytes(), "validation policy"
    )
    if (
        profile.get("profile_id") != "jps-retained-json-complete-v1"
        or profile.get("source_member", {}).get("sha256") != _sha(source_bytes)
        or profile.get("source_selector", {}).get("content_pointer") != "/books"
        or policy.get("source_selector") != "/books"
        or policy.get("work_id") != "jps"
    ):
        raise ValueError("JPS oracle: profile or policy binding mismatch")

    candidate_root = candidate.path
    tei_bytes = (candidate_root / "content.tei.xml").read_bytes()
    accounting_bytes = (candidate_root / "source-accountability.json").read_bytes()
    check_content(source_bytes, tei_bytes, accounting_bytes)

    schema = etree.XMLSchema(etree.parse(str(manifest.authority_path("tei-p5-xsd"))))
    schema.assertValid(etree.fromstring(tei_bytes))

    source_sha = _sha(source_bytes)
    if (candidate_root / "README.source.md").read_bytes() != _expected_readme(
        manifest, source_sha
    ):
        raise ValueError(
            "JPS oracle: source/rights README differs from retained support evidence"
        )
    if (candidate_root / "unresolved.jsonl").read_bytes() != _expected_unresolved(
        source_sha
    ):
        raise ValueError("JPS oracle: unresolved identity/rights scope drift")

    bindings = {
        str(item["name"]): str(item["sha256"]) for item in record["authorities"]
    }
    expected_provenance = {
        "source_manifest_sha256": manifest.sha256,
        "authorities": bindings,
        "converter": dict(record["converter"]),
        "scope": "complete exact JPS.json /books selector plus /translation source label; no edition, rights, or print-completeness claim",
    }
    if (
        _strict_json((candidate_root / "provenance.json").read_bytes(), "provenance")
        != expected_provenance
    ):
        raise ValueError("JPS oracle: provenance binding drift")

    facts = MechanicalFacts(
        validator_implementation_sha256=_sha(Path(__file__).read_bytes()),
        validator_import_closure_sha256=_closure_digest(),
        source_sha256=source_sha,
        profile_sha256=bindings["jps-profile"],
        package_schema_sha256=bindings["candidate-package-schema"],
        xsd_sha256=bindings["tei-p5-xsd"],
        policy_sha256=bindings["jps-policy"],
        findings=(),
    )
    return verify_mechanical_facts(manifest, candidate, facts).as_record()


oracle.oracle_id = ORACLE_ID
oracle.oracle_version = ORACLE_VERSION
