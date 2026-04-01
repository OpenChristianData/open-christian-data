"""sword_commentary.py
Parser for SWORD zCom commentary modules: Barnes, CalvinCommentaries, Wesley.

Reads extracted SWORD module files from raw/sword_modules/{module}/
and outputs per-book JSON files to data/commentaries/{commentary_id}/
following the OCD commentary schema v2.1.0.

Format decoded from binary inspection (2026-03-28):
  BZS (block index): 12-byte entries struct.unpack('<III') = (offset, compressed_len, uncompressed_len)
  BZV (verse index): 10-byte entries struct.unpack('<IIH') = (block_num, verse_start, verse_len)
  BZZ (data):        zlib-compressed blocks; use zlib.decompress() (standard zlib with header)
  BlockType BOOK  -> file prefix 'b' (nt.bzs, nt.bzv, nt.bzz)
  BlockType CHAPTER -> file prefix 'c' (nt.czs, nt.czv, nt.czz)

Positional index formula (from pysword BibleStructure):
  book_offset = 2 + sum(book.size for earlier books in testament)
  book.size   = sum(chapter_lengths) + len(chapter_lengths) + 1
  chapter_offset(ch_idx) = sum(chapter_lengths[:ch_idx]) + ch_idx + 2
  bzv_index   = book_offset + chapter_offset(chapter - 1) + (verse - 1)
  where chapter and verse are 1-indexed

pysword confirmed this with BZV[4] = Matt 1:1 -> (2 + 0) + (0 + 1 + 1) + 0 = 4

Usage:
    py -3 build/parsers/sword_commentary.py --module barnes --dry-run
    py -3 build/parsers/sword_commentary.py --module calvin
    py -3 build/parsers/sword_commentary.py --module wesley
    py -3 build/parsers/sword_commentary.py --all
"""

import argparse
import hashlib
import json
import logging
import re
import struct
import sys
import time
import traceback
import zlib
from datetime import datetime, timezone
from pathlib import Path

# Normalizer lives in build/lib/ alongside other shared pipeline libs.
# Import here so the module-level import fails fast rather than mid-run.
_REPO_ROOT_FOR_IMPORT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT_FOR_IMPORT))
from build.lib.bible_ref_normalizer import parse_thml_refs  # noqa: E402

# ---------------------------------------------------------------------------
# OSIS ref filter
# ---------------------------------------------------------------------------

def _filter_osis_refs(refs: list[str]) -> list[str]:
    """
    Drop cross-reference strings that fail OSIS existence validation.

    This catches cases where the SWORD source module uses non-standard
    numbering (e.g. Calvin's Harmony of the Gospels uses section numbers
    like 'Matt.45.24' which are not valid biblical chapter:verse refs).
    Invalid refs are logged at DEBUG level and silently dropped.
    """
    if not refs:
        return refs
    try:
        from build.scripts.validate_osis import validate_osis_ref  # noqa: PLC0415
    except ImportError:
        return refs  # index unavailable — pass through unfiltered

    valid = []
    for ref in refs:
        ok, reason = validate_osis_ref(ref)
        if ok:
            valid.append(ref)
        else:
            logging.debug("  _filter_osis_refs: dropped invalid ref %r (%s)", ref, reason)
    return valid


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SWORD_RAW_DIR = REPO_ROOT / "raw" / "sword_modules"
OUTPUT_BASE = REPO_ROOT / "data" / "commentaries"
SOURCES_BASE = REPO_ROOT / "sources" / "commentaries"
LOG_FILE = Path(__file__).parent / "sword_commentary.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

# Module definitions: name -> testament coverage and block type prefix
MODULE_CONFIGS = {
    "barnes": {
        "sword_name": "Barnes",
        "block_prefix": {"nt": "c"},   # CHAPTER block type
        "testaments": ["nt"],
    },
    "calvin": {
        "sword_name": "CalvinCommentaries",
        "block_prefix": {"ot": "b", "nt": "b"},  # BOOK block type
        "testaments": ["ot", "nt"],
    },
    "wesley": {
        "sword_name": "Wesley",
        "block_prefix": {"ot": "b", "nt": "b"},  # BOOK block type
        "testaments": ["ot", "nt"],
    },
}

# ---------------------------------------------------------------------------
# Book reference tables (copied from helloao_commentary.py for consistency)
# ---------------------------------------------------------------------------

