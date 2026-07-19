"""gutenberg_sermons.py
Parse Luther's Church Postil (Lenker, 1903) and Newman's Parochial and Plain
Sermons (Rivingtons, 1868) from Internet Archive and Project Gutenberg.

Sources:
  Luther -- Internet Archive DjVu OCR text (volumes 7-14 of
    "The Precious and Sacred Writings of Martin Luther"; IA identifiers
    precioussacredwr07luth through precioussacredwr14luth).
    Vols 7-9 = Epistle Sermons; vols 10-14 = Gospel Sermons (Church Postil).

  Newman -- IA DjVu OCR text vols 1-6 (parochialplainse0{N}newmuoft) and
    Project Gutenberg plain text vols 7-8 (PG#24256, PG#24284).

Output:
  data/sermons/luther-lenker-sermons.json
  data/sermons/newman-parochial-sermons.json

Schema: sermon (ocd_kernel/schemas/v1/sermon.schema.json)
Tradition: Luther = lutheran, reformation; Newman = anglican

Usage:
    py -3 build/parsers/gutenberg_sermons.py --series luther --download --parse
    py -3 build/parsers/gutenberg_sermons.py --series newman --download --parse
    py -3 build/parsers/gutenberg_sermons.py --series all --download --parse
    py -3 build/parsers/gutenberg_sermons.py --series luther --dry-run
    py -3 build/parsers/gutenberg_sermons.py --series luther --volume 1

Parser quirks (for extending this file):
  Luther Text: boundary: varies by volume. Vol 1 = "Epistle Text:" / "Gospel Text:" with
    colon-letter-digit format. Vols 2-8 = bare "Text:" with varied separators (colon,
    period, comma). Vol 7 DjVu OCR uses "Text." (period). LUTHER_TEXT_RE handles all.
  OCR sentence-break stripping: _SCRIPTURE_BREAK_RE removes embedded quotation text
    that DjVu OCR runs together with the scripture ref line (e.g. "Text: Romans ...quoted
    verse text continued here..."). Strip before extracting the ref.
  Newman primary_reference: PG vols extract ref from "--Book ch.v" at end of quotation
    block (_extract_newman_pg_ref). IA vols set primary_reference to explicit null (not
    absent) -- the validator treats absent-key as "missing" but null as intentional.
"""

import argparse
import hashlib
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

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib._generated_enums import (  # noqa: E402
    SERMON__META__AUDIENCE,
    SERMON__META__COMPLETENESS,
    SERMON__META__ERA,
    SERMON__META__PROVENANCE__PROCESSING_METHOD,
    SERMON__META__TRADITION,
)
from build.lib.text_utils import compute_source_hash, smart_title  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)

LUTHER_DIR = REPO_ROOT / "raw" / "gutenberg" / "sermons" / "luther"
NEWMAN_DIR = REPO_ROOT / "raw" / "gutenberg" / "sermons" / "newman"
OUTPUT_DIR = REPO_ROOT / "data" / "sermons"
OUTPUT_FILE_LUTHER = OUTPUT_DIR / "luther-lenker-sermons.json"
OUTPUT_FILE_NEWMAN = OUTPUT_DIR / "newman-parochial-sermons.json"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_sermons.log"

SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_sermons.py@v1.0.0"
DOWNLOAD_DATE = "2026-04-24"
USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
REQUEST_DELAY = 2.0
RETRY_DELAYS = (2.0, 4.0, 8.0)
RETRY_STATUS_CODES = frozenset([429, 500, 502, 503])

# ---------------------------------------------------------------------------
# Volume configs
# ---------------------------------------------------------------------------

# Luther: 8 sermon volumes from IA "Precious and Sacred Writings" vols 7-14.
# Parser vol numbering is 1-8 (logical), mapping to PSW vols 7-14.
# series_label: "epistle-sermons" (PSW 7-9) or "gospel-sermons" (PSW 10-14).
LUTHER_VOLUMES = [
    {
        "vol": 1,
        "psw_vol": 7,
        "ia_id": "precioussacredwr07luth",
        "series_label": "epistle-sermons",
        "title": "Epistle Sermons, Part 1",
        "year": 1903,
    },
    {
        "vol": 2,
        "psw_vol": 8,
        "ia_id": "precioussacredwr08luth",
        "series_label": "epistle-sermons",
        "title": "Epistle Sermons, Part 2",
        "year": 1903,
    },
    {
        "vol": 3,
        "psw_vol": 9,
        "ia_id": "precioussacredwr09luth",
        "series_label": "epistle-sermons",
        "title": "Epistle Sermons, Part 3",
        "year": 1903,
    },
    {
        "vol": 4,
        "psw_vol": 10,
        "ia_id": "precioussacredwr10luth",
        "series_label": "gospel-sermons",
        "title": "Gospel Sermons (Church Postil), Part 1",
        "year": 1903,
    },
    {
        "vol": 5,
        "psw_vol": 11,
        "ia_id": "precioussacredwr11luth",
        "series_label": "gospel-sermons",
        "title": "Gospel Sermons (Church Postil), Part 2",
        "year": 1903,
    },
    {
        "vol": 6,
        "psw_vol": 12,
        "ia_id": "precioussacredwr12luth",
        "series_label": "gospel-sermons",
        "title": "Gospel Sermons (Church Postil), Part 3",
        "year": 1903,
    },
    {
        "vol": 7,
        "psw_vol": 13,
        "ia_id": "precioussacredwr13luth",
        "series_label": "gospel-sermons",
        "title": "Gospel Sermons (Church Postil), Part 4",
        "year": 1903,
    },
    {
        "vol": 8,
        "psw_vol": 14,
        "ia_id": "precioussacredwr14luth",
        "series_label": "gospel-sermons",
        "title": "Gospel Sermons (Church Postil), Part 5",
        "year": 1903,
    },
]

