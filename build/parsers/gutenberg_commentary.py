"""gutenberg_commentary.py
Reusable parser for verse-keyed commentaries from Project Gutenberg plain-text files.

Designed for 19th-century critical commentaries that follow the Lightfoot/Westcott
pattern: Greek text followed by block-separated verse-by-verse notes.

FIRST USE: J.B. Lightfoot, St Paul's Epistles to the Colossians and to Philemon
  (1875), Project Gutenberg #50857.
  Output: data/commentaries/lightfoot-colossians-philemon/

Verse heading formats handled:
  Colossians  -- Roman numeral chapter + verse(s) + ]: "I. 1, 2]"
  Philemon    -- Verse(s) + ] (single-chapter epistle): "1-3]"

Blocks are separated by dashes (---...) in the PG transcription.
Duplicate headings (same verse covered by multiple blocks) are merged.

Usage:
    py -3 build/parsers/gutenberg_commentary.py --dry-run
    py -3 build/parsers/gutenberg_commentary.py
    py -3 build/parsers/gutenberg_commentary.py --force-download
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)

LOG_FILE = Path(__file__).with_suffix(".log")

RAW_DIR = REPO_ROOT / "raw" / "gutenberg" / "commentary" / "lightfoot-colossians-philemon"
OUTPUT_DIR = REPO_ROOT / "data" / "commentaries" / "lightfoot-colossians-philemon"

RESOURCE_ID = "lightfoot-colossians-philemon"
SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_commentary.py@v1.0.0"
DOWNLOAD_DATE = "2026-06-17"

PG_URL = "https://www.gutenberg.org/cache/epub/50857/pg50857.txt"
PG_FILE = RAW_DIR / "pg50857.txt"

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(open-source data project; contact: openchristiandata@gmail.com)"
)

# ---------------------------------------------------------------------------
# PG structural patterns
# ---------------------------------------------------------------------------

_PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
_PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)
_DASH_SEP_RE = re.compile(r"^-{40,}$")

# Colossians verse heading: Roman-numeral chapter + verse range + ]
# Examples: "I. 3]", "I. 1, 2]", "III. 19–22]", "IV. 18]"
_COL_HEADING_RE = re.compile(r"^([IVX]+)\. ([\d,\s–—\-]+)\]$")

# Philemon verse heading: verse range + ] (no chapter numeral)
# Examples: "1–3]", "4, 5]", "6]", "23–25]"
_PHM_HEADING_RE = re.compile(r"^([\d,\s–—\-]+)\]$")

# ---------------------------------------------------------------------------
# Section config for Lightfoot Colossians+Philemon (#50857)
# ---------------------------------------------------------------------------
# Each dict describes one epistle's commentary section within the PG file.

LIGHTFOOT_COL_PHILEMON_SECTIONS = [
    {
        "book_osis": "Col",
        "book_name": "Colossians",
        "book_number": 51,
        # Pattern that marks the section title (find 2nd occurrence = commentary start)
        "section_title_re": r"ΠΡΟΣ ΚΟΛΑΣΣΑΕΙΣ",
        # Regex for verse headings within this section
        "heading_re": _COL_HEADING_RE,
        # Function to parse heading -> (chapter, verse_range, osis)
        "heading_parser": "col",
        # Pattern marking start of intro content
        "intro_start_re": r"THE CHURCHES OF THE LYCUS",
        # Pattern marking end of this section (exclusive)
        "section_end_re": r"ΠΡΟΣ\s+ΦΙΛΗΜΟΝΑ",
    },
    {
        "book_osis": "Phlm",
        "book_name": "Philemon",
        "book_number": 57,
        "section_title_re": r"ΠΡΟΣ\s+ΦΙΛΗΜΟΝΑ",
        "heading_re": _PHM_HEADING_RE,
        "heading_parser": "phm",
        "intro_start_re": r"INTRODUCTION TO THE EPISTLE\.",
        # End of Philemon = ADDITIONS AND CORRECTIONS or INDEX
        "section_end_re": r"_ADDITIONS AND CORRECTIONS\._|_INDEX\._",
    },
]

# ---------------------------------------------------------------------------
# Utility: Roman numeral conversion
# ---------------------------------------------------------------------------

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to an integer (subtractive notation)."""
    result = 0
    prev = 0
    for ch in reversed(s.upper()):
        curr = _ROMAN_VALUES.get(ch, 0)
        if curr < prev:
            result -= curr
        else:
            result += curr
        prev = curr
    return result


