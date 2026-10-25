"""Bounded source-located literary block enrichment for LIB-068.

The regular LIB-068 producer establishes the section, paragraph, note, and
physical-line floor.  This module is deliberately an independent post-pass:
it only consumes that tree, the retained source lines, and the pinned
reconstruction profile.  It never calls the producer and never invents an
edition, date, image, or editorial reading.

``apply_blocks`` mutates the supplied retained-source ``div`` in place and
returns a source inventory plus deterministic mutation descriptions.  The
independent actual-tree checker lives in the companion oracle helper; this
producer has no self-verifying fast path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import hashlib
import re
from typing import Any

from lxml import etree


TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
_T = f"{{{TEI_NS}}}"
_XML_ID = f"{{{XML_NS}}}id"

NEWMAN = "newman-apologia-pro-vita-sua"
DONNE = "donne-devotions-upon-emergent-occasions"
SUPPORTED_WORKS = frozenset({NEWMAN, DONNE})


# These pins are intentionally source metadata, not a second retained-source
# store.  ``lines`` must be the exact list returned by the LIB-068 source-line
# loader, including the BOM-bearing first line and terminal empty split line.
SOURCE_PINS: dict[str, dict[str, Any]] = {
    NEWMAN: {
        "source_path": "raw/gutenberg/pg22088.txt",
        "source_sha256": "18e63c1d0bf11c66d6a6fdda83c19de9005c50b06831785a3507fcd1b6a49073",
        "line_count": 14_174,
        "blank_count": 1_553,
        "newline": "\r\n",
    },
    DONNE: {
        "source_path": "raw/gutenberg/pg23772.txt",
        "source_sha256": "f1f2b08f2dcfe9f6618bb8031a5d055b5d58e30f80a399ff866d5b205b1773b7",
        "line_count": 7_647,
        "blank_count": 1_098,
        "newline": "\r\n",
    },
}


# All ranges are inclusive source line numbers.  Repeated headings remain
# separate records; no heading text is used as an identity key.
SPECIAL_SOURCE_INVENTORY: dict[str, dict[str, Any]] = {
    NEWMAN: {
        "verse": [
            {
                "id": "newman-title-psalm",
                "start": 43,
                "end": 45,
                "parent": 33,
                "stanzas": [(43, 45)],
                "titles": (),
                "attributions": (),
                "illustrations": (),
            }
        ],
        "calendar": {
            "parent": 10742,
            "months": [
                (10745, "JANUARY."),
                (10778, "FEBRUARY."),
                (10810, "MARCH."),
                (10844, "APRIL."),
                (10877, "MAY."),
                (10911, "JUNE."),
                (10944, "JULY."),
                (10979, "AUGUST."),
                (11013, "SEPTEMBER."),
                (11046, "OCTOBER."),
                (11081, "NOVEMBER."),
                (11114, "DECEMBER."),
            ],
        },
        "chronology": {
            "parent": 11155,
            "heading_count": 34,
            "entry_count": 300,
            # Inner groups precede enclosing groups when both begin on one line.
            "brace_groups": [(11231, 11235), (11337, 11341), (11345, 11347), (11390, 11394), (11390, 11398), (11399, 11408)],
        },
        "supplement_i": {"parent": 12385, "header": 12389, "start": 12390, "end": 12464, "row_count": 75},
        "bibliography": {
            "parent": 12469,
            "categories": (12476, 12489, 12500, 12519, 12528, 12540, 12556),
            # The last category's visible prose ends at 12568; the profile
            # keeps its four trailing physical blanks (12569-12572) under
            # the category before Supplement III begins at 12573.
            "end": 12572,
        },
    },
    DONNE: {
        "verse": [
            {
                "id": "donne-hymn-father",
                "start": 767,
                "end": 790,
                "parent": 93,
                "stanzas": [(771, 776), (778, 783), (785, 790)],
                "titles": (767, 769),
                "attributions": (),
                "illustrations": (),
            },
            {
                "id": "donne-george-herbert-verse",
                "start": 856,
                "end": 919,
                "parent": 93,
                "stanzas": [(862, 865), (869, 871), (873, 894), (904, 906), (908, 917)],
                "titles": (856, 858, 900, 902),
                "attributions": (896, 919),
                "illustrations": (860, 867),
            },
            {
                "id": "donne-hymn-sickness",
                "start": 927,
                "end": 945,
                "parent": 93,
                "stanzas": [(931, 935), (937, 939), (941, 945)],
                "titles": (927, 929),
                "attributions": (),
                "illustrations": (),
            },
        ],
        "components": {"parent": 1481, "start": 1489, "end": 1494, "items": (1489, 1491, 1493)},
        "station_contents": {"parent": 1539, "start": 1546, "end": 1607, "item_count": 23},
    },
}


_MONTH_RE = re.compile(r"^\s*(\d{1,2})(?:\s+(.*?))?\s*$")
_CHRONOLOGY_START_RE = re.compile(
    r"^\s*(?:(?:\d{3,4}(?:-\d{2,4})?|(?:abt\.|aft\.|bef\.)\s+\d{3,4})\s+)?"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|Ap|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2}[\.,]"
    r"|^\s*(?:\d{3,4}(?:-\d{2,4})?|(?:abt\.|aft\.|bef\.)\s+\d{3,4})\s*(?:[-—]{2,}|(?=\S))"
)
_BIB_NUMBER_RE = re.compile(r"^\s*(\d+(?:\s*[-,]\s*\d+)*)\.\s+")


def _tag(name: str) -> str:
    return f"{_T}{name}"


def _sha_lines(work_id: str, lines: Sequence[str]) -> str:
    pin = SOURCE_PINS[work_id]
    return hashlib.sha256(pin["newline"].join(lines).encode("utf-8")).hexdigest()


def _validate_source(work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    if work_id not in SUPPORTED_WORKS:
        raise ValueError(f"LIB-068 literary blocks do not support {work_id!r}")
    pin = SOURCE_PINS[work_id]
    if len(lines) != pin["line_count"] or sum(line == "" for line in lines) != pin["blank_count"]:
        raise ValueError(f"LIB-068 {work_id} source line census drifted")
    actual_sha = _sha_lines(work_id, lines)
    if actual_sha != pin["source_sha256"]:
        raise ValueError(f"LIB-068 {work_id} source bytes drifted")
    if not lines or not lines[-1] == "":
        raise ValueError(f"LIB-068 {work_id} source terminal split line drifted")
    return pin


def _profile_rows(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = profile.get("literary_sections")
    if not isinstance(rows, list) or not rows:
        raise ValueError("LIB-068 literary profile rows are absent")
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("LIB-068 literary profile row is invalid")
    starts = [int(row["line"]) for row in rows]
    if starts != sorted(set(starts)) or starts[0] != 1:
        raise ValueError("LIB-068 literary profile order drifted")
    return rows


def _seg_map(scope: etree._Element) -> dict[int, etree._Element]:
    result: dict[int, etree._Element] = {}
    for node in scope.iter(_tag("seg")):
        if node.get("type") != "source-line" or node.get("n") is None:
            continue
        number = int(node.get("n"))
        if number in result:
            raise ValueError(f"LIB-068 duplicate source-line carrier {number}")
        result[number] = node
    return result


def _section_node(scope: etree._Element, number: int, kind: str | None = None) -> etree._Element:
    matches = [node for node in scope.iter(_tag("div")) if node.get("n") == str(number)]
    if kind is not None:
        matches = [node for node in matches if node.get("type") == kind]
    if len(matches) != 1:
        raise ValueError(f"LIB-068 expected one section {kind or ''} at line {number}, found {len(matches)}")
    return matches[0]


def _nearest_block(seg: etree._Element) -> etree._Element:
    for parent in seg.iterancestors():
        if parent.tag in {_tag("p"), _tag("ab"), _tag("head")}:
            return parent
    raise ValueError(f"LIB-068 source-line {seg.get('n')} has no source block parent")


def _block_numbers(block: etree._Element) -> list[int]:
    return [int(seg.get("n")) for seg in block.iter(_tag("seg")) if seg.get("type") == "source-line"]


def _extract_range(scope: etree._Element, start: int, end: int) -> tuple[etree._Element, int, list[etree._Element], dict[int, etree._Element]]:
    expected = set(range(start, end + 1))
    segments = _seg_map(scope)
    missing = sorted(expected - set(segments))
    if missing:
        raise ValueError(f"LIB-068 source range {start}-{end} omits lines {missing[:5]}")
    blocks: set[etree._Element] = set()
    for number in expected:
        block = _nearest_block(segments[number])
        blocks.add(block)
    parent = next(iter(blocks)).getparent()
    if any(block.getparent() is not parent for block in blocks):
        raise ValueError(f"LIB-068 source range {start}-{end} crosses source containers")
    ordered = sorted(blocks, key=parent.index)
    for block in ordered:
        actual = set(_block_numbers(block))
        if not actual <= expected:
            raise ValueError(f"LIB-068 source range {start}-{end} cuts source block {sorted(actual)[:5]}")
    indices = [parent.index(block) for block in ordered]
    if indices != list(range(min(indices), max(indices) + 1)):
        raise ValueError(f"LIB-068 source range {start}-{end} has an unselected sibling block")
    insert_at = min(indices)
    for block in reversed(ordered):
        parent.remove(block)
    return parent, insert_at, ordered, {number: segments[number] for number in expected}


def _extract_body_blocks(section: etree._Element) -> tuple[int, list[etree._Element], dict[int, etree._Element]]:
    blocks = [
        child
        for child in section
        if child.tag in {_tag("p"), _tag("ab")} and _block_numbers(child)
    ]
    if not blocks:
        raise ValueError(f"LIB-068 section {section.get('n')} has no direct source blocks")
    indices = [section.index(block) for block in blocks]
    if indices != list(range(min(indices), max(indices) + 1)):
        raise ValueError(f"LIB-068 section {section.get('n')} body has an unexpected child between source blocks")
    segments = _seg_map(section)
    selected = {number: segments[number] for block in blocks for number in _block_numbers(block)}
    insert_at = min(indices)
    for block in reversed(blocks):
        section.remove(block)
    return insert_at, blocks, selected


def _line_id(work_id: str, number: int) -> str:
    return f"{work_id}-line-{number}"


def _mark_segment(seg: etree._Element, work_id: str, number: int) -> None:
    expected = _line_id(work_id, number)
    current = seg.get(_XML_ID)
    if current not in (None, expected):
        raise ValueError(f"LIB-068 source-line {number} has an unrelated XML ID")
    seg.set(_XML_ID, expected)
    if seg.getparent() is not None:
        seg.getparent().remove(seg)
    seg.tail = None


def _append_seg(parent: etree._Element, seg: etree._Element, work_id: str) -> None:
    number = int(seg.get("n"))
    _mark_segment(seg, work_id, number)
    parent.append(seg)


def _new_whitespace(numbers: Iterable[int], segments: Mapping[int, etree._Element], work_id: str) -> etree._Element:
    node = etree.Element(_tag("ab"), type="source-whitespace")
    for number in numbers:
        _append_seg(node, segments[number], work_id)
    return node


def _new_line_block(
    name: str,
    numbers: Iterable[int],
    segments: Mapping[int, etree._Element],
    work_id: str,
    **attributes: str,
) -> etree._Element:
    node = etree.Element(_tag(name), **attributes)
    for number in numbers:
        _append_seg(node, segments[number], work_id)
    return node


def _append_mixed_text(parent: etree._Element, text: str) -> None:
    """Append text at the correct mixed-content position."""
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _slice_inline_content(node: etree._Element, start: int, end: int) -> etree._Element:
    """Clone one inline node while retaining only an itertext slice.

    The table columns cut only at source-column boundaries, but source-line
    segments can contain ``hi`` or ``ref`` children.  This small mixed-content
    slicer keeps those children (and their attributes) when a boundary falls
    inside one, rather than flattening or duplicating source text.
    """
    total = len("".join(node.itertext()))
    if start < 0 or end > total or start >= end:
        raise ValueError(f"LIB-068 invalid inline slice {start}:{end} of {total}")
    clone = etree.Element(node.tag, attrib=dict(node.attrib))
    cursor = 0

    def add_text(value: str) -> None:
        nonlocal cursor
        value_start = cursor
        value_end = cursor + len(value)
        overlap_start = max(start, value_start)
        overlap_end = min(end, value_end)
        if overlap_start < overlap_end:
            _append_mixed_text(clone, value[overlap_start - value_start : overlap_end - value_start])
        cursor = value_end

    add_text(node.text or "")
    for child in node:
        child_text = "".join(child.itertext())
        child_start = cursor
        child_end = cursor + len(child_text)
        overlap_start = max(start, child_start)
        overlap_end = min(end, child_end)
        if overlap_start < overlap_end:
            clone.append(
                _slice_inline_content(
                    child,
                    overlap_start - child_start,
                    overlap_end - child_start,
                )
            )
        cursor = child_end
        add_text(child.tail or "")
    if cursor != total:
        raise ValueError("LIB-068 inline content census drifted while splitting a source line")
    if "".join(clone.itertext()) != "".join(node.itertext())[start:end]:
        raise ValueError("LIB-068 inline source slice changed source text")
    return clone


def _split_source_segment(
    source: etree._Element,
    work_id: str,
    number: int,
    line: str,
    spans: Sequence[tuple[str, int, int]],
    ana_prefix: str,
) -> list[etree._Element]:
    """Detach a source-line carrier into exact, source-backed column parts."""
    if source.get("type") != "source-line" or source.get("n") != str(number):
        raise ValueError(f"LIB-068 expected source-line carrier at {number}")
    expected_id = _line_id(work_id, number)
    current_id = source.get(_XML_ID)
    if current_id not in (None, expected_id):
        raise ValueError(f"LIB-068 source-line {number} has an unrelated XML ID")
    if not spans or spans[0][1] != 0 or spans[-1][2] != len(line):
        raise ValueError(f"LIB-068 column spans do not cover source line {number}")
    cursor = 0
    nonempty: list[tuple[str, int, int]] = []
    for column, start, end in spans:
        if start != cursor or end < start or end > len(line):
            raise ValueError(f"LIB-068 column spans are not contiguous at source line {number}")
        cursor = end
        if start < end:
            nonempty.append((column, start, end))
    if cursor != len(line) or not nonempty:
        raise ValueError(f"LIB-068 source line {number} has no represented column text")
    if source.getparent() is None:
        raise ValueError(f"LIB-068 source-line {number} is already detached")
    source.getparent().remove(source)
    source.tail = None
    fragments: list[etree._Element] = []
    for part_index, (column, start, end) in enumerate(nonempty):
        part = "N" if len(nonempty) == 1 else "I" if part_index == 0 else "F" if part_index == len(nonempty) - 1 else "M"
        fragment = _slice_inline_content(source, start, end)
        fragment.set("type", "source-line-fragment")
        fragment.set("n", str(number))
        fragment.set("part", part)
        fragment.set("ana", f"{ana_prefix}-{column}")
        # TEI has no generic numeric ``offset`` attribute.  The standard
        # segLike ``function`` attribute carries the exact half-open source
        # column range while n remains the physical source-line identity.
        fragment.set("function", f"source-column-{column}-{start}-{end}")
        fragment.set(_XML_ID, expected_id if part_index == 0 else f"{expected_id}-fragment-{column}")
        if part_index:
            fragment.set("corresp", f"#{expected_id}")
        if "".join(fragment.itertext()) != line[start:end]:
            raise ValueError(f"LIB-068 source-line fragment changed text at {number}")
        fragments.append(fragment)
    return fragments


def _append_fragment_cell(
    row: etree._Element,
    role: str,
    work_id: str,
    line_numbers: Sequence[int],
    fragments: Sequence[etree._Element],
    **attributes: str,
) -> etree._Element | None:
    """Append a nonempty table cell carrying exact source-line fragments."""
    if not fragments:
        return None
    cell_attributes = {"role": role, **attributes}
    targets = " ".join(dict.fromkeys(f"#{_line_id(work_id, number)}" for number in line_numbers))
    if targets:
        cell_attributes["corresp"] = targets
    cell = etree.SubElement(row, _tag("cell"), **cell_attributes)
    p = etree.SubElement(cell, _tag("p"))
    for fragment in fragments:
        p.append(fragment)
    return cell


def _fixed_page_span(line: str, number: int) -> tuple[int, str]:
    """Return the retained table's fixed date/page column boundary."""
    if len(line) != 31:
        raise ValueError(f"LIB-068 Supplement I line {number} is not the pinned 31-column width")
    match = re.search(r"(\d+)\s*$", line)
    if match is None or match.end() != len(line) or not 1 <= len(match.group(1)) <= 3:
        raise ValueError(f"LIB-068 Supplement I page column drift at line {number}")
    boundary = 27
    page_field = line[boundary:]
    if page_field.strip() != match.group(1) or not page_field.strip().isdigit():
        raise ValueError(f"LIB-068 Supplement I fixed page column drift at line {number}")
    return boundary, match.group(1)