OSIS_TO_NAME = {
    "Gen": "Genesis", "Exod": "Exodus", "Lev": "Leviticus", "Num": "Numbers",
    "Deut": "Deuteronomy", "Josh": "Joshua", "Judg": "Judges", "Ruth": "Ruth",
    "1Sam": "1 Samuel", "2Sam": "2 Samuel", "1Kgs": "1 Kings", "2Kgs": "2 Kings",
    "1Chr": "1 Chronicles", "2Chr": "2 Chronicles", "Ezra": "Ezra", "Neh": "Nehemiah",
    "Esth": "Esther", "Job": "Job", "Ps": "Psalms", "Prov": "Proverbs",
    "Eccl": "Ecclesiastes", "Song": "Song of Solomon", "Isa": "Isaiah",
    "Jer": "Jeremiah", "Lam": "Lamentations", "Ezek": "Ezekiel", "Dan": "Daniel",
    "Hos": "Hosea", "Joel": "Joel", "Amos": "Amos", "Obad": "Obadiah",
    "Jonah": "Jonah", "Mic": "Micah", "Nah": "Nahum", "Hab": "Habakkuk",
    "Zeph": "Zephaniah", "Hag": "Haggai", "Zech": "Zechariah", "Mal": "Malachi",
    "Matt": "Matthew", "Mark": "Mark", "Luke": "Luke", "John": "John",
    "Acts": "Acts", "Rom": "Romans", "1Cor": "1 Corinthians", "2Cor": "2 Corinthians",
    "Gal": "Galatians", "Eph": "Ephesians", "Phil": "Philippians", "Col": "Colossians",
    "1Thess": "1 Thessalonians", "2Thess": "2 Thessalonians", "1Tim": "1 Timothy",
    "2Tim": "2 Timothy", "Titus": "Titus", "Phlm": "Philemon", "Heb": "Hebrews",
    "Jas": "James", "1Pet": "1 Peter", "2Pet": "2 Peter", "1John": "1 John",
    "2John": "2 John", "3John": "3 John", "Jude": "Jude", "Rev": "Revelation",
}

OSIS_BOOK_NUMBER = {
    "Gen": 1, "Exod": 2, "Lev": 3, "Num": 4, "Deut": 5, "Josh": 6,
    "Judg": 7, "Ruth": 8, "1Sam": 9, "2Sam": 10, "1Kgs": 11, "2Kgs": 12,
    "1Chr": 13, "2Chr": 14, "Ezra": 15, "Neh": 16, "Esth": 17, "Job": 18,
    "Ps": 19, "Prov": 20, "Eccl": 21, "Song": 22, "Isa": 23, "Jer": 24,
    "Lam": 25, "Ezek": 26, "Dan": 27, "Hos": 28, "Joel": 29, "Amos": 30,
    "Obad": 31, "Jonah": 32, "Mic": 33, "Nah": 34, "Hab": 35, "Zeph": 36,
    "Hag": 37, "Zech": 38, "Mal": 39,
    "Matt": 40, "Mark": 41, "Luke": 42, "John": 43, "Acts": 44, "Rom": 45,
    "1Cor": 46, "2Cor": 47, "Gal": 48, "Eph": 49, "Phil": 50, "Col": 51,
    "1Thess": 52, "2Thess": 53, "1Tim": 54, "2Tim": 55, "Titus": 56,
    "Phlm": 57, "Heb": 58, "Jas": 59, "1Pet": 60, "2Pet": 61, "1John": 62,
    "2John": 63, "3John": 64, "Jude": 65, "Rev": 66,
}

