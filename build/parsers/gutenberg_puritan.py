r"""gutenberg_puritan.py
Parse Puritan treatises from Project Gutenberg and Internet Archive into structured_text schema.

Sources:
  PG #53527  -- Charnock, Existence and Attributes of God (vol 1 + vol 2 combined)
  IA christianincom00gurn  -- Gurnall, Christian in Complete Armour (1845 combined ed.)
  IA preciousremedies00broo -- Brooks, Precious Remedies Against Satan's Devices (1832, abridged)
  IA JerimiahBurroughsTheRareJewelOfChristianContentment -- Burroughs, Rare Jewel (transcription)
  IA bruisedreedands00sibbgoog -- Sibbes, Bruised Reed and Smoking Flax (1878)

Outputs (data/structured-text/):
  charnock-existence-attributes-vol-1.json
  charnock-existence-attributes-vol-2.json
  gurnall-complete-armour.json
  brooks-precious-remedies.json
  burroughs-rare-jewel-contentment.json
  sibbes-bruised-reed.json

Source configs (sources/structured-text/{slug}/config.json):
  One config per output file.

Volume notes:
  - Charnock: PG file is "TWO VOLUMES IN ONE". Parser splits on "Volume 1"/"Volume 2" markers.
  - Gurnall: 1845 combined ed. merges original 3 vols without volume markers. One output file.
  - Brooks 1832: abridged edition -- completeness="abridged".

Usage:
    py -3 build/parsers/gutenberg_puritan.py --dry-run
    py -3 build/parsers/gutenberg_puritan.py --download
    py -3 build/parsers/gutenberg_puritan.py --parse
    py -3 build/parsers/gutenberg_puritan.py --download --parse
    py -3 build/parsers/gutenberg_puritan.py --work charnock-existence-attributes-vol-1 --parse --dry-run
    py -3 build/parsers/gutenberg_puritan.py --all

Parser quirks (for extending this file):
  Charnock TOC ambiguity: the PG file has DISCOURSE headings in both TOC and body.
    Distinguish by the {a\d+} anchor prefix -- body entries carry it, TOC entries don't.
    See DISCOURSE_ANCHOR_RE and PG_ANCHOR_RE.
  IA Chap. vs Chapter: IA files use abbreviated "Chap." in the body; TOC may use full
    "Chapter". Handle both forms when writing IA-sourced chapter heading regexes.
  Burroughs case-sensitivity: BURROUGHS_SECTION_RE must remain case-sensitive.
    Uppercase Roman numerals (I., II., ...) are main sections; lowercase (i., ii., iv.)
    are sub-points. A case-insensitive flag would merge them incorrectly.
"""

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__PROVENANCE__PROCESSING_METHOD,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.text_utils import compute_source_hash, smart_title  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)

RAW_PG_DIR = REPO_ROOT / "raw" / "gutenberg"
RAW_IA_DIR = REPO_ROOT / "raw" / "ia"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
SOURCES_DIR = REPO_ROOT / "sources" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_puritan.log"

SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_puritan.py@v1.0.0"
DOWNLOAD_DATE = "2026-04-23"

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
REQUEST_DELAY = 2.0

# PG wrapper markers
PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)

# Charnock: DISCOURSE headings and Volume markers
# Body discourse headings have a PG anchor prefix ({a23}, {b5} etc); TOC entries do not.
# Requiring the anchor distinguishes body from TOC.
CHARNOCK_DISCOURSE_RE = re.compile(r"^\s*\{[ab]\d+\}\s+DISCOURSE\s+([IVX]+)\.?\s*$")
CHARNOCK_VOL_RE = re.compile(r"^\s*Volume\s+(\d+)\s*$", re.IGNORECASE)

# Gurnall: CHAPTER headings (body uses full "CHAPTER" in ALL CAPS; TOC uses "CHAP.").
# Case-sensitive per PIPE-24: ALL CAPS signals body headings; lowercase "chapter"
# appears in prose cross-references and must not be treated as a chapter boundary.
GURNALL_CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([IVX]+)\.?\s*$")

# Brooks: CHAP. headings (abbreviated, used in body chapters 3+)
BROOKS_CHAP_RE = re.compile(r"^\s*CHAP\.\s+([IVX]+)\.?\s*$")
# Brooks: device descriptions used as chapter 1-2 headings
BROOKS_DEVICE_RE = re.compile(
    r"(?:THE\s+)?(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|"
    r"NINTH|TENTH|ELEVENTH|TWELFTH|THIRTEENTH|FOURTEENTH|FIFTEENTH|SIXTEENTH|"
    r"SEVENTEENTH|EIGHTEENTH|NINETEENTH|TWENTIETH)\s+DEVICE\s+OF\s+SATAN",
    re.IGNORECASE,
)
# Brooks: page running headers to skip
BROOKS_HEADER_RE = re.compile(r"^\s*(?:PRECIOUS\s+REMEDIES|AGAINST\s+SATAN)", re.IGNORECASE)

# Burroughs: Roman numeral section headings (I., II., ... followed by ALL-CAPS description)
# Case-sensitive: main sections use UPPERCASE Roman numerals. Lowercase (i., ii., iv., etc.)
# are sub-points within sections and must NOT be matched as top-level sections.
BURROUGHS_SECTION_RE = re.compile(
    r"^\s*((?:I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XIV|XV|XVI|XVII|XVIII|XIX|XX|V)\.)\s+([A-Z].*)"
)

# Sibbes: Chapter headings use "Chap. [Roman]." format in body (TOC uses "Chapter [Roman].")
# Title text follows on the same line after an em-dash or hyphen.
SIBBES_CHAPTER_RE = re.compile(r"^\s*Chap\.\s+([IVXL]+)\.", re.IGNORECASE)

# PG anchor tags like {a1}, {a2} to strip from content
PG_ANCHOR_RE = re.compile(r"\{a\d+\}")

# ---------------------------------------------------------------------------
# Work config
# ---------------------------------------------------------------------------

