"""gutenberg_theology.py
Parse Project Gutenberg theological texts into structured_text schema.

Sources (raw/gutenberg/):
  pg1722.txt  -- Luther's Large Catechism (Bente/Dau trans., 1921)
  pg45001.txt -- Calvin's Institutes Vol. 1 (John Allen trans., 6th American ed.)
  pg64392.txt -- Calvin's Institutes Vol. 2 (John Allen trans., 6th American ed.)
  pg3296.txt  -- Augustine's Confessions (E. B. Pusey trans.)

Outputs (data/structured-text/):
  luthers-large-catechism.json
  calvins-institutes.json          (Books I-IV from both volumes combined)
  augustines-confessions.json

Schema: structured_text (schemas/v1/structured_text.schema.json)

Notes on translations:
  - Calvin's Institutes (PG #45001, #64392): The PG files use the John Allen
    translation (6th American edition, Philadelphia: Presbyterian Board of
    Publication, 1813), NOT the Beveridge 1845 translation as originally
    anticipated. Both are public domain. Allen's is confirmed by the PG file text.
  - Luther's Large Catechism: Bente/Dau translation confirmed from Triglot
    Concordia (Concordia Publishing House, 1921) -- matches expected.
  - Augustine's Confessions: E. B. Pusey (Edward Bouverie Pusey) translation --
    confirmed from PG file text.

Usage:
    py -3 build/parsers/gutenberg_theology.py
    py -3 build/parsers/gutenberg_theology.py --dry-run
    py -3 build/parsers/gutenberg_theology.py --work luther_large
    py -3 build/parsers/gutenberg_theology.py --work calvin
    py -3 build/parsers/gutenberg_theology.py --work augustine
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

RAW_DIR = REPO_ROOT / "raw" / "gutenberg"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_theology.log"

SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_theology.py@v1.0.0"
DOWNLOAD_DATE = "2026-03-30"

# PG markers
PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII only) and append to log list."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def strip_pg_wrapper(text: str) -> list:
    """Strip PG header/footer. Returns body lines."""
    lines = text.splitlines()
    start_idx = end_idx = None
    for i, l in enumerate(lines):
        if PG_START_RE.search(l) and start_idx is None:
            start_idx = i
        if PG_END_RE.search(l):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError("Could not find PG start/end markers")
    return lines[start_idx + 1 : end_idx]


def gather_paragraphs(lines: list, start: int, stop: int) -> list:
    """Collect paragraphs (blank-line-separated blocks) from lines[start:stop].

    Each paragraph is a single string (lines joined with space).
    Short lines that are numbering markers (e.g., 'II. ') are absorbed into
    the following paragraph.
    """
    paragraphs = []
    current_block = []

    for i in range(start, min(stop, len(lines))):
        l = lines[i].rstrip()
        stripped = l.strip()

        if not stripped:
            # Blank line: flush current block
            if current_block:
                text = " ".join(current_block)
                text = " ".join(text.split())  # normalize whitespace
                if text:
                    paragraphs.append(text)
                current_block = []
        else:
            current_block.append(stripped)

    # Flush any remaining
    if current_block:
        text = " ".join(current_block)
        text = " ".join(text.split())
        if text:
            paragraphs.append(text)

    return paragraphs


def word_count(blocks: list) -> int:
    """Count words across all content blocks."""
    return sum(len(b.split()) for b in blocks)


def build_meta_envelope(
    work_id: str,
    title: str,
    author: str,
    birth: int,
    death: int,
    contributors: list,
    pub_year: int,
    tradition: list,
    tradition_notes: str,
    era: str,
    audience: str,
    original_lang: str,
    source_url: str,
    source_edition: str,
    source_hash: str,
    notes: str,
) -> dict:
    """Build the meta envelope for a structured_text output file."""
    return {
        "id": work_id,
        "title": title,
        "author": author,
        "author_birth_year": birth,
        "author_death_year": death,
        "contributors": contributors,
        "original_publication_year": pub_year,
        "language": "en",
        "original_language": original_lang,
        "tradition": tradition,
        "tradition_notes": tradition_notes,
        "era": era,
        "audience": audience,
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": source_url,
            "source_format": "plain text (UTF-8)",
            "source_edition": source_edition,
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": datetime.today().strftime("%Y-%m-%d"),
            "notes": notes,
        },
    }


# ---------------------------------------------------------------------------
# Luther's Large Catechism parser
# ---------------------------------------------------------------------------

# "Part First. The Ten Commandments." / "Part Second. OF THE CREED." / "Part Fourth."
_LLC_PART_RE = re.compile(
    r"^\s*Part\s+(First|Second|Third|Fourth|Fifth|Sixth)\.?\s*(.*)$",
    re.IGNORECASE,
)

# Sub-section headings within parts
# "The First Commandment." / "The Second Article." / "The First Petition." etc.
_LLC_SUBSECTION_RES = [
    re.compile(
        r"^\s*(The\s+(First|Second|Third|Fourth|Fifth|Sixth|Seventh|Eighth|Ninth|Tenth)\s+"
        r"(Commandment|Article|Petition|Sacrament)\.?)$",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(The\s+(Introduction|Conclusion|Close of the Commandments))$", re.IGNORECASE),
    re.compile(r"^\s*(The\s+Baptism)\.?$", re.IGNORECASE),
    re.compile(r"^\s*(CONFESSION)\.?$"),
    re.compile(r"^\s*(OF\s+(THE\s+)?BAPTISM|OF\s+THE\s+SACRAMENT(\s+OF\s+THE\s+ALTAR)?)$"),
]

# All-caps headings that are preface sections
_LLC_PREFACE_RE = re.compile(r"^\s*(PREFACE|SHORT PREFACE OF DR\. MARTIN LUTHER)\.?\s*$")


def _is_llc_subsection(line: str) -> bool:
    stripped = line.strip()
    return any(p.match(stripped) for p in _LLC_SUBSECTION_RES)


def parse_luther_large(body_lines: list, log_lines: list) -> dict:
    """Parse Luther's Large Catechism into a structured_text data object.

    Top-level sections:
      - preface (Preface + Short Preface combined)
      - Part First through Part Fourth (+ optional Fifth)

    Each part has children = sub-sections (The First Commandment, etc.).
    Each sub-section has content_blocks = paragraphs.

    Returns the 'data' object: {"work_id": ..., "work_kind": ..., "sections": [...]}.
    """
    work_id = "luthers-large-catechism"
    lines = body_lines

    # Find structural boundaries by scanning for Part headings
    # We'll build an index of (line_index, type, label) events
    events = []  # (line_idx, event_type, label)

    for i, l in enumerate(lines):
        stripped = l.strip()
        if not stripped:
            continue
        # Preface sections
        if _LLC_PREFACE_RE.match(stripped):
            events.append((i, "preface", stripped.rstrip(".")))
            continue
        # Part headings
        m = _LLC_PART_RE.match(stripped)
        if m:
            ordinal = m.group(1).title()
            title_rest = m.group(2).strip().rstrip(".")
            label = f"Part {ordinal}"
            title = title_rest if title_rest else None
            events.append((i, "part", label, title))
            continue
        # Sub-section headings
        if _is_llc_subsection(stripped):
            events.append((i, "subsection", stripped.rstrip(".")))

    # Build section tree from events
    # Strategy: iterate events, collect content between each event boundary
    sections = []

    # Preface: everything before the first Part heading
    first_part_idx = next(
        (e[0] for e in events if e[1] == "part"), len(lines)
    )

    preface_paragraphs = gather_paragraphs(lines, 0, first_part_idx)
    if preface_paragraphs:
        sections.append(
            {
                "section_type": "preface",
                "label": "Preface",
                "title": "Preface and Short Preface",
                "content_blocks": preface_paragraphs,
                "scripture_references": [],
                "word_count": word_count(preface_paragraphs),
                "children": [],
            }
        )
        log(f"  Preface: {len(preface_paragraphs)} paragraphs", log_lines)

    # Parts
    part_events = [(e[0], e[2], e[3] if len(e) > 3 else None) for e in events if e[1] == "part"]

    for p_idx, (part_line, part_label, part_title) in enumerate(part_events):
        # Content range for this part: from part_line to next part_line
        next_part_line = part_events[p_idx + 1][0] if p_idx + 1 < len(part_events) else len(lines)

        # Subsection events within this part
        sub_events = [
            (e[0], e[2])
            for e in events
            if e[1] == "subsection" and part_line < e[0] < next_part_line
        ]

        # Intro content before first subsection
        first_sub_line = sub_events[0][0] if sub_events else next_part_line
        intro_paragraphs = gather_paragraphs(lines, part_line + 1, first_sub_line)

        children = []

        # Add intro as subsection if substantial
        if intro_paragraphs:
            # Check if this is really an intro (vs scattered content)
            total_intro_words = word_count(intro_paragraphs)
            if total_intro_words > 10:
                children.append(
                    {
                        "section_type": "subsection",
                        "label": "Introduction",
                        "title": None,
                        "content_blocks": intro_paragraphs,
                        "scripture_references": [],
                        "word_count": total_intro_words,
                        "children": [],
                    }
                )

        # Build sub-sections
        for s_idx, (sub_line, sub_label) in enumerate(sub_events):
            next_sub_line = sub_events[s_idx + 1][0] if s_idx + 1 < len(sub_events) else next_part_line
            sub_paragraphs = gather_paragraphs(lines, sub_line + 1, next_sub_line)
            children.append(
                {
                    "section_type": "subsection",
                    "label": sub_label,
                    "title": None,
                    "content_blocks": sub_paragraphs,
                    "scripture_references": [],
                    "word_count": word_count(sub_paragraphs),
                    "children": [],
                }
            )

        part_section = {
            "section_type": "part",
            "label": part_label,
            "title": part_title,
            "content_blocks": [],
            "scripture_references": [],
            "word_count": sum(c["word_count"] for c in children),
            "children": children,
        }
        sections.append(part_section)

        child_summary = ", ".join(c["label"] for c in children[:3])
        if len(children) > 3:
            child_summary += f", ... ({len(children)} total)"
        log(f"  {part_label}: {len(children)} subsections [{child_summary}]", log_lines)

    total_words = sum(s.get("word_count", 0) for s in sections)
    log(f"  Total words: {total_words}", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "catechism-prose",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Calvin's Institutes parser (both volumes combined)
# ---------------------------------------------------------------------------

# Vol 1 chapter headings: "Chapter I. Title Case Title." at column 0 (not in TOC)
# Vol 2 chapter headings: "CHAPTER XIV." ALL CAPS, heavily centered
_CAL_CHAPTER_V1_RE = re.compile(r"^Chapter\s+([IVX]+)\.\s*(.*)$")
_CAL_CHAPTER_V2_RE = re.compile(r"^CHAPTER\s+([IVX]+)\.?\s*$")

# Book headings (both vols): "BOOK I. TITLE" -- ALL CAPS only
# Case-sensitive to exclude TOC entries (Title Case) and body-text references
_CAL_BOOK_STRICT_RE = re.compile(r"^BOOK\s+([IVX]+)\.?\s*(.*)?$")

# TOC entries in Vol 1 use 3-space indent: "   Chapter I. ..."
_TOC_INDENT = 3


def parse_calvin(vol1_body: list, vol2_body: list, log_lines: list) -> dict:
    """Parse Calvin's Institutes (Books I-IV) from two PG volumes.

    Book I-II from Vol 1, Book III merged from both vols, Book IV from Vol 2.
    Structure: Book -> Chapter -> content_blocks (paragraphs).

    Returns the 'data' object.
    """
    work_id = "calvins-institutes"

    def scan_volume(body: list, vol_num: int) -> list:
        """Returns list of (line_idx, 'book'|'chapter', roman, title) events.

        Vol 1: book headings are ALL CAPS (not TOC title case); chapter headings
               are 'Chapter I. Title.' at column 0 (indent < 3 to skip TOC).
        Vol 2: book and chapter headings are ALL CAPS centered; no indent check.
        """
        evts = []
        i = 0
        while i < len(body):
            l = body[i]
            stripped = l.strip()
            if not stripped:
                i += 1
                continue

            # Book headings: ALL CAPS only (filters TOC and body-text refs)
            # "BOOK I. ON THE KNOWLEDGE OF GOD THE CREATOR."
            if stripped.upper() == stripped and stripped.startswith("BOOK "):
                m = _CAL_BOOK_STRICT_RE.match(stripped)
                if m:
                    roman = m.group(1).upper()
                    title = (m.group(2) or "").strip().rstrip(".")
                    evts.append((i, "book", roman, title))
                    i += 1
                    continue

            # Chapter headings differ by volume format
            if vol_num == 1:
                # Vol 1: "Chapter I. Title..." title-case, column-0 (no TOC indent)
                indent = len(l) - len(l.lstrip())
                if indent < _TOC_INDENT:
                    m = _CAL_CHAPTER_V1_RE.match(stripped)
                    if m:
                        evts.append((i, "chapter", m.group(1), m.group(2).strip()))
                        i += 1
                        continue
            else:
                # Vol 2: "CHAPTER XIV." ALL CAPS, centered (no indent limit)
                m = _CAL_CHAPTER_V2_RE.match(stripped)
                if m:
                    roman = m.group(1)
                    title = ""
                    # Chapter title is on the next non-empty ALL CAPS line
                    j = i + 1
                    while j < len(body) and not body[j].strip():
                        j += 1
                    if j < len(body):
                        cand = body[j].strip()
                        if (
                            cand
                            and cand.upper() == cand
                            and not cand.startswith("BOOK ")
                            and not cand.startswith("CHAPTER ")
                            and len(cand) < 250
                        ):
                            title = cand.rstrip(".")
                            i = j  # consume title line
                    evts.append((i, "chapter", roman, title))
                    i += 1
                    continue

            i += 1
        return evts

    log("  Scanning Vol 1...", log_lines)
    events_v1 = scan_volume(vol1_body, 1)
    log("  Scanning Vol 2...", log_lines)
    events_v2 = scan_volume(vol2_body, 2)

    # Report what we found
    books_v1 = [(e[2], e[3]) for e in events_v1 if e[1] == "book"]
    chs_v1 = [(e[2], e[3]) for e in events_v1 if e[1] == "chapter"]
    books_v2 = [(e[2], e[3]) for e in events_v2 if e[1] == "book"]
    chs_v2 = [(e[2], e[3]) for e in events_v2 if e[1] == "chapter"]

    log(f"  Vol 1: {len(books_v1)} books, {len(chs_v1)} chapter headings", log_lines)
    for roman, title in books_v1:
        log(f"    Book {roman}: {title[:60]}", log_lines)
    log(f"  Vol 2: {len(books_v2)} books, {len(chs_v2)} chapter headings", log_lines)
    for roman, title in books_v2:
        log(f"    Book {roman}: {title[:60]}", log_lines)

    def build_book_sections(body: list, events: list, source_label: str) -> list:
        """Build a list of book sections with chapter children from one volume."""
        book_sections = []
        book_events = [(e[0], e[2], e[3]) for e in events if e[1] == "book"]
        all_chapter_events = [(e[0], e[2], e[3]) for e in events if e[1] == "chapter"]

        for b_idx, (book_line, book_roman, book_title) in enumerate(book_events):
            next_book_line = book_events[b_idx + 1][0] if b_idx + 1 < len(book_events) else len(body)

            # Chapters within this book
            ch_events = [
                (l, r, t)
                for l, r, t in all_chapter_events
                if book_line < l < next_book_line
            ]

            children = []
            for c_idx, (ch_line, ch_roman, ch_title) in enumerate(ch_events):
                next_ch_line = ch_events[c_idx + 1][0] if c_idx + 1 < len(ch_events) else next_book_line
                ch_paragraphs = gather_paragraphs(body, ch_line + 1, next_ch_line)
                children.append(
                    {
                        "section_type": "chapter",
                        "label": f"Chapter {ch_roman}",
                        "title": ch_title if ch_title else None,
                        "content_blocks": ch_paragraphs,
                        "scripture_references": [],
                        "word_count": word_count(ch_paragraphs),
                        "children": [],
                    }
                )

            book_sections.append(
                {
                    "section_type": "book",
                    "label": f"Book {book_roman}",
                    "title": book_title.rstrip(".") if book_title else None,
                    "content_blocks": [],
                    "scripture_references": [],
                    "word_count": sum(c["word_count"] for c in children),
                    "children": children,
                }
            )
            log(
                f"  {source_label} Book {book_roman}: {len(children)} chapters, "
                f"{book_sections[-1]['word_count']} words",
                log_lines,
            )

        return book_sections

    # Vol 1 has Books I, II, and the start of III (up to where Vol 2 picks up)
    # Vol 2 has Book III (continuing from Ch XIV) and Book IV
    # Strategy: use Vol 1 for Books I-II (and the partial Book III chapters from Vol 1),
    # and Vol 2 for Books III-IV.
    # Since the volumes split Book III, we need to merge:
    # - Book III chapters from Vol 1 + Book III chapters from Vol 2

    log("  Building Vol 1 sections...", log_lines)
    sections_v1 = build_book_sections(vol1_body, events_v1, "Vol1")

    log("  Building Vol 2 sections...", log_lines)
    sections_v2 = build_book_sections(vol2_body, events_v2, "Vol2")

    # Merge Book III from both volumes
    # sections_v1 contains Books I, II, III (partial)
    # sections_v2 contains Book III (partial, from Ch XIV) and Book IV
    merged_sections = []

    v1_books = {s["label"]: s for s in sections_v1}
    v2_books = {s["label"]: s for s in sections_v2}

    # Books I and II come entirely from Vol 1
    for label in ["Book I", "Book II"]:
        if label in v1_books:
            merged_sections.append(v1_books[label])

    # Book III: merge chapters from both volumes
    book3_v1 = v1_books.get("Book III")
    book3_v2 = v2_books.get("Book III")

    if book3_v1 and book3_v2:
        # Combine: Vol 1 chapters first, then Vol 2 chapters
        combined_children = book3_v1["children"] + book3_v2["children"]
        # Use Vol 2 title (it's the same book, but Vol 1 may have better title)
        book3_title = book3_v1["title"] or book3_v2["title"]
        merged_book3 = {
            "section_type": "book",
            "label": "Book III",
            "title": book3_title,
            "content_blocks": [],
            "scripture_references": [],
            "word_count": sum(c["word_count"] for c in combined_children),
            "children": combined_children,
        }
        merged_sections.append(merged_book3)
        log(
            f"  Book III merged: {len(book3_v1['children'])} ch from Vol1 + "
            f"{len(book3_v2['children'])} ch from Vol2 = {len(combined_children)} total",
            log_lines,
        )
    elif book3_v1:
        merged_sections.append(book3_v1)
    elif book3_v2:
        merged_sections.append(book3_v2)

    # Book IV comes from Vol 2
    if "Book IV" in v2_books:
        merged_sections.append(v2_books["Book IV"])

    total_words = sum(s["word_count"] for s in merged_sections)
    total_chapters = sum(len(s["children"]) for s in merged_sections)
    log(f"  Total: {len(merged_sections)} books, {total_chapters} chapters, {total_words} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "theological-work",
        "sections": merged_sections,
    }


# ---------------------------------------------------------------------------
# Augustine's Confessions parser
# ---------------------------------------------------------------------------

# "BOOK I", "BOOK II", ..., "BOOK XIII"
_AUG_BOOK_RE = re.compile(r"^BOOK\s+([IVX]+)$")


def parse_augustine(body_lines: list, log_lines: list) -> dict:
    """Parse Augustine's Confessions into a structured_text data object.

    Structure: 13 Books, each with continuous prose content_blocks.
    The PG Pusey translation does not mark chapter divisions within books.

    Returns the 'data' object.
    """
    work_id = "augustines-confessions"
    lines = body_lines

    # Find all BOOK headings
    book_events = []
    for i, l in enumerate(lines):
        m = _AUG_BOOK_RE.match(l.strip())
        if m:
            book_events.append((i, m.group(1)))

    log(f"  Found {len(book_events)} book headings", log_lines)

    sections = []
    for b_idx, (book_line, roman) in enumerate(book_events):
        next_book_line = book_events[b_idx + 1][0] if b_idx + 1 < len(book_events) else len(lines)
        paragraphs = gather_paragraphs(lines, book_line + 1, next_book_line)
        wc = word_count(paragraphs)
        sections.append(
            {
                "section_type": "book",
                "label": f"Book {roman}",
                "title": None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            }
        )
        log(f"  Book {roman}: {len(paragraphs)} paragraphs, {wc} words", log_lines)

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Total: {len(sections)} books, {total_words} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "theological-work",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(data: dict, label: str, log_lines: list) -> None:
    """Report completeness metrics for a structured_text work."""
    sections = data.get("sections", [])
    total_sections = 0
    total_blocks = 0
    empty_blocks = 0
    all_word_counts = []

    def traverse(sec_list: list) -> None:
        nonlocal total_sections, total_blocks, empty_blocks
        for sec in sec_list:
            total_sections += 1
            blocks = sec.get("content_blocks", [])
            total_blocks += len(blocks)
            empty_blocks += sum(1 for b in blocks if not b.strip())
            all_word_counts.append(sec.get("word_count", 0))
            traverse(sec.get("children", []))

    traverse(sections)

    all_word_counts.sort()
    log(f"  {label}: {total_sections} sections, {total_blocks} content blocks", log_lines)
    log(f"    Empty blocks: {empty_blocks}", log_lines)
    if all_word_counts:
        mid = len(all_word_counts) // 2
        median = all_word_counts[mid]
        log(
            f"    Word counts (per section): min={all_word_counts[0]}, "
            f"median={median}, max={all_word_counts[-1]}",
            log_lines,
        )


# ---------------------------------------------------------------------------
# Work runners
# ---------------------------------------------------------------------------


def run_luther_large(dry_run: bool, log_lines: list) -> bool:
    """Parse Luther's Large Catechism and write output. Returns True on success."""
    source_path = RAW_DIR / "pg1722.txt"
    output_path = OUTPUT_DIR / "luthers-large-catechism.json"
    work_id = "luthers-large-catechism"

    log(f"\n--- {work_id} (PG#1722) ---", log_lines)
    log(f"  Source: {source_path}", log_lines)

    if not source_path.exists():
        log("  ERROR: Source file not found. Run download_gutenberg.py first.", log_lines)
        return False

    source_hash = sha256_file(source_path)
    log(f"  Hash: {source_hash}", log_lines)

    text = source_path.read_text(encoding="utf-8")
    body_lines = strip_pg_wrapper(text)
    log(f"  Body lines: {len(body_lines)}", log_lines)

    data = parse_luther_large(body_lines, log_lines)
    print_quality_stats(data, work_id, log_lines)

    meta = build_meta_envelope(
        work_id=work_id,
        title="The Large Catechism",
        author="Martin Luther",
        birth=1483,
        death=1546,
        contributors=["F. Bente (translator)", "W. H. T. Dau (translator)"],
        pub_year=1529,
        tradition=["lutheran", "confessional"],
        tradition_notes=(
            "Luther's Large Catechism (1529) was intended for pastors and educated laypeople. "
            "Translated by F. Bente and W. H. T. Dau and published in the Triglot Concordia: "
            "The Symbolical Books of the Ev. Lutheran Church (Concordia Publishing House, 1921). "
            "The 1921 Triglot Concordia is now public domain."
        ),
        era="reformation",
        audience="pastoral",
        original_lang="de",
        source_url="http://www.gutenberg.org/cache/epub/1722/pg1722.txt",
        source_edition=(
            "Bente/Dau translation, Triglot Concordia (CPH 1921), "
            "Project Gutenberg digitization"
        ),
        source_hash=source_hash,
        notes=(
            "Contains Preface, Short Preface, and four main parts: Ten Commandments, "
            "Creed, Lord's Prayer, Baptism. "
            "No chapter headings within sub-sections; content is continuous prose paragraphs."
        ),
    )

    if dry_run:
        top_section = data["sections"][0] if data["sections"] else {}
        log(f"  DRY RUN -- first section: {top_section.get('label')} "
            f"({top_section.get('word_count', 0)} words)", log_lines)
        log("  DRY RUN -- no files written", log_lines)
        return True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"meta": meta, "data": data}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {output_path}", log_lines)
    return True