def _insert(parent: etree._Element, index: int, nodes: Iterable[etree._Element]) -> None:
    for offset, node in enumerate(nodes):
        parent.insert(index + offset, node)


def _assert_anchor(lines: Sequence[str], number: int, expected: str | re.Pattern[str]) -> None:
    value = lines[number - 1]
    if isinstance(expected, str):
        if value != expected:
            raise ValueError(f"LIB-068 source anchor drift at line {number}")
    elif expected.fullmatch(value) is None:
        raise ValueError(f"LIB-068 source anchor pattern drift at line {number}")


def _verse_quote(scope: etree._Element, work_id: str, lines: Sequence[str], spec: Mapping[str, Any]) -> None:
    parent, index, _, segments = _extract_range(scope, spec["start"], spec["end"])
    quote = etree.Element(
        _tag("quote"),
        type="source-verse",
        n=str(spec["start"]),
        **{_XML_ID: f"{work_id}-{spec['id']}"},
    )
    titles = set(spec["titles"])
    attributions = set(spec["attributions"])
    illustrations = set(spec["illustrations"])
    stanzas = {number: (first, last) for first, last in spec["stanzas"] for number in range(first, last + 1)}
    assigned: set[int] = set()
    number = spec["start"]
    while number <= spec["end"]:
        if lines[number - 1] == "":
            end = number
            while end <= spec["end"] and lines[end - 1] == "":
                end += 1
            quote.append(_new_whitespace(range(number, end), segments, work_id))
            assigned.update(range(number, end))
            number = end
            continue
        if number in illustrations:
            figure_id = f"{work_id}-illustration-{number}"
            figure = etree.Element(
                _tag("figure"),
                type="source-illustration-placeholder",
                n=str(number),
                corresp=f"#{_line_id(work_id, number)}",
                **{_XML_ID: figure_id},
            )
            figure.append(etree.Element(_tag("figDesc")))
            marker = _new_line_block(
                "p",
                (number,),
                segments,
                work_id,
                ana="source-illustration-marker",
                corresp=f"#{figure_id}",
            )
            quote.extend((figure, marker))
            assigned.add(number)
            number += 1
            continue
        if number in titles:
            quote.append(_new_line_block("p", (number,), segments, work_id, ana="source-verse-title", n=str(number)))
            assigned.add(number)
            number += 1
            continue
        if number in attributions:
            quote.append(_new_line_block("p", (number,), segments, work_id, ana="source-attribution", n=str(number)))
            assigned.add(number)
            number += 1
            continue
        stanza = stanzas.get(number)
        if stanza is None or number != stanza[0]:
            raise ValueError(f"LIB-068 verse inventory does not classify source line {number}")
        first, last = stanza
        lg = etree.Element(_tag("lg"), type="stanza", n=str(first))
        for line_number in range(first, last + 1):
            if lines[line_number - 1] == "":
                raise ValueError(f"LIB-068 verse stanza unexpectedly contains blank line {line_number}")
            line = etree.SubElement(lg, _tag("l"), n=str(line_number))
            _append_seg(line, segments[line_number], work_id)
            assigned.add(line_number)
        quote.append(lg)
        number = last + 1
    expected = set(range(spec["start"], spec["end"] + 1))
    if assigned != expected:
        raise ValueError(f"LIB-068 verse mapping does not account for {sorted(expected - assigned)}")
    _insert(parent, index, (quote,))


