"""Independent contents, hierarchy, inline and source-accounting oracle for #45283."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest
from ocd_kernel.tei.validate import compiled_schema

ORACLE_ID = "ocd-strong-pg45283-independent-structure-oracle"
ORACLE_VERSION = "9"
WORK_ID = "strong-systematic-theology-vol-3"
SOURCE_ID = "strong-systematic-theology-vol-3-pg45283-retained"
EDITION = "Revised and enlarged edition, Volume 3: The Doctrine of Salvation (Philadelphia: The Griffith & Rowland Press, 1909), Project Gutenberg #45283."
TITLE_PAGE_LINES = {
    "44": "Revised and Enlarged",
    "46": "In Three Volumes",
    "48": "Volume 3",
    "50": "The Doctrine of Salvation",
    "52": "The Griffith & Rowland Press",
    "54": "Philadelphia",
    "56": "1909",
}
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
CONTENTS_TITLE_LINE = 62
CONTENTS_FIRST_LINE = 65
CONTENTS_LAST_LINE = 234
BODY_FIRST_LINE = 267
EPIGRAPH_LINES = (250, 253, 256, 259)
END_PREFIX = "*** END OF THE PROJECT GUTENBERG EBOOK"
_SOURCE_NATIVE_MARKER = re.compile(
    r"^(?:(?P<upper>[A-Z])\.|\(_(?P<underscore>[a-z])_\)|\((?P<paren>[a-z])\))\s+"
)

def _Q(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_id(number: int) -> str:
    return f"{WORK_ID}-line-{number:05d}"


def _scan(data: bytes) -> list[tuple[int, int, int, str, bytes, str]]:
    rows = []
    offset = 0
    for number, raw in enumerate(data.splitlines(keepends=True), 1):
        if raw.endswith(b"\r\n"):
            payload, ending = raw[:-2], "CRLF"
        elif raw.endswith(b"\n"):
            payload, ending = raw[:-1], "LF"
        else:
            payload, ending = raw, "none"
        value = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        rows.append((number, offset, offset + len(raw), ending, raw, value))
        offset += len(raw)
    if offset != len(data):
        raise ValueError("independent source scan did not reach the file end")
    return rows


def _blocks(rows: list[tuple[int, int, int, str, bytes, str]]) -> list[list[tuple[int, int, int, str, bytes, str]]]:
    result = []
    current = []
    for row in rows:
        if row[5] == "":
            if current:
                result.append(current)
                current = []
        else:
            current.append(row)
    if current:
        result.append(current)
    return result


def _joined(rows: list[tuple[int, int, int, str, bytes, str]], *, trim_indent: bool = False) -> str:
    parts = [row[5].lstrip(" ") if trim_indent else row[5] for row in rows]
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _is_contents_entry(value: str) -> bool:
    text = value.lstrip(" ")
    if re.match(r"^(?:Part|Chapter)\s+[IVXLCDM]+\.", text, re.IGNORECASE):
        return True
    if re.match(r"^Section\s+[IVXLCDM]+(?:\.|[—–-])", text, re.IGNORECASE):
        return True
    if re.match(r"^(?:[IVXLCDM]+|[0-9]+|[A-Z])\.", text):
        return True
    if re.match(r"^\([a-z]\)(?:\s|[.,])", text):
        return True
    if re.match(r"^(?:First|Secondly|Thirdly|Fourthly)[,—–-]", text, re.IGNORECASE):
        return True
    return text.casefold() == "indexes." or text.casefold().startswith("index of ")


def _contents(rows: list[tuple[int, int, int, str, bytes, str]]) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    if rows[CONTENTS_TITLE_LINE - 1][5].strip() != "CONTENTS":
        raise ValueError("source contents title is not at the pinned locus")
    source_rows = rows[CONTENTS_FIRST_LINE - 1 : CONTENTS_LAST_LINE]
    if len(source_rows) != CONTENTS_LAST_LINE - CONTENTS_FIRST_LINE + 1:
        raise ValueError("source contents outline is truncated")
    roots: list[dict[str, object]] = []
    path: list[dict[str, object]] = []
    last_item: dict[str, object] | None = None
    for row in source_rows:
        line = row[5]
        indentation = len(line) - len(line.lstrip(" "))
        if not line[indentation:]:
            raise ValueError(f"unexpected blank contents record at line {row[0]}")
        if _is_contents_entry(line):
            while path and int(path[-1]["indentation"]) >= indentation:
                path.pop()
            parent = path[-1] if path else None
            if parent is None and indentation:
                raise ValueError(f"source outline has no parent at line {row[0]}")
            item: dict[str, object] = {
                "start": row[0],
                "end": row[0],
                "indentation": indentation,
                "source_rows": [row],
                "parent": parent,
                "children": [],
            }
            if parent is None:
                roots.append(item)
            else:
                parent["children"].append(item)
            path.append(item)
            last_item = item
        else:
            if last_item is None or int(last_item["indentation"]) != indentation:
                raise ValueError(f"wrapped contents line {row[0]} has no aligned entry")
            last_item["source_rows"].append(row)
            last_item["end"] = row[0]

    flat = _flatten(roots)
    inventory = [
        {
            "line": int(item["start"]),
            "end_line": int(item["end"]),
            "indent": int(item["indentation"]),
            "parent_line": int(item["parent"]["start"]) if item["parent"] is not None else None,
            "text": _joined(item["source_rows"], trim_indent=True),
        }
        for item in flat
    ]
    summary = {
        "title_line": CONTENTS_TITLE_LINE,
        "first_entry_line": CONTENTS_FIRST_LINE,
        "last_entry_line": CONTENTS_LAST_LINE,
        "entry_count": len(inventory),
        "wrapped_entry_count": sum(item["end_line"] > item["line"] for item in inventory),
        "outline_sha256": _sha(_canonical(inventory)),
    }
    return roots, flat, summary


def _flatten(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    flat = []
    for item in entries:
        flat.append(item)
        flat.extend(_flatten(item["children"]))
    return flat


def _division_role(title: str) -> tuple[str, str | None]:
    for prefix in ("Part", "Chapter", "Section"):
        found = re.match(rf"^{prefix}\s+([IVXLCDM]+)", title, re.IGNORECASE)
        if found:
            return prefix.lower(), found.group(1).upper()
    if title.casefold().startswith("indexes."):
        return "indexes", None
    found = re.match(r"^Index\s+Of\s+(.+?)\.?$", title, re.IGNORECASE)
    if found:
        return "index", found.group(1)
    found = re.match(r"^\(([a-z])\)", title)
    if found:
        return "subsection", found.group(1)
    found = re.match(
        r"^((?:[IVXLCDM]+)|(?:[0-9]+)|(?:[A-Z]+)|First|Secondly|Thirdly|Fourthly)(?=[.,—–-])",
        title,
        re.IGNORECASE,
    )
    return ("subsection", found.group(1) if found else None)


def _source_heading_marker(title: str) -> tuple[int, str] | None:
    """Return the retained source's heading level and marker."""
    if re.match(r"^Part\s+", title, re.IGNORECASE):
        return 0, "Part"
    if re.match(r"^Chapter\s+", title, re.IGNORECASE):
        return 1, "Chapter"
    if re.match(r"^Section\s+", title, re.IGNORECASE):
        return 2, "Section"
    if re.match(r"^(?:Indexes\.|Index\s+Of\b)", title, re.IGNORECASE):
        return 0, "Index"
    roman = re.match(r"^([IVXL]+)\.\s+", title)
    if roman:
        return 3, roman.group(1)
    numeric = re.match(r"^([0-9]+)\.\s+", title)
    if numeric:
        return 4, numeric.group(1)
    upper = re.match(r"^([A-Z])\.\s+", title)
    if upper:
        return 5, upper.group(1)
    parenthetical = re.match(r"^\(_([a-z])_\)\s+", title)
    if parenthetical:
        return 6, parenthetical.group(1)
    parenthetical = re.match(r"^\(([a-z])\)\s+", title)
    if parenthetical:
        return 6, parenthetical.group(1)
    if re.match(r"^(?:First|Secondly|Thirdly|Fourthly)[,—–-]", title, re.IGNORECASE):
        return 6, title.split(",", 1)[0]
    return None