# KJV versification: (name, osis, chapter_lengths[]) for each testament
# Derived from pysword canons['kjv']
KJV_CANON = {
    "ot": [
        ("Genesis", "Gen", [31,25,24,26,32,22,24,22,29,32,32,20,18,24,21,16,27,33,38,18,34,24,20,67,34,35,46,22,35,43,55,32,20,31,29,43,36,30,23,23,57,38,34,34,28,34,31,22,33,26]),
        ("Exodus", "Exod", [22,25,22,31,23,30,25,32,35,29,10,51,22,31,27,36,16,27,25,26,36,31,33,18,40,37,21,43,46,38,18,35,23,35,35,38,29,31,43,38]),
        ("Leviticus", "Lev", [17,16,17,35,19,30,38,36,24,20,47,8,59,57,33,34,16,30,24,16,15,18,21,20,14,16,17,28]),
        ("Numbers", "Num", [54,34,51,49,31,27,89,26,23,36,35,16,33,45,41,50,13,32,22,29,35,41,30,25,18,65,23,31,40,16,54,42,56,29,34,13]),
        ("Deuteronomy", "Deut", [46,37,29,49,33,25,26,20,29,22,32,32,18,29,23,22,20,22,21,20,23,30,25,22,19,19,26,68,29,20,30,52,29,12]),
        ("Joshua", "Josh", [18,24,17,24,15,27,26,35,27,43,23,24,33,15,63,10,18,28,51,9,45,34,16,33]),
        ("Judges", "Judg", [36,23,31,24,31,40,25,35,57,18,40,15,25,20,20,31,13,31,30,48,25]),
        ("Ruth", "Ruth", [22,23,18,22]),
        ("I Samuel", "1Sam", [28,36,21,22,12,21,17,22,27,27,15,25,23,52,35,23,58,30,24,42,15,23,29,22,44,25,12,25,11,31,13]),
        ("II Samuel", "2Sam", [27,32,39,12,25,23,29,18,13,19,27,31,39,33,37,23,29,33,43,26,22,51,39,25]),
        ("I Kings", "1Kgs", [53,46,28,34,18,38,51,66,28,29,43,33,34,31,34,34,24,46,21,43,29,53]),
        ("II Kings", "2Kgs", [18,25,27,44,27,33,20,29,37,36,21,21,25,29,38,20,41,37,37,21,26,20,37,20,30]),
        ("I Chronicles", "1Chr", [54,55,24,43,26,81,40,40,44,14,47,40,14,17,29,43,27,17,19,8,30,19,32,31,31,32,34,21,30]),
        ("II Chronicles", "2Chr", [17,18,17,22,14,42,22,18,31,19,23,16,22,15,19,14,19,34,11,37,20,12,21,27,28,23,9,27,36,27,21,33,25,33,27,23]),
        ("Ezra", "Ezra", [11,70,13,24,17,22,28,36,15,44]),
        ("Nehemiah", "Neh", [11,20,32,23,19,19,73,18,38,39,36,47,31]),
        ("Esther", "Esth", [22,28,23,31,29,41,4,18,20,11,27,23]),
        ("Job", "Job", [22,13,26,21,27,30,21,22,35,22,20,25,28,22,35,22,16,21,29,29,34,30,17,25,6,14,23,28,25,31,40,22,33,37,16,33,24,41,30,24,34,17]),
        ("Psalms", "Ps", [6,12,8,8,12,10,17,9,20,18,7,8,6,7,5,11,15,50,14,9,13,31,6,10,22,12,14,9,11,12,24,11,22,22,28,12,40,22,13,17,13,11,5,26,17,11,9,14,20,23,19,9,6,7,23,13,11,11,17,12,8,12,11,10,13,20,7,35,36,5,24,20,28,23,10,12,20,72,13,19,16,8,18,12,13,17,7,18,52,17,16,15,5,23,11,13,12,9,9,5,8,28,22,35,45,48,43,13,31,7,10,10,9,8,18,19,2,29,176,7,8,9,4,8,5,6,5,6,8,8,3,18,3,3,21,26,9,8,24,14,10,8,12,15,21,10,20,14,9,6]),
        ("Proverbs", "Prov", [33,22,35,27,23,35,27,36,18,32,31,28,25,35,33,33,28,24,29,30,31,29,35,34,28,28,27,28,27,33,31]),
        ("Ecclesiastes", "Eccl", [18,26,22,16,20,12,29,17,18,20,10,14]),
        ("Song of Solomon", "Song", [17,17,11,16,16,13,13,14]),
        ("Isaiah", "Isa", [31,22,26,6,30,13,25,22,21,34,16,6,22,32,9,14,14,7,25,6,17,25,18,23,12,21,13,29,24,33,9,20,24,17,10,22,38,22,8,31,29,25,28,28,25,13,15,22,26,11,23,15,12,17,13,12,21,14,21,22,11,12,19,12,25,24]),
        ("Jeremiah", "Jer", [19,37,25,31,31,30,34,22,26,25,23,17,27,22,21,21,27,23,15,18,14,30,40,10,38,24,22,17,32,24,40,44,26,22,19,32,21,28,18,16,18,22,13,30,5,28,7,47,39,46,64,34]),
        ("Lamentations", "Lam", [22,22,66,22,22]),
        ("Ezekiel", "Ezek", [28,10,27,17,17,14,27,18,11,22,25,28,23,23,8,63,24,32,14,49,32,31,49,27,17,21,36,26,21,26,18,32,33,31,15,38,28,23,29,49,26,20,27,31,25,24,23,35]),
        ("Daniel", "Dan", [21,49,30,37,31,28,28,27,27,21,45,13]),
        ("Hosea", "Hos", [11,23,5,19,15,11,16,14,17,15,12,14,16,9]),
        ("Joel", "Joel", [20,32,21]),
        ("Amos", "Amos", [15,16,15,13,27,14,17,14,15]),
        ("Obadiah", "Obad", [21]),
        ("Jonah", "Jonah", [17,10,10,11]),
        ("Micah", "Mic", [16,13,12,13,15,16,20]),
        ("Nahum", "Nah", [15,13,19]),
        ("Habakkuk", "Hab", [17,20,19]),
        ("Zephaniah", "Zeph", [18,15,20]),
        ("Haggai", "Hag", [15,23]),
        ("Zechariah", "Zech", [21,13,10,14,11,15,14,23,17,12,17,14,9,21]),
        ("Malachi", "Mal", [14,17,18,6]),
    ],
    "nt": [
        ("Matthew", "Matt", [25,23,17,25,48,34,29,34,38,42,30,50,58,36,39,28,27,35,30,34,46,46,39,51,46,75,66,20]),
        ("Mark", "Mark", [45,28,35,41,43,56,37,38,50,52,33,44,37,72,47,20]),
        ("Luke", "Luke", [80,52,38,44,39,49,50,56,62,42,54,59,35,35,32,31,37,43,48,47,38,71,56,53]),
        ("John", "John", [51,25,36,54,47,71,53,59,41,42,57,50,38,31,27,33,26,40,42,31,25]),
        ("Acts", "Acts", [26,47,26,37,42,15,60,40,43,48,30,25,52,28,41,40,34,28,41,38,40,30,35,27,27,32,44,31]),
        ("Romans", "Rom", [32,29,31,25,21,23,25,39,33,21,36,21,14,26,33,24,24,24,27,35]),
        ("I Corinthians", "1Cor", [31,16,23,21,13,20,40,13,27,33,34,31,13,40,58,24]),
        ("II Corinthians", "2Cor", [24,17,18,18,21,18,16,24,15,18,33,21,14]),
        ("Galatians", "Gal", [24,21,29,31,26,18]),
        ("Ephesians", "Eph", [23,22,21,28,20,12]),
        ("Philippians", "Phil", [30,30,21,23]),
        ("Colossians", "Col", [29,23,25,18]),
        ("I Thessalonians", "1Thess", [10,20,13,18,28]),
        ("II Thessalonians", "2Thess", [12,17,18]),
        ("I Timothy", "1Tim", [20,15,16,16,25,21]),
        ("II Timothy", "2Tim", [18,26,17,22]),
        ("Titus", "Titus", [16,15,15]),
        ("Philemon", "Phlm", [25]),
        ("Hebrews", "Heb", [14,18,19,16,14,20,28,13,28,39,40,29,25]),
        ("James", "Jas", [27,26,18,17,20]),
        ("I Peter", "1Pet", [25,25,22,19,14]),
        ("II Peter", "2Pet", [21,22,18]),
        ("I John", "1John", [10,29,24,21,21]),
        ("II John", "2John", [13]),
        ("III John", "3John", [15]),
        ("Jude", "Jude", [25]),
        ("Revelation of John", "Rev", [20,29,22,11,14,17,17,13,21,11,19,17,18,20,8,21,18,24,21,15,27,21]),
    ],
}


