"""Convert a bounded Project Gutenberg marked-up work into TEI."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from ocd_kernel.tei.writer import TEI_NS, serialize, stamp_header, tei_el

PG_START_RE = re.compile(r"\*{3}\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*{3}\s*END OF", re.IGNORECASE)
BOOK_RE = re.compile(r"^BOOK\s+([IVX]+)\.?\s*(.*)?$")
CHAPTER_V1_RE = re.compile(r"^Chapter\s+([IVX]+)\.\s*(.*)$")
CHAPTER_V2_RE = re.compile(r"^CHAPTER\s+([IVX]+)\.?$")
INLINE_RE = re.compile(
    r"(?<!\w)_(?!_)([^_\n]{1,500})_(?!\w)|"
    r"(?<!\w)\[(\d{1,4})\](?!\w)|"
    r"\((\d{1,4})\)"
)
NOTE_START_RE = re.compile(r"^\s{1,4}(\d{1,4})\s+(.+)$")
NOTE_LABEL_RE = re.compile(r"^\s*Footnote\s+(\d{1,4}):\s*$", re.IGNORECASE)
INDEX_RE = re.compile(r"^\s*INDEX OF THE PRINCIPAL MATTERS\.\s*$", re.IGNORECASE)


class ConversionError(ValueError):
    """Raised when the selected Gutenberg source cannot be represented safely."""


@dataclass(frozen=True)
class ConversionResult:
    output_path: Path
    paragraph_count: int
    emphasis_count: int
    anchor_count: int
    note_body_count: int


@dataclass(frozen=True)
class _Event:
    kind: str
    roman: str
    title: str
    line: int
    content_start: int


@dataclass(frozen=True)
class _Source:
    path: Path
    slug: str
    lines: tuple[str, ...]
    main_start: int
    main_stop: int
    first_book: int
    events: tuple[_Event, ...]


@dataclass
class _InlineState:
    ref_number: int = 0
    parenthetical_next_by_source: dict[str, int] = field(default_factory=dict)
    parenthetical_note_numbers_by_source: dict[str, frozenset[int]] = field(default_factory=dict)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slug(path: Path) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", path.stem).strip("-")
    return value if value and not value[0].isdigit() else f"pg-{value}"


def _strip_pg_wrapper(text: str) -> tuple[str, ...]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if PG_START_RE.search(line)), None)
    end = next((i for i, line in enumerate(lines) if PG_END_RE.search(line)), None)
    if start is None or end is None or end <= start:
        raise ConversionError("Could not find Project Gutenberg start/end markers")
    return tuple(lines[start + 1 : end])


def _normalise_paragraph(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip()).strip()


def _paragraphs(
    lines: tuple[str, ...],
    start: int,
    stop: int,
    *,
    skip_ranges: tuple[tuple[int, int], ...] = (),
) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    current: list[str] = []
    first_line = start
    for index in range(start, min(stop, len(lines))):
        if any(range_start <= index < range_stop for range_start, range_stop in skip_ranges):
            text = _normalise_paragraph(current)
            if text:
                result.append((first_line, text))
            current = []
            first_line = index + 1
            continue
        line = lines[index].rstrip()
        if not line.strip():
            text = _normalise_paragraph(current)
            if text:
                result.append((first_line, text))
            current = []
            first_line = index + 1
            continue
        if not current:
            first_line = index
        current.append(line)
    text = _normalise_paragraph(current)
    if text:
        result.append((first_line, text))
    return result


def _heading_events(lines: tuple[str, ...], volume: int, start: int, stop: int) -> tuple[_Event, ...]:
    events: list[_Event] = []
    index = start
    while index < min(stop, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        book_match = BOOK_RE.match(stripped) if stripped.upper() == stripped else None
        if book_match:
            events.append(_Event("book", book_match.group(1), (book_match.group(2) or "").strip().rstrip("."), index, index + 1))
            index += 1
            continue
        if volume == 1:
            indent = len(lines[index]) - len(lines[index].lstrip())
            chapter_match = CHAPTER_V1_RE.match(stripped) if indent < 3 else None
            if chapter_match:
                events.append(_Event("chapter", chapter_match.group(1), chapter_match.group(2).strip(), index, index + 1))
        else:
            chapter_match = CHAPTER_V2_RE.match(stripped)
            if chapter_match:
                title = ""
                title_line = index + 1
                while title_line < min(stop, len(lines)) and not lines[title_line].strip():
                    title_line += 1
                if title_line < min(stop, len(lines)):
                    candidate = lines[title_line].strip()
                    if (
                        candidate
                        and candidate.upper() == candidate
                        and not candidate.startswith("BOOK ")
                        and not candidate.startswith("CHAPTER ")
                        and len(candidate) < 250
                    ):
                        title = candidate.rstrip(".")
                        events.append(_Event("chapter", chapter_match.group(1), title, index, title_line + 1))
                        index = title_line
                        index += 1
                        continue
                events.append(_Event("chapter", chapter_match.group(1), title, index, index + 1))
        index += 1
    return tuple(events)


def _load_source(path: Path, volume: int) -> _Source:
    lines = _strip_pg_wrapper(path.read_text(encoding="utf-8"))
    first_book = next(
        (
            i
            for i, line in enumerate(lines)
            if line.strip().upper() == line.strip() and BOOK_RE.match(line.strip())
        ),
        None,
    )
    if first_book is None:
        raise ConversionError(f"No book heading found in {path.as_posix()}")
    if volume == 1:
        footnotes = next(
            (i for i in range(first_book, len(lines)) if lines[i].strip().upper() == "FOOTNOTES"),
            len(lines),
        )
        main_stop = footnotes
    else:
        main_stop = next(
            (i for i in range(first_book, len(lines)) if lines[i].strip().upper() == "END OF THE INSTITUTES."),
            len(lines),
        )
    events = _heading_events(lines, volume, first_book, main_stop)
    return _Source(path, _slug(path), lines, first_book, main_stop, first_book, events)


def _append_text(parent: etree._Element, text: str) -> None:
    if not text:
        return
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _paired_parenthetical_anchor_count(
    texts: list[str], note_numbers: frozenset[int]
) -> int:
    expected = 1
    count = 0
    for text in texts:
        for match in re.finditer(r"\((\d{1,4})\)", text):
            number = int(match.group(1))
            if number == expected and number in note_numbers:
                count += 1
                expected += 1
    return count


def _append_inline(
    parent: etree._Element,
    text: str,
    source_slug: str,
    line: int,
    state: _InlineState,
    *,
    allow_emphasis: bool = True,
    parenthetical_note_numbers: frozenset[int] | None = None,
) -> None:
    cursor = 0
    pattern = INLINE_RE if allow_emphasis else re.compile(r"(?<!\w)\[(\d{1,4})\](?!\w)")
    for match in pattern.finditer(text):
        _append_text(parent, text[cursor : match.start()])
        emphasis = match.group(1) if allow_emphasis else None
        anchor = match.group(2) if allow_emphasis else match.group(1)
        parenthetical_anchor = match.group(3) if allow_emphasis else None
        if emphasis is not None:
            hi = tei_el("hi", {"rend": "italic"})
            _append_inline(
                hi,
                emphasis,
                source_slug,
                line,
                state,
                allow_emphasis=False,
                parenthetical_note_numbers=parenthetical_note_numbers,
            )
            parent.append(hi)
        elif parenthetical_anchor is not None:
            if parenthetical_note_numbers is None:
                _append_text(parent, match.group(0))
            else:
                number = int(parenthetical_anchor)
                expected = state.parenthetical_next_by_source.setdefault(source_slug, 1)
                if number == expected and number in parenthetical_note_numbers:
                    state.parenthetical_next_by_source[source_slug] = expected + 1
                    state.ref_number += 1
                    ref_id = f"{source_slug}-ref-{line + 1}-{state.ref_number}"
                    target = f"#{source_slug}-note-{number}"
                    parent.append(
                        tei_el(
                            "ref",
                            {"type": "note", "target": target, "xml:id": ref_id},
                            f"({number})",
                        )
                    )
                else:
                    _append_text(parent, match.group(0))
        elif anchor is not None:
            state.ref_number += 1
            ref_id = f"{source_slug}-ref-{line + 1}-{state.ref_number}"
            target = f"#{source_slug}-note-{anchor}"
            parent.append(tei_el("ref", {"type": "note", "target": target, "xml:id": ref_id}, f"[{anchor}]"))
        else:
            _append_text(parent, match.group(0))
        cursor = match.end()
    _append_text(parent, text[cursor:])


def _paragraph_node(
    source: _Source,
    line: int,
    text: str,
    state: _InlineState,
    *,
    parenthetical_anchors: bool = False,
) -> etree._Element:
    paragraph = tei_el("p", {"xml:id": f"{source.slug}-p-{line + 1}"})
    _append_inline(
        paragraph,
        text,
        source.slug,
        line,
        state,
        parenthetical_note_numbers=(
            state.parenthetical_note_numbers_by_source.get(source.slug)
            if parenthetical_anchors
            else None
        ),
    )
    return paragraph


def _source_groups(source: _Source) -> list[tuple[_Event, list[_Event]]]:
    groups: list[tuple[_Event, list[_Event]]] = []
    current: _Event | None = None
    chapters: list[_Event] = []
    for event in source.events:
        if event.kind == "book":
            if current is not None:
                groups.append((current, chapters))
            current = event
            chapters = []
        elif current is not None:
            chapters.append(event)
    if current is not None:
        groups.append((current, chapters))
    return groups


def _footnote_limit(source: _Source) -> int:
    return next(
        (
            index
            for index in range(source.first_book, len(source.lines))
            if INDEX_RE.match(source.lines[index])
        ),
        len(source.lines),
    )


def _is_vol1_source(source: _Source) -> bool:
    return source.main_stop < len(source.lines) and source.lines[source.main_stop].strip().upper() == "FOOTNOTES"


def _footnote_starts(source: _Source) -> list[tuple[int, int, str]]:
    limit = _footnote_limit(source)
    starts: list[tuple[int, int, str]] = []
    if source.main_stop < len(source.lines) and source.lines[source.main_stop].strip().upper() == "FOOTNOTES":
        candidate_lines = range(source.main_stop + 1, limit)
        for index in candidate_lines:
            match = NOTE_START_RE.match(source.lines[index])
            if match and len(source.lines[index]) - len(source.lines[index].lstrip()) <= 4:
                starts.append((index, int(match.group(1)), match.group(2)))
    else:
        for index in range(source.first_book, limit):
            match = NOTE_LABEL_RE.match(source.lines[index])
            if match:
                starts.append((index, int(match.group(1)), ""))
    return starts


def _vol2_note_end(source: _Source, start: int, limit: int) -> tuple[int, list[str]]:
    body_lines: list[str] = []
    index = start + 1
    while index < limit:
        line = source.lines[index]
        if not line.strip():
            index += 1
            continue
        indent = len(line) - len(line.lstrip())
        if 0 < indent <= 4:
            body_lines.append(line.strip())
            index += 1
            continue
        break
    return index, body_lines


def _footnote_ranges(source: _Source) -> tuple[tuple[int, int], ...]:
    starts = _footnote_starts(source)
    limit = _footnote_limit(source)
    if source.main_stop >= len(source.lines) or source.lines[source.main_stop].strip().upper() != "FOOTNOTES":
        return tuple(
            (line, _vol2_note_end(source, line, limit)[0])
            for line, _number, _first_text in starts
        )
    return tuple(
        (line, starts[position + 1][0] if position + 1 < len(starts) else limit)
        for position, (line, _number, _first_text) in enumerate(starts)
    )


def _footnotes(source: _Source) -> list[tuple[int, int, str]]:
    starts = _footnote_starts(source)
    limit = _footnote_limit(source)
    if source.main_stop >= len(source.lines) or source.lines[source.main_stop].strip().upper() != "FOOTNOTES":
        result: list[tuple[int, int, str]] = []
        for line, number, _first_text in starts:
            _stop, body_lines = _vol2_note_end(source, line, limit)
            result.append((line, number, _normalise_paragraph(body_lines)))
        return result
    result: list[tuple[int, int, str]] = []
    for position, (line, number, first_text) in enumerate(starts):
        stop = starts[position + 1][0] if position + 1 < len(starts) else limit
        body_lines = [first_text] if first_text else []
        body_lines.extend(source.lines[i].strip() for i in range(line + 1, stop))
        body = _normalise_paragraph(body_lines)
        result.append((line, number, body))
    return result


def _front_div(source: _Source, state: _InlineState) -> etree._Element:
    front = tei_el("div", {"type": "titlepage", "xml:id": f"{source.slug}-front"})
    front.append(tei_el("head", text=f"{source.slug} front matter"))
    for line, text in _paragraphs(source.lines, 0, source.first_book):
        front.append(
            _paragraph_node(
                source,
                line,
                text,
                state,
                parenthetical_anchors=_is_vol1_source(source),
            )
        )
    return front


def _build_body(sources: tuple[_Source, ...], state: _InlineState) -> etree._Element:
    body = tei_el("body")
    groups_by_book: dict[str, list[tuple[_Source, _Event, list[_Event]]]] = {}
    for source in sources:
        for book, chapters in _source_groups(source):
            groups_by_book.setdefault(book.roman, []).append((source, book, chapters))

    for roman in ("I", "II", "III", "IV"):
        groups = groups_by_book.get(roman, [])
        if not groups:
            continue
        first_source, first_book, _ = groups[0]
        book = tei_el("div", {"type": "book", "xml:id": f"{first_source.slug}-book-{roman}", "n": roman})
        book.append(tei_el("head", {"xml:id": f"{first_source.slug}-book-head-{roman}"}, f"Book {roman}. {first_book.title}".rstrip(". ")))
        for source, _book, chapters in groups:
            skip_ranges = _footnote_ranges(source)
            for position, chapter in enumerate(chapters):
                stop = chapters[position + 1].line if position + 1 < len(chapters) else (
                    next((event.line for event in source.events if event.kind == "book" and event.line > _book.line), source.main_stop)
                )
                chapter_div = tei_el(
                    "div",
                    {
                        "type": "chapter",
                        "xml:id": f"{source.slug}-chapter-{roman}-{chapter.roman}",
                        "n": chapter.roman,
                    },
                )
                chapter_div.append(
                    tei_el(
                        "head",
                        {"xml:id": f"{source.slug}-chapter-head-{roman}-{chapter.roman}"},
                        f"Chapter {chapter.roman}. {chapter.title}".rstrip(". "),
                    )
                )
                for line, text in _paragraphs(
                    source.lines,
                    chapter.content_start,
                    stop,
                    skip_ranges=skip_ranges,
                ):
                    chapter_div.append(
                        _paragraph_node(
                            source,
                            line,
                            text,
                            state,
                            parenthetical_anchors=_is_vol1_source(source),
                        )
                    )
                book.append(chapter_div)
        body.append(book)
    return body


def _build_back(sources: tuple[_Source, ...], state: _InlineState) -> etree._Element | None:
    note_sources = [(source, _footnotes(source)) for source in sources]
    if not any(notes for _source, notes in note_sources):
        return None
    back = tei_el("back")
    for source, notes in note_sources:
        if not notes:
            continue
        container = tei_el("div", {"type": "notes", "xml:id": f"{source.slug}-footnotes"})
        container.append(tei_el("head", text=f"{source.slug} footnotes"))
        for line, number, text in notes:
            note = tei_el(
                "note",
                {"place": "end", "n": str(number), "xml:id": f"{source.slug}-note-{number}"},
            )
            note.append(_paragraph_node(source, line, text, state))
            container.append(note)
        back.append(container)
    return back


def convert_calvin_to_tei(vol1_path: str | Path, vol2_path: str | Path, output_path: str | Path) -> ConversionResult:
    sources = (
        _load_source(Path(vol1_path), 1),
        _load_source(Path(vol2_path), 2),
    )
    for source in sources:
        front_paragraphs = [
            text for _line, text in _paragraphs(source.lines, 0, source.first_book)
        ]
        body_paragraphs = [
            text
            for book, chapter_events in _source_groups(source)
            for position, chapter in enumerate(chapter_events)
            for _line, text in _paragraphs(
                source.lines,
                chapter.content_start,
                chapter_events[position + 1].line
                if position + 1 < len(chapter_events)
                else next(
                    (
                        event.line
                        for event in source.events
                        if event.kind == "book" and event.line > book.line
                    ),
                    source.main_stop,
                ),
                skip_ranges=_footnote_ranges(source),
            )
        ]
        anchor_texts = [*front_paragraphs, *body_paragraphs]
        if _is_vol1_source(source):
            note_numbers = frozenset(number for _line, number, _text in _footnotes(source))
            anchor_count = _paired_parenthetical_anchor_count(anchor_texts, note_numbers)
        else:
            anchor_count = sum(
                1
                for text in anchor_texts
                for match in INLINE_RE.finditer(text)
                if match.group(2)
            )
        if anchor_count and not _footnotes(source):
            raise ConversionError(
                f"{source.path.as_posix()} contains {anchor_count} numeric note anchors but no recoverable note bodies"
            )
    state = _InlineState(
        parenthetical_note_numbers_by_source={
            source.slug: frozenset(number for _line, number, _text in _footnotes(source))
            for source in sources
            if _is_vol1_source(source)
        }
    )
    combined_hash = "sha256:" + hashlib.sha256("".join(_sha256(source.path) for source in sources).encode()).hexdigest()
    header = stamp_header(
        title="Institutes of the Christian Religion",
        author="John Calvin",
        contributors=["John Allen"],
        source_url="https://www.gutenberg.org/ebooks/45001; https://www.gutenberg.org/ebooks/64392",
        source_sha256=combined_hash,
        print_source="John Allen translation, sixth American edition, Project Gutenberg volumes 1 and 2",
    )
    for response in header.iter(f"{{{TEI_NS}}}respStmt"):
        response.find("{%s}resp" % TEI_NS).text = "Translator"

    tei = etree.Element(f"{{{TEI_NS}}}TEI", nsmap={None: TEI_NS})
    tei.append(header)
    text = tei_el("text")
    front = tei_el("front")
    for source in sources:
        front.append(_front_div(source, state))
    text.append(front)
    text.append(_build_body(sources, state))
    back = _build_back(sources, state)
    if back is not None:
        text.append(back)
    tei.append(text)
    output = Path(output_path)
    serialize(etree.ElementTree(tei), output)
    return ConversionResult(
        output_path=output,
        paragraph_count=len(tei.xpath("//tei:p", namespaces={"tei": TEI_NS})),
        emphasis_count=len(tei.xpath("//tei:hi[@rend='italic']", namespaces={"tei": TEI_NS})),
        anchor_count=len(tei.xpath("//tei:ref[@type='note']", namespaces={"tei": TEI_NS})),
        note_body_count=len(tei.xpath("//tei:note[@place='end']", namespaces={"tei": TEI_NS})),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vol1", type=Path)
    parser.add_argument("vol2", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = convert_calvin_to_tei(args.vol1, args.vol2, args.output)
    print(
        f"Wrote {result.output_path.as_posix()} paragraphs={result.paragraph_count} "
        f"emphasis={result.emphasis_count} anchors={result.anchor_count} notes={result.note_body_count}"
    )


if __name__ == "__main__":
    main()