def _body_map(
    rows: list[tuple[int, int, int, str, bytes, str]],
    entries: list[dict[str, object]],
    end_marker: int,
) -> tuple[dict[int, dict[str, object]], dict[str, object]]:
    body = [block for block in _blocks(rows) if BODY_FIRST_LINE <= block[0][0] < end_marker]
    labels = [_key(_joined(block)) for block in body]
    cursor = 0
    for item in entries:
        expected = _key(_joined(item["source_rows"], trim_indent=True))
        location = next(
            (index for index in range(cursor, len(body)) if labels[index] == expected),
            None,
        )
        item["body_rows"] = body[location] if location is not None else None
        if location is not None:
            cursor = location + 1

    mapped = []
    omitted = []
    by_first_line: dict[int, dict[str, object]] = {}
    for item in entries:
        body_rows = item["body_rows"]
        if body_rows is None:
            omitted.append({"toc_line": int(item["start"]), "reason": "no-exact-body-block"})
            continue
        parent = item["parent"]
        if parent is not None and parent.get("body_rows") is None:
            omitted.append(
                {
                    "toc_line": int(item["start"]),
                    "reason": "source-heading-parent-has-no-body-heading",
                }
            )
            continue
        role, number = _division_role(_joined(item["source_rows"], trim_indent=True))
        parent_rows = parent.get("body_rows") if parent is not None else None
        record = {
            "toc_line": int(item["start"]),
            "start_line": int(body_rows[0][0]),
            "end_line": int(body_rows[-1][0]),
            "type": role,
            "n": number,
            "parent_start_line": int(parent_rows[0][0]) if parent_rows is not None else None,
        }
        item["body_record"] = record
        mapped.append(record)
        by_first_line[int(body_rows[0][0])] = item
    summary = {
        "matched_heading_count": len(mapped),
        "wrapped_heading_count": sum(
            int(record["end_line"]) > int(record["start_line"])
            for record in mapped
        ),
        "unresolved_toc_entry_count": len(omitted),
        "unresolved_toc_entries": omitted,
        "heading_inventory_sha256": _sha(_canonical(mapped)),
    }
    return by_first_line, summary


