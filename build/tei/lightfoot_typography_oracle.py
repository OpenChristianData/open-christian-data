"""Independent source-first oracle for Lightfoot typography markup.

The retained witness is a UTF-8, CRLF line file.  Its transcription note
defines a small set of literal delimiter conventions.  This module derives
those conventions from the supplied source lines and checks a TEI tree that
already contains native ``hi`` elements.  It deliberately does not import or
call the producer.

``discover_source_spans`` is the source inventory used by the verifier.  Each
record has a deterministic source ID, a TEI ``rend`` value, and one part per
physical source line.  ``verify_and_normalize_typography`` first checks every
``hi`` against those source intervals, roles, and links.  Only after that
check succeeds does it deep-copy the tree and unwrap the ``hi`` elements.
The supplied tree is never modified.

The checker validates the typography forms represented by the current
producer: underscore italics and Greek gesperrt (represented by
``rend="letter-spaced"``), double-equals uncial, the source-declared
blackletter example, the two generic same-line equals spans, numeric and
source-label caret superscripts, and braced numeric subscripts.  Bare
manuscript subscripts and the two quoted underscore examples remain literal
source syntax.  The three carets embedded in Greek words also remain literal;
all of those boundaries are recorded in ``source_census``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from typing import Any
import unicodedata

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
XML_ID = f"{{{XML}}}id"
SOURCE_LINE_TYPE = "source-line"
TYPOGRAPHY_ID_PREFIX = "lightfoot-typography-"
SOURCE_BYTES = 1_511_463
SOURCE_SHA256 = "a97cb49964906a2c158a0444cfdc3b0daf13261620c919a90f1333a98ac0b913"
SOURCE_LINE_COUNT = 26_185

HI = f"{{{TEI}}}hi"
SOURCE_LINE_TAGS = frozenset(
    {
        f"{{{TEI}}}ab",
        f"{{{TEI}}}head",
        f"{{{TEI}}}label",
        f"{{{TEI}}}p",
        f"{{{TEI}}}seg",
    }
)
RENDS = frozenset(
    {
        "italic",
        "letter-spaced",
        "source-underscore-emphasis",
        "uncial",
        "blackletter",
        "emphasis",
        "superscript",
        "subscript",
    }
)

# The transcriber note quotes these two underscores as punctuation.  The
# anchors are checked by source text, rather than trusted as bare positions.
LITERAL_UNDERSCORE_ANCHORS = (
    (33, "‘_’"),
    (36, "‘_’"),
)

# The transcriber note identifies this source-spanning pair as blackletter.
BLACKLETTER_SOURCE_LINES = (54, 55)
BLACKLETTER_START_TEXT = "=blackletter"
BLACKLETTER_END_TEXT = "text="

_BRACED_SUBSCRIPT_RE = re.compile(r"_\{\d+\}")
_BARE_SUBSCRIPT_RE = re.compile(r"_(?:\d+)(?:\*)?")
_NUMERIC_CARET_RE = re.compile(r"\^(?:\{\d+\}|\d+)")
_SUPPORTED_CARET_RE = re.compile(r"\^(?:\{[^}]*\}|\d+|[A-Za-z*])")
_ANY_CARET_RE = re.compile(r"\^(?:\{[^}\r\n]*\}|[^\r\n])")
_EQUALS_RUN_RE = re.compile(r"=+")
_N_RE = re.compile(r"^(\d+):(\d+)-(\d+)$")
_SPAN_ID_RE = re.compile(r"^lightfoot-typography-\d{6}$")


@dataclass(frozen=True, slots=True)
class _ExpectedSpan:
    ident: str
    rend: str
    syntax: str
    start_line: int
    start_char: int
    end_line: int
    end_char: int
    parts: tuple[tuple[int, int, int], ...]

    @property
    def nonempty_parts(self) -> tuple[tuple[int, int, int], ...]:
        return tuple(part for part in self.parts if part[1] < part[2])

    @property
    def by_line(self) -> dict[int, frozenset[int]]:
        return {
            line: frozenset(range(start, end))
            for line, start, end in self.nonempty_parts
        }


@dataclass(frozen=True, slots=True)
class _ObservedHi:
    node: etree._Element
    ident: str
    target: str
    rend: str
    line: int
    start: int
    end: int
    positions: frozenset[int]


def _tag(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _source_lines(lines: Sequence[str]) -> list[str]:
    """Validate the exact retained witness envelope represented by ``lines``."""

    if isinstance(lines, (str, bytes, bytearray)) or not isinstance(lines, Sequence):
        raise TypeError("Lightfoot typography lines must be a string sequence")
    values = list(lines)
    if any(not isinstance(value, str) for value in values):
        raise TypeError("Lightfoot typography lines must contain only strings")
    if any("\r" in value or "\n" in value for value in values):
        raise ValueError("Lightfoot typography lines must not contain line endings")
    if len(values) != SOURCE_LINE_COUNT or not values or values[-1] != "":
        raise ValueError("Lightfoot retained witness line census drifted")

    # The file-initial BOM is an encoding marker, not readable line text.
    # Restore it only when checking the exact retained witness bytes.
    if values[0].startswith("\ufeff"):
        raise ValueError("Lightfoot readable first line retains the source BOM")
    reconstructed = b"\xef\xbb\xbf" + "\r\n".join(values).encode("utf-8") + b"\r\n"
    if len(reconstructed) != SOURCE_BYTES or hashlib.sha256(reconstructed).hexdigest() != SOURCE_SHA256:
        raise ValueError("Lightfoot retained witness bytes drifted")
    return values


def _parts(
    lines: list[str],
    start_line: int,
    start_char: int,
    end_line: int,
    end_char: int,
) -> tuple[tuple[int, int, int], ...]:
    if not 1 <= start_line <= end_line <= len(lines):
        raise ValueError("Lightfoot typography span line bounds drifted")
    result: list[tuple[int, int, int]] = []
    for line in range(start_line, end_line + 1):
        start = start_char if line == start_line else 0
        end = end_char if line == end_line else len(lines[line - 1])
        if not 0 <= start <= end <= len(lines[line - 1]):
            raise ValueError(f"Lightfoot typography span offsets drifted at line {line}")
        result.append((line, start, end))
    return tuple(result)


def _expected(
    lines: list[str],
    *,
    rend: str,
    syntax: str,
    start_line: int,
    start_char: int,
    end_line: int,
    end_char: int,
) -> dict[str, Any]:
    parts = _parts(lines, start_line, start_char, end_line, end_char)
    return {
        "rend": rend,
        "syntax": syntax,
        "start_line": start_line,
        "start_char": start_char,
        "end_line": end_line,
        "end_char": end_char,
        "parts": [
            {
                "line": line,
                "start_char": start,
                "end_char": end,
                "text": lines[line - 1][start:end],
            }
            for line, start, end in parts
        ],
        "text": "\n".join(lines[line - 1][start:end] for line, start, end in parts),
    }


def _anchor(line: int, value: str, needle: str, *, suffix: bool = False) -> int:
    matches = [match.start() for match in re.finditer(re.escape(needle), value)]
    if len(matches) != 1:
        raise ValueError(f"Lightfoot source anchor {needle!r} drifted at line {line}")
    position = matches[0]
    if suffix and not value.endswith(needle):
        raise ValueError(f"Lightfoot source suffix anchor {needle!r} drifted at line {line}")
    return position


def _underscore_rend(lines: list[str], parts: tuple[tuple[int, int, int], ...]) -> str:
    """Classify an underscore span from the scripts in its source text.

    The transcriber note says Greek emphasis is printed gesperrt (wider
    spacing), while the same underscore syntax marks ordinary italics.  The
    TEI role ``letter-spaced`` records that source convention.  The three
    mixed-script spans receive the explicit unresolved role
    ``source-underscore-emphasis`` because the source does not identify which
    printed font applies to the whole mixed span.
    """

    text = "\n".join(lines[line - 1][start:end] for line, start, end in parts)
    inner = text[1:-1]
    names = [unicodedata.name(character, "") for character in inner]
    has_greek = any("GREEK" in name for name in names)
    has_latin = any("LATIN" in name for name in names)
    if has_greek and not has_latin:
        return "letter-spaced"
    if has_greek and has_latin:
        return "source-underscore-emphasis"
    return "italic"


def _inventory(lines: list[str]) -> tuple[list[_ExpectedSpan], dict[str, Any]]:
    """Derive expected spans and literal syntax from the retained lines."""

    expected: list[dict[str, Any]] = []
    excluded_underscores: set[tuple[int, int]] = set()
    literal_underscores: list[dict[str, Any]] = []
    literal_bare_subscripts: list[dict[str, Any]] = []
    numeric_carets: list[dict[str, Any]] = []
    supported_carets: list[dict[str, Any]] = []
    literal_carets: list[dict[str, Any]] = []
    nonnumeric_caret_markers: list[dict[str, Any]] = []
    supported_caret_positions: set[tuple[int, int]] = set()

    for line, value in enumerate(lines, 1):
        for match in _BRACED_SUBSCRIPT_RE.finditer(value):
            expected.append(
                _expected(
                    lines,
                    rend="subscript",
                    syntax="braced-subscript",
                    start_line=line,
                    start_char=match.start(),
                    end_line=line,
                    end_char=match.end(),
                )
            )
            excluded_underscores.add((line, match.start()))
        for match in _BARE_SUBSCRIPT_RE.finditer(value):
            literal_bare_subscripts.append(
                {
                    "line": line,
                    "start_char": match.start(),
                    "end_char": match.end(),
                    "token": match.group(),
                    "reason": "bare manuscript subscript remains literal source syntax",
                }
            )
            excluded_underscores.add((line, match.start()))
        for match in _SUPPORTED_CARET_RE.finditer(value):
            expected.append(
                _expected(
                    lines,
                    rend="superscript",
                    syntax="caret",
                    start_line=line,
                    start_char=match.start(),
                    end_line=line,
                    end_char=match.end(),
                )
            )
            supported_caret_positions.add((line, match.start()))
            supported_carets.append(
                {
                    "line": line,
                    "start_char": match.start(),
                    "end_char": match.end(),
                    "token": match.group(),
                }
            )
            if _NUMERIC_CARET_RE.fullmatch(match.group()):
                numeric_carets.append(supported_carets[-1])

        for match in _ANY_CARET_RE.finditer(value):
            token = match.group()
            if _NUMERIC_CARET_RE.fullmatch(token):
                continue
            body = token[1:]
            if token == "^*":
                category = "star"
                reason = "source manuscript correction sigil"
            elif body.startswith("{"):
                category = "braced-nonnumeric"
                reason = "source manuscript or apparatus label"
            elif len(token) == 2 and token[1].isascii() and token[1].isalpha():
                category = "ascii-letter"
                reason = "source sidenote or manuscript label"
            elif body.isalpha():
                category = "greek-letter"
                reason = "Greek embedded caret text"
            else:
                category = "other"
                reason = "unclassified nonnumeric caret source syntax"
            rendered = (line, match.start()) in supported_caret_positions
            record = {
                "line": line,
                "start_char": match.start(),
                "end_char": match.end(),
                "token": token,
                "category": category,
                "reason": reason,
                "rendered": rendered,
            }
            nonnumeric_caret_markers.append(record)
            if not rendered:
                literal_carets.append(record)

    for line, quoted in LITERAL_UNDERSCORE_ANCHORS:
        positions = [match.start() + 1 for match in re.finditer(re.escape(quoted), lines[line - 1])]
        if len(positions) != 1:
            raise ValueError(f"Lightfoot quoted underscore anchor drifted at line {line}")
        position = positions[0]
        excluded_underscores.add((line, position))
        literal_underscores.append(
            {
                "line": line,
                "start_char": position,
                "end_char": position + 1,
                "token": "_",
                "reason": "quoted delimiter mention in the transcriber note",
            }
        )

    underscore_markers = [
        (line, position)
        for line, value in enumerate(lines, 1)
        for position, character in enumerate(value)
        if character == "_" and (line, position) not in excluded_underscores
    ]
    if len(underscore_markers) % 2:
        raise ValueError("Lightfoot underscore typography markers are unbalanced")
    for (start_line, start_char), (end_line, end_char) in zip(
        underscore_markers[::2], underscore_markers[1::2], strict=True
    ):
        span_parts = _parts(lines, start_line, start_char, end_line, end_char + 1)
        expected.append(
            _expected(
                lines,
                rend=_underscore_rend(lines, span_parts),
                syntax="underscore",
                start_line=start_line,
                start_char=start_char,
                end_line=end_line,
                end_char=end_char + 1,
            )
        )

    double_tokens: list[tuple[int, int, int]] = []
    single_tokens: list[tuple[int, int, int]] = []
    for line, value in enumerate(lines, 1):
        for match in _EQUALS_RUN_RE.finditer(value):
            if len(match.group()) == 2:
                double_tokens.append((line, match.start(), match.end()))
            elif len(match.group()) == 1:
                single_tokens.append((line, match.start(), match.end()))
            else:
                raise ValueError(f"Lightfoot equals run width drifted at line {line}")
    if len(double_tokens) % 2:
        raise ValueError("Lightfoot double-equals typography markers are unbalanced")
    for (start_line, start_char, _), (end_line, _, end_char) in zip(
        double_tokens[::2], double_tokens[1::2], strict=True
    ):
        expected.append(
            _expected(
                lines,
                rend="uncial",
                syntax="double-equals",
                start_line=start_line,
                start_char=start_char,
                end_line=end_line,
                end_char=end_char,
            )
        )

    black_start_line, black_end_line = BLACKLETTER_SOURCE_LINES
    black_start = _anchor(black_start_line, lines[black_start_line - 1], BLACKLETTER_START_TEXT, suffix=True)
    black_end_text_start = _anchor(black_end_line, lines[black_end_line - 1], BLACKLETTER_END_TEXT)
    if (black_start_line, black_start, black_start + 1) not in single_tokens:
        raise ValueError("Lightfoot blackletter opening delimiter is not a single equals")
    if (black_end_line, black_end_text_start + len(BLACKLETTER_END_TEXT) - 1, black_end_text_start + len(BLACKLETTER_END_TEXT)) not in single_tokens:
        raise ValueError("Lightfoot blackletter closing delimiter is not a single equals")
    blackletter_positions = {
        (black_start_line, black_start),
        (black_end_line, black_end_text_start + len(BLACKLETTER_END_TEXT) - 1),
    }
    expected.append(
        _expected(
            lines,
            rend="blackletter",
            syntax="single-equals-blackletter",
            start_line=black_start_line,
            start_char=black_start,
            end_line=black_end_line,
            end_char=black_end_text_start + len(BLACKLETTER_END_TEXT),
        )
    )

    single_by_line: dict[int, list[int]] = defaultdict(list)
    for line, start, _ in single_tokens:
        if (line, start) not in blackletter_positions:
            single_by_line[line].append(start)
    generic_single_pairs: list[tuple[int, int, int, int]] = []
    for line, positions in sorted(single_by_line.items()):
        if len(positions) >= 2 and len(positions) % 2 == 0:
            for first, second in zip(positions[::2], positions[1::2], strict=True):
                generic_single_pairs.append((line, first, line, second + 1))
    for start_line, start_char, end_line, end_char in generic_single_pairs:
        expected.append(
            _expected(
                lines,
                rend="emphasis",
                syntax="single-equals-emphasis",
                start_line=start_line,
                start_char=start_char,
                end_line=end_line,
                end_char=end_char,
            )
        )

    paired_single_positions = set(blackletter_positions)
    for start_line, start_char, end_line, end_char in generic_single_pairs:
        paired_single_positions.add((start_line, start_char))
        paired_single_positions.add((end_line, end_char - 1))
    literal_equals = [
        {
            "line": line,
            "start_char": start,
            "end_char": end,
            "token": "=",
            "reason": "standalone equality or source notation; no paired typography evidence",
        }
        for line, start, end in single_tokens
        if (line, start) not in paired_single_positions
    ]

    if len(underscore_markers) != 7_344:
        raise ValueError("Lightfoot underscore source census drifted")
    if len(double_tokens) != 190 or len(single_tokens) != 17:
        raise ValueError("Lightfoot equals source census drifted")
    if len(numeric_carets) != 167 or len(supported_carets) != 272 or len(literal_carets) != 3:
        raise ValueError("Lightfoot caret source census drifted")
    if len(literal_bare_subscripts) != 39 or len(literal_underscores) != 2:
        raise ValueError("Lightfoot literal underscore source census drifted")
    if len(generic_single_pairs) != 2 or len(literal_equals) != 11:
        raise ValueError("Lightfoot single-equals source census drifted")

    expected.sort(
        key=lambda item: (
            int(item["start_line"]),
            int(item["start_char"]),
            -int(item["end_line"]),
            -int(item["end_char"]),
            str(item["syntax"]),
        )
    )
    typed: list[_ExpectedSpan] = []
    for ordinal, item in enumerate(expected, 1):
        typed.append(
            _ExpectedSpan(
                ident=f"{TYPOGRAPHY_ID_PREFIX}{ordinal:06d}",
                rend=str(item["rend"]),
                syntax=str(item["syntax"]),
                start_line=int(item["start_line"]),
                start_char=int(item["start_char"]),
                end_line=int(item["end_line"]),
                end_char=int(item["end_char"]),
                parts=tuple(
                    (
                        int(part["line"]),
                        int(part["start_char"]),
                        int(part["end_char"]),
                    )
                    for part in item["parts"]
                ),
            )
        )

    # The current source has disjoint typography intervals.  Recording this
    # fact keeps an accidental new overlapping interpretation fail-closed.
    intervals: list[tuple[int, int, int, str]] = [
        (line, start, end, span.ident)
        for span in typed
        for line, start, end in span.nonempty_parts
    ]
    for previous, current in zip(
        sorted(intervals, key=lambda item: (item[0], item[1], item[2])),
        sorted(intervals, key=lambda item: (item[0], item[1], item[2]))[1:],
        strict=False,
    ):
        if previous[0] == current[0] and previous[2] > current[1]:
            raise ValueError(
                f"Lightfoot source typography intervals overlap at line {current[0]}"
            )

    counts: dict[str, int] = {}
    for span in typed:
        counts[span.rend] = counts.get(span.rend, 0) + 1
    underscore_spans = [span for span in typed if span.syntax == "underscore"]
    underscore_role_counts = {
        role: sum(span.rend == role for span in underscore_spans)
        for role in ("letter-spaced", "italic", "source-underscore-emphasis")
    }
    mixed_underscore_spans = [
        {
            "id": span.ident,
            "start_line": span.start_line,
            "start_char": span.start_char,
            "end_line": span.end_line,
            "end_char": span.end_char,
            "text": "\n".join(
                lines[line - 1][start:end] for line, start, end in span.parts
            ),
            "reason": "mixed Greek and Latin underscore text has no separate source convention",
        }
        for span in underscore_spans
        if span.rend == "source-underscore-emphasis"
    ]
    if underscore_role_counts != {
        "letter-spaced": 261,
        "italic": 3_408,
        "source-underscore-emphasis": 3,
    } or len(mixed_underscore_spans) != 3:
        raise ValueError("Lightfoot underscore script-role census drifted")
    literal_caret_counts: dict[str, int] = {}
    nonnumeric_caret_counts: dict[str, int] = {}
    for item in nonnumeric_caret_markers:
        category = str(item["category"])
        nonnumeric_caret_counts[category] = nonnumeric_caret_counts.get(category, 0) + 1
    for item in literal_carets:
        category = str(item["category"])
        literal_caret_counts[category] = literal_caret_counts.get(category, 0) + 1
    literals = {
        "quoted_underscores": literal_underscores,
        "bare_subscripts": literal_bare_subscripts,
        "equals": literal_equals,
        # Keep all nonnumeric caret markers available to accountability
        # consumers.  ``rendered`` distinguishes the 105 source labels that
        # receive superscript hi from the three Greek spelling markers that
        # remain literal.
        "carets": nonnumeric_caret_markers,
        "literal_carets": literal_carets,
    }
    census = {
        "source_sha256": SOURCE_SHA256,
        "source_bytes": SOURCE_BYTES,
        "line_count": len(lines),
        "span_count": len(typed),
        "part_count": sum(len(span.nonempty_parts) for span in typed),
        "cross_line_span_count": sum(span.start_line != span.end_line for span in typed),
        "counts": dict(sorted(counts.items())),
        "underscore_role_counts": underscore_role_counts,
        "literal_counts": {
            "quoted_underscore_mentions": len(literal_underscores),
            "bare_manuscript_subscripts": len(literal_bare_subscripts),
            "standalone_equals": len(literal_equals),
            "total_caret_tokens": len(numeric_carets) + len(nonnumeric_caret_markers),
            "numeric_caret_tokens": len(numeric_carets),
            "nonnumeric_carets": len(nonnumeric_caret_markers),
            "nonnumeric_caret_rendered": sum(
                bool(item["rendered"]) for item in nonnumeric_caret_markers
            ),
            "literal_nonnumeric_carets": len(literal_carets),
            "nonnumeric_caret_kinds": dict(sorted(nonnumeric_caret_counts.items())),
            "literal_caret_kinds": dict(sorted(literal_caret_counts.items())),
        },
        "source_anchors": {
            "cross_line_underscore": {
                "start": "37:64",
                "end": "38:8",
                "text": "_μου\nγίνεσθε_",
                "rend": "letter-spaced",
            },
            "blackletter": {
                "start": f"{black_start_line}:{black_start}",
                "end": f"{black_end_line}:{black_end_text_start + len(BLACKLETTER_END_TEXT)}",
                "text": "=blackletter\ntext=",
            },
            "line_20655_uncial": {
                "line": 20_655,
                "backslash_count": lines[20_655 - 1].count("\\"),
            },
        },
        "mixed_script_underscore_spans": mixed_underscore_spans,
        "literals": literals,
        "coverage_policy": {
            "numeric_carets": "superscript hi spans",
            "greek_underscore_spans": (
                "Greek-only underscore spans are gesperrt source emphasis recorded "
                "as letter-spaced; "
                "the delimiters remain literal text and no spaces are inserted"
            ),
            "mixed_script_underscore_spans": (
                "mixed Greek and Latin underscore spans use "
                "source-underscore-emphasis because the source does not resolve "
                "a narrower printed role"
            ),
            "nonnumeric_carets": (
                "ASCII labels, stars, and braced sigla receive superscript hi; "
                "three Greek embedded markers remain literal and all are recorded"
            ),
            "bare_subscripts": "literal manuscript notation, recorded and not normalized",
            "quoted_underscores": "literal delimiter mentions in the transcriber note",
            "standalone_equals": "literal source notation without a paired typography span",
        },
    }
    return typed, census


def _public_span(span: _ExpectedSpan, lines: list[str]) -> dict[str, Any]:
    parts = [
        {
            "id": (
                span.ident
                if len(span.parts) == 1
                else f"{span.ident}-part-{ordinal:02d}"
            ),
            "line": line,
            "start_char": start,
            "end_char": end,
            "text": lines[line - 1][start:end],
            "n": f"{line}:{start}-{end}",
        }
        for ordinal, (line, start, end) in enumerate(span.parts, 1)
    ]
    if len(parts) > 1:
        for part in parts:
            part["corresp"] = f"#{span.ident}"
    return {
        "id": span.ident,
        "rend": span.rend,
        "syntax": span.syntax,
        "start_line": span.start_line,
        "start_char": span.start_char,
        "end_line": span.end_line,
        "end_char": span.end_char,
        "text": "\n".join(part["text"] for part in parts),
        "parts": parts,
    }


def discover_source_spans(lines: Sequence[str]) -> list[dict[str, Any]]:
    """Return the independent source-located typography inventory."""

    values = _source_lines(lines)
    spans, _ = _inventory(values)
    return [_public_span(span, values) for span in spans]


def source_census(lines: Sequence[str]) -> dict[str, Any]:
    """Return source pins, feature counts, literal exceptions, and policy."""

    values = _source_lines(lines)
    _, census = _inventory(values)
    return census


def _carrier_inventory(root: etree._Element, lines: list[str]) -> dict[int, etree._Element]:
    carriers: dict[int, etree._Element] = {}
    for node in root.iter():
        if not isinstance(node.tag, str) or node.get("type") != SOURCE_LINE_TYPE:
            continue
        raw_number = node.get("n")
        if raw_number is None or not raw_number.isdigit() or str(int(raw_number)) != raw_number:
            raise ValueError("Lightfoot source-line carrier has no canonical numeric n")
        line = int(raw_number)
        if not 1 <= line <= len(lines):
            raise ValueError(f"Lightfoot source-line carrier is outside source at line {line}")
        if line in carriers:
            raise ValueError(f"Lightfoot source-line carrier is duplicated at line {line}")
        if node.tag not in SOURCE_LINE_TAGS:
            raise ValueError(f"Lightfoot source-line carrier has unsupported tag at line {line}")
        carriers[line] = node
    expected = set(range(1, len(lines) + 1))
    if set(carriers) != expected:
        missing = sorted(expected - set(carriers))
        extra = sorted(set(carriers) - expected)
        raise ValueError(
            f"Lightfoot source-line carrier census drifted (missing={missing[:3]}, extra={extra[:3]})"
        )
    for line, carrier in carriers.items():
        if "".join(carrier.itertext()) != lines[line - 1]:
            raise ValueError(f"Lightfoot source-line text drifted at line {line}")
        parent = carrier.getparent()
        while parent is not None:
            if parent.get("type") == SOURCE_LINE_TYPE:
                raise ValueError(f"Lightfoot source-line carriers are nested at line {line}")
            parent = parent.getparent()
    return carriers


def _text_slots(
    carrier: etree._Element,
) -> tuple[
    list[tuple[etree._Element, int, int, bool]],
    dict[tuple[etree._Element, bool], tuple[int, int]],
]:
    """Map every content text node to its source-line character interval."""

    slots: list[tuple[etree._Element, int, int, bool]] = []
    by_node: dict[tuple[etree._Element, bool], tuple[int, int]] = {}
    cursor = 0

    def visit(node: etree._Element) -> None:
        nonlocal cursor
        if node.text:
            start = cursor
            cursor += len(node.text)
            end = cursor
            slots.append((node, start, end, True))
            by_node[(node, True)] = (start, end)
        for child in node:
            visit(child)
            if child.tail:
                start = cursor
                cursor += len(child.tail)
                end = cursor
                slots.append((child, start, end, False))
                by_node[(child, False)] = (start, end)

    visit(carrier)
    if cursor != len("".join(carrier.itertext())):
        raise ValueError("Lightfoot source-line text slot census drifted")
    return slots, by_node


def _content_positions(
    node: etree._Element,
    by_node: dict[tuple[etree._Element, bool], tuple[int, int]],
) -> list[int]:
    positions: list[int] = []

    def visit(current: etree._Element) -> None:
        if current.text:
            try:
                start, end = by_node[(current, True)]
            except KeyError as exc:
                raise ValueError("Lightfoot typography text node is outside its source carrier") from exc
            positions.extend(range(start, end))
        for child in current:
            visit(child)
            if child.tail:
                try:
                    start, end = by_node[(child, False)]
                except KeyError as exc:
                    raise ValueError("Lightfoot typography tail is outside its source carrier") from exc
                positions.extend(range(start, end))

    visit(node)
    return positions


def _source_carrier_for(
    node: etree._Element,
    carrier_by_node: dict[etree._Element, tuple[int, etree._Element]],
) -> tuple[int, etree._Element]:
    matches: list[tuple[int, etree._Element]] = []
    parent = node.getparent()
    while parent is not None:
        if parent in carrier_by_node:
            matches.append(carrier_by_node[parent])
        parent = parent.getparent()
    if len(matches) != 1:
        raise ValueError("Lightfoot typography hi must belong to exactly one source-line carrier")
    return matches[0]


def _observed_his(
    root: etree._Element,
    lines: list[str],
    carriers: dict[int, etree._Element],
) -> list[_ObservedHi]:
    by_carrier: dict[int, dict[tuple[int, bool], tuple[int, int]]] = {}
    carrier_by_node = {carrier: (line, carrier) for line, carrier in carriers.items()}
    for line, carrier in carriers.items():
        _, by_carrier[line] = _text_slots(carrier)

    observed: list[_ObservedHi] = []
    ids: set[str] = set()
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag != HI:
            if etree.QName(node).localname == "hi":
                raise ValueError("Lightfoot typography uses an unqualified hi element")
            continue
        attrs = set(node.attrib)
        allowed = {XML_ID, "rend", "n", "corresp"}
        if attrs - allowed:
            raise ValueError(f"Lightfoot typography hi has unsupported attributes: {sorted(attrs - allowed)}")
        ident = node.get(XML_ID)
        if ident is None or not ident or ident in ids:
            raise ValueError("Lightfoot typography hi IDs must be present and unique")
        ids.add(ident)
        rend = node.get("rend")
        if rend not in RENDS:
            raise ValueError(f"Lightfoot typography hi has unsupported rend {rend!r}")
        raw_corresp = node.get("corresp")
        if raw_corresp is not None:
            if not _SPAN_ID_RE.fullmatch(raw_corresp[1:]) or not raw_corresp.startswith("#"):
                raise ValueError("Lightfoot typography corresp must name one canonical source span")
            target = raw_corresp[1:]
        else:
            target = ident
        raw_n = node.get("n")
        if raw_n is None:
            raise ValueError("Lightfoot typography hi has no source offset n")
        match = _N_RE.fullmatch(raw_n)
        if match is None:
            raise ValueError(f"Lightfoot typography hi n is not a source offset: {raw_n!r}")
        declared_line, declared_start, declared_end = (int(value) for value in match.groups())
        if declared_start >= declared_end:
            raise ValueError("Lightfoot typography hi n must have a nonempty interval")
        line, carrier = _source_carrier_for(node, carrier_by_node)
        if declared_line != line:
            raise ValueError("Lightfoot typography hi n names the wrong source line")
        positions = _content_positions(node, by_carrier[line])
        if not positions:
            raise ValueError("Lightfoot typography hi has no represented source text")
        position_set = frozenset(positions)
        if len(position_set) != len(positions):
            raise ValueError("Lightfoot typography hi repeats a source text node")
        start = min(position_set)
        end = max(position_set) + 1
        if position_set != frozenset(range(start, end)):
            raise ValueError("Lightfoot typography hi source interval is not contiguous")
        if (declared_start, declared_end) != (start, end):
            raise ValueError("Lightfoot typography hi n disagrees with its actual source interval")
        text = "".join(node.itertext())
        if text != lines[line - 1][start:end]:
            raise ValueError("Lightfoot typography hi text disagrees with its source interval")
        observed.append(
            _ObservedHi(
                node=node,
                ident=ident,
                target=target,
                rend=rend,
                line=line,
                start=start,
                end=end,
                positions=position_set,
            )
        )
    return observed


def _verify_coverage(expected: list[_ExpectedSpan], observed: list[_ObservedHi]) -> None:
    by_id = {span.ident: span for span in expected}
    groups: dict[str, list[_ObservedHi]] = defaultdict(list)
    for item in observed:
        if item.target not in by_id:
            raise ValueError(f"Lightfoot typography hi points to unknown source span {item.target}")
        span = by_id[item.target]
        if item.rend != span.rend:
            raise ValueError(f"Lightfoot typography role drifted for {item.target}")
        groups[item.target].append(item)

    if len(observed) == 0:
        raise ValueError("Lightfoot typography has no native hi spans")
    for span in expected:
        actual = groups.get(span.ident, [])
        if not actual:
            raise ValueError(f"Lightfoot typography source span is unrepresented: {span.ident}")
        expected_by_line = span.by_line
        actual_by_line: dict[int, set[int]] = defaultdict(set)
        previous_by_line: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for item in actual:
            if item.line not in expected_by_line:
                raise ValueError(f"Lightfoot typography span is on the wrong line: {span.ident}")
            for start, end in previous_by_line[item.line]:
                if start < item.end and item.start < end:
                    raise ValueError(f"Lightfoot typography fragments overlap: {span.ident}")
            previous_by_line[item.line].append((item.start, item.end))
            actual_by_line[item.line].update(item.positions)
        if {
            line: frozenset(values) for line, values in actual_by_line.items()
        } != expected_by_line:
            raise ValueError(f"Lightfoot typography source coverage drifted for {span.ident}")

        # The canonical span ID must be an actual source-first fragment.  A
        # set of continuations that all point at the base but has no base
        # element is a dangling graph even when its text union is complete.
        bases = [item for item in actual if item.ident == span.ident]
        if len(bases) != 1:
            raise ValueError(f"Lightfoot typography span has no unique base fragment: {span.ident}")
        first = min(actual, key=lambda item: (item.line, item.start, item.end, item.ident))
        base = bases[0]
        if first is not base or base.node.get("corresp") is not None:
            raise ValueError(f"Lightfoot typography base fragment is not source-first: {span.ident}")
        for item in actual:
            if item is base:
                continue
            if item.node.get("corresp") != f"#{span.ident}":
                raise ValueError(f"Lightfoot typography continuation link is unresolved: {span.ident}")


def _ref_seg_signature(root: etree._Element) -> list[tuple[Any, ...]]:
    result: list[tuple[Any, ...]] = []
    for node in root.iter():
        if not isinstance(node.tag, str) or etree.QName(node).localname not in {"ref", "seg"}:
            continue
        children = tuple(
            (
                child.tag,
                tuple(sorted(child.attrib.items())),
            )
            for child in node
            if child.tag != HI
        )
        result.append(
            (
                node.tag,
                tuple(sorted(node.attrib.items())),
                "".join(node.itertext()),
                children,
            )
        )
    return result


def _unwrap_hi(node: etree._Element) -> None:
    parent = node.getparent()
    if parent is None:
        raise ValueError("Lightfoot typography hi cannot be the tree root")
    index = parent.index(node)

    def append_before(text: str) -> None:
        if not text:
            return
        if index == 0:
            parent.text = (parent.text or "") + text
        else:
            previous = parent[index - 1]
            previous.tail = (previous.tail or "") + text

    append_before(node.text or "")
    children = list(node)
    for child in children:
        node.remove(child)
        parent.insert(index, child)
        index += 1
    if node.tail:
        if index == 0:
            parent.text = (parent.text or "") + node.tail
        else:
            previous = parent[index - 1]
            previous.tail = (previous.tail or "") + node.tail
    parent.remove(node)


def _normalize_clone(root: etree._Element) -> etree._Element:
    clone = deepcopy(root)
    for node in list(clone.iter(HI))[::-1]:
        _unwrap_hi(node)
    if any(node.tag == HI for node in clone.iter()):
        raise ValueError("Lightfoot typography hi removal was incomplete")
    return clone


def verify_and_normalize_typography(root: etree._Element, lines: Sequence[str]) -> etree._Element:
    """Verify native typography and return a private clone without ``hi``.

    The input ``root`` is never changed.  A ``ValueError`` identifies any
    missing, invented, mislinked, misrended, shifted, or text-changing span.
    The returned clone keeps the source-line carriers and all non-typography
    ``ref``/``seg`` nodes and text in their original order.
    """

    if not isinstance(root, etree._Element):
        raise TypeError("Lightfoot typography root must be an lxml element")
    source = _source_lines(lines)
    expected, _ = _inventory(source)
    original_bytes = etree.tostring(root, encoding="utf-8")
    carriers = _carrier_inventory(root, source)
    before_ref_seg = _ref_seg_signature(root)
    observed = _observed_his(root, source, carriers)
    _verify_coverage(expected, observed)
    clone = _normalize_clone(root)
    if etree.tostring(root, encoding="utf-8") != original_bytes:
        raise ValueError("Lightfoot typography verifier modified its input tree")
    if _ref_seg_signature(clone) != before_ref_seg:
        raise ValueError("Lightfoot typography normalization changed ref/seg content")
    normalized_carriers = _carrier_inventory(clone, source)
    for line, carrier in normalized_carriers.items():
        if "".join(carrier.itertext()) != source[line - 1]:
            raise ValueError(f"Lightfoot normalized source-line text drifted at line {line}")
    return clone


__all__ = [
    "SOURCE_BYTES",
    "SOURCE_LINE_COUNT",
    "SOURCE_SHA256",
    "discover_source_spans",
    "source_census",
    "verify_and_normalize_typography",
]