WORK_CONFIG = [
    {
        "slug": "charnock-existence-attributes-vol-1",
        "source_type": "pg",
        "pg_id": 53527,
        "raw_file": RAW_PG_DIR / "pg53527.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/53527/pg53527.txt",
        "vol_num": 1,
        "parser": "charnock",
        "title": "The Existence and Attributes of God, Vol. 1",
        "author": "Stephen Charnock",
        "author_id": "charnock-stephen",
        "author_birth_year": 1628,
        "author_death_year": 1680,
        "contributors": [],
        "original_publication_year": 1682,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Stephen Charnock (1628-1680) was an English Puritan divine. "
            "Existence and Attributes of God (published posthumously 1682) is his magnum opus, "
            "a series of discourses on the divine nature and attributes."
        ),
        "era": "post-reformation",
        "audience": "scholarly",
        "original_lang": "en",
        "work_kind": "systematic-theology",
        "source_edition": (
            "Robert Carter & Brothers, 1853; reprinted Baker Books, 1996. "
            "Project Gutenberg PG#53527 (Two Volumes in One)."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "PG file contains both volumes in one. Vol. 1 covers Discourses I-IX. "
            "Parser splits on 'Volume 1'/'Volume 2' markers. "
            "{a1}-style anchor tags stripped from content."
        ),
    },
    {
        "slug": "charnock-existence-attributes-vol-2",
        "source_type": "pg",
        "pg_id": 53527,
        "raw_file": RAW_PG_DIR / "pg53527.txt",
        "source_url": "http://www.gutenberg.org/cache/epub/53527/pg53527.txt",
        "vol_num": 2,
        "parser": "charnock",
        "title": "The Existence and Attributes of God, Vol. 2",
        "author": "Stephen Charnock",
        "author_id": "charnock-stephen",
        "author_birth_year": 1628,
        "author_death_year": 1680,
        "contributors": [],
        "original_publication_year": 1682,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Stephen Charnock (1628-1680) was an English Puritan divine. "
            "Vol. 2 covers Discourses X-XIV on Power, Holiness, Goodness, and other attributes."
        ),
        "era": "post-reformation",
        "audience": "scholarly",
        "original_lang": "en",
        "work_kind": "systematic-theology",
        "source_edition": (
            "Robert Carter & Brothers, 1853; reprinted Baker Books, 1996. "
            "Project Gutenberg PG#53527 (Two Volumes in One)."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "PG file contains both volumes in one. Vol. 2 covers Discourses X+. "
            "Parser splits on 'Volume 1'/'Volume 2' markers."
        ),
    },
    {
        "slug": "gurnall-complete-armour",
        "source_type": "ia",
        "ia_id": "christianincom00gurn",
        "raw_file": RAW_IA_DIR / "gurnall_complete_armour.txt",
        "source_url": (
            "https://archive.org/download/christianincom00gurn/"
            "christianincom00gurn_djvu.txt"
        ),
        "parser": "gurnall",
        "title": "The Christian in Complete Armour",
        "author": "William Gurnall",
        "author_id": "gurnall-william",
        "author_birth_year": 1616,
        "author_death_year": 1679,
        "contributors": ["John Campbell (reviser)"],
        "original_publication_year": 1662,
        "tradition": ["reformed", "puritan"],
        "tradition_notes": (
            "William Gurnall (1616-1679) was an English Puritan minister at Lavenham, Suffolk. "
            "The Christian in Complete Armour (1655-1662, 3 vols) is a classic exposition of "
            "Ephesians 6:10-20 on spiritual warfare."
        ),
        "era": "post-reformation",
        "audience": "pastoral",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "Carefully revised and corrected by Rev. John Campbell, D.D. "
            "London: Thomas Tegg, 1845. (Princeton Theological Seminary scan via Internet Archive.)"
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "1845 combined edition merges all 3 original volumes (1655-1662) without volume markers. "
            "OCR text from ABBYY FineReader 8.0 scan at 400 ppi. "
            "Double spaces and OCR artifacts normalized. TOC entries (CHAP.) skipped; "
            "body chapters detected by full 'CHAPTER' keyword."
        ),
    },
    {
        "slug": "brooks-precious-remedies",
        "source_type": "ia",
        "ia_id": "preciousremedies00broo",
        "raw_file": RAW_IA_DIR / "brooks_precious_remedies.txt",
        "source_url": (
            "https://archive.org/download/preciousremedies00broo/"
            "preciousremedies00broo_djvu.txt"
        ),
        "parser": "brooks",
        "title": "Precious Remedies Against Satan's Devices",
        "author": "Thomas Brooks",
        "author_id": "brooks-thomas",
        "author_birth_year": 1608,
        "author_death_year": 1680,
        "contributors": [
            "W. Smelle (abridger)",
            "Staunton Stevens Burdott (editor)",
        ],
        "original_publication_year": 1652,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Thomas Brooks (1608-1680) was an English Puritan minister. "
            "Precious Remedies Against Satan's Devices (1652) catalogues Satan's temptation "
            "strategies and provides scriptural remedies for each."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "Abridged by W. Smelle; edited by Staunton Stevens Burdott. "
            "First American Edition. New Haven: Nathan Whiting, 1832."
        ),
        "completeness": "abridged",
        "processing_method": "ocr",
        "notes": (
            "1832 abridged American edition. OCR from scanned book. "
            "Running page headers ('PRECIOUS REMEDIES') filtered from content. "
            "Device descriptions used as chapter titles."
        ),
    },
    {
        "slug": "burroughs-rare-jewel-contentment",
        "source_type": "ia",
        "ia_id": "JerimiahBurroughsTheRareJewelOfChristianContentment",
        "raw_file": RAW_IA_DIR / "burroughs_rare_jewel.txt",
        "source_url": (
            "https://archive.org/download/"
            "JerimiahBurroughsTheRareJewelOfChristianContentment/"
            "Jerimiah%20Burroughs%20The%20Rare%20Jewel%20of%20Christian%20Contentment_djvu.txt"
        ),
        "parser": "burroughs",
        "title": "The Rare Jewel of Christian Contentment",
        "author": "Jeremiah Burroughs",
        "author_id": "burroughs-jeremiah",
        "author_birth_year": 1600,
        "author_death_year": 1646,
        "contributors": [],
        "original_publication_year": 1648,
        "tradition": ["reformed", "puritan", "nonconformist"],
        "tradition_notes": (
            "Jeremiah Burroughs (1600-1646) was an English Puritan Congregationalist minister. "
            "The Rare Jewel of Christian Contentment (1648) expounds Philippians 4:11 on "
            "learning contentment in all circumstances."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "Modern transcription uploaded to Internet Archive; edition date unknown. "
            "Work originally published 1648."
        ),
        "completeness": "full",
        "processing_method": "automated",
        "notes": (
            "Source appears to be a modern transcription (not scanned OCR). "
            "Structure uses ALL CAPS numbered sections (I., II., III.) as primary divisions."
        ),
    },
    {
        "slug": "sibbes-bruised-reed",
        "source_type": "ia",
        "ia_id": "bruisedreedands00sibbgoog",
        "raw_file": RAW_IA_DIR / "sibbes_bruised_reed.txt",
        "source_url": (
            "https://archive.org/download/bruisedreedands00sibbgoog/"
            "bruisedreedands00sibbgoog_djvu.txt"
        ),
        "parser": "sibbes",
        "title": "The Bruised Reed and Smoking Flax",
        "author": "Richard Sibbes",
        "author_id": "sibbes-richard",
        "author_birth_year": 1577,
        "author_death_year": 1635,
        "contributors": ["Alexander Beith (introductory essay)"],
        "original_publication_year": 1630,
        "tradition": ["reformed", "puritan"],
        "tradition_notes": (
            "Richard Sibbes (1577-1635) was an English Puritan divine. "
            "The Bruised Reed and Smoking Flax (1630) expounds Matthew 12:20, "
            "showing Christ's tender care for weak and struggling believers."
        ),
        "era": "post-reformation",
        "audience": "lay",
        "original_lang": "en",
        "work_kind": "treatise",
        "source_edition": (
            "With introductory essay by Alexander Beith, D.D. "
            "Edinburgh: Maclaren & Macniven; London: J. Nisbet & Co., 1878. "
            "Google Books digitization via Internet Archive."
        ),
        "completeness": "full",
        "processing_method": "ocr",
        "notes": (
            "1878 edition with Beith introductory essay included as a preface section. "
            "Google Books OCR. Chapter headings 'Chapter I.' through chapter IX."
        ),
    },
]


