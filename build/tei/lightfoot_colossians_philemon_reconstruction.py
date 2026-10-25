"""Source-structured TEI reconstruction for retained PG #50857.

The retained witness is a line-oriented plain-text source, but its own layout
marks a book envelope, epistle introductions, commentary range occurrences,
Greek text, paraphrase, commentary, footnotes, sidenotes, apparatus, index,
and Project Gutenberg license material. This module keeps every source line
as an accountable TEI leaf while placing those source-native carriers around
the leaves. It intentionally does not merge repeated range labels or infer
verse joins across page contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from typing import Mapping

from lxml import etree

from ocd_kernel.reconstruction.contract import SourceManifest

CONVERTER_ID = "ocd-lightfoot-colossians-philemon-structured-source-to-tei"
CONVERTER_VERSION = "3"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"

_SOURCE_BYTES = 1_511_463
_SOURCE_SHA = "a97cb49964906a2c158a0444cfdc3b0daf13261620c919a90f1333a98ac0b913"
_RANGE_RE = re.compile(r"^[IVX]+\.\s*[\d,\s–—\-]+\]$")
_PHILEMON_RANGE_RE = re.compile(r"^[\d,\s–—\-]+\]$")
_FOOTNOTE_RE = re.compile(r"^Footnote (\d+):$")
_SIDENOTE_MARKER = "[Sidenote:"

# These are source-located display headings, rather than inferred theological
# or verse units.  The source is a fixed plain-text witness, so the coordinates
# are retained as facts and checked against the decoded text before use.
_SOURCE_HEADING_LINES = frozenset(
    {
        75,
        77,
        79,
        81,
        83,
        85,
        87,
        95,
        96,
        97,
        98,
        100,
        102,
        104,
        109,
        111,
        121,
        122,
        123,
        125,
        160,
        220,
        222,
        224,
        252,
        263,
        264,
        4171,
        4172,
        6332,
        6335,
        6336,
        10148,
        10149,
        10818,
        10828,
        10830,
        10832,
        10856,
        18354,
        19108,
        20277,
        21030,
        21180,
        22121,
        22123,
        23595,
        23600,
        23603,
        23612,
        24499,
        24587,
        25785,
        25790,
        25835,
    }
)

# These two numbered prose spans follow the Greek carrier in the source but
# are not quoted.  They are source-native paraphrases, not commentary: their
# exact coordinates and starts are checked by _source_feature_facts().
_UNQUOTED_PARAPHRASE_SPANS = (
    (12679, 12687, "20. The false teachers aimed at effecting a partial reconciliation"),
    (17721, 17723, "10. The salutations to Philemon are sent from the same persons as to the"),
)

# A critical apparatus band is set in a deeply indented Greek line between the
# source Greek carrier and the prose note.  These source-located bands must not
# be folded into the commentary carrier.
_APPARATUS_LINES = frozenset(
    {11455, 11631, 12786, 13876, 14362, 14815, 14916, 15986, 17177, 23824, 23872}
)

# These eight spans begin with a Greek lemma followed by an English gloss and
# annotation.  They look like quoted paraphrases to a quotation-only parser,
# but the retained source places them in the lemma-note layout.
_LEMMA_SPANS = (
    (12432, 12455, "17."),
    (13462, 13466, "29."),
    (13720, 13725, "4."),
    (14492, 14498, "14."),
    (15954, 15962, "2."),
    (17241, 17246, "24."),
    (18214, 18220, "16."),
    (24149, 24171, "13."),
)

# Every exact numeric bracket token is source-scanned below and joined only
# when its displayed number names one unique retained Footnote N definition.
# Source-located years and bracketed scripture verse numbers remain literal.
_FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS = (
    (3804, 32, "[1550]", "year in the source date sequence"),
    (18346, 14, "[24]", "bracketed verse number in a scripture reference list"),
)

_MIXED_SOURCE_LINE = (
    13183,
    "τοῦ σώματος αὐτοῦ",
    " An antithesis of the Apostle’s own flesh and Christ’s",
)

_PARALLEL_TABLE_ROWS = {
    "lightfoot-parallel-reading-table": (
        (18466, 18467, "label"),
        (18468, 18470, "source-text"),
        (18471, 18472, "label"),
        (18473, 18474, "source-text"),
    ),
    "lightfoot-parallel-reading-table-b": (
        (18481, 18483, "source-text"),
        (18484, 18485, "source-text"),
    ),
}


@dataclass(frozen=True, slots=True)
class _Row:
    number: int
    offset: int
    value: str
    raw: bytes


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _tei(
    name: str,
    attrs: Mapping[str, str] | None = None,
    text: str | None = None,
) -> etree._Element:
    element = etree.Element(f"{{{TEI}}}{name}")
    for key, value in (attrs or {}).items():
        element.set(f"{{{XML}}}id" if key == "xml:id" else key, value)
    element.text = text
    return element


def _source(manifest: SourceManifest) -> bytes:
    content = manifest.authority_path("retained-lightfoot-text").read_bytes()
    if len(content) != _SOURCE_BYTES or _sha(content) != _SOURCE_SHA:
        raise ValueError("Lightfoot retained witness bytes drifted")
    content.decode("utf-8")
    return content


def _lines(content: bytes) -> list[_Row]:
    if not content.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Lightfoot retained witness lost its file-initial UTF-8 BOM")
    rows: list[_Row] = []
    offset = 0
    for number, raw in enumerate(content.splitlines(keepends=True), 1):
        ending = b"\n" if raw.endswith(b"\n") else b""
        payload = raw[:-1] if ending else raw
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        # Keep the original three bytes in raw/offset accounting; the file BOM
        # declares encoding and is not part of the first readable source line.
        readable = payload[3:] if number == 1 else payload
        rows.append(_Row(number, offset, readable.decode("utf-8"), raw))
        offset += len(raw)
    if offset != len(content):
        raise ValueError("Lightfoot source line accounting does not cover final bytes")
    return rows


def _spec(
    unit_id: str,
    unit_type: str,
    start: int,
    end: int,
    parent: str | None,
    *,
    label: str | None = None,
    ordinal: int | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "id": unit_id,
        "type": unit_type,
        "start_line": start,
        "end_line": end,
        "parent": parent,
    }
    if label is not None:
        result["n"] = label
    if ordinal is not None:
        result["ordinal"] = ordinal
    return result


def _static_specs() -> list[dict[str, object]]:
    return [
        _spec("lightfoot-envelope", "gutenberg-envelope", 1, 26185, None),
        _spec("lightfoot-region-preamble", "gutenberg-preamble", 1, 29, "lightfoot-envelope"),
        _spec("lightfoot-region-transcriber-note", "transcriber-note", 30, 74, "lightfoot-envelope"),
        _spec("lightfoot-region-title-page", "title-page", 75, 159, "lightfoot-envelope"),
        _spec("lightfoot-region-preface", "preface", 160, 219, "lightfoot-envelope"),
        _spec("lightfoot-region-contents", "contents", 220, 262, "lightfoot-envelope"),
        _spec("lightfoot-region-colossians-introduction", "colossians-introduction", 263, 10813, "lightfoot-envelope"),
        _spec("lightfoot-colossians-introduction-i", "introduction-section", 263, 4170, "lightfoot-region-colossians-introduction", label="I"),
        _spec("lightfoot-colossians-introduction-ii", "introduction-section", 4171, 6331, "lightfoot-region-colossians-introduction", label="II"),
        _spec("lightfoot-essene-dissertation", "dissertation", 6332, 10147, "lightfoot-region-colossians-introduction", label="On some points connected with the Essenes"),
        _spec("lightfoot-colossians-introduction-iii", "introduction-section", 10148, 10813, "lightfoot-region-colossians-introduction", label="III"),
        _spec("lightfoot-region-colossians-frontmatter", "colossians-text-frontmatter", 10814, 10859, "lightfoot-envelope"),
        _spec("lightfoot-region-colossians-commentary", "colossians-text-commentary", 10860, 18352, "lightfoot-envelope"),
        _spec("lightfoot-region-colossians-apparatus", "colossians-apparatus", 18353, 22120, "lightfoot-envelope"),
        _spec("lightfoot-various-readings", "dissertation", 18353, 19107, "lightfoot-region-colossians-apparatus", label="On some Various Readings in the Epistle"),
        _spec("lightfoot-meaning-of-pleroma", "dissertation", 19108, 20276, "lightfoot-region-colossians-apparatus", label="On the meaning of πλήρωμα"),
        _spec("lightfoot-epistle-from-laodicea", "dissertation", 20277, 22120, "lightfoot-region-colossians-apparatus", label="The Epistle from Laodicea"),
        _spec("lightfoot-laodiceans-mss-capitula", "laodiceans-mss-and-capitula", 21030, 21179, "lightfoot-epistle-from-laodicea"),
        _spec("lightfoot-laodiceans-text-apparatus", "laodiceans-text-and-apparatus", 21180, 21346, "lightfoot-epistle-from-laodicea"),
        _spec("lightfoot-laodiceans-notes-history", "laodiceans-notes-and-history", 21347, 22120, "lightfoot-epistle-from-laodicea"),
        _spec("lightfoot-laodiceans-capitula", "capitula", 21030, 21042, "lightfoot-laodiceans-mss-capitula"),
        _spec("lightfoot-region-philemon-introduction", "philemon-introduction", 22121, 23594, "lightfoot-envelope"),
        _spec("lightfoot-region-philemon-frontmatter", "philemon-text-frontmatter", 23595, 23615, "lightfoot-envelope"),
        _spec("lightfoot-region-philemon-commentary", "philemon-text-commentary", 23616, 24498, "lightfoot-envelope"),
        _spec("lightfoot-region-additions", "additions-and-corrections", 24499, 24586, "lightfoot-envelope"),
        _spec("lightfoot-region-index", "index", 24587, 25784, "lightfoot-envelope"),
        _spec("lightfoot-region-colophon-note", "colophon-and-transcriber-note", 25785, 25834, "lightfoot-envelope"),
        _spec("lightfoot-region-gutenberg-end", "gutenberg-end-envelope", 25835, 25862, "lightfoot-envelope"),
        _spec("lightfoot-region-gutenberg-license", "gutenberg-license", 25863, 26185, "lightfoot-envelope"),
        _spec("lightfoot-illustration-placeholder", "illustration-placeholder", 89, 89, "lightfoot-region-title-page"),
        _spec("lightfoot-parallel-reading", "parallel-reading", 18463, 18485, "lightfoot-various-readings"),
        _spec("lightfoot-parallel-reading-table", "parallel-reading-table", 18466, 18474, "lightfoot-parallel-reading"),
        _spec("lightfoot-parallel-reading-table-b", "parallel-reading-table", 18481, 18485, "lightfoot-parallel-reading"),
    ]


def _is_separator(value: str) -> bool:
    return bool(re.fullmatch(r"-{40,}", value))


def _source_feature_facts(rows: list[_Row]) -> dict[str, object]:
    """Validate source-located exceptions before applying semantic mapping.

    The source has a few layout carriers whose meaning cannot be recovered
    from a generic Greek or quotation heuristic.  Keeping the anchors here
    makes those decisions auditable while preserving every source line.
    """
    for line in _SOURCE_HEADING_LINES:
        if line < 1 or line > len(rows) or not rows[line - 1].value.strip():
            raise ValueError(f"Lightfoot source heading anchor drifted at line {line}")
    for start, end, prefix in _UNQUOTED_PARAPHRASE_SPANS:
        if not rows[start - 1].value.lstrip().startswith(prefix):
            raise ValueError(f"Lightfoot unquoted paraphrase anchor drifted at line {start}")
        if any(not rows[line - 1].value.strip() for line in range(start, end + 1)):
            raise ValueError(f"Lightfoot unquoted paraphrase span contains a blank at {start}")
        if end == len(rows) or rows[end].value.strip():
            raise ValueError(f"Lightfoot unquoted paraphrase end drifted at line {end}")
    for line in _APPARATUS_LINES:
        if line < 2 or line >= len(rows):
            raise ValueError(f"Lightfoot apparatus anchor out of bounds at line {line}")
        value = rows[line - 1].value
        leading = len(value) - len(value.lstrip(" "))
        if (
            leading < 20
            or _greek_count(value) < 2
            or "^" in value
            or rows[line - 2].value.strip()
            or rows[line].value.strip()
        ):
            raise ValueError(f"Lightfoot apparatus anchor drifted at line {line}")
    for start, end, prefix in _LEMMA_SPANS:
        if not rows[start - 1].value.lstrip().startswith(prefix):
            raise ValueError(f"Lightfoot lemma anchor drifted at line {start}")
        if any(not rows[line - 1].value.strip() for line in range(start, end + 1)):
            raise ValueError(f"Lightfoot lemma span contains a blank at {start}")
        if start == 1 or rows[start - 2].value.strip():
            raise ValueError(f"Lightfoot lemma start is not source-separated at line {start}")
        if end == len(rows) or rows[end].value.strip():
            raise ValueError(f"Lightfoot lemma end drifted at line {end}")
    mixed_line, mixed_prefix, mixed_suffix = _MIXED_SOURCE_LINE
    if rows[mixed_line - 1].value != mixed_prefix + mixed_suffix:
        raise ValueError(f"Lightfoot mixed source line drifted at line {mixed_line}")
    for line, start, token, _ in _FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS:
        value = rows[line - 1].value
        if value[start : start + len(token)] != token:
            raise ValueError(f"Lightfoot literal footnote-reference exception drifted at line {line}")
    return {
        "heading_lines": sorted(_SOURCE_HEADING_LINES),
        "unquoted_paraphrase_spans": [
            {"start_line": start, "end_line": end, "prefix": prefix}
            for start, end, prefix in _UNQUOTED_PARAPHRASE_SPANS
        ],
        "apparatus_lines": sorted(_APPARATUS_LINES),
        "lemma_spans": [
            {"start_line": start, "end_line": end, "prefix": prefix}
            for start, end, prefix in _LEMMA_SPANS
        ],
        "footnote_reference_exceptions": [
            {"line": line, "start_char": start, "token": token, "reason": reason}
            for line, start, token, reason in _FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
        ],
        "mixed_source_line": {
            "line": mixed_line,
            "prefix": mixed_prefix,
            "suffix": mixed_suffix,
        },
    }


def _heading_lines(rows: list[_Row]) -> set[int]:
    facts = _source_feature_facts(rows)
    result = set(int(line) for line in facts["heading_lines"])
    # Standalone italic headings are source display headings.  Require blank
    # surroundings so inline editorial italics in prose remain paragraphs.
    for row in rows:
        value = row.value.strip()
        if (
            value.startswith("_")
            and value.endswith("_")
            and row.number > 1
            and row.number < len(rows)
            and not rows[row.number - 2].value.strip()
            and not rows[row.number].value.strip()
        ):
            result.add(row.number)
    result.update(
        int(item["start_line"])
        for item in _range_specs(rows)
        if item["type"] == "range-occurrence"
    )
    return result


def _greek_count(value: str) -> int:
    return sum(
        0x0370 <= ord(char) <= 0x03FF or 0x1F00 <= ord(char) <= 0x1FFF
        for char in value
    )


def _is_scripture_line(value: str) -> bool:
    stripped = value.strip()
    if not stripped or _greek_count(stripped) < 2:
        return False
    if re.match(r"^\d+\s", stripped) and not stripped.startswith("^"):
        return False
    if "i.e." in stripped or "comp." in stripped:
        return False
    if "]" in stripped:
        suffixes = re.findall(r"]\s*([^,.;:]+)", stripped)
        if any(
            re.match(r"(?:[A-Za-z‘’'\"]|The|This|Not|For|As|If|It|So)\S", suffix)
            for suffix in suffixes
        ):
            return False
    if re.match(r"^[A-Za-z§]", stripped) and "^" not in stripped:
        return False
    return "^" in stripped or any(
        0x0370 <= ord(char) <= 0x03FF or 0x1F00 <= ord(char) <= 0x1FFF
        for char in stripped[:3]
    )


def _paraphrase_start(value: str, line_number: int | None = None) -> bool:
    if line_number is not None and any(
        line_number == start for start, _, _ in _UNQUOTED_PARAPHRASE_SPANS
    ):
        return True
    return bool(
        re.match(
            r"^\s*(?:[IVX]+\.\s*)?\d+(?:[–—\-]\d+|,\s*\d+)*\.\s+",
            value,
        )
        and any(char in value for char in ("'", "‘", "“", '"'))
    )


def _is_apparatus_line(rows: list[_Row], line_number: int, start: int, end: int) -> bool:
    """Identify the source's isolated, deeply indented Greek reading band."""
    if line_number not in _APPARATUS_LINES or not start <= line_number <= end:
        return False
    value = rows[line_number - 1].value
    leading = len(value) - len(value.lstrip(" "))
    return bool(
        leading >= 20
        and _greek_count(value) >= 2
        and "^" not in value
        and line_number > 1
        and line_number < len(rows)
        and not rows[line_number - 2].value.strip()
        and not rows[line_number].value.strip()
    )