def _source_native_body_outline(
    rows: list[tuple[int, int, int, str, bytes, str]],
    heading_by_start: dict[int, dict[str, object]],
) -> dict[str, object]:
    blocks = _blocks(rows)
    indexes_boundaries = [
        block[0][0]
        for block in blocks
        if _joined(block).casefold() == "indexes."
    ]
    if len(indexes_boundaries) != 1:
        raise ValueError("source INDEXES. structure boundary is missing or duplicated")
    structure_end_line = indexes_boundaries[0]
    headings = []
    stack: list[tuple[int, int]] = []
    counts = {"uppercase": 0, "underscore-parenthetical": 0, "parenthetical": 0}
    for block in blocks:
        source_line = block[0][0]
        if source_line < BODY_FIRST_LINE or source_line >= structure_end_line:
            continue
        source_text = _joined(block)
        marker = _source_heading_marker(source_text)
        matched_entry = heading_by_start.get(source_line)
        first_line = block[0][5]
        unlisted_marker = _SOURCE_NATIVE_MARKER.match(first_line)
        if matched_entry is None and unlisted_marker is None:
            continue
        if marker is None:
            raise ValueError(f"source structural block has no hierarchy level at line {source_line}")
        level, _marker = marker
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_line = stack[-1][1] if stack else None
        if matched_entry is not None:
            body_record = matched_entry.get("body_record")
            declared_parent = body_record.get("parent_start_line") if body_record else None
            if declared_parent != parent_line:
                raise ValueError(
                    f"source hierarchy disagrees with contents at line {source_line}"
                )
        else:
            if parent_line is None:
                raise ValueError(
                    f"unlisted source heading has no source-supported parent at line {source_line}"
                )
            label = (
                unlisted_marker.group("upper")
                or unlisted_marker.group("underscore")
                or unlisted_marker.group("paren")
            )
            assert label is not None
            if unlisted_marker.group("upper") is not None:
                kind = "uppercase"
            elif unlisted_marker.group("underscore") is not None:
                kind = "underscore-parenthetical"
            else:
                kind = "parenthetical"
            counts[kind] += 1
            headings.append(
                {
                    "start_line": source_line,
                    "end_line": block[-1][0],
                    "type": "subsection",
                    "n": label,
                    "parent_start_line": parent_line,
                    "matched_contents_entry": False,
                    "source_text": source_text,
                }
            )
        stack.append((level, source_line))
    return {
        "heading_count": len(headings),
        "heading_inventory_sha256": _sha(_canonical(headings)),
        "structure_start_line": BODY_FIRST_LINE,
        "structure_end_line_exclusive": structure_end_line,
        "marker_counts": counts,
        "marker_policy": [
            "^[A-Z]\\.\\s+",
            "^\\(_[a-z]_\\)\\s+",
            "^\\([a-z]\\)\\s+",
        ],
        "headings": headings,
    }


def _text_index_profile(
    rows: list[tuple[int, int, int, str, bytes, str]],
) -> dict[str, object]:
    blocks = _blocks(rows)
    named_headings: dict[str, list[int]] = {
        "index of scripture texts.": [],
        "index of apocryphal texts.": [],
        "index of greek words.": [],
    }
    for block in blocks:
        if len(block) != 1:
            continue
        title = _joined(block)
        key = _key(title)
        if key in named_headings:
            named_headings[key].append(block[0][0])
    if any(len(lines) != 1 for lines in named_headings.values()):
        raise ValueError("source text-index boundaries are missing or duplicated")

    boundaries = (
        (
            "Scripture Texts",
            named_headings["index of scripture texts."][0],
            named_headings["index of apocryphal texts."][0],
        ),
        (
            "Apocryphal Texts",
            named_headings["index of apocryphal texts."][0],
            named_headings["index of greek words."][0],
        ),
    )
    sections = []
    for title, heading_line, end_line_exclusive in boundaries:
        book_groups = [
            {"start_line": block[0][0], "label": block[0][5]}
            for block in blocks
            if heading_line < block[0][0] < end_line_exclusive
            and len(block) == 1
            and re.fullmatch(r"(?:[1-3] )?[A-Z][A-Za-z ,]+[.]", block[0][5]) is not None
        ]
        sections.append(
            {
                "title": title,
                "body_heading_line": heading_line,
                "end_line_exclusive": end_line_exclusive,
                "book_group_count": len(book_groups),
                "book_groups": book_groups,
            }
        )
    return {
        "book_group_count": sum(int(section["book_group_count"]) for section in sections),
        "sections": sections,
    }


