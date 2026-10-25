"""Direct two-volume Gutenberg Calvin witness to a nonaccepted TEI candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Callable, Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest


CONVERTER_ID = "ocd-calvins-institutes-two-volume-gutenberg-to-tei"
CONVERTER_VERSION = "1"
_PROFILE_ID = "calvins-institutes-complete-two-volume-source-v1"
_TEI = "http://www.tei-c.org/ns/1.0"
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_BOOK_RE = re.compile(r"^BOOK\s+([IVX]+)\.(?:\s|$)", re.IGNORECASE)
_CHAPTER_RE = re.compile(r"^CHAPTER\s+([IVXLCDM]+)\.(?:\s|$)", re.IGNORECASE)
_V1_ANCHOR_RE = re.compile(r"\((\d+)\)")
_V2_ANCHOR_RE = re.compile(r"\[(\d+)\]")
_V1_NOTE_RE = re.compile(r"^\s*(\d+)\s+")
_V2_NOTE_RE = re.compile(r"^Footnote\s+(\d+):$", re.IGNORECASE)
_EMPHASIS_RE = re.compile(r"_(.+?)_", re.DOTALL)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _strict_json(content: bytes, label: str) -> dict[str, object]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _authority(source_manifest: SourceManifest, name: str) -> Mapping[str, object]:
    matches = [item for item in source_manifest.record["authorities"] if item.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Calvin authority {name} cardinality mismatch")
    return matches[0]


def _el(name: str, attrs: Mapping[str, str] | None = None, text: str | None = None) -> etree._Element:
    node = etree.Element(f"{{{_TEI}}}{name}")
    for key, value in (attrs or {}).items():
        node.set(_XML_ID if key == "xml:id" else key, value)
    node.text = text
    return node


def _roman(value: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    result = previous = 0
    for character in reversed(value.upper()):
        current = values[character]
        result += -current if current < previous else current
        previous = max(previous, current)
    return result


def _line_records(volume: int, member: str, source: bytes) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    offset = 0
    for number, record in enumerate(source.splitlines(keepends=True), 1):
        if not record.endswith(b"\r\n"):
            raise ValueError(f"Calvin volume {volume} line {number} lost its CRLF terminator")
        payload = record[:-2]
        encoding = "utf-8-sig" if number == 1 else "utf-8"
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(f"Calvin volume {volume} line {number} is not UTF-8") from exc
        records.append(
            {
                "volume": volume,
                "member": member,
                "line": number,
                "byte_start": offset,
                "byte_end": offset + len(record),
                "terminator": "CRLF",
                "text": text,
                "text_sha256": _sha(payload),
                "record_sha256": _sha(record),
            }
        )
        offset += len(record)
    if offset != len(source):
        raise ValueError(f"Calvin volume {volume} byte accounting is not contiguous")
    return records


def _blocks(lines: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    current: list[dict[str, object]] = []
    blank: bool | None = None
    for line in lines:
        is_blank = not str(line["text"]).strip()
        if current and is_blank != blank:
            result.append(_make_block(current, bool(blank), len(result) + 1))
            current = []
        current.append(line)
        blank = is_blank
    if current:
        result.append(_make_block(current, bool(blank), len(result) + 1))
    return result


def _make_block(lines: list[dict[str, object]], blank: bool, ordinal: int) -> dict[str, object]:
    volume = int(lines[0]["volume"])
    text = "\n".join(str(item["text"]) for item in lines)
    return {
        "id": f"calvin-v{volume}-block-{ordinal:04d}",
        "volume": volume,
        "ordinal": ordinal,
        "start_line": int(lines[0]["line"]),
        "end_line": int(lines[-1]["line"]),
        "blank": blank,
        "text": text,
        "text_sha256": _sha(text.encode("utf-8")),
        "line_ids": [f"calvin-v{volume}-line-{int(item['line']):05d}" for item in lines],
        "lines": lines,
    }


def _position(block: Mapping[str, object], offset: int) -> tuple[int, int]:
    before = str(block["text"])[:offset]
    return int(block["start_line"]) + before.count("\n"), len(before.rsplit("\n", 1)[-1]) + 1


def _classify(
    volumes: list[list[dict[str, object]]],
    *,
    included_volumes: tuple[int, ...] = (1, 2),
) -> dict[str, object]:
    physical_books: list[dict[str, object]] = []
    chapters: list[dict[str, object]] = []
    front: list[dict[str, object]] = []
    arguments: list[dict[str, object]] = []
    body: list[dict[str, object]] = []
    indexes: dict[str, list[dict[str, object]]] = {"principal-matters": [], "scripture": []}
    anchors: dict[int, list[dict[str, object]]] = {1: [], 2: []}
    notes: dict[int, list[dict[str, object]]] = {1: [], 2: []}
    emphasis: list[dict[str, object]] = []
    current_note: dict[str, object] | None = None
    emphasis_number = 0
    for volume, blocks in enumerate(volumes, 1):
        state = "gutenberg-header"
        book = chapter = None
        seen_book = False
        start_line = 27 if volume == 1 else 29
        end_line = 30824 if volume == 1 else 38373
        for block in blocks:
            first = str(block["text"]).split("\n", 1)[0].strip()
            upper = first.upper()
            block["book"] = book
            block["chapter"] = chapter
            block["note"] = None
            if int(block["start_line"]) == start_line:
                block["category"] = "gutenberg-start-marker"
                block["disposition"] = "evidence-only"
                state = "front-matter"
            elif int(block["start_line"]) == end_line:
                block["category"] = "gutenberg-end-marker"
                block["disposition"] = "evidence-only"
                state = "gutenberg-license"
            elif state == "gutenberg-header":
                block["category"] = "gutenberg-header-evidence"
                block["disposition"] = "evidence-only"
            elif state == "gutenberg-license":
                block["category"] = "gutenberg-license-evidence"
                block["disposition"] = "evidence-only"
            elif bool(block["blank"]):
                block["category"] = f"{state}-spacing"
                block["disposition"] = "evidence-only" if state.startswith("gutenberg") else "represented"
            elif int(block["start_line"]) == 32957 and volume == 2:
                state = "principal-matters-index"
                block["category"] = "principal-matters-index-heading"
                block["disposition"] = "represented"
                indexes["principal-matters"].append(block)
            elif int(block["start_line"]) == 33424 and volume == 2:
                state = "scripture-index"
                block["category"] = "scripture-index-heading"
                block["disposition"] = "represented"
                indexes["scripture"].append(block)
            elif state == "principal-matters-index":
                block["category"] = "principal-matters-index-entry"
                block["disposition"] = "represented"
                indexes["principal-matters"].append(block)
            elif state == "scripture-index":
                block["category"] = "transcriber-note" if int(block["start_line"]) == 38364 else "scripture-index-entry"
                block["disposition"] = "represented"
                indexes["scripture"].append(block)
            elif match := _BOOK_RE.match(first):
                book = _roman(match.group(1))
                chapter = None
                state = "chapter-body" if volume == 2 and book == 3 else "book-argument"
                seen_book = True
                block.update(category="book-heading", disposition="represented", book=book, chapter=None)
                physical_books.append(
                    {"volume": volume, "book": book, "start_line": block["start_line"], "end_line": block["end_line"], "heading_sha256": block["text_sha256"]}
                )
            elif match := _CHAPTER_RE.match(first):
                chapter = _roman(match.group(1))
                state = "chapter-body"
                current_note = None
                block.update(category="chapter-heading", disposition="represented", book=book, chapter=chapter)
                chapters.append(
                    {"volume": volume, "book": book, "chapter": chapter, "start_line": block["start_line"], "end_line": block["end_line"], "heading_sha256": block["text_sha256"]}
                )
            elif volume == 1 and upper == "FOOTNOTES":
                state = "volume-notes"
                current_note = None
                block.update(category="notes-heading", disposition="represented", book=None, chapter=None)
            elif volume == 2 and (match := _V2_NOTE_RE.fullmatch(first)):
                state = "chapter-notes"
                number = int(match.group(1))
                current_note = {
                    "volume": 2,
                    "number": number,
                    "book": book,
                    "chapter": chapter,
                    "label": first,
                    "label_block_id": block["id"],
                    "block_ids": [block["id"]],
                    "start_line": block["start_line"],
                    "end_line": block["end_line"],
                }
                notes[2].append(current_note)
                block.update(category="note-label", disposition="represented", note=number)
            elif state == "chapter-notes" and current_note is not None:
                block.update(category="note-body", disposition="represented", note=current_note["number"], book=book, chapter=chapter)
                current_note["block_ids"].append(block["id"])
                current_note["end_line"] = block["end_line"]
            elif state == "volume-notes":
                match = _V1_NOTE_RE.match(str(block["text"]))
                if match is None:
                    raise ValueError(f"Calvin volume I note block {block['id']} has no exact label")
                number = int(match.group(1))
                block.update(category="note-body", disposition="represented", note=number, book=None, chapter=None)
                notes[1].append(
                    {
                        "volume": 1,
                        "number": number,
                        "book": None,
                        "chapter": None,
                        "label": match.group(1),
                        "label_block_id": block["id"],
                        "block_ids": [block["id"]],
                        "start_line": block["start_line"],
                        "end_line": block["end_line"],
                    }
                )
            elif not seen_book and state == "front-matter":
                block.update(category="front-matter", disposition="represented", book=None, chapter=None)
                front.append(block)
            elif state == "book-argument":
                block.update(category="book-argument", disposition="represented", book=book, chapter=None)
                arguments.append(block)
            elif state == "chapter-body" and upper == "END OF THE INSTITUTES.":
                block.update(category="work-end-marker", disposition="represented", book=book, chapter=chapter)
            elif state == "chapter-body":
                block.update(category="chapter-body", disposition="represented", book=book, chapter=chapter)
                body.append(block)
            else:
                raise ValueError(f"Calvin block {block['id']} cannot be dispositioned in state {state}")

            if not bool(block["blank"]):
                for match in _EMPHASIS_RE.finditer(str(block["text"])):
                    emphasis_number += 1
                    start_line_number, start_column = _position(block, match.start())
                    end_line_number, end_column = _position(block, match.end() - 1)
                    emphasis.append(
                        {
                            "occurrence": emphasis_number,
                            "id": f"calvin-emphasis-{emphasis_number:04d}",
                            "volume": volume,
                            "block_id": block["id"],
                            "start_line": start_line_number,
                            "start_column": start_column,
                            "end_line": end_line_number,
                            "end_column": end_column,
                            "value": match.group(1),
                            "value_sha256": _sha(match.group(1).encode("utf-8")),
                        }
                    )
            anchor_category = block.get("category") in ({"front-matter", "chapter-body"} if volume == 1 else {"chapter-body"})
            if anchor_category:
                pattern = _V1_ANCHOR_RE if volume == 1 else _V2_ANCHOR_RE
                for match in pattern.finditer(str(block["text"])):
                    if volume == 2 and int(match.group(1)) == 1473:
                        continue
                    line_number, column = _position(block, match.start())
                    anchors[volume].append(
                        {
                            "volume": volume,
                            "occurrence": len(anchors[volume]) + 1,
                            "number": int(match.group(1)),
                            "label": match.group(0),
                            "book": book,
                            "chapter": chapter,
                            "block_id": block["id"],
                            "line": line_number,
                            "column": column,
                        }
                    )

    note_by_number = {volume: {int(item["number"]): item for item in values} for volume, values in notes.items()}
    for volume in included_volumes:
        for anchor in anchors[volume]:
            note = note_by_number[volume].get(int(anchor["number"]))
            if note is None:
                raise ValueError(f"Calvin volume {volume} anchor {anchor['number']} has no note")
            if volume == 1:
                note["book"] = anchor["book"]
                note["chapter"] = anchor["chapter"]
    pairs = [
        {
            "volume": volume,
            "number": number,
            "anchor": next((item for item in anchors[volume] if int(item["number"]) == number), None),
            "note": note_by_number[volume][number],
        }
        for volume in included_volumes
        for number in range(1, 2017 if volume == 1 else 1491)
    ]
    return {
        "physical_books": physical_books,
        "chapters": chapters,
        "front_blocks": front,
        "argument_blocks": arguments,
        "body_blocks": body,
        "indexes": indexes,
        "anchors": anchors,
        "notes": notes,
        "pairs": pairs,
        "emphasis": emphasis,
    }


def _inventory(rows: list[Mapping[str, object]], fields: tuple[str, ...]) -> list[dict[str, object]]:
    return [{key: row[key] for key in fields} for row in rows]


def _digest(rows: object) -> str:
    return _sha(_canonical(rows))


def _verify_floor(model: Mapping[str, object], profile: Mapping[str, object]) -> dict[str, str]:
    physical_books = model["physical_books"]
    chapters = model["chapters"]
    front = model["front_blocks"]
    arguments = model["argument_blocks"]
    body = model["body_blocks"]
    indexes = model["indexes"]
    anchors = model["anchors"]
    notes = model["notes"]
    emphasis = model["emphasis"]
    assert isinstance(physical_books, list) and isinstance(chapters, list)
    assert isinstance(front, list) and isinstance(arguments, list) and isinstance(body, list)
    assert isinstance(indexes, dict) and isinstance(anchors, dict) and isinstance(notes, dict) and isinstance(emphasis, list)
    counts = {
        "logical_books": len({int(item["book"]) for item in physical_books}),
        "physical_book_headings": len(physical_books),
        "chapters": len(chapters),
        "volume_1_chapters": sum(int(item["volume"]) == 1 for item in chapters),
        "volume_2_chapters": sum(int(item["volume"]) == 2 for item in chapters),
        "front_blocks": len(front),
        "argument_blocks": len(arguments),
        "chapter_body_blocks": len(body),
        "principal_index_lines": 33423 - 32957 + 1,
        "principal_index_blocks": len(indexes["principal-matters"]),
        "scripture_index_lines": 38372 - 33424 + 1,
        "scripture_index_blocks": len(indexes["scripture"]),
        "volume_1_anchors": len(anchors[1]),
        "volume_1_notes": len(notes[1]),
        "volume_2_anchors": len(anchors[2]),
        "volume_2_notes": len(notes[2]),
        "emphasis_carriers": len(emphasis),
    }
    if counts != profile.get("required_counts"):
        raise ValueError(f"Calvin corrected direct-source floor drifted: {counts}")
    if [int(item["number"]) for item in anchors[1]] != list(range(1, 2017)):
        raise ValueError("Calvin volume I anchor order or label drifted")
    if [int(item["number"]) for item in notes[1]] != list(range(1, 2017)):
        raise ValueError("Calvin volume I note order or label drifted")
    if [int(item["number"]) for item in anchors[2]] != [number for number in range(1, 1491) if number != 1473]:
        raise ValueError("Calvin volume II anchor order or sole gap drifted")
    if [int(item["number"]) for item in notes[2]] != list(range(1, 1491)):
        raise ValueError("Calvin volume II note order or label drifted")
    book_fields = ("volume", "book", "start_line", "end_line", "heading_sha256")
    chapter_fields = ("volume", "book", "chapter", "start_line", "end_line", "heading_sha256")
    structural = [
        {"kind": "volume", "volume": 1, "line": 1},
        *({"kind": "book", **row} for row in _inventory(physical_books, book_fields)),
        *({"kind": "chapter", **row} for row in _inventory(chapters, chapter_fields)),
        {"kind": "volume", "volume": 2, "line": 1},
    ]
    index_fields = ("id", "start_line", "end_line", "text_sha256")
    anchor_fields = ("volume", "occurrence", "number", "label", "book", "chapter", "block_id", "line", "column")
    note_fields = ("volume", "number", "label", "book", "chapter", "label_block_id", "block_ids", "start_line", "end_line")
    emphasis_fields = ("occurrence", "id", "volume", "block_id", "start_line", "start_column", "end_line", "end_column", "value", "value_sha256")
    digests = {
        "structural_events_sha256": _digest(structural),
        "front_blocks_sha256": _digest(_inventory(front, index_fields)),
        "argument_blocks_sha256": _digest(_inventory(arguments, index_fields)),
        "chapter_body_blocks_sha256": _digest(_inventory(body, index_fields)),
        "principal_index_blocks_sha256": _digest(_inventory(indexes["principal-matters"], index_fields)),
        "scripture_index_blocks_sha256": _digest(_inventory(indexes["scripture"], index_fields)),
        "anchors_sha256": _digest(_inventory([*anchors[1], *anchors[2]], anchor_fields)),
        "notes_sha256": _digest(_inventory([*notes[1], *notes[2]], note_fields)),
        "attachments_sha256": _digest(model["pairs"]),
        "emphasis_sha256": _digest(_inventory(emphasis, emphasis_fields)),
    }
    if digests != profile.get("derived_inventory_digests"):
        raise ValueError("Calvin exact structural, attachment, index, or emphasis inventory drifted")
    return digests


def _append_text(parent: etree._Element, text: str) -> None:
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _render_source_text(node: etree._Element, block: Mapping[str, object], emphasis: list[Mapping[str, object]]) -> None:
    text = str(block["text"])
    line_starts = [0]
    for match in re.finditer("\n", text):
        line_starts.append(match.end())
    line_events = {position: line_id for position, line_id in zip(line_starts, block["line_ids"], strict=True)}
    emph_by_start: dict[int, Mapping[str, object]] = {}
    emph_by_end: dict[int, Mapping[str, object]] = {}
    for item in emphasis:
        start_line = int(item["start_line"])
        start_column = int(item["start_column"])
        end_line = int(item["end_line"])
        end_column = int(item["end_column"])
        start = line_starts[start_line - int(block["start_line"])] + start_column - 1
        end = line_starts[end_line - int(block["start_line"])] + end_column - 1
        emph_by_start[start] = item
        emph_by_end[end] = item
    anchor_pattern = _V1_ANCHOR_RE if int(block["volume"]) == 1 else _V2_ANCHOR_RE
    anchor_category = block.get("category") in ({"front-matter", "chapter-body"} if int(block["volume"]) == 1 else {"chapter-body"})
    anchor_by_start = {
        match.start(): match
        for match in anchor_pattern.finditer(text)
        if not (int(block["volume"]) == 2 and int(match.group(1)) == 1473)
    } if anchor_category else {}
    stack = [node]
    index = 0
    while index <= len(text):
        if index in line_events:
            stack[-1].append(_el("lb", {"xml:id": str(line_events[index]), "n": str(int(block["start_line"]) + line_starts.index(index))}))
        if index == len(text):
            break
        if index in emph_by_start:
            item = emph_by_start[index]
            stack[-1].append(_el("c", {"type": "emphasis-delimiter"}, "_"))
            hi = _el("hi", {"xml:id": str(item["id"]), "rend": "underscore", "ana": "#source-emphasis"})
            stack[-1].append(hi)
            stack.append(hi)
            index += 1
            continue
        if index in emph_by_end:
            if len(stack) != 2:
                raise ValueError("Calvin emphasis carrier nesting drifted")
            stack.pop()
            stack[-1].append(_el("c", {"type": "emphasis-delimiter"}, "_"))
            index += 1
            continue
        if index in anchor_by_start:
            match = anchor_by_start[index]
            number = int(match.group(1))
            stack[-1].append(
                _el(
                    "ref",
                    {"type": "note", "n": str(number), "target": f"#calvin-v{block['volume']}-note-{number:04d}"},
                    match.group(0),
                )
            )
            index = match.end()
            continue
        if text[index] == "\n":
            index += 1
            continue
        next_events = [value for value in (*line_events, *emph_by_start, *emph_by_end, *anchor_by_start) if value > index]
        stop = min(next_events) if next_events else len(text)
        newline = text.find("\n", index, stop)
        if newline >= 0:
            stop = newline
        _append_text(stack[-1], text[index:stop])
        index = stop
    if len(stack) != 1:
        raise ValueError("Calvin emphasis carrier did not close")


def _is_scripture_index_table_block(block: Mapping[str, object]) -> bool:
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


def _render_scripture_index_entry(
    parent: etree._Element,
    block: Mapping[str, object],
    emphasis: list[Mapping[str, object]],
) -> None:
    """Keep each physical Scripture-index row independently readable.

    The source classifier deliberately retains a contiguous nonblank run as
    one accounting block. This wrapper keeps that block identity while giving
    the presentation layer explicit table rows and cells for fixed-column
    source runs, and one line-preserving text carrier for non-tabular entries.
    """
    lines = block.get("lines")
    line_ids = block.get("line_ids")
    if not isinstance(lines, list) or not isinstance(line_ids, list) or len(lines) != len(line_ids):
        raise ValueError(f"Calvin Scripture-index row inventory drifted: {block['id']}")
    wrapper = _el("div", {"xml:id": str(block["id"]), "type": str(block["category"])})
    parent.append(wrapper)
    if not _is_scripture_index_table_block(block):
        node = _el("ab", {"type": f"{block['category']}-text"})
        wrapper.append(node)
        _render_source_text(node, block, emphasis)
        return
    if emphasis:
        raise ValueError(f"Calvin Scripture-index table emphasis cannot be split: {block['id']}")
    table = _el(
        "table",
        {
            "type": "scripture-index-table",
            "rows": str(len(lines)),
            "cols": "4",
        },
    )
    wrapper.append(table)
    columns = (("chapter", 0, 34), ("verse", 34, 40), ("volume", 40, 44), ("page", 44, None))
    for source_line, line_id in zip(lines, line_ids, strict=True):
        if not isinstance(source_line, Mapping):
            raise ValueError(f"Calvin Scripture-index source row is not a mapping: {block['id']}")
        line_number = int(source_line["line"])
        raw = str(source_line["text"])
        row = _el("row", {"role": "data", "n": str(line_number)})
        table.append(row)
        for ordinal, (column, start, end) in enumerate(columns):
            cell = _el("cell", {"xml:id": f"{line_id}-{column}", "role": "data"})
            row.append(cell)
            if ordinal == 0:
                cell.append(_el("lb", {"xml:id": str(line_id), "n": str(line_number)}))
                cell[-1].tail = raw[start:end]
            else:
                cell.text = raw[start:end]


def _header(policy: Mapping[str, object], source_set_sha256: str) -> etree._Element:
    header = _el("teiHeader")
    file_desc = _el("fileDesc")
    title_stmt = _el("titleStmt")
    title_stmt.append(_el("title", text="Institutes of the Christian Religion, retained two-volume Gutenberg candidate"))
    title_stmt.append(_el("author", {"ana": "#source-name-conflict"}, "Jean Calvin (Gutenberg metadata); John Calvin (retained title pages)"))
    resp = _el("respStmt")
    resp.append(_el("resp", text="Translator named by both retained volumes"))
    resp.append(_el("name", text="John Allen"))
    title_stmt.append(resp)
    file_desc.append(title_stmt)
    publication = _el("publicationStmt")
    publication.append(_el("publisher", text="Open Christian Data"))
    availability = _el("availability", {"status": "unknown"})
    availability.append(_el("p", text=str(policy["rights_statement"])))
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _el("sourceDesc")
    bibl = _el("bibl")
    bibl.append(_el("title", text="Institutes of the Christian Religion, Project Gutenberg volumes I and II"))
    bibl.append(_el("idno", {"type": "sha256"}, source_set_sha256))
    bibl.append(_el("note", text="Exact Project Gutenberg eBook #45001 and #64392 retained bytes; wrapper, license, credits, release, and update evidence remain visible but distinct from represented work and index content."))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    encoding = _el("encodingDesc")
    encoding.append(_el("p", text="Four logical books are represented by five physical book headings; Book III is continued across the exact volume boundary."))
    header.append(encoding)
    return header


def _build_tei(
    blocks_by_volume: list[list[dict[str, object]]],
    model: Mapping[str, object],
    policy: Mapping[str, object],
    source_set_sha: str,
    *,
    volume_numbers: tuple[int, ...] = (1, 2),
    header_builder: Callable[[Mapping[str, object], str], etree._Element] = _header,
    tei_xml_id: str = "calvins-institutes-gutenberg-two-volume-candidate",
) -> bytes:
    root = _el("TEI", {"xml:id": tei_xml_id})
    root.append(header_builder(policy, source_set_sha))
    text_root = _el("text")
    group = _el("group")
    text_root.append(group)
    root.append(text_root)
    emphasis_by_block: dict[str, list[Mapping[str, object]]] = {}
    for item in model["emphasis"]:
        emphasis_by_block.setdefault(str(item["block_id"]), []).append(item)
    for volume, blocks in zip(volume_numbers, blocks_by_volume, strict=True):
        volume_text = _el("text", {"xml:id": f"calvin-volume-{volume}", "n": str(volume)})
        body = _el("body")
        volume_text.append(body)
        group.append(volume_text)
        body.append(_el("milestone", {"unit": "physical-volume", "n": str(volume), "xml:id": f"calvin-volume-{volume}-boundary"}))
        wrapper_header = _el("div", {"type": "source-evidence", "subtype": "project-gutenberg-header"})
        front = _el("div", {"type": "front-matter"})
        wrapper_license = _el("div", {"type": "source-evidence", "subtype": "project-gutenberg-license"})
        body.extend((wrapper_header, front))
        current: etree._Element = wrapper_header
        current_book: etree._Element | None = None
        current_chapter: etree._Element | None = None
        current_notes: etree._Element | None = None
        index_nodes: dict[str, etree._Element] = {}
        for block in blocks:
            category = str(block["category"])
            if category == "gutenberg-start-marker":
                current = wrapper_header
            elif category == "front-matter" or category.startswith("front-matter-"):
                current = front
            elif category == "book-heading":
                book = int(block["book"])
                part = "I" if book == 3 and volume == 1 else ("F" if book == 3 and volume == 2 else "N")
                current_book = _el("div", {"type": "book", "n": str(book), "part": part, "xml:id": f"calvin-book-{book}-volume-{volume}"})
                body.append(current_book)
                current = current_book
                current_chapter = None
            elif category == "book-argument":
                if current_book is None:
                    raise ValueError("Calvin argument escaped its physical book")
                argument = next((child for child in current_book if child.get("type") == "argument"), None)
                if argument is None:
                    argument = _el("div", {"type": "argument"})
                    current_book.append(argument)
                current = argument
            elif category == "chapter-heading":
                if current_book is None:
                    raise ValueError("Calvin chapter escaped its physical book")
                current_chapter = _el("div", {"type": "chapter", "n": str(block["chapter"]), "xml:id": f"calvin-v{volume}-book-{block['book']}-chapter-{block['chapter']}"})
                current_book.append(current_chapter)
                current = current_chapter
                current_notes = None
            elif category == "notes-heading":
                current_notes = _el("div", {"type": "notes", "subtype": "volume-endnotes"})
                body.append(current_notes)
                current = current_notes
            elif category in {"note-label", "note-body"}:
                if volume == 2 and current_chapter is not None:
                    if current_notes is None or current_notes.getparent() is not current_chapter:
                        current_notes = _el("div", {"type": "notes", "subtype": "chapter-endnotes"})
                        current_chapter.append(current_notes)
                    current = current_notes
                elif current_notes is not None:
                    current = current_notes
            elif category.startswith("principal-matters-index"):
                if "principal" not in index_nodes:
                    index_nodes["principal"] = _el("div", {"type": "index", "subtype": "principal-matters", "xml:id": "calvin-index-principal-matters"})
                    body.append(index_nodes["principal"])
                current = index_nodes["principal"]
            elif category.startswith("scripture-index") or category == "transcriber-note":
                if "scripture" not in index_nodes:
                    index_nodes["scripture"] = _el("div", {"type": "index", "subtype": "scripture", "xml:id": "calvin-index-scripture"})
                    body.append(index_nodes["scripture"])
                current = index_nodes["scripture"]
            elif category == "gutenberg-end-marker" or category.startswith("gutenberg-license"):
                if wrapper_license.getparent() is None:
                    body.append(wrapper_license)
                current = wrapper_license

            if category in {"scripture-index-entry", "scripture-index-spacing", "transcriber-note"}:
                _render_scripture_index_entry(current, block, emphasis_by_block.get(str(block["id"]), []))
                continue

            if bool(block["blank"]):
                tag = "ab"
            elif category in {"book-heading", "chapter-heading", "notes-heading", "principal-matters-index-heading", "scripture-index-heading"}:
                tag = "head"
            elif category == "note-body":
                note = _el("note", {"xml:id": f"calvin-v{volume}-note-{int(block['note']):04d}", "n": str(block["note"]), "place": "end"})
                current.append(note)
                node = _el("ab", {"xml:id": str(block["id"]), "type": category})
                note.append(node)
                _render_source_text(node, block, emphasis_by_block.get(str(block["id"]), []))
                continue
            elif category in {"front-matter", "book-argument", "chapter-body"}:
                tag = "ab"
            else:
                tag = "ab"
            node = _el(tag, {"xml:id": str(block["id"]), "type": category})
            current.append(node)
            _render_source_text(node, block, emphasis_by_block.get(str(block["id"]), []))
    schema = etree.XMLSchema(etree.parse(str(Path(__file__).resolve().parents[2] / "ocd_kernel/tei/vendor/xsd/tei_all.xsd")))
    tree = etree.ElementTree(root)
    if not schema.validate(tree):
        raise ValueError(f"Calvin generated TEI P5 validation failed: {schema.error_log.last_error}")
    return etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)


def _local_module_path(root: Path, module: str) -> Path | None:
    stem = root.joinpath(*module.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("Calvin producer import closure escaped repository") from exc
        if resolved.is_file():
            return resolved
    return None


def _import_names(path: Path, root: Path, node: ast.ImportFrom) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        package = list(path.relative_to(root).parts[:-1])
        prefix = package[: len(package) - node.level + 1]
        base = ".".join([*prefix, *((node.module or "").split(".") if node.module else [])])
    return tuple([base, *(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")])


def _closure(root: Path, entry: Path) -> tuple[dict[str, str], ...]:
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        relative = path.relative_to(root)
        for depth in range(1, len(relative.parts)):
            initializer = root.joinpath(*relative.parts[:depth], "__init__.py")
            if initializer.is_file() and initializer.resolve() not in seen:
                pending.append(initializer.resolve())
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = tuple(alias.name for alias in node.names) if isinstance(node, ast.Import) else (_import_names(path, root, node) if isinstance(node, ast.ImportFrom) else ())
            for name in names:
                dependency = _local_module_path(root, name)
                if dependency is not None and dependency not in seen:
                    pending.append(dependency)
    return tuple({"path": path.relative_to(root).as_posix(), "sha256": _sha(path.read_bytes())} for path in sorted(seen, key=lambda item: item.relative_to(root).as_posix()))


def _loaded_paths(root: Path) -> dict[str, str]:
    expected = {
        "converter": Path(__file__).resolve(strict=True),
        "contract": Path(sys.modules["ocd_kernel.reconstruction.contract"].__file__).resolve(strict=True),
    }
    result = {}
    for name, path in expected.items():
        try:
            relative = path.relative_to(root.resolve(strict=True)).as_posix()
        except ValueError as exc:
            raise ValueError(f"Calvin producer loaded {name} outside repository: {path}") from exc
        if "__editable__" in relative or "site-packages" in relative:
            raise ValueError(f"Calvin producer loaded shadowed {name}: {path}")
        result[name] = relative
    return result


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _strict_json(profile_bytes, "Calvin reconstruction profile")
    policy = _strict_json(policy_bytes, "Calvin validation policy")
    if profile.get("contract") != "ocd-calvins-institutes-reconstruction-profile-v1" or profile.get("profile_id") != _PROFILE_ID:
        raise ValueError("Calvin reconstruction profile identity mismatch")
    sources = []
    blocks_by_volume = []
    line_rows = []
    observed_members = []
    for volume, name in ((1, "retained-volume-1"), (2, "retained-volume-2")):
        path = source_manifest.authority_path(name)
        content = path.read_bytes()
        sources.append(content)
        authority = _authority(source_manifest, name)
        observed_members.append({"path": authority["path"], "bytes": len(content), "sha256": _sha(content)})
        lines = _line_records(volume, str(authority["path"]), content)
        line_rows.extend(lines)
        blocks_by_volume.append(_blocks(lines))
    scope = profile.get("source_scope")
    if not isinstance(scope, dict) or observed_members != scope.get("members") or sum(len(item) for item in sources) != scope.get("bytes") or len(line_rows) != scope.get("physical_lines"):
        raise ValueError("Calvin exact two-volume retained scope drifted")
    member_set_sha = _digest({"contract": "ocd-calvin-two-volume-member-set-v1", "members": observed_members})
    exact_line_inventory = [
        {key: row[key] for key in ("volume", "member", "line", "byte_start", "byte_end", "terminator", "record_sha256")}
        for row in line_rows
    ]
    exact_line_sha = _digest(exact_line_inventory)
    if member_set_sha != scope.get("derived_member_set_sha256") or exact_line_sha != scope.get("derived_exact_line_inventory_sha256"):
        raise ValueError("Calvin member-set or exact-line inventory digest drifted")
    model = _classify(blocks_by_volume)
    digests = _verify_floor(model, profile)
    root = source_manifest.repository_root
    producer_closure = _closure(root, Path(__file__))
    producer_closure_sha = _digest(producer_closure)
    if producer_closure_sha != profile.get("producer_import_closure_sha256"):
        raise ValueError("Calvin producer recursive import closure drifted")
    loaded = _loaded_paths(root)
    tei_bytes = _build_tei(blocks_by_volume, model, policy, member_set_sha)

    block_lookup = {str(block["id"]): block for blocks in blocks_by_volume for block in blocks}
    lines_accounted = []
    line_to_block = {
        (int(block["volume"]), line): block
        for volume_blocks in blocks_by_volume
        for block in volume_blocks
        for line in range(int(block["start_line"]), int(block["end_line"]) + 1)
    }
    for row in line_rows:
        block = line_to_block[(int(row["volume"]), int(row["line"]))]
        lines_accounted.append(
            {
                **row,
                "feature_id": f"calvin-v{row['volume']}-line-{int(row['line']):05d}",
                "block_id": block["id"],
                "category": block["category"],
                "disposition": block["disposition"],
                "tei_selector": f"#calvin-v{row['volume']}-line-{int(row['line']):05d}",
            }
        )
    represented = sum(item["disposition"] == "represented" for item in lines_accounted)
    evidence = len(lines_accounted) - represented
    accountability = {
        "contract": "ocd-calvins-institutes-source-accountability-v1",
        "schema": "calvins-institutes.source-accountability.schema.json",
        "source_members": observed_members,
        "source_bytes": sum(len(item) for item in sources),
        "physical_line_count": len(lines_accounted),
        "represented_line_count": represented,
        "evidence_only_line_count": evidence,
        "omitted_line_count": 0,
        "duplicate_line_count": 0,
        "derived_member_set_sha256": member_set_sha,
        "derived_exact_line_inventory_sha256": exact_line_sha,
        "inventory_digests": digests,
        "required_counts": profile["required_counts"],
        "lines": lines_accounted,
        "structural_events": [*model["physical_books"], *model["chapters"]],
        "note_attachments": model["pairs"],
        "emphasis_carriers": model["emphasis"],
    }
    authorities = {str(item["name"]): {key: item[key] for key in ("path", "role", "bytes", "sha256")} for item in source_manifest.record["authorities"]}
    provenance = {
        "contract": "ocd-calvins-institutes-candidate-provenance-v1",
        "status": "nonaccepted",
        "authorities": authorities,
        "loaded_module_paths": loaded,
        "producer_import_closure": producer_closure,
        "producer_import_closure_sha256": producer_closure_sha,
        "source_member_set_sha256": member_set_sha,
        "identity_conflicts": profile["identity_conflicts"],
        "rights": profile["rights"],
        "source_bytes_embedded_in_candidate": False,
    }
    unresolved = [
        {"id": "calvin-author-name", "status": "unresolved", "detail": "Project Gutenberg metadata says Jean Calvin; retained title pages say John Calvin."},
        {"id": "calvin-edition-identity", "status": "unresolved", "detail": "The title pages state Sixth American Edition, revised and corrected, Philadelphia, Presbyterian Board of Publication, 1813; this package does not normalize the claim."},
        {"id": "calvin-scripture-index-identity", "status": "unresolved", "detail": "The appended Scripture Index identifies S. T. Livermore, the Presbyterian Board of Publication, the University of Rochester, and MDCCCLII (1852)."},
        {"id": "calvin-project-gutenberg-records", "status": "unresolved", "detail": "The two retained Gutenberg wrappers carry different release/update records and volume-II Distributed Proofreaders credits; all remain evidence, not a synthesized edition claim."},
        {"id": "calvin-rights-jurisdiction-and-terms", "status": "unresolved", "detail": "The source asserts a United States public-domain basis, warns readers to check local law, and imposes Project Gutenberg license and trademark terms; validation is not rights clearance."},
        {"id": "calvin-human-acceptance", "status": "unresolved", "detail": "This deterministic candidate is explicitly nonaccepted and has not received human textual, identity, or rights acceptance."},
    ]
    readme = (
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
    del block_lookup
    return {
        "content.tei.xml": tei_bytes,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()


__all__: tuple[str, ...] = ()
