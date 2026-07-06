"""ia_fisher_marrow.py
Parser for Edward Fisher, *The Marrow of Modern Divinity* (1645), in the
Thomas Boston annotated edition (Edinburgh: J. and D. Collie, 1828).

Source: Internet Archive identifier `marrowmoderndiv00bostgoog`. Format
`_djvu.txt` (Google Books OCR via ABBYY).

The Marrow is a theological dialogue between four named speakers:
  Evan.  -- Evangelista, a minister of the gospel
  Nom.   -- Nomista, a legalist
  Ant.   -- Antinomista, an antinomian
  Neo.   -- Neophytus, a young Christian

Speaker labels are preserved as bold prefixes at the start of paragraphs
(`**Evan.** body...`). The schema's content_blocks are plain strings, so a
dedicated `speaker` field would require a schema bump that a single-work
acquisition does not justify.

Boston's footnote markers (`*`, `†`, `‡`) are preserved inline with the body.
Plain-text OCR has no reliable cue to segregate footnote text from main text;
this is documented in research/prompts/acquire-fisher-marrow-ia-census.md.

Two-part structure:
  Part I   -- The covenant of works and the covenant of grace
  Part II  -- An exposition of the Ten Commandments

Each part contains chapters (`Chap. I.`, `Chap. II.`, ...) which contain
sections (`Sect. 1.`, `Sect. 2.`, ...). Sections are leaf nodes carrying
content_blocks; chapters without explicit Sect. markers carry content_blocks
directly.

Usage:
    py -3 build/parsers/ia_fisher_marrow.py --download
    py -3 build/parsers/ia_fisher_marrow.py --parse --dry-run
    py -3 build/parsers/ia_fisher_marrow.py --parse
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib._generated_enums import (
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__DEFS__SECTION__SECTION_TYPE,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__LICENSE,
    STRUCTURED_TEXT__META__PROVENANCE__PROCESSING_METHOD,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.text_utils import compute_source_hash, normalize_line
from build.parsers._framework import assert_source_evidence  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
RAW_DIR = REPO_ROOT / "raw" / "internet-archive" / "fisher-marrow"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
OUTPUT_FILE = OUTPUT_DIR / "fisher-marrow-of-modern-divinity.json"
LOG_PATH = REPO_ROOT / "logs" / "ia_fisher_marrow.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "build/parsers/ia_fisher_marrow.py@v1.0.2"

# Internet Archive identifier and filename
IA_IDENTIFIER = "marrowmoderndiv00bostgoog"
IA_FILENAME = f"{IA_IDENTIFIER}_djvu.txt"
IA_DOWNLOAD_URL = f"https://archive.org/download/{IA_IDENTIFIER}/{IA_FILENAME}"
IA_DETAILS_URL = f"https://archive.org/details/{IA_IDENTIFIER}"

USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)
DOWNLOAD_DELAY_SECONDS = 10

# WORK_CONFIG: single entry, mirrors structure used by external-config parsers
WORK_CONFIG = {
    "work_id": "fisher-marrow-of-modern-divinity",
    "title": "The Marrow of Modern Divinity",
    "author": "Edward Fisher",
    "author_id": "fisher-edward",
    "author_birth_year": 1627,
    "author_death_year": 1655,
    "contributors": [
        {"name": "Thomas Boston (annotator, 1677-1732)"},
    ],
    "original_publication_year": 1645,
    "language": "en",
    "original_language": "en",
    "tradition": ["reformed", "puritan"],
    "tradition_notes": (
        "Edward Fisher was an English lay theologian whose Marrow of Modern Divinity "
        "(1645) became central to Scottish Federal Theology after Thomas Boston "
        "(1677-1732) reissued it with annotations in 1718. The 1720s 'Marrow Controversy' "
        "in the Church of Scotland turned on Boston's reading of Fisher's covenantal "
        "framework. This is the canonical Scottish Reformed form of the work."
    ),
    "era": "post-reformation",
    "audience": "pastoral",
    "license": "public-domain",
    "schema_type": "structured_text",
    "work_kind": "theological-work",
    "completeness": "full",
    # Evidence strings unique to the Boston 1828 Edinburgh edition.
    # assert_source_evidence() checks these against the raw OCR text at parse time.
    # "Boston" verifies Thomas Boston's annotations are present (absent from
    # the 1645 Fisher-only editions). "Edinburgh" verifies the publication city.
    "expected_source_evidence": [
        "Boston",
        "Edinburgh",
    ],
    "source_edition": (
        "Edinburgh: J. and D. Collie, 1828; Thomas Boston annotated edition "
        "(reprint of Boston's 1718 annotated text)"
    ),
}

# ---------------------------------------------------------------------------
# Schema enum guards (REL-09 / schema-enum source-of-truth)
# ---------------------------------------------------------------------------

for _t in WORK_CONFIG["tradition"]:
    assert _t in STRUCTURED_TEXT__META__TRADITION, f"invalid tradition {_t!r}"
assert WORK_CONFIG["era"] in STRUCTURED_TEXT__META__ERA, (
    f"invalid era {WORK_CONFIG['era']!r}"
)
assert WORK_CONFIG["audience"] in STRUCTURED_TEXT__META__AUDIENCE, (
    f"invalid audience {WORK_CONFIG['audience']!r}"
)
assert WORK_CONFIG["completeness"] in STRUCTURED_TEXT__META__COMPLETENESS, (
    f"invalid completeness {WORK_CONFIG['completeness']!r}"
)
assert WORK_CONFIG["license"] in STRUCTURED_TEXT__META__LICENSE, (
    f"invalid license {WORK_CONFIG['license']!r}"
)
assert WORK_CONFIG["work_kind"] in STRUCTURED_TEXT__DATA__WORK_KIND, (
    f"invalid work_kind {WORK_CONFIG['work_kind']!r}"
)
assert "ocr" in STRUCTURED_TEXT__META__PROVENANCE__PROCESSING_METHOD, (
    "schema missing 'ocr' processing_method"
)
for _st in ("part", "chapter", "section", "introduction", "conclusion", "preface"):
    assert _st in STRUCTURED_TEXT__DEFS__SECTION__SECTION_TYPE, (
        f"invalid section_type {_st!r}"
    )

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
            logging.StreamHandler(),
        ],
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_source() -> Path:
    """Download the IA _djvu.txt file if not cached. Returns local path."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    local_path = RAW_DIR / IA_FILENAME

    if local_path.exists():
        logger.info("Cached: %s (%d bytes)", local_path.name, local_path.stat().st_size)
        return local_path

    logger.info("Downloading %s", IA_DOWNLOAD_URL)

    last_exc: Exception | None = None
    for attempt in range(3):
        if attempt:
            delay = 2 ** attempt
            logger.warning("Retry %d/2 after %ds ...", attempt, delay)
            time.sleep(delay)
        try:
            req = urllib.request.Request(IA_DOWNLOAD_URL, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as resp:
                if resp.getcode() not in (200, 206):
                    raise RuntimeError(f"HTTP {resp.getcode()}")
                data = resp.read()
            local_path.write_bytes(data)
            logger.info("Downloaded %d bytes -> %s", len(data), local_path.name)
            logger.info("SHA-256: %s", hashlib.sha256(data).hexdigest())
            return local_path
        except Exception as exc:
            last_exc = exc
            logger.warning("Download attempt %d failed: %s", attempt + 1, exc)

    raise RuntimeError(
        f"Download failed for {IA_FILENAME} after 3 attempts: {last_exc}"
    ) from last_exc




# ---------------------------------------------------------------------------
# Text classification helpers
# ---------------------------------------------------------------------------


# Pre-compiled regexes -- structural markers
# Real chapter heading is fully ALL-CAPS, standalone on its line, ending after
# a roman/letter token. Mixed-case variants like 'Chap. 2.' are running page
# headers and must be skipped instead.
RE_CHAPTER_HEADING = re.compile(r"^(?:CHAP|CHAPTER)\.?\s+[A-Z]+\.?\s*$")
# Part II boundary: literally 'PART SECOND' (1828 Boston edition convention).
RE_PART_SECOND = re.compile(r"^PART\s+SECOND[,.\s]*$")
# Part II commandment headings are mostly standalone, with a few OCR variants.
RE_COMMANDMENT_HEADING = re.compile(
    r"^\W*COMMANDMENT\s+(?P<num>[IVXLCDM]+|IF|VHI)[.,\-\s]*$",
    re.IGNORECASE,
)
# Section heading. The OCR has many punctuation variants after 'Sect'
# ('Sect.', 'Sect,', 'Sect*', 'Sect-') and after the number ('1.', '1,', '1').
# Real section headings end with an em-dash (or two hyphens) that introduces
# the section body. Synopsis lines listing multiple sections (e.g.
# 'Sect. I. The Nature... — 2. Adam's Fall — 3. ...') are skipped at runtime
# via the 'synopsis_expected' state immediately after a CHAPTER heading.
RE_SECT_HEADING = re.compile(
    r"^[Ss]ect[*.,\-]?\s+(?P<num>\d+|[IVXLMixvlm]+)[*†‡.,]?\s*[—–\-]+\s*(?P<rest>.*)$"
)
# Speaker labels at line start. Canonical OCR forms only.
# OCR variants like 'Nam' for 'Nom' are common enough to include; others
# (jVbm, JSVaw, iVeo, AnL, ...) are too noisy and stay as written.
_SPEAKER_RE = r"(?P<speaker>Evan|Nom|Nam|Ant|Neo)"
RE_SECTION_INLINE_SPEAKER = re.compile(
    r"^[Ss]ect[*.,\-]?\s+(?P<num>\d+|[IVXLMixvlm]+)[*†‡.,]?\s*[—–\-]+\s*"
    + _SPEAKER_RE
    + r"\.?\s+(?P<rest>.*)$"
)
RE_SPEAKER = re.compile(r"^" + _SPEAKER_RE + r"\.\s+(?P<rest>.*)$")
# Standalone digits = page number. Skip.
RE_PAGE_NUMBER = re.compile(r"^\d+\s*$")
# Body-start sentinel: 'INTRODUCTION.' line (the first one followed by a
# substantive Sect. line is the dialogue body, not the TOC).
RE_INTRODUCTION = re.compile(r"^INTRODUCTION\.\s*$", re.IGNORECASE)
# Running-header forms in this OCR (mixed-case 'Chap.' / 'Part' / 'Pari' /
# 'MODERN DIVINITY' / 'THE MARROW OF'). These appear hundreds of times.
RE_RUNNING_HEADER_CHAP = re.compile(r"^Chap\.?\s+", re.IGNORECASE)
RE_RUNNING_HEADER_PART = re.compile(r"^Par[ti]\b", re.IGNORECASE)

_COMMANDMENT_OCR_NUMS = {
    "IF": "II",
    "VHI": "VIII",
}

_PRESERVE_HYPHEN_PREFIXES = frozenset([
    "christ",
    "death",
    "god",
    "gospel",
    "heart",
    "ill",
    "law",
    "life",
    "self",
    "sin",
    "well",
])


def is_running_header(norm: str) -> bool:
    """Detect running page headers to skip.

    Forms observed in this _djvu.txt:
      'Chap. 2.', 'Chap. 2. MODERN DIVINITY. 17', 'Chap. 2,' (single-line)
      'Part 1.', 'Part I.', 'Part L', 'Part 2.', 'Pari I.', 'Pan 1.'  (right-edge)
      'THE MARROW OF', 'MODERN DIVINITY' (top-of-page banners)
      Standalone short ALL-CAPS noise lines from page boundaries.

    The real chapter heading 'CHAPTER I.' is fully ALL-CAPS and is matched
    before this function runs (see RE_CHAPTER_HEADING). The real Part II
    boundary is 'PART SECOND,' (matched separately).
    """
    s = norm.strip()
    if not s:
        return False

    # Mixed-case 'Chap.' or 'Pari' / 'Part' is a running header.
    # (ALL-CAPS forms are real headings or skipped earlier.)
    if RE_RUNNING_HEADER_CHAP.match(s) and not s.startswith(("CHAP.", "CHAPTER")):
        return True
    if RE_RUNNING_HEADER_PART.match(s) and not s.upper().startswith("PART SECOND"):
        # Allow the literal 'PART SECOND,' boundary; everything else with
        # a 'Part'/'Pari' prefix is a running header.
        return True

    upper = s.upper()
    if "MARROW OF MODERN DIVINITY" in upper and len(s) < 60:
        return True
    if upper.startswith("THE MARROW OF"):
        return True
    if upper.startswith("MODERN DIVINITY") and len(s) < 40:
        return True
    if upper in {
        "THE MARROW", "MARROW", "OF MODERN DIVINITY",
        "MARROW OF", "MARROW OF MODERN",
    }:
        return True
    return False


def is_page_marker(norm: str) -> bool:
    """Standalone digits = page number; skip."""
    return bool(RE_PAGE_NUMBER.match(norm.strip()))


# ---------------------------------------------------------------------------
# Body-start detection
# ---------------------------------------------------------------------------


def find_body_start(lines: list[str]) -> int:
    """Locate the first body-content line after Google Books boilerplate, title
    page, dedications, preface, and TOC.

    Strategy: walk past the Google Books boilerplate (~first 80 lines) and
    locate the first occurrence of an INTRODUCTION. line that is followed
    within ~15 lines by an actual paragraph (not just a TOC fragment).

    Falls back to first Sect. 1. occurrence after line 200 if no INTRODUCTION.
    found.
    """
    # Google Books boilerplate ends around line 50-80; the dedication / preface
    # / TOC then runs through several hundred lines. Body proper begins at the
    # first INTRODUCTION. that has substantive prose content following it.
    # Phase 1: scan for all INTRODUCTION. occurrences.
    intro_indices = [
        i for i, ln in enumerate(lines) if RE_INTRODUCTION.match(normalize_line(ln))
    ]
    # Phase 2: pick the first INTRODUCTION. that is followed within 30 lines
    # by substantial paragraph text (>= 60 chars) or a Sect. line. The TOC's
    # 'INTRODUCTION.' entry is followed by short page-number-style fragments,
    # not by a real synopsis or dialogue.
    for idx in intro_indices:
        for j in range(idx + 1, min(idx + 30, len(lines))):
            norm = normalize_line(lines[j]).strip()
            if not norm:
                continue
            if norm.lower().startswith("sect") or len(norm) >= 60:
                return idx
    # Fallback: first 'Sect. 1.' line after line 200
    for i, ln in enumerate(lines[200:], start=200):
        norm = normalize_line(ln).strip()
        if norm.lower().startswith("sect. 1.") or norm.lower().startswith("sect, 1."):
            return i
    return -1


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _new_section(label: str | None, title: str | None,
                 section_type: str = "section") -> dict:
    return {
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": [],
        "scripture_references": [],
        "children": [],
    }


def apply_speaker_prefix(text: str) -> str:
    """If text begins with a speaker label, wrap that label in markdown bold:
    'Evan. The truth' -> '**Evan.** The truth'.

    Handles section-prefixed forms: 'Sect. 1. — Nom. The truth' becomes
    'Sect. 1. — **Nom.** The truth'. OCR variant 'Nam.' for 'Nom.' is
    preserved as written (not normalised).
    """
    m = RE_SECTION_INLINE_SPEAKER.match(text)
    if m:
        sect_num = m.group("num")
        speaker = m.group("speaker")
        rest = m.group("rest")
        return f"Sect. {sect_num}. — **{speaker}.** {rest}"
    m = RE_SPEAKER.match(text)
    if m:
        speaker = m.group("speaker")
        rest = m.group("rest")
        return f"**{speaker}.** {rest}"
    return text


def _merge_ocr_hyphen_breaks(lines: list[str]) -> list[str]:
    """Repair OCR word breaks split across line endings inside one paragraph."""
    merged: list[str] = []
    for line in lines:
        if (
            merged
            and merged[-1].endswith("-")
            and line
            and line[0].islower()
        ):
            prefix = merged[-1].rsplit(None, 1)[-1][:-1].lower()
            if prefix.isalpha():
                if prefix in _PRESERVE_HYPHEN_PREFIXES:
                    merged[-1] = merged[-1] + line
                else:
                    merged[-1] = merged[-1][:-1] + line
                continue
        merged.append(line)
    return merged


def _normalise_commandment_num(raw_num: str) -> str:
    return _COMMANDMENT_OCR_NUMS.get(raw_num.upper(), raw_num.upper())


def _apply_chapter_title(chapter: dict, parts: list[str]) -> None:
    raw = " ".join(parts)
    raw = re.sub(r"\bOP\b", "OF", raw)  # OCR misreads 'F' as 'P' in 'OF'
    chapter["title"] = raw.title()


def _roman(n: int) -> str:
    """Convert 1..20 to Roman numeral (sufficient for this work's chapters)."""
    table = [
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    out = ""
    for value, sym in table:
        while n >= value:
            out += sym
            n -= value
    return out


def parse_text(text: str) -> dict:
    """Parse the full _djvu.txt content into the schema's data structure.

    Strategy:
      - Walk lines from the body-start marker (INTRODUCTION. line).
      - Strip running page headers ('Chap. 2.', 'Part I.', 'MODERN DIVINITY' etc.).
      - Detect chapter boundaries via standalone ALL-CAPS 'CHAPTER X.' / 'CHAP. LV.'
        lines. Number chapters by sequence (the OCR mangles roman numerals: e.g.
        'CHAPTER TL' for II, 'CHAP. LV.' for IV; sequence is more reliable).
      - Detect Part II via the literal 'PART SECOND,' line.
      - Within Part I chapters, detect new sections via the inline-speaker form
        'Sect. 1. — Nom. ...' (Arabic digit, em-dash, speaker label).
      - Speaker labels at paragraph start get bold-prefixed.

    Returns:
        {"work_id": ..., "work_kind": ..., "sections": [...]}
    """
    lines = text.splitlines()
    logger.info("Lines total: %d", len(lines))

    body_start = find_body_start(lines)
    if body_start < 0:
        raise RuntimeError("Could not locate body start (no INTRODUCTION./Sect. 1.)")
    logger.info("Body starts at line %d: %r",
                body_start + 1, normalize_line(lines[body_start])[:80])

    parts: list[dict] = []
    current_part = _new_section(label="Part I", title=None, section_type="part")
    current_chapter: dict | None = None
    current_section: dict | None = None
    chapter_seq = 0  # increments on each detected ALL-CAPS chapter heading
    # Captures the next non-empty ALL-CAPS line(s) immediately after a CHAPTER heading.
    pending_chapter_title: list[str] | None = None
    paragraph: list[str] = []
    paragraph_starts_new_speaker_turn = True

    def commit_section() -> None:
        nonlocal current_section
        if current_section is not None and (
            current_section["content_blocks"] or current_section["children"]
        ):
            target = current_chapter if current_chapter is not None else current_part
            target["children"].append(_finalize_section(current_section))
        current_section = None

    def commit_chapter() -> None:
        nonlocal current_chapter
        commit_section()
        if current_chapter is not None and (
            current_chapter["content_blocks"] or current_chapter["children"]
        ):
            current_part["children"].append(_finalize_section(current_chapter))
        current_chapter = None

    def commit_part() -> None:
        nonlocal current_part
        commit_chapter()
        if current_part["content_blocks"] or current_part["children"]:
            parts.append(_finalize_section(current_part))

    def append_paragraph_to_current() -> None:
        nonlocal paragraph_starts_new_speaker_turn
        if not paragraph:
            paragraph_starts_new_speaker_turn = True
            return
        joined = " ".join(_merge_ocr_hyphen_breaks(paragraph)).strip()
        joined = re.sub(r"\s+", " ", joined)
        if joined:
            if paragraph_starts_new_speaker_turn:
                joined = apply_speaker_prefix(joined)
            target = (
                current_section if current_section is not None
                else current_chapter if current_chapter is not None
                else current_part
            )
            target["content_blocks"].append(joined)
        paragraph.clear()
        paragraph_starts_new_speaker_turn = True

    in_part_two = False

    for raw_line in lines[body_start:]:
        norm = normalize_line(raw_line)
        stripped = norm.strip()

        # Paragraph break
        if not stripped:
            append_paragraph_to_current()
            continue

        # Page numbers and running headers
        if is_page_marker(norm) or is_running_header(norm):
            continue

        # PART SECOND boundary -- enter Part II
        if RE_PART_SECOND.match(stripped):
            append_paragraph_to_current()
            commit_part()
            current_part = _new_section(
                label="Part II", title=None, section_type="part",
            )
            current_chapter = None
            current_section = None
            chapter_seq = 0
            pending_chapter_title = None
            in_part_two = True
            continue

        # Part II headings are the Ten Commandments exposition. Standalone
        # OCR variants such as "COMMANDMENT IF." mean "COMMANDMENT II.".
        m_commandment = RE_COMMANDMENT_HEADING.match(stripped)
        if in_part_two and m_commandment:
            append_paragraph_to_current()
            commit_section()
            roman = _normalise_commandment_num(m_commandment.group("num"))
            current_section = _new_section(
                label=f"Commandment {roman}",
                title=f"Commandment {roman}",
                section_type="section",
            )
            continue

        # ALL-CAPS chapter heading (only valid in Part I; Part II has no
        # explicit chapters in this edition).
        if not in_part_two and RE_CHAPTER_HEADING.match(stripped):
            append_paragraph_to_current()
            commit_chapter()
            chapter_seq += 1
            roman = _roman(chapter_seq)
            current_chapter = _new_section(
                label=f"Chap. {roman}", title=None, section_type="chapter",
            )
            current_section = None
            pending_chapter_title = []
            continue

        # Capture chapter title (ALL-CAPS lines immediately after a CHAPTER
        # heading, before any Sect. or body line).
        if pending_chapter_title is not None:
            is_all_caps = stripped == stripped.upper() and any(
                c.isalpha() for c in stripped
            )
            looks_like_sect = bool(RE_SECT_HEADING.match(stripped))
            if is_all_caps and not looks_like_sect:
                pending_chapter_title.append(stripped.rstrip(" .,;:"))
                continue
            # End of pending title
            if pending_chapter_title and current_chapter is not None:
                _apply_chapter_title(current_chapter, pending_chapter_title)
            pending_chapter_title = None

        # Section start (real Sect. N. heading with em-dash).
        # The chapter synopsis line ('Sect. I. The Nature of... — 2. Adam's
        # Fall — 3. ...') has no em-dash directly after the section number, so
        # RE_SECT_HEADING does not match it -- it falls through to the body
        # branch and accumulates into the chapter's content_blocks ahead of
        # the first real Sect. heading.
        m_sect = RE_SECT_HEADING.match(stripped)
        if m_sect:
            if current_chapter is not None or in_part_two:
                append_paragraph_to_current()
                commit_section()
                sect_num = m_sect.group("num")
                label = f"Sect. {sect_num}"
                current_section = _new_section(
                    label=label, title=None, section_type="section",
                )
                paragraph.append(stripped)
                continue

        # Body line -- accumulate into paragraph buffer
        paragraph.append(stripped)

    # Flush trailing buffer / open sections
    append_paragraph_to_current()
    if pending_chapter_title and current_chapter is not None:
        _apply_chapter_title(current_chapter, pending_chapter_title)
    commit_part()

    if not parts:
        raise RuntimeError("Parser produced 0 parts; check body-start detection")

    if len(parts) == 1:
        logger.warning(
            "Only one part parsed; expected Part I + Part II for Boston edition."
        )

    return {
        "work_id": WORK_CONFIG["work_id"],
        "work_kind": WORK_CONFIG["work_kind"],
        "sections": parts,
    }


def _finalize_section(section: dict) -> dict:
    """Recursively compute word_count and prune empty fields per schema."""
    children = [_finalize_section(c) for c in section.get("children", [])]
    blocks = section.get("content_blocks", [])
    out: dict = {
        "section_type": section["section_type"],
        "label": section.get("label"),
        "title": section.get("title"),
        "content_blocks": blocks,
        "scripture_references": section.get("scripture_references", []),
        "word_count": sum(len(b.split()) for b in blocks),
    }
    # Only attach children when non-empty (schema allows omission)
    if children:
        out["children"] = children
    return out


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def build_meta(source_hash: str, download_date: str) -> dict:
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "id": WORK_CONFIG["work_id"],
        "title": WORK_CONFIG["title"],
        "author": WORK_CONFIG["author"],
        "author_id": WORK_CONFIG["author_id"],
        "author_birth_year": WORK_CONFIG["author_birth_year"],
        "author_death_year": WORK_CONFIG["author_death_year"],
        "contributors": WORK_CONFIG["contributors"],
        "original_publication_year": WORK_CONFIG["original_publication_year"],
        "language": WORK_CONFIG["language"],
        "original_language": WORK_CONFIG["original_language"],
        "tradition": WORK_CONFIG["tradition"],
        "tradition_notes": WORK_CONFIG["tradition_notes"],
        "era": WORK_CONFIG["era"],
        "audience": WORK_CONFIG["audience"],
        "license": WORK_CONFIG["license"],
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": WORK_CONFIG["completeness"],
        "provenance": {
            "source_url": IA_DETAILS_URL,
            "source_format": "_djvu.txt OCR (Google Books, ABBYY FineReader)",
            "source_edition": WORK_CONFIG["source_edition"],
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "ocr",
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": process_date,
            "source_type": "internet_archive_djvu",
            "source_file": str(
                (RAW_DIR / IA_FILENAME).relative_to(REPO_ROOT)
            ).replace("\\", "/"),
            "translator": None,
            "notes": (
                "Boston annotated edition (Edinburgh: J. and D. Collie, 1828). "
                "Speaker labels (Evan./Nom./Ant./Neo.) preserved as bold prefix in "
                "content_blocks. Boston's footnote markers (*, dagger) preserved "
                "inline; plain-text OCR cannot reliably segregate footnote bodies "
                "from main text. Google Books boilerplate and TOC skipped via "
                "INTRODUCTION. body marker. Part II commandment headings are "
                "preserved as child sections when explicitly detected in OCR. "
                "crawl-delay 10s honoured."
            ),
        },
    }


def save_output(doc: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(str(OUTPUT_FILE), "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    size_kb = OUTPUT_FILE.stat().st_size / 1024
    logger.info("Wrote %s (%.0f KB)", OUTPUT_FILE.name, size_kb)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _walk_sections(sections: list[dict]):
    for s in sections:
        yield s
        yield from _walk_sections(s.get("children", []))


def print_stats(doc: dict) -> None:
    sections = doc["data"]["sections"]
    leaf_count = 0
    block_count = 0
    word_count = 0
    speaker_blocks = {"Evan": 0, "Nom": 0, "Ant": 0, "Neo": 0}
    for s in _walk_sections(sections):
        if s.get("content_blocks"):
            leaf_count += 1
            block_count += len(s["content_blocks"])
            for block in s["content_blocks"]:
                word_count += len(block.split())
                for sp in speaker_blocks:
                    if block.startswith(f"**{sp}.**") or f"**{sp}.**" in block[:80]:
                        speaker_blocks[sp] += 1
                        break
    logger.info("--- Stats ---")
    logger.info("  Top-level parts: %d", len(sections))
    for p in sections:
        logger.info("    %s: %d chapters/children", p.get("label"), len(p.get("children", [])))
    logger.info("  Leaf sections with content: %d", leaf_count)
    logger.info("  Content blocks total: %d", block_count)
    logger.info("  Word count total: %d", word_count)
    logger.info("  Blocks beginning with speaker prefix: %s", speaker_blocks)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def cmd_download() -> int:
    setup_logging()
    path = download_source()
    logger.info("Source hash: %s", compute_source_hash(path))
    return 0


def cmd_parse(dry_run: bool) -> int:
    setup_logging()
    path = RAW_DIR / IA_FILENAME
    if not path.exists():
        logger.error("Source not cached at %s -- run --download first", path)
        return 2

    raw_bytes = path.read_bytes()
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed, falling back to latin-1")
        text = raw_bytes.decode("latin-1", errors="replace")
    download_date = datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc,
    ).strftime("%Y-%m-%d")

    # Verify we have the correct edition before parsing (F-10 fix).
    # Raises ValueError if any expected_source_evidence string is absent.
    assert_source_evidence(WORK_CONFIG, text)

    data = parse_text(text)
    meta = build_meta(source_hash, download_date)
    doc = {"meta": meta, "data": data}

    print_stats(doc)

    if dry_run:
        logger.info("[dry-run] Skipping write to %s", OUTPUT_FILE)
        # Show the first content block of the first leaf as a smoke check
        for s in _walk_sections(doc["data"]["sections"]):
            if s.get("content_blocks"):
                logger.info(
                    "[dry-run] first leaf %r block[0]: %s",
                    s.get("label"), s["content_blocks"][0][:160],
                )
                break
        return 0

    save_output(doc)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Parse Edward Fisher's *Marrow of Modern Divinity* (Boston annotated "
            "edition) from Internet Archive _djvu.txt OCR into OCD structured_text."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--download", action="store_true",
        help="Fetch the IA _djvu.txt source and cache locally.",
    )
    group.add_argument(
        "--parse", action="store_true",
        help="Parse the cached source and write JSON output.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="With --parse: parse and report, but do not write the JSON file.",
    )
    parser.add_argument(
        "--edition", choices=["boston"], default="boston",
        help="Edition to acquire. Only 'boston' is currently implemented.",
    )
    args = parser.parse_args()

    if args.download:
        sys.exit(cmd_download())
    if args.parse:
        sys.exit(cmd_parse(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