# ---------------------------------------------------------------------------
# Utility: verse range normalization
# ---------------------------------------------------------------------------

def normalize_verse_range(raw: str) -> str:
    """
    Normalize a verse range string from a PG heading to 'N' or 'N-M' format.

    Input forms handled:
      "6"       -> "6"
      "1, 2"    -> "1-2"
      "19–22"   -> "19-22"  (en-dash)
      "1-3"     -> "1-3"
      "1, 2, 3" -> "1-3"   (first to last)
    """
    raw = raw.strip()
    # Normalize en-dash and em-dash to hyphen
    raw = raw.replace("–", "-").replace("—", "-")

    if "," in raw:
        # Comma-separated list: take first and last
        parts = [p.strip() for p in raw.split(",") if p.strip().isdigit()]
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0]}-{parts[-1]}"

    # May already be a hyphen range or single number
    raw = raw.replace(" ", "")
    return raw


# ---------------------------------------------------------------------------
# Utility: OSIS verse range construction
# ---------------------------------------------------------------------------

def build_verse_range_osis(book_osis: str, chapter: int, verse_range: str) -> str:
    """
    Build an OSIS verse reference string.

    Single verse: "Col.1.6"
    Range:        "Col.1.1-Col.1.2"
    """
    if "-" in verse_range:
        start_v, end_v = verse_range.split("-", 1)
        return f"{book_osis}.{chapter}.{start_v}-{book_osis}.{chapter}.{end_v}"
    return f"{book_osis}.{chapter}.{verse_range}"


# ---------------------------------------------------------------------------
# Utility: heading parsers
# ---------------------------------------------------------------------------

def parse_col_heading(heading: str, book_osis: str) -> tuple:
    """
    Parse a Colossians heading like 'I. 1, 2]' or 'III. 19–22]'.

    Returns: (chapter: int, verse_range: str, verse_range_osis: str)
    """
    m = _COL_HEADING_RE.match(heading.strip())
    if not m:
        raise ValueError(f"Not a valid Col heading: {heading!r}")
    chapter = roman_to_int(m.group(1))
    verse_range = normalize_verse_range(m.group(2))
    osis = build_verse_range_osis(book_osis, chapter, verse_range)
    return chapter, verse_range, osis


def parse_phm_heading(heading: str, book_osis: str) -> tuple:
    """
    Parse a Philemon heading like '6]' or '1–3]'.

    Returns: (chapter: int, verse_range: str, verse_range_osis: str)
    Always chapter=1 (Philemon is a single-chapter letter).
    """
    m = _PHM_HEADING_RE.match(heading.strip())
    if not m:
        raise ValueError(f"Not a valid Phlm heading: {heading!r}")
    verse_range = normalize_verse_range(m.group(1))
    osis = build_verse_range_osis(book_osis, 1, verse_range)
    return 1, verse_range, osis


def _is_verse_heading(line: str, section: dict) -> bool:
    """Return True if line matches this section's verse heading pattern."""
    return bool(section["heading_re"].match(line.strip()))


def _parse_heading(heading: str, section: dict) -> tuple:
    """Dispatch to the right heading parser for this section."""
    if section["heading_parser"] == "col":
        return parse_col_heading(heading.strip(), section["book_osis"])
    return parse_phm_heading(heading.strip(), section["book_osis"])


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def _extract_body(text: str) -> list:
    """Strip PG header and footer; return body as list of lines."""
    lines = text.splitlines()
    start = 0
    end = len(lines)
    for i, line in enumerate(lines):
        if _PG_START_RE.search(line):
            start = i + 1
        if _PG_END_RE.search(line):
            end = i
            break
    return lines[start:end]