# ---------------------------------------------------------------------------
# Book slug helpers
# ---------------------------------------------------------------------------

def _book_slug(name: str) -> str:
    """
    Convert a pysword book name to the OCD filename slug.

    Examples:
      'Genesis'              -> 'genesis'
      'I Samuel'             -> '1-samuel'
      'II Chronicles'        -> '2-chronicles'
      'III John'             -> '3-john'
      'Revelation of John'   -> 'revelation'
      'Song of Solomon'      -> 'song-of-solomon'
      'Psalms'               -> 'psalms'
    """
    # Handle Roman numeral prefixes
    name = re.sub(r"^III ", "3 ", name)
    name = re.sub(r"^II ", "2 ", name)
    name = re.sub(r"^I ", "1 ", name)
    # Shorten 'Revelation of John' -> 'Revelation'
    if name == "Revelation of John":
        name = "Revelation"
    # Lowercase and replace spaces with hyphens
    return name.lower().replace(" ", "-")


# ---------------------------------------------------------------------------
# SWORD zCom reader
# ---------------------------------------------------------------------------

class SwordZComReader:
    """
    Reads SWORD zCom module files (BZS, BZV, BZZ) for one testament.
    Provides get_verse(book_idx, chapter, verse) -> text or None.

    Positional index is 0-indexed from the start of the testament file.
    All block decompression is cached in memory.
    """

    def __init__(self, module_dir: Path, testament: str, prefix: str):
        """
        :param module_dir: Path to the SWORD module data directory
        :param testament: 'ot' or 'nt'
        :param prefix: 'b' (BOOK block type) or 'c' (CHAPTER block type)
        """
        bzs_path = module_dir / f"{testament}.{prefix}zs"
        bzv_path = module_dir / f"{testament}.{prefix}zv"
        bzz_path = module_dir / f"{testament}.{prefix}zz"

        if not bzv_path.exists():
            raise FileNotFoundError(f"BZV not found: {bzv_path}")

        self._bzs_data = bzs_path.read_bytes()
        self._bzv_data = bzv_path.read_bytes()
        self._bzz_data = bzz_path.read_bytes()
        self._cache: dict = {}  # block_num -> decompressed bytes

        n_blocks = len(self._bzs_data) // 12
        self._n_bzv_entries = len(self._bzv_data) // 10
        logging.info(
            "  Loaded %s %s: %d blocks, %d verse positions",
            testament.upper(), bzv_path.name, n_blocks, self._n_bzv_entries
        )

    def _decompress_block(self, block_num: int) -> bytes:
        """Return decompressed bytes for a block (cached)."""
        if block_num in self._cache:
            return self._cache[block_num]

        if block_num * 12 + 12 > len(self._bzs_data):
            self._cache[block_num] = b""
            return b""

        offset, clen, _uclen = struct.unpack_from("<III", self._bzs_data, block_num * 12)
        if clen == 0 or offset + clen > len(self._bzz_data):
            self._cache[block_num] = b""
            return b""

        compressed = self._bzz_data[offset : offset + clen]
        try:
            result = zlib.decompress(compressed)
        except zlib.error as exc:
            logging.warning("    Block %d decomp failed: %s", block_num, exc)
            result = b""
        self._cache[block_num] = result
        return result

    def get_text_at_index(self, bzv_index: int) -> bytes:
        """Return raw bytes for a verse at the given BZV positional index. Empty if no content."""
        if bzv_index < 0 or bzv_index >= self._n_bzv_entries:
            return b""
        entry_offset = bzv_index * 10
        block_num, verse_start, verse_len = struct.unpack_from(
            "<IIH", self._bzv_data, entry_offset
        )
        if verse_len == 0:
            return b""
        block_data = self._decompress_block(block_num)
        if verse_start + verse_len > len(block_data):
            return b""
        return block_data[verse_start : verse_start + verse_len]


# ---------------------------------------------------------------------------
# Positional index calculation (mirrors pysword BibleStructure)
# ---------------------------------------------------------------------------