def run_calvin(dry_run: bool, log_lines: list) -> bool:
    """Parse Calvin's Institutes (both volumes) and write output. Returns True on success."""
    path_v1 = RAW_DIR / "pg45001.txt"
    path_v2 = RAW_DIR / "pg64392.txt"
    output_path = OUTPUT_DIR / "calvins-institutes.json"
    work_id = "calvins-institutes"

    log(f"\n--- {work_id} (PG#45001 + PG#64392) ---", log_lines)

    for path in [path_v1, path_v2]:
        if not path.exists():
            log(f"  ERROR: {path.name} not found. Run download_gutenberg.py first.", log_lines)
            return False

    hash_v1 = sha256_file(path_v1)
    hash_v2 = sha256_file(path_v2)
    log(f"  Hash v1: {hash_v1}", log_lines)
    log(f"  Hash v2: {hash_v2}", log_lines)

    # Combined hash for provenance (hash of both hashes concatenated)
    combined_hash = "sha256:" + hashlib.sha256((hash_v1 + hash_v2).encode()).hexdigest()

    text_v1 = path_v1.read_text(encoding="utf-8")
    text_v2 = path_v2.read_text(encoding="utf-8")
    body_v1 = strip_pg_wrapper(text_v1)
    body_v2 = strip_pg_wrapper(text_v2)
    log(f"  Body lines v1: {len(body_v1)}, v2: {len(body_v2)}", log_lines)

    data = parse_calvin(body_v1, body_v2, log_lines)
    print_quality_stats(data, work_id, log_lines)

    meta = build_meta_envelope(
        work_id=work_id,
        title="Institutes of the Christian Religion",
        author="John Calvin",
        birth=1509,
        death=1564,
        contributors=["John Allen (translator)"],
        pub_year=1536,
        tradition=["reformed", "calvinist", "confessional"],
        tradition_notes=(
            "Calvin's Institutes (1536, final Latin edition 1559) is the foundational "
            "systematic theology of the Reformed tradition. "
            "This PG edition uses the John Allen translation (6th American edition, "
            "Philadelphia: Presbyterian Board of Publication). The original task specification "
            "anticipated the Beveridge 1845 translation; however, PG #45001 and #64392 "
            "contain the Allen translation. Both are public domain."
        ),
        era="reformation",
        audience="scholarly",
        original_lang="la",
        source_url=(
            "http://www.gutenberg.org/cache/epub/45001/pg45001.txt; "
            "http://www.gutenberg.org/cache/epub/64392/pg64392.txt"
        ),
        source_edition=(
            "John Allen translation (6th American ed., Presbyterian Board of Publication), "
            "Project Gutenberg PG#45001 (Vol I) + PG#64392 (Vol II), merged"
        ),
        source_hash=combined_hash,
        notes=(
            "Books I-IV combined from two PG volumes. "
            "Book III chapters are split across both volumes and merged here. "
            "Source hash is SHA-256 of the concatenation of both file hashes."
        ),
    )

    if dry_run:
        books = [s["label"] for s in data["sections"]]
        log(f"  DRY RUN -- books: {books}", log_lines)
        log("  DRY RUN -- no files written", log_lines)
        return True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"meta": meta, "data": data}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {output_path}", log_lines)
    return True