def _find_nth_occurrence(body: list, pattern_str: str, n: int) -> int:
    """Return line index of the nth occurrence of pattern_str in body. -1 if not found."""
    pat = re.compile(pattern_str)
    count = 0
    for i, line in enumerate(body):
        if pat.search(line):
            count += 1
            if count == n:
                return i
    return -1


def _split_on_dashes(body: list, start: int, end: int) -> list:
    """
    Split body[start:end] into blocks at dash-separator lines.
    Returns list of (block_start_idx, block_lines) tuples.
    """
    blocks = []
    current_start = start
    current_lines = []
    for i in range(start, end):
        line = body[i]
        if _DASH_SEP_RE.match(line.strip()):
            if current_lines:
                blocks.append((current_start, current_lines))
            current_start = i + 1
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        blocks.append((current_start, current_lines))
    return blocks


def _block_text(block_lines: list) -> str:
    """Join block lines into a single text string, stripping leading/trailing blanks."""
    # Remove leading blank lines
    while block_lines and not block_lines[0].strip():
        block_lines = block_lines[1:]
    # Remove trailing blank lines
    while block_lines and not block_lines[-1].strip():
        block_lines = block_lines[:-1]
    return "\n".join(block_lines)


def _word_count(text: str) -> int:
    return len(text.split())


def _build_entry(
    resource_id: str,
    book_osis: str,
    book_name: str,
    book_number: int,
    chapter: int,
    verse_range: str,
    verse_range_osis: "str | None",
    commentary_text: str,
    entry_suffix: str = "",
) -> dict:
    """Build a single commentary entry dict."""
    commentary_text = decode_pg_inline_markup(commentary_text)
    if chapter == 0:
        id_suffix = f"{book_osis}.0.intro"
    else:
        # Use OSIS-style id: "Col.1.1-2" or "Col.1.6"
        id_suffix = f"{book_osis}.{chapter}.{verse_range}"
    entry_id = f"{resource_id}.{id_suffix}{entry_suffix}"

    return {
        "entry_id": entry_id,
        "book": book_name,
        "book_osis": book_osis,
        "book_number": book_number,
        "chapter": chapter,
        "verse_range": verse_range,
        "verse_range_osis": verse_range_osis,
        "verse_text": None,
        "commentary_text": commentary_text,
        "summary": None,
        "summary_review_status": "withheld",
        "cross_references": [],
        "word_count": _word_count(commentary_text),
    }