def _validate_configs() -> None:
    for cfg in WORK_CONFIG:
        slug = cfg["slug"]
        for tradition in cfg.get("tradition", []):
            assert tradition in STRUCTURED_TEXT__META__TRADITION, f"{slug}: invalid tradition value {tradition!r}"
        assert (era := cfg["era"]) in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era value {era!r}"
        assert (audience := cfg["audience"]) in STRUCTURED_TEXT__META__AUDIENCE, (
            f"{slug}: invalid audience value {audience!r}"
        )
        assert (work_kind := cfg["work_kind"]) in STRUCTURED_TEXT__DATA__WORK_KIND, (
            f"{slug}: invalid work_kind value {work_kind!r}"
        )
        assert (completeness := cfg["completeness"]) in STRUCTURED_TEXT__META__COMPLETENESS, (
            f"{slug}: invalid completeness value {completeness!r}"
        )
        assert (
            processing_method := cfg["processing_method"]
        ) in STRUCTURED_TEXT__META__PROVENANCE__PROCESSING_METHOD, (
            f"{slug}: invalid processing_method value {processing_method!r}"
        )


_validate_configs()

# Build lookup by slug
_WORK_BY_SLUG = {w["slug"]: w for w in WORK_CONFIG}


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII only, PY-05) and append to log list."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

_RETRY_STATUSES = {429, 500, 502, 503}
_RETRY_DELAYS = [2.0, 4.0, 8.0]