def _book_size(chapter_lengths: list) -> int:
    """Total BZV slots for one book: sum of verses + chapter headings + book heading."""
    return sum(chapter_lengths) + len(chapter_lengths) + 1


def _chapter_offset(chapter_lengths: list, chapter_idx: int) -> int:
    """
    BZV offset within a book for a given chapter (0-indexed chapter_idx).
    = sum(chapter_lengths[:chapter_idx]) + chapter_idx + 2
    """
    return sum(chapter_lengths[:chapter_idx]) + chapter_idx + 2


def build_verse_position_map(testament: str) -> dict:
    """
    Build a mapping of (book_idx, chapter, verse) -> BZV positional index
    for every verse in the KJV canon for the given testament ('ot' or 'nt').

    book_idx is 0-based (0 = Genesis for OT, 0 = Matthew for NT).
    chapter and verse are 1-based.
    """
    books = KJV_CANON[testament]
    verse_map = {}

    # Testament starts at BZV position 2 (2 slots reserved as testament heading)
    book_offset = 2
    for book_idx, (name, osis, chapter_lengths) in enumerate(books):
        for ch_idx, n_verses in enumerate(chapter_lengths):
            chapter = ch_idx + 1
            ch_off = _chapter_offset(chapter_lengths, ch_idx)
            for verse in range(1, n_verses + 1):
                bzv_index = book_offset + ch_off + (verse - 1)
                verse_map[(book_idx, chapter, verse)] = bzv_index
        book_offset += _book_size(chapter_lengths)

    return verse_map


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

# Cross-reference pattern for ThML: <scripRef passage="Mk 1:1">Mk 1:1</scripRef>
# Also handles embedded refs in Calvin's OSIS: <reference osisRef="Bible:Matt.1.1">
_THML_REF_PATTERN = re.compile(
    r'<scripRef[^>]*\bpassage=["\']([^"\']+)["\'][^>]*>[^<]*</scripRef>',
    re.IGNORECASE,
)
# Wesley uses text-content format (no passage= attribute):
#   <scripRef>Luke 3:31</scripRef>
#   <scripRef>Deut 24:1; Matt 19:7</scripRef>
_THML_REF_CONTENT_PATTERN = re.compile(
    r'<scripRef>([^<]+)</scripRef>',
    re.IGNORECASE,
)
_OSIS_REF_PATTERN = re.compile(
    r'<reference[^>]*\bosisRef=["\']([^"\']+)["\'][^>]*>',
    re.IGNORECASE,
)

# Strip all XML/HTML tags
_TAG_PATTERN = re.compile(r"<[^>]+>")

# Collapse runs of whitespace (including newlines, tabs)
_WS_PATTERN = re.compile(r"\s+")



# Regex identifying a token that starts a new book+chapter:verse reference.
# Used by _split_ref_candidates() to split space-separated multi-ref strings.
# Matches: optional digit prefix, one or more letters (book abbrev), then
# whitespace or end-of-token boundary followed by digits:digits.
# Examples: "Ge", "Psa", "John", "1Sam", "2Cor"
_BOOK_ABBREV_RE = re.compile(
    r"(?:^|\s)(\d?\s*[A-Za-z]+)\s+(\d+:\d+(?:[-.]\d+)*(?::\d+)?)",
)

# Bare chapter:verse pattern used during candidate scanning
_BARE_CHAV_RE = re.compile(r"^\d+:\d+")


def _split_ref_candidates(text: str) -> list[str]:
    """
    Split a Wesley-style scripRef text into individual ref candidate strings
    that parse_thml_refs() can handle one at a time.

    Wesley scripRef text is space-separated and may contain:
      - "Ge 15:1 17:1"        (same book, two ch:v pairs)
      - "Psa 104:9 Job 38:9"  (two different books)
      - "John 11:9 and work John 9:4"  (prose words interspersed)

    Strategy:
      1. Walk tokens left-to-right tracking a "current book" context.
      2. When a book-abbreviation token is seen (followed by ch:v), start a new
         candidate, carrying the book into subsequent bare ch:v tokens.
      3. Bare ch:v tokens (no book prefix) are emitted as "{current_book} {token}"
         so parse_thml_refs() can normalise them with book context.
      4. Tokens that are neither a book abbrev+ch:v starter nor a bare ch:v are
         skipped (prose words like "and", "work", "as", "the", etc.).

    Returns a list of strings, each suitable for passing to parse_thml_refs().
    These are minimal single-ref strings, not the full original text.
    """
    # Tokenize on whitespace; we'll scan pairs of (token, next_token) to detect
    # book+ch:v boundaries.
    tokens = text.split()
    candidates: list[str] = []
    current_book: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Check if this token looks like a book abbreviation followed by a ch:v
        # in the NEXT token (e.g. tok="Ge", tokens[i+1]="15:1")
        if i + 1 < len(tokens) and re.match(r"^\d?\s*[A-Za-z]+$", tok):
            next_tok = tokens[i + 1]
            if _BARE_CHAV_RE.match(next_tok):
                # Book + ch:v pair
                current_book = tok
                candidates.append(f"{tok} {next_tok}")
                i += 2
                continue
        # Check if this single token is already a "book ch:v" compound (no space)
        # e.g. "Ge15:1" — unlikely in Wesley but guard anyway
        m = re.match(r"^(\d?[A-Za-z]+)(\d+:\d+.*)$", tok)
        if m:
            current_book = m.group(1)
            candidates.append(tok)
            i += 1
            continue
        # Bare ch:v token — use current book context
        if _BARE_CHAV_RE.match(tok) and current_book is not None:
            candidates.append(f"{current_book} {tok}")
            i += 1
            continue
        # Anything else (prose word, standalone number, etc.) — skip
        i += 1
    return candidates


