"""Independent source-derived oracle for the isolated Lightfoot candidate.

This module deliberately repeats the source inventory rules instead of
importing the producer. It derives the expected envelope, range occurrences,
carrier spans, notes, sidenotes, and line features from the pinned witness,
then compares both the accountability receipt and the TEI tree with those
expectations.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import re
import sys

from jsonschema import Draft202012Validator
from lxml import etree

from ocd_kernel.reconstruction.contract import CandidatePackage, SourceManifest

ORACLE_ID = "ocd-lightfoot-colossians-philemon-source-to-tei-oracle"
ORACLE_VERSION = "3"
TEI = "http://www.tei-c.org/ns/1.0"
XML = "http://www.w3.org/XML/1998/namespace"
SOURCE_BYTES = 1_511_463
SOURCE_SHA = "a97cb49964906a2c158a0444cfdc3b0daf13261620c919a90f1333a98ac0b913"
RANGE_RE = re.compile(r"^[IVX]+\.\s*[\d,\s–—\-]+\]$")
PHILEMON_RANGE_RE = re.compile(r"^[\d,\s–—\-]+\]$")
FOOTNOTE_RE = re.compile(r"^Footnote (\d+):$")
SIDENOTE = "[Sidenote:"

# Independently declared source facts.  The oracle checks these coordinates
# against the retained witness and then corroborates the generated inventory;
# it does not trust a producer receipt to define them.
SOURCE_HEADING_LINES = frozenset(
    {
        75, 77, 79, 81, 83, 85, 87, 95, 96, 97, 98, 100, 102, 104, 109, 111,
        121, 122, 123, 125, 160, 220, 222, 224, 252, 263, 264, 4171, 4172,
        6332, 6335, 6336, 10148, 10149, 10818, 10828, 10830, 10832, 10856,
        18354, 19108, 20277, 21030, 21180, 22121, 22123, 23595, 23600, 23603,
        23612, 24499, 24587, 25785, 25790, 25835,
    }
)

# The contents page names three separate essays in the Colossians apparatus.
# Their display headings and range boundaries are source facts; _essay_specs()
# re-locates and validates them before they are used to build the expected
# structural inventory.
ESSAY_SOURCE_ANCHORS = (
    (
        246,
        18354,
        "lightfoot-various-readings",
        "On some Various Readings in the Epistle",
        "_On some Various Readings in the Epistle[535]._",
    ),
    (
        248,
        19108,
        "lightfoot-meaning-of-pleroma",
        "On the meaning of πλήρωμα",
        "_On the meaning of πλήρωμα._",
    ),
    (
        250,
        20277,
        "lightfoot-epistle-from-laodicea",
        "The Epistle from Laodicea",
        "_The Epistle from_ _Laodicea_[591].",
    ),
)
APPARATUS_NEXT_HEADING_LINE = 22121
APPARATUS_NEXT_HEADING_TEXT = "EPISTLE TO PHILEMON."
UNQUOTED_PARAPHRASE_SPANS = (
    (12679, 12687, "20. The false teachers aimed at effecting a partial reconciliation"),
    (17721, 17723, "10. The salutations to Philemon are sent from the same persons as to the"),
)
APPARATUS_LINES = frozenset(
    {11455, 11631, 12786, 13876, 14362, 14815, 14916, 15986, 17177, 23824, 23872}
)
LEMMA_SPANS = (
    (12432, 12455, "17."),
    (13462, 13466, "29."),
    (13720, 13725, "4."),
    (14492, 14498, "14."),
    (15954, 15962, "2."),
    (17241, 17246, "24."),
    (18214, 18220, "16."),
    (24149, 24171, "13."),
)
FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS = (
    (3804, 32, "[1550]", "year in the source date sequence"),
    (18346, 14, "[24]", "bracketed verse number in a scripture reference list"),
)
MIXED_SOURCE_LINE = (
    13183,
    "τοῦ σώματος αὐτοῦ",
    " An antithesis of the Apostle’s own flesh and Christ’s",
)
PARALLEL_TABLE_ROWS = {
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


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canon(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _obj(value: bytes, label: str) -> dict[str, object]:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict UTF-8 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be an object")
    return parsed


def _source(manifest: SourceManifest) -> bytes:
    value = manifest.authority_path("retained-lightfoot-text").read_bytes()
    if len(value) != SOURCE_BYTES or _sha(value) != SOURCE_SHA:
        raise ValueError("Lightfoot source identity drifted")
    value.decode("utf-8")
    return value


def _rows(content: bytes) -> list[dict[str, object]]:
    if not content.startswith(b"\xef\xbb\xbf"):
        raise ValueError("Lightfoot retained witness lost its file-initial UTF-8 BOM")
    result: list[dict[str, object]] = []
    offset = 0
    for number, raw in enumerate(content.splitlines(keepends=True), 1):
        payload = raw[:-1] if raw.endswith(b"\n") else raw
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        # Decode the first physical line as UTF-8-with-signature while retaining
        # raw bytes independently for source-line and offset verification.
        decoded = payload.decode("utf-8-sig" if number == 1 else "utf-8")
        result.append({"line": number, "offset": offset, "raw": raw, "text": decoded})
        offset += len(raw)
    if offset != len(content) or len(result) != 26_185:
        raise ValueError("Lightfoot source line accounting drifted")
    return result


def _unit(unit_id: str, unit_type: str, start: int, end: int, parent: str | None, *, label: str | None = None, ordinal: int | None = None) -> dict[str, object]:
    value: dict[str, object] = {"id": unit_id, "type": unit_type, "start_line": start, "end_line": end, "parent": parent}
    if label is not None:
        value["n"] = label
    if ordinal is not None:
        value["ordinal"] = ordinal
    return value


def _essay_specs(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Derive the three apparatus essay ranges from retained source headings."""

    headings: list[tuple[int, str, str]] = []
    for toc_line, heading_line, unit_id, label, heading_prefix in ESSAY_SOURCE_ANCHORS:
        toc_value = str(rows[toc_line - 1]["text"]).strip()
        if not toc_value.startswith(f"_{label}_"):
            raise ValueError(f"Lightfoot essay TOC anchor drifted at line {toc_line}")
        located = [
            int(row["line"])
            for row in rows
            if str(row["text"]).strip().startswith(heading_prefix)
        ]
        if located != [heading_line]:
            raise ValueError(f"Lightfoot essay heading anchor drifted at line {heading_line}")
        headings.append((located[0], unit_id, label))

    # The first essay owns the source separator immediately before its
    # heading.  The later headings begin directly after the preceding blank
    # source line.  Deriving the starts and ends from the located headings
    # prevents a copied range from silently surviving a source shift.
    next_heading_lines = [
        int(row["line"])
        for row in rows
        if int(row["line"]) > headings[-1][0]
        if str(row["text"]).strip() == APPARATUS_NEXT_HEADING_TEXT
    ]
    if next_heading_lines != [APPARATUS_NEXT_HEADING_LINE]:
        raise ValueError(
            f"Lightfoot apparatus closing heading drifted at line {APPARATUS_NEXT_HEADING_LINE}"
        )
    next_heading_line = next_heading_lines[0]
    starts = [headings[0][0] - 1, headings[1][0], headings[2][0]]
    ends = [
        headings[1][0] - 1,
        headings[2][0] - 1,
        next_heading_line - 1,
    ]
    expected = [(18353, 19107), (19108, 20276), (20277, 22120)]
    if list(zip(starts, ends, strict=True)) != expected:
        raise ValueError("Lightfoot apparatus essay range anchors drifted")
    if str(rows[starts[0] - 1]["text"]).strip() or any(
        str(rows[end - 1]["text"]).strip() for end in ends
    ):
        raise ValueError("Lightfoot apparatus essay boundaries are not source-separated")
    if any(str(rows[heading_line - 2]["text"]).strip() for heading_line, _, _ in headings[1:]):
        raise ValueError("Lightfoot apparatus essay headings are not source-separated")
    return [
        _unit(unit_id, "dissertation", start, end, "lightfoot-region-colossians-apparatus", label=label)
        for (heading_line, unit_id, label), start, end in zip(headings, starts, ends, strict=True)
    ]


