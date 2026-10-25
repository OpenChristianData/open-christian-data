"""Source-pinned typography discovery and TEI ``hi`` post-pass for Lightfoot.

The retained Lightfoot witness is a line-oriented text file.  This helper
keeps the source syntax in the rendered text and adds native TEI ``hi``
elements around the exact source slices.  It deliberately knows only the
source transcription conventions needed by this witness; it does not import
the Lightfoot producer or oracle.

``discover_spans`` returns JSON-shaped records so a producer and an
independent checker can consume the same coordinate vocabulary without
sharing implementation state.  ``apply_typography`` is a post-pass: it
locates existing ``source-line`` carriers, wraps text-node slices in place,
and leaves the existing ``seg``/``ref`` carriers and their attributes intact.

The source's transcriber note distinguishes Greek gesperrt from ordinary
italic type.  Greek-only underscore spans therefore use
``rend="letter-spaced"``; Latin-only spans use ``rend="italic"``; mixed-script
spans retain the honest generic ``rend="source-underscore-emphasis"`` because
the witness does not resolve their printed font.
"""

from __future__ import annotations

from collections.abc import Sequence
import re
from typing import Any
import unicodedata

from lxml import etree


TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_LINE_TYPE = "source-line"
TYPOGRAPHY_ID_PREFIX = "lightfoot-typography-"

# These two underscores are quoted examples in the transcriber note.  They
# are source-located literal punctuation, not italic delimiters.  The
# coordinates are checked against the text before they are excluded.
LITERAL_UNDERSCORE_COORDINATES = {
    (33, 32),
    (36, 67),
}

# The note at lines 52--55 explicitly identifies this one single-equals pair
# as blackletter.  Other same-line single-equals pairs are retained as the
# source's generic equals emphasis because the transcription does not provide
# a more specific source-located distinction for them.
BLACKLETTER_COORDINATES = ((54, 49), (55, 4))

_BRACED_SUBSCRIPT_RE = re.compile(r"_\{\d+\}")
_MANUSCRIPT_SUBSCRIPT_RE = re.compile(r"_[0-9]+\*?")
_NUMERIC_CARET_RE = re.compile(r"\^\{\d+\}|\^\d+")
# ASCII letter and star caret labels are superscripted source sigla.  Greek
# letters are intentionally absent: the three embedded Greek carets in this
# witness mark source spelling/accent notation rather than raised characters.
_SUPPORTED_CARET_RE = re.compile(r"\^\{[^}]*\}|\^\d+|\^[A-Za-z*]")
_ANY_CARET_RE = re.compile(r"\^(?:\{[^}]*\}|[^\s])")
_EQUALS_RUN_RE = re.compile(r"=+")


def _contains_script(text: str, script: str) -> bool:
    return any(script in unicodedata.name(character, "") for character in text)


def _underscore_rend(text: str) -> str:
    """Return the narrowest source-supported role for an underscore span."""

    has_greek = _contains_script(text, "GREEK")
    has_latin = _contains_script(text, "LATIN")
    if has_greek and not has_latin:
        return "letter-spaced"
    if has_greek and has_latin:
        # Headings such as ``_On the meaning of πλήρωμα_`` mix scripts.  The
        # witness identifies the delimiter convention but does not identify
        # which printed font applies to the whole mixed span.
        return "source-underscore-emphasis"
    return "italic"


def _tag(name: str) -> str:
    return f"{{{TEI}}}{name}"


def _xml_id(node: etree._Element) -> str | None:
    return node.get(f"{{{XML}}}id")


def _line_texts(lines: Sequence[str]) -> list[str]:
    if not isinstance(lines, Sequence):
        raise TypeError("Lightfoot typography lines must be a string sequence")
    result = list(lines)
    if any(not isinstance(value, str) for value in result):
        raise TypeError("Lightfoot typography lines must contain only strings")
    if any("\r" in value or "\n" in value for value in result):
        raise ValueError("Lightfoot typography lines must not contain line endings")
    return result