def _extract_refs_thml(raw: str) -> list:
    """
    Extract and normalise scripture refs from ThML markup, returning OSIS strings.

    Two input formats are supported:
    - Barnes (passage= attribute): <scripRef passage="Mt 1:2">...</scripRef>
    - Wesley (text-content only):  <scripRef>Luke 3:31</scripRef>

    Both patterns are always collected (Fix 2: no longer an if/else — a source
    with mixed tags will yield refs from both patterns, deduplicated).

    For content-only refs (Wesley), the text is first split into individual
    ref candidates by _split_ref_candidates() before normalisation. This fixes
    the root cause of 570/4177 Wesley scripRef tags failing normalisation:
    multi-ref strings like "Ge 15:1 17:1" or "Psa 104:9 Job 38:9" were
    previously passed as one unit to parse_thml_refs(), which requires tokens
    delimited by commas or semicolons and rejected the whole string. Now each
    space-separated book+ch:v candidate is extracted and passed individually,
    recovering refs that would otherwise produce cross_references: [].
    Prose words ("and", "work", "as", etc.) are skipped during candidate
    extraction. Accepted residual loss: content with no recognisable book+ch:v
    pattern at all (e.g. bare chapter references like "Mt 4") still yields [].
    """
    raw_strings: list[str] = []

    # Barnes: passage= attribute values (always collect these)
    for m in _THML_REF_PATTERN.finditer(raw):
        raw_strings.append(m.group(1))

    # Wesley / mixed sources: text-content values (always collect, not else-only).
    # Each content string is split into individual ref candidates so that
    # space-separated multi-ref strings like "Ge 15:1 17:1" are resolved.
    for m in _THML_REF_CONTENT_PATTERN.finditer(raw):
        content = m.group(1).strip()
        if not content:
            continue
        # If the content contains commas or semicolons, parse_thml_refs already
        # handles multi-ref splitting well — pass directly.
        # If it looks like a simple space-separated multi-ref, split first.
        if "," in content or ";" in content:
            raw_strings.append(content)
        else:
            # Split into per-ref candidates and add each separately so that
            # "Ge 15:1 17:1" becomes ["Ge 15:1", "Ge 17:1"] before normalisation.
            candidates = _split_ref_candidates(content)
            if candidates:
                raw_strings.extend(candidates)
            else:
                # Fallback: pass the whole string to parse_thml_refs as before
                raw_strings.append(content)

    # Normalise each string to OSIS refs, then deduplicate preserving order
    seen: set[str] = set()
    refs: list[str] = []
    for passage_str in raw_strings:
        for osis_ref in parse_thml_refs(passage_str):
            if osis_ref not in seen:
                seen.add(osis_ref)
                refs.append(osis_ref)

    return refs


def _extract_refs_osis(raw: str) -> list:
    """
    Extract scripture references from OSIS reference tags. Returns list of OSIS strings.
    osisRef values may be space-separated and may carry a 'Bible:' scope prefix, e.g.:
      osisRef="Jer.27.20 Bible:Jer.28.4"
    Split each value by whitespace and strip the prefix from each token.
    """
    refs = []
    for m in _OSIS_REF_PATTERN.finditer(raw):
        for token in m.group(1).split():
            clean = re.sub(r"^Bible:", "", token).strip()
            # Only emit verse-level refs (Book.Chapter.Verse); skip chapter-level refs (Book.Chapter)
            if clean and clean.count(".") >= 2:
                refs.append(clean)
    return refs


def clean_markup(text: str, source_type: str) -> tuple:
    """
    Strip HTML/XML markup from commentary text.
    Returns (plain_text, cross_references[]).
    """
    if not text:
        return "", []

    # Extract cross-references before stripping tags
    if source_type.lower() == "osis":
        cross_refs = _extract_refs_osis(text)
    else:  # ThML
        cross_refs = _extract_refs_thml(text)

    # Strip all tags
    plain = _TAG_PATTERN.sub(" ", text)
    # Collapse whitespace
    plain = _WS_PATTERN.sub(" ", plain).strip()
    return plain, cross_refs


# ---------------------------------------------------------------------------
# Schema validation (first-book gate)
# ---------------------------------------------------------------------------

class SchemaValidationError(Exception):
    """First-book schema validation found errors. Stops extraction before bulk file writes."""