def _range_roles(rows: list[_Row], start: int, end: int) -> list[dict[str, object]]:
    """Find source layout spans after a range marker.

    The first Greek run may contain a blank-page continuation (for example
    10,920–10,923 for source marker 10,918). Only a source-looking Greek
    continuation is admitted; a Greek lemma followed by commentary is not
    promoted into the scripture carrier.
    """

    cursor = start + 1
    while cursor <= end and not rows[cursor - 1].value.strip():
        cursor += 1
    greek_lines: list[int] = []
    while cursor <= end:
        if cursor == _MIXED_SOURCE_LINE[0]:
            # The retained line changes from a Greek carrier to an English
            # annotation mid-line.  Keep the exact line as a separate
            # provisional mixed role; do not assign its English suffix to
            # scripture or fabricate a verse boundary.
            break
        value = rows[cursor - 1].value
        if value.strip():
            if not _is_scripture_line(value):
                break
            greek_lines.append(cursor)
            cursor += 1
            continue
        lookahead = cursor
        while lookahead <= end and not rows[lookahead - 1].value.strip():
            lookahead += 1
        if lookahead <= end and _is_scripture_line(rows[lookahead - 1].value):
            cursor = lookahead
            continue
        break
    if not greek_lines:
        raise ValueError(f"Lightfoot range at line {start} has no source Greek carrier")

    greek_end = cursor - 1
    while cursor <= end and not rows[cursor - 1].value.strip():
        cursor += 1
    roles: list[dict[str, object]] = [
        {"type": "scripture-text", "start_line": start + 1, "end_line": greek_end}
    ]
    if cursor == _MIXED_SOURCE_LINE[0]:
        roles.append(
            {
                "type": "mixed-source-line",
                "start_line": cursor,
                "end_line": cursor,
            }
        )
        cursor += 1
    apparatus: list[dict[str, object]] = []
    while cursor <= end and _is_apparatus_line(rows, cursor, start, end):
        apparatus.append({"type": "apparatus", "start_line": cursor, "end_line": cursor})
        cursor += 1
        while cursor <= end and not rows[cursor - 1].value.strip():
            cursor += 1
    roles.extend(apparatus)
    lemma_spans = {
        lemma_start: lemma_end
        for lemma_start, lemma_end, _ in _LEMMA_SPANS
        if start <= lemma_start <= end
    }
    if cursor in lemma_spans:
        lemma_end = lemma_spans[cursor]
        roles.append({"type": "lemma", "start_line": cursor, "end_line": lemma_end})
        cursor = lemma_end + 1
        while cursor <= end and not rows[cursor - 1].value.strip():
            cursor += 1
    if cursor <= end and _paraphrase_start(rows[cursor - 1].value, cursor):
        paraphrase_start = cursor
        while cursor <= end and rows[cursor - 1].value.strip():
            cursor += 1
        paraphrase_end = cursor - 1
        while cursor <= end and not rows[cursor - 1].value.strip():
            cursor += 1
        roles.append(
            {
                "type": "paraphrase",
                "start_line": paraphrase_start,
                "end_line": paraphrase_end,
            }
        )
    if cursor <= end:
        roles.append({"type": "commentary", "start_line": cursor, "end_line": end})
    return roles