def _parse_section(body: list, section: dict, resource_id: str, dry_run: bool = False) -> list:
    """
    Parse one epistle's commentary section from the body lines.
    Returns a list of entry dicts.
    """
    book_osis = section["book_osis"]
    book_name = section["book_name"]
    book_number = section["book_number"]
    title_re = section["section_title_re"]
    end_re_str = section.get("section_end_re")
    intro_start_re_str = section.get("intro_start_re")

    # -- Find commentary section start (2nd occurrence of section title) --
    # 1st occurrence is in the intro/dissertations; 2nd is the actual commentary header
    commentary_title_idx = _find_nth_occurrence(body, title_re, 2)
    if commentary_title_idx == -1:
        logging.warning(
            "[%s] Could not find 2nd occurrence of section title %r", book_osis, title_re
        )
        return []

    # Next dash separator after title = start of commentary blocks
    commentary_blocks_start = commentary_title_idx + 1
    while commentary_blocks_start < len(body):
        if _DASH_SEP_RE.match(body[commentary_blocks_start].strip()):
            commentary_blocks_start += 1
            break
        commentary_blocks_start += 1

    # -- Find end of section --
    section_end = len(body)
    if end_re_str:
        end_pat = re.compile(end_re_str)
        for i in range(commentary_blocks_start, len(body)):
            if end_pat.search(body[i]):
                section_end = i
                break

    logging.info(
        "[%s] Commentary section: body lines %d..%d (%d lines)",
        book_osis,
        commentary_blocks_start,
        section_end,
        section_end - commentary_blocks_start,
    )

    # -- Intro section --
    intro_entry = None
    if intro_start_re_str:
        intro_pat = re.compile(intro_start_re_str)
        # Intro runs from intro_start to 1st occurrence of the section title
        intro_title_idx = _find_nth_occurrence(body, title_re, 1)
        intro_start = -1
        for i in range(0, intro_title_idx if intro_title_idx != -1 else len(body)):
            if intro_pat.search(body[i]):
                intro_start = i
                break
        if intro_start != -1:
            intro_end = intro_title_idx if intro_title_idx != -1 else commentary_title_idx
            intro_lines = body[intro_start:intro_end]
            intro_text = _block_text(list(intro_lines))
            if intro_text:
                intro_entry = _build_entry(
                    resource_id, book_osis, book_name, book_number,
                    0, "intro", None, intro_text,
                )

    # -- Commentary blocks --
    blocks = _split_on_dashes(body, commentary_blocks_start, section_end)

    # Collect blocks grouped by verse heading (merge duplicates)
    # ordered_keys preserves first-seen order
    ordered_keys = []
    block_texts = {}  # heading -> list of text chunks

    for _start, block_lines in blocks:
        trimmed = [l for l in block_lines]
        # First non-blank line should be the verse heading
        first_content = next((l.strip() for l in trimmed if l.strip()), "")
        if _is_verse_heading(first_content, section):
            heading = first_content
            # Body = everything after the heading
            rest = block_lines[next(
                j for j, l in enumerate(block_lines) if l.strip() == heading
            ) + 1:]
            text = _block_text(list(rest))
            if heading not in block_texts:
                ordered_keys.append(heading)
                block_texts[heading] = []
            if text:
                block_texts[heading].append(text)
        else:
            if not dry_run:
                logging.debug("[%s] Skipping non-verse block: %r...", book_osis, first_content[:60])

    entries = []
    if intro_entry:
        entries.append(intro_entry)

    # Ensure unique entry_ids (in case of ID collision after normalization)
    seen_ids: set = set()
    if intro_entry:
        seen_ids.add(intro_entry["entry_id"])

    for heading in ordered_keys:
        try:
            chapter, verse_range, verse_range_osis = _parse_heading(heading, section)
        except ValueError as exc:
            logging.warning("[%s] Could not parse heading %r: %s", book_osis, heading, exc)
            continue

        merged_text = "\n\n".join(block_texts[heading])
        if not merged_text.strip():
            logging.warning("[%s] Empty text for heading %r -- skipping", book_osis, heading)
            continue

        suffix = ""
        base_id = f"{resource_id}.{book_osis}.{chapter}.{verse_range}"
        counter = 2
        candidate_id = base_id
        while candidate_id in seen_ids:
            candidate_id = f"{base_id}-{counter}"
            suffix = f"-{counter}"
            counter += 1
        seen_ids.add(candidate_id)

        entry = _build_entry(
            resource_id, book_osis, book_name, book_number,
            chapter, verse_range, verse_range_osis, merged_text, suffix,
        )
        entries.append(entry)

        if dry_run:
            logging.info(
                "  [DRY-RUN] %s: %s -> %s (%d words)",
                book_osis, heading, verse_range_osis, entry["word_count"],
            )

    return entries


def parse_pg_verse_commentary(
    source_path: Path,
    sections: list,
    resource_id: str = RESOURCE_ID,
    dry_run: bool = False,
) -> list:
    """
    Parse a Project Gutenberg plain-text verse-keyed commentary.

    Args:
        source_path: Path to the downloaded PG .txt file.
        sections: List of section config dicts (one per epistle).
        resource_id: Resource identifier prefix for entry_ids.
        dry_run: If True, log but do not write output.

    Returns:
        List of commentary entry dicts.
    """
    text = source_path.read_text(encoding="utf-8", errors="replace")
    body = _extract_body(text)
    logging.info("Body lines: %d", len(body))

    all_entries = []
    for section in sections:
        entries = _parse_section(body, section, resource_id, dry_run=dry_run)
        logging.info(
            "[%s] Parsed %d entries", section["book_osis"], len(entries)
        )
        all_entries.extend(entries)

    return all_entries


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------