def _check_first_book_schema(module_name: str, slug: str, output: dict) -> None:
    """
    Validate the first book's output dict against the commentary schema in-memory.
    Raises SchemaValidationError if any errors are found — this stops the run
    before 27-66 files with the same defect are written.

    Called unconditionally (dry-run and production alike) for the first book
    in each testament. Overhead is negligible (~0.05s).
    """
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    try:
        from build.validate import validate_commentary_file  # noqa: PLC0415
    except ImportError as exc:
        logging.warning("  Schema check skipped (could not import validate): %s", exc)
        return

    fake_path = OUTPUT_BASE / module_name / f"{slug}.json"
    errors, _warnings = validate_commentary_file(fake_path, output)
    if errors:
        logging.error(
            "  SCHEMA CHECK FAILED (%s/%s) -- %d error(s). "
            "Stopping extraction to prevent writing bulk bad output:",
            module_name, slug, len(errors),
        )
        for e in errors[:10]:
            logging.error("    %s", e)
        if len(errors) > 10:
            logging.error("    ... and %d more -- run validate.py for full list", len(errors) - 10)
        raise SchemaValidationError(
            f"{module_name}/{slug}: {len(errors)} schema errors -- see log for details"
        )
    logging.info(
        "  Schema check OK (%s/%s, %d entries validated)",
        module_name, slug, len(output.get("data", [])),
    )


# ---------------------------------------------------------------------------
# Meta envelope builder
# ---------------------------------------------------------------------------