def _end_marker(rows: list[tuple[int, int, int, str, bytes, str]]) -> int:
    found = [row[0] for row in rows if row[5].startswith(END_PREFIX)]
    if len(found) != 1:
        raise ValueError("source Gutenberg end marker is missing or duplicated")
    return found[0]


def _notes(
    source_blocks: list[list[tuple[int, int, int, str, bytes, str]]],
    heading_map: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    headings = [item["body_record"] for item in heading_map.values()]
    notes = []
    for block in source_blocks:
        if block[0][5].startswith("[Transcriber’s Note:") and block[-1][5].endswith("]"):
            preceding = [record for record in headings if int(record["start_line"]) < block[0][0]]
            nearest = max(preceding, key=lambda record: int(record["start_line"])) if preceding else None
            notes.append(
                {
                    "start_line": block[0][0],
                    "end_line": block[-1][0],
                    "type": "transcribers-note",
                    "parent_start_line": int(nearest["start_line"]) if nearest is not None else None,
                }
            )
    return notes


def _inline_profile(
    source_blocks: list[list[tuple[int, int, int, str, bytes, str]]],
) -> dict[str, object]:
    marker_blocks = 0
    marker_total = 0
    crossing = 0
    spans = []
    for block in source_blocks:
        coordinates = [
            (row[0], match.start())
            for row in block
            for match in re.finditer("_", row[5])
        ]
        if not coordinates:
            continue
        marker_blocks += 1
        marker_total += len(coordinates)
        if len(coordinates) % 2:
            raise ValueError(f"unmatched source emphasis delimiter in block starting {block[0][0]}")
        for open_at, close_at in zip(coordinates[0::2], coordinates[1::2], strict=True):
            crossing += open_at[0] != close_at[0]
            spans.append(
                {
                    "start_line": open_at[0],
                    "start_column": open_at[1],
                    "end_line": close_at[0],
                    "end_column": close_at[1],
                }
            )
    return {
        "marker": "underscore",
        "rend": "italic",
        "blank_delimited_blocks": marker_blocks,
        "marker_count": marker_total,
        "span_count": len(spans),
        "cross_physical_line_span_count": crossing,
        "span_positions_sha256": _sha(_canonical(spans)),
    }


def _expected_events(
    rows: list[tuple[int, int, int, str, bytes, str]],
    flat_contents: list[dict[str, object]],
) -> list[tuple[str, object]]:
    # A nonempty line containing only spaces is a source separator. Keep it as
    # its own expected block so the whitespace remains accounted without
    # joining the prose on either side into one paragraph.
    source_groups = []
    current = []
    for row in rows:
        if row[5] == "":
            if current:
                source_groups.append(current)
                current = []
        elif not row[5].strip():
            if current:
                source_groups.append(current)
                current = []
            source_groups.append([row])
        else:
            current.append(row)
    if current:
        source_groups.append(current)

    groups = []
    for block in source_groups:
        start = block[0][0]
        if start == CONTENTS_FIRST_LINE:
            groups.extend(item["source_rows"] for item in flat_contents)
        elif CONTENTS_FIRST_LINE <= start <= CONTENTS_LAST_LINE:
            continue
        else:
            groups.append(block)
    events: list[tuple[str, object]] = []

    def add_text(value: str) -> None:
        if value:
            if events and events[-1][0] == "text":
                events[-1] = ("text", str(events[-1][1]) + value)
            else:
                events.append(("text", value))

    for group in groups:
        events.append(("block", group[0][0]))
        emphasized = False
        for index, row in enumerate(group):
            if index:
                events.append(("lb", row[0]))
            value = row[5].lstrip(" ") if CONTENTS_FIRST_LINE <= row[0] <= CONTENTS_LAST_LINE else row[5]
            for char in value:
                if char == "_":
                    emphasized = not emphasized
                    events.append(("hi-open" if emphasized else "hi-close", None))
                else:
                    add_text(char)
        if emphasized:
            raise ValueError(f"source emphasis does not close before blank line {group[0][0]}")
    return events


def _actual_events(transcript: etree._Element) -> tuple[list[tuple[str, object]], list[str]]:
    events: list[tuple[str, object]] = []
    line_ids = []

    def add_text(value: str | None) -> None:
        if value:
            if events and events[-1][0] == "text":
                events[-1] = ("text", str(events[-1][1]) + value)
            else:
                events.append(("text", value))

    def visit(node: etree._Element) -> None:
        anchor = node.get(XML_ID)
        if anchor and anchor.startswith(f"{WORK_ID}-line-"):
            line_ids.append(anchor)
            if node.tag != _Q("lb"):
                events.append(("block", int(anchor.rsplit("-", 1)[1])))
        if node.tag == _Q("hi"):
            events.append(("hi-open", None))
        elif node.tag == _Q("lb"):
            events.append(("lb", int(node.get("n", "0"))))
        add_text(node.text)
        for child in node:
            visit(child)
            add_text(child.tail)
        if node.tag == _Q("hi"):
            events.append(("hi-close", None))

    visit(transcript)
    return events, line_ids


def _line_number(node: etree._Element) -> int:
    anchor = node.get(XML_ID, "")
    if not anchor.startswith(f"{WORK_ID}-line-"):
        raise ValueError("source line xml:id is missing")
    return int(anchor.rsplit("-", 1)[1])


def _text_with_line_breaks(node: etree._Element) -> str:
    parts: list[str] = []

    def visit(current: etree._Element) -> None:
        if current.text:
            parts.append(current.text)
        for child in current:
            if child.tag == _Q("lb"):
                parts.append(" ")
            else:
                visit(child)
            if child.tail:
                parts.append(child.tail)

    visit(node)
    return "".join(parts)


def _actual_contents(list_node: etree._Element) -> list[dict[str, int | None]]:
    result: list[dict[str, int | None]] = []

    def descend(list_element: etree._Element, parent_line: int | None) -> None:
        for item in list_element.findall(_Q("item")):
            paragraphs = item.findall(_Q("p"))
            if len(paragraphs) != 1:
                raise ValueError("contents item must contain exactly one paragraph")
            paragraph = paragraphs[0]
            start = _line_number(paragraph)
            end = max([start, *[int(lb.get("n", "0")) for lb in paragraph.iter(_Q("lb"))]])
            result.append({"line": start, "end_line": end, "parent_line": parent_line})
            child_list = item.find(_Q("list"))
            if child_list is not None:
                descend(child_list, start)

    descend(list_node, None)
    return result


def _parent_heading(div: etree._Element) -> int | None:
    if div.get("type") == "retained-file-transcription":
        return None
    head = div.find(_Q("head"))
    return _line_number(head) if head is not None else None


def _actual_headings(document: etree._Element) -> list[dict[str, object]]:
    result = []
    selected = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']//tei:div/tei:head",
        namespaces={"tei": TEI},
    )
    for head in selected:
        division = head.getparent()
        if division.get("type") == "contents":
            continue
        start = _line_number(head)
        ends = [int(lb.get("n", "0")) for lb in head.iter(_Q("lb"))]
        result.append(
            {
                "start_line": start,
                "end_line": max([start, *ends]),
                "type": division.get("type"),
                "n": division.get("n"),
                "parent_start_line": _parent_heading(division.getparent()),
            }
        )
    return result