# Newman: vols 1-6 from IA DjVu, vols 7-8 from PG.
# source: "ia" or "pg"
NEWMAN_VOLUMES = [
    {"vol": 1, "ia_id": "parochialplainse01newmuoft", "source": "ia", "year": 1868},
    {"vol": 2, "ia_id": "parochialplainse02newmuoft", "source": "ia", "year": 1868},
    {"vol": 3, "ia_id": "parochialplainse03newmuoft", "source": "ia", "year": 1868},
    {"vol": 4, "ia_id": "parochialplainse04newmuoft", "source": "ia", "year": 1868},
    {"vol": 5, "ia_id": "parochialplainse05newmuoft", "source": "ia", "year": 1868},
    {"vol": 6, "ia_id": "parochialplainse06newmuoft", "source": "ia", "year": 1868},
    {"vol": 7, "pg_id": "24256", "source": "pg", "year": 1868},
    {"vol": 8, "pg_id": "24284", "source": "pg", "year": 1868},
]


def _validate_configs() -> None:
    series_configs = {
        "luther": {
            "tradition": ["lutheran"],
            "era": "reformation",
            "audience": "lay",
            "completeness": "full",
            "processing_method": "ocr",
        },
        "newman": {
            "tradition": ["anglican"],
            "era": "modern",
            "audience": "lay",
            "completeness": "full",
            "processing_method": "ocr",
        },
    }
    for slug, cfg in series_configs.items():
        for tradition in cfg["tradition"]:
            assert tradition in SERMON__META__TRADITION, f"{slug}: invalid tradition value {tradition!r}"
        assert (era := cfg["era"]) in SERMON__META__ERA, f"{slug}: invalid era value {era!r}"
        assert (audience := cfg["audience"]) in SERMON__META__AUDIENCE, (
            f"{slug}: invalid audience value {audience!r}"
        )
        assert (completeness := cfg["completeness"]) in SERMON__META__COMPLETENESS, (
            f"{slug}: invalid completeness value {completeness!r}"
        )
        assert (
            processing_method := cfg["processing_method"]
        ) in SERMON__META__PROVENANCE__PROCESSING_METHOD, (
            f"{slug}: invalid processing_method value {processing_method!r}"
        )


_validate_configs()

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# PG header/footer markers (Newman vols 7-8)
_PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
_PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)

# Luther sermon boundary: "Epistle Text:", "Gospel Text:", or bare "Text:" at block start.
# DjVu OCR varies by volume: some use colon, others use period or comma as separator.
# "Text: Romans 12, 1-6" / "Text. Luke 16:19-31" / "Text, Luke 15:1-10"
# The separator character distinguishes boundary lines from body sentences with "text."
_LUTHER_TEXT_LINE_RE = re.compile(
    r"^\s*(?:(?:Epistle|Gospel)\s+)?Text\s*[:.,]\s*(\S.*)$", re.IGNORECASE
)

# Sentence break in OCR text: period/exclamation/hyphen/comma + 2+ spaces + uppercase (or quote).
# Used to strip embedded quotation text from a "Text:" line that OCR ran together.
# Hyphen: some DjVu volumes write verse-range refs as "34-39-  Therefore" (trailing hyphen).
# Comma: some volumes end the ref with a trailing comma before the prose:
#   "Math,  2, 1-12,  Nozv zvhen..." \u2192 break at "1-12,  Nozv" (comma + 2+ spaces + uppercase).
# The 2+ space requirement prevents matching intra-ref commas like "ch. 2, verse 3".
# IMPORTANT: comma-breaks where the first word after the break contains a digit are skipped in
# _extract_luther_scripture_ref \u2014 they are OCR'd verse-number continuations, not prose starts
# (e.g. "John  Jf,  Jf6-5Ii" where "Jf" = OCR "4", "Jf6" = OCR "46").
_SCRIPTURE_BREAK_RE = re.compile(r"[-!.,]\s{2,}[A-Z\"\u2018\u201c]")

# Luther ALL-CAPS title detection (adapted from Maclaren parser)
_LUTHER_TITLE_RE = re.compile(r"^[A-Z][A-Z\s\-\u2014,;:.!?'\"]{4,}$")


# Newman sermon header: "SERMON [Roman numerals]" at block start
_NEWMAN_SERMON_RE = re.compile(
    r"^SERMON\s+([IVXLCDM]+)[.\s,]", re.IGNORECASE
)

# Newman scripture ref: book name abbreviation + chapter.verse after sermon header
# Matches patterns like "Hebrews xii. 14" or "Matt. xv. 32" or "2 Cor. iii. 18"
_NEWMAN_SCRIPTURE_RE = re.compile(
    r"^\s*(\d?\s*[A-Z][a-z]+\.?\s+[ivxlcIVXLC]+\.?\s+\d[\d,\s\-]*\.?)\s*$"
)

# Newman PG dash-ref: scripture embedded at end of quotation block as "--Book ch. v"
# Matches: '"_Whatsoever..._"--Eccles. ix. 10'
_NEWMAN_DASH_REF_RE = re.compile(
    r"--\s*(\d*\s*[A-Z][a-z]+\.?\s+[ivxlcIVXLCdm]+\.?\s*\d[\d,\s\-\.]*)\s*$"
)

