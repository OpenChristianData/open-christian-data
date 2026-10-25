"""Source-bound, structure-aware reconstruction of Gutenberg #45283, volume 3."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import sys
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest

CONVERTER_ID = "ocd-strong-pg45283-volume-3-structured-transcription"
CONVERTER_VERSION = "9"
WORK_ID = "strong-systematic-theology-vol-3"
SOURCE_ID = "strong-systematic-theology-vol-3-pg45283-retained"
SOURCE_PATH = "raw/gutenberg/pg45283.txt"
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
EDITION_EVIDENCE = {
    "original_publication_year": None,
    "source_edition": EDITION,
    "title_page_lines": TITLE_PAGE_LINES,
}
TEI = "http://www.tei-c.org/ns/1.0"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
PROFILE_PATH = "sources/strong-systematic-theology-vol-3/strong-systematic-theology-vol-3.reconstruction-profile.json"
POLICY_PATH = "sources/strong-systematic-theology-vol-3/strong-systematic-theology-vol-3.validation-policy.json"
README_PATH = "sources/strong-systematic-theology-vol-3/README.source.md"
CONTENTS_TITLE_LINE = 62
CONTENTS_FIRST_ENTRY_LINE = 65
CONTENTS_LAST_ENTRY_LINE = 234
BODY_FIRST_LINE = 267
EPIGRAPH_LINES = (250, 253, 256, 259)
GUTENBERG_END_PREFIX = "*** END OF THE PROJECT GUTENBERG EBOOK"

_TOC_LEADER = re.compile(
    r"^(?:"
    r"Part\s+[IVXLCDM]+\."
    r"|Chapter\s+[IVXLCDM]+\."
    r"|Section\s+[IVXLCDM]+(?:\.|[—–-])"
    r"|[IVXLCDM]+\."
    r"|[0-9]+\."
    r"|[A-Z]\."
    r"|\([a-z]\)"
    r"|(?:First|Secondly|Thirdly|Fourthly)[,—–-]"
    r"|Indexes\."
    r"|Index\s+Of\b"
    r")",
    re.IGNORECASE,
)

_SOURCE_NATIVE_MARKER = re.compile(
    r"^(?:(?P<upper>[A-Z])\.|\(_(?P<underscore>[a-z])_\)|\((?P<paren>[a-z])\))\s+"
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_id(number: int) -> str:
    return f"{WORK_ID}-line-{number:05d}"


def _records(source: bytes) -> list[dict[str, object]]:
    result = []
    offset = 0
    for number, raw in enumerate(source.splitlines(keepends=True), 1):
        if raw.endswith(b"\r\n"):
            payload, ending = raw[:-2], "CRLF"
        elif raw.endswith(b"\n"):
            payload, ending = raw[:-1], "LF"
        else:
            payload, ending = raw, "none"
        result.append(
            {
                "line": number,
                "start": offset,
                "end": offset + len(raw),
                "ending": ending,
                "text": payload.decode("utf-8-sig" if number == 1 else "utf-8"),
                "sha256": _sha(raw),
            }
        )
        offset += len(raw)
    if offset != len(source):
        raise ValueError("Strong Vol. 3 source byte accounting is not contiguous")
    return result


def _line_blocks(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    blocks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for row in rows:
        if row["text"] == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks


def _render_blocks(rows: list[dict[str, object]]) -> list[list[dict[str, object]]]:
    """Keep whitespace-only source lines as explicit separators, not paragraph content."""
    blocks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    for row in rows:
        value = str(row["text"])
        if value == "":
            if current:
                blocks.append(current)
                current = []
        elif not value.strip():
            if current:
                blocks.append(current)
                current = []
            blocks.append([row])
        else:
            current.append(row)
    if current:
        blocks.append(current)
    return blocks


def _line_text(rows: list[dict[str, object]], *, strip_indent: bool = False) -> str:
    parts = []
    for row in rows:
        value = str(row["text"])
        parts.append(value.lstrip(" ") if strip_indent else value)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _normalized_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _toc_entry_leader(value: str) -> bool:
    return _TOC_LEADER.match(value) is not None


def _parse_contents(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    if str(rows[CONTENTS_TITLE_LINE - 1]["text"]).strip() != "CONTENTS":
        raise ValueError("Strong Vol. 3 contents title moved")
    title_rows = rows[CONTENTS_FIRST_ENTRY_LINE - 1 : CONTENTS_LAST_ENTRY_LINE]
    if len(title_rows) != CONTENTS_LAST_ENTRY_LINE - CONTENTS_FIRST_ENTRY_LINE + 1:
        raise ValueError("Strong Vol. 3 printed contents range is incomplete")

    roots: list[dict[str, object]] = []
    stack: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    for row in title_rows:
        value = str(row["text"])
        indent = len(value) - len(value.lstrip(" "))
        content = value[indent:]
        if not content:
            raise ValueError(f"empty contents line {row['line']} is not an outline entry")
        if _toc_entry_leader(content):
            while stack and int(stack[-1]["indent"]) >= indent:
                stack.pop()
            parent = stack[-1] if stack else None
            if parent is None and indent != 0:
                raise ValueError(f"contents line {row['line']} has no source-indicated parent")
            entry: dict[str, object] = {
                "start_line": int(row["line"]),
                "end_line": int(row["line"]),
                "indent": indent,
                "lines": [row],
                "parent": parent,
                "children": [],
            }
            if parent is None:
                roots.append(entry)
            else:
                children = parent["children"]
                assert isinstance(children, list)
                children.append(entry)
            stack.append(entry)
            previous = entry
        else:
            if previous is None or int(previous["indent"]) != indent:
                raise ValueError(
                    f"contents continuation at line {row['line']} is not aligned with its entry"
                )
            lines = previous["lines"]
            assert isinstance(lines, list)
            lines.append(row)
            previous["end_line"] = int(row["line"])

    if int(title_rows[-1]["line"]) != CONTENTS_LAST_ENTRY_LINE:
        raise ValueError("Strong Vol. 3 printed contents endpoint drifted")
    flattened = _flatten_contents(roots)
    records = [
        {
            "line": int(entry["start_line"]),
            "end_line": int(entry["end_line"]),
            "indent": int(entry["indent"]),
            "parent_line": (
                int(entry["parent"]["start_line"])
                if entry["parent"] is not None
                else None
            ),
            "text": _line_text(entry["lines"], strip_indent=True),
        }
        for entry in flattened
    ]
    summary = {
        "title_line": CONTENTS_TITLE_LINE,
        "first_entry_line": CONTENTS_FIRST_ENTRY_LINE,
        "last_entry_line": CONTENTS_LAST_ENTRY_LINE,
        "entry_count": len(records),
        "wrapped_entry_count": sum(record["end_line"] > record["line"] for record in records),
        "outline_sha256": _sha(_canonical(records)),
    }
    return roots, flattened, summary


def _flatten_contents(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for entry in entries:
        result.append(entry)
        children = entry["children"]
        assert isinstance(children, list)
        result.extend(_flatten_contents(children))
    return result


def _entry_kind(title: str) -> tuple[str, str | None]:
    match = re.match(r"^(Part|Chapter|Section)\s+([IVXLCDM]+)", title, re.IGNORECASE)
    if match:
        return match.group(1).lower(), match.group(2).upper()
    if re.match(r"^Indexes\.", title, re.IGNORECASE):
        return "indexes", None
    index_match = re.match(r"^Index\s+Of\s+(.+?)\.?$", title, re.IGNORECASE)
    if index_match:
        return "index", index_match.group(1)
    parenthetical = re.match(r"^\(([a-z])\)", title, re.IGNORECASE)
    if parenthetical:
        return "subsection", parenthetical.group(1)
    marker = re.match(
        r"^(?:\((?P<paren>[a-z])\)|(?P<label>[IVXLCDM]+|[0-9]+|[A-Z]+|First|Secondly|Thirdly|Fourthly))"
        r"(?=[.,—–-])",
        title,
        re.IGNORECASE,
    )
    if marker:
        return "subsection", marker.group("paren") or marker.group("label")
    return "subsection", None


def _source_heading_marker(title: str) -> tuple[int, str] | None:
    """Return the source-visible hierarchy level and marker for a heading block."""
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


def _body_heading_profile(
    rows: list[dict[str, object]],
    flat_contents: list[dict[str, object]],
    end_marker_line: int,
) -> tuple[dict[int, dict[str, object]], dict[str, object]]:
    blocks = _line_blocks(rows)
    body_blocks = [
        block
        for block in blocks
        if BODY_FIRST_LINE <= int(block[0]["line"]) < end_marker_line
    ]
    body_titles = [_normalized_title(_line_text(block)) for block in body_blocks]
    cursor = 0
    for entry in flat_contents:
        title = _normalized_title(_line_text(entry["lines"], strip_indent=True))
        found = None
        for index in range(cursor, len(body_blocks)):
            if body_titles[index] == title:
                found = index
                break
        entry["body_block"] = body_blocks[found] if found is not None else None
        if found is not None:
            cursor = found + 1

    materialized: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    heading_by_start: dict[int, dict[str, object]] = {}
    for entry in flat_contents:
        block = entry["body_block"]
        if block is None:
            gaps.append({"toc_line": int(entry["start_line"]), "reason": "no-exact-body-block"})
            continue
        parent = entry["parent"]
        if parent is not None and parent.get("body_block") is None:
            gaps.append(
                {
                    "toc_line": int(entry["start_line"]),
                    "reason": "source-heading-parent-has-no-body-heading",
                }
            )
            continue
        kind, number = _entry_kind(_line_text(entry["lines"], strip_indent=True))
        parent_block = parent.get("body_block") if parent is not None else None
        parent_line = int(parent_block[0]["line"]) if parent_block is not None else None
        record = {
            "toc_line": int(entry["start_line"]),
            "start_line": int(block[0]["line"]),
            "end_line": int(block[-1]["line"]),
            "type": kind,
            "n": number,
            "parent_start_line": parent_line,
        }
        entry["body_record"] = record
        materialized.append(record)
        heading_by_start[int(block[0]["line"])] = entry

    summary = {
        "matched_heading_count": len(materialized),
        "wrapped_heading_count": sum(
            int(record["end_line"]) > int(record["start_line"])
            for record in materialized
        ),
        "unresolved_toc_entry_count": len(gaps),
        "unresolved_toc_entries": gaps,
        "heading_inventory_sha256": _sha(_canonical(materialized)),
    }
    return heading_by_start, summary


def _source_native_body_outline(
    rows: list[dict[str, object]],
    heading_by_start: dict[int, dict[str, object]],
) -> dict[str, object]:
    blocks = _line_blocks(rows)
    indexes_boundaries = [
        int(block[0]["line"])
        for block in blocks
        if _line_text(block).casefold() == "indexes."
    ]
    if len(indexes_boundaries) != 1:
        raise ValueError("Strong Vol. 3 INDEXES. structure boundary is missing or duplicated")
    structure_end_line = indexes_boundaries[0]
    headings = []
    stack: list[tuple[int, int]] = []
    counts = {"uppercase": 0, "underscore-parenthetical": 0, "parenthetical": 0}
    for block in blocks:
        start_line = int(block[0]["line"])
        if start_line < BODY_FIRST_LINE or start_line >= structure_end_line:
            continue
        source_text = _line_text(block)
        marker = _source_heading_marker(source_text)
        matched_entry = heading_by_start.get(start_line)
        first_line = str(block[0]["text"])
        unlisted_marker = _SOURCE_NATIVE_MARKER.match(first_line)
        if matched_entry is None and unlisted_marker is None:
            continue
        if marker is None:
            raise ValueError(f"Strong Vol. 3 structural block has no hierarchy level at line {start_line}")
        level, _marker = marker
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_line = stack[-1][1] if stack else None
        if matched_entry is not None:
            body_record = matched_entry.get("body_record")
            declared_parent = body_record.get("parent_start_line") if body_record else None
            if declared_parent != parent_line:
                raise ValueError(
                    f"Strong Vol. 3 source hierarchy disagrees with contents at line {start_line}"
                )
        else:
            if parent_line is None:
                raise ValueError(
                    f"Strong Vol. 3 unlisted source heading has no source-supported parent at line {start_line}"
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
                    "start_line": start_line,
                    "end_line": int(block[-1]["line"]),
                    "type": "subsection",
                    "n": label,
                    "parent_start_line": parent_line,
                    "matched_contents_entry": False,
                    "source_text": source_text,
                }
            )
        stack.append((level, start_line))
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
    rows: list[dict[str, object]],
) -> dict[str, object]:
    blocks = _line_blocks(rows)
    named_headings: dict[str, list[int]] = {
        "Index Of Scripture Texts.": [],
        "Index Of Apocryphal Texts.": [],
        "Index Of Greek Words.": [],
    }
    for block in blocks:
        if len(block) != 1:
            continue
        title = _line_text(block)
        if title in named_headings:
            named_headings[title].append(int(block[0]["line"]))
    if any(len(lines) != 1 for lines in named_headings.values()):
        raise ValueError("Strong Vol. 3 text-index source boundaries are missing or duplicated")

    boundaries = [
        (
            "Scripture Texts",
            named_headings["Index Of Scripture Texts."][0],
            named_headings["Index Of Apocryphal Texts."][0],
        ),
        (
            "Apocryphal Texts",
            named_headings["Index Of Apocryphal Texts."][0],
            named_headings["Index Of Greek Words."][0],
        ),
    ]
    sections = []
    for title, heading_line, end_line_exclusive in boundaries:
        book_groups = [
            {"start_line": int(block[0]["line"]), "label": str(block[0]["text"])}
            for block in blocks
            if heading_line < int(block[0]["line"]) < end_line_exclusive
            and len(block) == 1
            and re.fullmatch(r"(?:[1-3] )?[A-Z][A-Za-z ,]+[.]", str(block[0]["text"]))
            is not None
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


def _note_inventory(
    blocks: list[list[dict[str, object]]],
    heading_by_start: dict[int, dict[str, object]],
) -> list[dict[str, object]]:
    headings = [entry["body_record"] for entry in heading_by_start.values()]
    notes = []
    for block in blocks:
        first = str(block[0]["text"])
        if first.startswith("[Transcriber’s Note:") and str(block[-1]["text"]).endswith("]"):
            preceding = [record for record in headings if int(record["start_line"]) < int(block[0]["line"])]
            nearest = max(preceding, key=lambda record: int(record["start_line"])) if preceding else None
            notes.append(
                {
                    "start_line": int(block[0]["line"]),
                    "end_line": int(block[-1]["line"]),
                    "type": "transcribers-note",
                    "parent_start_line": int(nearest["start_line"]) if nearest is not None else None,
                }
            )
    return notes


def _inline_inventory(blocks: list[list[dict[str, object]]]) -> dict[str, object]:
    spans = []
    marker_count = 0
    marker_blocks = 0
    cross_line = 0
    for block in blocks:
        positions = []
        for row in block:
            value = str(row["text"])
            for match in re.finditer("_", value):
                positions.append((int(row["line"]), match.start()))
        if not positions:
            continue
        marker_blocks += 1
        marker_count += len(positions)
        if len(positions) % 2:
            raise ValueError(f"unpaired underscore marker in source block at line {block[0]['line']}")
        for index in range(0, len(positions), 2):
            start_line, start_column = positions[index]
            end_line, end_column = positions[index + 1]
            cross_line += start_line != end_line
            spans.append(
                {
                    "start_line": start_line,
                    "start_column": start_column,
                    "end_line": end_line,
                    "end_column": end_column,
                }
            )
    return {
        "marker": "underscore",
        "rend": "italic",
        "blank_delimited_blocks": marker_blocks,
        "marker_count": marker_count,
        "span_count": len(spans),
        "cross_physical_line_span_count": cross_line,
        "span_positions_sha256": _sha(_canonical(spans)),
    }


def _append_text(parent: etree._Element, value: str) -> None:
    if not value:
        return
    if len(parent):
        previous = parent[-1]
        previous.tail = (previous.tail or "") + value
    else:
        parent.text = (parent.text or "") + value


def _append_block(
    parent: etree._Element,
    tag: str,
    block: list[dict[str, object]],
    *,
    type_value: str | None = None,
    strip_indentation: bool = False,
) -> etree._Element:
    node = etree.SubElement(
        parent,
        f"{{{TEI}}}{tag}",
        **({"type": type_value} if type_value is not None else {}),
    )
    node.set(XML_ID, _line_id(int(block[0]["line"])))
    node.set("n", str(block[0]["line"]))
    node.set(XML_SPACE, "preserve")

    active_hi: etree._Element | None = None
    marker_count = sum(str(row["text"]).count("_") for row in block)
    if marker_count % 2:
        raise ValueError(f"unpaired underscore marker in source block at line {block[0]['line']}")
    for row_index, row in enumerate(block):
        line_number = int(row["line"])
        if row_index:
            line_parent = active_hi if active_hi is not None else node
            line_break = etree.SubElement(line_parent, f"{{{TEI}}}lb")
            line_break.set(XML_ID, _line_id(line_number))
            line_break.set("n", str(line_number))
        value = str(row["text"])
        if strip_indentation:
            value = value.lstrip(" ")
        for character in value:
            if character == "_":
                if active_hi is None:
                    active_hi = etree.SubElement(node, f"{{{TEI}}}hi", rend="italic")
                else:
                    active_hi = None
            else:
                _append_text(active_hi if active_hi is not None else node, character)
    if active_hi is not None:
        raise ValueError(f"unclosed underscore emphasis at source line {block[-1]['line']}")
    return node


def _render_contents(
    parent: etree._Element,
    entries: list[dict[str, object]],
) -> None:
    list_node = etree.SubElement(parent, f"{{{TEI}}}list")
    for entry in entries:
        item = etree.SubElement(list_node, f"{{{TEI}}}item")
        _append_block(item, "p", entry["lines"], strip_indentation=True)
        children = entry["children"]
        assert isinstance(children, list)
        if children:
            _render_contents(item, children)


def _inventory_digest(rows: list[dict[str, object]]) -> str:
    return _sha(
        _canonical(
            [
                {key: row[key] for key in ("line", "start", "end", "ending", "sha256")}
                for row in rows
            ]
        )
    )


def _convert(source_manifest: SourceManifest) -> Mapping[str, bytes]:
    source_manifest.verify()
    authority = source_manifest.authority_path("retained-source")
    source = authority.read_bytes()
    rows = _records(source)
    if (
        source_manifest.record.get("source_id") != SOURCE_ID
        or len(source) != 1_868_543
        or _sha(source) != "103dc623072326111214078015dfbe8cb8f97197cba6e5e6faffede8bb1a20fe"
    ):
        raise ValueError("Strong Vol. 3 exact retained witness drifted")
    profile = json.loads(source_manifest.authority_path("reconstruction-profile").read_bytes())
    if profile.get("edition_evidence") != EDITION_EVIDENCE:
        raise ValueError("Strong Vol. 3 title-page edition profile drifted")
    if any(str(rows[int(line) - 1]["text"]).strip() != text for line, text in TITLE_PAGE_LINES.items()):
        raise ValueError("Strong Vol. 3 retained title-page imprint drifted")
    source_config = json.loads(source_manifest.authority_path("source-config").read_bytes())
    if source_config.get("source_edition") != EDITION or source_config.get("original_publication_year") is not None:
        raise ValueError("Strong Vol. 3 work config conflates volume imprint and original-publication year")
    policy = json.loads(source_manifest.authority_path("validation-policy").read_bytes())
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
    }
    if not required_checks.issubset(set(policy.get("required_checks", []))):
        raise ValueError("Strong Vol. 3 validation policy omits a source-structure or inline check")

    blocks = _line_blocks(rows)
    roots, flat_contents, contents_summary = _parse_contents(rows)
    end_markers = [
        int(row["line"])
        for row in rows
        if str(row["text"]).startswith(GUTENBERG_END_PREFIX)
    ]
    if len(end_markers) != 1:
        raise ValueError("Strong Vol. 3 Gutenberg end marker is missing or duplicated")
    heading_by_start, body_summary = _body_heading_profile(rows, flat_contents, end_markers[0])
    source_native_body_outline = _source_native_body_outline(rows, heading_by_start)
    text_index_profile = _text_index_profile(rows)
    source_native_heading_by_start = {
        int(item["start_line"]): item
        for item in source_native_body_outline["headings"]
    }
    index_group_by_start = {
        int(item["start_line"]): (str(section["title"]), str(item["label"]))
        for section in text_index_profile["sections"]
        for item in section["book_groups"]
    }
    for section in text_index_profile["sections"]:
        index_entry = heading_by_start.get(int(section["body_heading_line"]))
        if (
            index_entry is None
            or _entry_kind(_line_text(index_entry["lines"], strip_indent=True))
            != ("index", str(section["title"]))
        ):
            raise ValueError(
                f"Strong Vol. 3 {section['title']} index boundary is not the matched contents heading"
            )
    notes = _note_inventory(blocks, heading_by_start)
    inline = _inline_inventory(blocks)
    if profile.get("source_scope") != {
        "bytes": len(source),
        "physical_lines": len(rows),
        "source_inventory_sha256": _inventory_digest(rows),
    }:
        raise ValueError("Strong Vol. 3 source profile census drifted")
    if profile.get("contents_outline") != contents_summary:
        raise ValueError("Strong Vol. 3 printed contents outline differs from its profile")
    if profile.get("body_outline") != body_summary:
        raise ValueError("Strong Vol. 3 matched body-heading inventory differs from its profile")
    if profile.get("source_native_body_outline") != source_native_body_outline:
        raise ValueError("Strong Vol. 3 source-native body headings differ from their profile")
    if profile.get("text_index_groups") != text_index_profile:
        raise ValueError("Strong Vol. 3 index headings differ from their source profile")
    if profile.get("note_blocks") != notes:
        raise ValueError("Strong Vol. 3 explicit transcriber-note inventory differs from its profile")
    if profile.get("inline_emphasis") != inline:
        raise ValueError("Strong Vol. 3 underscore-emphasis inventory differs from its profile")
    if profile.get("figure_placeholder_line") != 241 or str(rows[240]["text"]).strip() != "[Cover Art]":
        raise ValueError("Strong Vol. 3 cover-art placeholder differs from its profile")

    root = etree.Element(f"{{{TEI}}}TEI", nsmap={None: TEI})
    header = etree.SubElement(root, f"{{{TEI}}}teiHeader")
    file_desc = etree.SubElement(header, f"{{{TEI}}}fileDesc")
    title_stmt = etree.SubElement(file_desc, f"{{{TEI}}}titleStmt")
    etree.SubElement(title_stmt, f"{{{TEI}}}title").text = "Systematic Theology, Vol. 3"
    etree.SubElement(title_stmt, f"{{{TEI}}}author").text = "Augustus H. Strong"
    publication = etree.SubElement(file_desc, f"{{{TEI}}}publicationStmt")
    etree.SubElement(publication, f"{{{TEI}}}p").text = "Nonaccepted reconstruction candidate; publication:not_ready."
    source_desc = etree.SubElement(file_desc, f"{{{TEI}}}sourceDesc")
    bibliography = etree.SubElement(source_desc, f"{{{TEI}}}bibl")
    etree.SubElement(bibliography, f"{{{TEI}}}title").text = (
        f"Exact retained non-OCR Project Gutenberg text #45283; SHA-256 {_sha(source)}."
    )
    for kind, value in (
        ("work-id", WORK_ID),
        ("gutenberg", "45283"),
        ("source-sha256", _sha(source)),
        ("edition", EDITION),
        ("source-path", SOURCE_PATH),
    ):
        etree.SubElement(bibliography, f"{{{TEI}}}idno", type=kind).text = value
    text = etree.SubElement(root, f"{{{TEI}}}text")
    body = etree.SubElement(text, f"{{{TEI}}}body")
    transcript = etree.SubElement(body, f"{{{TEI}}}div", type="retained-file-transcription", n="complete-file")

    note_by_start = {item["start_line"]: item for item in notes}
    active_div = transcript
    contents_div: etree._Element | None = None
    outline_body: etree._Element | None = None
    heading_div_by_start: dict[int, etree._Element] = {}
    active_text_index_div: etree._Element | None = None
    active_text_index_title: str | None = None
    for block in _render_blocks(rows):
        start_line = int(block[0]["line"])
        if start_line == CONTENTS_TITLE_LINE:
            contents_div = etree.SubElement(transcript, f"{{{TEI}}}div", type="contents")
            _append_block(contents_div, "head", block)
            continue
        if start_line == CONTENTS_FIRST_ENTRY_LINE:
            if contents_div is None:
                raise ValueError("Strong Vol. 3 contents heading was not emitted")
            _render_contents(contents_div, roots)
            continue
        if CONTENTS_FIRST_ENTRY_LINE <= start_line <= CONTENTS_LAST_ENTRY_LINE:
            continue
        if len(block) == 1 and not str(block[0]["text"]).strip():
            _append_block(active_div, "ab", block, type_value="source-whitespace-line")
            continue
        if start_line in heading_by_start:
            entry = heading_by_start[start_line]
            parent_entry = entry["parent"]
            if parent_entry is None:
                if outline_body is None:
                    raise ValueError("Strong Vol. 3 unheaded source container was not materialized")
                parent_div = outline_body
            else:
                parent_div = parent_entry.get("tei_div")
                if parent_div is None:
                    raise ValueError(
                        f"source outline parent at line {parent_entry['start_line']} was not materialized"
                    )
            kind, number = _entry_kind(_line_text(entry["lines"], strip_indent=True))
            attributes = {"type": kind}
            if number is not None:
                attributes["n"] = number
            active_div = etree.SubElement(parent_div, f"{{{TEI}}}div", **attributes)
            entry["tei_div"] = active_div
            heading_div_by_start[start_line] = active_div
            _append_block(active_div, "head", block)
            active_text_index_title = (
                number if kind == "index" and number in {"Scripture Texts", "Apocryphal Texts"} else None
            )
            active_text_index_div = active_div if active_text_index_title is not None else None
            continue
        if start_line in source_native_heading_by_start:
            heading = source_native_heading_by_start[start_line]
            parent_start = int(heading["parent_start_line"])
            parent_div = heading_div_by_start.get(parent_start)
            if parent_div is None:
                raise ValueError(
                    f"Strong Vol. 3 source-native heading parent at line {parent_start} was not materialized"
                )
            active_div = etree.SubElement(
                parent_div,
                f"{{{TEI}}}div",
                type=str(heading["type"]),
                n=str(heading["n"]),
            )
            heading_div_by_start[start_line] = active_div
            _append_block(active_div, "head", block)
            continue
        if start_line in index_group_by_start:
            title, label = index_group_by_start[start_line]
            if active_text_index_div is None or active_text_index_title != title:
                raise ValueError(f"Strong Vol. 3 {title} book heading is outside its source index")
            active_div = etree.SubElement(
                active_text_index_div,
                f"{{{TEI}}}div",
                type="index-group",
                n=label.rstrip("."),
            )
            _append_block(active_div, "head", block)
            continue
        if start_line in note_by_start:
            _append_block(active_div, "note", block, type_value="transcribers-note")
            continue
        if start_line == 241 and str(block[0]["text"]).strip() == "[Cover Art]":
            outline_body = etree.SubElement(
                transcript,
                f"{{{TEI}}}div",
                type="source-outline-body",
            )
            active_div = outline_body
            _append_block(active_div, "ab", block, type_value="source-figure-placeholder")
            continue
        if start_line in EPIGRAPH_LINES:
            _append_block(active_div, "quote", block, type_value="epigraph")
            continue
        if str(block[0]["text"]).startswith(GUTENBERG_END_PREFIX):
            if outline_body is None:
                raise ValueError("Strong Vol. 3 Gutenberg tail has no source-outline container")
            active_div = etree.SubElement(
                outline_body,
                f"{{{TEI}}}div",
                type="source-envelope-tail",
            )
        tag = "p" if BODY_FIRST_LINE <= start_line < end_markers[0] else "ab"
        type_value = "source-block" if tag == "ab" else None
        _append_block(active_div, tag, block, type_value=type_value)

    accountability = {
        "contract": "ocd-source-accountability-v1",
        "work_id": WORK_ID,
        "source_member": {"path": SOURCE_PATH, "bytes": len(source), "sha256": _sha(source)},
        "physical_line_count": len(rows),
        "nonblank_line_count": sum(bool(row["text"]) for row in rows),
        "blank_line_count": sum(not row["text"] for row in rows),
        "source_inventory_sha256": _inventory_digest(rows),
        "line_disposition": (
            "every nonblank retained physical line is represented once by its xml:id anchor; "
            "line wraps use lb; printed contents indentation becomes nested lists; balanced "
            "underscore delimiters become hi rend=italic; blank records are separators"
        ),
        "lines": [
            {
                "line": row["line"],
                "byte_start": row["start"],
                "byte_end": row["end"],
                "terminator": row["ending"],
                "record_sha256": row["sha256"],
                "disposition": "represented" if row["text"] else "separator",
                "tei_selector": f"#{_line_id(int(row['line']))}" if row["text"] else None,
            }
            for row in rows
        ],
    }
    runtime = f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})"
    provenance = {
        "contract": "ocd-reconstruction-provenance-v1",
        "status": "nonaccepted",
        "publication": "not_ready",
        "work_id": WORK_ID,
        "source_sha256": _sha(source),
        "source_manifest_sha256": source_manifest.sha256,
        "producer": {"id": CONVERTER_ID, "version": CONVERTER_VERSION},
        "runtime": runtime,
        "scope": (
            "complete retained Gutenberg file; the indented contents outline is nested; "
            "body headings are nested where exact source blocks match contents entries or "
            "the source-marked unlisted outline; balanced underscore emphasis and explicit "
            "transcriber notes are mapped; unmarked prose and index entries remain in source "
            "order without invented hierarchy"
        ),
    }
    unresolved = [
        {
            "id": f"{WORK_ID}-original-publication-year",
            "status": "unresolved",
            "statement": "The Volume 3 title page gives a 1909 imprint; the work's original-publication year is not established and is not inferred from a set-level date.",
        },
        {
            "id": f"{WORK_ID}-rights",
            "status": "unresolved",
            "statement": "The Gutenberg notice is not worldwide rights clearance.",
        },
        {
            "id": f"{WORK_ID}-human-acceptance",
            "status": "unresolved",
            "statement": "No human acceptance is asserted.",
        },
        {
            "id": f"{WORK_ID}-publication",
            "status": "not_ready",
            "statement": "Publication is not authorized.",
        },
        {
            "id": f"{WORK_ID}-structure",
            "status": "unresolved",
            "statement": (
                f"{body_summary['matched_heading_count']} body headings match the printed "
                f"contents and are nested; {body_summary['unresolved_toc_entry_count']} "
                "contents entries lack a directly matched body heading or a materialized "
                f"parent. The {source_native_body_outline['heading_count']} unlisted source-"
                "marked blocks before INDEXES. are represented and nested by their retained "
                "marker levels. Unmarked prose and index entries remain source-ordered "
                "containers without an invented hierarchy; no unlisted source-marked block "
                "is omitted by this route."
            ),
        },
        {
            "id": f"{WORK_ID}-note-semantics",
            "status": "unresolved",
            "statement": (
                "The two explicitly labeled transcriber notes are represented as notes. "
                "Citations and inline page references are preserved as text; the source does "
                "not establish a separate scholarly note apparatus."
            ),
        },
    ]
    return {
        "README.source.md": source_manifest.authority_path("attribution-readme").read_bytes(),
        "content.tei.xml": etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False),
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