def _actual_notes(document: etree._Element) -> list[dict[str, object]]:
    result = []
    for note in document.xpath(".//tei:note[@type='transcribers-note']", namespaces={"tei": TEI}):
        start = _line_number(note)
        ends = [int(lb.get("n", "0")) for lb in note.iter(_Q("lb"))]
        result.append(
            {
                "start_line": start,
                "end_line": max([start, *ends]),
                "type": "transcribers-note",
                "parent_start_line": _parent_heading(note.getparent()),
            }
        )
    return result


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> Mapping[str, object]:
    source_manifest.verify()
    if source_manifest.record.get("source_id") != SOURCE_ID:
        raise ValueError("Strong Vol. 3 oracle source identity mismatch")
    source = source_manifest.authority_path("retained-source").read_bytes()
    if len(source) != 1_868_543 or _sha(source) != "103dc623072326111214078015dfbe8cb8f97197cba6e5e6faffede8bb1a20fe":
        raise ValueError("oracle exact Gutenberg witness mismatch")
    rows = _scan(source)
    blocks = _blocks(rows)
    _roots, outline, contents_profile = _contents(rows)
    end_line = _end_marker(rows)
    heading_map, body_profile = _body_map(rows, outline, end_line)
    source_native_body_outline = _source_native_body_outline(rows, heading_map)
    text_index_profile = _text_index_profile(rows)
    note_profile = _notes(blocks, heading_map)
    inline_profile = _inline_profile(blocks)

    edition_evidence = {
        "original_publication_year": None,
        "source_edition": EDITION,
        "title_page_lines": TITLE_PAGE_LINES,
    }
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    source_config = json.loads(source_manifest.authority_path("source-config").read_bytes())
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
    if profile.get("edition_evidence") != edition_evidence or source_config.get("source_edition") != EDITION or source_config.get("original_publication_year") is not None:
        raise ValueError("source config or profile has a conflicting volume-specific edition")
    if any(rows[int(line) - 1][5].strip() != text for line, text in TITLE_PAGE_LINES.items()):
        raise ValueError("retained title page does not support the configured Volume 3 imprint")
    required_checks = {
        "volume-specific-edition-imprint-and-original-publication-date-separation",
        "source-indented-contents-hierarchy-and-wrapped-entry-accounting",
        "contents-derived-body-heading-hierarchy-and-wrapped-heading-accounting",
        "source-native-body-heading-hierarchy",
        "explicit-transcriber-notes-and-cover-art-placeholder",
        "balanced-underscore-emphasis-across-physical-lines",
        "four-source-quoted-mottos-are-mapped-as-epigraphs",
        "citation-and-page-reference-semantics-remain-uninferred",
        "neutral-source-sequence-containers-preserve-unheaded-groups",
        "scripture-index-book-headings-group-related-reference-entries",
        "scripture-and-apocryphal-index-book-headings-group-related-reference-entries",
    }
    if not required_checks.issubset(set(policy.get("required_checks", []))):
        raise ValueError("validation policy omits a source-structure or inline check")
    if profile.get("contents_outline") != contents_profile:
        raise ValueError("source-derived contents outline differs from the reconstruction profile")
    if profile.get("body_outline") != body_profile:
        raise ValueError("source-derived body-heading inventory differs from the reconstruction profile")
    if profile.get("source_native_body_outline") != source_native_body_outline:
        raise ValueError("source-derived unlisted body headings differ from the reconstruction profile")
    if profile.get("text_index_groups") != text_index_profile:
        raise ValueError("source-derived index headings differ from the reconstruction profile")
    if profile.get("note_blocks") != note_profile:
        raise ValueError("source-derived transcriber-note inventory differs from the reconstruction profile")
    if profile.get("inline_emphasis") != inline_profile:
        raise ValueError("source-derived underscore-emphasis inventory differs from the reconstruction profile")
    expected_inventory = [
        {
            "line": number,
            "start": start,
            "end": end,
            "ending": ending,
            "sha256": _sha(raw),
        }
        for number, start, end, ending, raw, _value in rows
    ]
    if profile.get("source_scope") != {
        "bytes": len(source),
        "physical_lines": len(rows),
        "source_inventory_sha256": _sha(_canonical(expected_inventory)),
    }:
        raise ValueError("source physical-line census differs from the reconstruction profile")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("attribution-readme").read_bytes():
        raise ValueError("candidate attribution README differs from its pinned authority")

    document = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    if not compiled_schema().validate(etree.ElementTree(document)):
        raise ValueError(f"TEI P5 invalid: {compiled_schema().error_log.last_error}")
    if document.xpath("string(//tei:idno[@type='work-id'])", namespaces={"tei": TEI}) != WORK_ID:
        raise ValueError("TEI work identity mismatch")
    if document.xpath("string(//tei:idno[@type='edition'])", namespaces={"tei": TEI}) != EDITION:
        raise ValueError("candidate volume-specific edition metadata mismatch")
    if document.xpath("./tei:teiHeader//tei:date", namespaces={"tei": TEI}):
        raise ValueError("candidate must not infer an original-publication year")
    transcript_nodes = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']",
        namespaces={"tei": TEI},
    )
    if len(transcript_nodes) != 1:
        raise ValueError("candidate must contain one complete retained-file transcription")
    transcript = transcript_nodes[0]

    expected_epigraphs = [block for block in _blocks(rows) if block[0][0] in EPIGRAPH_LINES]
    actual_epigraphs = transcript.xpath(
        "./tei:div[@type='source-outline-body']/tei:quote[@type='epigraph']",
        namespaces={"tei": TEI},
    )
    if (
        [block[0][0] for block in expected_epigraphs] != list(EPIGRAPH_LINES)
        or [_line_number(node) for node in actual_epigraphs] != list(EPIGRAPH_LINES)
        or any(
            _key(_text_with_line_breaks(node)) != _key(_joined(block).replace("_", ""))
            for node, block in zip(actual_epigraphs, expected_epigraphs, strict=True)
        )
    ):
        raise ValueError("source epigraph quotation structure or text differs from witness")

    actual_line_ids = [
        node.get(XML_ID)
        for node in transcript.iter()
        if node.get(XML_ID, "").startswith(f"{WORK_ID}-line-")
    ]
    expected_line_ids = [
        _line_id(number)
        for number, _start, _end, _ending, _raw, value in rows
        if value
    ]
    if actual_line_ids != expected_line_ids:
        raise ValueError("source physical-line anchors are omitted, duplicated, or reordered")
    accountability = json.loads(candidate.member_bytes("source-accountability.json"))
    expected_accounting = [
        {
            "line": number,
            "byte_start": start,
            "byte_end": end,
            "terminator": ending,
            "record_sha256": _sha(raw),
            "disposition": "represented" if value else "separator",
            "tei_selector": f"#{_line_id(number)}" if value else None,
        }
        for number, start, end, ending, raw, value in rows
    ]
    if accountability.get("work_id") != WORK_ID or accountability.get("lines") != expected_accounting:
        raise ValueError("independent physical-line and byte accounting mismatch")
    if accountability.get("source_member") != {
        "path": "raw/gutenberg/pg45283.txt",
        "bytes": len(source),
        "sha256": _sha(source),
    }:
        raise ValueError("source accountability binding mismatch")
    if accountability.get("physical_line_count") != len(rows):
        raise ValueError("source accountability line count mismatch")
    if accountability.get("nonblank_line_count") != len(expected_line_ids):
        raise ValueError("source accountability nonblank line count mismatch")

    contents_divs = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']/tei:div[@type='contents']",
        namespaces={"tei": TEI},
    )
    contents_lists = document.xpath(
        "./tei:text/tei:body/tei:div[@type='retained-file-transcription']/tei:div[@type='contents']/tei:list",
        namespaces={"tei": TEI},
    )
    if len(contents_divs) != 1 or len(contents_lists) != 1:
        raise ValueError("candidate contents outline is missing or duplicated")
    contents_head = contents_divs[0].find(_Q("head"))
    if contents_head is None or _line_number(contents_head) != CONTENTS_TITLE_LINE:
        raise ValueError("candidate contents title is not source-anchored")
    expected_outline = [
        {
            "line": int(item["start"]),
            "end_line": int(item["end"]),
            "parent_line": int(item["parent"]["start"]) if item["parent"] is not None else None,
        }
        for item in outline
    ]
    if _actual_contents(contents_lists[0]) != expected_outline:
        raise ValueError("candidate contents nesting or wrapped-entry grouping differs from source indentation")

    source_containers = transcript.xpath("./tei:div[@type='source-outline-body']", namespaces={"tei": TEI})
    if len(source_containers) != 1 or transcript.index(contents_divs[0]) >= transcript.index(source_containers[0]):
        raise ValueError("neutral source-outline sequence container is missing or out of source order")
    tail_containers = source_containers[0].xpath("./tei:div[@type='source-envelope-tail']", namespaces={"tei": TEI})
    outline_line_ids = [
        node.get(XML_ID)
        for node in source_containers[0].iter()
        if node.get(XML_ID, "").startswith(f"{WORK_ID}-line-")
    ]
    tail_line_ids = [
        node.get(XML_ID)
        for node in tail_containers[0].iter()
        if node.get(XML_ID, "").startswith(f"{WORK_ID}-line-")
    ] if len(tail_containers) == 1 else []
    if (
        not outline_line_ids
        or int(outline_line_ids[0].rsplit("-", 1)[1]) != 241
        or len(tail_containers) != 1
        or not tail_line_ids
        or int(tail_line_ids[0].rsplit("-", 1)[1]) != end_line
    ):
        raise ValueError("neutral source-sequence containers do not preserve the observed boundaries")

    expected_headings = [
        {
            key: item["body_record"][key]
            for key in ("start_line", "end_line", "type", "n", "parent_start_line")
        }
        for item in outline
        if item.get("body_record") is not None
        and (item["parent"] is None or item["parent"].get("body_record") is not None)
    ]
    expected_by_start = {
        int(item["start_line"]): item
        for item in expected_headings
    }
    for source_heading in source_native_body_outline["headings"]:
        expected = {
            key: source_heading[key]
            for key in ("start_line", "end_line", "type", "n", "parent_start_line")
        }
        start_line = int(expected["start_line"])
        contents_heading = expected_by_start.get(start_line)
        if contents_heading is not None and contents_heading != expected:
            raise ValueError(
                f"contents and source-native heading hierarchies disagree at line {start_line}"
            )
        expected_by_start[start_line] = expected
    expected_headings = list(expected_by_start.values())
    for section in text_index_profile["sections"]:
        expected_headings.extend(
            {
                "start_line": int(item["start_line"]),
                "end_line": int(item["start_line"]),
                "type": "index-group",
                "n": str(item["label"]).rstrip("."),
                "parent_start_line": int(section["body_heading_line"]),
            }
            for item in section["book_groups"]
        )
    expected_headings.sort(key=lambda item: int(item["start_line"]))
    if _actual_headings(document) != expected_headings:
        raise ValueError("candidate body-heading hierarchy or wrapped-heading grouping differs from source")
    for section in text_index_profile["sections"]:
        index_nodes = transcript.xpath(
            ".//tei:div[@type='index'][@n=$title]",
            namespaces={"tei": TEI},
            title=str(section["title"]),
        )
        if len(index_nodes) != 1:
            raise ValueError(f"candidate {section['title']} index is missing or duplicated")
        actual_groups = index_nodes[0].xpath(
            "./tei:div[@type='index-group']",
            namespaces={"tei": TEI},
        )
        group_specs = section["book_groups"]
        if len(actual_groups) != int(section["book_group_count"]):
            raise ValueError(f"candidate {section['title']} book groups differ from source headings")
        for index, (group, spec) in enumerate(zip(actual_groups, group_specs, strict=True)):
            start_line = int(spec["start_line"])
            next_start = (
                int(group_specs[index + 1]["start_line"])
                if index + 1 < len(group_specs)
                else int(section["end_line_exclusive"])
            )
            expected_group_ids = [
                _line_id(number)
                for number, _start, _end, _ending, _raw, value in rows
                if start_line <= number < next_start and value
            ]
            actual_group_ids = [
                node.get(XML_ID)
                for node in group.iter()
                if node.get(XML_ID, "").startswith(f"{WORK_ID}-line-")
            ]
            if actual_group_ids != expected_group_ids:
                raise ValueError(
                    f"candidate {section['title']} entries are grouped under the wrong book"
                )
    if _actual_notes(document) != note_profile:
        raise ValueError("candidate transcriber-note structure or attachment differs from source")
    placeholders = document.xpath(".//tei:ab[@type='source-figure-placeholder']", namespaces={"tei": TEI})
    if (
        len(placeholders) != 1
        or _line_number(placeholders[0]) != 241
        or "".join(placeholders[0].itertext()).strip() != "[Cover Art]"
        or profile.get("figure_placeholder_line") != 241
        or document.xpath(".//tei:graphic", namespaces={"tei": TEI})
    ):
        raise ValueError("source cover-art placeholder was omitted or recast as an image")

    actual_emphasis = document.xpath(".//tei:hi", namespaces={"tei": TEI})
    if len(actual_emphasis) != int(inline_profile["span_count"]) or any(
        node.get("rend") != "italic" for node in actual_emphasis
    ):
        raise ValueError("candidate underscore emphasis span count or rendition differs from source")
    cross_line_emphasis = sum(
        bool(node.xpath(".//tei:lb", namespaces={"tei": TEI}))
        for node in actual_emphasis
    )
    if cross_line_emphasis != int(inline_profile["cross_physical_line_span_count"]):
        raise ValueError("candidate cross-line underscore emphasis differs from source")

    expected_events = _expected_events(rows, outline)
    actual_events, _ids = _actual_events(transcript)
    if actual_events != expected_events:
        raise ValueError("readable source lines, physical wraps, or underscore emphasis differ from source")
    if candidate.manifest.get("status") != "nonaccepted":
        raise ValueError("candidate is not nonaccepted")
    unresolved = [
        json.loads(line)
        for line in candidate.member_bytes("unresolved.jsonl").decode("utf-8").splitlines()
    ]
    required_unresolved = {
        f"{WORK_ID}-original-publication-year",
        f"{WORK_ID}-rights",
        f"{WORK_ID}-human-acceptance",
        f"{WORK_ID}-publication",
        f"{WORK_ID}-structure",
        f"{WORK_ID}-note-semantics",
    }
    if {item.get("id") for item in unresolved} != required_unresolved:
        raise ValueError("unresolved issue inventory mismatch")
    oracle_path = Path(__file__).resolve()
    implementation_sha = _sha(oracle_path.read_bytes())
    closure_sha = _sha(
        _canonical(
            [
                {
                    "path": oracle_path.relative_to(source_manifest.repository_root).as_posix(),
                    "sha256": implementation_sha,
                }
            ]
        )
    )
    runtime = f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"
    result = {
        "status": "pass",
        "oracle_id": ORACLE_ID,
        "oracle_version": ORACLE_VERSION,
        "implementation_sha256": implementation_sha,
        "import_closure_sha256": closure_sha,
        "runtime": runtime,
        "source_manifest_sha256": source_manifest.sha256,
        "candidate_sha256": candidate.sha256,
        "profile_sha256": _sha(source_manifest.authority_path("reconstruction-profile").read_bytes()),
        "package_schema_sha256": _sha(source_manifest.authority_path("candidate-package-schema").read_bytes()),
        "source_sha256": _sha(source),
        "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()),
        "policy_sha256": _sha(source_manifest.authority_path("validation-policy").read_bytes()),
        "findings": [],
    }
    result["result_sha256"] = _sha(_canonical(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