def _apply_verses(scope: etree._Element, work_id: str, lines: Sequence[str]) -> None:
    for spec in SPECIAL_SOURCE_INVENTORY[work_id]["verse"]:
        _verse_quote(scope, work_id, lines, spec)


def _calendar_table(scope: etree._Element, work_id: str, lines: Sequence[str], month_start: int, next_start: int, month_name: str) -> dict[str, int]:
    month = _section_node(scope, month_start, "month")
    row_starts = [
        number
        for number in range(month_start + 1, next_start)
        if _MONTH_RE.fullmatch(lines[number - 1]) is not None
    ]
    if not row_starts:
        raise ValueError(f"LIB-068 calendar month {month_name} has no day rows")
    row_ranges: list[tuple[int, int]] = []
    for index, row_start in enumerate(row_starts):
        boundary = row_starts[index + 1] if index + 1 < len(row_starts) else next_start
        row_end = boundary - 1
        first_blank = next((number for number in range(row_start, boundary) if not lines[number - 1].strip()), None)
        if first_blank is not None:
            if index + 1 < len(row_starts):
                raise ValueError(f"LIB-068 calendar row has an unexpected blank at line {first_blank}")
            row_end = first_blank - 1
        if row_end < row_start or any(not lines[number - 1].strip() for number in range(row_start, row_end + 1)):
            raise ValueError(f"LIB-068 calendar row has an unexpected blank at line {row_start}")
        row_ranges.append((row_start, row_end))
    first, last = row_ranges[0][0], row_ranges[-1][1]
    parent, index, _, segments = _extract_range(scope, first, last)
    if parent is not month:
        raise ValueError(f"LIB-068 calendar month {month_name} source blocks escaped month section")
    table = etree.Element(
        _tag("table"),
        type="calendar",
        n=str(month_start),
        **{_XML_ID: f"{work_id}-calendar-{month_start}"},
    )
    observed = 0
    empty = 0
    for row_start, row_end in row_ranges:
        number = row_start
        match = _MONTH_RE.fullmatch(lines[number - 1])
        if match is None:
            raise ValueError(f"LIB-068 calendar day row drift at line {number}")
        day, description = int(match.group(1)), (match.group(2) or "").strip()
        if len(lines[number - 1]) < 2 or lines[number - 1][:2].strip() != str(day):
            raise ValueError(f"LIB-068 calendar fixed day column drift at line {number}")
        row = etree.SubElement(table, _tag("row"), n=str(number), **{_XML_ID: f"{work_id}-calendar-row-{number}"})
        day_fragments: list[etree._Element] = []
        observance_fragments: list[etree._Element] = []
        row_line_numbers = list(range(row_start, row_end + 1))
        for source_number in range(row_start, row_end + 1):
            raw = lines[source_number - 1]
            if source_number == row_start:
                spans = (("day", 0, 2), ("observance", 2, len(raw)))
            else:
                # July 15 has the source continuation ``Q.V.`` on its own
                # physical line.  It belongs to the observation column and
                # remains a distinct source-line fragment.
                if _MONTH_RE.fullmatch(raw) is not None:
                    raise ValueError(f"LIB-068 calendar row boundary drift at line {source_number}")
                spans = (("observance", 0, len(raw)),)
            fragments = _split_source_segment(
                segments[source_number],
                work_id,
                source_number,
                raw,
                spans,
                "calendar",
            )
            for fragment in fragments:
                if fragment.get("function", "").startswith("source-column-day-"):
                    day_fragments.append(fragment)
                else:
                    observance_fragments.append(fragment)
        _append_fragment_cell(row, "day", work_id, (number,), day_fragments, n=str(day))
        if observance_fragments:
            _append_fragment_cell(
                row,
                "observance",
                work_id,
                row_line_numbers,
                observance_fragments,
                n="present",
            )
        if description:
            observed += 1
        else:
            empty += 1
    _insert(parent, index, (table,))
    return {"rows": len(row_ranges), "observed": observed, "empty": empty}


