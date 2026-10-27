"""Independent retained-source oracle for the two-volume Calvin candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema


ORACLE_ID = "ocd-calvins-institutes-independent-two-volume-oracle"
ORACLE_VERSION = "1"

_RIGHTS_STATEMENT = (
    "The retained Project Gutenberg wrappers state a United States public-domain basis and a jurisdiction warning; "
    "Project Gutenberg license and trademark terms remain separate retained evidence. Worldwide status and publication "
    "authorization are unresolved."
)
_RIGHTS = {
    "candidate": "nonaccepted; no publication authorization",
    "project_gutenberg_license_and_trademark": "retained terms apply to Gutenberg-branded redistribution",
    "source_claim": "underlying works stated by Project Gutenberg to lack United States copyright protection",
    "worldwide_status": "unresolved; retained wrappers direct users to check local law",
}
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
# Nested text sections overlap; select each descendant once before checking ancestry.
_TEXT_IDENTIFIED_NODES = etree.XPath("//*[@xml:id][ancestor::tei:text]", namespaces={"tei": _TEI})
_TEXT_LINE_IDS = etree.XPath("//tei:lb[ancestor::tei:text]/@xml:id", namespaces={"tei": _TEI})
_BOOK = re.compile(r"^BOOK\s+([IVX]+)\.(?:\s|$)", re.I)
_CHAPTER = re.compile(r"^CHAPTER\s+([IVXLCDM]+)\.(?:\s|$)", re.I)
_FOOTNOTE = re.compile(r"^Footnote\s+(\d+):$", re.I)
_V1_NOTE = re.compile(r"^\s*(\d+)\s+")
_EMPHASIS = re.compile(r"_(.+?)_", re.S)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _strict(content: bytes, label: str, *, canonical: bool = True) -> dict[str, object]:
    value = json.loads(content)
    if not isinstance(value, dict) or (canonical and _canonical(value) != content):
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    values = [item for item in source_manifest.record["authorities"] if item.get("name") == name]
    if len(values) != 1:
        raise ValueError(f"Independent Calvin authority {name} cardinality mismatch")
    return values[0]


def _roman(text: str) -> int:
    table = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for index, character in enumerate(text.upper()):
        value = table[character]
        total += -value if index + 1 < len(text) and table[text[index + 1].upper()] > value else value
    return total


def _scan_records(volume: int, member: str, content: bytes) -> list[dict[str, object]]:
    matches = list(re.finditer(rb".*?\r\n", content, re.S))
    if not matches or matches[-1].end() != len(content):
        raise ValueError(f"Calvin volume {volume} does not consist entirely of CRLF records")
    rows = []
    for number, match in enumerate(matches, 1):
        record = match.group(0)
        payload = record[:-2]
        text = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        rows.append(
            {
                "volume": volume,
                "member": member,
                "line": number,
                "byte_start": match.start(),
                "byte_end": match.end(),
                "terminator": "CRLF",
                "text": text,
                "text_sha256": _sha(payload),
                "record_sha256": _sha(record),
            }
        )
    return rows


def _paragraphs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: list[list[dict[str, object]]] = []
    for row in rows:
        blank = not str(row["text"]).strip()
        if not groups or (not str(groups[-1][0]["text"]).strip()) != blank:
            groups.append([])
        groups[-1].append(row)
    result = []
    for ordinal, group in enumerate(groups, 1):
        volume = int(group[0]["volume"])
        text = "\n".join(str(item["text"]) for item in group)
        result.append(
            {
                "id": f"calvin-v{volume}-block-{ordinal:04d}",
                "volume": volume,
                "ordinal": ordinal,
                "start_line": int(group[0]["line"]),
                "end_line": int(group[-1]["line"]),
                "blank": not str(group[0]["text"]).strip(),
                "text": text,
                "text_sha256": _sha(text.encode()),
                "line_ids": [f"calvin-v{volume}-line-{int(item['line']):05d}" for item in group],
                "lines": group,
            }
        )
    return result


def _source_position(block: Mapping[str, object], offset: int) -> tuple[int, int]:
    prefix = str(block["text"])[:offset]
    return int(block["start_line"]) + prefix.count("\n"), len(prefix.rsplit("\n", 1)[-1]) + 1


def _is_scripture_index_table_block(block: Mapping[str, object]) -> bool:
    """Independently recognize the retained fixed-width Scripture-index runs."""
    lines = block.get("lines")
    return (
        block.get("category") == "scripture-index-entry"
        and isinstance(lines, list)
        and bool(lines)
        and all(
            isinstance(source_line, Mapping)
            and len(str(source_line.get("text", ""))) >= 40
            and str(source_line["text"])[:23] == " " * 23
            for source_line in lines
        )
    )


def _independent_model(all_blocks: list[list[dict[str, object]]]) -> dict[str, object]:
    books: list[dict[str, object]] = []
    chapters: list[dict[str, object]] = []
    front: list[dict[str, object]] = []
    arguments: list[dict[str, object]] = []
    body_rows: list[dict[str, object]] = []
    indexes: dict[str, list[dict[str, object]]] = {"principal-matters": [], "scripture": []}
    anchors: dict[int, list[dict[str, object]]] = {1: [], 2: []}
    notes: dict[int, list[dict[str, object]]] = {1: [], 2: []}
    emphasis: list[dict[str, object]] = []
    emphasis_ordinal = 0
    for volume in (1, 2):
        phase = "pg-header"
        current_book: int | None = None
        current_chapter: int | None = None
        active_note: dict[str, object] | None = None
        has_book = False
        for block in all_blocks[volume - 1]:
            first = str(block["text"]).partition("\n")[0].strip()
            upper = first.upper()
            line = int(block["start_line"])
            block.update(book=current_book, chapter=current_chapter, note=None)
            category = ""
            disposition = "represented"
            if line == (27 if volume == 1 else 29):
                category, disposition, phase = "gutenberg-start-marker", "evidence-only", "front"
            elif line == (30824 if volume == 1 else 38373):
                category, disposition, phase = "gutenberg-end-marker", "evidence-only", "pg-license"
            elif phase == "pg-header":
                category, disposition = "gutenberg-header-evidence", "evidence-only"
            elif phase == "pg-license":
                category, disposition = "gutenberg-license-evidence", "evidence-only"
            elif bool(block["blank"]):
                spacing_phase = {
                    "front": "front-matter",
                    "body": "chapter-body",
                    "argument": "book-argument",
                    "pg-header": "gutenberg-header",
                    "pg-license": "gutenberg-license",
                }.get(phase, phase)
                category = f"{spacing_phase}-spacing"
                disposition = "evidence-only" if phase.startswith("pg-") else "represented"
            elif volume == 2 and line == 32957:
                phase, category = "principal-matters-index", "principal-matters-index-heading"
                indexes["principal-matters"].append(block)
            elif volume == 2 and line == 33424:
                phase, category = "scripture-index", "scripture-index-heading"
                indexes["scripture"].append(block)
            elif phase == "principal-matters-index":
                category = "principal-matters-index-entry"
                indexes["principal-matters"].append(block)
            elif phase == "scripture-index":
                category = "transcriber-note" if line == 38364 else "scripture-index-entry"
                indexes["scripture"].append(block)
            elif match := _BOOK.match(first):
                current_book = _roman(match.group(1))
                current_chapter = None
                phase = "body" if volume == 2 and current_book == 3 else "argument"
                category = "book-heading"
                has_book = True
                block.update(book=current_book, chapter=None)
                books.append({"volume": volume, "book": current_book, "start_line": line, "end_line": block["end_line"], "heading_sha256": block["text_sha256"]})
            elif match := _CHAPTER.match(first):
                current_chapter = _roman(match.group(1))
                phase = "body"
                active_note = None
                category = "chapter-heading"
                block.update(book=current_book, chapter=current_chapter)
                chapters.append({"volume": volume, "book": current_book, "chapter": current_chapter, "start_line": line, "end_line": block["end_line"], "heading_sha256": block["text_sha256"]})
            elif volume == 1 and upper == "FOOTNOTES":
                phase, category = "volume-notes", "notes-heading"
                block.update(book=None, chapter=None)
            elif volume == 2 and (match := _FOOTNOTE.fullmatch(first)):
                phase, category = "chapter-notes", "note-label"
                number = int(match.group(1))
                active_note = {"volume": 2, "number": number, "book": current_book, "chapter": current_chapter, "label": first, "label_block_id": block["id"], "block_ids": [block["id"]], "start_line": line, "end_line": block["end_line"]}
                notes[2].append(active_note)
                block["note"] = number
            elif phase == "chapter-notes" and active_note is not None:
                category = "note-body"
                block.update(note=active_note["number"], book=current_book, chapter=current_chapter)
                active_note["block_ids"].append(block["id"])
                active_note["end_line"] = block["end_line"]
            elif phase == "volume-notes":
                match = _V1_NOTE.match(str(block["text"]))
                if match is None:
                    raise ValueError(f"Independent Calvin parser found unlabeled volume-I note {block['id']}")
                number = int(match.group(1))
                category = "note-body"
                block.update(note=number, book=None, chapter=None)
                notes[1].append({"volume": 1, "number": number, "book": None, "chapter": None, "label": match.group(1), "label_block_id": block["id"], "block_ids": [block["id"]], "start_line": line, "end_line": block["end_line"]})
            elif not has_book and phase == "front":
                category = "front-matter"
                block.update(book=None, chapter=None)
                front.append(block)
            elif phase == "argument":
                category = "book-argument"
                block.update(book=current_book, chapter=None)
                arguments.append(block)
            elif phase == "body" and upper == "END OF THE INSTITUTES.":
                category = "work-end-marker"
            elif phase == "body":
                category = "chapter-body"
                body_rows.append(block)
            else:
                raise ValueError(f"Independent Calvin parser cannot disposition {block['id']} in {phase}")
            block.update(category=category, disposition=disposition)

            if not bool(block["blank"]):
                for match in _EMPHASIS.finditer(str(block["text"])):
                    emphasis_ordinal += 1
                    start_line, start_col = _source_position(block, match.start())
                    end_line, end_col = _source_position(block, match.end() - 1)
                    emphasis.append({"occurrence": emphasis_ordinal, "id": f"calvin-emphasis-{emphasis_ordinal:04d}", "volume": volume, "block_id": block["id"], "start_line": start_line, "start_column": start_col, "end_line": end_line, "end_column": end_col, "value": match.group(1), "value_sha256": _sha(match.group(1).encode())})
            anchor_category = category in ({"front-matter", "chapter-body"} if volume == 1 else {"chapter-body"})
            if anchor_category:
                pattern = re.compile(r"\((\d+)\)") if volume == 1 else re.compile(r"\[(\d+)\]")
                for match in pattern.finditer(str(block["text"])):
                    if volume == 2 and int(match.group(1)) == 1473:
                        continue
                    line_number, column = _source_position(block, match.start())
                    anchors[volume].append({"volume": volume, "occurrence": len(anchors[volume]) + 1, "number": int(match.group(1)), "label": match.group(0), "book": current_book, "chapter": current_chapter, "block_id": block["id"], "line": line_number, "column": column})

    lookup = {volume: {int(note["number"]): note for note in values} for volume, values in notes.items()}
    for anchor in anchors[1]:
        lookup[1][int(anchor["number"])]["book"] = anchor["book"]
        lookup[1][int(anchor["number"])]["chapter"] = anchor["chapter"]
    pairs = [{"volume": volume, "number": number, "anchor": next((row for row in anchors[volume] if int(row["number"]) == number), None), "note": lookup[volume][number]} for volume in (1, 2) for number in range(1, 2017 if volume == 1 else 1491)]
    return {"physical_books": books, "chapters": chapters, "front_blocks": front, "argument_blocks": arguments, "body_blocks": body_rows, "indexes": indexes, "anchors": anchors, "notes": notes, "pairs": pairs, "emphasis": emphasis}


def _project(rows: list[Mapping[str, object]], fields: tuple[str, ...]) -> list[dict[str, object]]:
    return [{key: row[key] for key in fields} for row in rows]


def _digest(value: object) -> str:
    return _sha(_canonical(value))


def _inventory_digests(model: Mapping[str, object]) -> dict[str, str]:
    book_fields = ("volume", "book", "start_line", "end_line", "heading_sha256")
    chapter_fields = ("volume", "book", "chapter", "start_line", "end_line", "heading_sha256")
    events = [
        {"kind": "volume", "volume": 1, "line": 1},
        *({"kind": "book", **row} for row in _project(model["physical_books"], book_fields)),
        *({"kind": "chapter", **row} for row in _project(model["chapters"], chapter_fields)),
        {"kind": "volume", "volume": 2, "line": 1},
    ]
    block_fields = ("id", "start_line", "end_line", "text_sha256")
    anchor_fields = ("volume", "occurrence", "number", "label", "book", "chapter", "block_id", "line", "column")
    note_fields = ("volume", "number", "label", "book", "chapter", "label_block_id", "block_ids", "start_line", "end_line")
    emphasis_fields = ("occurrence", "id", "volume", "block_id", "start_line", "start_column", "end_line", "end_column", "value", "value_sha256")
    indexes = model["indexes"]
    anchors = model["anchors"]
    notes = model["notes"]
    return {
        "structural_events_sha256": _digest(events),
        "front_blocks_sha256": _digest(_project(model["front_blocks"], block_fields)),
        "argument_blocks_sha256": _digest(_project(model["argument_blocks"], block_fields)),
        "chapter_body_blocks_sha256": _digest(_project(model["body_blocks"], block_fields)),
        "principal_index_blocks_sha256": _digest(_project(indexes["principal-matters"], block_fields)),
        "scripture_index_blocks_sha256": _digest(_project(indexes["scripture"], block_fields)),
        "anchors_sha256": _digest(_project([*anchors[1], *anchors[2]], anchor_fields)),
        "notes_sha256": _digest(_project([*notes[1], *notes[2]], note_fields)),
        "attachments_sha256": _digest(model["pairs"]),
        "emphasis_sha256": _digest(_project(model["emphasis"], emphasis_fields)),
    }


def _plain_and_inline(node: etree._Element) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    output: list[str] = []
    refs: list[dict[str, object]] = []
    emphasis: list[dict[str, object]] = []
    seen_line = False

    def walk(current: etree._Element) -> None:
        nonlocal seen_line
        local = etree.QName(current).localname
        if local == "lb":
            if seen_line:
                output.append("\n")
            seen_line = True
            return
        start = len("".join(output))
        if local == "ref":
            refs.append({"offset": start, "number": int(current.get("n", "0")), "label": "".join(current.itertext()), "target": current.get("target")})
        if current.text:
            output.append(current.text)
        for child in current:
            walk(child)
            if child.tail:
                output.append(child.tail)
        if local == "hi":
            emphasis.append({"offset": start, "id": current.get(_XML_ID), "value": "".join(output)[start:], "rend": current.get("rend"), "ana": current.get("ana")})

    walk(node)
    return "".join(output), refs, emphasis


def _element_projection(node: etree._Element) -> dict[str, object]:
    return {
        "name": etree.QName(node).localname,
        "attributes": {
            ("xml:id" if key == _XML_ID else etree.QName(key).localname): value
            for key, value in sorted(node.attrib.items())
        },
        "text": node.text or "",
        "children": [_element_projection(child) for child in node],
    }


def _expected_header(source_set_sha256: str) -> dict[str, object]:
    def element(name: str, *, text: str = "", attributes: Mapping[str, str] | None = None, children: list[dict[str, object]] | None = None) -> dict[str, object]:
        return {"name": name, "attributes": dict(attributes or {}), "text": text, "children": children or []}

    return element(
        "teiHeader",
        children=[
            element(
                "fileDesc",
                children=[
                    element(
                        "titleStmt",
                        children=[
                            element("title", text="Institutes of the Christian Religion, retained two-volume Gutenberg candidate"),
                            element("author", text="Jean Calvin (Gutenberg metadata); John Calvin (retained title pages)", attributes={"ana": "#source-name-conflict"}),
                            element(
                                "respStmt",
                                children=[
                                    element("resp", text="Translator named by both retained volumes"),
                                    element("name", text="John Allen"),
                                ],
                            ),
                        ],
                    ),
                    element(
                        "publicationStmt",
                        children=[
                            element("publisher", text="Open Christian Data"),
                            element("availability", attributes={"status": "unknown"}, children=[element("p", text=_RIGHTS_STATEMENT)]),
                        ],
                    ),
                    element(
                        "sourceDesc",
                        children=[
                            element(
                                "bibl",
                                children=[
                                    element("title", text="Institutes of the Christian Religion, Project Gutenberg volumes I and II"),
                                    element("idno", text=source_set_sha256, attributes={"type": "sha256"}),
                                    element("note", text="Exact Project Gutenberg eBook #45001 and #64392 retained bytes; wrapper, license, credits, release, and update evidence remain visible but distinct from represented work and index content."),
                                ],
                            )
                        ],
                    ),
                ],
            ),
            element(
                "encodingDesc",
                children=[element("p", text="Four logical books are represented by five physical book headings; Book III is continued across the exact volume boundary.")],
            ),
        ],
    )


def _expected_readme() -> bytes:
    return (
        "# Calvin Institutes retained-source candidate\n\n"
        "This package-only README accompanies a nonaccepted reconstruction of the exact retained Project Gutenberg text files for "
        "[volume I, eBook 45001](https://www.gutenberg.org/ebooks/45001) and "
        "[volume II, eBook 64392](https://www.gutenberg.org/ebooks/64392).\n\n"
        "The TEI distinguishes represented title matter, contents, Advertisement, translator and author prefaces, dedication, syllabus, "
        "four logical books, 80 chapters, all book arguments, both indexes, footnotes, cover-text alternative, and transcriber notes from "
        "Project Gutenberg wrapper, release/update, credit, license, and trademark evidence. The wrapper and full-license text are retained "
        "as evidence; they are not treated as authored Institutes or index content.\n\n"
        "Rights are deliberately split: the retained files state a United States public-domain basis, warn users outside the United States "
        "to check their jurisdiction, and retain Project Gutenberg redistribution and trademark conditions. Review the "
        "[Project Gutenberg License](https://www.gutenberg.org/license/) before redistribution. This package does not claim unconditional "
        "availability, worldwide public-domain status, human acceptance, or publication authorization.\n\n"
        "John Allen, both Gutenberg release/update records, and the volume-II Richard Hulse, Heather Clark, David King, Online Distributed "
        "Proofreading Team, Internet Archive, S. T. Livermore, Presbyterian Board of Publication, and University of Rochester evidence remain visible.\n"
    ).encode("utf-8")


def _expected_unresolved() -> bytes:
    records = (
        {
            "id": "calvin-author-name",
            "status": "unresolved",
            "detail": "Project Gutenberg metadata says Jean Calvin; retained title pages say John Calvin.",
        },
        {
            "id": "calvin-edition-identity",
            "status": "unresolved",
            "detail": "The title pages state Sixth American Edition, revised and corrected, Philadelphia, Presbyterian Board of Publication, 1813; this package does not normalize the claim.",
        },
        {
            "id": "calvin-scripture-index-identity",
            "status": "unresolved",
            "detail": "The appended Scripture Index identifies S. T. Livermore, the Presbyterian Board of Publication, the University of Rochester, and MDCCCLII (1852).",
        },
        {
            "id": "calvin-project-gutenberg-records",
            "status": "unresolved",
            "detail": "The two retained Gutenberg wrappers carry different release/update records and volume-II Distributed Proofreaders credits; all remain evidence, not a synthesized edition claim.",
        },
        {
            "id": "calvin-rights-jurisdiction-and-terms",
            "status": "unresolved",
            "detail": "The source asserts a United States public-domain basis, warns readers to check local law, and imposes Project Gutenberg license and trademark terms; validation is not rights clearance.",
        },
        {
            "id": "calvin-human-acceptance",
            "status": "unresolved",
            "detail": "This deterministic candidate is explicitly nonaccepted and has not received human textual, identity, or rights acceptance.",
        },
    )
    return b"".join(_canonical(record) for record in records)


def _assert_retained_rights_evidence(contents: list[bytes]) -> None:
    required = (
        "you will have to check the laws of the country where you are located before using this eBook.",
        "Nearly all the individual works in the collection are in the public domain in the United States.",
        "The Foundation makes no representations concerning the copyright status of any work in any country other than the United States.",
        "Project Gutenberg is a registered trademark",
    )
    for ordinal, content in enumerate(contents, 1):
        normalized = " ".join(content.decode("utf-8-sig").split())
        if any(phrase not in normalized for phrase in required):
            raise ValueError(f"Calvin retained volume {ordinal} rights or jurisdiction evidence mutation")


def _verify_tei(
    candidate: CandidatePackage,
    blocks: list[list[dict[str, object]]],
    model: Mapping[str, object],
    policy: Mapping[str, object],
    source_set_sha256: str,
) -> None:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
    tei = etree.fromstring(candidate.member_bytes("content.tei.xml"), parser)
    if etree.QName(tei).text != f"{{{_TEI}}}TEI" or not compiled_schema().validate(etree.ElementTree(tei)):
        raise ValueError(f"Calvin TEI P5 validation failure: {compiled_schema().error_log.last_error}")
    ns = {"tei": _TEI, "xml": "http://www.w3.org/XML/1998/namespace"}
    headers = tei.xpath("./tei:teiHeader", namespaces=ns)
    header_source_set = tei.xpath(
        "string(./tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:bibl/tei:idno[@type='sha256'])",
        namespaces=ns,
    )
    if header_source_set != source_set_sha256:
        raise ValueError("Calvin TEI source-set digest mutation")
    if tei.get(_XML_ID) != "calvins-institutes-gutenberg-two-volume-candidate" or len(headers) != 1 or _element_projection(headers[0]) != _expected_header(source_set_sha256):
        raise ValueError("Calvin exact source-derived header metadata or rights mutation")
    if policy.get("rights_statement") != _RIGHTS_STATEMENT:
        raise ValueError("Calvin validation policy invented or conflated rights certainty")
    volume_texts = tei.xpath("./tei:text/tei:group/tei:text", namespaces=ns)
    if [(node.get(_XML_ID), node.get("n")) for node in volume_texts] != [("calvin-volume-1", "1"), ("calvin-volume-2", "2")]:
        raise ValueError("Calvin exact physical-volume wrapper identity mutation")
    expected_lines = [line_id for volume_blocks in blocks for block in volume_blocks for line_id in block["line_ids"]]
    observed_lines = [str(value) for value in _TEXT_LINE_IDS(tei)]
    if observed_lines != expected_lines:
        raise ValueError("Calvin TEI physical-line omission, duplication, or reorder")
    block_nodes = {
        str(node.get(_XML_ID)): node
        for node in _TEXT_IDENTIFIED_NODES(tei)
        if str(node.get(_XML_ID)).startswith("calvin-v") and "-block-" in str(node.get(_XML_ID))
    }
    expected_refs = []
    expected_emphasis = []
    emphasis_lookup: dict[str, list[Mapping[str, object]]] = {}
    for item in model["emphasis"]:
        emphasis_lookup.setdefault(str(item["block_id"]), []).append(item)
    for volume_blocks in blocks:
        for block in volume_blocks:
            node = block_nodes.get(str(block["id"]))
            if node is None:
                raise ValueError(f"Calvin TEI block target cardinality mutation: {block['id']}")
            plain, refs, carriers = _plain_and_inline(node)
            if plain != block["text"]:
                raise ValueError(f"Calvin TEI block text or wrapped-line mutation: {block['id']}")
            ids = [str(value) for value in node.xpath(".//tei:lb/@xml:id", namespaces=ns)]
            if ids != block["line_ids"]:
                raise ValueError(f"Calvin TEI line-to-block attachment mutation: {block['id']}")
            if node.get("type") != block["category"]:
                raise ValueError(f"Calvin TEI semantic block kind mutation: {block['id']}")
            if block["category"] in {"scripture-index-entry", "scripture-index-spacing", "transcriber-note"}:
                if etree.QName(node).localname != "div":
                    raise ValueError(f"Calvin index block lost its wrapper: {block['id']}")
                children = list(node)
                if _is_scripture_index_table_block(block):
                    if len(children) != 1:
                        raise ValueError(f"Calvin Scripture-index table cardinality mutation: {block['id']}")
                    table = children[0]
                    if (
                        etree.QName(table).localname != "table"
                        or table.get("type") != "scripture-index-table"
                        or table.get("rows") != str(len(block["lines"]))
                        or table.get("cols") != "4"
                    ):
                        raise ValueError(f"Calvin Scripture-index table identity mutation: {block['id']}")
                    rows = table.xpath("./tei:row", namespaces=ns)
                    if list(table) != rows or len(rows) != len(block["line_ids"]):
                        raise ValueError(f"Calvin Scripture-index table row count or placement mutation: {block['id']}")
                    columns = (("chapter", 0, 34), ("verse", 34, 40), ("volume", 40, 44), ("page", 44, None))
                    for row, source_line, line_id in zip(rows, block["lines"], block["line_ids"], strict=True):
                        expected_line = str(int(source_line["line"]))
                        cells = row.xpath("./tei:cell", namespaces=ns)
                        if (
                            row.get("role") != "data"
                            or row.get("n") != expected_line
                            or list(row) != cells
                            or len(cells) != len(columns)
                            or [cell.get(_XML_ID) for cell in cells] != [f"{line_id}-{column[0]}" for column in columns]
                            or [cell.get("role") for cell in cells] != ["data"] * len(columns)
                        ):
                            raise ValueError(f"Calvin Scripture-index row or column identity mutation: {block['id']}")
                        raw = str(source_line["text"])
                        for ordinal, (cell, (_, start, end)) in enumerate(zip(cells, columns, strict=True)):
                            observed = "".join(cell.itertext())
                            if observed != raw[start:end]:
                                raise ValueError(f"Calvin Scripture-index column text mutation: {block['id']}")
                            lbs = cell.xpath("./tei:lb", namespaces=ns)
                            if ordinal == 0:
                                if len(lbs) != 1 or lbs[0].get(_XML_ID) != str(line_id) or lbs[0].get("n") != expected_line:
                                    raise ValueError(f"Calvin Scripture-index line attachment mutation: {block['id']}")
                            elif lbs or cell.xpath(".//tei:lb", namespaces=ns):
                                raise ValueError(f"Calvin Scripture-index column carrier mutation: {block['id']}")
                elif len(children) != 1 or etree.QName(children[0]).localname != "ab" or children[0].get("type") != f"{block['category']}-text":
                    raise ValueError(f"Calvin index text carrier cardinality or type mutation: {block['id']}")
            for ref in refs:
                prefix = plain[: int(ref["offset"])]
                line, column = _source_position(block, len(prefix))
                expected_refs.append({"volume": block["volume"], "number": ref["number"], "label": ref["label"], "block_id": block["id"], "line": line, "column": column, "target": ref["target"]})
            source_carriers = emphasis_lookup.get(str(block["id"]), [])
            if len(carriers) != len(source_carriers):
                raise ValueError(f"Calvin TEI emphasis count mutation in {block['id']}")
            for carrier, source in zip(carriers, source_carriers, strict=True):
                lines = str(block["text"]).split("\n")
                relative_line = int(source["start_line"]) - int(block["start_line"])
                opening_offset = sum(len(value) + 1 for value in lines[:relative_line]) + int(source["start_column"]) - 1
                if carrier["id"] != source["id"] or carrier["value"] != source["value"] or carrier["rend"] != "underscore" or carrier["ana"] != "#source-emphasis" or int(carrier["offset"]) != opening_offset + 1:
                    raise ValueError(f"Calvin TEI exact emphasis carrier mutation: {source['id']}")
                expected_emphasis.append(carrier)
    source_anchors = [*model["anchors"][1], *model["anchors"][2]]
    if len(expected_refs) != len(source_anchors):
        raise ValueError("Calvin TEI note-reference occurrence count mutation")
    for observed, expected in zip(expected_refs, source_anchors, strict=True):
        target = f"#calvin-v{expected['volume']}-note-{int(expected['number']):04d}"
        keys = ("volume", "number", "label", "block_id", "line", "column")
        if {key: observed[key] for key in keys} != {key: expected[key] for key in keys} or observed["target"] != target:
            raise ValueError("Calvin TEI note-reference label, target, occurrence, or attachment mutation")
    note_nodes = tei.xpath("//tei:note[starts-with(@xml:id, 'calvin-v')]", namespaces=ns)
    expected_notes = [*model["notes"][1], *model["notes"][2]]
    expected_note_ids = [f"calvin-v{int(note['volume'])}-note-{int(note['number']):04d}" for note in expected_notes]
    if [node.get(_XML_ID) for node in note_nodes] != expected_note_ids:
        raise ValueError("Calvin TEI note body omission, duplication, or reorder mutation")
    for node, expected in zip(note_nodes, expected_notes, strict=True):
        volume = int(expected["volume"])
        number = int(expected["number"])
        notes_parent = node.getparent()
        if node.get("n") != str(number) or node.get("place") != "end" or notes_parent is None or etree.QName(notes_parent).localname != "div" or notes_parent.get("type") != "notes":
            raise ValueError(f"Calvin exact note label or notes-parent mutation: volume {volume} note {number}")
        if volume == 1:
            body = notes_parent.getparent()
            volume_text = body.getparent() if body is not None else None
            if notes_parent.get("subtype") != "volume-endnotes" or body is None or etree.QName(body).localname != "body" or volume_text is None or volume_text.get(_XML_ID) != "calvin-volume-1":
                raise ValueError(f"Calvin volume-endnote ancestry mutation: note {number}")
        else:
            chapter = notes_parent.getparent()
            book = chapter.getparent() if chapter is not None else None
            body = book.getparent() if book is not None else None
            volume_text = body.getparent() if body is not None else None
            expected_chapter_id = f"calvin-v2-book-{int(expected['book'])}-chapter-{int(expected['chapter'])}"
            if (
                notes_parent.get("subtype") != "chapter-endnotes"
                or chapter is None
                or chapter.get(_XML_ID) != expected_chapter_id
                or chapter.get("n") != str(expected["chapter"])
                or book is None
                or book.get(_XML_ID) != f"calvin-book-{int(expected['book'])}-volume-2"
                or body is None
                or etree.QName(body).localname != "body"
                or volume_text is None
                or volume_text.get(_XML_ID) != "calvin-volume-2"
            ):
                raise ValueError(f"Calvin chapter-endnote ancestry mutation: note {number}")
    notes_containers = tei.xpath("//tei:div[@type='notes']", namespaces=ns)
    actual_note_container_locations = []
    for container in notes_containers:
        parent = container.getparent()
        actual_note_container_locations.append((container.get("subtype"), parent.get(_XML_ID) if parent is not None else None))
    expected_note_container_locations = [("volume-endnotes", None)]
    seen_chapters: set[tuple[int, int]] = set()
    for note in model["notes"][2]:
        location = (int(note["book"]), int(note["chapter"]))
        if location not in seen_chapters:
            seen_chapters.add(location)
            expected_note_container_locations.append(("chapter-endnotes", f"calvin-v2-book-{location[0]}-chapter-{location[1]}"))
    if actual_note_container_locations != expected_note_container_locations:
        raise ValueError("Calvin exact note-container location or cardinality mutation")
    note_1473 = tei.xpath("//*[@xml:id='calvin-v2-note-1473']", namespaces=ns)
    refs_1473 = tei.xpath("//tei:ref[@target='#calvin-v2-note-1473']", namespaces=ns)
    if len(note_1473) != 1 or refs_1473:
        raise ValueError("Calvin sole unreferenced volume-II note 1473 mutation")
    physical_books = tei.xpath("//tei:div[@type='book']", namespaces=ns)
    expected_books = []
    for source_book in model["physical_books"]:
        volume = int(source_book["volume"])
        book = int(source_book["book"])
        expected_books.append((str(book), "I" if book == 3 and volume == 1 else ("F" if book == 3 and volume == 2 else "N"), f"calvin-book-{book}-volume-{volume}", f"calvin-volume-{volume}"))
    actual_books = []
    for node in physical_books:
        body = node.getparent()
        volume_text = body.getparent() if body is not None else None
        actual_books.append((node.get("n"), node.get("part"), node.get(_XML_ID), volume_text.get(_XML_ID) if volume_text is not None else None))
    if actual_books != expected_books:
        raise ValueError("Calvin logical-book or physical-volume continuation mutation")
    milestones = tei.xpath("//tei:milestone[@unit='physical-volume']", namespaces=ns)
    milestone_locations = []
    for node in milestones:
        body = node.getparent()
        volume_text = body.getparent() if body is not None else None
        milestone_locations.append((node.get("n"), node.get(_XML_ID), volume_text.get(_XML_ID) if volume_text is not None else None, body.index(node) if body is not None else None))
    if milestone_locations != [("1", "calvin-volume-1-boundary", "calvin-volume-1", 0), ("2", "calvin-volume-2-boundary", "calvin-volume-2", 0)]:
        raise ValueError("Calvin physical-volume milestone mutation")
    chapters = tei.xpath("//tei:div[@type='chapter']", namespaces=ns)
    actual_chapters = []
    for node in chapters:
        book = node.getparent()
        body = book.getparent() if book is not None else None
        volume_text = body.getparent() if body is not None else None
        actual_chapters.append((node.get(_XML_ID), node.get("n"), book.get(_XML_ID) if book is not None else None, book.get("n") if book is not None else None, volume_text.get(_XML_ID) if volume_text is not None else None))
    expected_chapters = [
        (
            f"calvin-v{int(item['volume'])}-book-{int(item['book'])}-chapter-{int(item['chapter'])}",
            str(item["chapter"]),
            f"calvin-book-{int(item['book'])}-volume-{int(item['volume'])}",
            str(item["book"]),
            f"calvin-volume-{int(item['volume'])}",
        )
        for item in model["chapters"]
    ]
    if actual_chapters != expected_chapters:
        raise ValueError("Calvin exact chapter identity, number, book, or physical-volume ancestry mutation")
    if len(tei.xpath("//tei:div[@type='argument']/*[@type='book-argument']", namespaces=ns)) != 65:
        raise ValueError("Calvin argument ordering or attachment mutation")
    if len(tei.xpath("//tei:div[@type='index' and @subtype='principal-matters']/*[@type='principal-matters-index-heading' or @type='principal-matters-index-entry']", namespaces=ns)) != 203:
        raise ValueError("Calvin principal-matters index block mutation")
    if len(tei.xpath("//tei:div[@type='index' and @subtype='scripture']/*[@type='scripture-index-heading' or @type='scripture-index-entry' or @type='transcriber-note']", namespaces=ns)) != 838:
        raise ValueError("Calvin Scripture index block mutation")


def _module_path(root: Path, name: str) -> Path | None:
    if not name or any(part in {"", ".", ".."} for part in name.split(".")):
        return None
    stem = root.joinpath(*name.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Calvin oracle import closure escaped repository") from exc
        if resolved.is_file():
            return resolved
    return None


def _imports(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        if node.level - 1 > len(package):
            raise ValueError("Calvin oracle relative import escaped repository package")
        base = ".".join([*package[: len(package) - node.level + 1], *((node.module or "").split(".") if node.module else [])])
    return tuple([base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")])


def _repository_import_closure(root: Path, entry: Path, forbidden: tuple[str, ...]) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        path.relative_to(root)
        visited.add(path)
        relative = path.relative_to(root)
        for depth in range(1, len(relative.parts)):
            initializer = root.joinpath(*relative.parts[:depth], "__init__.py")
            if initializer.is_file() and initializer.resolve() not in visited:
                pending.append(initializer.resolve())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec"}:
                raise ValueError("Calvin oracle closure contains dynamic import or execution")
            names = tuple(alias.name for alias in node.names) if isinstance(node, ast.Import) else (_imports(path, root, node) if isinstance(node, ast.ImportFrom) else ())
            for name in names:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise ValueError(f"Calvin oracle closure contains forbidden import {name}")
                dependency = _module_path(root, name)
                if dependency is not None and dependency not in visited:
                    pending.append(dependency)
    return tuple({"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(visited, key=lambda item: item.relative_to(root).as_posix()))


def _closure_digest(root: Path, policy: Mapping[str, object], entry: Path | None = None) -> str:
    forbidden = tuple(str(item) for item in policy.get("forbidden_import_prefixes", []))
    return _digest(_repository_import_closure(root, entry or Path(__file__), forbidden))


def _runtime_paths(root: Path) -> dict[str, str]:
    module_files = {
        "oracle": __file__,
        "contract": sys.modules["ocd_kernel.reconstruction.contract"].__file__,
        "tei_validate": sys.modules["ocd_kernel.tei.validate"].__file__,
    }
    result = {}
    for name, module_file in module_files.items():
        if not isinstance(module_file, str):
            raise ValueError(f"Calvin oracle loaded {name} without a filesystem path")
        path = Path(module_file).resolve(strict=False)
        try:
            relative = path.relative_to(root.resolve(strict=True)).as_posix()
        except ValueError as exc:
            raise ValueError(f"Calvin oracle loaded {name} outside repository: {path}") from exc
        if "__editable__" in relative or "site-packages" in relative:
            raise ValueError(f"Calvin oracle loaded shadowed dependency {path}")
        if not path.is_file():
            raise ValueError(f"Calvin oracle loaded missing dependency {path}")
        result[name] = relative
    return result


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    root = source_manifest.repository_root
    expected_manifest = source_manifest.path.relative_to(root).as_posix()
    if candidate.manifest.get("status") != "nonaccepted" or candidate.manifest.get("source_manifest") != {"path": expected_manifest, "sha256": source_manifest.sha256} or candidate.manifest.get("converter") != source_manifest.record["converter"] or candidate.manifest.get("package_schema") != source_manifest.record["package_schema"]:
        raise ValueError("Calvin candidate authority binding mutation")
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict(profile_bytes, "Calvin profile", canonical=False)
    policy = _strict(policy_bytes, "Calvin validation policy", canonical=False)
    rows_by_volume = []
    blocks = []
    members = []
    source_contents = []
    for volume, name in ((1, "retained-volume-1"), (2, "retained-volume-2")):
        authority = _authority(source_manifest, name)
        content = source_manifest.authority_path(name).read_bytes()
        source_contents.append(content)
        members.append({"path": authority["path"], "bytes": len(content), "sha256": _sha(content)})
        rows = _scan_records(volume, str(authority["path"]), content)
        rows_by_volume.append(rows)
        blocks.append(_paragraphs(rows))
    all_rows = [row for rows in rows_by_volume for row in rows]
    scope = profile.get("source_scope")
    if not isinstance(scope, dict) or any(key.startswith("reviewed_") for key in profile) or any(key.startswith("reviewed_") for key in scope):
        raise ValueError("Calvin profile retains redundant reviewed digest claims")
    _assert_retained_rights_evidence(source_contents)
    if policy.get("rights_statement") != _RIGHTS_STATEMENT or profile.get("rights") != _RIGHTS:
        raise ValueError("Calvin exact retained-source rights boundary mutation")
    member_set = _digest({"contract": "ocd-calvin-two-volume-member-set-v1", "members": members})
    exact_line_inventory = [{key: row[key] for key in ("volume", "member", "line", "byte_start", "byte_end", "terminator", "record_sha256")} for row in all_rows]
    exact_lines = _digest(exact_line_inventory)
    if members != scope.get("members") or len(all_rows) != 69897 or sum(int(item["bytes"]) for item in members) != 4060187 or member_set != scope.get("derived_member_set_sha256") or exact_lines != scope.get("derived_exact_line_inventory_sha256"):
        raise ValueError("Calvin retained member, byte, line, or ordered record scope mutation")
    model = _independent_model(blocks)
    counts = {"logical_books": len({int(item["book"]) for item in model["physical_books"]}), "physical_book_headings": len(model["physical_books"]), "chapters": len(model["chapters"]), "volume_1_chapters": sum(int(item["volume"]) == 1 for item in model["chapters"]), "volume_2_chapters": sum(int(item["volume"]) == 2 for item in model["chapters"]), "front_blocks": len(model["front_blocks"]), "argument_blocks": len(model["argument_blocks"]), "chapter_body_blocks": len(model["body_blocks"]), "principal_index_lines": 33423 - 32957 + 1, "principal_index_blocks": len(model["indexes"]["principal-matters"]), "scripture_index_lines": 38372 - 33424 + 1, "scripture_index_blocks": len(model["indexes"]["scripture"]), "volume_1_anchors": len(model["anchors"][1]), "volume_1_notes": len(model["notes"][1]), "volume_2_anchors": len(model["anchors"][2]), "volume_2_notes": len(model["notes"][2]), "emphasis_carriers": len(model["emphasis"])}
    digests = _inventory_digests(model)
    if counts != profile.get("required_counts") or digests != profile.get("derived_inventory_digests"):
        raise ValueError("Calvin corrected source-derived fidelity floor or exact inventory digest mutation")
    if [int(row["number"]) for row in model["anchors"][1]] != list(range(1, 2017)) or [int(row["number"]) for row in model["anchors"][2]] != [number for number in range(1, 1491) if number != 1473]:
        raise ValueError("Calvin exact per-occurrence anchor order mutation")
    if [int(row["number"]) for row in model["notes"][1]] != list(range(1, 2017)) or [int(row["number"]) for row in model["notes"][2]] != list(range(1, 1491)):
        raise ValueError("Calvin exact note label/order mutation")

    accountability = _strict(candidate.member_bytes("source-accountability.json"), "Calvin source accountability")
    schema = _strict(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Calvin accountability schema", canonical=False)
    errors = sorted(Draft202012Validator(schema).iter_errors(accountability), key=str)
    if errors:
        raise ValueError(f"Calvin accountability schema failure: {errors[0].message}")
    expected_lines = []
    line_to_block = {
        (int(block["volume"]), line): block
        for volume_blocks in blocks
        for block in volume_blocks
        for line in range(int(block["start_line"]), int(block["end_line"]) + 1)
    }
    for row in all_rows:
        block = line_to_block[(int(row["volume"]), int(row["line"]))]
        expected_lines.append({**row, "feature_id": f"calvin-v{row['volume']}-line-{int(row['line']):05d}", "block_id": block["id"], "category": block["category"], "disposition": block["disposition"], "tei_selector": f"#calvin-v{row['volume']}-line-{int(row['line']):05d}"})
    represented = sum(row["disposition"] == "represented" for row in expected_lines)
    if accountability.get("lines") != expected_lines or accountability.get("source_members") != members or accountability.get("physical_line_count") != 69897 or accountability.get("represented_line_count") != represented or accountability.get("evidence_only_line_count") != 69897 - represented or accountability.get("omitted_line_count") != 0 or accountability.get("duplicate_line_count") != 0 or accountability.get("inventory_digests") != digests or accountability.get("note_attachments") != model["pairs"] or accountability.get("emphasis_carriers") != model["emphasis"]:
        raise ValueError("Calvin source accountability omission, duplication, disposition, or attachment mutation")
    _verify_tei(candidate, blocks, model, policy, member_set)

    provenance = _strict(candidate.member_bytes("provenance.json"), "Calvin provenance")
    expected_authorities = {str(item["name"]): {key: item[key] for key in ("path", "role", "bytes", "sha256")} for item in source_manifest.record["authorities"]}
    producer_path = root / str(source_manifest.record["converter"]["implementation_path"])
    producer_closure = _repository_import_closure(root, producer_path, tuple(str(item) for item in policy.get("producer_forbidden_import_prefixes", [])))
    if provenance.get("contract") != "ocd-calvins-institutes-candidate-provenance-v1" or provenance.get("status") != "nonaccepted" or provenance.get("authorities") != expected_authorities or provenance.get("source_member_set_sha256") != member_set or provenance.get("identity_conflicts") != profile.get("identity_conflicts") or provenance.get("rights") != profile.get("rights") or provenance.get("producer_import_closure") != list(producer_closure) or provenance.get("producer_import_closure_sha256") != _digest(producer_closure) or provenance.get("source_bytes_embedded_in_candidate") is not False:
        raise ValueError("Calvin provenance, identity, rights, or producer closure mutation")
    loaded = provenance.get("loaded_module_paths")
    if loaded != {"converter": "build/tei/calvins_institutes_reconstruction.py", "contract": "ocd_kernel/reconstruction/contract.py"}:
        raise ValueError("Calvin producer loaded-module path attestation mutation")
    _runtime_paths(root)
    closure_sha = _closure_digest(root, policy)
    if closure_sha != source_manifest.record["validator"]["import_closure_sha256"] or _sha(Path(__file__).read_bytes()) != source_manifest.record["validator"]["implementation_sha256"]:
        raise ValueError("Calvin oracle implementation or recursive import closure drifted")
    unresolved_bytes = candidate.member_bytes("unresolved.jsonl")
    if unresolved_bytes != _expected_unresolved():
        raise ValueError("Calvin exact unresolved identity/rights ledger mutation")
    if candidate.member_bytes("README.source.md") != _expected_readme():
        raise ValueError("Calvin exact package-only source attribution or terms README mutation")
    contract_members = sorted(
        ({key: item[key] for key in ("name", "path", "bytes", "sha256")} for item in source_manifest.record["authorities"] if item["role"] == "primary-source"),
        key=lambda item: (str(item["path"]), str(item["name"])),
    )
    contract_source_sha = _digest({"contract": "ocd-source-member-set-v1", "members": contract_members})
    result: dict[str, object] = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": _sha(Path(__file__).read_bytes()),
        "import_closure_sha256": closure_sha,
        "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})",
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(profile_bytes),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": contract_source_sha,
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(policy_bytes),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
