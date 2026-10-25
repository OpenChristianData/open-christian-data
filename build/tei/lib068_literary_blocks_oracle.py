"""Independent checker and source-line normalizer for LIB-068 literary blocks.

The block producer is allowed to expose useful native TEI structures while a
candidate is being reviewed.  The base LIB-068 oracle, however, checks the
source-located ``div``/``head``/``p``/``ab``/``note`` floor.  This module checks
the actual native structures against the retained source first, then returns a
clone with those structures removed and their checked carriers restored to the
floor.  It deliberately has no producer import and never calls a producer to
construct an expected tree.

Table cells use the declared ``function=source-column-*-start-end``
interface.  The range is an exact half-open character span of the retained
physical line.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
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


# These are source pins, not a retained-source store.  ``lines`` is the exact
# list supplied by the LIB-068 loader, including its BOM-bearing first line
# and terminal empty split line.
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


# Inclusive source coordinates.  The inventory is deliberately explicit for
# special ranges; anchors, row counts, and item starts are independently
# derived from ``lines`` below before any actual node is accepted.
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
            "brace_groups": [(11231, 11235), (11337, 11341), (11345, 11347), (11390, 11394), (11390, 11398), (11399, 11408)],
        },
        "supplement_i": {
            "parent": 12385,
            "header": 12389,
            "start": 12390,
            "end": 12464,
            "row_count": 75,
        },
        "bibliography": {
            "parent": 12469,
            "categories": (12476, 12489, 12500, 12519, 12528, 12540, 12556),
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
_STATION_NUMBER_RE = re.compile(r"^\s*(\d+)\.\s+")


def _tag(name: str) -> str:
    return f"{_T}{name}"


def _fail(message: str) -> None:
    raise ValueError(f"LIB-068 {message}")


def _validate_source(work_id: str, lines: Sequence[str]) -> None:
    if work_id not in SUPPORTED_WORKS:
        _fail(f"literary blocks do not support {work_id!r}")
    pin = SOURCE_PINS[work_id]
    if not isinstance(lines, Sequence) or any(not isinstance(line, str) for line in lines):
        _fail("source lines are invalid")
    if len(lines) != pin["line_count"] or sum(line == "" for line in lines) != pin["blank_count"]:
        _fail(f"{work_id} source line census drifted")
    actual = hashlib.sha256(pin["newline"].join(lines).encode("utf-8")).hexdigest()
    if actual != pin["source_sha256"]:
        _fail(f"{work_id} source bytes drifted")
    if not lines or lines[-1] != "":
        _fail(f"{work_id} source terminal split line drifted")


def _profile_rows(profile: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = profile.get("literary_sections")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, Mapping) for row in rows):
        _fail("literary profile rows are absent or invalid")
    starts = [int(row["line"]) for row in rows]
    if starts != sorted(set(starts)) or starts[0] != 1:
        _fail("literary profile order drifted")
    return rows


def _section(scope: etree._Element, number: int, kind: str | None = None) -> etree._Element:
    nodes = [node for node in scope.iter(_tag("div")) if node.get("n") == str(number)]
    if kind is not None:
        nodes = [node for node in nodes if node.get("type") == kind]
    if len(nodes) != 1:
        _fail(f"expected one section {kind or ''} at line {number}, found {len(nodes)}")
    return nodes[0]


def _line_id(work_id: str, number: int) -> str:
    return f"{work_id}-line-{number}"


def _optional_line_id(node: etree._Element, work_id: str, number: int, label: str) -> None:
    attrs = set(node.attrib)
    if attrs - {"type", "n", _XML_ID}:
        _fail(f"{label} {number} has unrelated attributes")
    if node.get(_XML_ID) not in (None, _line_id(work_id, number)):
        _fail(f"{label} {number} has an unrelated XML ID")


class _Carriers:
    """Indexes actual source-line and source-line-fragment nodes."""

    def __init__(self, scope: etree._Element, lines: Sequence[str], work_id: str) -> None:
        self.lines = lines
        self.work_id = work_id
        self.regular: dict[int, etree._Element] = {}
        self.fragments: dict[int, list[etree._Element]] = {}
        self.fragment_nodes: set[int] = set()
        self._scan(scope)

    def _scan(self, scope: etree._Element) -> None:
        ids: set[str] = set()
        for node in scope.iter(_tag("seg")):
            carrier_type = node.get("type")
            if carrier_type not in {"source-line", "source-line-fragment"}:
                continue
            raw_number = node.get("n")
            try:
                number = int(raw_number) if raw_number is not None else -1
            except (TypeError, ValueError):
                _fail("source carrier has an invalid line number")
            if number < 1 or number > len(self.lines):
                _fail(f"source carrier line {number} is outside retained source")
            following = node.getnext()
            if node.getparent().tag in {_tag("p"), _tag("ab"), _tag("cell")} and following is not None and following.tag == _tag("seg") and following.get("type") in {"source-line", "source-line-fragment"}:
                separator = "\n" if following.get("n") != raw_number else ""
                if (node.tail or "") != separator:
                    _fail(f"source physical-line separator drifted after {number}")
            if carrier_type == "source-line":
                if number in self.regular:
                    _fail(f"duplicate source-line carrier {number}")
                _optional_line_id(node, self.work_id, number, "source-line")
                if "".join(node.itertext()) != self.lines[number - 1]:
                    _fail(f"source-line {number} text drifted")
                xml_id = node.get(_XML_ID)
                if xml_id is not None:
                    if xml_id in ids:
                        _fail("duplicate source carrier XML ID")
                    ids.add(xml_id)
                self.regular[number] = node
            else:
                if number in self.regular:
                    _fail(f"source-line {number} is both whole and fragmented")
                xml_id = node.get(_XML_ID)
                if xml_id is not None:
                    if xml_id in ids:
                        _fail("duplicate source carrier XML ID")
                    ids.add(xml_id)
                self.fragments.setdefault(number, []).append(node)
                self.fragment_nodes.add(id(node))

    def record_regular(self, number: int, node: etree._Element, seen: set[int]) -> None:
        if self.regular.get(number) is not node:
            _fail(f"actual source-line carrier mismatch at {number}")
        if number in seen:
            _fail(f"source-line {number} is attached to multiple special structures")
        seen.add(number)

    def record_fragments(self, numbers: Iterable[int], nodes: Iterable[etree._Element], seen: set[int]) -> None:
        expected_nodes = {id(node) for number in numbers for node in self.fragments.get(number, ())}
        for node in nodes:
            if id(node) not in expected_nodes:
                _fail("table contains an unindexed source-line fragment")
            if id(node) in seen:
                _fail("source-line fragment is attached to multiple table cells")
            seen.add(id(node))

    def materialize(self, number: int) -> etree._Element:
        if number in self.regular:
            return self.regular[number]
        fragments = self.fragments.get(number)
        if not fragments:
            _fail(f"source line {number} has no actual carrier")
        spans = [_fragment_span(fragment, self.lines, self.work_id) for fragment in fragments]
        spans.sort(key=lambda item: (item[1], item[2]))
        cursor = 0
        for _, start, end, _ in spans:
            if start != cursor:
                _fail(f"source-line fragments leave a gap or overlap at {number}")
            cursor = end
        if cursor != len(self.lines[number - 1]):
            _fail(f"source-line fragments do not cover line {number}")
        merged = etree.Element(_tag("seg"), type="source-line", n=str(number))
        for fragment, _, _, _ in spans:
            _append_mixed(merged, fragment)
        if "".join(merged.itertext()) != self.lines[number - 1]:
            _fail(f"merged source-line fragments changed line {number}")
        return merged


def _append_mixed(parent: etree._Element, source: etree._Element) -> None:
    """Copy mixed content without flattening actual inline children."""

    if source.text:
        if len(parent):
            parent[-1].tail = (parent[-1].tail or "") + source.text
        else:
            parent.text = (parent.text or "") + source.text
    for child in source:
        copied = deepcopy(child)
        tail = copied.tail or ""
        copied.tail = None
        # A column boundary can split one source emphasis span.  The producer
        # emits two adjacent ``hi`` fragments; joining only those equal
        # emphasis nodes recreates the source-line inline carrier while
        # retaining every actual child and its attributes.  References remain
        # separate because adjacent equal references can be distinct markers.
        if (
            copied.tag == _tag("hi")
            and len(parent)
            and parent[-1].tag == copied.tag
            and dict(parent[-1].attrib) == dict(copied.attrib)
            and not parent[-1].tail
        ):
            _append_mixed(parent[-1], copied)
        else:
            parent.append(copied)
        if tail:
            if len(parent):
                parent[-1].tail = (parent[-1].tail or "") + tail
            else:
                parent.text = (parent.text or "") + tail


def _fragment_span(
    fragment: etree._Element,
    lines: Sequence[str],
    work_id: str,
) -> tuple[etree._Element, int, int, str]:
    if fragment.tag != _tag("seg") or fragment.get("type") != "source-line-fragment":
        _fail("table contains a non-fragment carrier")
    number = int(fragment.get("n", "-1"))
    if number < 1 or number > len(lines):
        _fail("source-line fragment line is outside retained source")
    ana = fragment.get("ana")
    if not ana:
        _fail(f"source-line fragment {number} has no column role")
    function = fragment.get("function")
    column: str | None = None
    start: int | None = None
    end: int | None = None
    if function is None:
        _fail(f"source-line fragment {number} has no exact source function")
    match = re.fullmatch(r"source-column-(?P<column>[A-Za-z0-9_-]+)-(?P<start>\d+)-(?P<end>\d+)", function)
    if match is None:
        _fail(f"source-line fragment {number} function range is invalid")
    column, start, end = match.group("column"), int(match.group("start")), int(match.group("end"))
    expected_column = {
        "calendar-day": "day",
        "calendar-observance": "observance",
        "supplement-date-page-date": "date",
        "supplement-date-page-page": "page",
    }.get(ana)
    if expected_column is None or column != expected_column:
        _fail(f"source-line fragment {number} column role disagrees with its carrier role")
    if start < 0 or end <= start or end > len(lines[number - 1]):
        _fail(f"source-line fragment {number} range is outside its source line")
    allowed = {"type", "n", "part", "ana", "function", _XML_ID, "corresp"}
    if set(fragment.attrib) - allowed:
        _fail(f"source-line fragment {number} has unrelated attributes")
    expected_id = _line_id(work_id, number)
    xml_id = fragment.get(_XML_ID)
    if xml_id not in (expected_id,) and not (xml_id and xml_id.startswith(expected_id + "-fragment-")):
        _fail(f"source-line fragment {number} has an unrelated XML ID")
    if xml_id == expected_id:
        if fragment.get("corresp") is not None:
            _fail(f"first source-line fragment {number} has an unexpected corresp")
    elif fragment.get("corresp") != f"#{expected_id}":
        _fail(f"source-line fragment {number} has an invalid corresp")
    if "".join(fragment.itertext()) != lines[number - 1][start:end]:
        _fail(f"source-line fragment changed source text at {number}")
    following = fragment.getnext()
    expected_tail = "\n" if following is not None and following.tag == _tag("seg") and following.get("n") != fragment.get("n") else ""
    if (fragment.tail or "") != expected_tail:
        _fail(f"source-line fragment {number} has an unexpected tail")
    return fragment, start, end, column


def _check_fragment_cell(
    cell: etree._Element,
    work_id: str,
    lines: Sequence[str],
    expected_role: str,
    expected_numbers: Sequence[int],
    spans: Sequence[tuple[int, str, int, int]],
    carriers: _Carriers,
    seen_fragments: set[int],
) -> None:
    expected_attrs = {"role": expected_role, "corresp": " ".join(dict.fromkeys(f"#{_line_id(work_id, n)}" for n in expected_numbers))}
    if expected_role == "day":
        expected_attrs["n"] = str(int(_MONTH_RE.fullmatch(lines[expected_numbers[0] - 1]).group(1)))
    elif expected_role == "observance":
        expected_attrs["n"] = "present"
    if expected_role == "page":
        expected_attrs["n"] = re.search(r"(\d+)\s*$", lines[expected_numbers[0] - 1]).group(1)
    if dict(cell.attrib) != expected_attrs or cell.text or cell.tail or len(cell) != 1 or cell[0].tag != _tag("p"):
        _fail(f"{expected_role} table cell layout drifted")
    paragraph = cell[0]
    if paragraph.attrib or paragraph.text or paragraph.tail:
        _fail(f"{expected_role} table cell paragraph drifted")
    actual = list(paragraph)
    if len(actual) != len(spans):
        _fail(f"{expected_role} table cell fragment count drifted")
    actual_spans: list[tuple[etree._Element, int, int, str]] = []
    for fragment in actual:
        actual_spans.append(_fragment_span(fragment, lines, work_id))
    expected = [(number, column, start, end) for number, column, start, end in spans]
    observed = [(int(fragment.get("n")), column, start, end) for fragment, start, end, column in actual_spans]
    if observed != expected:
        _fail(f"{expected_role} table cell source ranges drifted")
    carriers.record_fragments(expected_numbers, actual, seen_fragments)


def _check_fragment_parts(
    fragments: Iterable[etree._Element],
    lines: Sequence[str],
    work_id: str,
) -> None:
    by_line: dict[int, list[tuple[etree._Element, int, int, str]]] = {}
    for fragment in fragments:
        item = _fragment_span(fragment, lines, work_id)
        by_line.setdefault(int(fragment.get("n")), []).append(item)
    for number, entries in by_line.items():
        ordered = sorted(entries, key=lambda item: (item[1], item[2]))
        parts = [fragment.get("part") for fragment, *_ in ordered]
        expected_parts = ["N"] if len(ordered) == 1 else ["I"] + ["M"] * (len(ordered) - 2) + ["F"]
        if parts != expected_parts:
            _fail(f"source-line fragment part order drifted at {number}")
        cursor = 0
        for _, start, end, _ in ordered:
            if start != cursor:
                _fail(f"source-line fragment offsets overlap at {number}")
            cursor = end
        if cursor != len(lines[number - 1]):
            _fail(f"source-line fragments do not cover line {number}")
        for index, (fragment, _, _, column) in enumerate(ordered):
            expected_id = _line_id(work_id, number) if index == 0 else f"{_line_id(work_id, number)}-fragment-{column}"
            if fragment.get(_XML_ID) != expected_id:
                _fail(f"source-line fragment XML ID drifted at {number}")


def _source_seg(
    node: etree._Element,
    number: int,
    lines: Sequence[str],
    carriers: _Carriers,
    seen: set[int],
) -> None:
    if node.tag != _tag("seg") or node.get("type") != "source-line" or node.get("n") != str(number):
        _fail(f"source-line carrier identity drifted at {number}")
    _optional_line_id(node, carriers.work_id, number, "source-line")
    if "".join(node.itertext()) != lines[number - 1]:
        _fail(f"source-line {number} text drifted")
    carriers.record_regular(number, node, seen)


def _container(node: etree._Element, label: str, expected_attrs: Mapping[str, str]) -> None:
    if dict(node.attrib) != dict(expected_attrs) or node.text or node.tail:
        _fail(f"{label} identity or text drifted")


def _verify_verse(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    spec: Mapping[str, Any],
    carriers: _Carriers,
    seen: set[int],
) -> set[int]:
    parent = _section(scope, int(spec["parent"]))
    quotes = [node for node in parent if node.tag == _tag("quote") and node.get("n") == str(spec["start"])]
    if len(quotes) != 1:
        _fail(f"verse quote census drifted at {spec['start']}")
    quote = quotes[0]
    _container(quote, "source verse", {"type": "source-verse", "n": str(spec["start"]), _XML_ID: f"{work_id}-{spec['id']}"})
    titles = set(spec["titles"])
    attributions = set(spec["attributions"])
    illustrations = set(spec["illustrations"])
    stanza_by_line = {n: (a, b) for a, b in spec["stanzas"] for n in range(a, b + 1)}
    expected = set(range(spec["start"], spec["end"] + 1))
    assigned: set[int] = set()
    cursor = int(spec["start"])
    skip_marker = False
    for child in quote:
        if skip_marker:
            skip_marker = False
            continue
        if child.tag == _tag("ab") and child.get("type") == "source-whitespace":
            if child.attrib != {"type": "source-whitespace"} or child.text or child.tail:
                _fail("verse whitespace carrier drifted")
            numbers: list[int] = []
            for seg in child:
                number = int(seg.get("n", "-1"))
                if lines[number - 1].strip():
                    _fail("verse whitespace contains nonblank source")
                _source_seg(seg, number, lines, carriers, seen)
                numbers.append(number)
            if numbers != list(range(cursor, cursor + len(numbers))) or not numbers:
                _fail("verse whitespace range drifted")
            assigned.update(numbers)
            cursor += len(numbers)
            continue
        number = cursor
        if number in illustrations:
            expected_id = f"{work_id}-illustration-{number}"
            if child.tag != _tag("figure") or dict(child.attrib) != {"type": "source-illustration-placeholder", "n": str(number), "corresp": f"#{_line_id(work_id, number)}", _XML_ID: expected_id} or child.text or child.tail or len(child) != 1:
                _fail(f"verse illustration placeholder drifted at {number}")
            desc = child[0]
            if desc.tag != _tag("figDesc") or desc.attrib or desc.text or desc.tail:
                _fail(f"verse illustration description drifted at {number}")
            assigned.add(number)
            marker = quote[quote.index(child) + 1] if quote.index(child) + 1 < len(quote) else None
            if marker is None or dict(marker.attrib) != {"ana": "source-illustration-marker", "corresp": f"#{expected_id}"} or marker.tag != _tag("p") or marker.text or marker.tail or len(marker) != 1:
                _fail(f"verse illustration marker drifted at {number}")
            _source_seg(marker[0], number, lines, carriers, seen)
            skip_marker = True
            cursor += 1
            continue
        if number in titles or number in attributions:
            ana = "source-verse-title" if number in titles else "source-attribution"
            attrs = {"ana": ana, "n": str(number)}
            if child.tag != _tag("p") or dict(child.attrib) != attrs or child.text or child.tail or len(child) != 1:
                _fail(f"verse labelled line drifted at {number}")
            _source_seg(child[0], number, lines, carriers, seen)
            assigned.add(number)
            cursor += 1
            continue
        stanza = stanza_by_line.get(number)
        if stanza is None or number != stanza[0] or child.tag != _tag("lg") or dict(child.attrib) != {"type": "stanza", "n": str(number)} or child.text or child.tail:
            _fail(f"verse stanza boundary drifted at {number}")
        first, last = stanza
        if len(child) != last - first + 1:
            _fail(f"verse stanza line count drifted at {number}")
        for line_number, verse_line in zip(range(first, last + 1), child, strict=True):
            if verse_line.tag != _tag("l") or dict(verse_line.attrib) != {"n": str(line_number)} or verse_line.text or verse_line.tail or len(verse_line) != 1:
                _fail(f"verse line carrier drifted at {line_number}")
            _source_seg(verse_line[0], line_number, lines, carriers, seen)
            assigned.add(line_number)
        cursor = last + 1
    if assigned != expected:
        _fail(f"verse range omitted or duplicated at {spec['start']}")
    return assigned


def _calendar_ranges(lines: Sequence[str], start: int, next_start: int) -> list[tuple[int, int]]:
    starts = [n for n in range(start + 1, next_start) if _MONTH_RE.fullmatch(lines[n - 1])]
    if not starts:
        _fail(f"calendar month at {start} has no day rows")
    result: list[tuple[int, int]] = []
    for index, first in enumerate(starts):
        boundary = starts[index + 1] if index + 1 < len(starts) else next_start
        end = boundary - 1
        blanks = [n for n in range(first, boundary) if not lines[n - 1].strip()]
        if blanks:
            if index + 1 < len(starts):
                _fail(f"calendar row has an unexpected blank at line {blanks[0]}")
            end = blanks[0] - 1
        if end < first or any(not lines[n - 1].strip() for n in range(first, end + 1)):
            _fail(f"calendar row at {first} contains a blank")
        result.append((first, end))
    return result


def _fixed_page_span(line: str, number: int) -> tuple[int, str]:
    if len(line) != 31:
        _fail(f"Supplement I line {number} is not the pinned 31-column width")
    match = re.search(r"(\d+)\s*$", line)
    if match is None or match.end() != len(line) or not 1 <= len(match.group(1)) <= 3:
        _fail(f"Supplement I page column drift at line {number}")
    if line[27:].strip() != match.group(1) or not line[27:].strip().isdigit():
        _fail(f"Supplement I fixed page column drift at line {number}")
    return 27, match.group(1)


def _verify_calendar(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    carriers: _Carriers,
    seen: set[int],
    seen_fragments: set[int],
) -> set[int]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["calendar"]
    _section(scope, data["parent"], "calendar")
    expected_numbers: set[int] = set()
    months = data["months"]
    if len(months) != 12:
        _fail("calendar month inventory drifted")
    observed_rows = 0
    empty_rows = 0
    for index, (month_start, month_name) in enumerate(months):
        if lines[month_start - 1] != month_name:
            _fail(f"calendar month anchor drifted at {month_start}")
        month = _section(scope, month_start, "month")
        next_start = months[index + 1][0] if index + 1 < len(months) else 11155
        ranges = _calendar_ranges(lines, month_start, next_start)
        tables = [node for node in month if node.tag == _tag("table") and node.get("type") == "calendar" and node.get("n") == str(month_start)]
        if len(tables) != 1:
            _fail(f"calendar table census drifted for {month_name}")
        table = tables[0]
        _container(table, "calendar table", {"type": "calendar", "n": str(month_start), _XML_ID: f"{work_id}-calendar-{month_start}"})
        # The table's n is the month heading line, while its first row n is
        # the first source day line.
        if table.get("n") != str(month_start) or len(table) != len(ranges):
            _fail(f"calendar table range drifted for {month_name}")
        expected_day = 1
        for row, (row_start, row_end) in zip(table, ranges, strict=True):
            if row.tag != _tag("row") or dict(row.attrib) != {"n": str(row_start), _XML_ID: f"{work_id}-calendar-row-{row_start}"} or row.text or row.tail:
                _fail(f"calendar row identity drifted at {row_start}")
            match = _MONTH_RE.fullmatch(lines[row_start - 1])
            if match is None or int(match.group(1)) != expected_day:
                _fail(f"calendar day sequence drifted at {row_start}")
            description = (match.group(2) or "").strip()
            expected_day += 1
            observed_rows += 1
            if description:
                expected_observance = [(row_start, "observance", 2, len(lines[row_start - 1]))]
                expected_observance.extend((n, "observance", 0, len(lines[n - 1])) for n in range(row_start + 1, row_end + 1))
                if len(row) != 2:
                    _fail(f"calendar observance cell missing at {row_start}")
            else:
                expected_observance = []
                empty_rows += 1
                if len(row) != 1:
                    _fail(f"empty calendar row has an observance cell at {row_start}")
            expected_day_spans = [(row_start, "day", 0, 2)]
            _check_fragment_cell(row[0], work_id, lines, "day", [row_start], expected_day_spans, carriers, seen_fragments)
            if expected_observance:
                _check_fragment_cell(row[1], work_id, lines, "observance", list(range(row_start, row_end + 1)), expected_observance, carriers, seen_fragments)
            expected_numbers.update(range(row_start, row_end + 1))
    if observed_rows != 366 or empty_rows != 140:
        _fail("calendar day census drifted")
    all_fragments = [node for nodes in carriers.fragments.values() for node in nodes]
    _check_fragment_parts(all_fragments, lines, work_id)
    return expected_numbers


def _profile_bounds(rows: Sequence[Mapping[str, Any]], row: Mapping[str, Any], total: int) -> tuple[int, int]:
    index = rows.index(row)
    depth = int(row["depth"])
    for later in rows[index + 1 :]:
        if int(later["depth"]) <= depth:
            return int(row["head_end"]) + 1, int(later["line"])
    return int(row["head_end"]) + 1, total + 1


def _verify_head(section: etree._Element, line: int, lines: Sequence[str]) -> etree._Element:
    heads = [node for node in section if node.tag == _tag("head")]
    if len(heads) != 1:
        _fail(f"section heading census drifted at {line}")
    head = heads[0]
    if head.attrib or head.text or head.tail or len(head) != 1:
        _fail(f"section heading carrier drifted at {line}")
    if head[0].tag != _tag("seg") or head[0].get("type") != "source-line" or head[0].get("n") != str(line) or "".join(head[0].itertext()) != lines[line - 1]:
        _fail(f"section heading source drifted at {line}")
    return head


def _chronology_item_numbers(item: etree._Element, lines: Sequence[str], carriers: _Carriers, seen: set[int]) -> list[int]:
    numbers: list[int] = []
    for child in item:
        if child.tag == _tag("ab"):
            if child.attrib != {"type": "source-whitespace"} or child.text or child.tail:
                _fail("chronology whitespace carrier drifted")
        elif child.tag == _tag("p"):
            if child.get("ana") not in {"chronology-entry", "chronology-label"} or child.text or child.tail:
                _fail("chronology paragraph role drifted")
            segment_numbers = [int(seg.get("n", "-1")) for seg in child]
            if not segment_numbers or dict(child.attrib) != {"ana": child.get("ana"), "n": str(segment_numbers[0])}:
                _fail("chronology paragraph source identity drifted")
        else:
            _fail("chronology item contains an unexpected node")
        for seg in child:
            n = int(seg.get("n", "-1"))
            _source_seg(seg, n, lines, carriers, seen)
            numbers.append(n)
    if not numbers or numbers != list(range(numbers[0], numbers[-1] + 1)):
        _fail("chronology item source range drifted")
    return numbers


def _verify_chronology_list(
    listing: etree._Element,
    work_id: str,
    lines: Sequence[str],
    body_numbers: Sequence[int],
    brace_groups: Sequence[tuple[int, int]],
    carriers: _Carriers,
    seen: set[int],
) -> set[int]:
    section_number = listing.get("n")
    if dict(listing.attrib) != {"type": "chronology-entries", "n": section_number, _XML_ID: f"{work_id}-chronology-list-{section_number}"} or listing.text or listing.tail:
        _fail("chronology list identity drifted")
    if not list(body_numbers):
        _fail("chronology section has no source body")
    def verify_item(item: etree._Element, parent_group: tuple[int, int] | None = None) -> set[int]:
        if item.tag != _tag("item") or item.text or item.tail:
            _fail("chronology item wrapper drifted")
        ana = item.get("ana")
        if ana == "brace-group":
            group = next((pair for pair in brace_groups if item.get("n") == f"{pair[0]}-{pair[1]}"), None)
            if group is None:
                _fail("chronology brace group coordinate drifted")
            group_id = f"{group[0]}-{group[1]}"
            enclosing = [pair for pair in brace_groups if pair != group and pair[0] <= group[0] and pair[1] >= group[1]]
            expected_parent = min(enclosing, key=lambda pair: pair[1] - pair[0]) if enclosing else None
            if parent_group != expected_parent:
                _fail("chronology brace nesting drifted")
            if dict(item.attrib) != {"ana": "brace-group", "n": group_id, _XML_ID: f"{work_id}-brace-group-{group_id}"}:
                _fail("chronology brace group identity drifted")
            if len(item) != 1 or item[0].tag != _tag("list"):
                _fail("chronology brace wrapper drifted")
            nested = item[0]
            if dict(nested.attrib) != {"type": "chronology-brace-entries", "n": group_id, _XML_ID: f"{work_id}-brace-list-{group_id}"} or nested.text or nested.tail:
                _fail("chronology brace list identity drifted")
            group_numbers: set[int] = set()
            for child in nested:
                group_numbers.update(verify_item(child, group))
            if not group_numbers or min(group_numbers) < group[0] - 1 or max(group_numbers) > group[1] + 1:
                _fail("chronology brace source range drifted")
            nonblank = sorted(n for n in group_numbers if lines[n - 1].strip())
            if nonblank != list(range(group[0], group[1] + 1)):
                _fail("chronology brace source range drifted")
            return group_numbers
        if ana not in {"chronology-entry", "chronology-label"}:
            _fail("chronology item role drifted")
        item_numbers = _chronology_item_numbers(item, lines, carriers, seen)
        first_nonblank = next((n for n in item_numbers if lines[n - 1].strip()), None)
        if first_nonblank is None or dict(item.attrib) != {
            "ana": ana,
            "n": str(first_nonblank),
            _XML_ID: f"{work_id}-chronology-item-{first_nonblank}",
        }:
            _fail("chronology item source identity drifted")
        source_value = lines[first_nonblank - 1]
        expected_ana = "chronology-entry" if _CHRONOLOGY_START_RE.match(source_value) else "chronology-label" if not source_value.startswith((" ", "\t")) else None
        if expected_ana != ana:
            _fail("chronology entry/label classification drifted")
        return set(item_numbers)

    represented: set[int] = set()
    for item in listing:
        represented.update(verify_item(item))
    if sorted(represented) != list(body_numbers):
        _fail("chronology list source coverage drifted")
    return represented


def _source_brace_groups(lines: Sequence[str]) -> list[tuple[int, int]]:
    """Corroborate declarations using literal braces and the retained labels.

    Simple groups are bounded by unbraced lines. In the compound group the
    doubled braces enclose the Children of St. Richard, and repeated terminal
    Boniface labels end two separately printed outer groups. This source-local
    interpretation does not infer genealogy from outside historical knowledge.
    """
    runs: list[list[int]] = []
    for number in range(11157, 11640):
        if "}" not in lines[number - 1]:
            continue
        if not runs or number != runs[-1][-1] + 1:
            runs.append([])
        runs[-1].append(number)
    result: list[tuple[int, int]] = []
    for run in runs:
        doubled = [number for number in run if lines[number - 1].count("}") > 1]
        if not doubled:
            result.append((run[0], run[-1]))
            continue
        if doubled != list(range(run[0], doubled[-1] + 1)) or any(lines[number - 1].count("}") != 2 for number in doubled):
            _fail("chronology nested source brace marks drifted")
        inner_text = " ".join(lines[number - 1] for number in doubled)
        if "Children of}" not in inner_text or "St. Richard.}" not in inner_text:
            _fail("chronology nested source brace label drifted")
        result.append((doubled[0], doubled[-1]))
        endings = [number for number in run if lines[number - 1].rsplit("}", 1)[-1].strip() == "Boniface."]
        if len(endings) != 2 or endings[-1] != run[-1] or endings[0] < doubled[-1]:
            _fail("chronology outer source brace labels drifted")
        start = run[0]
        for end in endings:
            label_text = " ".join(lines[number - 1] for number in range(start, end + 1))
            if "Companions" not in label_text:
                _fail("chronology outer source brace attachment drifted")
            result.append((start, end))
            start = end + 1
    return result


def _verify_chronology(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    profile_rows: Sequence[Mapping[str, Any]],
    carriers: _Carriers,
    seen: set[int],
) -> set[int]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["chronology"]
    if data["brace_groups"] != _source_brace_groups(lines):
        _fail("chronology declared brace groups disagree with source marks and labels")
    section = _section(scope, data["parent"], "chronology")
    if lines[data["parent"] - 1] != "CHRONOLOGICAL ARRANGEMENT.":
        _fail("chronology section anchor drifted")
    century_rows = [row for row in profile_rows if row.get("kind") == "century"]
    if len(century_rows) != data["heading_count"]:
        _fail("chronology heading census drifted")
    expected_all: set[int] = set()
    all_start_lines = {n for n, line in enumerate(lines, 1) if line.isupper() and line.endswith(("CENTURY.", "CENTURIES."))}
    if all_start_lines != {int(row["line"]) for row in century_rows}:
        _fail("chronology source heading census drifted")
    for row in century_rows:
        number = int(row["line"])
        century = _section(section, number, "century")
        head = _verify_head(century, number, lines)
        body_first, body_end = _profile_bounds(profile_rows, row, len(lines))
        listings = [node for node in century if node.tag == _tag("list") and node.get("type") == "chronology-entries"]
        if len(listings) != 1 or century.index(listings[0]) <= century.index(head):
            _fail(f"chronology list missing at {number}")
        groups = [pair for pair in data["brace_groups"] if body_first <= pair[0] < body_end]
        expected_all.update(_verify_chronology_list(listings[0], work_id, lines, range(body_first, body_end), groups, carriers, seen))
    entry_count = sum(1 for n in range(11157, 11640) if lines[n - 1] and _CHRONOLOGY_START_RE.match(lines[n - 1]))
    if entry_count != data["entry_count"]:
        _fail("chronology dated-entry census drifted")
    return expected_all


def _verify_column_table(
    table: etree._Element,
    work_id: str,
    lines: Sequence[str],
    table_type: str,
    row_numbers: Sequence[int],
    carriers: _Carriers,
    seen: set[int],
    seen_fragments: set[int],
    header: int | None = None,
) -> set[int]:
    start = int(table.get("n", "-1"))
    expected_attrs = {"type": table_type, "n": str(start), _XML_ID: f"{work_id}-supplement-i"}
    if table_type == "supplement-date-page":
        if dict(table.attrib) != expected_attrs or table.text or table.tail or len(table) != len(row_numbers) + 1:
            _fail("Supplement I table identity drifted")
        heading = table[0]
        if heading.tag != _tag("head") or heading.attrib or heading.text or heading.tail or len(heading) != 1:
            _fail("Supplement I table heading drifted")
        _source_seg(heading[0], int(header), lines, carriers, seen)
        children = list(table)[1:]
    else:
        if dict(table.attrib) != {"type": table_type, "n": str(start), _XML_ID: f"{work_id}-calendar-{start}"} or table.text or table.tail or len(table) != len(row_numbers):
            _fail("calendar table identity drifted")
        children = list(table)
    represented: set[int] = {int(header)} if header is not None else set()
    for row, number in zip(children, row_numbers, strict=True):
        if row.tag != _tag("row") or dict(row.attrib) != {"n": str(number), _XML_ID: f"{work_id}-calendar-row-{number}" if table_type == "calendar" else f"{work_id}-supplement-i-row-{number}"}:
            _fail(f"{table_type} row identity drifted at {number}")
        raw = lines[number - 1]
        boundary, page = _fixed_page_span(raw, number)
        if table_type == "calendar":
            continue
        if len(row) != 2:
            _fail(f"Supplement I row cell count drifted at {number}")
        _check_fragment_cell(row[0], work_id, lines, "date", [number], [(number, "date", 0, boundary)], carriers, seen_fragments)
        _check_fragment_cell(row[1], work_id, lines, "page", [number], [(number, "page", boundary, len(raw))], carriers, seen_fragments)
        represented.add(number)
    return represented


def _bibliography_markers(numbers: Sequence[int], lines: Sequence[str]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    # Scan punctuation and its neighboring characters independently of the
    # producer's regular expression. A physical line ending is a valid boundary:
    # the enumerated title can begin on the following retained line.
    for number in numbers:
        value = lines[number - 1]
        for stop, character in enumerate(value):
            if character != "." or (stop + 1 < len(value) and not value[stop + 1].isspace()):
                continue
            start = stop
            while start and value[start - 1].isdecimal():
                start -= 1
            if start == stop or (start and (value[start - 1].isalnum() or value[start - 1] == "_")):
                continue
            result.append((value[start:stop], number))
    return result[1:]


def _verify_grouped_list(
    listing: etree._Element,
    work_id: str,
    lines: Sequence[str],
    expected_range: Sequence[int],
    item_kind: str,
    carriers: _Carriers,
    seen: set[int],
    *,
    station: bool = False,
) -> set[int]:
    represented: set[int] = set()
    expected_starts = [n for n in expected_range if _STATION_NUMBER_RE.match(lines[n - 1])] if station else []
    expected_start_set = set(expected_starts)
    if listing.text or listing.tail:
        _fail(f"{item_kind} list text drifted")
    for index, item in enumerate(listing):
        if item.tag != _tag("item") or item.text or item.tail:
            _fail(f"{item_kind} item wrapper drifted")
        source_segments = [seg for seg in item.iter(_tag("seg")) if seg.get("type") == "source-line"]
        numbers = [int(seg.get("n", "-1")) for seg in source_segments]
        if not numbers or numbers != list(range(numbers[0], numbers[-1] + 1)):
            _fail(f"{item_kind} item source range drifted")
        if set(numbers) & represented:
            _fail(f"{item_kind} item source overlap drifted")
        represented.update(numbers)
        blank_item = all(not lines[n - 1].strip() for n in numbers)
        if blank_item:
            if (
                dict(item.attrib) != {"ana": "source-whitespace", "n": str(numbers[0])}
                or len(item) != 1
                or item[0].tag != _tag("ab")
                or item[0].attrib != {"type": "source-whitespace"}
                or item[0].text
                or item[0].tail
            ):
                _fail(f"{item_kind} whitespace item drifted")
        else:
            if item.get("ana") != item_kind:
                _fail(f"{item_kind} item role drifted")
            expected_item_id = (
                f"{work_id}-bibliography-item-{numbers[0]}"
                if item_kind == "bibliography-item"
                else f"{listing.get(_XML_ID)}-item-{index + 1}"
            )
            if item.get(_XML_ID) != expected_item_id:
                _fail(f"{item_kind} item XML ID drifted")
            first_nonblank = next(n for n in numbers if lines[n - 1].strip())
            if station:
                match = _STATION_NUMBER_RE.match(lines[first_nonblank - 1])
                if match is None or first_nonblank not in expected_start_set or item.get("n") != match.group(1):
                    _fail("station contents item number drifted")
                nonblank = [n for n in numbers if lines[n - 1].strip()]
                page_match = re.search(r"(\d+)\s*$", lines[nonblank[-1] - 1])
                labels = [node for node in item if node.tag == _tag("label")]
                if page_match is None or len(labels) != 1 or dict(labels[0].attrib) != {"n": page_match.group(1)} or labels[0].text or labels[0].tail:
                    _fail("station contents page label drifted")
            elif item_kind == "bibliography-item":
                match = _BIB_NUMBER_RE.match(lines[first_nonblank - 1])
                expected_number = match.group(1).replace(" ", "") if match is not None else None
                if item.get("n") != expected_number:
                    _fail("bibliography item number drifted")
            elif item.get("n") != str(index + 1):
                _fail(f"{item_kind} item number drifted")
            expected_tags = (
                ["label", "p", "ab"]
                if station
                else ["p", "ab", "list"]
                if item_kind == "bibliography-item" and any(child.tag == _tag("list") for child in item)
                else ["p", "ab"]
            )
            if [etree.QName(child).localname for child in item] != expected_tags:
                _fail(f"{item_kind} item child order drifted")
            for child in item:
                if child.tag == _tag("p"):
                    expected_p_attrs = {"ana": "bibliography-source"} if item_kind == "bibliography-item" else {}
                    if dict(child.attrib) != expected_p_attrs or child.text or child.tail:
                        _fail(f"{item_kind} paragraph carrier drifted")
                elif child.tag == _tag("ab"):
                    if child.attrib != {"type": "source-whitespace"} or child.text or child.tail:
                        _fail(f"{item_kind} whitespace carrier drifted")
                elif child.tag not in {_tag("list"), _tag("label"), _tag("ab")}:
                    _fail(f"{item_kind} item contains an unexpected node")
                elif child.tag == _tag("list") and child.get("type") != "bibliography-subitems":
                    _fail("bibliography item contains an unexpected list")
            if item_kind == "bibliography-item":
                markers = _bibliography_markers(numbers, lines)
                nested = [node for node in item if node.tag == _tag("list") and node.get("type") == "bibliography-subitems"]
                if bool(markers) != (len(nested) == 1):
                    _fail("bibliography subitem presence drifted")
                if markers:
                    sub = nested[0]
                    if dict(sub.attrib) != {"type": "bibliography-subitems", _XML_ID: f"{work_id}-bibliography-subitems-{numbers[0]}"} or sub.text or sub.tail or len(sub) != len(markers):
                        _fail("bibliography subitem list drifted")
                    for node, (marker, line_number) in zip(sub, markers, strict=True):
                        if node.tag != _tag("item") or dict(node.attrib) != {"n": marker, "corresp": f"#{_line_id(work_id, line_number)}"} or node.text or node.tail or len(node):
                            _fail("bibliography subitem identity drifted")
        for seg in source_segments:
            _source_seg(seg, int(seg.get("n")), lines, carriers, seen)
    if sorted(represented) != list(expected_range):
        _fail(f"{item_kind} list source coverage drifted")
    return represented


def _verify_bibliography(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    carriers: _Carriers,
    seen: set[int],
) -> set[int]:
    data = SPECIAL_SOURCE_INVENTORY[work_id]["bibliography"]
    parent = _section(scope, data["parent"], "supplement-section")
    category_rows = [row for row in rows if row.get("kind") == "bibliography-category"]
    if [int(row["line"]) for row in category_rows] != list(data["categories"]):
        _fail("bibliography category census drifted")
    represented: set[int] = set()
    for row in category_rows:
        number = int(row["line"])
        category = _section(scope, number, "bibliography-category")
        head = _verify_head(category, number, lines)
        first, end = _profile_bounds(rows, row, len(lines))
        # The declared terminal boundary intentionally includes the four
        # trailing blanks before Supplement III.
        if number == data["categories"][-1]:
            end = data["end"] + 1
        listings = [node for node in category if node.tag == _tag("list") and node.get("type") == "bibliography"]
        if len(listings) != 1 or category.index(listings[0]) <= category.index(head):
            _fail(f"bibliography list missing at {number}")
        listing = listings[0]
        if dict(listing.attrib) != {"type": "bibliography", "n": str(number), _XML_ID: f"{work_id}-bibliography-list-{number}"}:
            _fail(f"bibliography list identity drifted at {number}")
        represented.update(_verify_grouped_list(listing, work_id, lines, range(first, end), "bibliography-item", carriers, seen))
    return represented


def _verify_donne_list(
    scope: etree._Element,
    work_id: str,
    lines: Sequence[str],
    data: Mapping[str, Any],
    list_type: str,
    list_id: str,
    item_kind: str,
    carriers: _Carriers,
    seen: set[int],
    *,
    station: bool = False,
) -> set[int]:
    parent = _section(scope, int(data["parent"]), "station-contents" if station else "devotions-title-page")
    listings = [node for node in parent if node.tag == _tag("list") and node.get("type") == list_type]
    if len(listings) != 1:
        _fail(f"{list_type} list census drifted")
    listing = listings[0]
    if dict(listing.attrib) != {"type": list_type, "n": str(data["start"]), _XML_ID: list_id}:
        _fail(f"{list_type} list identity drifted")
    expected = range(int(data["start"]), int(data["end"]) + 1)
    represented = _verify_grouped_list(listing, work_id, lines, expected, item_kind, carriers, seen, station=station)
    if station:
        starts = [n for n in expected if _STATION_NUMBER_RE.match(lines[n - 1])]
        numbers = [int(_STATION_NUMBER_RE.match(lines[n - 1]).group(1)) for n in starts]
        if numbers != list(range(1, 24)) or len(listing) != 23:
            _fail("station contents source census drifted")
    else:
        if len(listing) != 3 or [int(item.get("n", "-1")) for item in listing] != [1, 2, 3]:
            _fail("devotional component census drifted")
    return represented


def _verify_special_node_inventory(scope: etree._Element, work_id: str) -> None:
    allowed = {
        "quote": {"source-verse"},
        "table": {"calendar", "supplement-date-page"},
        "list": {"chronology-entries", "chronology-brace-entries", "bibliography", "bibliography-subitems", "devotional-components", "station-contents"},
        "figure": {"source-illustration-placeholder"},
    }
    for tag_name, types in allowed.items():
        for node in scope.iter(_tag(tag_name)):
            if node.get("type") not in types:
                _fail(f"unrecognized literary {tag_name} type {node.get('type')!r}")
    if work_id == NEWMAN:
        if len([n for n in scope.iter(_tag("figure")) if n.get("type") == "source-illustration-placeholder"]) != 0:
            _fail("Newman has an unexpected illustration placeholder")
    else:
        if len([n for n in scope.iter(_tag("table")) if n.get("type") in {"calendar", "supplement-date-page"}]) != 0:
            _fail("Donne has an unexpected table")


def _verify_wrapper_inventory(scope: etree._Element, work_id: str, rows: Sequence[Mapping[str, Any]]) -> None:
    data = SPECIAL_SOURCE_INVENTORY[work_id]
    expected_quotes = {
        (str(spec["start"]), f"{work_id}-{spec['id']}") for spec in data["verse"]
    }
    actual_quotes = {
        (node.get("n"), node.get(_XML_ID))
        for node in scope.iter(_tag("quote"))
        if node.get("type") == "source-verse"
    }
    if actual_quotes != expected_quotes:
        _fail("source verse wrapper inventory drifted")
    expected_figures = {
        (str(number), f"{work_id}-illustration-{number}")
        for spec in data["verse"]
        for number in spec["illustrations"]
    }
    actual_figures = {
        (node.get("n"), node.get(_XML_ID))
        for node in scope.iter(_tag("figure"))
        if node.get("type") == "source-illustration-placeholder"
    }
    if actual_figures != expected_figures:
        _fail("source illustration wrapper inventory drifted")
    if work_id == NEWMAN:
        expected_tables = {
            ("calendar", str(number), f"{work_id}-calendar-{number}")
            for number, _ in data["calendar"]["months"]
        } | {
            ("supplement-date-page", str(data["supplement_i"]["start"]), f"{work_id}-supplement-i")
        }
        actual_tables = {
            (node.get("type"), node.get("n"), node.get(_XML_ID))
            for node in scope.iter(_tag("table"))
            if node.get("type") in {"calendar", "supplement-date-page"}
        }
        if actual_tables != expected_tables:
            _fail("Newman table wrapper inventory drifted")
        expected_chronology = {
            (str(row["line"]), f"{work_id}-chronology-list-{row['line']}")
            for row in rows
            if row.get("kind") == "century"
        }
        actual_chronology = {
            (node.get("n"), node.get(_XML_ID))
            for node in scope.iter(_tag("list"))
            if node.get("type") == "chronology-entries"
        }
        if actual_chronology != expected_chronology:
            _fail("chronology list wrapper inventory drifted")
        expected_bibliography = {
            (str(row["line"]), f"{work_id}-bibliography-list-{row['line']}")
            for row in rows
            if row.get("kind") == "bibliography-category"
        }
        actual_bibliography = {
            (node.get("n"), node.get(_XML_ID))
            for node in scope.iter(_tag("list"))
            if node.get("type") == "bibliography"
        }
        if actual_bibliography != expected_bibliography:
            _fail("bibliography list wrapper inventory drifted")
        expected_braces = {
            (f"{start}-{end}", f"{work_id}-brace-list-{start}-{end}")
            for start, end in data["chronology"]["brace_groups"]
        }
        actual_braces = {
            (node.get("n"), node.get(_XML_ID))
            for node in scope.iter(_tag("list"))
            if node.get("type") == "chronology-brace-entries"
        }
        if actual_braces != expected_braces:
            _fail("chronology brace wrapper inventory drifted")
    else:
        expected_lists = {
            ("devotional-components", str(data["components"]["start"]), f"{work_id}-components"),
            ("station-contents", str(data["station_contents"]["start"]), f"{work_id}-station-contents-list"),
        }
        actual_lists = {
            (node.get("type"), node.get("n"), node.get(_XML_ID))
            for node in scope.iter(_tag("list"))
            if node.get("type") in {"devotional-components", "station-contents"}
        }
        if actual_lists != expected_lists:
            _fail("Donne list wrapper inventory drifted")


def _restore_blocks(
    wrapper: etree._Element,
    first: int,
    last: int,
    lines: Sequence[str],
    carriers: _Carriers,
    work_id: str,
) -> None:
    parent = wrapper.getparent()
    if parent is None:
        _fail("special wrapper is detached")
    index = parent.index(wrapper)
    nodes: list[etree._Element] = []
    cursor = first
    while cursor <= last:
        blank = not lines[cursor - 1].strip()
        end = cursor + 1
        while end <= last and bool(not lines[end - 1].strip()) == blank:
            end += 1
        if blank:
            block = etree.Element(_tag("ab"), type="source-whitespace")
        else:
            footnote = re.match(r"^\s*\[(\d+)\] ", lines[cursor - 1])
            if footnote:
                block = etree.Element(_tag("note"), n=footnote.group(1), type="source-footnote", **{_XML_ID: f"{work_id}-footnote-{footnote.group(1)}"})
            else:
                block = etree.Element(_tag("p"))
        for number in range(cursor, end):
            seg = carriers.materialize(number)
            if seg.getparent() is not None:
                seg.getparent().remove(seg)
            seg.attrib.clear()
            seg.set("type", "source-line")
            seg.set("n", str(number))
            seg.tail = "\n" if number < end - 1 else None
            block.append(seg)
        nodes.append(block)
        cursor = end
    parent.remove(wrapper)
    for offset, node in enumerate(nodes):
        parent.insert(index + offset, node)


def verify_and_normalize_blocks(scope: etree._Element, work_id: str, lines: Sequence[str], profile: Mapping[str, Any]) -> etree._Element:
    """Verify actual special blocks and return a normalized cloned scope.

    The caller is expected to run the letter normalizer first.  This function
    mutates only its private clone and leaves the candidate tree untouched.
    """

    _validate_source(work_id, lines)
    rows = _profile_rows(profile)
    clone = deepcopy(scope)
    _verify_special_node_inventory(clone, work_id)
    _verify_wrapper_inventory(clone, work_id, rows)
    carriers = _Carriers(clone, lines, work_id)
    seen: set[int] = set()
    seen_fragments: set[int] = set()
    expected_special: set[int] = set()
    data = SPECIAL_SOURCE_INVENTORY[work_id]
    for spec in data["verse"]:
        expected_special.update(_verify_verse(clone, work_id, lines, spec, carriers, seen))
    if work_id == NEWMAN:
        expected_special.update(_verify_calendar(clone, work_id, lines, carriers, seen, seen_fragments))
        expected_special.update(_verify_chronology(clone, work_id, lines, rows, carriers, seen))
        supplement = data["supplement_i"]
        parent = _section(clone, supplement["parent"], "supplement-section")
        tables = [node for node in parent if node.tag == _tag("table") and node.get("type") == "supplement-date-page"]
        if len(tables) != 1:
            _fail("Supplement I table census drifted")
        table = tables[0]
        if not re.fullmatch(r"\s+PAGE", lines[supplement["header"] - 1]):
            _fail("Supplement I header anchor drifted")
        expected_special.update(_verify_column_table(table, work_id, lines, "supplement-date-page", range(supplement["start"], supplement["end"] + 1), carriers, seen, seen_fragments, supplement["header"]))
        expected_special.update(_verify_bibliography(clone, work_id, lines, rows, carriers, seen))
    else:
        components = data["components"]
        component_lines = list(components["items"])
        for number in component_lines:
            if _STATION_NUMBER_RE.match(lines[number - 1]) is None:
                _fail(f"component source anchor drifted at {number}")
        expected_special.update(_verify_donne_list(clone, work_id, lines, components, "devotional-components", f"{work_id}-components", "component", carriers, seen))
        station = data["station_contents"]
        expected_special.update(_verify_donne_list(clone, work_id, lines, station, "station-contents", f"{work_id}-station-contents-list", "station", carriers, seen, station=True))
    observed_special = set(seen)
    for number, nodes in carriers.fragments.items():
        if any(id(node) in seen_fragments for node in nodes):
            observed_special.add(number)
    if observed_special != expected_special:
        _fail("special block source coverage drifted")
    if {id(node) for nodes in carriers.fragments.values() for node in nodes} != seen_fragments:
        _fail("unattached source-line fragment remains")
    if set(carriers.regular) | set(carriers.fragments) != set(range(1, len(lines) + 1)):
        _fail("source carrier census is incomplete")

    # Restore in document order.  The wrapper references are held before any
    # removal, so index changes in one section cannot redirect another range.
    wrappers: list[tuple[etree._Element, int, int]] = []
    for quote in clone.iter(_tag("quote")):
        if quote.get("type") == "source-verse":
            spec = next(spec for spec in data["verse"] if spec["start"] == int(quote.get("n")))
            wrappers.append((quote, spec["start"], spec["end"]))
    for table in clone.iter(_tag("table")):
        table_type = table.get("type")
        if table_type == "calendar":
            rows_for_table = [row for row in table if row.tag == _tag("row")]
            if rows_for_table:
                wrappers.append((table, int(rows_for_table[0].get("n")), int(rows_for_table[-1].get("n"))))
        elif table_type == "supplement-date-page":
            supplement = data["supplement_i"]
            wrappers.append((table, supplement["header"], supplement["end"]))
    for listing in clone.iter(_tag("list")):
        list_type = listing.get("type")
        if list_type == "chronology-entries":
            section_number = int(listing.get("n"))
            row = next(row for row in rows if int(row["line"]) == section_number)
            first, end = _profile_bounds(rows, row, len(lines))
            wrappers.append((listing, first, end - 1))
        elif list_type == "bibliography":
            number = int(listing.get("n"))
            row = next(row for row in rows if int(row["line"]) == number)
            first, end = _profile_bounds(rows, row, len(lines))
            if number == data["bibliography"]["categories"][-1]:
                end = data["bibliography"]["end"] + 1
            wrappers.append((listing, first, end - 1))
        elif work_id == DONNE and list_type == "devotional-components":
            component = data["components"]
            wrappers.append((listing, component["start"], component["end"]))
        elif work_id == DONNE and list_type == "station-contents":
            station = data["station_contents"]
            wrappers.append((listing, station["start"], station["end"]))
    # Special wrappers are disjoint; process by their current document order
    # and restore source blocks at each wrapper's original position.
    wrappers.sort(key=lambda item: len(list(item[0].iterancestors())) if item[0].getparent() is not None else 0)
    for wrapper, first, last in wrappers:
        if wrapper.getparent() is None:
            continue
        _restore_blocks(wrapper, first, last, lines, carriers, work_id)
    native_wrapper_tags = {_tag("quote"), _tag("table"), _tag("list"), _tag("figure")}
    if any(node.tag in native_wrapper_tags for node in clone.iter()):
        _fail("unremoved literary special wrapper remains")
    # Check the normalized floor locally.  The base oracle repeats this after
    # its own inline and source-boundary checks.
    leaves = list(clone.iter(_tag("seg")))
    if len(leaves) != len(lines):
        _fail("normalized source-line census drifted")
    for number, leaf in enumerate(leaves, 1):
        if dict(leaf.attrib) != {"type": "source-line", "n": str(number)} or "".join(leaf.itertext()) != lines[number - 1]:
            _fail(f"normalized source-line {number} drifted")
    return clone


__all__ = ["verify_and_normalize_blocks", "SOURCE_PINS", "SPECIAL_SOURCE_INVENTORY"]