# Luther Gospel Sermon "CONTENTS:" prefix on title blocks.
# Gospel Sermon volumes (vols 4-8) prefix the title with "CONTENTS:" followed by the
# descriptive title in ALL CAPS: "CONTENTS:  THE WITNESS AND CONFESSION OF JOHN THE BAPTIST".
# The prefix is stripped; the remaining ALL-CAPS text is used as the sermon title.
_CONTENTS_PREFIX_RE = re.compile(r"^\s*CONTENTS\s*:\s*", re.IGNORECASE)

# IA DjVu footer sentinels: marks the start of non-sermon content (publisher catalog,
# statistics tables, library date card). Text is truncated at the first match.
# Sentinels confirmed per volume:
#   vol 4 (PSW 10): "|KE,AD LUTHER" = OCR "READ LUTHER!" ad header
#   vol 6 (PSW 12): "ECUMENICAL PROTESTANT STATISTICS" = statistical table header
#   vol 7 (PSW 13): "ICtbmrg Translator" = OCR "Library Translator" publisher magazine
#   vol 8 (PSW 14): "ECUMENICAL LUTHERAN STATISTICS" = statistical table header
#   all vols: "Date" alone on a line = library "Date Due" card (last resort)
_IA_FOOTER_SENTINELS = [
    re.compile(r"ECUMENICAL\s+\w+\s+STATISTICS", re.IGNORECASE),
    re.compile(r"\|KE,AD\s+LUTHER", re.IGNORECASE),
    re.compile(r"ICtbmrg\s+Translator", re.IGNORECASE),
    re.compile(r"^\s*Date\s*$"),  # Library "Date Due" card — final fallback
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print ASCII-safe message to console and append to log list."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)




def word_count(blocks: list) -> int:
    return sum(len(b.split()) for b in blocks)


def blocks_from_text(text: str) -> list:
    """Split text into blank-line-separated paragraphs, whitespace-normalised."""
    blocks = []
    current: list = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append(decode_pg_inline_markup(" ".join(current)))
                current = []
        else:
            current.append(stripped)
    if current:
        blocks.append(decode_pg_inline_markup(" ".join(current)))
    return blocks


def strip_pg_wrapper(text: str) -> list:
    """Strip PG header/footer. Returns body lines. Raises ValueError if markers absent."""
    lines = text.splitlines()
    start_idx = end_idx = None
    for i, line in enumerate(lines):
        if _PG_START_RE.search(line) and start_idx is None:
            start_idx = i
        if _PG_END_RE.search(line):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError("PG START OF / END OF markers not found")
    return lines[start_idx + 1 : end_idx]


def strip_ia_footer(text: str) -> str:
    """Truncate IA DjVu text at the first publisher catalog / library card sentinel.

    IA volumes include publisher advertisements and library catalog material after the
    last sermon. The sentinels in _IA_FOOTER_SENTINELS cover confirmed patterns across
    all Luther volumes; the final fallback is the library 'Date Due' card line.
    Returns the truncated text, or the original text if no sentinel is found.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for sentinel in _IA_FOOTER_SENTINELS:
            if sentinel.search(line):
                return "\n".join(lines[:i])
    return text


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def _fetch_url(url: str, dest_path: Path, log_lines: list) -> bool:
    """Download url to dest_path. Returns True on success.

    Follows HTTP redirects (IA CDN redirects). Retries on transient errors.
    Skips if already cached.
    """
    if dest_path.exists() and dest_path.stat().st_size > 0:
        log(f"    Cached: {dest_path.name}", log_lines)
        return True
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    delays = [0.0, *RETRY_DELAYS]
    for attempt, delay in enumerate(delays):
        if delay:
            log(f"    Retry {attempt}/{len(RETRY_DELAYS)} after {delay:.0f}s...", log_lines)
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as response:
                raw = response.read()
            dest_path.write_bytes(raw)
            log(f"    Saved {dest_path.name} ({len(raw):,} bytes)", log_lines)
            time.sleep(REQUEST_DELAY)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_STATUS_CODES:
                log(f"    HTTP {exc.code} (transient) for {url}", log_lines)
            else:
                log(f"    HTTP {exc.code} (permanent) for {url} -- skipping URL", log_lines)
                break
        except Exception as exc:
            log(f"    WARN: {url} failed: {exc}", log_lines)
    log(f"    ERROR: Download failed: {dest_path.name}", log_lines)
    return False


def download_ia_text(ia_id: str, dest_path: Path, log_lines: list) -> bool:
    """Download IA DjVu text file for the given IA identifier."""
    url = f"https://archive.org/download/{ia_id}/{ia_id}_djvu.txt"
    log(f"    GET {url}", log_lines)
    return _fetch_url(url, dest_path, log_lines)


def download_pg_text(pg_id: str, dest_path: Path, log_lines: list) -> bool:
    """Download PG plain text using the standard cache URL patterns."""
    url_patterns = [
        f"https://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt",
        f"https://www.gutenberg.org/files/{pg_id}/{pg_id}-0.txt",
        f"https://www.gutenberg.org/files/{pg_id}/{pg_id}.txt",
    ]
    for url in url_patterns:
        log(f"    GET {url}", log_lines)
        if _fetch_url(url, dest_path, log_lines):
            return True
    return False


# ---------------------------------------------------------------------------
# Luther parsing
# ---------------------------------------------------------------------------


def _is_luther_title_block(block: str) -> bool:
    """Return True if block looks like a Luther ALL-CAPS sermon title.

    Valid titles are short, mostly uppercase, and at least 5 characters.
    They must contain at least one word of 3+ characters (filters isolated
    numerals and single-letter lines).
    """
    s = block.strip()
    if len(s) < 5 or len(s) > 200:
        return False
    # Must have 3+ letter word
    words = s.split()
    if not any(len(w) >= 3 and w.isalpha() for w in words):
        return False
    alpha = [c for c in s if c.isalpha()]
    if len(alpha) < 4:
        return False
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    return upper_ratio >= 0.80


def _extract_luther_scripture_ref(text_line_tail: str) -> str | None:
    """Extract scripture reference from the tail of a 'Text:' line.

    Some DjVu volumes run the scripture ref and quotation together on the same
    line without a paragraph break. Strip everything after the first sentence
    break (period/exclamation/hyphen/comma + 2+ spaces + uppercase char).

    Comma-breaks are treated carefully: if the first word after the comma-break
    contains a digit, it is an OCR'd verse-number continuation (e.g. "Jf6" for
    "46") and NOT a prose sentence start — so that match is skipped.

    Returns a clean raw ref string or None.
    """
    raw = text_line_tail.strip()
    if not raw:
        return None
    # Iterate through candidate sentence-breaks; for comma-breaks, skip those
    # where the first token after the break contains a digit (OCR'd verse ref).
    found_break = None
    for m in _SCRIPTURE_BREAK_RE.finditer(raw):
        break_char = raw[m.start()]
        if break_char == ",":
            rest = raw[m.end() :].strip()
            first_tok = rest.split()[0] if rest.split() else ""
            if any(c.isdigit() for c in first_tok):
                continue  # OCR digit continuation — not a prose break
        found_break = m
        break
    if found_break:
        raw = raw[: found_break.start() + 1]
    # Strip trailing punctuation: period, hyphen, or comma at end of ref.
    raw = raw.strip().rstrip(".,- ")
    if not (any(c.isalpha() for c in raw) and any(c.isdigit() for c in raw)):
        return None
    return raw


def parse_luther_volume(
    vol_cfg: dict,
    text: str,
    sermon_num_start: int,
    log_lines: list,
) -> list:
    """Parse one Luther IA DjVu volume into a list of sermon entry dicts.

    Algorithm:
    1. Split text into blank-line-separated blocks.
    2. Find all blocks whose first line matches the 'Epistle/Gospel Text:' pattern.
    3. Each Text: block begins a sermon. Collect:
       a. Scripture ref from the Text: block itself.
       b. Title: first subsequent block that looks like an ALL-CAPS heading.
       c. Content: all blocks between the title (exclusive) and the next Text: block.
    4. Filter entries with word_count < 100 (catches stray blocks).
    """
    vol = vol_cfg["vol"]
    series_label = vol_cfg["series_label"]
    collection_id = "luther-lenker-sermons"

    # Strip publisher catalog and library card footer before parsing.
    text = strip_ia_footer(text)
    blocks = blocks_from_text(text)

    # Find all Text: block indices; require a digit in the tail to exclude body
    # sentences that happen to start with the word "text".
    text_indices = []
    for i, block in enumerate(blocks):
        m = _LUTHER_TEXT_LINE_RE.match(block)
        if m:
            tail = m.group(1).strip()
            if any(c.isdigit() for c in tail):
                text_indices.append((i, tail))

    if not text_indices:
        log(f"  WARNING: No Epistle/Gospel Text: markers found in vol {vol}", log_lines)
        return []

    entries = []
    sermon_num = sermon_num_start

    for idx, (ti, ref_tail) in enumerate(text_indices):
        next_ti = text_indices[idx + 1][0] if idx + 1 < len(text_indices) else len(blocks)

        # Blocks between this Text: marker and the next
        between = blocks[ti + 1 : next_ti]

        # Title: first block in 'between' that is ALL-CAPS (skip scripture quotation blocks)
        title_block_idx = None
        for j, b in enumerate(between):
            if _is_luther_title_block(b):
                title_block_idx = j
                break

        if title_block_idx is None:
            # Fallback: use the Text: block itself trimmed as title
            raw_title = blocks[ti].split(":")[0].strip()
            title = smart_title(raw_title)
            content_blocks = between
        else:
            raw_title = between[title_block_idx]
            # Gospel Sermon volumes (vols 4-8) prefix the title block with "CONTENTS:".
            # Strip the prefix so the title is the descriptive ALL-CAPS heading only.
            # Example: "CONTENTS: THE WITNESS AND CONFESSION OF JOHN THE BAPTIST"
            #       → "The Witness And The Confession Of John The Baptist"
            raw_title = _CONTENTS_PREFIX_RE.sub("", raw_title).strip().rstrip(".")
            title = smart_title(raw_title)
            content_blocks = between[title_block_idx + 1 :]

        total_words = word_count(content_blocks)
        if total_words < 100:
            continue

        # Scripture ref
        scripture_ref = _extract_luther_scripture_ref(ref_tail)

        entry: dict = {
            "collection_id": collection_id,
            "sermon_id": f"luther-lenker-v{vol:02d}-{sermon_num:04d}",
            "series": series_label,
            "title": title,
            "content_blocks": content_blocks,
            "word_count": total_words,
        }
        if scripture_ref:
            entry["primary_reference"] = {"raw": scripture_ref, "osis": []}

        entries.append(entry)
        sermon_num += 1

    return entries


# ---------------------------------------------------------------------------
# Newman parsing
# ---------------------------------------------------------------------------


def _extract_newman_title(sermon_block: str) -> str:
    """Extract the title from a Newman SERMON header block.

    Two cases:
    - Single-line: "SERMON I. THE LAPSE OF TIME."
    - Multi-line: "SERMON I." on first line, title on next line

    Returns title-cased string.
    """
    # Try to extract from the same block (after SERMON [numeral].)
    m = _NEWMAN_SERMON_RE.match(sermon_block)
    if not m:
        return "Untitled Sermon"

    # Text after the Roman numeral + punctuation
    tail = sermon_block[m.end():].strip().rstrip(".")
    if tail and len(tail) > 3:
        return smart_title(tail)

    # No inline title; use the next meaningful fragment
    parts = sermon_block.split("\n")
    for part in parts[1:]:
        stripped = part.strip().rstrip(".")
        if stripped and len(stripped) > 3:
            return smart_title(stripped)

    return f"Sermon {m.group(1)}"


def _extract_newman_scripture_ref(blocks_after_header: list) -> str | None:
    """Try to extract scripture reference from the 2-3 blocks following a sermon header.

    Newman's format: title block, then scripture ref on its own line/block
    (e.g. "Hebrews xii. 14."), then quotation.

    Returns the raw ref string or None if not confidently identified.
    """
    for block in blocks_after_header[:3]:
        stripped = block.strip()
        m = _NEWMAN_SCRIPTURE_RE.match(stripped)
        if m:
            ref = m.group(1).strip().rstrip(".")
            # Validate: must contain a digit (chapter/verse number)
            if any(c.isdigit() for c in ref):
                return ref
    return None


def _extract_newman_pg_ref(block: str) -> str | None:
    """Extract scripture ref embedded at end of a PG quotation block.

    PG format: '"_Whatsoever..._"--Eccles. ix. 10'
    Returns cleaned ref string or None.
    """
    m = _NEWMAN_DASH_REF_RE.search(block)
    if not m:
        return None
    ref = m.group(1).strip().rstrip(".")
    return ref if any(c.isdigit() for c in ref) else None


def parse_newman_volume(
    vol_cfg: dict,
    text: str,
    is_pg: bool,
    sermon_num_start: int,
    log_lines: list,
) -> list:
    """Parse one Newman volume into a list of sermon entry dicts.

    Algorithm:
    1. For PG text: strip PG header/footer first.
    2. Split into blank-line-separated blocks.
    3. Find all blocks matching 'SERMON [Roman numeral]' at block start.
    4. For each sermon block:
       a. Extract title from the header block.
       b. Look for scripture ref in the next 2-3 blocks.
       c. Collect content until the next SERMON marker.
    5. Filter entries with word_count < 100.
    """
    vol = vol_cfg["vol"]
    collection_id = "newman-parochial-sermons"

    if is_pg:
        try:
            body_lines = strip_pg_wrapper(text)
        except ValueError as exc:
            log(f"  ERROR: PG wrapper strip failed for vol {vol}: {exc}", log_lines)
            return []
        body_text = "\n".join(body_lines)
    else:
        body_text = text

    blocks = blocks_from_text(body_text)

    # Find all SERMON marker block indices
    sermon_indices = [
        i for i, b in enumerate(blocks)
        if _NEWMAN_SERMON_RE.match(b)
    ]

    if not sermon_indices:
        log(f"  WARNING: No SERMON markers found in Newman vol {vol}", log_lines)
        return []

    entries = []
    sermon_num = sermon_num_start

    for idx, si in enumerate(sermon_indices):
        next_si = sermon_indices[idx + 1] if idx + 1 < len(sermon_indices) else len(blocks)

        sermon_block = blocks[si]
        blocks_after = blocks[si + 1 : next_si]

        if is_pg:
            # PG format: SERMON block has only the numeral; title is in blocks_after[0];
            # scripture ref is embedded at end of quotation block (blocks_after[1]).
            if blocks_after:
                title = smart_title(blocks_after[0].strip().rstrip("."))
                content_start = 1
                scripture_ref = None
                if len(blocks_after) > 1:
                    scripture_ref = _extract_newman_pg_ref(blocks_after[1])
                    if scripture_ref:
                        content_start = 2
            else:
                m_head = _NEWMAN_SERMON_RE.match(sermon_block)
                title = f"Sermon {m_head.group(1)}" if m_head else "Untitled Sermon"
                content_start = 0
                scripture_ref = None
        else:
            # IA format: title is inline in the SERMON block; scripture ref is
            # on a standalone block immediately following.
            title = _extract_newman_title(sermon_block)
            scripture_ref = _extract_newman_scripture_ref(blocks_after[:3])
            content_start = 0
            if scripture_ref and blocks_after:
                for k, b in enumerate(blocks_after[:4]):
                    if _NEWMAN_SCRIPTURE_RE.match(b.strip()):
                        content_start = k + 1
                        if content_start < len(blocks_after):
                            nxt = blocks_after[content_start].strip()
                            if nxt.startswith(("'", '"', "\u2018")):
                                content_start += 1
                        break

        content_blocks = blocks_after[content_start:]
        total_words = word_count(content_blocks)

        if total_words < 100:
            continue

        entry: dict = {
            "collection_id": collection_id,
            "sermon_id": f"newman-pps-v{vol:02d}-{sermon_num:04d}",
            "series": f"vol-{vol}",
            "title": title,
            "content_blocks": content_blocks,
            "word_count": total_words,
            # null = intentionally absent (IA vols lack explicit "Text:" label per census notes)
            "primary_reference": {"raw": scripture_ref, "osis": []} if scripture_ref else None,
        }

        entries.append(entry)
        sermon_num += 1

    return entries


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(entries: list, label: str, log_lines: list) -> None:
    total = len(entries)
    if not total:
        log(f"  {label}: 0 sermons", log_lines)
        return
    with_ref = sum(1 for e in entries if e.get("primary_reference"))
    ref_pct = round(100 * with_ref / total)
    min_wc = min(e["word_count"] for e in entries)
    max_wc = max(e["word_count"] for e in entries)
    avg_wc = sum(e["word_count"] for e in entries) // total
    log(
        f"  {label}: {total} sermons | {with_ref}/{total} ({ref_pct}%) with ref "
        f"| wc min={min_wc} max={max_wc} avg={avg_wc}",
        log_lines,
    )


# ---------------------------------------------------------------------------
# Top-level runners
# ---------------------------------------------------------------------------


def run_luther(
    dry_run: bool,
    do_download: bool,
    do_parse: bool,
    target_vol: int | None,
    log_lines: list,
) -> bool:
    """Download and/or parse Luther volumes. Returns True on success."""
    start = time.time()
    vols = (
        [v for v in LUTHER_VOLUMES if v["vol"] == target_vol]
        if target_vol is not None
        else LUTHER_VOLUMES
    )
    if not vols:
        log(f"ERROR: Luther vol {target_vol} not in catalogue", log_lines)
        return False

    log(f"\n=== Luther Lenker Church Postil ({len(vols)} of {len(LUTHER_VOLUMES)} vols) ===",
        log_lines)

    hashes: dict = {}
    failed_download: list = []

    if do_download:
        log("\n-- Downloading (Luther) --", log_lines)
        for v in vols:
            dest = LUTHER_DIR / f"{v['ia_id']}_djvu.txt"
            ok = download_ia_text(v["ia_id"], dest, log_lines)
            if not ok:
                log(f"  ERROR: Could not download {v['ia_id']} -- skipping", log_lines)
                failed_download.append(v["vol"])
                continue
            hashes[v["vol"]] = compute_source_hash(dest)
            log(f"    Hash vol {v['vol']}: {hashes[v['vol']]}", log_lines)

        if failed_download:
            log(f"  WARNING: {len(failed_download)} vol(s) failed to download: {failed_download}",
                log_lines)

    if not do_parse:
        log(f"\n-- Download-only mode; skipping parse --", log_lines)
        return not bool(failed_download)

    # --- Parse ---
    log("\n-- Parsing (Luther) --", log_lines)
    all_entries: list = []
    serial = 1
    failed_parse: list = []

    for i, v in enumerate(vols, 1):
        if v["vol"] in failed_download:
            continue
        src = LUTHER_DIR / f"{v['ia_id']}_djvu.txt"
        if not src.exists():
            log(f"  ERROR: Source not found: {src.name} -- run --download first", log_lines)
            failed_parse.append(v["vol"])
            continue

        log(f"\n  [{i}/{len(vols)}] Luther vol {v['vol']} -- {v['title']}", log_lines)

        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log(f"  WARN: {src.name} is not valid UTF-8; falling back to latin-1", log_lines)
            text = src.read_text(encoding="latin-1")

        vol_entries = parse_luther_volume(v, text, serial, log_lines)
        if not vol_entries:
            log(f"  WARNING: Zero sermons extracted from vol {v['vol']}", log_lines)
        print_quality_stats(vol_entries, f"  Vol {v['vol']}", log_lines)

        all_entries.extend(vol_entries)
        serial += len(vol_entries)

    log(f"\n-- Luther total: {len(all_entries)} sermons --", log_lines)
    if all_entries:
        print_quality_stats(all_entries, "  Combined", log_lines)

    any_failure = bool(failed_download or failed_parse)

    if dry_run:
        log("\nDRY RUN -- first 3 Luther entries:", log_lines)
        for e in all_entries[:3]:
            log(
                f"  [{e['sermon_id']}] \"{e['title']}\" "
                f"| wc={e['word_count']} "
                f"| ref={e.get('primary_reference', {}).get('raw', 'None') if e.get('primary_reference') else 'None'}",
                log_lines,
            )
        elapsed = time.time() - start
        log(f"DRY RUN complete ({elapsed:.1f}s) -- no files written", log_lines)
        return not any_failure

    if not all_entries:
        log("ERROR: No Luther entries to write", log_lines)
        return False

    # Build combined source hash
    if hashes:
        combined_hash = "sha256:" + hashlib.sha256(
            "".join(hashes[v["vol"]] for v in vols if v["vol"] in hashes).encode()
        ).hexdigest()
    else:
        combined_hash = "sha256:" + "0" * 64

    volume_hash_notes = "; ".join(
        f"vol{v['vol']}={hashes[v['vol']]}" for v in vols if v["vol"] in hashes
    )

    meta = {
        "id": "luther-lenker-sermons",
        "title": "Luther's Church Postil (Lenker Translation)",
        "author": "Martin Luther",
        "author_id": "luther-martin",
        "author_birth_year": 1483,
        "author_death_year": 1546,
        "contributors": [
            {
                "role": "translator",
                "name": "John Nicholas Lenker",
            }
        ],
        "original_publication_year": 1903,
        "language": "en",
        "original_language": "de",
        "tradition": ["lutheran"],
        "tradition_notes": (
            "Martin Luther (1483-1546) was the primary figure of the German Reformation. "
            "His Church Postil (Kirchenpostille) comprises sermons on the lectionary texts "
            "for the church year, originally preached 1521-1522. The Lenker translation "
            "(1903-1909) covers both Epistle sermons (vols 7-9 of 'Precious and Sacred "
            "Writings') and Gospel sermons / Church Postil (vols 10-14)."
        ),
        "era": "reformation",
        "audience": "lay",
        "license": "public-domain",
        "schema_type": "sermon",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": (
                "https://archive.org/download/precioussacredwr07luth/"
                "precioussacredwr07luth_djvu.txt"
            ),
            "source_format": "DjVu OCR plain text",
            "source_edition": (
                "The Precious and Sacred Writings of Martin Luther, translated by "
                "John Nicholas Lenker; Lutherans in all Lands Co., Minneapolis, 1903. "
                "Internet Archive DjVu OCR text, identifiers precioussacredwr07luth "
                "through precioussacredwr14luth (8 volumes)."
            ),
            "download_date": DOWNLOAD_DATE,
            "source_hash": combined_hash,
            "processing_method": "ocr",
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d"
            ),
            "notes": append_pg_inline_markup_note(
                f"8 sermon volumes: vols 7-9 = Epistle Sermons (Church Postil on Epistles); "
                f"vols 10-14 = Gospel Sermons (Church Postil on Gospels). "
                f"Sermon boundaries detected by 'Epistle Text:' / 'Gospel Text:' markers. "
                f"Titles from subsequent ALL-CAPS heading block. "
                f"Scripture refs extracted from Text: line; empty osis (raw ref only). "
                f"Volume hashes: {volume_hash_notes}"
            ),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"meta": meta, "data": all_entries}
    with open(OUTPUT_FILE_LUTHER, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start
    log(f"\nWritten: {OUTPUT_FILE_LUTHER}", log_lines)
    log(f"  Total sermons: {len(all_entries)}", log_lines)
    log(f"  Elapsed: {elapsed:.1f}s", log_lines)
    if any_failure:
        log(
            f"  WARNING: Completed with failures -- "
            f"download={failed_download} parse={failed_parse}",
            log_lines,
        )
    return not any_failure


def run_newman(
    dry_run: bool,
    do_download: bool,
    do_parse: bool,
    target_vol: int | None,
    log_lines: list,
) -> bool:
    """Download and/or parse Newman volumes. Returns True on success."""
    start = time.time()
    vols = (
        [v for v in NEWMAN_VOLUMES if v["vol"] == target_vol]
        if target_vol is not None
        else NEWMAN_VOLUMES
    )
    if not vols:
        log(f"ERROR: Newman vol {target_vol} not in catalogue", log_lines)
        return False

    log(f"\n=== Newman Parochial and Plain Sermons ({len(vols)} of {len(NEWMAN_VOLUMES)} vols) ===",
        log_lines)

    hashes: dict = {}
    failed_download: list = []

    if do_download:
        log("\n-- Downloading (Newman) --", log_lines)
        for v in vols:
            if v["source"] == "ia":
                dest = NEWMAN_DIR / f"{v['ia_id']}_djvu.txt"
                ok = download_ia_text(v["ia_id"], dest, log_lines)
            else:
                dest = NEWMAN_DIR / f"pg{v['pg_id']}.txt"
                ok = download_pg_text(v["pg_id"], dest, log_lines)

            if not ok:
                log(f"  ERROR: Could not download Newman vol {v['vol']} -- skipping", log_lines)
                failed_download.append(v["vol"])
                continue
            hashes[v["vol"]] = compute_source_hash(dest)
            log(f"    Hash vol {v['vol']}: {hashes[v['vol']]}", log_lines)

        if failed_download:
            log(
                f"  WARNING: {len(failed_download)} vol(s) failed to download: {failed_download}",
                log_lines,
            )

    if not do_parse:
        log(f"\n-- Download-only mode; skipping parse --", log_lines)
        return not bool(failed_download)

    # --- Parse ---
    log("\n-- Parsing (Newman) --", log_lines)
    all_entries: list = []
    serial = 1
    failed_parse: list = []

    for i, v in enumerate(vols, 1):
        if v["vol"] in failed_download:
            continue
        is_pg = v["source"] == "pg"
        if is_pg:
            src = NEWMAN_DIR / f"pg{v['pg_id']}.txt"
        else:
            src = NEWMAN_DIR / f"{v['ia_id']}_djvu.txt"

        if not src.exists():
            log(f"  ERROR: Source not found: {src.name} -- run --download first", log_lines)
            failed_parse.append(v["vol"])
            continue

        log(f"\n  [{i}/{len(vols)}] Newman vol {v['vol']} ({'PG' if is_pg else 'IA'})", log_lines)

        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            log(f"  WARN: {src.name} is not valid UTF-8; falling back to latin-1", log_lines)
            text = src.read_text(encoding="latin-1")

        vol_entries = parse_newman_volume(v, text, is_pg, serial, log_lines)
        if not vol_entries:
            log(f"  WARNING: Zero sermons extracted from Newman vol {v['vol']}", log_lines)
        print_quality_stats(vol_entries, f"  Vol {v['vol']}", log_lines)

        all_entries.extend(vol_entries)
        serial += len(vol_entries)

    log(f"\n-- Newman total: {len(all_entries)} sermons --", log_lines)
    if all_entries:
        print_quality_stats(all_entries, "  Combined", log_lines)

    any_failure = bool(failed_download or failed_parse)

    if dry_run:
        log("\nDRY RUN -- first 3 Newman entries:", log_lines)
        for e in all_entries[:3]:
            log(
                f"  [{e['sermon_id']}] \"{e['title']}\" "
                f"| wc={e['word_count']} "
                f"| ref={e.get('primary_reference', {}).get('raw', 'None') if e.get('primary_reference') else 'None'}",
                log_lines,
            )
        elapsed = time.time() - start
        log(f"DRY RUN complete ({elapsed:.1f}s) -- no files written", log_lines)
        return not any_failure

    if not all_entries:
        log("ERROR: No Newman entries to write", log_lines)
        return False

    if hashes:
        combined_hash = "sha256:" + hashlib.sha256(
            "".join(hashes[v["vol"]] for v in vols if v["vol"] in hashes).encode()
        ).hexdigest()
    else:
        combined_hash = "sha256:" + "0" * 64

    volume_hash_notes = "; ".join(
        f"vol{v['vol']}={hashes[v['vol']]}" for v in vols if v["vol"] in hashes
    )

    meta = {
        "id": "newman-parochial-sermons",
        "title": "Parochial and Plain Sermons",
        "author": "John Henry Newman",
        "author_id": "newman-john-henry",
        "author_birth_year": 1801,
        "author_death_year": 1890,
        "contributors": [
            {
                "role": "editor",
                "name": "W. J. Copeland",
            }
        ],
        "original_publication_year": 1834,
        "language": "en",
        "original_language": "en",
        "tradition": ["anglican"],
        "tradition_notes": (
            "John Henry Newman (1801-1890) was an Anglican clergyman at St. Mary the "
            "Virgin, Oxford, who later converted to Roman Catholicism (1845). These 8 "
            "volumes of sermons, preached 1825-1843 and published 1834-1843 (Rivingtons), "
            "are widely regarded as the most influential Victorian Anglican sermon series. "
            "The 1868 Copeland edition (repr. Rivingtons) is used here."
        ),
        "era": "modern",
        "audience": "lay",
        "license": "public-domain",
        "schema_type": "sermon",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": (
                "https://archive.org/download/parochialplainse01newmuoft/"
                "parochialplainse01newmuoft_djvu.txt"
            ),
            "source_format": "DjVu OCR plain text (vols 1-6); Project Gutenberg plain text (vols 7-8)",
            "source_edition": (
                "Parochial and Plain Sermons, 8 vols., Rivingtons, London, 1868 "
                "(W.J. Copeland ed.). Internet Archive University of Toronto scans "
                "(vols 1-6: parochialplainse0{1-6}newmuoft); PG #24256 (vol 7), "
                "PG #24284 (vol 8)."
            ),
            "download_date": DOWNLOAD_DATE,
            "source_hash": combined_hash,
            "processing_method": "ocr-with-review",
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": datetime.now(timezone.utc).strftime(
                "%Y-%m-%d"
            ),
            "notes": append_pg_inline_markup_note(
                f"8 volumes. Vols 1-6 are IA DjVu OCR (1868 Rivingtons/Copeland ed., "
                f"University of Toronto scans); vols 7-8 are PG manually transcribed text. "
                f"Sermon boundaries detected by 'SERMON [Roman numeral]' heading. "
                f"Scripture refs extracted when clearly on a standalone line after title. "
                f"Volume hashes: {volume_hash_notes}"
            ),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"meta": meta, "data": all_entries}
    with open(OUTPUT_FILE_NEWMAN, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start
    log(f"\nWritten: {OUTPUT_FILE_NEWMAN}", log_lines)
    log(f"  Total sermons: {len(all_entries)}", log_lines)
    log(f"  Elapsed: {elapsed:.1f}s", log_lines)
    if any_failure:
        log(
            f"  WARNING: Completed with failures -- "
            f"download={failed_download} parse={failed_parse}",
            log_lines,
        )
    return not any_failure


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Luther Lenker and Newman PPS sermon collections"
    )
    parser.add_argument(
        "--series",
        choices=["luther", "newman", "all"],
        default="all",
        help="Which series to process (default: all)",
    )
    parser.add_argument(
        "--volume",
        type=int,
        metavar="N",
        help="Process only volume N within the chosen series",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download raw source files",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse downloaded files and write JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse but do not write output files",
    )
    args = parser.parse_args()

    # Default: if neither --download nor --parse is given and not --dry-run,
    # enable both for convenience.
    do_download = args.download
    do_parse = args.parse or args.dry_run
    if not do_download and not do_parse and not args.dry_run:
        do_download = True
        do_parse = True

    log_lines: list = []
    success = True
    try:
        if args.series in ("luther", "all"):
            ok = run_luther(
                dry_run=args.dry_run,
                do_download=do_download,
                do_parse=do_parse,
                target_vol=args.volume,
                log_lines=log_lines,
            )
            success = success and ok

        if args.series in ("newman", "all"):
            ok = run_newman(
                dry_run=args.dry_run,
                do_download=do_download,
                do_parse=do_parse,
                target_vol=args.volume,
                log_lines=log_lines,
            )
            success = success and ok

    except Exception as exc:
        log(f"FATAL: Unhandled exception: {exc}", log_lines)
        success = False
    finally:
        log(f"\nSUMMARY: {'SUCCESS' if success else 'FAILURE'}", log_lines)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