def _build_meta(
    resource_id: str,
    book_osis: str,
    download_date: str,
    source_hash: str,
    processing_date: str,
) -> dict:
    return {
        "id": resource_id,
        "title": "St. Paul's Epistles to the Colossians and to Philemon",
        "author": "J.B. Lightfoot",
        "author_birth_year": 1828,
        "author_death_year": 1889,
        "contributors": [],
        "original_publication_year": 1875,
        "language": "en",
        "tradition": ["anglican"],
        "tradition_notes": (
            "J.B. Lightfoot (1828-1889) was a Church of England bishop and "
            "one of the Cambridge Triumvirate of NT scholars (with Westcott and Hort). "
            "His commentaries combine rigorous textual criticism with orthodox Anglican theology."
        ),
        "license": "public-domain",
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "verse_text_source": "none",
        "verse_reference_standard": "OSIS",
        "completeness": "full",
        "coverage": {
            "strategy": "scriptural_canon",
            "intent": "exhaustive",
            "parameters": {
                "books": {
                    "value": (
                        ["Col", "Phlm"] if book_osis == "both"
                        else [book_osis]
                    ),
                    "provenance": {
                        "source": "config",
                        "path": "sources/commentaries/lightfoot-colossians-philemon/config.json",
                    },
                }
            },
        },
        "provenance": {
            "source_url": "https://www.gutenberg.org/ebooks/50857",
            "source_format": "Project Gutenberg plain text (UTF-8)",
            "source_edition": (
                "First edition (Macmillan and Co., London, 1875). "
                "PG transcription by the Distributed Proofreaders team."
            ),
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": processing_date,
            "notes": append_pg_inline_markup_note(
                "Greek and Latin apparatus text preserved verbatim. "
                "Multiple commentary blocks for the same verse are merged. "
                "PG superscript notation (^{N}) and footnote references preserved."
            ),
        },
    }


def _compute_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path, force: bool = False) -> None:
    if dest.exists() and not force:
        logging.info("Using cached source: %s", dest)
        return
    logging.info("Downloading %s -> %s", url, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    logging.info("Downloaded %d bytes", len(data))
    time.sleep(2)  # courteous delay


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    parser = argparse.ArgumentParser(
        description="Parse PG #50857 Lightfoot Colossians+Philemon commentary"
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write")
    parser.add_argument("--force-download", action="store_true", help="Re-download source")
    args = parser.parse_args()

    # Download source
    _download(PG_URL, PG_FILE, force=args.force_download)

    # Parse
    source_hash = _compute_hash(PG_FILE)
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    download_date = DOWNLOAD_DATE

    all_entries = parse_pg_verse_commentary(
        PG_FILE,
        LIGHTFOOT_COL_PHILEMON_SECTIONS,
        resource_id=RESOURCE_ID,
        dry_run=args.dry_run,
    )

    if not all_entries:
        logging.error("Zero records produced -- stopping")
        return 1

    # Group by book
    by_book: dict = {}
    for entry in all_entries:
        bk = entry["book_osis"]
        by_book.setdefault(bk, []).append(entry)

    book_file_map = {"Col": "colossians.json", "Phlm": "philemon.json"}
    book_name_map = {"Col": "Colossians", "Phlm": "Philemon"}
    book_num_map = {"Col": 51, "Phlm": 57}

    for book_osis, entries in by_book.items():
        count = len([e for e in entries if e["chapter"] > 0])
        intro = len([e for e in entries if e["chapter"] == 0])
        logging.info(
            "[%s] %d verse entries, %d intro record(s)", book_osis, count, intro
        )

    logging.info("Total records: %d", len(all_entries))

    if args.dry_run:
        logging.info("--dry-run: no files written")
        return 0

    # Write one JSON file per book
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for book_osis, filename in book_file_map.items():
        entries = by_book.get(book_osis, [])
        if not entries:
            logging.warning("[%s] No entries -- skipping output file", book_osis)
            continue

        meta = _build_meta(RESOURCE_ID, book_osis, download_date, source_hash, processing_date)
        meta["coverage"]["parameters"]["books"]["value"] = [book_osis]

        output = {"meta": meta, "data": entries}
        out_path = OUTPUT_DIR / filename
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out_path)
        logging.info("[%s] Written: %s (%d entries)", book_osis, out_path, len(entries))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