def _record(
    *,
    lines: list[str],
    rend: str,
    syntax: str,
    start_line: int,
    start_char: int,
    end_line: int,
    end_char: int,
) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    for line_number in range(start_line, end_line + 1):
        start = start_char if line_number == start_line else 0
        end = end_char if line_number == end_line else len(lines[line_number - 1])
        if end < start or end > len(lines[line_number - 1]):
            raise ValueError(f"Lightfoot typography span has invalid coordinates at line {line_number}")
        parts.append(
            {
                "line": line_number,
                "start_char": start,
                "end_char": end,
                "text": lines[line_number - 1][start:end],
            }
        )
    return {
        "rend": rend,
        "syntax": syntax,
        "start_line": start_line,
        "start_char": start_char,
        "end_line": end_line,
        "end_char": end_char,
        "text": "\n".join(str(part["text"]) for part in parts),
        "parts": parts,
    }


def _set_ids(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for ordinal, span in enumerate(spans, 1):
        ident = f"{TYPOGRAPHY_ID_PREFIX}{ordinal:06d}"
        span["id"] = ident
        parts = span["parts"]
        if len(parts) == 1:
            parts[0]["id"] = ident
        else:
            for part_ordinal, part in enumerate(parts, 1):
                part["id"] = f"{ident}-part-{part_ordinal:02d}"
                part["corresp"] = f"#{ident}"
        for part in parts:
            part["n"] = f"{part['line']}:{part['start_char']}-{part['end_char']}"
    return spans


def _single_equals_pairs(lines: list[str]) -> list[tuple[int, int, int, int]]:
    """Return source-located same-line single-equals delimiter pairs.

    Standalone equality signs in prose are deliberately left literal.  The
    source gives an explicit cross-line blackletter example; all remaining
    delimiter pairs are required to close on their own source line.  This
    keeps ``[= Greek]`` translation notation from becoming typography.
    """
    pairs: list[tuple[int, int, int, int]] = []
    blackletter = set(BLACKLETTER_COORDINATES)
    for line_number, value in enumerate(lines, 1):
        positions = [
            match.start()
            for match in _EQUALS_RUN_RE.finditer(value)
            if len(match.group()) == 1 and (line_number, match.start()) not in blackletter
        ]
        if len(positions) < 2 or len(positions) % 2:
            continue
        for first, second in zip(positions[::2], positions[1::2], strict=True):
            pairs.append((line_number, first, line_number, second + 1))
    return pairs


def _non_numeric_caret_markers(lines: list[str]) -> list[dict[str, Any]]:
    """Record nonnumeric caret annotations and their rendering disposition.

    Caret syntax for numeric values, ASCII source labels, stars, and braced
    sigla is the transcriber's superscript convention and is emitted as
    ``hi rend="superscript"``.  The three carets embedded inside Greek words
    are source spelling/accent notation rather than raised characters.  They
    remain literal, and all nonnumeric coordinates are returned so an
    independent checker can verify that boundary.
    """
    records: list[dict[str, Any]] = []
    for line_number, value in enumerate(lines, 1):
        for match in _ANY_CARET_RE.finditer(value):
            token = match.group()
            if _NUMERIC_CARET_RE.fullmatch(token):
                continue
            if token == "^*":
                category = "star"
                reason = "source manuscript correction sigil"
            elif token.startswith("^{"):
                category = "braced-nonnumeric"
                reason = "source manuscript or apparatus label"
            elif len(token) == 2 and (
                "A" <= token[1] <= "Z" or "a" <= token[1] <= "z"
            ):
                category = "ascii-letter"
                reason = "source sidenote or manuscript label"
            else:
                category = "greek-letter"
                reason = "Greek embedded caret text"
            records.append(
                {
                    "line": line_number,
                    "start_char": match.start(),
                    "end_char": match.end(),
                    "token": token,
                    "category": category,
                    "reason": reason,
                    "rendered": category != "greek-letter",
                }
            )
    return records


def discover_spans(lines: Sequence[str]) -> list[dict[str, Any]]:
    """Discover all source typography spans with 1-based line coordinates.

    Character offsets are Python string offsets and the end offset is
    exclusive.  Every returned record includes delimiter-inclusive source
    text and one part per source line.  The source syntax remains in each
    part; callers should wrap the slice rather than normalize it.
    """
    source = _line_texts(lines)
    spans: list[dict[str, Any]] = []

    # Occupied marker coordinates keep subscript and manuscript notation from
    # being mistaken for underscore italics.  The two quoted note examples
    # are checked by text shape below before they are excluded.
    excluded: set[tuple[int, int]] = set()
    for line_number, value in enumerate(source, 1):
        for match in _BRACED_SUBSCRIPT_RE.finditer(value):
            spans.append(
                _record(
                    lines=source,
                    rend="subscript",
                    syntax="braced-subscript",
                    start_line=line_number,
                    start_char=match.start(),
                    end_line=line_number,
                    end_char=match.end(),
                )
            )
            excluded.update((line_number, position) for position in range(match.start(), match.end()))
        for match in _MANUSCRIPT_SUBSCRIPT_RE.finditer(value):
            excluded.update((line_number, position) for position in range(match.start(), match.end()))
        for match in _SUPPORTED_CARET_RE.finditer(value):
            spans.append(
                _record(
                    lines=source,
                    rend="superscript",
                    syntax="caret",
                    start_line=line_number,
                    start_char=match.start(),
                    end_line=line_number,
                    end_char=match.end(),
                )
            )

    for line_number, position in LITERAL_UNDERSCORE_COORDINATES:
        if line_number > len(source):
            # Short synthetic sequences are useful for focused helper tests;
            # the Lightfoot-specific note anchors simply are not in scope.
            continue
        value = source[line_number - 1] if line_number <= len(source) else ""
        if (
            value[position : position + 1] == "_"
            and value[position - 1 : position] == "‘"
            and value[position + 1 : position + 2] == "’"
        ):
            excluded.add((line_number, position))
        else:
            raise ValueError(f"Lightfoot quoted underscore anchor drifted at line {line_number}")

    underscore_markers = [
        (line_number, position)
        for line_number, value in enumerate(source, 1)
        for position, character in enumerate(value)
        if character == "_" and (line_number, position) not in excluded
    ]
    if len(underscore_markers) % 2:
        raise ValueError("Lightfoot underscore typography markers are unbalanced")
    for (start_line, start_char), (end_line, end_char_inclusive) in zip(
        underscore_markers[::2], underscore_markers[1::2], strict=True
    ):
        span = _record(
            lines=source,
            rend="italic",
            syntax="underscore",
            start_line=start_line,
            start_char=start_char,
            end_line=end_line,
            end_char=end_char_inclusive + 1,
        )
        span["rend"] = _underscore_rend(str(span["text"]))
        spans.append(span)

    equals_tokens: list[tuple[int, int, int]] = []
    for line_number, value in enumerate(source, 1):
        equals_tokens.extend(
            (line_number, match.start(), len(match.group()))
            for match in _EQUALS_RUN_RE.finditer(value)
            if len(match.group()) == 2
        )
    if len(equals_tokens) % 2:
        raise ValueError("Lightfoot double-equals typography markers are unbalanced")
    for (start_line, start_char, _), (end_line, end_char, _) in zip(
        equals_tokens[::2], equals_tokens[1::2], strict=True
    ):
        spans.append(
            _record(
                lines=source,
                rend="uncial",
                syntax="double-equals",
                start_line=start_line,
                start_char=start_char,
                end_line=end_line,
                end_char=end_char + 2,
            )
        )

    blackletter_start, blackletter_end = BLACKLETTER_COORDINATES
    if len(source) >= max(line for line, _ in BLACKLETTER_COORDINATES):
        if (
            blackletter_start[0] <= len(source)
            and blackletter_end[0] <= len(source)
            and source[blackletter_start[0] - 1][blackletter_start[1] :].startswith("=blackletter")
            and source[blackletter_end[0] - 1][blackletter_end[1] - 4 : blackletter_end[1] + 1] == "text="
        ):
            spans.append(
                _record(
                    lines=source,
                    rend="blackletter",
                    syntax="single-equals-blackletter",
                    start_line=blackletter_start[0],
                    start_char=blackletter_start[1],
                    end_line=blackletter_end[0],
                    end_char=blackletter_end[1] + 1,
                )
            )
        else:
            raise ValueError("Lightfoot blackletter source anchor drifted")

    for start_line, start_char, end_line, end_char in _single_equals_pairs(source):
        spans.append(
            _record(
                lines=source,
                rend="emphasis",
                syntax="single-equals-emphasis",
                start_line=start_line,
                start_char=start_char,
                end_line=end_line,
                end_char=end_char,
            )
        )

    spans.sort(
        key=lambda span: (
            int(span["start_line"]),
            int(span["start_char"]),
            -int(span["end_line"]),
            -int(span["end_char"]),
            str(span["syntax"]),
        )
    )
    return _set_ids(spans)


def _text_slots(carrier: etree._Element) -> list[dict[str, Any]]:
    slots: list[dict[str, Any]] = []
    cursor = 0

    def visit(node: etree._Element) -> None:
        nonlocal cursor
        if node.text:
            start = cursor
            cursor += len(node.text)
            slots.append({"owner": node, "is_text": True, "start": start, "end": cursor, "text": node.text})
        for child in node:
            visit(child)
            if child.tail:
                start = cursor
                cursor += len(child.tail)
                slots.append({"owner": child, "is_text": False, "start": start, "end": cursor, "text": child.tail})

    visit(carrier)
    return slots


def _wrap_slot(
    slot: dict[str, Any],
    local_start: int,
    local_end: int,
    attrs: dict[str, str],
) -> etree._Element:
    text = str(slot["text"])
    if not 0 <= local_start < local_end <= len(text):
        raise ValueError("Lightfoot typography text-node slice is out of bounds")
    owner: etree._Element = slot["owner"]
    selected = text[local_start:local_end]
    prefix = text[:local_start]
    suffix = text[local_end:]
    hi = etree.Element(_tag("hi"), attrs)
    hi.text = selected
    if bool(slot["is_text"]):
        owner.text = prefix or None
        owner.insert(0, hi)
        hi.tail = suffix or None
    else:
        parent = owner.getparent()
        if parent is None:
            raise ValueError("Lightfoot typography tail has no parent")
        owner.tail = prefix or None
        parent.insert(parent.index(owner) + 1, hi)
        hi.tail = suffix or None
    return hi


def _carrier_inventory(root: etree._Element, line_count: int) -> dict[int, etree._Element]:
    carriers: dict[int, etree._Element] = {}
    for node in root.iter():
        if node.get("type") != SOURCE_LINE_TYPE:
            continue
        raw_number = node.get("n")
        if raw_number is None or not raw_number.isdigit():
            raise ValueError("Lightfoot source-line carrier has no numeric n")
        line = int(raw_number)
        if line < 1 or line > line_count:
            raise ValueError(f"Lightfoot source-line carrier is outside source at line {line}")
        if line in carriers:
            raise ValueError(f"Lightfoot source-line carrier is duplicated at line {line}")
        carriers[line] = node
    expected = set(range(1, line_count + 1))
    if set(carriers) != expected:
        missing = sorted(expected - set(carriers))
        extra = sorted(set(carriers) - expected)
        raise ValueError(f"Lightfoot source-line carrier census drifted (missing={missing[:3]}, extra={extra[:3]})")
    return carriers


def apply_typography(root: etree._Element, lines: Sequence[str]) -> dict[str, Any]:
    """Wrap discovered source typography in native TEI ``hi`` elements.

    The returned inventory contains the source span records plus aggregate
    counts and generated part identities.  The operation is fail-closed when
    source-line carriers are missing, duplicated, already changed, or when a
    formatting interval would require an unsupported partial overlap.
    """
    source = _line_texts(lines)
    spans = discover_spans(source)
    non_numeric_carets = _non_numeric_caret_markers(source)
    carriers = _carrier_inventory(root, len(source))
    for line, carrier in carriers.items():
        if "".join(carrier.itertext()) != source[line - 1]:
            raise ValueError(f"Lightfoot source-line text drifted before typography at line {line}")
    existing_ids = {
        ident
        for node in root.iter(_tag("hi"))
        if (ident := _xml_id(node)) is not None and ident.startswith(TYPOGRAPHY_ID_PREFIX)
    }
    if existing_ids:
        raise ValueError("Lightfoot typography is already applied")

    # Outer spans are applied first so a later nested span naturally becomes a
    # child hi in the same source text node.  Equal-length non-overlapping
    # spans retain source order.
    application_order = sorted(
        spans,
        key=lambda span: (
            -(
                (int(span["end_line"]) - int(span["start_line"])) * 1_000_000
                + int(span["end_char"])
                - int(span["start_char"])
            ),
            int(span["start_line"]),
            int(span["start_char"]),
            str(span["id"]),
        ),
    )
    generated: dict[str, etree._Element] = {}
    generated_meta: dict[str, dict[str, Any]] = {}
    for span in application_order:
        parts = span["parts"]
        rendered_parts: list[dict[str, Any]] = []
        for part in reversed(parts):
            line = int(part["line"])
            start = int(part["start_char"])
            end = int(part["end_char"])
            if start == end:
                continue
            carrier = carriers[line]
            slots = _text_slots(carrier)
            overlaps = [
                slot
                for slot in slots
                if int(slot["start"]) < end and int(slot["end"]) > start
            ]
            if not overlaps:
                raise ValueError(f"Lightfoot typography slice is not represented at line {line}")
            # A source-line slice can cross an existing ref/seg text boundary.
            # Each resulting hi is a deterministic part of the same source
            # span, linked by corresp.  Allocate IDs in source order while
            # applying the XML edits from right to left.
            piece_count = len(overlaps)
            part_records: list[dict[str, Any]] = []
            for piece_ordinal, slot in enumerate(overlaps, 1):
                overlap_start = max(start, int(slot["start"]))
                overlap_end = min(end, int(slot["end"]))
                if overlap_start >= overlap_end:
                    continue
                part_records.append(
                    {
                        "slot": slot,
                        "start": overlap_start,
                        "end": overlap_end,
                        "ordinal": piece_ordinal,
                    }
                )
            for piece in reversed(part_records):
                slot = piece["slot"]
                overlap_start = int(piece["start"])
                overlap_end = int(piece["end"])
                # Source records have one ID per physical line part, but a
                # rendered span can split further at existing ref/seg/font
                # boundaries.  The first rendered fragment owns the span ID;
                # every continuation gets a distinct ID and points back to
                # that real XML node.  This prevents orphan fragment links.
                source_part_is_first = part is parts[0]
                piece_is_first = int(piece["ordinal"]) == 1
                if source_part_is_first and piece_is_first:
                    ident = str(span["id"])
                elif piece_count == 1:
                    ident = str(part["id"])
                else:
                    ident = f"{part['id']}-piece-{int(piece['ordinal']):02d}"
                n = f"{line}:{overlap_start}-{overlap_end}"
                attrs = {
                    f"{{{XML}}}id": ident,
                    "rend": str(span["rend"]),
                    "n": n,
                }
                if not (source_part_is_first and piece_is_first):
                    attrs["corresp"] = f"#{span['id']}"
                if ident in generated:
                    raise ValueError(f"Lightfoot typography part ID repeated: {ident}")
                generated[ident] = _wrap_slot(
                    slot,
                    overlap_start - int(slot["start"]),
                    overlap_end - int(slot["start"]),
                    attrs,
                )
                metadata = {
                    "id": ident,
                    "line": line,
                    "start_char": overlap_start,
                    "end_char": overlap_end,
                    "text": source[line - 1][overlap_start:overlap_end],
                    "n": n,
                }
                if not (source_part_is_first and piece_is_first):
                    metadata["corresp"] = f"#{span['id']}"
                generated_meta[ident] = metadata
                rendered_parts.append(metadata)
        span["rendered_parts"] = sorted(
            rendered_parts,
            key=lambda part: (int(part["line"]), int(part["start_char"]), str(part["id"])),
        )

    expected_parts = {
        str(part["id"]): (
            int(part["line"]),
            str(part["text"]),
            f"{int(part['line'])}:{int(part['start_char'])}-{int(part['end_char'])}",
        )
        for part in generated_meta.values()
    }
    if set(generated) != set(expected_parts):
        raise ValueError("Lightfoot typography part inventory drifted during application")
    for ident, (line, expected_text, expected_n) in expected_parts.items():
        node = generated[ident]
        if node.get(f"{{{XML}}}id") != ident or node.get("n") != expected_n or "".join(node.itertext()) != expected_text:
            raise ValueError(f"Lightfoot typography hi drifted for {ident}")
        if node.getparent() is None:
            raise ValueError(f"Lightfoot typography hi detached for {ident}")
        if "".join(carriers[line].itertext()) != source[line - 1]:
            raise ValueError(f"Lightfoot source-line text changed at line {line}")

    counts: dict[str, int] = {}
    lines_with_formatting: set[int] = set()
    for span in spans:
        rend = str(span["rend"])
        counts[rend] = counts.get(rend, 0) + 1
        lines_with_formatting.update(int(part["line"]) for part in span["parts"])
    return {
        "source_line_count": len(source),
        "spans": spans,
        "non_numeric_caret_markers": non_numeric_carets,
        "non_numeric_caret_count": len(non_numeric_carets),
        "span_count": len(spans),
        "part_count": len(expected_parts),
        "cross_line_span_count": sum(int(span["start_line"]) != int(span["end_line"]) for span in spans),
        "counts": dict(sorted(counts.items())),
        "lines_with_formatting": sorted(lines_with_formatting),
    }