def _range_specs(rows: list[_Row]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for prefix, start, end, pattern in (
        ("lightfoot-colossians-range", 10860, 18352, _RANGE_RE),
        ("lightfoot-philemon-range", 23616, 24498, _PHILEMON_RANGE_RE),
    ):
        headings = [
            row.number
            for row in rows[start - 1 : end]
            if pattern.fullmatch(row.value)
        ]
        for ordinal, heading in enumerate(headings, 1):
            range_end = headings[ordinal] - 1 if ordinal < len(headings) else end
            parent = (
                "lightfoot-region-colossians-commentary"
                if prefix.endswith("colossians-range")
                else "lightfoot-region-philemon-commentary"
            )
            unit_id = f"{prefix}-{ordinal:04d}"
            result.append(
                _spec(
                    unit_id,
                    "range-occurrence",
                    heading,
                    range_end,
                    parent,
                    label=rows[heading - 1].value,
                    ordinal=ordinal,
                )
            )
            role_ordinals: dict[str, int] = {}
            for role in _range_roles(rows, heading, range_end):
                role_type = str(role["type"])
                role_ordinals[role_type] = role_ordinals.get(role_type, 0) + 1
                role_ordinal = role_ordinals[role_type]
                role_id = f"{unit_id}-{role_type}"
                if role_ordinal > 1:
                    role_id = f"{role_id}-{role_ordinal:02d}"
                result.append(
                    _spec(
                        role_id,
                        role_type,
                        int(role["start_line"]),
                        int(role["end_line"]),
                        unit_id,
                    )
                )
    range_count = sum(item["type"] == "range-occurrence" for item in result)
    if range_count != 120:
        raise ValueError("Lightfoot range occurrence inventory drifted")
    return result


def _footnote_spans(rows: list[_Row]) -> list[dict[str, int]]:
    spans: list[dict[str, int]] = []

    def continuation(value: str) -> bool:
        indent = len(value) - len(value.lstrip(" "))
        return bool(value.strip()) and 1 <= indent <= 4

    for row in rows:
        match = _FOOTNOTE_RE.fullmatch(row.value)
        if not match:
            continue
        cursor = row.number + 1
        last_body = row.number
        while cursor <= len(rows):
            value = rows[cursor - 1].value
            if continuation(value):
                last_body = cursor
                cursor += 1
                continue
            if not value.strip():
                lookahead = cursor
                while lookahead <= len(rows) and not rows[lookahead - 1].value.strip():
                    lookahead += 1
                if lookahead <= len(rows) and continuation(rows[lookahead - 1].value):
                    cursor = lookahead
                    continue
            break
        spans.append(
            {
                "start_line": row.number,
                "end_line": last_body,
                "number": int(match.group(1)),
                "ordinal": len(spans) + 1,
            }
        )
    if len(spans) != 759:
        raise ValueError("Lightfoot footnote inventory drifted")
    return spans


def _footnote_references(
    rows: list[_Row], footnotes: list[dict[str, int]]
) -> dict[int, list[tuple[int, int, str, int]]]:
    """Resolve every numeric bracket token against unique source footnotes."""
    by_number: dict[int, list[dict[str, int]]] = {}
    for note in footnotes:
        by_number.setdefault(int(note["number"]), []).append(note)
    result: dict[int, list[tuple[int, int, str, int]]] = {}
    exceptions = {
        (line, start, token)
        for line, start, token, _ in _FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
    }
    seen_exceptions: set[tuple[int, int, str]] = set()
    for row in rows:
        for match in re.finditer(r"\[([0-9]+)\]", row.value):
            token = match.group(0)
            key = (row.number, match.start(), token)
            if key in exceptions:
                seen_exceptions.add(key)
                continue
            if match.start() and (row.value[match.start() - 1].isspace() or row.value[match.start() - 1] == ","):
                raise ValueError(f"Lightfoot unclassified numeric bracket in citation-like context at line {row.number}")
            number = int(match.group(1))
            notes = by_number.get(number, [])
            if len(notes) != 1:
                raise ValueError(
                    f"Lightfoot source footnote reference target is ambiguous for {number} at line {row.number}"
                )
            result.setdefault(row.number, []).append(
                (
                    match.start(),
                    match.end(),
                    f"lightfoot-footnote-{notes[0]['ordinal']:04d}",
                    number,
                )
            )
    if sum(len(values) for values in result.values()) != 761 or seen_exceptions != exceptions:
        raise ValueError("Lightfoot source footnote reference census drifted")
    return result


def _sidenote_close(value: str, marker: int) -> int:
    """Find the matching outer bracket, retaining nested source brackets."""
    depth = 1
    for index in range(marker + len(_SIDENOTE_MARKER), len(value)):
        character = value[index]
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _sidenote_records(
    rows: list[_Row],
) -> tuple[list[dict[str, object]], dict[int, list[tuple[int, int, int, str]]]]:
    records: list[dict[str, object]] = []
    segments: dict[int, list[tuple[int, int, int, str]]] = {}
    pending: dict[str, int] | None = None
    for row in rows:
        cursor = 0
        while True:
            if pending is not None:
                close = row.value.find("]", cursor)
                marker = row.value.find(_SIDENOTE_MARKER, cursor)
                if close >= 0 and (marker < 0 or close < marker):
                    segments.setdefault(row.number, []).append(
                        (cursor, close + 1, pending["ordinal"], "sidenote-continuation")
                    )
                    records[pending["ordinal"] - 1]["end_line"] = row.number
                    records[pending["ordinal"] - 1]["end_char"] = close + 1
                    pending = None
                    cursor = close + 1
                    continue
                if marker >= 0:
                    raise ValueError("Lightfoot sidenote marker nesting is ambiguous")
                if row.value[cursor:]:
                    segments.setdefault(row.number, []).append(
                        (cursor, len(row.value), pending["ordinal"], "sidenote-continuation")
                    )
                break
            marker = row.value.find(_SIDENOTE_MARKER, cursor)
            if marker < 0:
                break
            close = _sidenote_close(row.value, marker)
            ordinal = len(records) + 1
            if close >= 0:
                segments.setdefault(row.number, []).append(
                    (marker, close + 1, ordinal, "sidenote")
                )
                records.append(
                    {
                        "id": f"lightfoot-sidenote-{ordinal:04d}",
                        "start_line": row.number,
                        "start_char": marker,
                        "end_line": row.number,
                        "end_char": close + 1,
                        "same_line": True,
                    }
                )
                cursor = close + 1
                continue
            segments.setdefault(row.number, []).append(
                (marker, len(row.value), ordinal, "sidenote")
            )
            records.append(
                {
                    "id": f"lightfoot-sidenote-{ordinal:04d}",
                    "start_line": row.number,
                    "start_char": marker,
                    "end_line": row.number,
                    "end_char": len(row.value),
                    "same_line": False,
                }
            )
            pending = {"ordinal": ordinal}
            break
    if pending is not None:
        raise ValueError("Lightfoot source ends inside a sidenote marker")
    if len(records) != 677:
        raise ValueError("Lightfoot sidenote inventory drifted")
    return records, segments


def _choose_parent(
    specs: list[dict[str, object]], start: int, end: int
) -> dict[str, object]:
    candidates = [
        item
        for item in specs
        if item["type"] != "footnote"
        and int(item["start_line"]) <= start
        and int(item["end_line"]) >= end
    ]
    if not candidates:
        raise ValueError(f"Lightfoot structural parent missing for lines {start}-{end}")
    return min(
        candidates,
        key=lambda item: (
            int(item["end_line"]) - int(item["start_line"]),
            str(item["id"]),
        ),
    )


def _build_specs(
    rows: list[_Row],
) -> tuple[
    list[dict[str, object]],
    list[dict[str, int]],
    list[dict[str, object]],
    dict[int, list[tuple[int, int, int, str]]],
]:
    specs = _static_specs() + _range_specs(rows)
    _source_feature_facts(rows)
    heading_lines = _heading_lines(rows)
    footnotes = _footnote_spans(rows)
    sidenotes, sidenote_segments = _sidenote_records(rows)
    for item in footnotes:
        parent = _choose_parent(specs, item["start_line"], item["end_line"])
        specs.append(
            _spec(
                f"lightfoot-footnote-{item['ordinal']:04d}",
                "footnote",
                item["start_line"],
                item["end_line"],
                str(parent["id"]),
                label=str(item["number"]),
                ordinal=item["ordinal"],
            )
        )

    direct_lines = {
        int(item["start_line"])
        for item in specs
        if item["type"] in {"range-occurrence", "footnote"}
    }
    direct_lines.update(heading_lines)
    for item in specs:
        if item["type"] == "parallel-reading-table":
            direct_lines.update(
                range(int(item["start_line"]), int(item["end_line"]) + 1)
            )
    semantic_specs = list(specs)
    for parent in semantic_specs:
        parent_id = str(parent["id"])
        children = [item for item in semantic_specs if item.get("parent") == parent_id]
        intervals = sorted(
            (int(item["start_line"]), int(item["end_line"])) for item in children
        )
        cursor = int(parent["start_line"])
        while cursor <= int(parent["end_line"]):
            covering = next((end for start, end in intervals if start == cursor), None)
            if covering is not None:
                cursor = covering + 1
                continue
            if any(start < cursor <= end for start, end in intervals):
                cursor += 1
                continue
            if cursor in direct_lines:
                cursor += 1
                continue
            if rows[cursor - 1].value.strip():
                paragraph_start = cursor
                cursor += 1
                while cursor <= int(parent["end_line"]):
                    if cursor in direct_lines or any(
                        start < cursor <= end for start, end in intervals
                    ):
                        break
                    if not rows[cursor - 1].value.strip():
                        break
                    cursor += 1
                specs.append(
                    _spec(
                        f"lightfoot-paragraph-{parent_id}-{paragraph_start:06d}",
                        "paragraph",
                        paragraph_start,
                        cursor - 1,
                        parent_id,
                    )
                )
                continue
            cursor += 1
    return specs, footnotes, sidenotes, sidenote_segments


def _role_by_line(specs: list[dict[str, object]]) -> dict[int, str]:
    role_map: dict[int, str] = {}
    for item in specs:
        if item["type"] in {"scripture-text", "paraphrase", "commentary", "apparatus", "lemma", "mixed-source-line"}:
            for number in range(int(item["start_line"]), int(item["end_line"]) + 1):
                role_map[number] = str(item["type"])
    return role_map


def _footnote_by_line(specs: list[dict[str, object]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in specs:
        if item["type"] == "footnote":
            for number in range(int(item["start_line"]), int(item["end_line"]) + 1):
                result[number] = str(item["id"])
    return result


def _line_ana(
    row: _Row,
    role_map: dict[int, str],
    footnote_map: dict[int, str],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    range_headings: set[int],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> list[str]:
    values: list[str] = []
    if not row.value.strip():
        values.append("#blank")
    if _is_separator(row.value):
        values.append("#separator")
    if row.number in range_headings:
        values.append("#range-heading")
    if row.number in role_map:
        values.append(f"#{role_map[row.number]}")
    if row.number in footnote_map:
        values.append("#footnote")
    if row.number in sidenote_segments:
        values.append("#sidenote")
    if row.number in footnote_references:
        values.append("#footnote-reference")
    return values


def _append_source_line(
    parent: etree._Element,
    row: _Row,
    *,
    ana: list[str],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
    tag: str = "seg",
) -> etree._Element:
    attrs = {
        "xml:id": f"lightfoot-line-{row.number:06d}",
        "n": str(row.number),
        "type": "source-line",
    }
    if ana:
        attrs["ana"] = " ".join(ana)
    element = _tei(tag, attrs)
    spans: list[tuple[int, int, str, str, str, str | None]] = []
    spans.extend(
        (
            start,
            end,
            f"lightfoot-sidenote-{ordinal:04d}-line-{row.number:06d}",
            segment_type,
            f"#lightfoot-sidenote-{ordinal:04d}",
            None,
        )
        for start, end, ordinal, segment_type in sidenote_segments.get(row.number, [])
    )
    spans.extend(
        (
            start,
            end,
            f"lightfoot-footnote-ref-{number}-line-{row.number:06d}",
            "footnote-reference",
            f"#{target}",
            None,
        )
        for start, end, target, number in footnote_references.get(row.number, [])
    )
    if row.number == _MIXED_SOURCE_LINE[0]:
        prefix = _MIXED_SOURCE_LINE[1]
        suffix = _MIXED_SOURCE_LINE[2]
        if row.value != prefix + suffix:
            raise ValueError(f"Lightfoot mixed source line drifted at {row.number}")
        spans.extend(
            (
                0,
                len(prefix),
                f"lightfoot-mixed-source-line-{row.number:06d}-prefix",
                "mixed-source-line-part",
                f"#lightfoot-mixed-source-line-{row.number:06d}",
                "#scripture-text",
            )
            for _ in [0]
        )
        spans.append(
            (
                len(prefix),
                len(prefix) + len(suffix),
                f"lightfoot-mixed-source-line-{row.number:06d}-suffix",
                "mixed-source-line-part",
                f"#lightfoot-mixed-source-line-{row.number:06d}",
                "#commentary",
            )
        )
    spans.sort(key=lambda item: (item[0], item[1], item[2]))
    cursor = 0
    for start, end, ident, segment_type, corresp, part_ana in spans:
        if start < cursor or end > len(row.value):
            raise ValueError(f"Lightfoot inline source segmentation overlaps line {row.number}")
        if cursor == 0:
            element.text = row.value[:start]
        else:
            element[-1].tail = row.value[cursor:start]
        if segment_type == "footnote-reference":
            child = _tei("ref", {"xml:id": ident, "type": segment_type, "target": corresp}, row.value[start:end])
        else:
            attrs = {"xml:id": ident, "type": segment_type, "corresp": corresp}
            if part_ana is not None:
                attrs["ana"] = part_ana
            child = _tei(
                "seg",
                attrs,
                row.value[start:end],
            )
        element.append(child)
        cursor = end
    if not spans:
        element.text = row.value
    else:
        element[-1].tail = row.value[cursor:]
    parent.append(element)
    return element


def _append_source_gap(
    parent: etree._Element,
    row: _Row,
    *,
    ana: list[str],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
    wrapped: bool = False,
) -> None:
    target = parent
    if wrapped:
        # A div that already contains structural child divs cannot accept a
        # later direct ab under the bundled TEI content model.  Keep the
        # source blank line in a one-line structural fragment rather than
        # dropping it or joining it to a neighboring unit.
        target = _tei("div", {"type": "source-line-gap"})
        parent.append(target)
    gap = _tei("ab", {"type": "source-line-gap"})
    _append_source_line(
        gap,
        row,
        ana=ana,
        sidenote_segments=sidenote_segments,
        footnote_references=footnote_references,
    )
    target.append(gap)


def _append_heading_fragment(
    parent: etree._Element,
    row: _Row,
    *,
    ana: list[str],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> None:
    # TEI div permits head only in its leading divTop sequence.  A source
    # heading encountered after paragraph/range content therefore gets its
    # own anonymous div fragment while retaining a native head leaf.
    fragment = _tei("div", {"type": "source-heading-fragment"})
    _append_source_line(
        fragment,
        row,
        ana=ana,
        sidenote_segments=sidenote_segments,
        footnote_references=footnote_references,
        tag="head",
    )
    parent.append(fragment)


def _append_direct_line(
    parent: etree._Element,
    row: _Row,
    *,
    ana: list[str],
    heading_lines: set[int],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
    wrap_gap: bool = False,
    wrap_heading: bool = False,
) -> None:
    if not row.value.strip():
        _append_source_gap(
            parent,
            row,
            ana=ana,
            sidenote_segments=sidenote_segments,
            footnote_references=footnote_references,
            wrapped=wrap_gap,
        )
        return
    if row.number not in heading_lines:
        raise ValueError(f"Lightfoot non-heading source line escaped a native paragraph at {row.number}")
    if wrap_heading:
        _append_heading_fragment(
            parent,
            row,
            ana=ana,
            sidenote_segments=sidenote_segments,
            footnote_references=footnote_references,
        )
        return
    _append_source_line(
        parent,
        row,
        ana=ana,
        sidenote_segments=sidenote_segments,
        footnote_references=footnote_references,
        tag="head",
    )


def _append_parallel_table(
    table: etree._Element,
    item: dict[str, object],
    rows: list[_Row],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
    role_map: dict[int, str],
    footnote_map: dict[int, str],
    range_headings: set[int],
) -> None:
    row_specs = _PARALLEL_TABLE_ROWS.get(str(item["id"]))
    if row_specs is None:
        raise ValueError(f"Lightfoot parallel table source mapping missing for {item['id']}")
    expected_lines = {
        number
        for start, end, _ in row_specs
        for number in range(start, end + 1)
    }
    actual_start = int(item["start_line"])
    actual_end = int(item["end_line"])
    if expected_lines != set(range(actual_start, actual_end + 1)):
        raise ValueError(f"Lightfoot parallel table does not cover its source span: {item['id']}")
    for ordinal, (start, end, role) in enumerate(row_specs, 1):
        row = _tei(
            "row",
            {"xml:id": f"{item['id']}-row-{ordinal:02d}", "n": str(start)},
        )
        cell = _tei("cell", {"role": role})
        paragraph = _tei("p")
        for number in range(start, end + 1):
            source_row = rows[number - 1]
            _append_source_line(
                paragraph,
                source_row,
                ana=_line_ana(
                    source_row,
                    role_map,
                    footnote_map,
                    sidenote_segments,
                    range_headings,
                    footnote_references,
                ),
                sidenote_segments=sidenote_segments,
                footnote_references=footnote_references,
            )
            if number < end:
                paragraph.append(_tei("lb"))
        cell.append(paragraph)
        row.append(cell)
        table.append(row)


def _attrs_for_unit(item: dict[str, object]) -> dict[str, str]:
    attrs = {"xml:id": str(item["id"]), "type": str(item["type"])}
    if item.get("n") is not None:
        attrs["n"] = str(item["n"])
    if item["type"] == "parallel-reading-table":
        attrs["n"] = str(item["start_line"])
    if item["type"] == "range-occurrence":
        attrs["corresp"] = f"#lightfoot-line-{int(item['start_line']):06d}"
    return attrs


def _append_unit(
    parent: etree._Element,
    item: dict[str, object],
    by_parent: dict[str | None, list[dict[str, object]]],
    rows: list[_Row],
    role_map: dict[int, str],
    footnote_map: dict[int, str],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    range_headings: set[int],
    heading_lines: set[int],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> None:
    unit_type = str(item["type"])
    tag = {
        "paragraph": "p",
        "footnote": "note",
        "parallel-reading-table": "table",
    }.get(unit_type, "div")
    unit_attrs = _attrs_for_unit(item)
    # TEI p has no att.typed/@type in the bundled P5 schema.  The paragraph's
    # source identity remains in xml:id and the source-accountability record;
    # native element choice carries the structural meaning here.
    if unit_type == "paragraph":
        unit_attrs.pop("type", None)
    element = _tei(tag, unit_attrs)
    if unit_type == "paragraph":
        start = int(item["start_line"])
        end = int(item["end_line"])
        for number in range(start, end + 1):
            _append_source_line(
                element,
                rows[number - 1],
                ana=_line_ana(
                    rows[number - 1],
                    role_map,
                    footnote_map,
                    sidenote_segments,
                    range_headings,
                    footnote_references,
                ),
                sidenote_segments=sidenote_segments,
                footnote_references=footnote_references,
            )
            if number < end:
                element.append(_tei("lb"))
        parent.append(element)
        return
    if unit_type == "parallel-reading-table":
        _append_parallel_table(element, item, rows, sidenote_segments, footnote_references, role_map, footnote_map, range_headings)
        parent.append(element)
        return
    children = sorted(
        by_parent.get(str(item["id"]), []),
        key=lambda child: (int(child["start_line"]), int(child["end_line"]), str(child["id"])),
    )
    cursor = int(item["start_line"])
    content_started = False
    fragment_mode = False
    has_div_children = any(str(child["type"]) not in {"paragraph", "footnote"} for child in children)

    if unit_type == "footnote":
        # A note uses a label for its source footnote marker.  The TEI note
        # content model does not allow head, while label preserves the source
        # heading role and exact line leaf without changing the surrounding
        # native note structure.
        if not rows[cursor - 1].value.strip():
            raise ValueError(f"Lightfoot footnote head is blank at {cursor}")
        label = _tei("label")
        _append_source_line(
            label,
            rows[cursor - 1],
            ana=_line_ana(
                rows[cursor - 1],
                role_map,
                footnote_map,
                sidenote_segments,
                range_headings,
                footnote_references,
            ),
            sidenote_segments=sidenote_segments,
            footnote_references=footnote_references,
        )
        element.append(label)
        cursor += 1
        content_started = True

    def append_direct(row: _Row) -> None:
        nonlocal content_started, fragment_mode
        is_blank = not row.value.strip()
        late = content_started or fragment_mode
        wrap_gap = fragment_mode or has_div_children
        wrap_heading = late
        if unit_type == "footnote":
            if is_blank:
                _append_source_gap(
                    element,
                    row,
                    ana=_line_ana(
                        row,
                        role_map,
                        footnote_map,
                        sidenote_segments,
                        range_headings,
                        footnote_references,
                    ),
                    sidenote_segments=sidenote_segments,
                    footnote_references=footnote_references,
                )
            else:
                paragraph = _tei("p")
                _append_source_line(
                    paragraph,
                    row,
                    ana=_line_ana(
                        row,
                        role_map,
                        footnote_map,
                        sidenote_segments,
                        range_headings,
                        footnote_references,
                    ),
                    sidenote_segments=sidenote_segments,
                    footnote_references=footnote_references,
                )
                element.append(paragraph)
            content_started = True
            return
        _append_direct_line(
            element,
            row,
            ana=_line_ana(
                row,
                role_map,
                footnote_map,
                sidenote_segments,
                range_headings,
                footnote_references,
            ),
            heading_lines=heading_lines,
            sidenote_segments=sidenote_segments,
            footnote_references=footnote_references,
            wrap_gap=wrap_gap,
            wrap_heading=wrap_heading,
        )
        if is_blank:
            content_started = True
            if wrap_gap:
                fragment_mode = True
        elif wrap_heading:
            fragment_mode = True

    for child in children:
        child_start = int(child["start_line"])
        child_end = int(child["end_line"])
        while cursor < child_start:
            row = rows[cursor - 1]
            append_direct(row)
            cursor += 1
        if cursor != child_start:
            raise ValueError(f"Lightfoot structural unit overlap at {child['id']}")
        child_parent = element
        child_type = str(child["type"])
        if fragment_mode and child_type in {"paragraph", "parallel-reading-table"}:
            # Once a div fragment has entered a TEI div's content sequence,
            # P5 requires later paragraph/table-like children to remain in
            # the div-like branch.  Keep the native element inside an
            # anonymous content fragment so source order and identity remain.
            child_parent = _tei("div", {"type": "source-content-fragment"})
            element.append(child_parent)
        elif child_type == "parallel-reading-table":
            # A table is not a divPart in this TEI profile.  Its native table
            # therefore travels in a div-like fragment when mixed with the
            # surrounding prose paragraphs.
            child_parent = _tei("div", {"type": "source-content-fragment"})
            element.append(child_parent)
        _append_unit(
            child_parent,
            child,
            by_parent,
            rows,
            role_map,
            footnote_map,
            sidenote_segments,
            range_headings,
            heading_lines,
            footnote_references,
        )
        cursor = child_end + 1
        content_started = True
        if child_type not in {"paragraph", "footnote"}:
            fragment_mode = True
    while cursor <= int(item["end_line"]):
        row = rows[cursor - 1]
        append_direct(row)
        cursor += 1
    parent.append(element)


def _metadata_header(content: bytes) -> etree._Element:
    header = _tei("teiHeader")
    file_desc = _tei("fileDesc")
    title_stmt = _tei("titleStmt")
    title_stmt.append(_tei("title", text="St. Paul's Epistles to the Colossians and to Philemon"))
    title_stmt.append(_tei("author", text="J. B. Lightfoot"))
    file_desc.append(title_stmt)
    publication = _tei("publicationStmt")
    publication.append(_tei("publisher", text="Open Christian Data"))
    availability = _tei("availability", {"status": "unknown"})
    availability.append(
        _tei(
            "p",
            text="Nonaccepted candidate; rights, visual comparison, and human acceptance remain unresolved.",
        )
    )
    publication.append(availability)
    file_desc.append(publication)
    source_desc = _tei("sourceDesc")
    bibl = _tei("bibl")
    bibl.append(_tei("title", text="St. Paul's Epistles to the Colossians and to Philemon"))
    bibl.append(_tei("author", text="J. B. Lightfoot"))
    bibl.append(_tei("idno", {"type": "gutenberg"}, "50857"))
    bibl.append(_tei("idno", {"type": "sha256"}, _sha(content)))
    source_desc.append(bibl)
    file_desc.append(source_desc)
    header.append(file_desc)
    return header


def _feature_counts(
    rows: list[_Row],
    specs: list[dict[str, object]],
    footnotes: list[dict[str, int]],
    sidenotes: list[dict[str, object]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> dict[str, int]:
    role_map = _role_by_line(specs)
    range_items = [item for item in specs if item["type"] == "range-occurrence"]
    starts = {
        int(item["start_line"])
        for item in sidenotes
        if rows[int(item["start_line"]) - 1].value[: int(item["start_char"])].strip() == ""
    }
    inline_starts = {
        int(item["start_line"]) for item in sidenotes if int(item["start_char"]) > 0
    }
    return {
        "source_regions": 17,
        "structural_units": len(specs),
        "paragraphs": sum(item["type"] == "paragraph" for item in specs),
        "range_occurrences": len(range_items),
        "colossians_range_occurrences": sum(
            str(item["id"]).startswith("lightfoot-colossians-range-") for item in range_items
        ),
        "philemon_range_occurrences": sum(
            str(item["id"]).startswith("lightfoot-philemon-range-") for item in range_items
        ),
        "dash_separators": sum(_is_separator(row.value) for row in rows),
        "footnote_heads": len(footnotes),
        "footnote_body_lines": sum(
            item["end_line"] - item["start_line"] + 1 for item in footnotes
        ),
        "sidenote_markers": len(sidenotes),
        "sidenote_start_lines": len(starts),
        "sidenote_inline_lines": len(inline_starts),
        "sidenote_cross_line_markers": sum(not item["same_line"] for item in sidenotes),
        "greek_lines": sum(
            bool(rows[number - 1].value.strip())
            and role in {"scripture-text", "mixed-source-line"}
            for number, role in role_map.items()
        ),
        "paraphrase_lines": sum(
            bool(rows[number - 1].value.strip()) and role == "paraphrase"
            for number, role in role_map.items()
        ),
        "lemma_lines": sum(
            bool(rows[number - 1].value.strip()) and role == "lemma"
            for number, role in role_map.items()
        ),
        "apparatus_lines": sum(
            bool(rows[number - 1].value.strip()) and role == "apparatus"
            for number, role in role_map.items()
        ),
        "commentary_lines": sum(
            bool(rows[number - 1].value.strip()) and role == "commentary"
            for number, role in role_map.items()
        ),
        "mixed_source_lines": sum(
            bool(rows[number - 1].value.strip()) and role == "mixed-source-line"
            for number, role in role_map.items()
        ),
        "footnote_references": sum(len(value) for value in footnote_references.values()),
        "illustration_placeholders": sum(row.value.strip() == "[Illustration]" for row in rows),
        "gutenberg_start_markers": sum(row.value.startswith("*** START ") for row in rows),
        "gutenberg_end_markers": sum(row.value.startswith("*** END ") for row in rows),
    }


def _unit_records(specs: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            key: item[key]
            for key in ("id", "type", "parent", "start_line", "end_line", "n", "ordinal")
            if key in item
        }
        for item in sorted(specs, key=lambda value: str(value["id"]))
    ]


def _accountability(
    content: bytes,
    rows: list[_Row],
    specs: list[dict[str, object]],
    footnotes: list[dict[str, int]],
    sidenotes: list[dict[str, object]],
    sidenote_segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> dict[str, object]:
    role_map = _role_by_line(specs)
    footnote_map = _footnote_by_line(specs)
    range_headings = {
        int(item["start_line"])
        for item in specs
        if item["type"] == "range-occurrence"
    }
    features = []
    for row in rows:
        ana = _line_ana(
            row,
            role_map,
            footnote_map,
            sidenote_segments,
            range_headings,
            footnote_references,
        )
        if ana:
            features.append({"line": row.number, "ana": ana})
    ranges = []
    for item in sorted(
        (unit for unit in specs if unit["type"] == "range-occurrence"),
        key=lambda unit: str(unit["id"]),
    ):
        start = int(item["start_line"])
        end = int(item["end_line"])
        roles = {
            str(role["type"]): role
            for role in specs
            if role.get("parent") == item["id"]
            and role["type"] in {"scripture-text", "paraphrase", "commentary", "apparatus", "lemma", "mixed-source-line"}
        }
        ranges.append(
            {
                "id": item["id"],
                "work": "colossians" if str(item["id"]).startswith("lightfoot-colossians") else "philemon",
                "ordinal": item["ordinal"],
                "label": item["n"],
                "start_line": start,
                "end_line": end,
                "separator_lines": [
                    row.number for row in rows[start - 1 : end] if _is_separator(row.value)
                ],
                "greek_line_count": sum(
                    bool(rows[n - 1].value.strip())
                    for n in range(int(roles["scripture-text"]["start_line"]), int(roles["scripture-text"]["end_line"]) + 1)
                ),
                "mixed_source_line_count": sum(
                    bool(rows[n - 1].value.strip())
                    for role in roles.values()
                    if role["type"] == "mixed-source-line"
                    for n in range(int(role["start_line"]), int(role["end_line"]) + 1)
                ),
                "paraphrase_line_count": sum(
                    bool(rows[n - 1].value.strip())
                    for n in range(int(roles["paraphrase"]["start_line"]), int(roles["paraphrase"]["end_line"]) + 1)
                ) if "paraphrase" in roles else 0,
                "lemma_line_count": sum(
                    bool(rows[n - 1].value.strip())
                    for role in roles.values()
                    if role["type"] == "lemma"
                    for n in range(int(role["start_line"]), int(role["end_line"]) + 1)
                ),
                "apparatus_line_count": sum(
                    bool(rows[n - 1].value.strip())
                    for role in roles.values()
                    if role["type"] == "apparatus"
                    for n in range(int(role["start_line"]), int(role["end_line"]) + 1)
                ),
                "commentary_line_count": sum(
                    bool(rows[n - 1].value.strip())
                    for n in range(int(roles["commentary"]["start_line"]), int(roles["commentary"]["end_line"]) + 1)
                ) if "commentary" in roles else 0,
                "footnote_heads": sum(
                    int(note["start_line"]) >= start and int(note["start_line"]) <= end
                    for note in footnotes
                ),
                "sidenote_markers": sum(
                    int(note["start_line"]) >= start and int(note["start_line"]) <= end
                    for note in sidenotes
                ),
            }
        )
    crosswalk = [
        {
            "line": row.number,
            "byte_start": row.offset,
            "byte_end": row.offset + len(row.raw),
            "source_sha256": _sha(row.raw),
            "tei_id": f"lightfoot-line-{row.number:06d}",
            "text": row.value,
        }
        for row in rows
    ]
    return {
        "contract": "ocd-lightfoot-colossians-philemon-source-accountability-v3",
        "profile_id": "lightfoot-colossians-philemon-v3",
        "source_sha256": _sha(content),
        "source_bytes": len(content),
        "line_count": len(rows),
        "newline_count": content.count(b"\n"),
        "represented_count": len(rows),
        "evidence_only_count": 0,
        "omitted_count": 0,
        "duplicate_count": 0,
        "reordered_count": 0,
        "crosswalk": crosswalk,
        "structural_units": _unit_records(specs),
        "line_features": features,
        "feature_counts": _feature_counts(rows, specs, footnotes, sidenotes, footnote_references),
        "range_occurrences": ranges,
        "sidenote_markers": sidenotes,
        "footnote_references": [
            {
                "line": line,
                "start_char": start,
                "end_char": end,
                "number": number,
                "target": f"#{target}",
                "target_start_line": next(
                    int(note["start_line"])
                    for note in footnotes
                    if f"lightfoot-footnote-{int(note['ordinal']):04d}" == target
                ),
            }
            for line, values in footnote_references.items()
            for start, end, target, number in values
        ],
        "footnote_reference_exceptions": [
            {
                "line": line,
                "start_char": start,
                "end_char": start + len(token),
                "token": token,
                "reason": reason,
            }
            for line, start, token, reason in _FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
        ],
    }


def _convert(source_manifest: SourceManifest) -> dict[str, bytes]:
    source_manifest.verify()
    content = _source(source_manifest)
    rows = _lines(content)
    specs, footnotes, sidenotes, sidenote_segments = _build_specs(rows)
    heading_lines = _heading_lines(rows)
    footnote_references = _footnote_references(rows, footnotes)
    role_map = _role_by_line(specs)
    footnote_map = _footnote_by_line(specs)
    range_headings = {
        int(item["start_line"])
        for item in specs
        if item["type"] == "range-occurrence"
    }

    root = _tei("TEI", {"xml:id": "lightfoot-colossians-philemon-candidate"})
    root.append(_metadata_header(content))
    text = _tei("text")
    body = _tei("body")
    text.append(body)
    root.append(text)
    by_parent: dict[str | None, list[dict[str, object]]] = {}
    for item in specs:
        by_parent.setdefault(item.get("parent"), []).append(item)
    envelope = next(item for item in specs if item["id"] == "lightfoot-envelope")
    _append_unit(
        body,
        envelope,
        by_parent,
        rows,
        role_map,
        footnote_map,
        sidenote_segments,
        range_headings,
        heading_lines,
        footnote_references,
    )
    helper_path = Path(__file__).with_name("lightfoot_typography.py")
    helper_spec = importlib.util.spec_from_file_location("lightfoot_typography", helper_path)
    if helper_spec is None or helper_spec.loader is None:
        raise ValueError("Lightfoot typography implementation is unavailable")
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    typography = helper.apply_typography(root, [row.value for row in rows])
    tei = etree.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=False)
    accountability = _accountability(
        content,
        rows,
        specs,
        footnotes,
        sidenotes,
        sidenote_segments,
        footnote_references,
    )
    accountability["typography"] = {
        "spans": helper.discover_spans([row.value for row in rows]),
        "literal_caret_markers": [
            {key: marker[key] for key in ("line", "start_char", "end_char", "token")}
            for marker in typography["non_numeric_caret_markers"]
            if not marker["rendered"]
        ],
    }
    provenance = {
        "contract": "ocd-lightfoot-colossians-philemon-candidate-provenance-v3",
        "status": "nonaccepted",
        "ticket_id": "LIB-070",
        "work_id": "lightfoot-colossians-philemon",
        "source_id": source_manifest.record["source_id"],
        "source_manifest_sha256": source_manifest.sha256,
        "source_sha256": _sha(content),
        "source_authority": "D:/Library/Open Christian Data/raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt",
        "candidate_boundary": {
            "acceptance_status": "nonaccepted",
            "publication_status": "not-authorized",
            "canonical_data_or_ir_written": False,
        },
    }
    unresolved = [
        {
            "id": "lightfoot-rights-review",
            "status": "unresolved",
            "detail": "Validation does not establish worldwide publication rights.",
        },
        {
            "id": "lightfoot-human-acceptance",
            "status": "unresolved",
            "detail": "This candidate has not received human textual acceptance.",
        },
        {
            "id": "lightfoot-visual-source-compare",
            "status": "unresolved",
            "detail": "No supported browser visual comparison was available in this execution.",
        },
    ]
    readme = source_manifest.authority_path("source-attribution-readme").read_bytes()
    return {
        "content.tei.xml": tei,
        "source-accountability.json": _canonical(accountability),
        "provenance.json": _canonical(provenance),
        "unresolved.jsonl": b"".join(_canonical(item) for item in unresolved),
        "README.source.md": readme,
    }


_convert.converter_id = CONVERTER_ID
_convert.converter_version = CONVERTER_VERSION
_convert.implementation_path = Path(__file__).resolve()