def run_augustine(dry_run: bool, log_lines: list) -> bool:
    """Parse Augustine's Confessions and write output. Returns True on success."""
    source_path = RAW_DIR / "pg3296.txt"
    output_path = OUTPUT_DIR / "augustines-confessions.json"
    work_id = "augustines-confessions"

    log(f"\n--- {work_id} (PG#3296) ---", log_lines)

    if not source_path.exists():
        log("  ERROR: Source file not found. Run download_gutenberg.py first.", log_lines)
        return False

    source_hash = sha256_file(source_path)
    log(f"  Hash: {source_hash}", log_lines)

    text = source_path.read_text(encoding="utf-8")
    body_lines = strip_pg_wrapper(text)
    log(f"  Body lines: {len(body_lines)}", log_lines)

    data = parse_augustine(body_lines, log_lines)
    print_quality_stats(data, work_id, log_lines)

    meta = build_meta_envelope(
        work_id=work_id,
        title="Confessions",
        author="Augustine of Hippo",
        birth=354,
        death=430,
        contributors=["E. B. Pusey (translator)"],
        pub_year=401,
        tradition=["patristic", "catholic"],
        tradition_notes=(
            "Augustine of Hippo's Confessions (c. 397-401 AD) is one of the foundational "
            "works of Western Christian spirituality. This PG edition uses the Edward "
            "Bouverie Pusey translation (1838). Pusey was an Oxford Movement Anglican "
            "scholar whose translation became widely used."
        ),
        era="patristic",
        audience="lay",
        original_lang="la",
        source_url="http://www.gutenberg.org/cache/epub/3296/pg3296.txt",
        source_edition=(
            "E. B. Pusey translation (Edward Bouverie Pusey, 1838), "
            "Project Gutenberg PG#3296"
        ),
        source_hash=source_hash,
        notes=(
            "13 books. The Pusey PG edition does not mark chapter divisions within books; "
            "content is structured at book level with continuous prose content_blocks. "
            "Chapter-level structure would require a different edition."
        ),
    )

    if dry_run:
        for sec in data["sections"]:
            log(f"  DRY RUN -- {sec['label']}: {sec['word_count']} words", log_lines)
        log("  DRY RUN -- no files written", log_lines)
        return True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"meta": meta, "data": data}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {output_path}", log_lines)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

WORK_RUNNERS = {
    "luther_large": run_luther_large,
    "calvin": run_calvin,
    "augustine": run_augustine,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse PG theological texts to structured_text JSON"
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing output")
    parser.add_argument(
        "--work",
        choices=list(WORK_RUNNERS.keys()),
        help="Parse one work only (default: all)",
    )
    args = parser.parse_args()

    log_lines = []
    start_time = time.time()
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log(f"[{run_ts}] gutenberg_theology -- {'DRY RUN' if args.dry_run else 'LIVE RUN'}", log_lines)

    keys_to_run = [args.work] if args.work else list(WORK_RUNNERS.keys())
    log(f"Works to parse: {', '.join(keys_to_run)}", log_lines)

    successes = 0
    failures = 0
    for key in keys_to_run:
        ok = WORK_RUNNERS[key](args.dry_run, log_lines)
        if ok:
            successes += 1
        else:
            failures += 1

    elapsed = time.time() - start_time
    log(f"\nDone -- {successes} succeeded, {failures} failed, {elapsed:.1f}s", log_lines)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n\n")

    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