def _static_units(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    # These source boundaries are independently located from the retained
    # headings and Gutenberg envelope; they are not imported from the writer.
    essays = _essay_specs(rows)
    essay_by_id = {str(item["id"]): item for item in essays}
    return [
        _unit("lightfoot-envelope", "gutenberg-envelope", 1, 26185, None),
        _unit("lightfoot-region-preamble", "gutenberg-preamble", 1, 29, "lightfoot-envelope"),
        _unit("lightfoot-region-transcriber-note", "transcriber-note", 30, 74, "lightfoot-envelope"),
        _unit("lightfoot-region-title-page", "title-page", 75, 159, "lightfoot-envelope"),
        _unit("lightfoot-region-preface", "preface", 160, 219, "lightfoot-envelope"),
        _unit("lightfoot-region-contents", "contents", 220, 262, "lightfoot-envelope"),
        _unit("lightfoot-region-colossians-introduction", "colossians-introduction", 263, 10813, "lightfoot-envelope"),
        _unit("lightfoot-colossians-introduction-i", "introduction-section", 263, 4170, "lightfoot-region-colossians-introduction", label="I"),
        _unit("lightfoot-colossians-introduction-ii", "introduction-section", 4171, 6331, "lightfoot-region-colossians-introduction", label="II"),
        _unit("lightfoot-essene-dissertation", "dissertation", 6332, 10147, "lightfoot-region-colossians-introduction", label="On some points connected with the Essenes"),
        _unit("lightfoot-colossians-introduction-iii", "introduction-section", 10148, 10813, "lightfoot-region-colossians-introduction", label="III"),
        _unit("lightfoot-region-colossians-frontmatter", "colossians-text-frontmatter", 10814, 10859, "lightfoot-envelope"),
        _unit("lightfoot-region-colossians-commentary", "colossians-text-commentary", 10860, 18352, "lightfoot-envelope"),
        _unit("lightfoot-region-colossians-apparatus", "colossians-apparatus", 18353, 22120, "lightfoot-envelope"),
        essay_by_id["lightfoot-various-readings"],
        essay_by_id["lightfoot-meaning-of-pleroma"],
        essay_by_id["lightfoot-epistle-from-laodicea"],
        _unit("lightfoot-laodiceans-mss-capitula", "laodiceans-mss-and-capitula", 21030, 21179, "lightfoot-epistle-from-laodicea"),
        _unit("lightfoot-laodiceans-text-apparatus", "laodiceans-text-and-apparatus", 21180, 21346, "lightfoot-epistle-from-laodicea"),
        _unit("lightfoot-laodiceans-notes-history", "laodiceans-notes-and-history", 21347, 22120, "lightfoot-epistle-from-laodicea"),
        _unit("lightfoot-laodiceans-capitula", "capitula", 21030, 21042, "lightfoot-laodiceans-mss-capitula"),
        _unit("lightfoot-region-philemon-introduction", "philemon-introduction", 22121, 23594, "lightfoot-envelope"),
        _unit("lightfoot-region-philemon-frontmatter", "philemon-text-frontmatter", 23595, 23615, "lightfoot-envelope"),
        _unit("lightfoot-region-philemon-commentary", "philemon-text-commentary", 23616, 24498, "lightfoot-envelope"),
        _unit("lightfoot-region-additions", "additions-and-corrections", 24499, 24586, "lightfoot-envelope"),
        _unit("lightfoot-region-index", "index", 24587, 25784, "lightfoot-envelope"),
        _unit("lightfoot-region-colophon-note", "colophon-and-transcriber-note", 25785, 25834, "lightfoot-envelope"),
        _unit("lightfoot-region-gutenberg-end", "gutenberg-end-envelope", 25835, 25862, "lightfoot-envelope"),
        _unit("lightfoot-region-gutenberg-license", "gutenberg-license", 25863, 26185, "lightfoot-envelope"),
        _unit("lightfoot-illustration-placeholder", "illustration-placeholder", 89, 89, "lightfoot-region-title-page"),
        _unit("lightfoot-parallel-reading", "parallel-reading", 18463, 18485, "lightfoot-various-readings"),
        _unit("lightfoot-parallel-reading-table", "parallel-reading-table", 18466, 18474, "lightfoot-parallel-reading"),
        _unit("lightfoot-parallel-reading-table-b", "parallel-reading-table", 18481, 18485, "lightfoot-parallel-reading"),
    ]


def _separator(value: str) -> bool:
    return bool(re.fullmatch(r"-{40,}", value))


def _greek_count(value: str) -> int:
    return sum(0x0370 <= ord(char) <= 0x03FF or 0x1F00 <= ord(char) <= 0x1FFF for char in value)


def _source_feature_facts(rows: list[dict[str, object]]) -> dict[str, object]:
    """Validate declared source anchors before checking candidate structure."""
    essay_specs = _essay_specs(rows)
    for line in SOURCE_HEADING_LINES:
        if line < 1 or line > len(rows) or not str(rows[line - 1]["text"]).strip():
            raise ValueError(f"Lightfoot source heading anchor drifted at line {line}")
    for start, end, prefix in UNQUOTED_PARAPHRASE_SPANS:
        if not str(rows[start - 1]["text"]).lstrip().startswith(prefix):
            raise ValueError(f"Lightfoot unquoted paraphrase anchor drifted at line {start}")
        if any(not str(rows[line - 1]["text"]).strip() for line in range(start, end + 1)):
            raise ValueError(f"Lightfoot unquoted paraphrase span contains a blank at {start}")
        if end == len(rows) or str(rows[end]["text"]).strip():
            raise ValueError(f"Lightfoot unquoted paraphrase end drifted at line {end}")
    for line in APPARATUS_LINES:
        if line < 2 or line >= len(rows):
            raise ValueError(f"Lightfoot apparatus anchor out of bounds at line {line}")
        value = str(rows[line - 1]["text"])
        leading = len(value) - len(value.lstrip(" "))
        if (
            leading < 20
            or _greek_count(value) < 2
            or "^" in value
            or str(rows[line - 2]["text"]).strip()
            or str(rows[line]["text"]).strip()
        ):
            raise ValueError(f"Lightfoot apparatus anchor drifted at line {line}")
    for start, end, prefix in LEMMA_SPANS:
        if not str(rows[start - 1]["text"]).lstrip().startswith(prefix):
            raise ValueError(f"Lightfoot lemma anchor drifted at line {start}")
        if any(not str(rows[line - 1]["text"]).strip() for line in range(start, end + 1)):
            raise ValueError(f"Lightfoot lemma span contains a blank at {start}")
        if start == 1 or str(rows[start - 2]["text"]).strip():
            raise ValueError(f"Lightfoot lemma start is not source-separated at line {start}")
        if end == len(rows) or str(rows[end]["text"]).strip():
            raise ValueError(f"Lightfoot lemma end drifted at line {end}")
    mixed_line, mixed_prefix, mixed_suffix = MIXED_SOURCE_LINE
    if str(rows[mixed_line - 1]["text"]) != mixed_prefix + mixed_suffix:
        raise ValueError(f"Lightfoot mixed source line drifted at line {mixed_line}")
    for line, start, token, _ in FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS:
        value = str(rows[line - 1]["text"])
        if value[start : start + len(token)] != token:
            raise ValueError(f"Lightfoot literal footnote-reference exception drifted at line {line}")
    exception_keys = {
        (line, start, token)
        for line, start, token, _ in FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
    }
    citation_like_keys = {
        (int(row["line"]), match.start(), match.group(0))
        for row in rows
        for match in re.finditer(r"\[([0-9]+)\]", str(row["text"]))
        if match.start()
        and (
            str(row["text"])[match.start() - 1].isspace()
            or str(row["text"])[match.start() - 1] == ","
        )
    }
    if citation_like_keys != exception_keys:
        raise ValueError("Lightfoot citation-like numeric bracket census drifted")
    return {
        "heading_lines": sorted(SOURCE_HEADING_LINES),
        "essay_ranges": [
            {
                "id": str(item["id"]),
                "start_line": int(item["start_line"]),
                "end_line": int(item["end_line"]),
                "label": str(item["n"]),
            }
            for item in essay_specs
        ],
        "unquoted_paraphrase_spans": [
            {"start_line": start, "end_line": end, "prefix": prefix}
            for start, end, prefix in UNQUOTED_PARAPHRASE_SPANS
        ],
        "apparatus_lines": sorted(APPARATUS_LINES),
        "lemma_spans": [
            {"start_line": start, "end_line": end, "prefix": prefix}
            for start, end, prefix in LEMMA_SPANS
        ],
        "footnote_reference_exceptions": [
            {"line": line, "start_char": start, "token": token, "reason": reason}
            for line, start, token, reason in FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
        ],
        "citation_like_numeric_brackets": [
            {"line": line, "start_char": start, "token": token}
            for line, start, token in sorted(citation_like_keys)
        ],
        "mixed_source_line": {
            "line": mixed_line,
            "prefix": mixed_prefix,
            "suffix": mixed_suffix,
        },
    }


def _heading_lines(rows: list[dict[str, object]], ranges: list[dict[str, object]]) -> set[int]:
    facts = _source_feature_facts(rows)
    result = set(int(line) for line in facts["heading_lines"])
    for row in rows:
        value = str(row["text"]).strip()
        number = int(row["line"])
        if (
            value.startswith("_")
            and value.endswith("_")
            and number > 1
            and number < len(rows)
            and not str(rows[number - 2]["text"]).strip()
            and not str(rows[number]["text"]).strip()
        ):
            result.add(number)
    result.update(int(item["start_line"]) for item in ranges if item["type"] == "range-occurrence")
    return result


def _greek_carrier(value: str) -> bool:
    """Recognize source Greek carriers, including page continuations."""
    stripped = value.strip()
    if not stripped or _greek_count(stripped) < 2:
        return False
    if "i.e." in stripped or "comp." in stripped:
        return False
    if re.match(r"^\d+\s", stripped) and "^" not in stripped:
        return False
    if "]" in stripped:
        for suffix in re.findall(r"]\s*([^,.;:]+)", stripped):
            if re.match(r"(?:[A-Za-z‘’'\"]|The|This|Not|For|As|If|It|So)\S", suffix):
                return False
    if re.match(r"^[A-Za-z§]", stripped) and "^" not in stripped:
        return False
    return "^" in stripped or any(0x0370 <= ord(char) <= 0x03FF or 0x1F00 <= ord(char) <= 0x1FFF for char in stripped[:3])


def _paraphrase(value: str) -> bool:
    return bool(re.match(r"^\s*(?:[IVX]+\.\s*)?\d+(?:[–—\-]\d+|,\s*\d+)*\.\s+", value) and any(char in value for char in ("'", "‘", "“", '"')))


def _is_apparatus_line(rows: list[dict[str, object]], line_number: int, start: int, end: int) -> bool:
    if line_number not in APPARATUS_LINES or not start <= line_number <= end:
        return False
    value = str(rows[line_number - 1]["text"])
    leading = len(value) - len(value.lstrip(" "))
    return bool(
        leading >= 20
        and _greek_count(value) >= 2
        and "^" not in value
        and line_number > 1
        and line_number < len(rows)
        and not str(rows[line_number - 2]["text"]).strip()
        and not str(rows[line_number]["text"]).strip()
    )


def _source_paraphrase(value: str, line_number: int) -> bool:
    if any(line_number == start for start, _, _ in UNQUOTED_PARAPHRASE_SPANS):
        return True
    return _paraphrase(value)


def _sidenote_close(value: str, marker: int) -> int:
    depth = 1
    for index in range(marker + len(SIDENOTE), len(value)):
        character = value[index]
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _range_roles(rows: list[dict[str, object]], start: int, end: int) -> list[dict[str, object]]:
    cursor = start + 1
    while cursor <= end and not str(rows[cursor - 1]["text"]).strip():
        cursor += 1
    carriers: list[int] = []
    while cursor <= end:
        if cursor == MIXED_SOURCE_LINE[0]:
            # The retained line changes from Greek to an English annotation
            # mid-line; keep that source line outside the all-scripture span.
            break
        value = str(rows[cursor - 1]["text"])
        if value.strip():
            if not _greek_carrier(value):
                break
            carriers.append(cursor)
            cursor += 1
            continue
        lookahead = cursor
        while lookahead <= end and not str(rows[lookahead - 1]["text"]).strip():
            lookahead += 1
        if lookahead <= end and _greek_carrier(str(rows[lookahead - 1]["text"])):
            cursor = lookahead
            continue
        break
    if not carriers:
        raise ValueError(f"Lightfoot range {start} has no source Greek carrier")
    greek_end = cursor - 1
    while cursor <= end and not str(rows[cursor - 1]["text"]).strip():
        cursor += 1
    answer: list[dict[str, object]] = [{"type": "scripture-text", "start_line": start + 1, "end_line": greek_end}]
    if cursor == MIXED_SOURCE_LINE[0]:
        answer.append({"type": "mixed-source-line", "start_line": cursor, "end_line": cursor})
        cursor += 1
    apparatus: list[dict[str, object]] = []
    while cursor <= end and _is_apparatus_line(rows, cursor, start, end):
        apparatus.append({"type": "apparatus", "start_line": cursor, "end_line": cursor})
        cursor += 1
        while cursor <= end and not str(rows[cursor - 1]["text"]).strip():
            cursor += 1
    answer.extend(apparatus)
    lemma_spans = {
        lemma_start: lemma_end
        for lemma_start, lemma_end, _ in LEMMA_SPANS
        if start <= lemma_start <= end
    }
    if cursor in lemma_spans:
        lemma_end = lemma_spans[cursor]
        answer.append({"type": "lemma", "start_line": cursor, "end_line": lemma_end})
        cursor = lemma_end + 1
        while cursor <= end and not str(rows[cursor - 1]["text"]).strip():
            cursor += 1
    if cursor <= end and _source_paraphrase(str(rows[cursor - 1]["text"]), cursor):
        begin = cursor
        while cursor <= end and str(rows[cursor - 1]["text"]).strip():
            cursor += 1
        answer.append({"type": "paraphrase", "start_line": begin, "end_line": cursor - 1})
        while cursor <= end and not str(rows[cursor - 1]["text"]).strip():
            cursor += 1
    if cursor <= end:
        answer.append({"type": "commentary", "start_line": cursor, "end_line": end})
    return answer


def _ranges(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for prefix, start, end, pattern, parent in (
        ("lightfoot-colossians-range", 10860, 18352, RANGE_RE, "lightfoot-region-colossians-commentary"),
        ("lightfoot-philemon-range", 23616, 24498, PHILEMON_RANGE_RE, "lightfoot-region-philemon-commentary"),
    ):
        heads = [int(row["line"]) for row in rows[start - 1 : end] if pattern.fullmatch(str(row["text"]))]
        for ordinal, heading in enumerate(heads, 1):
            stop = heads[ordinal] - 1 if ordinal < len(heads) else end
            rid = f"{prefix}-{ordinal:04d}"
            result.append(_unit(rid, "range-occurrence", heading, stop, parent, label=str(rows[heading - 1]["text"]), ordinal=ordinal))
            role_ordinals: dict[str, int] = {}
            for role in _range_roles(rows, heading, stop):
                role_type = str(role["type"])
                role_ordinals[role_type] = role_ordinals.get(role_type, 0) + 1
                role_id = f"{rid}-{role_type}"
                if role_ordinals[role_type] > 1:
                    role_id = f"{role_id}-{role_ordinals[role_type]:02d}"
                result.append(_unit(role_id, role_type, int(role["start_line"]), int(role["end_line"]), rid))
    if sum(item["type"] == "range-occurrence" for item in result) != 120:
        raise ValueError("Lightfoot range inventory drifted")
    return result


def _footnotes(rows: list[dict[str, object]]) -> list[dict[str, int]]:
    def continuation(value: str) -> bool:
        indent = len(value) - len(value.lstrip(" "))
        return bool(value.strip()) and 1 <= indent <= 4

    result: list[dict[str, int]] = []
    for row in rows:
        match = FOOTNOTE_RE.fullmatch(str(row["text"]))
        if match is None:
            continue
        start = int(row["line"])
        cursor = start + 1
        last = start
        while cursor <= len(rows):
            value = str(rows[cursor - 1]["text"])
            if continuation(value):
                last = cursor
                cursor += 1
                continue
            if not value.strip():
                lookahead = cursor
                while lookahead <= len(rows) and not str(rows[lookahead - 1]["text"]).strip():
                    lookahead += 1
                if lookahead <= len(rows) and continuation(str(rows[lookahead - 1]["text"])):
                    cursor = lookahead
                    continue
            break
        result.append({"start_line": start, "end_line": last, "number": int(match.group(1)), "ordinal": len(result) + 1})
    if len(result) != 759:
        raise ValueError("Lightfoot footnote inventory drifted")
    return result


def _footnote_references(
    rows: list[dict[str, object]], notes: list[dict[str, int]]
) -> dict[int, list[tuple[int, int, str, int]]]:
    """Independently resolve every source numeric footnote token."""
    by_number: dict[int, list[dict[str, int]]] = {}
    for note in notes:
        by_number.setdefault(int(note["number"]), []).append(note)
    result: dict[int, list[tuple[int, int, str, int]]] = {}
    exceptions = {
        (line, start, token)
        for line, start, token, _ in FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
    }
    seen_exceptions: set[tuple[int, int, str]] = set()
    for row in rows:
        line = int(row["line"])
        value = str(row["text"])
        for match in re.finditer(r"\[([0-9]+)\]", value):
            token = match.group(0)
            key = (line, match.start(), token)
            if key in exceptions:
                seen_exceptions.add(key)
                continue
            if match.start() and (
                value[match.start() - 1].isspace()
                or value[match.start() - 1] == ","
            ):
                raise ValueError(
                    "Lightfoot unclassified numeric bracket in citation-like context "
                    f"at line {line}"
                )
            number = int(match.group(1))
            matches = by_number.get(number, [])
            if len(matches) != 1:
                raise ValueError(f"Lightfoot source footnote target is ambiguous for {number} at line {line}")
            result.setdefault(line, []).append(
                (match.start(), match.end(), f"lightfoot-footnote-{matches[0]['ordinal']:04d}", number)
            )
    if sum(len(values) for values in result.values()) != 761 or seen_exceptions != exceptions:
        raise ValueError("Lightfoot source footnote reference census drifted")
    return result


def _sidenotes(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[int, list[tuple[int, int, int, str]]]]:
    records: list[dict[str, object]] = []
    segments: dict[int, list[tuple[int, int, int, str]]] = {}
    pending: int | None = None
    for row in rows:
        line = int(row["line"])
        value = str(row["text"])
        cursor = 0
        while True:
            if pending is not None:
                close = value.find("]", cursor)
                marker = value.find(SIDENOTE, cursor)
                if close >= 0 and (marker < 0 or close < marker):
                    segments.setdefault(line, []).append((cursor, close + 1, pending, "sidenote-continuation"))
                    records[pending - 1]["end_line"] = line
                    records[pending - 1]["end_char"] = close + 1
                    pending = None
                    cursor = close + 1
                    continue
                if marker >= 0:
                    raise ValueError("nested Lightfoot sidenote marker")
                if value[cursor:]:
                    segments.setdefault(line, []).append((cursor, len(value), pending, "sidenote-continuation"))
                break
            marker = value.find(SIDENOTE, cursor)
            if marker < 0:
                break
            close = _sidenote_close(value, marker)
            ordinal = len(records) + 1
            if close >= 0:
                segments.setdefault(line, []).append((marker, close + 1, ordinal, "sidenote"))
                records.append({"id": f"lightfoot-sidenote-{ordinal:04d}", "start_line": line, "start_char": marker, "end_line": line, "end_char": close + 1, "same_line": True})
                cursor = close + 1
                continue
            segments.setdefault(line, []).append((marker, len(value), ordinal, "sidenote"))
            records.append({"id": f"lightfoot-sidenote-{ordinal:04d}", "start_line": line, "start_char": marker, "end_line": line, "end_char": len(value), "same_line": False})
            pending = ordinal
            break
    if pending is not None or len(records) != 677:
        raise ValueError("Lightfoot sidenote inventory drifted")
    return records, segments


def _parent(units: list[dict[str, object]], start: int, end: int) -> dict[str, object]:
    candidates = [item for item in units if item["type"] != "footnote" and int(item["start_line"]) <= start and int(item["end_line"]) >= end]
    if not candidates:
        raise ValueError(f"Lightfoot parent missing for {start}-{end}")
    return min(candidates, key=lambda item: (int(item["end_line"]) - int(item["start_line"]), str(item["id"])))


def _inventory(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, int]], list[dict[str, object]], dict[int, list[tuple[int, int, int, str]]]]:
    units = _static_units(rows) + _ranges(rows)
    _source_feature_facts(rows)
    ranges = [item for item in units if item["type"] == "range-occurrence"]
    heading_lines = _heading_lines(rows, ranges)
    notes = _footnotes(rows)
    sidenotes, segments = _sidenotes(rows)
    for note in notes:
        owner = _parent(units, note["start_line"], note["end_line"])
        units.append(_unit(f"lightfoot-footnote-{note['ordinal']:04d}", "footnote", note["start_line"], note["end_line"], str(owner["id"]), label=str(note["number"]), ordinal=note["ordinal"]))
    direct = {int(item["start_line"]) for item in units if item["type"] in {"range-occurrence", "footnote"}}
    direct.update(heading_lines)
    for item in units:
        if item["type"] == "parallel-reading-table":
            direct.update(range(int(item["start_line"]), int(item["end_line"]) + 1))
    snapshot = list(units)
    for owner in snapshot:
        owner_id = str(owner["id"])
        children = [item for item in snapshot if item.get("parent") == owner_id]
        intervals = sorted((int(item["start_line"]), int(item["end_line"])) for item in children)
        cursor = int(owner["start_line"])
        while cursor <= int(owner["end_line"]):
            child_end = next((end for start, end in intervals if start == cursor), None)
            if child_end is not None:
                cursor = child_end + 1
                continue
            if any(start < cursor <= end for start, end in intervals):
                cursor += 1
                continue
            if cursor in direct:
                cursor += 1
                continue
            if str(rows[cursor - 1]["text"]).strip():
                begin = cursor
                cursor += 1
                while cursor <= int(owner["end_line"]):
                    if cursor in direct or any(start < cursor <= end for start, end in intervals) or not str(rows[cursor - 1]["text"]).strip():
                        break
                    cursor += 1
                units.append(_unit(f"lightfoot-paragraph-{owner_id}-{begin:06d}", "paragraph", begin, cursor - 1, owner_id))
                continue
            cursor += 1
    if len(units) != 4583:
        raise ValueError(f"Lightfoot structural unit inventory drifted: {len(units)}")
    return units, notes, sidenotes, segments