def build_meta(config: dict, processing_date: str, source_hash: str, testament: str) -> dict:
    """Build the OCD metadata envelope for one output file."""
    return {
        "id": config["resource_id"],
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config.get("author_birth_year"),
        "author_death_year": config.get("author_death_year"),
        "contributors": config.get("contributors", []),
        "original_publication_year": config.get("original_publication_year"),
        "language": config["language"],
        "tradition": config["tradition"],
        "tradition_notes": config.get("tradition_notes"),
        "license": config["license"],
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "verse_text_source": "none",
        "verse_reference_standard": "OSIS",
        "completeness": "partial",
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": processing_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/sword_commentary.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# Module extraction
# ---------------------------------------------------------------------------

def extract_module(module_name: str, dry_run: bool = False) -> dict:
    """
    Extract one SWORD commentary module to OCD JSON files.
    Returns stats dict.
    """
    if module_name not in MODULE_CONFIGS:
        raise ValueError(f"Unknown module: {module_name}")

    mod_conf = MODULE_CONFIGS[module_name]
    sword_name = mod_conf["sword_name"]

    # Load source config
    config_path = SOURCES_BASE / module_name / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path} -- run the source setup step first")
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    resource_id = config["resource_id"]
    source_type = config.get("source_format", "ThML")
    # Detect SourceType from format string
    is_osis = "OSIS" in source_type.upper()

    # Module data directory
    module_dir = SWORD_RAW_DIR / sword_name / "modules" / "comments" / "zcom" / sword_name.lower()
    if not module_dir.exists():
        raise FileNotFoundError(f"Module data dir not found: {module_dir} -- run download_sword_modules.py first")

    # Compute source zip hash for provenance
    zip_path = SWORD_RAW_DIR / f"{sword_name}.zip"
    source_hash = ""
    if zip_path.exists():
        h = hashlib.sha256()
        with open(zip_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        source_hash = h.hexdigest()

    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logging.info("Module: %s (%s)", module_name, sword_name)
    logging.info("Resource ID: %s", resource_id)
    logging.info("Output: %s/%s/", OUTPUT_BASE, module_name)
    logging.info("Source type: %s", "OSIS" if is_osis else "ThML")
    if dry_run:
        logging.info("Mode: DRY-RUN (no files written)")

    total_entries = 0
    total_books = 0
    total_empty = 0
    all_word_counts: list = []
    entries_with_refs = 0  # entries where cross_references is non-empty

    for testament in mod_conf["testaments"]:
        prefix = mod_conf["block_prefix"][testament]

        logging.info("  Reading %s %s ...", module_name, testament.upper())
        try:
            reader = SwordZComReader(module_dir, testament, prefix)
        except FileNotFoundError as exc:
            logging.warning("  Skipping %s %s: %s", module_name, testament, exc)
            continue

        verse_map = build_verse_position_map(testament)
        books = KJV_CANON[testament]

        # Group verse_map entries by book_idx
        by_book: dict = {}
        for (book_idx, chapter, verse), bzv_index in verse_map.items():
            raw_bytes = reader.get_text_at_index(bzv_index)
            if not raw_bytes:
                total_empty += 1
                continue
            try:
                raw_text = raw_bytes.decode("utf-8", errors="replace")
            except Exception as exc:
                logging.warning(
                    "  Unexpected error decoding verse (%d,%d,%d): %s",
                    book_idx, chapter, verse, exc,
                )
                total_empty += 1
                continue
            try:
                plain, cross_refs = clean_markup(raw_text, "osis" if is_osis else "thml")
            except Exception as exc:
                logging.warning(
                    "  clean_markup failed for entry (%d/%d/%d), skipping: %s",
                    book_idx, chapter, verse, exc,
                )
                total_empty += 1
                continue
            if not plain:
                total_empty += 1
                continue
            if book_idx not in by_book:
                by_book[book_idx] = []
            by_book[book_idx].append((chapter, verse, plain, cross_refs))

        logging.info(
            "  %s %s: %d books with content (out of %d)",
            module_name, testament.upper(), len(by_book), len(books)
        )

        # Write one JSON file per book
        first_book_for_testament = True
        for book_idx in sorted(by_book.keys()):
            name, osis, chapter_lengths = books[book_idx]
            slug = _book_slug(name)
            book_num = OSIS_BOOK_NUMBER.get(osis, 0)
            book_name = OSIS_TO_NAME.get(osis, name)

            entries = []
            verse_entries = sorted(by_book[book_idx])  # sorted by (chapter, verse)
            for chapter, verse, plain, cross_refs in verse_entries:
                entry_id = f"{resource_id}.{osis}.{chapter}.{verse}"
                cross_refs = _filter_osis_refs(cross_refs)
                word_count = len(plain.split())
                all_word_counts.append(word_count)
                entry = {
                    "entry_id": entry_id,
                    "book": book_name,
                    "book_osis": osis,
                    "book_number": book_num,
                    "chapter": chapter,
                    "verse_range": str(verse),
                    "verse_range_osis": f"{osis}.{chapter}.{verse}",
                    "verse_text": None,
                    "commentary_text": plain,
                    "summary": None,
                    "summary_review_status": "withheld",
                    "cross_references": cross_refs,
                    "word_count": word_count,
                }
                entries.append(entry)
                if cross_refs:
                    entries_with_refs += 1

            meta = build_meta(config, processing_date, source_hash, testament)
            output = {"meta": meta, "data": entries}
            total_entries += len(entries)
            total_books += 1

            # First-book gate: validate schema before writing anything to disk.
            # A schema error here aborts the whole module, not just one book.
            if first_book_for_testament:
                first_book_for_testament = False
                _check_first_book_schema(module_name, slug, output)
                # In dry-run: surface the first entry's key fields so
                # cross_reference format is visible at a glance.
                if dry_run and entries:
                    sample = entries[0]
                    logging.info(
                        "  Sample entry (%s %s): entry_id=%s  cross_references=%s",
                        module_name, slug,
                        sample["entry_id"],
                        sample["cross_references"][:3],
                    )

            # Progress log
            logging.info(
                "  [%s] %s: %d entries", module_name, f"{osis}/{slug}", len(entries)
            )

            if not dry_run:
                out_dir = OUTPUT_BASE / module_name
                out_dir.mkdir(parents=True, exist_ok=True)
                out_file = out_dir / f"{slug}.json"
                with open(out_file, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                    f.write("\n")

    sorted_wc = sorted(all_word_counts)
    wc_stats = {}
    if sorted_wc:
        wc_stats = {
            "min": sorted_wc[0],
            "median": sorted_wc[len(sorted_wc) // 2],
            "max": sorted_wc[-1],
        }
    return {
        "module": module_name,
        "books_written": total_books,
        "entries_written": total_entries,
        "verses_empty": total_empty,
        "word_count_stats": wc_stats,
        "entries_with_refs": entries_with_refs,
    }


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def report_quality(stats: dict) -> None:
    """Print quality stats for one module extraction."""
    n = stats["entries_written"]
    logging.info(
        "  Result: %d books, %d entries, %d empty verse slots",
        stats["books_written"],
        n,
        stats["verses_empty"],
    )
    wc = stats.get("word_count_stats", {})
    if wc:
        logging.info(
            "  Word count: min=%d median=%d max=%d",
            wc["min"], wc["median"], wc["max"],
        )
    # Cross-references coverage -- non-zero means the normalizer is wired correctly
    with_refs = stats.get("entries_with_refs", 0)
    if n > 0:
        pct = 100.0 * with_refs / n
        logging.info(
            "  Cross-references: %d/%d entries have refs (%.1f%%)",
            with_refs, n, pct,
        )
        if with_refs == 0:
            logging.warning(
                "  WARNING: 0 entries have cross_references for %s"
                " -- normalizer may not be wired",
                stats["module"],
            )
    if n == 0:
        logging.warning("  WARNING: 0 entries written for %s", stats["module"])


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Extract SWORD zCom commentary modules (Barnes, Calvin, Wesley) to OCD schema"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--module",
        choices=list(MODULE_CONFIGS.keys()),
        help="Single module to process",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all modules (Barnes, Calvin, Wesley)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing output files",
    )
    args = parser.parse_args()

    start_time = time.time()
    modules = list(MODULE_CONFIGS.keys()) if args.all else [args.module]

    logging.info("=== SWORD Commentary Extraction ===")
    logging.info("Modules: %s", ", ".join(modules))

    all_stats = []
    failed_modules = []
    for i, module_name in enumerate(modules):
        logging.info("")
        logging.info("--- %s ---", module_name.upper())
        try:
            stats = extract_module(module_name, dry_run=args.dry_run)
            report_quality(stats)
            all_stats.append(stats)
        except Exception as exc:
            logging.error("FAILED %s: %s", module_name, exc)
            logging.error(traceback.format_exc())
            failed_modules.append(module_name)

    elapsed = time.time() - start_time
    logging.info("")
    logging.info("=== Summary ===")
    for s in all_stats:
        logging.info(
            "  %-20s %3d books  %6d entries",
            s["module"], s["books_written"], s["entries_written"]
        )
    if failed_modules:
        logging.error("  FAILED: %s", ", ".join(failed_modules))
    logging.info("Elapsed: %.1fs", elapsed)

    if args.dry_run:
        logging.info("Dry-run complete -- no files written.")


if __name__ == "__main__":
    main()
