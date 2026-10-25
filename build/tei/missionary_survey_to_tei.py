"""Reconstruct Project Gutenberg 13360 as a faithful, nonaccepted TEI candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import etree

from ocd_kernel.tei.validate import validate_file
from ocd_kernel.tei.writer import XML_LANG, XML_NS, serialize, stamp_header, tei_el

PG_START = "*** START OF THE PROJECT GUTENBERG EBOOK"
PG_END = "*** END OF THE PROJECT GUTENBERG EBOOK"
CHAPTER_RE = re.compile(r"^CHAPTER ([IVX]+)\.$")
FOOTNOTE_BODY_RE = re.compile(r"^\[Footnote (\d+):")
FOOTNOTE_REF_RE = re.compile(r"\[(\d+)\]")
EMPHASIS_RE = re.compile(r"_([^_\n]+)_")
ROMANS = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI")
SOURCE_URL = "https://www.gutenberg.org/cache/epub/13360/pg13360.txt"
HTML_URL = "https://www.gutenberg.org/cache/epub/13360/pg13360-images.html"
LANDING_URL = "https://www.gutenberg.org/ebooks/13360"
XML_ID = f"{{{XML_NS}}}id"
BLOCK_STYLE = "display: block; margin: 0.75rem 0"


class ConversionError(ValueError):
    """Raised when the retained source does not match the released work."""


@dataclass(frozen=True)
class Block:
    start_line: int
    end_line: int
    lines: tuple[str, ...]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class ParsedSource:
    path: Path
    raw_lines: tuple[str, ...]
    start_index: int
    end_index: int
    selected_lines: tuple[str, ...]
    blocks: tuple[Block, ...]
    chapter_block_indexes: tuple[int, ...]


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    receipt_path: Path
    accounting_path: Path
    validation_path: Path
    table_count: int
    chapter_count: int
    source_line_carrier_count: int


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(value))


def _blocks(lines: tuple[str, ...], first_raw_line: int) -> tuple[Block, ...]:
    result: list[Block] = []
    current: list[str] = []
    start_line = first_raw_line
    for offset, line in enumerate(lines):
        raw_line = first_raw_line + offset
        if not line.strip():
            if current:
                result.append(Block(start_line, raw_line - 1, tuple(current)))
                current = []
            start_line = raw_line + 1
            continue
        if not current:
            start_line = raw_line
        current.append(line)
    if current:
        result.append(Block(start_line, first_raw_line + len(lines) - 1, tuple(current)))
    return tuple(result)


def parse_source(path: Path) -> ParsedSource:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ConversionError("Project Gutenberg text authority is not UTF-8") from error
    lines = tuple(text.splitlines())
    start_matches = [index for index, line in enumerate(lines) if line.startswith(PG_START)]
    end_matches = [index for index, line in enumerate(lines) if line.startswith(PG_END)]
    if len(start_matches) != 1 or len(end_matches) != 1:
        raise ConversionError("Expected exactly one Project Gutenberg start and end marker")
    start_index, end_index = start_matches[0], end_matches[0]
    if end_index <= start_index:
        raise ConversionError("Project Gutenberg end marker precedes start marker")
    selected = lines[start_index + 1 : end_index]
    blocks = _blocks(selected, start_index + 2)
    chapter_indexes = tuple(
        index for index, block in enumerate(blocks) if CHAPTER_RE.fullmatch(block.text)
    )
    if len(chapter_indexes) != 22:
        raise ConversionError(f"Expected 22 contents/body chapter labels, found {len(chapter_indexes)}")
    sequences = tuple(CHAPTER_RE.fullmatch(blocks[index].text).group(1) for index in chapter_indexes)
    if sequences[:11] != ROMANS or sequences[11:] != ROMANS:
        raise ConversionError(f"Unexpected chapter sequence: {sequences!r}")
    required_blocks = {
        "Transcriber's Note: In order to maintain appropriate line length, some\n"
        "tables have been transposed, i.e. rows are columns and vice versa.",
        "PREFACE.",
        "ANALYSIS OF CONTENTS.",
    }
    present = {block.text for block in blocks}
    missing = sorted(required_blocks - present)
    if missing:
        raise ConversionError(f"Required source blocks missing: {missing!r}")
    return ParsedSource(path, lines, start_index, end_index, selected, blocks, chapter_indexes)


def _normalized_line(line: str) -> str:
    return EMPHASIS_RE.sub(lambda match: match.group(1), line)


def _line_digest(lines: Iterable[str]) -> str:
    return _sha256_bytes("\n".join(lines).encode("utf-8"))


def _is_table(block: Block) -> bool:
    pipe_lines = sum("|" in line for line in block.lines)
    rule_lines = sum(bool(re.fullmatch(r"[\s_+\-=]+", line)) for line in block.lines)
    return pipe_lines >= 2 and (rule_lines >= 1 or len(block.lines) >= 3)


def _is_heading(block: Block) -> bool:
    if _is_table(block) or len(block.text) > 260:
        return False
    letters = [character for character in block.text if character.isalpha()]
    return bool(letters) and all(not character.islower() for character in letters)


def _source_id(block: Block) -> str:
    return f"ms-src-L{block.start_line:05d}"


def _note_targets(blocks: Iterable[Block], chapter: str) -> dict[tuple[int, int, int], str]:
    ordered = tuple(blocks)
    bodies: dict[str, list[tuple[int, str]]] = defaultdict(list)
    body_ordinal: dict[str, int] = defaultdict(int)
    for block in ordered:
        match = FOOTNOTE_BODY_RE.match(block.text)
        if match:
            number = match.group(1)
            body_ordinal[number] += 1
            bodies[number].append(
                (
                    block.start_line,
                    f"ms-chapter-{chapter}-note-{number}-{body_ordinal[number]}",
                )
            )
    targets: dict[tuple[int, int, int], str] = {}
    used_targets: set[str] = set()
    for block in ordered:
        if FOOTNOTE_BODY_RE.match(block.text):
            continue
        for line_offset, line in enumerate(block.lines):
            for match in FOOTNOTE_REF_RE.finditer(line):
                number = match.group(1)
                raw_line = block.start_line + line_offset
                following = next(
                    (target for body_line, target in bodies[number] if body_line > raw_line),
                    None,
                )
                if following is None:
                    raise ConversionError(
                        f"No following footnote body for [{number}] at source line {raw_line}"
                    )
                targets[(raw_line, match.start(), int(number))] = following
                used_targets.add(following)
    leftovers = {
        number: [target for _line, target in members if target not in used_targets]
        for number, members in bodies.items()
        if any(target not in used_targets for _line, target in members)
    }
    if leftovers:
        raise ConversionError(f"Footnote bodies without references in chapter {chapter}: {leftovers!r}")
    return targets


def _append_inline(
    carrier: etree._Element,
    line: str,
    raw_line: int,
    targets: dict[tuple[int, int, int], str],
) -> int:
    emphasis_count = 0
    cursor = 0
    token_re = re.compile(r"_([^_\n]+)_|\[(\d+)\]")
    for match in token_re.finditer(line):
        literal = line[cursor : match.start()]
        if len(carrier):
            carrier[-1].tail = (carrier[-1].tail or "") + literal
        else:
            carrier.text = (carrier.text or "") + literal
        if match.group(1) is not None:
            node = tei_el("hi", {"rend": "italic"}, match.group(1))
            emphasis_count += 1
        else:
            number = int(match.group(2))
            target = targets.get((raw_line, match.start(), number))
            if target is None:
                node = tei_el("seg", {"type": "literal-note-marker"}, match.group(0))
            else:
                node = tei_el("ref", {"type": "note", "target": f"#{target}"}, match.group(0))
        carrier.append(node)
        cursor = match.end()
    remainder = line[cursor:]
    if len(carrier):
        carrier[-1].tail = (carrier[-1].tail or "") + remainder
    else:
        carrier.text = (carrier.text or "") + remainder
    return emphasis_count


def _append_lines(
    parent: etree._Element,
    block: Block,
    targets: dict[tuple[int, int, int], str] | None = None,
    *,
    carrier_type: str = "source-line",
) -> int:
    targets = targets or {}
    emphasis_count = 0
    for offset, line in enumerate(block.lines):
        if offset:
            parent.append(tei_el("lb", {"n": str(block.start_line + offset)}))
        carrier = tei_el(
            "seg",
            {"type": carrier_type, "n": str(block.start_line + offset)},
        )
        emphasis_count += _append_inline(carrier, line, block.start_line + offset, targets)
        parent.append(carrier)
    return emphasis_count


def _new_block_element(
    block: Block,
    targets: dict[tuple[int, int, int], str],
    *,
    chapter: str,
) -> tuple[etree._Element, int, bool]:
    note_match = FOOTNOTE_BODY_RE.match(block.text)
    if note_match:
        number = note_match.group(1)
        # The stable source-line suffix distinguishes reset/duplicate note numbers.
        note_id = f"ms-chapter-{chapter}-note-{number}-{block.start_line}"
        element = tei_el(
            "note",
            {
                "place": "end",
                "n": number,
                "xml:id": note_id,
            },
        )
        # Rewrite to the ordinal target assigned by _note_targets.
        ordinal_targets = sorted(
            {
                value
                for (line, _offset, candidate), value in targets.items()
                if candidate == int(number) and line < block.start_line
            }
        )
        if ordinal_targets:
            note_id = ordinal_targets[-1]
            element.set(XML_ID, note_id)
        emphasis = _append_lines(element, block, targets)
        return element, emphasis, False
    if _is_table(block):
        element = tei_el(
            "ab",
            {
                "type": "table-transcription",
                "rend": "fixed-width project-gutenberg-orientation",
                "style": (
                    "display: block; margin: 0.75rem 0; white-space: pre-wrap; "
                    "font-family: ui-monospace, monospace"
                ),
                "xml:id": _source_id(block),
                "n": f"{block.start_line}-{block.end_line}",
            },
        )
        emphasis = _append_lines(element, block, targets)
        return element, emphasis, True
    element = tei_el(
        "p",
        {
            "xml:id": _source_id(block),
            "n": f"{block.start_line}-{block.end_line}",
            "style": BLOCK_STYLE,
        },
    )
    emphasis = _append_lines(element, block, targets)
    return element, emphasis, False


def _append_heading(parent: etree._Element, block: Block, head_type: str) -> int:
    head = tei_el(
        "head",
        {
            "type": head_type,
            "xml:id": _source_id(block),
            "n": f"{block.start_line}-{block.end_line}",
        },
    )
    emphasis = _append_lines(head, block)
    parent.append(head)
    return emphasis


def _append_chapter(
    parent: etree._Element,
    blocks: tuple[Block, ...],
    roman: str,
    *,
    contents: bool,
) -> tuple[int, int]:
    div = tei_el(
        "div",
        {
            "type": "contents-entry" if contents else "chapter",
            "n": roman,
            "xml:id": f"ms-{'contents' if contents else 'chapter'}-{roman}",
        },
    )
    parent.append(div)
    emphasis = _append_heading(div, blocks[0], "chapter-label")
    table_count = 0
    targets = {} if contents else _note_targets(blocks[1:], roman)
    content_started = False
    for position, block in enumerate(blocks[1:], start=1):
        if _is_heading(block) and not content_started:
            emphasis += _append_heading(div, block, "title" if position == 1 else "section")
            continue
        element, count, is_table = _new_block_element(block, targets, chapter=roman)
        if _is_heading(block):
            element.set("rend", "section-heading")
        div.append(element)
        content_started = True
        emphasis += count
        table_count += int(is_table)
    return emphasis, table_count


def _header(source_sha256: str) -> etree._Element:
    header = stamp_header(
        title="Missionary Survey as an Aid to Intelligent Co-operation in Foreign Missions",
        author="Roland Allen",
        contributors=[
            {
                "name": "Thomas Cochrane",
                "role": "joint study contributor, named collaborator, and preface signer",
            },
            {
                "name": "Ted Garvin, Josephine Paolucci, and the Online Distributed Proofreading Team",
                "role": "Project Gutenberg production and proofreading",
            },
        ],
        source_url=SOURCE_URL,
        source_sha256=source_sha256,
        print_source=(
            "Longmans, Green and Co., 1920. Project Gutenberg states that some tables "
            "were transposed for line length. The surfaced orientation is retained pending "
            "an exact print-page comparison."
        ),
        rights_statement=(
            "Project Gutenberg states that this work is public domain in the USA. Rights "
            "outside the USA and Project Gutenberg trademark or redistribution conditions "
            "require separate review. This nonaccepted candidate is not publication clearance."
        ),
    )
    encoding = tei_el("encodingDesc")
    project = tei_el("projectDesc")
    project.append(
        tei_el(
            "p",
            text=(
                "Source-defined Project Gutenberg blocks and line breaks are retained. Paired "
                "underscore emphasis markers become hi elements; the underscores are markup, "
                "not content. Blank separator lines delimit blocks and are counted in the "
                "accounting report. Gutenberg wrapper and license text remain in retained raw "
                "source but are not represented as edition text."
            ),
        )
    )
    encoding.append(project)
    header.append(encoding)
    profile = tei_el("profileDesc")
    language_usage = tei_el("langUsage")
    language_usage.append(tei_el("language", {"ident": "en"}, "English"))
    profile.append(language_usage)
    header.append(profile)
    return header


def build_tree(parsed: ParsedSource) -> tuple[etree._ElementTree, dict[str, object]]:
    blocks = parsed.blocks
    preface_index = next(i for i, block in enumerate(blocks) if block.text == "PREFACE.")
    contents_index = next(i for i, block in enumerate(blocks) if block.text == "ANALYSIS OF CONTENTS.")
    body_start = parsed.chapter_block_indexes[11]
    title_index = next(
        i
        for i, block in enumerate(blocks[:preface_index])
        if block.text.startswith("MISSIONARY SURVEY AS AN AID")
    )

    root = tei_el("TEI", {"xml:lang": "en"})
    root.append(_header(_sha256(parsed.path)))
    text = tei_el("text")
    root.append(text)
    front = tei_el("front")
    body = tei_el("body")
    back = tei_el("back")
    text.extend((front, body, back))

    emphasis_count = 0
    transcriber = tei_el("div", {"type": "transcriber-note", "xml:id": "ms-transcriber-note"})
    transcriber_note = tei_el(
        "p",
        {"rend": "transcriber-note", "style": BLOCK_STYLE},
    )
    emphasis_count += _append_lines(transcriber_note, blocks[0])
    transcriber.append(transcriber_note)
    front.append(transcriber)

    title_page = tei_el("titlePage", {"xml:id": "ms-title-page"})
    for block in blocks[title_index:preface_index]:
        if block is blocks[title_index]:
            doc_title = tei_el("docTitle", {"style": BLOCK_STYLE})
            title_part = tei_el("titlePart", {"type": "main", "style": BLOCK_STYLE})
            emphasis_count += _append_lines(title_part, block)
            doc_title.append(title_part)
            title_page.append(doc_title)
        elif block.text in {"BY", "AND"}:
            byline = tei_el("byline", {"style": BLOCK_STYLE})
            emphasis_count += _append_lines(byline, block)
            title_page.append(byline)
        elif block.text == "1920":
            date = tei_el("docDate", {"when": "1920", "style": BLOCK_STYLE})
            emphasis_count += _append_lines(date, block)
            title_page.append(date)
        else:
            author = tei_el("docAuthor", {"style": BLOCK_STYLE})
            emphasis_count += _append_lines(author, block)
            title_page.append(author)
    front.append(title_page)

    preface = tei_el("div", {"type": "preface", "xml:id": "ms-preface"})
    emphasis_count += _append_heading(preface, blocks[preface_index], "main")
    for block in blocks[preface_index + 1 : contents_index]:
        if block.text == "THOS. COCHRANE.":
            signed = tei_el(
                "signed",
                {"xml:id": _source_id(block), "style": BLOCK_STYLE},
            )
            emphasis_count += _append_lines(signed, block)
            preface.append(signed)
        else:
            element, count, _ = _new_block_element(block, {}, chapter="preface")
            preface.append(element)
            emphasis_count += count
    front.append(preface)

    contents = tei_el("div", {"type": "contents", "xml:id": "ms-contents"})
    emphasis_count += _append_heading(contents, blocks[contents_index], "main")
    contents_chapters = parsed.chapter_block_indexes[:11]
    for ordinal, (roman, start) in enumerate(zip(ROMANS, contents_chapters, strict=True)):
        stop = contents_chapters[ordinal + 1] if ordinal + 1 < 11 else body_start
        count, _tables = _append_chapter(contents, blocks[start:stop], roman, contents=True)
        emphasis_count += count
    front.append(contents)

    table_count = 0
    body_chapters = parsed.chapter_block_indexes[11:]
    for ordinal, (roman, start) in enumerate(zip(ROMANS, body_chapters, strict=True)):
        stop = body_chapters[ordinal + 1] if ordinal + 1 < 11 else len(blocks)
        count, tables = _append_chapter(body, blocks[start:stop], roman, contents=False)
        emphasis_count += count
        table_count += tables

    marker_block = Block(parsed.end_index + 1, parsed.end_index + 1, (parsed.raw_lines[parsed.end_index],))
    wrapper = tei_el("div", {"type": "source-wrapper", "xml:id": "ms-pg-end-wrapper"})
    marker = tei_el(
        "p",
        {"rend": "project-gutenberg-end-marker", "style": BLOCK_STYLE},
    )
    _append_lines(marker, marker_block, carrier_type="wrapper-line")
    wrapper.append(marker)
    back.append(wrapper)

    stats: dict[str, object] = {
        "chapter_count": 11,
        "table_count": table_count,
        "emphasis_count": emphasis_count,
    }
    return etree.ElementTree(root), stats


def _carrier_map(tree: etree._ElementTree) -> list[tuple[int, str]]:
    carriers = tree.xpath("//tei:seg[@type='source-line']", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
    return [(int(carrier.get("n")), "".join(carrier.itertext())) for carrier in carriers]


def accounting_errors(parsed: ParsedSource, tree: etree._ElementTree) -> list[str]:
    expected = [
        (parsed.start_index + 2 + offset, _normalized_line(line))
        for offset, line in enumerate(parsed.selected_lines)
        if line.strip()
    ]
    actual = _carrier_map(tree)
    if expected == actual:
        return []
    errors: list[str] = []
    if len(expected) != len(actual):
        errors.append(f"source-line carrier count: expected {len(expected)}, found {len(actual)}")
    for index, (left, right) in enumerate(zip(expected, actual)):
        if left != right:
            errors.append(f"first source-line mismatch at ordinal {index}: expected {left!r}, found {right!r}")
            break
    return errors


def _source_members(raw_dir: Path) -> list[dict[str, object]]:
    roles = {
        "pg13360.txt": ("text-authority", SOURCE_URL),
        "pg13360-images.html": ("html-structural-crosscheck", HTML_URL),
        "pg13360.rdf": ("project-gutenberg-metadata", "https://www.gutenberg.org/ebooks/13360.rdf"),
        "gutenberg-landing.html": ("landing-page", LANDING_URL),
        "MN41419ucmf_1.pdf": ("rejected-print-witness", "https://archive.org/download/MN41419ucmf_1/MN41419ucmf_1.pdf"),
        "MN41419ucmf_1_djvu.xml": ("rejected-print-witness-ocr", "https://archive.org/download/MN41419ucmf_1/MN41419ucmf_1_djvu.xml"),
        "ia-mn41419-metadata.json": ("rejected-print-witness-metadata", "https://archive.org/metadata/MN41419ucmf_1"),
    }
    result: list[dict[str, object]] = []
    for path in sorted(raw_dir.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        role, url = roles.get(path.name, ("http-evidence" if "headers" in path.name else "acquisition-evidence", None))
        result.append(
            {
                "bytes": path.stat().st_size,
                "name": path.name,
                "role": role,
                "sha256": _sha256(path),
                "url": url,
            }
        )
    return result


def _receipt(raw_dir: Path) -> dict[str, object]:
    retrieved = (raw_dir / "retrieved-at-utc.txt").read_text(encoding="utf-8").strip()
    return {
        "archive_members": [],
        "completeness_checks": {
            "ending": "Chapter XI ends with 'that is the crying need,' followed by the retained Gutenberg end marker.",
            "middle": "All eleven body chapters and their fixed-width statistical/form blocks are present.",
            "opening": "Transcriber note, title surface, 1920 date, Cochrane-signed preface, and analytical contents are present.",
            "unusual_features": "Tables are surfaced in Gutenberg's stated possibly-transposed orientation; source line layout is retained.",
        },
        "credits": "Produced by Ted Garvin, Josephine Paolucci and the Online Distributed Proofreading Team.",
        "download_urls": [SOURCE_URL, HTML_URL, "https://www.gutenberg.org/ebooks/13360.rdf"],
        "edition": "Longmans, Green and Co., 1920",
        "identity": "provisional net-new candidate; no canonical WorkCatalog write",
        "landing_url": LANDING_URL,
        "omissions_from_tei": [
            "Project Gutenberg pre-start metadata and post-end license boilerplate remain in retained source evidence.",
            "Print pagination and full publisher/imprint matter are absent from the Gutenberg transcription.",
        ],
        "print_witness_rejection": {
            "identifier": "MN41419ucmf_1",
            "reason": "Archive metadata names this work, but the retained 265-page PDF opens with and contains unrelated German missionary material; it is not used as textual or layout authority.",
            "sha256": _sha256(raw_dir / "MN41419ucmf_1.pdf"),
        },
        "redirects": {
            "rdf": "https://www.gutenberg.org/ebooks/13360.rdf redirected through HTTP then HTTPS to https://www.gutenberg.org/cache/epub/13360/pg13360.rdf",
            "internet_archive_pdf": "Archive download redirected to a ca.archive.org object host.",
        },
        "retrieved_at_utc": retrieved,
        "rights_and_attribution": {
            "attribution": "Retain Project Gutenberg identifier, landing/download URLs, and production credits.",
            "status": "Project Gutenberg states public domain in the USA.",
            "unresolved": "Rights outside the USA and Project Gutenberg trademark/redistribution terms require separate review before publication.",
        },
        "source_members": _source_members(raw_dir),
        "source_title": "Missionary Survey as an Aid to Intelligent Co-operation in Foreign Missions",
        "source_responsibility": {
            "named_collaborator": "Thomas Cochrane; joint study and selection, preface signer, disclaims writing credit",
            "writer": "Roland Allen",
        },
        "transformations": [
            "Decoded the retained UTF-8 text without correction or OCR.",
            "Selected content strictly between the single Gutenberg start and end markers.",
            "Converted paired underscore emphasis markers to TEI hi elements.",
            "Retained source line wrapping as lb elements and fixed-width tables as table-transcription ab elements.",
            "Retained note marker text and linked it to source-order footnote bodies.",
        ],
        "unresolved_questions": [
            "Which exact print tables Project Gutenberg transposed, and their original axes, remain unresolved because no verified matching print scan was available.",
            "Human identity, edition, rights, textual, and editorial acceptance remain outside this candidate packet.",
        ],
    }


def convert(source_path: Path, output_path: Path, report_dir: Path) -> ConversionResult:
    parsed = parse_source(source_path)
    tree, stats = build_tree(parsed)
    errors = accounting_errors(parsed, tree)
    if errors:
        raise ConversionError("; ".join(errors))
    serialize(tree, output_path)
    xsd_errors = validate_file(output_path)
    if xsd_errors:
        raise ConversionError("TEI P5 XSD validation failed: " + "; ".join(xsd_errors[:5]))

    nonblank = [line for line in parsed.selected_lines if line.strip()]
    carriers = _carrier_map(tree)
    table_ids = tree.xpath(
        "//tei:ab[@type='table-transcription']/@xml:id",
        namespaces={"tei": "http://www.tei-c.org/ns/1.0", "xml": XML_NS},
    )
    refs = tree.xpath("//tei:ref[@type='note']", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
    notes = tree.xpath("//tei:note[@place='end']", namespaces={"tei": "http://www.tei-c.org/ns/1.0"})
    accounting = {
        "blank_selected_lines": sum(not line.strip() for line in parsed.selected_lines),
        "block_count": len(parsed.blocks),
        "carrier_stream_sha256": _line_digest(text for _line, text in carriers),
        "chapter_count": stats["chapter_count"],
        "duplicated_selected_nonblank_lines": [],
        "emphasis_count": stats["emphasis_count"],
        "footnote_body_count": len(notes),
        "footnote_reference_count": len(refs),
        "normalized_source_stream_sha256": _line_digest(_normalized_line(line) for line in nonblank),
        "omitted_selected_nonblank_lines": [],
        "raw_line_count": len(parsed.raw_lines),
        "selected_line_count": len(parsed.selected_lines),
        "selected_nonblank_line_count": len(nonblank),
        "source_line_carrier_count": len(carriers),
        "source_sha256": _sha256(source_path),
        "table_count": stats["table_count"],
        "table_orientation": "Project Gutenberg surfaced orientation retained; transcriber note explicitly preserved.",
        "table_source_ids": table_ids,
        "wrapper_lines_after_end_marker": len(parsed.raw_lines) - parsed.end_index - 1,
        "wrapper_lines_before_start_marker": parsed.start_index,
    }
    if accounting["normalized_source_stream_sha256"] != accounting["carrier_stream_sha256"]:
        raise ConversionError("Normalized source and TEI carrier digests differ")

    receipt_path = report_dir / "receipt.json"
    accounting_path = report_dir / "accounting.json"
    validation_path = report_dir / "validation.json"
    _write_json(receipt_path, _receipt(source_path.parent))
    _write_json(accounting_path, accounting)
    _write_json(
        validation_path,
        {
            "accounting_errors": [],
            "candidate_sha256": _sha256(output_path),
            "status": "technically_valid_nonaccepted_candidate",
            "tei_p5_xsd_errors": [],
            "tei_p5_xsd_valid": True,
        },
    )
    return ConversionResult(
        output_path,
        receipt_path,
        accounting_path,
        validation_path,
        int(stats["table_count"]),
        int(stats["chapter_count"]),
        len(carriers),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    result = convert(args.source, args.output, args.report_dir)
    print(
        json.dumps(
            {
                "accounting": str(result.accounting_path),
                "chapters": result.chapter_count,
                "output": str(result.output_path),
                "receipt": str(result.receipt_path),
                "source_line_carriers": result.source_line_carrier_count,
                "tables": result.table_count,
                "validation": str(result.validation_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