def _apply_calendar(scope: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["calendar"]
    months = data["months"]
    if len(months) != 12:
        raise ValueError("LIB-068 calendar month inventory drifted")
    summary: list[dict[str, Any]] = []
    for index, (start, name) in enumerate(months):
        next_start = months[index + 1][0] if index + 1 < len(months) else 11155
        _assert_anchor(lines, start, name)
        result = _calendar_table(scope, work_id, lines, start, next_start, name)
        summary.append({"line": start, "anchor": name, **result})
    empty_day_rows = sum(item["empty"] for item in summary)
    if sum(item["rows"] for item in summary) != 366 or empty_day_rows != 140:
        raise ValueError("LIB-068 calendar day census drifted")
    return {"months": summary, "month_count": len(summary), "day_rows": 366, "empty_day_rows": empty_day_rows}


def _chronology_entry_start(value: str) -> bool:
    # The source line continues with the person/event prose after the date;
    # the anchored expression identifies the date prefix only.
    return _CHRONOLOGY_START_RE.match(value) is not None


def _chronology_list(section: etree._Element, work_id: str, lines: Sequence[str], brace_groups: Sequence[tuple[int, int]]) -> dict[str, Any]:
    head = section.find(_tag("head"))
    if head is None:
        raise ValueError(f"LIB-068 chronology section {section.get('n')} has no heading")
    _, blocks, segments = _extract_body_blocks(section)
    body_numbers = sorted(segments)
    if body_numbers != list(range(body_numbers[0], body_numbers[-1] + 1)):
        raise ValueError("LIB-068 chronology body line sequence is not contiguous")
    listing = etree.Element(_tag("list"), type="chronology-entries", n=section.get("n", ""), **{_XML_ID: f"{work_id}-chronology-list-{section.get('n')}"})
    item_records: list[tuple[etree._Element, set[int]]] = []
    pending_blank: list[int] = []
    current_leading: list[int] = []
    current_numbers: list[int] = []
    current_nodes: list[etree._Element] = []
    current_start: int | None = None
    current_type = "chronology-entry"

    def flush() -> None:
        nonlocal current_leading, current_numbers, current_nodes, current_start, current_type
        if current_start is None:
            return
        item = etree.Element(_tag("item"), ana=current_type, n=str(current_start), **{_XML_ID: f"{work_id}-chronology-item-{current_start}"})
        leading_numbers = set(current_leading)
        if current_leading:
            item.append(_new_whitespace(current_leading, segments, work_id))
        for node in current_nodes:
            item.append(node)
        item_records.append((item, set(current_numbers) | leading_numbers))
        current_leading = []
        current_numbers = []
        current_nodes = []
        current_start = None
        current_type = "chronology-entry"

    number = body_numbers[0]
    while number <= body_numbers[-1]:
        if lines[number - 1] == "":
            run_start = number
            while number <= body_numbers[-1] and lines[number - 1] == "":
                number += 1
            run = list(range(run_start, number))
            # Keep separators pending until the next source item is known.
            # This prevents a brace group's trailing blank from being pulled
            # into that explicit source range.  A final pending run is added
            # after the last item below.
            pending_blank.extend(run)
            continue
        starts = _chronology_entry_start(lines[number - 1])
        label = not starts and current_start is None and not lines[number - 1].startswith((" ", "\t"))
        if starts:
            flush()
            current_start = number
            current_type = "chronology-entry"
            current_leading = pending_blank
            pending_blank = []
        elif label:
            flush()
            current_start = number
            current_type = "chronology-label"
            current_leading = pending_blank
            pending_blank = []
        if current_start is None:
            raise ValueError(f"LIB-068 chronology continuation has no source item at line {number}")
        if current_nodes and current_nodes[-1].tag == _tag("p"):
            previous = _block_numbers(current_nodes[-1])[-1]
            if previous == number - 1:
                _append_seg(current_nodes[-1], segments[number], work_id)
            else:
                current_nodes.append(_new_line_block("p", (number,), segments, work_id, ana=current_type, n=str(current_start)))
        else:
            current_nodes.append(_new_line_block("p", (number,), segments, work_id, ana=current_type, n=str(current_start)))
        current_numbers.append(number)
        number += 1
    flush()
    if pending_blank:
        if not item_records:
            raise ValueError("LIB-068 chronology contains only blank lines")
        item_records[-1][0].append(_new_whitespace(pending_blank, segments, work_id))
        item_records[-1][1].update(pending_blank)
    represented = sorted(number for _, numbers in item_records for number in numbers)
    if represented != body_numbers:
        raise ValueError("LIB-068 chronology item mapping omitted or duplicated source lines")

    # Convert only the explicit brace-bearing source windows into nested lists.
    for group_start, group_end in brace_groups:
        group_numbers = set(range(group_start, group_end + 1))
        selected = [record for record in item_records if (record[1] & group_numbers)]
        selected_nonblank = {
            number
            for _, numbers in selected
            for number in numbers
            if lines[number - 1].strip()
        }
        if not selected or selected_nonblank != group_numbers:
            raise ValueError(f"LIB-068 chronology brace group {group_start}-{group_end} is not source-contiguous")
        selected_indices = [item_records.index(record) for record in selected]
        if selected_indices != list(range(min(selected_indices), max(selected_indices) + 1)):
            raise ValueError(f"LIB-068 chronology brace group {group_start}-{group_end} has a noncontiguous item set")
        group_id = f"{group_start}-{group_end}"
        nested = etree.Element(_tag("list"), type="chronology-brace-entries", n=group_id, **{_XML_ID: f"{work_id}-brace-list-{group_id}"})
        group_item = etree.Element(_tag("item"), ana="brace-group", n=group_id, **{_XML_ID: f"{work_id}-brace-group-{group_id}"})
        for record in selected:
            nested.append(record[0])
        group_item.append(nested)
        first_index = selected_indices[0]
        item_records[first_index:first_index + len(selected)] = [(group_item, set().union(*(record[1] for record in selected)))]
    for item, _ in item_records:
        listing.append(item)
    section.insert(section.index(head) + 1, listing)
    return {"entries": len([item for item, _ in item_records]), "brace_groups": len(brace_groups), "body_lines": len(body_numbers)}


def _apply_chronology(scope: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["chronology"]
    section = _section_node(scope, data["parent"], "chronology")
    _assert_anchor(lines, data["parent"], "CHRONOLOGICAL ARRANGEMENT.")
    heading_numbers = [number for number, value in enumerate(lines, 1) if value.isupper() and value.endswith(("CENTURY.", "CENTURIES."))]
    if len(heading_numbers) != data["heading_count"]:
        raise ValueError("LIB-068 chronology heading census drifted")
    century_nodes = [child for child in section if child.tag == _tag("div") and child.get("type") == "century"]
    if len(century_nodes) != data["heading_count"]:
        raise ValueError("LIB-068 chronology profile/tree section count drifted")
    summaries = []
    for node in century_nodes:
        summaries.append(_chronology_list(node, work_id, lines, [group for group in data["brace_groups"] if any(group[0] <= n <= group[1] for n in _block_numbers(node))]))
    # The independent source census counts dated starts, rather than list
    # wrappers.  Repeated month-only dates are intentionally retained.
    source_entries = sum(
        1
        for number in range(11157, 11640)
        if lines[number - 1] and _chronology_entry_start(lines[number - 1])
    )
    if source_entries != data["entry_count"]:
        raise ValueError("LIB-068 chronology dated-entry census drifted")
    return {"heading_count": len(century_nodes), "dated_entry_count": source_entries, "brace_groups": len(data["brace_groups"]), "sections": summaries}


def _make_column_table(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    start: int,
    end: int,
    parent: etree._Element,
    table_type: str,
    table_id: str,
    header: int | None = None,
) -> dict[str, Any]:
    actual_parent, index, _, segments = _extract_range(scope, start if header is None else header, end)
    if actual_parent is not parent:
        raise ValueError(f"LIB-068 {table_type} source blocks escaped parent section")
    table = etree.Element(_tag("table"), type=table_type, n=str(start), **{_XML_ID: table_id})
    if header is not None:
        heading = etree.SubElement(table, _tag("head"))
        _append_seg(heading, segments[header], work_id)
    row_numbers = [number for number in range(start, end + 1) if number != header]
    page_values: dict[int, str] = {}
    for number in row_numbers:
        boundary, page_value = _fixed_page_span(lines[number - 1], number)
        page_values[number] = page_value
        row = etree.SubElement(table, _tag("row"), n=str(number), **{_XML_ID: f"{table_id}-row-{number}"})
        raw = lines[number - 1]
        fragments = _split_source_segment(
            segments[number],
            work_id,
            number,
            raw,
            (("date", 0, boundary), ("page", boundary, len(raw))),
            table_type,
        )
        date_fragments = [fragment for fragment in fragments if "-date-" in fragment.get("function", "")]
        page_fragments = [fragment for fragment in fragments if "-page-" in fragment.get("function", "")]
        _append_fragment_cell(row, "date", work_id, (number,), date_fragments)
        _append_fragment_cell(row, "page", work_id, (number,), page_fragments, n=page_value)
    _insert(actual_parent, index, (table,))
    return {"rows": len(row_numbers), "header": header, "page_values": page_values}


def _apply_supplement_i(scope: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["supplement_i"]
    parent = _section_node(scope, data["parent"], "supplement-section")
    _assert_anchor(lines, data["header"], re.compile(r"^\s+PAGE$"))
    result = _make_column_table(scope, work_id, lines, data["start"], data["end"], parent, "supplement-date-page", f"{work_id}-supplement-i", data["header"])
    if result["rows"] != data["row_count"]:
        raise ValueError("LIB-068 Supplement I row census drifted")
    return result


def _block_groups(blocks: Sequence[etree._Element]) -> list[tuple[etree._Element, list[etree._Element], list[int]]]:
    groups: list[tuple[etree._Element, list[etree._Element], list[int]]] = []
    current: tuple[etree._Element, list[etree._Element], list[int]] | None = None
    for block in blocks:
        if block.tag == _tag("p"):
            current = (block, [block], _block_numbers(block))
            groups.append(current)
        elif current is not None:
            current[1].append(block)
            current[2].extend(_block_numbers(block))
        else:
            groups.append((block, [block], _block_numbers(block)))
    return groups


def _bibliography_subitems(item: etree._Element, source_lines: Sequence[str], segments: Mapping[int, etree._Element], work_id: str, numbers: Sequence[int]) -> None:
    markers: list[tuple[str, int]] = []
    first = True
    for line_number in numbers:
        value = source_lines[line_number - 1]
        matches = list(re.finditer(r"(?<![\w])(?P<number>\d+)\.(?=\s|$)", value))
        for match in matches:
            if first:
                first = False
                continue
            markers.append((match.group("number"), line_number))
        first = False
    if not markers:
        return
    nested = etree.SubElement(item, _tag("list"), type="bibliography-subitems", **{_XML_ID: f"{work_id}-bibliography-subitems-{numbers[0]}"})
    for marker, line_number in markers:
        etree.SubElement(nested, _tag("item"), n=marker, corresp=f"#{_line_id(work_id, line_number)}")


def _bibliography_category(category: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    head = category.find(_tag("head"))
    if head is None:
        raise ValueError(f"LIB-068 bibliography category {category.get('n')} has no heading")
    _, blocks, segments = _extract_body_blocks(category)
    listing = etree.Element(_tag("list"), type="bibliography", n=category.get("n", ""), **{_XML_ID: f"{work_id}-bibliography-list-{category.get('n')}"})
    groups = _block_groups(blocks)
    item_count = 0
    nested_count = 0
    for first_block, group, source_numbers in groups:
        if not source_numbers:
            continue
        if first_block.tag != _tag("p"):
            # Leading/trailing whitespace is retained with the adjacent item
            # below; it is never silently dropped.
            if len(listing):
                listing[-1].append(first_block)
            else:
                item = etree.SubElement(listing, _tag("item"), ana="source-whitespace", n=str(source_numbers[0]))
                item.append(first_block)
            continue
        first_value = lines[source_numbers[0] - 1]
        match = _BIB_NUMBER_RE.match(first_value)
        attrs: dict[str, str] = {"ana": "bibliography-item", _XML_ID: f"{work_id}-bibliography-item-{source_numbers[0]}"}
        if match:
            attrs["n"] = match.group(1).replace(" ", "")
        item = etree.Element(_tag("item"), **attrs)
        for block in group:
            if block.tag == _tag("p"):
                for seg in list(block.iter(_tag("seg"))):
                    item_p = item.find(_tag("p"))
                    if item_p is None:
                        item_p = etree.SubElement(item, _tag("p"), ana="bibliography-source")
                    _append_seg(item_p, seg, work_id)
                # The original block has no non-seg content; its identity is
                # retained by the moved line carriers.
            else:
                item.append(block)
        _bibliography_subitems(item, lines, segments, work_id, source_numbers)
        listing.append(item)
        item_count += 1
        nested_count += len(item.findall(f".//{_tag('list')}[@type='bibliography-subitems']/{_tag('item')}"))
    category.insert(category.index(head) + 1, listing)
    return {"items": item_count, "nested_items": nested_count}


def _apply_bibliography(scope: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["bibliography"]
    parent = _section_node(scope, data["parent"], "supplement-section")
    categories = [_section_node(scope, number, "bibliography-category") for number in data["categories"]]
    summaries = [_bibliography_category(category, work_id, lines) for category in categories]
    return {"category_count": len(summaries), "categories": summaries}


def _list_from_groups(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    parent: etree._Element,
    start: int,
    end: int,
    list_type: str,
    list_id: str,
    item_kind: str,
    page_from_last_line: bool = False,
) -> dict[str, Any]:
    actual_parent, index, blocks, segments = _extract_range(scope, start, end)
    if actual_parent is not parent:
        raise ValueError(f"LIB-068 {list_type} source blocks escaped parent section")
    listing = etree.Element(_tag("list"), type=list_type, n=str(start), **{_XML_ID: list_id})
    groups = _block_groups(blocks)
    item_count = 0
    for first_block, group, source_numbers in groups:
        if first_block.tag != _tag("p"):
            if len(listing):
                listing[-1].append(first_block)
            else:
                item = etree.SubElement(listing, _tag("item"), ana="source-whitespace", n=str(source_numbers[0]) if source_numbers else "0")
                item.append(first_block)
            continue
        first_value = lines[source_numbers[0] - 1]
        station_match = number_match = re.match(r"^\s*(\d+)\.\s+", first_value) if page_from_last_line else None
        number_match = number_match or re.match(r"^\s*(\d+)\.\s+", first_value)
        attrs: dict[str, str] = {"ana": item_kind, _XML_ID: f"{list_id}-item-{item_count + 1}"}
        if number_match:
            attrs["n"] = number_match.group(1)
        item = etree.Element(_tag("item"), **attrs)
        if station_match:
            source_text_numbers = [source_number for source_number in source_numbers if lines[source_number - 1].strip()]
            if not source_text_numbers:
                raise ValueError(f"LIB-068 station item has no text at line {source_numbers[0]}")
            attrs_page = re.search(r"(\d+)\s*$", lines[source_text_numbers[-1] - 1])
            if attrs_page is None:
                raise ValueError(f"LIB-068 station page drift at line {source_text_numbers[-1]}")
            etree.SubElement(item, _tag("label"), n=attrs_page.group(1))
        for block in group:
            if block.tag == _tag("p"):
                item.append(block)
            else:
                item.append(block)
        listing.append(item)
        item_count += 1
    _insert(actual_parent, index, (listing,))
    return {"items": item_count, "source_lines": end - start + 1}


def _apply_components(scope: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    data = SPECIAL_SOURCE_INVENTORY[DONNE]["components"]
    parent = _section_node(scope, data["parent"], "devotions-title-page")
    for line in data["items"]:
        _assert_anchor(lines, line, re.compile(r"^\s*[123]\." + r".*$"))
    result = _list_from_groups(scope, work_id, lines, parent, data["start"], data["end"], "devotional-components", f"{work_id}-components", "component")
    if result["items"] != 3:
        raise ValueError("LIB-068 Donne component list census drifted")
    return result


def _apply_station_contents(scope: etree._Element, work_id: str, lines: Sequence[str]) -> dict[str, Any]:
    data = SPECIAL_SOURCE_INVENTORY[DONNE]["station_contents"]
    parent = _section_node(scope, data["parent"], "station-contents")
    entries = [number for number in range(data["start"], 1604) if re.match(r"^\s*\d+\.\s+", lines[number - 1])]
    if [int(re.match(r"^\s*(\d+)", lines[number - 1]).group(1)) for number in entries] != list(range(1, 24)):
        raise ValueError("LIB-068 Donne station contents source census drifted")
    result = _list_from_groups(scope, work_id, lines, parent, data["start"], data["end"], "station-contents", f"{work_id}-station-contents-list", "station", True)
    if result["items"] != data["item_count"]:
        raise ValueError("LIB-068 Donne station contents item census drifted")
    return {**result, "numbered_entries": len(entries)}


def _mutation_challenges(work_id: str) -> list[dict[str, str]]:
    common = [
        {"id": f"{work_id}-drop-special-line", "mutation": "remove one source-line seg from a verse/list/table block", "expected": "reject"},
        {"id": f"{work_id}-move-special-line", "mutation": "move a source-line carrier to an adjacent special block", "expected": "reject"},
        {"id": f"{work_id}-wrong-line-corresp", "mutation": "change a source-line cell, figure, or list corresp target", "expected": "reject"},
        {"id": f"{work_id}-invent-special-wrapper", "mutation": "add an unpinned special wrapper or source range", "expected": "reject"},
    ]
    if work_id == NEWMAN:
        common.extend(
            [
                {"id": f"{work_id}-drop-empty-calendar-day", "mutation": "remove an empty calendar day row", "expected": "reject"},
                {"id": f"{work_id}-merge-brace-groups", "mutation": "merge two explicit chronology brace groups", "expected": "reject"},
            ]
        )
    else:
        common.extend(
            [
                {"id": f"{work_id}-drop-illustration-marker", "mutation": "remove an explicit [Illustration] marker relationship", "expected": "reject"},
                {"id": f"{work_id}-change-station-page", "mutation": "change a station contents label page value", "expected": "reject"},
            ]
        )
    return common


def inventory_summary(work_id: str, lines: Sequence[str], profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return source-derived counts for the producer receipt."""
    pin = _validate_source(work_id, lines)
    if profile is not None:
        _profile_rows(profile)
    data = SPECIAL_SOURCE_INVENTORY[work_id]
    summary: dict[str, Any] = {
        "work_id": work_id,
        "source_path": pin["source_path"],
        "source_sha256": pin["source_sha256"],
        "source_line_count": pin["line_count"],
        "blank_line_count": pin["blank_count"],
        "special_blocks": {},
        "mutation_challenges": _mutation_challenges(work_id),
    }
    summary["special_blocks"]["verse"] = [
        {"id": spec["id"], "start": spec["start"], "end": spec["end"], "stanzas": len(spec["stanzas"]), "illustrations": len(spec["illustrations"])}
        for spec in data["verse"]
    ]
    if work_id == NEWMAN:
        summary["special_blocks"].update(
            {
                "calendar": {"months": 12, "day_rows": 366, "empty_day_rows": 140},
                "chronology": {"headings": 34, "dated_entries": 300, "brace_groups": len(data["chronology"]["brace_groups"])},
                "supplement_i": {"rows": 75},
                "bibliography": {"categories": 7},
            }
        )
    else:
        summary["special_blocks"].update(
            {
                "components": {"items": 3},
                "station_contents": {"items": 23},
            }
        )
    return summary


def apply_blocks(scope: etree._Element, work_id: str, lines: Sequence[str], profile: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the pinned literary transformations to ``scope`` in place."""
    _validate_source(work_id, lines)
    _profile_rows(profile)
    own_markers = {
        _tag("quote"): {"source-verse"},
        _tag("table"): {"calendar", "supplement-date-page"},
        _tag("list"): {"chronology-entries", "bibliography", "devotional-components", "station-contents"},
    }
    if any(node.get("type") in own_markers.get(node.tag, set()) for node in scope.iter()):
        raise ValueError("LIB-068 literary special blocks are already present; apply only to the baseline tree")
    for spec in SPECIAL_SOURCE_INVENTORY[work_id]["verse"]:
        _verse_quote(scope, work_id, lines, spec)
    result: dict[str, Any] = inventory_summary(work_id, lines, profile)
    if work_id == NEWMAN:
        result["applied"] = {
            "calendar": _apply_calendar(scope, work_id, lines),
            "chronology": _apply_chronology(scope, work_id, lines),
            "supplement_i": _apply_supplement_i(scope, work_id, lines),
            "bibliography": _apply_bibliography(scope, work_id, lines),
        }
    else:
        result["applied"] = {
            "components": _apply_components(scope, work_id, lines),
            "station_contents": _apply_station_contents(scope, work_id, lines),
        }
    # Reparenting strips a carrier's former tail. Restore physical line breaks
    # wherever successive carriers now share a readable text block. Two column
    # fragments from the same physical line must remain contiguous.
    for parent in scope.iter():
        if parent.tag not in {_tag("p"), _tag("ab"), _tag("cell")}:
            continue
        for left, right in zip(parent, list(parent)[1:]):
            if all(node.tag == _tag("seg") and node.get("type") in {"source-line", "source-line-fragment"} for node in (left, right)):
                left.tail = "\n" if left.get("n") != right.get("n") else None
    result["status"] = "applied"
    return result