def download_url(url: str, out_path: Path, log_lines: list) -> None:
    """Download URL to out_path with OCD User-Agent. Follows redirects. Retries."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt, delay in enumerate([0.0] + _RETRY_DELAYS, start=1):
        if delay:
            log(f"  Retry delay {delay}s...", log_lines)
            time.sleep(delay)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            out_path.write_bytes(data)
            size_kb = len(data) // 1024
            log(f"  Downloaded: {size_kb} KB -> {out_path.name}", log_lines)
            return
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code not in _RETRY_STATUSES:
                raise
            log(f"  HTTP {exc.code} attempt {attempt}/4", log_lines)
        except urllib.error.URLError as exc:
            last_exc = exc
            log(f"  URLError attempt {attempt}/4: {exc.reason}", log_lines)
    raise last_exc


def ensure_downloaded(cfg: dict, log_lines: list) -> bool:
    """Download raw source file if not already cached. Returns True on success."""
    raw_path = cfg["raw_file"]
    if raw_path.exists():
        size_kb = raw_path.stat().st_size // 1024
        log(f"  Cached: {raw_path.name} ({size_kb} KB)", log_lines)
        return True
    log(f"  Downloading: {cfg['source_url'][:80]}...", log_lines)
    try:
        download_url(cfg["source_url"], raw_path, log_lines)
        return True
    except Exception as exc:
        log(f"  ERROR downloading {cfg['slug']}: {type(exc).__name__}: {exc}", log_lines)
        return False


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


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


def strip_ia_header(text: str) -> list:
    """Strip common IA/Google Books OCR header lines. Returns body lines.

    IA djvu.txt files often start with Google Books terms-of-service text
    (typically ~20 lines), followed by the title page.
    Strategy: strip leading lines matching known header patterns.
    """
    lines = text.splitlines()
    header_re = re.compile(
        r"(?i)("
        r"digitized\s+by|google\s+book|books\.google|internet\s+archive"
        r"|public\s+domain|copyright\s+infringement|maintain\s+attribution"
        r"|keep\s+it\s+legal|about\s+google\s+book"
        r")"
    )
    # Find last line matching header patterns within the first 25 lines
    cutoff = 0
    for i, l in enumerate(lines[:25]):
        if l.strip() and header_re.search(l):
            cutoff = i + 1
    return lines[cutoff:]


def normalize_ocr_spaces(line: str) -> str:
    """Collapse OCR double-spaces to single spaces."""
    return re.sub(r" {2,}", " ", line)


def clean_content_block(text: str, strip_pg_anchors: bool = True) -> str:
    """Normalize whitespace and strip PG anchor tags from a content block."""
    if strip_pg_anchors:
        text = PG_ANCHOR_RE.sub("", text)
    text = " ".join(text.split())
    return text


def gather_paragraphs(lines: list, start: int, stop: int, strip_pg_anchors: bool = True) -> list:
    """Collect blank-line-separated paragraphs from lines[start:stop]."""
    paragraphs = []
    current_block: list = []

    for i in range(start, min(stop, len(lines))):
        stripped = lines[i].rstrip()
        content = stripped.strip()

        if not content:
            if current_block:
                text = clean_content_block(" ".join(current_block), strip_pg_anchors)
                if text:
                    paragraphs.append(decode_pg_inline_markup(text))
                current_block = []
        else:
            current_block.append(content)

    if current_block:
        text = clean_content_block(" ".join(current_block), strip_pg_anchors)
        if text:
            paragraphs.append(decode_pg_inline_markup(text))

    return paragraphs


def gather_paragraphs_ocr(lines: list, start: int, stop: int, skip_re: re.Pattern = None) -> list:
    """Like gather_paragraphs but normalizes OCR double-spaces and optionally skips lines.

    skip_re: if provided, lines fully matching this pattern are dropped before parsing.
    """
    filtered: list = []
    for i in range(start, min(stop, len(lines))):
        l = normalize_ocr_spaces(lines[i].rstrip())
        stripped = l.strip()
        if skip_re and stripped and skip_re.match(stripped):
            continue
        filtered.append(l)

    paragraphs = []
    current_block: list = []
    for l in filtered:
        content = l.strip()
        if not content:
            if current_block:
                text = " ".join(current_block)
                text = " ".join(text.split())
                if text:
                    paragraphs.append(decode_pg_inline_markup(text))
                current_block = []
        else:
            current_block.append(content)

    if current_block:
        text = " ".join(current_block)
        text = " ".join(text.split())
        if text:
            paragraphs.append(decode_pg_inline_markup(text))

    return paragraphs


def word_count(blocks: list) -> int:
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Meta envelope builder
# ---------------------------------------------------------------------------


def build_meta_envelope(cfg: dict, source_hash: str) -> dict:
    """Build the meta envelope for a structured_text output file from a work config."""
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_rel = cfg["raw_file"].relative_to(REPO_ROOT).as_posix()

    return {
        "id": cfg["slug"],
        "title": cfg["title"],
        "author": cfg["author"],
        "author_id": cfg.get("author_id"),
        "author_birth_year": cfg["author_birth_year"],
        "author_death_year": cfg["author_death_year"],
        "contributors": normalize_contributors(cfg.get("contributors", [])),
        "original_publication_year": cfg["original_publication_year"],
        "language": "en",
        "original_language": cfg["original_lang"],
        "tradition": cfg["tradition"],
        "tradition_notes": cfg.get("tradition_notes"),
        "era": cfg["era"],
        "audience": cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": cfg.get("completeness", "full"),
        "provenance": {
            "source_url": cfg["source_url"],
            "source_format": (
                "plain text (UTF-8)"
                if cfg["source_type"] == "pg"
                else "plain text (OCR from IA scan)"
            ),
            "source_edition": cfg["source_edition"],
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": cfg.get("processing_method", "automated"),
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": processing_date,
            "source_type": (
                "gutenberg_txt" if cfg["source_type"] == "pg" else "ia_ocr_txt"
            ),
            "source_file": raw_rel,
            "notes": append_pg_inline_markup_note(cfg.get("notes")),
        },
    }


def write_source_config(cfg: dict, source_hash: str) -> None:
    """Write sources/structured-text/{slug}/config.json."""
    config_dir = SOURCES_DIR / cfg["slug"]
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    raw_rel = cfg["raw_file"].relative_to(REPO_ROOT).as_posix()

    source_config = {
        "resource_id": cfg["slug"],
        "title": cfg["title"],
        "author": cfg["author"],
        "author_id": cfg.get("author_id"),
        "author_birth_year": cfg["author_birth_year"],
        "author_death_year": cfg["author_death_year"],
        "contributors": cfg.get("contributors", []),
        "original_publication_year": cfg["original_publication_year"],
        "language": "en",
        "original_language": cfg["original_lang"],
        "tradition": cfg["tradition"],
        "era": cfg["era"],
        "audience": cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "work_kind": cfg["work_kind"],
        "source_url": cfg["source_url"],
        "source_format": (
            "plain text (UTF-8)"
            if cfg["source_type"] == "pg"
            else "plain text (OCR from IA scan)"
        ),
        "source_edition": cfg["source_edition"],
        "source_hash": source_hash,
        "source_type": (
            "gutenberg_txt" if cfg["source_type"] == "pg" else "ia_ocr_txt"
        ),
        "source_file": raw_rel,
        "download_date": DOWNLOAD_DATE,
        "output_file": f"data/structured-text/{cfg['slug']}.json",
        "notes": cfg.get("notes"),
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(source_config, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Quality stats (PIPE-02)
# ---------------------------------------------------------------------------


def print_quality_stats(data: dict, label: str, log_lines: list) -> None:
    sections = data.get("sections", [])
    total_sections = 0
    total_blocks = 0
    all_word_counts: list = []

    def traverse(sec_list: list) -> None:
        nonlocal total_sections, total_blocks
        for sec in sec_list:
            total_sections += 1
            blocks = sec.get("content_blocks", [])
            total_blocks += len(blocks)
            all_word_counts.append(sec.get("word_count", 0))
            traverse(sec.get("children", []))

    traverse(sections)

    all_word_counts.sort()
    log(f"  {label}: {total_sections} sections, {total_blocks} blocks", log_lines)
    if all_word_counts:
        mid = len(all_word_counts) // 2
        log(
            f"  Word counts: min={all_word_counts[0]}, "
            f"median={all_word_counts[mid]}, max={all_word_counts[-1]}",
            log_lines,
        )


def check_structural_plausibility(data: dict, slug: str, log_lines: list) -> bool:
    """Warn if one top-level section dominates the word count in a multi-section work.

    If a single section holds >50% of all words in a work with >=5 sections, it
    almost always means the heading regex matched TOC entries (which have no prose)
    instead of body headings, funnelling all real content into the last section.
    Returns True if plausible, False if a suspicious outlier is found.

    The 50%/5-section threshold avoids false positives from legitimately uneven
    works (e.g. Gurnall's 212 chapters with genuine length variation).
    """
    sections = data.get("sections", [])
    if len(sections) < 5:
        return True

    wcs = [s.get("word_count", 0) for s in sections]
    total = sum(wcs)
    if total == 0:
        return True

    for s, wc in zip(sections, wcs, strict=True):
        share = wc / total
        if share > 0.50:
            log(
                f"  WARNING: {slug} -- section '{s['label']}' holds {share:.0%} of all words"
                f" (>50% in a {len(sections)}-section work).",
                log_lines,
            )
            log(
                "  Likely cause: heading regex matched TOC entries instead of body headings.",
                log_lines,
            )
            # Print all sections so the pattern (many near-zero, one giant) is visible
            log("  Section distribution:", log_lines)
            for sec, sec_wc in zip(sections, wcs, strict=True):
                log(f"    {sec['label']}: {sec_wc} words", log_lines)
            log(
                "  Output blocked -- fix the heading regex before re-running.",
                log_lines,
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Parser: Charnock (Existence and Attributes of God)
# ---------------------------------------------------------------------------


def _split_charnock_volumes(body_lines: list) -> tuple:
    """Split combined PG body into Vol 1 and Vol 2 line ranges.

    Returns (vol1_lines, vol2_lines).
    Vol 2 starts at the second 'Volume N' marker.
    """
    vol_starts = []
    for i, l in enumerate(body_lines):
        if CHARNOCK_VOL_RE.match(l.strip()):
            vol_starts.append(i)

    if len(vol_starts) < 2:
        raise ValueError(
            f"Expected 2 Volume markers in Charnock PG file, found {len(vol_starts)}"
        )

    vol1_end = vol_starts[1]
    return body_lines[:vol1_end], body_lines[vol_starts[1]:]


def _find_first_discourse(body_lines: list) -> int:
    """Return line index of first DISCOURSE heading (skips front matter)."""
    for i, l in enumerate(body_lines):
        if CHARNOCK_DISCOURSE_RE.match(l.strip()):
            return i
    return 0


def parse_charnock(body_lines: list, vol_num: int, log_lines: list) -> dict:
    """Parse one Charnock volume from body lines.

    Structure: DISCOURSE [Roman]. (with PG anchor prefix) / title (next non-blank line) / paragraphs.

    Vol 1 has front matter (TOC + Charnock biography) in the first ~940 lines. One TOC entry
    for DISCOURSE VI happens to have a PG anchor and would match the regex; skipping the first
    500 lines excludes it without risking any real discourse headings.
    """
    work_id = f"charnock-existence-attributes-vol-{vol_num}"

    # Skip front matter for vol 1; vol 2 has no anchor-tagged TOC entries
    start_scan = 500 if vol_num == 1 else 0

    # Find discourse events: (line_idx, roman_numeral, title)
    discourse_events = []
    i = start_scan
    while i < len(body_lines):
        m = CHARNOCK_DISCOURSE_RE.match(body_lines[i].strip())
        if m:
            roman = m.group(1)
            # Title is the next non-blank line
            j = i + 1
            while j < len(body_lines) and not body_lines[j].strip():
                j += 1
            title = body_lines[j].strip().rstrip(".") if j < len(body_lines) else ""
            # Strip PG anchors from title
            title = PG_ANCHOR_RE.sub("", title).strip()
            discourse_events.append((i, roman, title))
        i += 1

    log(f"  Vol {vol_num}: found {len(discourse_events)} discourse headings", log_lines)
    if discourse_events:
        for idx, rom, ttl in discourse_events[:4]:
            log(f"    DISCOURSE {rom}: {ttl[:60]}", log_lines)

    if not discourse_events:
        raise ValueError(f"No DISCOURSE headings found in Charnock Vol {vol_num}")

    sections = []
    for d_idx, (disc_line, roman, title) in enumerate(discourse_events):
        next_disc = discourse_events[d_idx + 1][0] if d_idx + 1 < len(discourse_events) else len(body_lines)
        paragraphs = gather_paragraphs(body_lines, disc_line + 1, next_disc, strip_pg_anchors=True)
        wc = word_count(paragraphs)
        sections.append(
            {
                "section_type": "chapter",
                "label": f"Discourse {roman}",
                "title": title if title else None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            }
        )
        log(f"  Discourse {roman}: {len(paragraphs)} paragraphs, {wc} words", log_lines)

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Vol {vol_num} total: {len(sections)} discourses, {total_words} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "systematic-theology",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Gurnall (Christian in Complete Armour)
# ---------------------------------------------------------------------------


def parse_gurnall(body_lines: list, log_lines: list) -> dict:
    """Parse Gurnall 1845 combined edition.

    The TOC uses abbreviated 'CHAP.' headings. The body uses full 'CHAPTER'.
    Normalize OCR double-spaces before matching.
    Skip running headers.
    """
    work_id = "gurnall-complete-armour"

    # Normalize lines for heading detection
    norm_lines = [normalize_ocr_spaces(l) for l in body_lines]

    # Find body CHAPTER headings (not TOC CHAP. entries)
    chapter_events = []
    for i, l in enumerate(norm_lines):
        stripped = l.strip()
        m = GURNALL_CHAPTER_RE.match(stripped)
        if m:
            roman = m.group(1).upper()
            # Title: next non-blank line
            j = i + 1
            while j < len(norm_lines) and not norm_lines[j].strip():
                j += 1
            title_parts = []
            if j < len(norm_lines):
                t = normalize_ocr_spaces(norm_lines[j]).strip()
                # Collect continuation lines (short lines that continue heading)
                title_parts.append(t)
                # Don't consume beyond one line for title
            title = title_parts[0].rstrip(".").strip() if title_parts else ""
            chapter_events.append((i, roman, title))

    log(f"  Found {len(chapter_events)} CHAPTER headings", log_lines)
    if not chapter_events:
        raise ValueError("No CHAPTER headings found in Gurnall")

    # Running header pattern to skip
    skip_re = re.compile(
        r"^(CHRISTIAN\s+IN\s+COMPLETE\s+ARMOUR|COMPLETE\s+ARMOUR"
        r"|A\s+TREATISE\s+ON\s+THE\s+SAINTS)",
        re.IGNORECASE,
    )

    sections = []
    for c_idx, (ch_line, roman, title) in enumerate(chapter_events):
        next_ch = chapter_events[c_idx + 1][0] if c_idx + 1 < len(chapter_events) else len(norm_lines)
        paragraphs = gather_paragraphs_ocr(norm_lines, ch_line + 1, next_ch, skip_re=skip_re)
        wc = word_count(paragraphs)
        sections.append(
            {
                "section_type": "chapter",
                "label": f"Chapter {roman}",
                "title": title if title else None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            }
        )

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Gurnall: {len(sections)} chapters, {total_words} words", log_lines)
    for sec in sections[:3]:
        log(f"  {sec['label']}: {sec['word_count']} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "treatise",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Brooks (Precious Remedies)
# ---------------------------------------------------------------------------


def _ordinal_to_int(ordinal: str) -> int:
    """Convert ordinal string to int (FIRST->1, SECOND->2, etc.)."""
    mapping = {
        "FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5,
        "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9, "TENTH": 10,
        "ELEVENTH": 11, "TWELFTH": 12, "THIRTEENTH": 13, "FOURTEENTH": 14,
        "FIFTEENTH": 15, "SIXTEENTH": 16, "SEVENTEENTH": 17, "EIGHTEENTH": 18,
        "NINETEENTH": 19, "TWENTIETH": 20,
    }
    return mapping.get(ordinal.upper(), 0)


def parse_brooks(body_lines: list, log_lines: list) -> dict:
    """Parse Brooks 1832 abridged edition.

    Chapters detected by 'CHAP. [Roman].' markers (ch.3+) OR
    'THE [ORDINAL] DEVICE OF SATAN' descriptions (ch.1-2).
    Running page headers ('PRECIOUS REMEDIES') skipped.
    OCR double-spaces normalized.
    """
    work_id = "brooks-precious-remedies"
    norm_lines = [normalize_ocr_spaces(l) for l in body_lines]

    # Detect chapter events: (line_idx, chapter_num, title_lines)
    # Strategy: collect lines matching CHAP. or DEVICE patterns
    events: list = []  # (line_idx, label, title_text)

    i = 0
    while i < len(norm_lines):
        stripped = norm_lines[i].strip()

        # Skip running page headers
        if BROOKS_HEADER_RE.match(stripped):
            i += 1
            continue

        # CHAP. [Roman]. heading
        chap_m = BROOKS_CHAP_RE.match(stripped)
        if chap_m:
            roman = chap_m.group(1)
            # Collect title from next non-blank lines
            j = i + 1
            title_parts = []
            while j < len(norm_lines):
                t = norm_lines[j].strip()
                if not t:
                    j += 1
                    continue
                if BROOKS_HEADER_RE.match(t) or BROOKS_CHAP_RE.match(t):
                    break
                # Collect up to 3 lines for title (device descriptions wrap)
                title_parts.append(t)
                j += 1
                if len(title_parts) >= 3:
                    break
            title = " ".join(title_parts).rstrip(".")
            events.append((i, f"Chapter {roman}", title))
            i += 1
            continue

        # Device description (for chapters without CHAP. marker)
        dev_m = BROOKS_DEVICE_RE.search(stripped)
        if dev_m and not events:  # Only use as fallback for first chapters
            ordinal_str = dev_m.group(1)
            label = f"Chapter {_ordinal_to_int(ordinal_str)}"
            # Use this line + next line as title
            title_parts = [stripped]
            j = i + 1
            while j < len(norm_lines):
                t = norm_lines[j].strip()
                if not t or BROOKS_HEADER_RE.match(t) or BROOKS_CHAP_RE.match(t):
                    break
                title_parts.append(t)
                j += 1
                if len(title_parts) >= 3:
                    break
            title = " ".join(title_parts).rstrip(".")
            events.append((i, label, title))
            i += 1
            continue

        i += 1

    # Fallback: if very few events found, scan for device descriptions more broadly
    if len(events) < 3:
        events = []
        for i, l in enumerate(norm_lines):
            stripped = l.strip()
            if BROOKS_HEADER_RE.match(stripped):
                continue
            dev_m = BROOKS_DEVICE_RE.search(stripped)
            if dev_m:
                ordinal_str = dev_m.group(1)
                num = _ordinal_to_int(ordinal_str)
                label = f"Device {num}: {smart_title(ordinal_str)}"
                title_parts = [stripped]
                for j in range(i + 1, min(i + 4, len(norm_lines))):
                    t = norm_lines[j].strip()
                    if not t or BROOKS_HEADER_RE.match(t):
                        break
                    title_parts.append(t)
                title = " ".join(title_parts).rstrip(".")
                events.append((i, label, title))

    log(f"  Brooks: found {len(events)} chapter/device events", log_lines)
    if not events:
        raise ValueError("No chapter events found in Brooks")

    sections = []
    for e_idx, (ev_line, label, title) in enumerate(events):
        next_ev = events[e_idx + 1][0] if e_idx + 1 < len(events) else len(norm_lines)
        paragraphs = gather_paragraphs_ocr(norm_lines, ev_line + 1, next_ev, skip_re=BROOKS_HEADER_RE)
        wc = word_count(paragraphs)
        sections.append(
            {
                "section_type": "chapter",
                "label": label,
                "title": title[:200] if title else None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            }
        )
        log(f"  {label}: {wc} words", log_lines)

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Brooks total: {len(sections)} chapters, {total_words} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "treatise",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Burroughs (Rare Jewel of Christian Contentment)
# ---------------------------------------------------------------------------


def parse_burroughs(body_lines: list, log_lines: list) -> dict:
    """Parse Burroughs modern transcription.

    Source structure: TOC at start, then body with Roman numeral ALL CAPS sections.
    The body starts after the TOC (after the first substantial ALL CAPS heading).
    Sections are numbered: I., II., III., etc.

    Strategy: skip TOC/front matter (first ~350 lines which end at an empty line
    before the first body heading), then detect Roman numeral sections.
    """
    work_id = "burroughs-rare-jewel-contentment"

    # Find the start of body text (skip TOC)
    # TOC ends and body begins when we see the first Roman numeral heading after ~line 350
    body_start = 0
    for i, l in enumerate(body_lines):
        m = BURROUGHS_SECTION_RE.match(l.strip())
        if m and i > 300:
            body_start = i
            break

    if body_start == 0:
        # Fallback: use start of all lines
        body_start = 0

    log(f"  Burroughs: body starts at line {body_start}", log_lines)

    # Find section events
    section_events: list = []
    i = body_start
    while i < len(body_lines):
        stripped = body_lines[i].strip()
        m = BURROUGHS_SECTION_RE.match(stripped)
        if m:
            roman_label = m.group(1).rstrip(".")
            title_text = m.group(2).strip()
            # Multi-line headings: check next lines
            j = i + 1
            extra: list = []
            while j < len(body_lines) and len(extra) < 2:
                nxt = body_lines[j].strip()
                if not nxt:
                    break
                # Is it a continuation (ALL CAPS, no Roman numeral prefix)?
                if nxt == nxt.upper() and len(nxt) > 5 and not BURROUGHS_SECTION_RE.match(nxt):
                    extra.append(nxt)
                    j += 1
                else:
                    break
            full_title = " ".join([title_text] + extra).rstrip(".")
            section_events.append((i, roman_label, full_title))
        i += 1

    log(f"  Burroughs: found {len(section_events)} Roman numeral sections", log_lines)

    if not section_events:
        raise ValueError("No Roman numeral sections found in Burroughs")

    sections = []
    for s_idx, (sec_line, roman_label, title) in enumerate(section_events):
        next_sec = section_events[s_idx + 1][0] if s_idx + 1 < len(section_events) else len(body_lines)
        paragraphs = gather_paragraphs(body_lines, sec_line + 1, next_sec, strip_pg_anchors=False)
        wc = word_count(paragraphs)
        sections.append(
            {
                "section_type": "section",
                "label": roman_label,
                "title": title[:200] if title else None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            }
        )

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Burroughs total: {len(sections)} sections, {total_words} words", log_lines)
    for sec in sections[:3]:
        log(f"  {sec['label']}: {sec['word_count']} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "treatise",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Parser: Sibbes (The Bruised Reed)
# ---------------------------------------------------------------------------


def parse_sibbes(body_lines: list, log_lines: list) -> dict:
    """Parse Sibbes 1878 edition with Beith introductory essay.

    Structure: Introductory Essay (before Chap. I), then Chap. I through Chap. XXVIII.
    Chapter headings: 'Chap. I. - Title text...' format (title on same line after dash).
    OCR running headers 'Introductory Essay.' filtered from essay section.
    """
    work_id = "sibbes-bruised-reed"

    # Running header pattern in essay section
    essay_header_re = re.compile(r"(?i)^introductory\s+essay", re.IGNORECASE)

    # Find chapter events: "Chap. [Roman]. - [title...]"
    chapter_events: list = []
    for i, l in enumerate(body_lines):
        norm = normalize_ocr_spaces(l.strip())
        m = SIBBES_CHAPTER_RE.match(norm)
        if m:
            roman = m.group(1).upper()
            # Title follows the chapter marker on the same line, after a dash/bullet
            rest = norm[m.end():].strip()
            # Strip leading dash/bullet characters and OCR artifacts
            rest = re.sub(r"^[\-\u2012\u2013\u2014\^]+\s*", "", rest)
            title = rest.rstrip(".").strip()
            chapter_events.append((i, roman, title))

    log(f"  Sibbes: found {len(chapter_events)} chapter headings", log_lines)

    # Find introductory essay (before first chapter)
    first_ch_line = chapter_events[0][0] if chapter_events else len(body_lines)

    # Find start of essay (look for "INTRODUCTORY ESSAY" heading)
    essay_start = 0
    for i, l in enumerate(body_lines[:first_ch_line]):
        if essay_header_re.match(l.strip()):
            essay_start = i
            break

    sections = []

    # Introductory essay as preface; skip running "Introductory Essay." page headers
    essay_lines = body_lines[essay_start:first_ch_line]
    if essay_lines:
        essay_paragraphs = gather_paragraphs_ocr(essay_lines, 0, len(essay_lines), skip_re=essay_header_re)
        if essay_paragraphs:
            wc = word_count(essay_paragraphs)
            sections.append(
                {
                    "section_type": "preface",
                    "label": "Introductory Essay",
                    "title": "Introductory Essay by Alexander Beith",
                    "content_blocks": essay_paragraphs,
                    "scripture_references": [],
                    "word_count": wc,
                    "children": [],
                }
            )
            log(f"  Introductory Essay: {wc} words", log_lines)

    # Chapters
    if not chapter_events:
        raise ValueError("No chapters found in Sibbes")

    for c_idx, (ch_line, roman, title) in enumerate(chapter_events):
        next_ch = chapter_events[c_idx + 1][0] if c_idx + 1 < len(chapter_events) else len(body_lines)
        paragraphs = gather_paragraphs_ocr(body_lines, ch_line + 1, next_ch)
        wc = word_count(paragraphs)
        sections.append(
            {
                "section_type": "chapter",
                "label": f"Chapter {roman}",
                "title": title if title else None,
                "content_blocks": paragraphs,
                "scripture_references": [],
                "word_count": wc,
                "children": [],
            }
        )
        log(f"  Chapter {roman}: {wc} words", log_lines)

    total_words = sum(s["word_count"] for s in sections)
    log(f"  Sibbes total: {len(sections)} sections, {total_words} words", log_lines)

    return {
        "work_id": work_id,
        "work_kind": "treatise",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Work runner
# ---------------------------------------------------------------------------


def run_work(cfg: dict, dry_run: bool, log_lines: list) -> bool:
    """Parse one work and write output file + source config. Returns True on success."""
    slug = cfg["slug"]
    raw_path = cfg["raw_file"]

    log(f"\n--- {slug} ---", log_lines)
    log(f"  Source: {raw_path.name}", log_lines)

    if not raw_path.exists():
        log(f"  ERROR: {raw_path} not found -- run with --download first", log_lines)
        return False

    source_hash = compute_source_hash(raw_path)
    log(f"  Hash: {source_hash}", log_lines)

    text = raw_path.read_text(encoding="utf-8", errors="replace")

    # Extract body lines per source type
    try:
        if cfg["source_type"] == "pg":
            body_lines = strip_pg_wrapper(text)
        else:
            body_lines = strip_ia_header(text)
    except ValueError as exc:
        log(f"  ERROR stripping header: {exc}", log_lines)
        return False

    log(f"  Body lines: {len(body_lines)}", log_lines)

    # Dispatch to appropriate parser
    parser_name = cfg["parser"]
    try:
        if parser_name == "charnock":
            vol1_lines, vol2_lines = _split_charnock_volumes(body_lines)
            vol_num = cfg["vol_num"]
            vol_lines = vol1_lines if vol_num == 1 else vol2_lines
            data = parse_charnock(vol_lines, vol_num, log_lines)
        elif parser_name == "gurnall":
            data = parse_gurnall(body_lines, log_lines)
        elif parser_name == "brooks":
            data = parse_brooks(body_lines, log_lines)
        elif parser_name == "burroughs":
            data = parse_burroughs(body_lines, log_lines)
        elif parser_name == "sibbes":
            data = parse_sibbes(body_lines, log_lines)
        else:
            log(f"  ERROR: Unknown parser '{parser_name}'", log_lines)
            return False
    except Exception as exc:
        log(f"  ERROR parsing {slug}: {type(exc).__name__}: {exc}", log_lines)
        return False

    # Validate section count
    section_count = len(data.get("sections", []))
    if section_count < 5:
        log(f"  ERROR: Only {section_count} top-level sections -- expected >= 5", log_lines)
        return False

    print_quality_stats(data, slug, log_lines)
    if not check_structural_plausibility(data, slug, log_lines):
        return False

    meta = build_meta_envelope(cfg, source_hash)
    output = {"meta": meta, "data": data}

    if dry_run:
        log(f"  DRY RUN -- {section_count} sections, no files written", log_lines)
        first_sec = data["sections"][0]
        log(
            f"  First section: {first_sec['label']} -- {first_sec['word_count']} words",
            log_lines,
        )
        return True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{slug}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"  Written: {out_path}", log_lines)

    write_source_config(cfg, source_hash)
    log(f"  Config: sources/structured-text/{slug}/config.json", log_lines)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Puritan treatises from PG/IA into structured_text JSON"
    )
    parser.add_argument(
        "--work",
        choices=list(_WORK_BY_SLUG.keys()),
        help="Process one work only",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download raw source files (skip if already cached)",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse cached files and write output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse but do not write output files",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all works (default when --work not specified)",
    )
    args = parser.parse_args()

    # Default: if neither --download nor --parse nor --all, show help
    if not any([args.download, args.parse, args.dry_run, args.all]):
        parser.print_help()
        sys.exit(0)

    log_lines: list = []
    start_time = time.time()
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    mode = "DRY RUN" if args.dry_run else "LIVE RUN"
    log(f"[{run_ts}] gutenberg_puritan -- {mode}", log_lines)

    # Determine which works to process
    if args.work:
        works_to_process = [_WORK_BY_SLUG[args.work]]
    else:
        works_to_process = WORK_CONFIG

    log(f"Works: {', '.join(w['slug'] for w in works_to_process)}", log_lines)

    # Download phase
    if args.download:
        log("\n=== DOWNLOAD PHASE ===", log_lines)
        # Track which raw files have already been downloaded (avoid re-downloading shared files)
        downloaded_files: set = set()
        download_errors = 0
        for cfg in works_to_process:
            raw_path = cfg["raw_file"]
            if str(raw_path) in downloaded_files:
                log(f"  Skipping {cfg['slug']} -- shared file already downloaded", log_lines)
                continue
            ok = ensure_downloaded(cfg, log_lines)
            if ok:
                downloaded_files.add(str(raw_path))
            else:
                download_errors += 1
            # Delay between downloads (skip for same file)
            if ok and len(downloaded_files) > 1:
                time.sleep(REQUEST_DELAY)
        if download_errors:
            log(f"\nDownload phase: {download_errors} errors", log_lines)
            if not args.parse:
                sys.exit(1)

    # Parse phase
    if args.parse or args.dry_run:
        log("\n=== PARSE PHASE ===", log_lines)
        successes = 0
        failures = 0
        for cfg in works_to_process:
            ok = run_work(cfg, args.dry_run, log_lines)
            if ok:
                successes += 1
            else:
                failures += 1

        elapsed = time.time() - start_time
        log(
            f"\nDone -- {successes} succeeded, {failures} failed, {elapsed:.1f}s",
            log_lines,
        )

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n\n")

        if failures > 0:
            sys.exit(1)
    else:
        # Download-only run
        elapsed = time.time() - start_time
        dl_ok = len(downloaded_files) if args.download else 0
        dl_err = download_errors if args.download else 0
        log(f"\nDownload done -- {dl_ok} ok, {dl_err} errors, {elapsed:.1f}s", log_lines)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n\n")


if __name__ == "__main__":
    main()
