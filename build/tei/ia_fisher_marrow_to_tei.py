"""Census and convert the Fisher Marrow IA DjVuTXT witness into TEI.

This module deliberately reads the raw Internet Archive OCR witness.  The
existing structured-text parser is a downstream projection and is not an
input to this converter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT
from ocd_kernel.tei.writer import TEI_NS, serialize, stamp_header, tei_el

RAW_PATH = REPO_ROOT / "raw" / "internet-archive" / "fisher-marrow" / "marrowmoderndiv00bostgoog_djvu.txt"
TEI_PATH = REPO_ROOT / "ir" / "fisher" / "fisher-marrow-of-modern-divinity.ia-ocr.tei.xml"
CENSUS_PATH = REPO_ROOT / "ir" / "census" / "fisher-marrow-of-modern-divinity.ia-ocr.census.json"

SOURCE_URL = "https://archive.org/details/marrowmoderndiv00bostgoog"
SOURCE_SHA_PREFIX = "sha256:"
CENSUS_SCHEMA = "tei-census-v1"
WORK_ID = "fisher-marrow-of-modern-divinity"
RENDERING_ID = "ia-ocr"
TEI_ID_PREFIX = "fisher-marrow"

# These are the forms that the raw census established as high-confidence
# speaker labels.  The spelling and punctuation are kept exactly in the TEI.
# More damaged starts remain ordinary prose and are reported as ambiguous;
# no OCR repair is hidden in the classifier.
SPEAKER_TOKEN_RE = (
    r"Evan|Nom|Nam|Ant|Neo|Norn|AnL|Anl|"
    r"iVeo|jVeo|JVeo|JVbm|jVbm|iVbm|JVom|jVom|iVom|"
    r"Mvan|Etfan|Eran|Euan|Ecan|Eean|E\^an|&an|£van|"
    r"N\^om|No7n|Nmn|n&Qt|N\^eo|\^eo|N\^o|iVffo|iV\^o|JV\^o"
)
SPEAKER_RE = re.compile(
    rf"^(?P<label>(?:{SPEAKER_TOKEN_RE}))(?P<punct>[.,;:!?*^>\-»~']*)"
    r"(?P<space>\s+)(?P<rest>.*)$"
)
SECTION_SPEAKER_RE = re.compile(
    rf"^(?P<label>(?:{SPEAKER_TOKEN_RE}))(?P<punct>[.,;:!?*^>\-»~']*)"
    r"(?P<space>\s+)(?P<rest>.*)$"
)

CHAPTER_RE = re.compile(r"^(?:CHAP|CHAPTER)\.?\s+[A-Z]+\.?\s*$")
PART_SECOND_RE = re.compile(r"^PART\s+SECOND[,\.\s]*$")
COMMANDMENT_RE = re.compile(r"^COMMANDMENT\s+(?P<num>[A-Z]+)[,\.\-\s]*$")
INTRODUCTION_RE = re.compile(r"^INTRODUCTION\.?\s*$", re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"^\d+\s*$")
ROMAN_PAGE_RE = re.compile(r"^[IVXLCDM]+\s*$", re.IGNORECASE)
SECTION_PREFIX_RE = re.compile(
    r"^(?P<prefix>SECT(?:ION)?[*.,\-]?\s*)"
    r"(?P<num>[A-Za-z0-9iIvVxXlLmM-]+)?(?P<rest>.*)$",
    re.IGNORECASE,
)

FRONT_HEADINGS = (
    ("RECOMMENDATIONS", "recommendations"),
    ("PREFACE", "preface"),
    ("DEDICATION", "dedication"),
    ("TO THE READER", "to-reader"),
)


@dataclass(frozen=True)
class RawLine:
    number: int
    text: str
    page_break_before: bool = False


@dataclass(frozen=True)
class SectionMarker:
    kind: str
    line: RawLine
    prefix: str
    body: str
    number: str | None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_raw(path: Path) -> tuple[str, list[RawLine]]:
    text = path.read_text(encoding="utf-8-sig")
    lines: list[RawLine] = []
    for number, newline_line in enumerate(text.split("\n"), start=1):
        parts = newline_line.split("\f")
        for index, part in enumerate(parts):
            lines.append(RawLine(number, part, page_break_before=index > 0))
    return text, lines


def _is_page_marker(value: str) -> bool:
    stripped = value.strip()
    return bool(PAGE_NUMBER_RE.fullmatch(stripped) or ROMAN_PAGE_RE.fullmatch(stripped))


def _is_running_header(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    upper = stripped.upper()
    if re.match(r"^(?:CHAP|CHAPTER)\.?\s+", stripped, re.IGNORECASE):
        return not bool(CHAPTER_RE.fullmatch(stripped))
    if re.match(r"^PAR[TI]\b", stripped, re.IGNORECASE):
        return not bool(PART_SECOND_RE.fullmatch(stripped))
    if "MARROW OF MODERN DIVINITY" in upper and len(stripped) < 70:
        return True
    if upper.startswith("THE MARROW OF") or upper.startswith("MODERN DIVINITY"):
        return True
    if upper in {"THE MARROW", "MARROW", "OF MODERN DIVINITY", "MARROW OF", "MARROW OF MODERN"}:
        return True
    return False


def _body_start(lines: list[RawLine]) -> int:
    for index, line in enumerate(lines):
        if INTRODUCTION_RE.fullmatch(line.text.strip()):
            return index
    raise ValueError("raw Fisher OCR has no INTRODUCTION. body boundary")


def _section_marker(line: RawLine) -> SectionMarker | None:
    value = line.text.strip()
    match = SECTION_PREFIX_RE.fullmatch(value)
    if not match:
        return None
    prefix = match.group("prefix")
    number = match.group("num")
    rest = match.group("rest")
    if value.upper().startswith("SECTION") and number:
        return SectionMarker("heading", line, value, "", number)

    # A synopsis has prose between its number and the dash that introduces
    # the next numbered topic.  It is kept as prose, not promoted to a div.
    # One OCR line starts with the separator itself and then contains a second
    # topic separator (line 6282 in the witness).  Keep that damaged contents
    # line in the synopsis class rather than treating the first dash as a
    # section boundary.
    if number and rest.count("—") + rest.count("–") >= 2:
        return SectionMarker("synopsis", line, "", value, number)
    if number and not re.match(r"^[*.,\-\s]*[—–-]", rest):
        if re.search(r"[—–-]\s*\d", rest) or rest.count("—") + rest.count("–") >= 2:
            return SectionMarker("synopsis", line, "", value, number)

    separator = re.search(r"[—–]", rest)
    if separator:
        before = rest[:separator.end()]
        after = rest[separator.end():]
        if re.match(r"\s*(?:Of|Or)\b", after, re.IGNORECASE):
            return SectionMarker("heading", line, value, "", number)
        return SectionMarker("boundary", line, value[: value.find(rest) + separator.end()], after, number)

    # This is the real OCR form "sect, vit But ...": the Roman numeral is
    # damaged and the body begins without a dash.  Preserve the ambiguous
    # number as raw text while still carrying the recoverable boundary.
    if number and re.match(r"\s*(?:But|And|Ant|Evan|Nom|Nam|Neo|Norn|AnL|iVeo|JVbm)\b", rest, re.IGNORECASE):
        prefix_end = value.find(rest)
        return SectionMarker("boundary", line, value[:prefix_end], rest, number)

    return SectionMarker("synopsis", line, "", value, number)


def _speaker_match(value: str) -> re.Match[str] | None:
    return SPEAKER_RE.fullmatch(value)


def _section_body_parts(marker: SectionMarker) -> tuple[str, str]:
    if marker.kind != "boundary":
        return "", ""
    prefix = marker.prefix
    body = marker.body
    # The section regex retains the raw prefix through the dash.  Keep the
    # whitespace after that dash in the body so visible source text is not
    # silently compacted.
    return prefix, body


def _feature(count: int, ids: Iterable[str] = ()) -> dict:
    return {"count": count, "ids": list(ids)}


def _line_id(kind: str, line_number: int, ordinal: int | None = None) -> str:
    suffix = f"-{ordinal}" if ordinal is not None else ""
    return f"{TEI_ID_PREFIX}-l{line_number}-{kind}{suffix}"


def _structural_lines(lines: list[RawLine], body_start: int) -> dict:
    body = lines[body_start:]
    chapters = [line for line in body if CHAPTER_RE.fullmatch(line.text.strip())]
    part_second = [line for line in body if PART_SECOND_RE.fullmatch(line.text.strip())]
    commandments = [line for line in body if COMMANDMENT_RE.fullmatch(line.text.strip())]
    sections = [marker for line in body if (marker := _section_marker(line)) is not None]
    section_markers = [m for m in sections if m.kind in {"heading", "boundary"}]
    synopses = [m for m in sections if m.kind == "synopsis"]

    speaker_forms: dict[str, int] = {}
    speaker_lines: list[RawLine] = []
    ambiguous: list[dict[str, object]] = []
    in_paragraph = False
    for line in body:
        stripped = line.text.strip()
        if not stripped:
            in_paragraph = False
            continue
        if _is_page_marker(stripped) or _is_running_header(stripped):
            continue
        marker = _section_marker(line)
        candidate = marker.body if marker and marker.kind == "boundary" else stripped
        if marker and marker.kind == "synopsis":
            continue
        match = _speaker_match(candidate.strip()) if not in_paragraph or marker else None
        if match:
            label = match.group("label") + match.group("punct")
            speaker_forms[label] = speaker_forms.get(label, 0) + 1
            speaker_lines.append(line)
        elif not in_paragraph and re.match(r"^[A-Za-z£&^JVNMi].{0,8}\s+", stripped):
            if any(ch in stripped.split(None, 1)[0] for ch in "JV^£&"):
                ambiguous.append({"line": line.number, "text": stripped[:120]})
        in_paragraph = True

    marker_counts = {
        marker: {"characters": sum(line.text.count(marker) for line in lines), "lines": sum(marker in line.text for line in lines)}
        for marker in ("*", "†", "‡", "§")
    }
    all_text = "\n".join(line.text for line in lines)
    greek = sum(0x0370 <= ord(char) <= 0x03FF for char in all_text)
    hebrew = sum(0x0590 <= ord(char) <= 0x05FF for char in all_text)
    return {
        "body": body,
        "chapters": chapters,
        "part_second": part_second,
        "commandments": commandments,
        "sections": sections,
        "section_markers": section_markers,
        "synopses": synopses,
        "speaker_forms": speaker_forms,
        "speaker_lines": speaker_lines,
        "ambiguous_speaker_like": ambiguous,
        "marker_counts": marker_counts,
        "greek_codepoints": greek,
        "hebrew_codepoints": hebrew,
    }


def census_fisher_marrow(raw_path: str | Path = RAW_PATH) -> dict:
    path = Path(raw_path)
    raw_text, lines = _read_raw(path)
    body_start = _body_start(lines)
    observed = _structural_lines(lines, body_start)
    chapter_ids = [_line_id("chapter", line.number, index) for index, line in enumerate(observed["chapters"], 1)]
    commandment_ids = [_line_id("commandment", line.number, index) for index, line in enumerate(observed["commandments"], 1)]
    section_ids = [_line_id("section", marker.line.number, index) for index, marker in enumerate(observed["section_markers"], 1)]
    synopsis_ids = [_line_id("synopsis", marker.line.number) for marker in observed["synopses"]]
    synopsis_p_ids = [_line_id("p", marker.line.number) for marker in observed["synopses"]]
    page_break_count = raw_text.count("\f")
    return {
        "census_schema": CENSUS_SCHEMA,
        "source": {
            "type": "internet_archive_djvutxt",
            "work_id": WORK_ID,
            "rendering_id": RENDERING_ID,
            "path": path.resolve().relative_to(REPO_ROOT.resolve()).as_posix(),
            "sha256": _sha256(path),
            "scope": {
                "start_line": lines[body_start].number,
                "start_marker": lines[body_start].text.strip(),
                "end": "end of raw witness",
                "excluded_before_body": "Google Books wrapper, title-page/contents container, and front matter before the first Recommendations heading; the preserved editorial front matter begins at the first Recommendations heading.",
            },
        },
        "ocr_quality": {
            "classification": "ocr-raw-english-prose",
            "english_prose": "Readable enough for structural ingestion, but visibly uncorrected ABBYY OCR; residual character and word errors remain in the TEI text.",
            "greek_codepoints": observed["greek_codepoints"],
            "hebrew_codepoints": observed["hebrew_codepoints"],
            "tables": "No table carrier was observed in the selected scope.",
            "apparatus": "Asterisk and section-mark symbols occur inline, but the DjVuTXT witness does not reliably delimit Boston footnote bodies from main prose; no note boundaries are invented.",
            "evidence_samples": [
                {"line": line.number, "text": line.text.strip()}
                for line in [
                    next(line for line in lines if line.number == 2503),
                    next(line for line in lines if line.number == 15573),
                    next(line for line in lines if line.number == 19090),
                ]
            ],
        },
        "structure": {
            "raw_line_count": len(lines),
            "newline_count": raw_text.count("\n"),
            "form_feed_page_breaks": page_break_count,
            "body_start_line": lines[body_start].number,
            "chapter_headings": {
                "count": len(observed["chapters"]),
                "ids": chapter_ids,
                "forms": {line.text.strip(): sum(other.text.strip() == line.text.strip() for other in observed["chapters"]) for line in observed["chapters"]},
            },
            "parts": {"count": 2, "explicit_part_second_boundaries": len(observed["part_second"])},
            "commandment_headings": {
                "count": len(observed["commandments"]),
                "ids": commandment_ids,
                "forms": {line.text.strip(): sum(other.text.strip() == line.text.strip() for other in observed["commandments"]) for line in observed["commandments"]},
                "missing_standalone_headings": ["COMMANDMENT III", "COMMANDMENT V"],
            },
            "section_markers": {
                "all_sect_prefixed_lines": len(observed["sections"]),
                "structural_count": len(observed["section_markers"]),
                "ids": section_ids,
                "heading_forms": [marker.line.text.strip() for marker in observed["section_markers"] if marker.kind == "heading"],
                "synopsis_count": len(observed["synopses"]),
                "synopsis_ids": synopsis_ids,
                "synopsis_forms": [marker.line.text.strip() for marker in observed["synopses"]],
                "punctuation_forms": {
                    key: sum(
                        1
                        for marker in observed["sections"]
                        if marker.line.text.strip().lower().startswith(key)
                    )
                    for key in ("sect.", "sect*", "sect,", "sect-", "sect ", "section")
                },
            },
            "speaker_labels": {
                "high_confidence_count": sum(observed["speaker_forms"].values()),
                "forms": observed["speaker_forms"],
                "ambiguous_unconverted_count": len(observed["ambiguous_speaker_like"]),
                "ambiguous_samples": observed["ambiguous_speaker_like"][:12],
            },
            "inline_marker_counts": observed["marker_counts"],
        },
        "features": {
            "chapters": _feature(len(observed["chapters"]), chapter_ids),
            "parts": _feature(2, [f"{TEI_ID_PREFIX}-part-I", f"{TEI_ID_PREFIX}-part-II"]),
            "commandments": _feature(len(observed["commandments"]), commandment_ids),
            "sections": _feature(len(observed["section_markers"]), section_ids),
            "section_synopses": _feature(len(observed["synopses"]), synopsis_p_ids),
            "page_breaks": _feature(page_break_count),
            "speaker_labels": _feature(sum(observed["speaker_forms"].values())),
        },
    }


def _append_text(parent: etree._Element, text: str) -> None:
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _append_raw_paragraph(parent: etree._Element, line_number: int, lines: list[str], *, rend: str | None = None) -> etree._Element:
    attrs = {"xml:id": _line_id("p", line_number)}
    if rend:
        attrs["rend"] = rend
    node = tei_el("p", attrs)
    node.text = "\n".join(lines)
    parent.append(node)
    return node


def _append_dialogue(parent: etree._Element, line_number: int, lines: list[str]) -> bool:
    first = lines[0]
    leading = first[: len(first) - len(first.lstrip())]
    match = _speaker_match(first.lstrip())
    if not match:
        return False
    speaker = match.group("label") + match.group("punct")
    sp = tei_el("sp", {"xml:id": _line_id("sp", line_number)})
    sp.append(tei_el("speaker", {"xml:id": _line_id("speaker", line_number)}, speaker))
    body_lines = [leading + match.group("space") + match.group("rest"), *lines[1:]]
    _append_raw_paragraph(sp, line_number, body_lines)
    parent.append(sp)
    return True


def _append_paragraph(parent: etree._Element, line_number: int, lines: list[str], *, rend: str | None = None) -> None:
    if not lines:
        return
    if rend is None and _append_dialogue(parent, line_number, lines):
        return
    _append_raw_paragraph(parent, line_number, lines, rend=rend)


def _front_div(parent: etree._Element, kind: str, start: int, stop: int, lines: list[RawLine], heading: str) -> None:
    div = tei_el("div", {"type": kind, "xml:id": f"{TEI_ID_PREFIX}-front-{kind}"})
    div.append(tei_el("head", {"xml:id": f"{TEI_ID_PREFIX}-front-{kind}-head"}, heading))
    paragraph: list[str] = []
    paragraph_start = start
    seen_heading = False

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            _append_paragraph(div, paragraph_start, paragraph)
            paragraph = []

    for line in lines:
        if not start <= line.number < stop:
            continue
        if line.page_break_before:
            flush()
            div.append(tei_el("pb", {"xml:id": _line_id("pb", line.number)}))
        stripped = line.text.strip()
        if not stripped:
            flush()
            continue
        if _is_page_marker(stripped) or _is_running_header(stripped):
            continue
        if stripped.upper() == heading.upper() or (
            heading.upper() == "PREFACE"
            and re.search(r"\bPREFACE\.?$", stripped, re.IGNORECASE)
        ):
            if seen_heading:
                continue
            seen_heading = True
            continue
        if not paragraph:
            paragraph_start = line.number
        paragraph.append(line.text)
    flush()
    parent.append(div)


def _titlepage(parent: etree._Element, lines: list[RawLine]) -> None:
    start = next((line.number for line in lines if line.text.strip() == "THE" and line.number > 50), None)
    if start is None:
        return
    stop = next((line.number for line in lines if line.number > start and re.fullmatch(r"\s*1837\.??\s*", line.text)), start)
    div = tei_el("div", {"type": "titlepage", "xml:id": f"{TEI_ID_PREFIX}-titlepage"})
    paragraph: list[str] = []
    paragraph_start = start
    for line in lines:
        if not start <= line.number <= stop:
            continue
        if not line.text.strip():
            if paragraph:
                _append_raw_paragraph(div, paragraph_start, paragraph)
                paragraph = []
            continue
        if line.text.strip() in {"STANFORD", "UNIVERSITY", "LIBRARIES"}:
            continue
        if not paragraph:
            paragraph_start = line.number
        paragraph.append(line.text)
    if paragraph:
        _append_raw_paragraph(div, paragraph_start, paragraph)
    parent.append(div)


def _new_div(kind: str, line_number: int, ordinal: int | None = None, number: str | None = None) -> etree._Element:
    attrs = {"type": kind, "xml:id": _line_id(kind, line_number, ordinal)}
    if number:
        attrs["n"] = number
    return tei_el("div", attrs)


def _convert(raw_path: Path, output_path: Path) -> None:
    raw_text, lines = _read_raw(raw_path)
    body_start = _body_start(lines)
    observed = _structural_lines(lines, body_start)
    source_hash = _sha256(raw_path)

    tei = tei_el("TEI")
    tei.append(
        stamp_header(
            title="The Marrow of Modern Divinity",
            author="Edward Fisher",
            contributors=["Thomas Boston (annotator)"],
            source_url=SOURCE_URL,
            source_sha256=source_hash,
            print_source="Boston annotated edition, Edinburgh 1828, Internet Archive DjVuTXT OCR witness.",
        )
    )
    source_desc = tei.xpath(
        "./tei:teiHeader/tei:fileDesc/tei:sourceDesc",
        namespaces={"tei": TEI_NS},
    )[0]
    source_bibl = source_desc.find(f"{{{TEI_NS}}}bibl")
    if source_bibl is None:
        raise ValueError("TEI header sourceDesc has no bibl carrier")
    source_bibl.append(tei_el("note", {"type": "scope"}, "Raw witness scope starts at INTRODUCTION.; Google Books wrapper and contents are excluded, while editorial front matter is preserved."))
    source_bibl.append(tei_el("note", {"type": "ocr-quality"}, "Uncorrected ABBYY OCR is ingested as an inherent source limit. Inline asterisk and section marks are preserved; ambiguous footnote boundaries are not invented."))

    text_node = tei_el("text")
    front = tei_el("front")
    _titlepage(front, lines)
    heading_positions = []
    for heading, kind in FRONT_HEADINGS:
        match = next(
            (
                line
                for line in lines
                if line.number >= 200
                and (
                    line.text.strip().upper() == heading
                    or (
                        heading == "PREFACE"
                        and re.search(r"\bPREFACE\.?$", line.text.strip(), re.IGNORECASE)
                    )
                )
            ),
            None,
        )
        if match:
            heading_positions.append((match.number, heading, kind))
    heading_positions.sort()
    for index, (start, heading, kind) in enumerate(heading_positions):
        stop = heading_positions[index + 1][0] if index + 1 < len(heading_positions) else lines[body_start].number
        _front_div(front, kind, start, stop, lines, heading)
    text_node.append(front)

    body_node = tei_el("body")
    part_one = _new_div("part", lines[body_start].number, 1, "I")
    part_one.append(tei_el("head", {"xml:id": f"{TEI_ID_PREFIX}-part-I-head"}, "PART I."))
    body_node.append(part_one)
    current_chapter: etree._Element | None = None
    current_section: etree._Element | None = None
    current_part = part_one
    paragraph: list[str] = []
    paragraph_start = lines[body_start].number
    paragraph_rend: str | None = None
    chapter_ordinal = 0
    section_ordinal = 0
    commandment_ordinal = 0
    in_part_two = False
    pending_chapter_title = False
    intro = _new_div("introduction", lines[body_start].number, 1)
    intro.append(
        tei_el(
            "head",
            {"xml:id": _line_id("introduction-head", lines[body_start].number)},
            lines[body_start].text,
        )
    )
    intro_opening = _new_div("prologue", lines[body_start].number, 1)
    intro.append(intro_opening)
    part_one.append(intro)
    current_container = intro_opening

    def flush(rend: str | None = None) -> None:
        nonlocal paragraph, paragraph_rend
        if paragraph:
            _append_paragraph(current_container, paragraph_start, paragraph, rend=rend or paragraph_rend)
            paragraph = []
            paragraph_rend = None

    for line in lines[body_start:]:
        if line.page_break_before:
            flush()
            current_container.append(tei_el("pb", {"xml:id": _line_id("pb", line.number)}))
        stripped = line.text.strip()
        if not stripped:
            flush()
            continue
        if _is_page_marker(stripped) or _is_running_header(stripped):
            continue
        if PART_SECOND_RE.fullmatch(stripped):
            flush()
            in_part_two = True
            current_part = _new_div("part", line.number, 2, "II")
            current_part.append(tei_el("head", {"xml:id": f"{TEI_ID_PREFIX}-part-II-head"}, line.text))
            body_node.append(current_part)
            part_two_opening = _new_div("prologue", line.number, 1)
            current_part.append(part_two_opening)
            current_container = part_two_opening
            current_chapter = None
            current_section = None
            intro = None
            pending_chapter_title = False
            continue
        commandment = COMMANDMENT_RE.fullmatch(stripped)
        if in_part_two and commandment:
            flush()
            commandment_ordinal += 1
            current_section = _new_div("commandment", line.number, commandment_ordinal, commandment.group("num"))
            current_section.append(tei_el("head", {"xml:id": _line_id("commandment-head", line.number)}, line.text))
            current_part.append(current_section)
            current_container = current_section
            continue
        if not in_part_two and CHAPTER_RE.fullmatch(stripped):
            flush()
            chapter_ordinal += 1
            current_chapter = _new_div("chapter", line.number, chapter_ordinal, str(chapter_ordinal))
            current_chapter.append(tei_el("head", {"xml:id": _line_id("chapter-head", line.number)}, line.text))
            current_part.append(current_chapter)
            current_container = current_chapter
            current_section = None
            pending_chapter_title = True
            intro = None
            continue
        if pending_chapter_title:
            if stripped == stripped.upper() and any(char.isalpha() for char in stripped):
                current_chapter.append(tei_el("head", {"xml:id": _line_id("chapter-title", line.number)}, line.text))
                pending_chapter_title = False
                continue
            pending_chapter_title = False

        marker = _section_marker(line)
        if marker is not None:
            if marker.kind == "synopsis":
                flush()
                if not paragraph:
                    paragraph_start = line.number
                paragraph.append(line.text)
                paragraph_rend = "section-synopsis"
                continue
            if current_chapter is None:
                # Introduction is a real body unit before Chapter I.
                if intro is None:
                    intro = _new_div("introduction", lines[body_start].number, 1)
                    intro.append(tei_el("head", {"xml:id": _line_id("introduction-head", lines[body_start].number)}, lines[body_start].text))
                    part_one.append(intro)
                current_container = intro
            flush()
            section_ordinal += 1
            section = _new_div("section", marker.line.number, section_ordinal, marker.number)
            prefix, section_body = _section_body_parts(marker)
            if marker.kind == "heading":
                section.append(tei_el("head", {"xml:id": _line_id("section-head", line.number)}, line.text))
            else:
                section.append(tei_el("head", {"xml:id": _line_id("section-head", line.number)}, prefix))
                if section_body:
                    paragraph_start = line.number
                    paragraph = [section_body]
            if current_chapter is not None:
                current_chapter.append(section)
            else:
                current_container.append(section)
            current_section = section
            current_container = section
            continue

        if not paragraph:
            paragraph_start = line.number
        paragraph.append(line.text)

    flush()
    text_node.append(body_node)
    tei.append(text_node)
    serialize(etree.ElementTree(tei), output_path)


def write_census(raw_path: Path, census_path: Path) -> dict:
    census = census_fisher_marrow(raw_path)
    census_path.parent.mkdir(parents=True, exist_ok=True)
    census_path.write_text(json.dumps(census, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return census


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=RAW_PATH)
    parser.add_argument("--tei", type=Path, default=TEI_PATH)
    parser.add_argument("--census", type=Path, default=CENSUS_PATH)
    parser.add_argument("--census-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    write_census(args.raw, args.census)
    if not args.census_only:
        _convert(args.raw, args.tei)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