def _role_map(units: list[dict[str, object]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in units:
        if item["type"] in {"scripture-text", "paraphrase", "commentary", "apparatus", "lemma", "mixed-source-line"}:
            for line in range(int(item["start_line"]), int(item["end_line"]) + 1):
                result[line] = str(item["type"])
    return result


def _note_map(units: list[dict[str, object]]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in units:
        if item["type"] == "footnote":
            for line in range(int(item["start_line"]), int(item["end_line"]) + 1):
                result[line] = str(item["id"])
    return result


def _ana(
    row: dict[str, object],
    roles: dict[int, str],
    notes: dict[int, str],
    segments: dict[int, list[tuple[int, int, int, str]]],
    heads: set[int],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> list[str]:
    line = int(row["line"])
    value = str(row["text"])
    answer: list[str] = []
    if not value.strip():
        answer.append("#blank")
    if _separator(value):
        answer.append("#separator")
    if line in heads:
        answer.append("#range-heading")
    if line in roles:
        answer.append(f"#{roles[line]}")
    if line in notes:
        answer.append("#footnote")
    if line in segments:
        answer.append("#sidenote")
    if line in footnote_references:
        answer.append("#footnote-reference")
    return answer


def _unit_records(units: list[dict[str, object]]) -> list[dict[str, object]]:
    return [{key: item[key] for key in ("id", "type", "parent", "start_line", "end_line", "n", "ordinal") if key in item} for item in sorted(units, key=lambda value: str(value["id"]))]


def _features(
    rows: list[dict[str, object]],
    units: list[dict[str, object]],
    notes: list[dict[str, int]],
    sidenotes: list[dict[str, object]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> dict[str, int]:
    roles = _role_map(units)
    starts = {int(item["start_line"]) for item in sidenotes if not str(rows[int(item["start_line"]) - 1]["text"])[: int(item["start_char"])].strip()}
    inlines = {int(item["start_line"]) for item in sidenotes if int(item["start_char"]) > 0}
    ranges = [item for item in units if item["type"] == "range-occurrence"]
    return {
        "source_regions": 17,
        "structural_units": len(units),
        "paragraphs": sum(item["type"] == "paragraph" for item in units),
        "range_occurrences": len(ranges),
        "colossians_range_occurrences": sum(str(item["id"]).startswith("lightfoot-colossians-range-") for item in ranges),
        "philemon_range_occurrences": sum(str(item["id"]).startswith("lightfoot-philemon-range-") for item in ranges),
        "dash_separators": sum(_separator(str(row["text"])) for row in rows),
        "footnote_heads": len(notes),
        "footnote_body_lines": sum(item["end_line"] - item["start_line"] + 1 for item in notes),
        "sidenote_markers": len(sidenotes),
        "sidenote_start_lines": len(starts),
        "sidenote_inline_lines": len(inlines),
        "sidenote_cross_line_markers": sum(not bool(item["same_line"]) for item in sidenotes),
        "greek_lines": sum(bool(str(rows[line - 1]["text"]).strip()) and role in {"scripture-text", "mixed-source-line"} for line, role in roles.items()),
        "paraphrase_lines": sum(bool(str(rows[line - 1]["text"]).strip()) and role == "paraphrase" for line, role in roles.items()),
        "lemma_lines": sum(bool(str(rows[line - 1]["text"]).strip()) and role == "lemma" for line, role in roles.items()),
        "apparatus_lines": sum(bool(str(rows[line - 1]["text"]).strip()) and role == "apparatus" for line, role in roles.items()),
        "commentary_lines": sum(bool(str(rows[line - 1]["text"]).strip()) and role == "commentary" for line, role in roles.items()),
        "mixed_source_lines": sum(bool(str(rows[line - 1]["text"]).strip()) and role == "mixed-source-line" for line, role in roles.items()),
        "footnote_references": sum(len(value) for value in footnote_references.values()),
        "illustration_placeholders": sum(str(row["text"]).strip() == "[Illustration]" for row in rows),
        "gutenberg_start_markers": sum(str(row["text"]).startswith("*** START ") for row in rows),
        "gutenberg_end_markers": sum(str(row["text"]).startswith("*** END ") for row in rows),
    }


def _account(
    rows: list[dict[str, object]],
    content: bytes,
    units: list[dict[str, object]],
    notes: list[dict[str, int]],
    sidenotes: list[dict[str, object]],
    segments: dict[int, list[tuple[int, int, int, str]]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> dict[str, object]:
    roles = _role_map(units)
    note_map = _note_map(units)
    heads = {int(item["start_line"]) for item in units if item["type"] == "range-occurrence"}
    ranges: list[dict[str, object]] = []
    for item in sorted((unit for unit in units if unit["type"] == "range-occurrence"), key=lambda unit: str(unit["id"])):
        start, end = int(item["start_line"]), int(item["end_line"])
        children = {
            str(child["type"]): child
            for child in units
            if child.get("parent") == item["id"]
            and child["type"] in {"scripture-text", "paraphrase", "commentary", "apparatus", "lemma", "mixed-source-line"}
        }
        ranges.append({
            "id": item["id"], "work": "colossians" if str(item["id"]).startswith("lightfoot-colossians") else "philemon", "ordinal": item["ordinal"], "label": item["n"], "start_line": start, "end_line": end,
            "separator_lines": [int(row["line"]) for row in rows[start - 1 : end] if _separator(str(row["text"]))],
            "greek_line_count": sum(bool(str(rows[line - 1]["text"]).strip()) for line in range(int(children["scripture-text"]["start_line"]), int(children["scripture-text"]["end_line"]) + 1)),
            "mixed_source_line_count": sum(
                bool(str(rows[line - 1]["text"]).strip())
                for child in children.values()
                if child["type"] == "mixed-source-line"
                for line in range(int(child["start_line"]), int(child["end_line"]) + 1)
            ),
            "paraphrase_line_count": sum(bool(str(rows[line - 1]["text"]).strip()) for line in range(int(children["paraphrase"]["start_line"]), int(children["paraphrase"]["end_line"]) + 1)) if "paraphrase" in children else 0,
            "lemma_line_count": sum(
                bool(str(rows[line - 1]["text"]).strip())
                for child in children.values()
                if child["type"] == "lemma"
                for line in range(int(child["start_line"]), int(child["end_line"]) + 1)
            ),
            "apparatus_line_count": sum(
                bool(str(rows[line - 1]["text"]).strip())
                for child in children.values()
                if child["type"] == "apparatus"
                for line in range(int(child["start_line"]), int(child["end_line"]) + 1)
            ),
            "commentary_line_count": sum(bool(str(rows[line - 1]["text"]).strip()) for line in range(int(children["commentary"]["start_line"]), int(children["commentary"]["end_line"]) + 1)) if "commentary" in children else 0,
            "footnote_heads": sum(start <= int(note["start_line"]) <= end for note in notes), "sidenote_markers": sum(start <= int(note["start_line"]) <= end for note in sidenotes),
        })
    crosswalk = [{"line": int(row["line"]), "byte_start": int(row["offset"]), "byte_end": int(row["offset"]) + len(row["raw"]), "source_sha256": _sha(row["raw"]), "tei_id": f"lightfoot-line-{int(row['line']):06d}", "text": row["text"]} for row in rows]
    line_features = [
        {
            "line": int(row["line"]),
            "ana": _ana(row, roles, note_map, segments, heads, footnote_references),
        }
        for row in rows
        if _ana(row, roles, note_map, segments, heads, footnote_references)
    ]
    return {
        "contract": "ocd-lightfoot-colossians-philemon-source-accountability-v3", "profile_id": "lightfoot-colossians-philemon-v3", "source_sha256": _sha(content), "source_bytes": len(content), "line_count": len(rows), "newline_count": content.count(b"\n"), "represented_count": len(rows), "evidence_only_count": 0, "omitted_count": 0, "duplicate_count": 0, "reordered_count": 0,
        "crosswalk": crosswalk,
        "structural_units": _unit_records(units),
        "line_features": line_features,
        "feature_counts": _features(rows, units, notes, sidenotes, footnote_references),
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
                    for note in notes
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
            for line, start, token, reason in FOOTNOTE_REFERENCE_LITERAL_EXCEPTIONS
        ],
    }


def _closure(root: Path) -> str:
    paths = [Path(__file__).resolve(strict=True), Path(__file__).with_name("lightfoot_typography_oracle.py").resolve(strict=True), (root / "ocd_kernel/reconstruction/contract.py").resolve(strict=True), (root / "ocd_kernel/reconstruction/__init__.py").resolve(strict=True)]
    members = [{"path": path.relative_to(root).as_posix(), "bytes": len(path.read_bytes()), "sha256": _sha(path.read_bytes())} for path in sorted(paths)]
    return _sha(_canon({"contract": "ocd-python-import-closure-v1", "members": members}))


def _one(parent: etree._Element, name: str) -> etree._Element:
    expected = f"{{{TEI}}}{name}"
    children = [child for child in parent if child.tag == expected]
    if len(children) != 1 or children[0].tag != expected:
        raise ValueError(f"Lightfoot expected one {name} child")
    return children[0]


def _assert_text(node: etree._Element, expected: str) -> None:
    if node.text != expected or len(node) != 0 or node.tail not in (None, ""):
        raise ValueError(f"Lightfoot metadata text drifted at {node.tag}")


def _header(root: etree._Element) -> None:
    if root.tag != f"{{{TEI}}}TEI" or dict(root.attrib) != {f"{{{XML}}}id": "lightfoot-colossians-philemon-candidate"}:
        raise ValueError("Lightfoot TEI root drifted")
    header, text = list(root)
    if header.tag != f"{{{TEI}}}teiHeader" or text.tag != f"{{{TEI}}}text":
        raise ValueError("Lightfoot top-level TEI structure drifted")
    file_desc = _one(header, "fileDesc")
    title_stmt, publication, source_desc = list(file_desc)
    if [node.tag for node in (title_stmt, publication, source_desc)] != [f"{{{TEI}}}titleStmt", f"{{{TEI}}}publicationStmt", f"{{{TEI}}}sourceDesc"]:
        raise ValueError("Lightfoot file description drifted")
    title, author = list(title_stmt)
    _assert_text(title, "St. Paul's Epistles to the Colossians and to Philemon")
    _assert_text(author, "J. B. Lightfoot")
    publisher, availability = list(publication)
    if dict(availability.attrib) != {"status": "unknown"}:
        raise ValueError("Lightfoot availability drifted")
    _assert_text(publisher, "Open Christian Data")
    _assert_text(_one(availability, "p"), "Nonaccepted candidate; rights, visual comparison, and human acceptance remain unresolved.")
    bibl = _one(source_desc, "bibl")
    bibl_title, bibl_author, gutenberg, source_sha = list(bibl)
    _assert_text(bibl_title, "St. Paul's Epistles to the Colossians and to Philemon")
    _assert_text(bibl_author, "J. B. Lightfoot")
    if dict(gutenberg.attrib) != {"type": "gutenberg"} or gutenberg.text != "50857" or dict(source_sha.attrib) != {"type": "sha256"} or source_sha.text != SOURCE_SHA:
        raise ValueError("Lightfoot source description drifted")


def _element_content_range(
    carrier: etree._Element,
    target: etree._Element,
) -> tuple[int, int]:
    """Return target's character interval within one source-line carrier."""

    cursor = 0
    found: tuple[int, int] | None = None
    target_id = target.get(f"{{{XML}}}id")

    def visit(node: etree._Element) -> None:
        nonlocal cursor, found
        start = cursor
        if node.text:
            cursor += len(node.text)
        for child in node:
            visit(child)
            if child.tail:
                cursor += len(child.tail)
        if node is target or (
            target_id is not None
            and node.tag == target.tag
            and node.get(f"{{{XML}}}id") == target_id
        ):
            found = (start, cursor)

    visit(carrier)
    if found is None:
        raise ValueError("Lightfoot source reference is outside its source-line carrier")
    return found


def _assert_reference_content(
    root: etree._Element,
    rows: list[dict[str, object]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
) -> None:
    """Check reference text and source offsets before any normalization."""

    source_line_nodes: dict[int, etree._Element] = {}
    for node in root.iter():
        if node.get("type") != "source-line":
            continue
        raw_number = node.get("n")
        if raw_number is None or not raw_number.isdigit():
            raise ValueError("Lightfoot source-line reference carrier has no numeric n")
        line = int(raw_number)
        if line in source_line_nodes:
            raise ValueError(f"Lightfoot source-line reference carrier is duplicated at {line}")
        source_line_nodes[line] = node
    if set(source_line_nodes) != set(range(1, len(rows) + 1)):
        raise ValueError("Lightfoot source-line reference carrier census drifted")

    ref_tag = f"{{{TEI}}}ref"
    observed: dict[int, list[etree._Element]] = {}
    for ref in root.iter(ref_tag):
        ancestors: list[etree._Element] = []
        parent = ref.getparent()
        while parent is not None:
            if parent.get("type") == "source-line":
                ancestors.append(parent)
            parent = parent.getparent()
        if len(ancestors) != 1:
            raise ValueError("Lightfoot source reference is not inside one source-line carrier")
        carrier = ancestors[0]
        direct_parent = ref.getparent()
        if (
            direct_parent is None
            or direct_parent.get("type") != "source-line"
            or direct_parent.get("n") != carrier.get("n")
        ):
            raise ValueError("Lightfoot source reference is not a direct source-line child")
        line = int(carrier.get("n", "0"))
        observed.setdefault(line, []).append(ref)

    if set(observed) != set(footnote_references):
        raise ValueError("Lightfoot candidate source reference line census drifted")
    xml_id = f"{{{XML}}}id"
    for line, expected in footnote_references.items():
        refs = observed.get(line, [])
        if len(refs) != len(expected):
            raise ValueError(f"Lightfoot candidate source reference count drifted at line {line}")
        carrier = source_line_nodes[line]
        source_value = str(rows[line - 1]["text"])
        for ref, (start, end, target, number) in zip(refs, expected, strict=True):
            expected_attrs = {
                xml_id: f"lightfoot-footnote-ref-{number}-line-{line:06d}",
                "type": "footnote-reference",
                "target": f"#{target}",
            }
            if dict(ref.attrib) != expected_attrs:
                raise ValueError(f"Lightfoot source reference attributes drifted at line {line}")
            if "".join(ref.itertext()) != source_value[start:end]:
                raise ValueError(f"Lightfoot source reference text drifted at line {line}")
            if _element_content_range(carrier, ref) != (start, end):
                raise ValueError(f"Lightfoot source reference offset drifted at line {line}")


def _assert_tree(
    root: etree._Element,
    rows: list[dict[str, object]],
    units: list[dict[str, object]],
    segments: dict[int, list[tuple[int, int, int, str]]],
    expected_features: list[dict[str, object]],
    footnote_references: dict[int, list[tuple[int, int, str, int]]],
    heading_lines: set[int],
) -> None:
    body = _one(_one(root, "text"), "body")
    xml_id = f"{{{XML}}}id"
    expected_by_id = {str(item["id"]): item for item in units}
    native_tags = {
        "paragraph": f"{{{TEI}}}p",
        "footnote": f"{{{TEI}}}note",
        "parallel-reading-table": f"{{{TEI}}}table",
    }
    structural: dict[str, etree._Element] = {}
    for node in root.iter():
        ident = node.get(xml_id)
        if ident is None:
            continue
        if ident in expected_by_id:
            if ident in structural:
                raise ValueError("Lightfoot structural unit IDs are not unique")
            structural[ident] = node
    if set(structural) != set(expected_by_id):
        raise ValueError("Lightfoot structural unit inventory differs from source")

    allowed_ids = set(expected_by_id)
    # The candidate root is a package envelope rather than a source unit, so
    # it is not present in the source-derived expected unit map.
    allowed_ids.add("lightfoot-colossians-philemon-candidate")
    allowed_ids.update(f"lightfoot-line-{int(row['line']):06d}" for row in rows)
    allowed_ids.update(
        f"lightfoot-sidenote-{ordinal:04d}-line-{line:06d}"
        for line, values in segments.items()
        for _, _, ordinal, _ in values
    )
    allowed_ids.update(
        f"lightfoot-footnote-ref-{number}-line-{line:06d}"
        for line, values in footnote_references.items()
        for _, _, _, number in values
    )
    allowed_ids.update(
        {
            f"lightfoot-mixed-source-line-{MIXED_SOURCE_LINE[0]:06d}-prefix",
            f"lightfoot-mixed-source-line-{MIXED_SOURCE_LINE[0]:06d}-suffix",
        }
    )
    for table_id, table_rows in PARALLEL_TABLE_ROWS.items():
        allowed_ids.update(
            f"{table_id}-row-{ordinal:02d}"
            for ordinal, _ in enumerate(table_rows, 1)
        )
    for node in root.iter():
        ident = node.get(xml_id)
        if ident is not None and ident.startswith("lightfoot-") and ident not in allowed_ids:
            raise ValueError(f"Lightfoot candidate contains an unknown source ID: {ident}")

    def expected_attrs(item: dict[str, object]) -> dict[str, str]:
        attrs = {xml_id: str(item["id"]), "type": str(item["type"])}
        if item["type"] == "paragraph":
            # The bundled TEI P5 schema does not permit @type on p.  The
            # native p tag plus source-accountability ID carries this unit's
            # paragraph meaning.
            attrs.pop("type")
        if "n" in item:
            attrs["n"] = str(item["n"])
        if item["type"] == "parallel-reading-table":
            attrs["n"] = str(item["start_line"])
        if item["type"] == "range-occurrence":
            attrs["corresp"] = f"#lightfoot-line-{int(item['start_line']):06d}"
        return attrs

    def line_leaves(node: etree._Element) -> list[etree._Element]:
        return [
            child
            for child in node.iter()
            if child.get("type") == "source-line"
        ]

    for ident, item in expected_by_id.items():
        node = structural[ident]
        expected_tag = native_tags.get(str(item["type"]), f"{{{TEI}}}div")
        if node.tag != expected_tag:
            raise ValueError(f"Lightfoot native tag drifted on {ident}")
        if dict(node.attrib) != expected_attrs(item):
            raise ValueError(f"Lightfoot attributes drifted on {ident}")
        parent = node.getparent()
        expected_parent = item["parent"]
        if expected_parent is None:
            if parent is not body:
                raise ValueError(f"Lightfoot root unit moved: {ident}")
        elif parent is not structural[str(expected_parent)]:
            # TEI's div content model may require a later native paragraph to
            # enter the div-like branch after a heading/gap fragment.  The
            # anonymous source-content fragment is an allowed carrier; the
            # source unit itself must still remain directly under the declared
            # source parent in the accountability map.
            if not (
                item["type"] in {"paragraph", "parallel-reading-table"}
                and parent.tag == f"{{{TEI}}}div"
                and parent.get("type") == "source-content-fragment"
                and parent.getparent() is structural[str(expected_parent)]
            ):
                raise ValueError(f"Lightfoot unit parent moved: {ident}")
        leaves = line_leaves(node)
        numbers = [int(leaf.get("n", "0")) for leaf in leaves]
        expected_numbers = list(range(int(item["start_line"]), int(item["end_line"]) + 1))
        if numbers != expected_numbers:
            raise ValueError(f"Lightfoot source span drifted on {ident}")
        if item["type"] == "range-occurrence":
            if not leaves or leaves[0].tag != f"{{{TEI}}}head":
                raise ValueError(f"Lightfoot source heading is not native on {ident}")
        if item["type"] == "footnote":
            if not leaves or leaves[0].getparent().tag != f"{{{TEI}}}label":
                raise ValueError(f"Lightfoot footnote label is not native on {ident}")

    for role, expected_count in {
        "scripture-text": 120,
        "paraphrase": 18,
        "lemma": 8,
        "apparatus": 11,
        "commentary": 120,
        "mixed-source-line": 1,
    }.items():
        actual = [
            node
            for node in root.iter(f"{{{TEI}}}div")
            if node.get("type") == role
        ]
        if len(actual) != expected_count:
            raise ValueError(f"Lightfoot {role} unit census drifted")

    tables = [
        node
        for node in root.iter(f"{{{TEI}}}table")
        if node.get("type") == "parallel-reading-table"
    ]
    if len(tables) != len(PARALLEL_TABLE_ROWS):
        raise ValueError("Lightfoot native parallel table census drifted")
    for table_id, row_specs in PARALLEL_TABLE_ROWS.items():
        table = structural[table_id]
        rows_in_table = list(table)
        if len(rows_in_table) != len(row_specs):
            raise ValueError(f"Lightfoot parallel table row census drifted on {table_id}")
        for ordinal, (row_node, (start, end, role)) in enumerate(zip(rows_in_table, row_specs, strict=True), 1):
            if row_node.tag != f"{{{TEI}}}row" or dict(row_node.attrib) != {xml_id: f"{table_id}-row-{ordinal:02d}", "n": str(start)}:
                raise ValueError(f"Lightfoot parallel table row identity drifted on {table_id}")
            cells = [child for child in row_node if child.tag == f"{{{TEI}}}cell"]
            if len(cells) != 1 or dict(cells[0].attrib) != {"role": role}:
                raise ValueError(f"Lightfoot parallel table cell mapping drifted on {table_id}")
            paragraphs = [child for child in cells[0] if child.tag == f"{{{TEI}}}p"]
            if len(paragraphs) != 1 or [int(leaf.get("n", "0")) for leaf in line_leaves(paragraphs[0])] != list(range(start, end + 1)):
                raise ValueError(f"Lightfoot parallel table source span drifted on {table_id}")

    leaves = [node for node in root.iter() if node.get("type") == "source-line"]
    if len(leaves) != len(rows):
        raise ValueError("Lightfoot source-line leaf count drifted")
    expected_ana = {int(item["line"]): item["ana"] for item in expected_features}
    observed_segments: dict[int, list[tuple[str, str, str, str]]] = {}
    observed_mixed: dict[int, list[tuple[str, str, str, str, str]]] = {}
    observed_refs: dict[int, list[tuple[str, str, str]]] = {}
    for node, row in zip(leaves, rows, strict=True):
        line = int(row["line"])
        if node.tag not in {f"{{{TEI}}}seg", f"{{{TEI}}}head"}:
            raise ValueError(f"Lightfoot source-line leaf tag drifted at {line}")
        expected_attrs = {xml_id: f"lightfoot-line-{line:06d}", "n": str(line), "type": "source-line"}
        if line in expected_ana:
            expected_attrs["ana"] = " ".join(str(value) for value in expected_ana[line])
        if dict(node.attrib) != expected_attrs or "".join(node.itertext()) != str(row["text"]):
            raise ValueError(f"Lightfoot source-line identity drifted at {line}")
        for seg in node.findall(f"{{{TEI}}}seg"):
            if seg.get("type") == "mixed-source-line-part":
                observed_mixed.setdefault(line, []).append(
                    (
                        str(seg.get(xml_id)),
                        str(seg.get("type")),
                        str(seg.get("corresp")),
                        str(seg.get("ana")),
                        "".join(seg.itertext()),
                    )
                )
            else:
                observed_segments.setdefault(line, []).append((str(seg.get(xml_id)), str(seg.get("type")), str(seg.get("corresp")), "".join(seg.itertext())))
        for ref in node.findall(f"{{{TEI}}}ref"):
            observed_refs.setdefault(line, []).append((str(ref.get(xml_id)), str(ref.get("type")), str(ref.get("target"))))
    for line, expected in segments.items():
        values = [
            (
                f"lightfoot-sidenote-{ordinal:04d}-line-{line:06d}",
                kind,
                f"#lightfoot-sidenote-{ordinal:04d}",
                str(rows[line - 1]["text"])[start:end],
            )
            for start, end, ordinal, kind in sorted(expected)
        ]
        if observed_segments.get(line) != values:
            raise ValueError(f"Lightfoot sidenote structure drifted at line {line}")
    if set(observed_segments) != set(segments):
        raise ValueError("Lightfoot candidate contains unexpected sidenote segments")
    mixed_line, mixed_prefix, mixed_suffix = MIXED_SOURCE_LINE
    expected_mixed = [
        (
            f"lightfoot-mixed-source-line-{mixed_line:06d}-prefix",
            "mixed-source-line-part",
            f"#lightfoot-mixed-source-line-{mixed_line:06d}",
            "#scripture-text",
            mixed_prefix,
        ),
        (
            f"lightfoot-mixed-source-line-{mixed_line:06d}-suffix",
            "mixed-source-line-part",
            f"#lightfoot-mixed-source-line-{mixed_line:06d}",
            "#commentary",
            mixed_suffix,
        ),
    ]
    if observed_mixed.get(mixed_line) != expected_mixed or set(observed_mixed) != {mixed_line}:
        raise ValueError("Lightfoot mixed source-line role segmentation drifted")
    for line, expected in footnote_references.items():
        values = [
            (
                f"lightfoot-footnote-ref-{number}-line-{line:06d}",
                "footnote-reference",
                f"#{target}",
            )
            for _, _, target, number in expected
        ]
        if observed_refs.get(line) != values:
            raise ValueError(f"Lightfoot footnote reference attachment drifted at line {line}")
    if set(observed_refs) != set(footnote_references):
        raise ValueError("Lightfoot candidate contains unexpected footnote references")
    if root.xpath(".//t:div[@type='source-line-container'] | .//t:ab[@type='source-line']", namespaces={"t": TEI}):
        raise ValueError("Lightfoot candidate retains arbitrary source-line wrappers")
    expected_heads = set(heading_lines)
    observed_heads = {
        int(node.get("n", "0"))
        for node in root.iter(f"{{{TEI}}}head")
        if node.get("type") == "source-line"
    }
    if observed_heads != expected_heads:
        raise ValueError("Lightfoot source heading census drifted")


def _oracle(source_manifest: SourceManifest, candidate: CandidatePackage) -> dict[str, object]:
    source_manifest.verify()
    candidate.verify_integrity()
    content = _source(source_manifest)
    rows = _rows(content)
    profile_bytes = source_manifest.authority_path("reconstruction-profile").read_bytes()
    policy_bytes = source_manifest.authority_path("validation-policy").read_bytes()
    profile = _obj(profile_bytes, "Lightfoot profile")
    policy = _obj(policy_bytes, "Lightfoot policy")
    if profile.get("profile_id") != "lightfoot-colossians-philemon-v3" or policy.get("policy_id") != "lightfoot-colossians-philemon-policy-v3" or policy.get("oracle_version") != "3":
        raise ValueError("Lightfoot profile or policy identity drifted")
    package_schema_bytes = source_manifest.authority_path("candidate-package-schema").read_bytes()
    package_schema = _obj(package_schema_bytes, "candidate package schema")
    manifest = _obj((candidate.path / "manifest.json").read_bytes(), "candidate manifest")
    errors = sorted(Draft202012Validator(package_schema).iter_errors(manifest), key=str)
    if errors:
        raise ValueError(f"Lightfoot candidate manifest schema failure: {errors[0].message}")
    units, notes, sidenotes, segments = _inventory(rows)
    footnote_references = _footnote_references(rows, notes)
    heading_lines = _heading_lines(rows, [item for item in units if item["type"] == "range-occurrence"])
    helper_path = Path(__file__).with_name("lightfoot_typography_oracle.py")
    helper_spec = importlib.util.spec_from_file_location("lightfoot_typography_oracle", helper_path)
    if helper_spec is None or helper_spec.loader is None:
        raise ValueError("Lightfoot independent typography checker is unavailable")
    helper = importlib.util.module_from_spec(helper_spec)
    sys.modules[helper_spec.name] = helper
    helper_spec.loader.exec_module(helper)
    expected_account = _account(rows, content, units, notes, sidenotes, segments, footnote_references)
    source_lines = [str(row["text"]) for row in rows]
    expected_account["typography"] = {
        "spans": helper.discover_source_spans(source_lines),
        "literal_caret_markers": [
            {key: marker[key] for key in ("line", "start_char", "end_char", "token")}
            for marker in helper.source_census(source_lines)["literals"]["carets"]
            if not marker["rendered"]
        ],
    }
    account_bytes = candidate.member_bytes("source-accountability.json")
    if account_bytes != _canon(expected_account) or _obj(account_bytes, "Lightfoot accountability") != expected_account:
        raise ValueError("Lightfoot source accountability is not source-derived")
    expected_manifest = {
        "contract": "ocd-candidate-package-v1", "status": "nonaccepted", "source_id": source_manifest.record["source_id"],
        "source_manifest": {"path": source_manifest.path.relative_to(source_manifest.repository_root).as_posix(), "sha256": source_manifest.sha256},
        "converter": dict(source_manifest.record["converter"]), "package_schema": dict(source_manifest.record["package_schema"]),
        "members": [{"name": name, "bytes": len(candidate.member_bytes(name)), "sha256": _sha(candidate.member_bytes(name))} for name in sorted(("README.source.md", "content.tei.xml", "provenance.json", "source-accountability.json", "unresolved.jsonl"))],
    }
    if manifest != expected_manifest:
        raise ValueError("Lightfoot candidate manifest binding drifted")
    try:
        tei = etree.fromstring(candidate.member_bytes("content.tei.xml"))
    except etree.LxmlError as exc:
        raise ValueError("Lightfoot candidate TEI is not well-formed XML") from exc
    _header(tei)
    expected_features = expected_account["line_features"]
    assert isinstance(expected_features, list)
    _assert_reference_content(tei, rows, footnote_references)
    structural_tei = helper.verify_and_normalize_typography(tei, [str(row["text"]) for row in rows])
    _assert_tree(structural_tei, rows, units, segments, expected_features, footnote_references, heading_lines)
    try:
        xsd = etree.XMLSchema(etree.parse(str(source_manifest.authority_path("tei-p5-xsd"))))
        xsd.assertValid(tei)
    except etree.LxmlError as exc:
        raise ValueError("Lightfoot candidate failed direct TEI P5 XSD validation") from exc
    account_schema = _obj(source_manifest.authority_path("source-accountability-schema").read_bytes(), "Lightfoot accountability schema")
    account_errors = sorted(Draft202012Validator(account_schema).iter_errors(expected_account), key=str)
    if account_errors:
        raise ValueError(f"Lightfoot accountability schema failure: {account_errors[0].message}")
    expected_provenance = {
        "contract": "ocd-lightfoot-colossians-philemon-candidate-provenance-v3", "status": "nonaccepted", "ticket_id": "LIB-070", "work_id": "lightfoot-colossians-philemon", "source_id": source_manifest.record["source_id"], "source_manifest_sha256": source_manifest.sha256, "source_sha256": _sha(content), "source_authority": "D:/Library/Open Christian Data/raw/gutenberg/commentary/lightfoot-colossians-philemon/pg50857.txt", "candidate_boundary": {"acceptance_status": "nonaccepted", "publication_status": "not-authorized", "canonical_data_or_ir_written": False},
    }
    if _obj(candidate.member_bytes("provenance.json"), "Lightfoot provenance") != expected_provenance or candidate.member_bytes("provenance.json") != _canon(expected_provenance):
        raise ValueError("Lightfoot provenance drifted")
    expected_unresolved = [
        {"id": "lightfoot-rights-review", "status": "unresolved", "detail": "Validation does not establish worldwide publication rights."},
        {"id": "lightfoot-human-acceptance", "status": "unresolved", "detail": "This candidate has not received human textual acceptance."},
        {"id": "lightfoot-visual-source-compare", "status": "unresolved", "detail": "No supported browser visual comparison was available in this execution."},
    ]
    if candidate.member_bytes("unresolved.jsonl") != b"".join(_canon(item) for item in expected_unresolved):
        raise ValueError("Lightfoot unresolved evidence drifted")
    if candidate.member_bytes("README.source.md") != source_manifest.authority_path("source-attribution-readme").read_bytes():
        raise ValueError("Lightfoot source attribution evidence drifted")
    result: dict[str, object] = {
        "status": "pass", "oracle_id": ORACLE_ID, "oracle_version": ORACLE_VERSION, "implementation_sha256": _sha(Path(__file__).read_bytes()), "import_closure_sha256": _closure(source_manifest.repository_root), "runtime": f"{platform.python_implementation()} {platform.python_version()} ({Path(sys.executable).resolve(strict=True)})", "source_manifest_sha256": source_manifest.sha256, "candidate_sha256": candidate.sha256, "profile_sha256": _sha(profile_bytes), "package_schema_sha256": _sha(package_schema_bytes), "source_sha256": _sha(content), "xsd_sha256": _sha(source_manifest.authority_path("tei-p5-xsd").read_bytes()), "policy_sha256": _sha(policy_bytes), "findings": [],
    }
    result["result_sha256"] = _sha(_canon(result))
    return result


_oracle.oracle_id = ORACLE_ID
_oracle.oracle_version = ORACLE_VERSION
_oracle.implementation_path = Path(__file__).resolve()
