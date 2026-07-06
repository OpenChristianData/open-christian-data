"""ia_schaff_herzog.py
Parser for Internet Archive _djvu.txt OCR files of the New Schaff-Herzog Encyclopedia
of Religious Knowledge (vols 3-8, 10-12).

These volumes are image-only on CCEL. Internet Archive has ABBYY FineReader OCR plain
text for all 9 via the NewSchaffHerzogEncyclopediaOfReligious collection.

This is a standalone script -- do NOT modify ccel_schaff_herzog.py.

Format: Google Books DjVu-derived plain text (_djvu.txt).
  - Words use double-spaces (OCR artifact from typeset source), normalized to single.
  - Article headings come in two forms:
      Inline: 'TERM_IN_CAPS: body text starts here'  (most common)
      Standalone: 'TERM_IN_CAPS:' on its own line, body follows on next lines
  - Running page headers ('THE NEW SCHAFF-HERZOG', 'RELIGIOUS ENCYCLOPEDIA') appear
    ~240 times per volume without colons -- always excluded from body text.
  - Front matter (~first 2600 lines): Google Books watermark, title page, editors,
    abbreviation table, transliteration/pronunciation keys -- skipped automatically
    by detecting the first article heading.
  - Page markers (standalone digits, volume markers like 'III.- 1') are skipped.

Source:
  Collection: NewSchaffHerzogEncyclopediaOfReligious
  URL: https://archive.org/download/NewSchaffHerzogEncyclopediaOfReligious/<filename>
  Format: _djvu.txt (ABBYY FineReader OCR, ~95-97% accuracy)
  All volumes US public domain (1908-1914, pre-1928).

Merges additively into data/reference/schaff-herzog-encyclopedia.json alongside the
2,386 CCEL entries (vols 1, 2, 9). Re-run safe: existing entry_ids are preserved.

Usage:
    py -3 build/parsers/ia_schaff_herzog.py --volume 3          # single volume
    py -3 build/parsers/ia_schaff_herzog.py --volume 3 --dry-run
    py -3 build/parsers/ia_schaff_herzog.py --all               # all 9 IA volumes
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib._generated_enums import (
    REFERENCE_ENTRY__META__COMPLETENESS,
    REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD,
    REFERENCE_ENTRY__META__TRADITION,
)
from build.lib.text_layers import assert_surface_field_invariant, build_reference_layers
from build.lib.text_utils import normalize_line

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
IA_RAW_DIR = REPO_ROOT / "raw" / "internet-archive" / "schaff-herzog"
CCEL_RAW_DIR = REPO_ROOT / "raw" / "ccel" / "schaff-herzog"
OUTPUT_DIR = REPO_ROOT / "data" / "reference"
OUTPUT_FILE = OUTPUT_DIR / "schaff-herzog-encyclopedia.json"
LOG_PATH = REPO_ROOT / "logs" / "ia_schaff_herzog.log"

SCHEMA_VERSION = "2.1.0"
DICTIONARY_ID = "schaff-herzog-encyclopedia"

for _t in ["ecumenical", "evangelical"]:
    assert _t in REFERENCE_ENTRY__META__TRADITION, f"invalid tradition {_t!r}"
assert "full" in REFERENCE_ENTRY__META__COMPLETENESS, "invalid completeness 'full'"
assert "automated" in REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD, "invalid processing_method 'automated'"

USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)
DOWNLOAD_DELAY_SECONDS = 10

IA_BASE_URL = (
    "https://archive.org/download/NewSchaffHerzogEncyclopediaOfReligious/{filename}"
)

# Ordered map of volume number -> IA _djvu.txt filename
IA_VOLUMES = {
    3: "03.NewSchaffHerzogEncycReligKnowl.v3.1909.Jackson.Sherman.Gilmore.1909._djvu.txt",
    4: "04.NewSchaffHerzogEncycReligKnowl.BibliogApend.v1-4.v4.Jackson.Sherman.Gilmore.1909._djvu.txt",
    5: "05.NewSchaffHerzogEncycReligKnowl.v5.Jackson.Sherman.Gilmore.1909._djvu.txt",
    6: "06.NewSchaffHerzogEncycReligKnowl.v6.Jackson.Sherman.Gilmore.1909._djvu.txt",
    7: "07.NewSchaffHerzogEncycReligKnowl.v7.Jackson.Sherman.Gilmore.1909._djvu.txt",
    8: "08.NewSchaffHerzogEncycReligKnowl.v8.Jackson.Sherman.Gilmore.1909._djvu.txt",
    10: "10.NewSchaffHerzogEncyc.ReligKnowl.v10.Jackson.Sherman.Gilmore.1909._djvu.txt",
    11: "11.NewSchaffHerzogEncyc.ReligKnowl.v11.Jackson.Sherman.Gilmore.1911._djvu.txt",
    12: "12.NewSchaffHerzogEncyc.ReligKnowl.v12.Jackson.Sherman.Gilmore.1912._djvu.txt",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure file + console logging. Log file at logs/ia_schaff_herzog.log."""
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
# Download helpers
# ---------------------------------------------------------------------------


def download_volume(vol_num: int) -> Path:
    """Download one _djvu.txt volume if not already cached. Returns local path."""
    IA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    filename = IA_VOLUMES[vol_num]
    local_path = IA_RAW_DIR / filename

    if local_path.exists():
        logger.info("  Cached: %s (%s)", filename, _human_size(local_path.stat().st_size))
        return local_path

    url = IA_BASE_URL.format(filename=filename)
    logger.info("  Downloading %s ...", url)

    last_exc: Exception | None = None
    for attempt in range(3):
        if attempt:
            delay = 2 ** attempt
            logger.warning("  Retry %d/2 for vol %d after %ds ...", attempt, vol_num, delay)
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as resp:
                status = resp.getcode()
                if status not in (200, 206):
                    raise RuntimeError(f"HTTP {status}")
                data = resp.read()
            with open(str(local_path), "wb") as f:
                f.write(data)
            size_kb = len(data) / 1024
            file_hash = hashlib.sha256(data).hexdigest()
            logger.info("  Downloaded %.0f KB -> %s", size_kb, filename)
            logger.info("  SHA-256: %s", file_hash)
            print(f"  SHA-256 (vol {vol_num}): {file_hash}")
            return local_path
        except Exception as exc:
            last_exc = exc
            logger.warning("  Download attempt %d failed for vol %d: %s", attempt + 1, vol_num, exc)

    raise RuntimeError(
        f"Download failed for vol {vol_num} ({filename}) after 3 attempts: {last_exc}. "
        f"Check network access and try again."
    ) from last_exc


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------


def normalize_text_block(text: str) -> str:
    """Normalize a full body block: collapse whitespace, strip edges."""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Line classification helpers
# ---------------------------------------------------------------------------


def is_article_heading(norm: str) -> bool:
    """True if normalized line is an article heading.

    Three valid forms:
      Form 1 (inline):       CAPS_TERM: body text starts on same line
      Form 2 (standalone+:): CAPS_TERM: (entire line, colon at end; body on next lines)
      Form 3 (standalone):   CAPS_TERM  (entire line ALL CAPS, no colon; long article names)

    Detection rules:
      - Starts with 2+ consecutive uppercase letters
      - Is NOT a running page header (excluded before this check)
      - Is NOT a Roman-numeral section header (I., II., etc.)
      - Either: contains ':', OR: entire stripped line is ALL CAPS with >= 4 alpha chars

    Notes:
      - Running headers ('THE NEW SCHAFF-HERZOG', 'RELIGIOUS ENCYCLOPEDIA', section
        header 'ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE') are excluded by is_running_header.
      - Body lines starting with 'See AARON: ...' fail because 'S' then 'e' is not 2+
        consecutive uppercase letters.
      - Multi-line headings (e.g. 'CHANDIEU, ... DE LA / ROCHE:' split across two OCR
        lines) will be incorrectly split; this is an inherent OCR limitation.
    """
    # Must start with 2+ consecutive uppercase letters
    if not re.match(r"^[A-Z]{2}", norm):
        return False
    # End-of-volume markers: "END OF VOL.", "END OF VOLUME" etc.
    if re.match(r"^END\s+OF\s+(VOL[\.,]?|VOLUME)\b", norm, re.IGNORECASE):
        return False
    # Skip running headers and section headers
    if is_running_header(norm):
        return False
    # Roman-numeral section headers within article body (e.g. 'I. History:', 'II. Doctrine:')
    if re.match(r"^[IVXLCDM]+\.?\s", norm):
        return False
    # Form 1 & 2: contains ':'
    if ":" in norm:
        return True
    # Form 3: entire line is ALL CAPS with enough alpha content
    stripped = norm.strip()
    if stripped == stripped.upper():
        alpha_count = sum(1 for c in stripped if c.isalpha())
        if alpha_count >= 4:
            return True
    # Form 4: cross-reference article -- "HEADWORD. See TARGET."
    if re.match(r"^[A-Z][A-Z ,\-]*\.\s+See\b", norm):
        return True
    # Form 5: pronunciation-guide -- "HEADWORD, phonetic." where phonetic is a
    # single lowercase token ending with a period, e.g. "GEZER, gi'zer."
    # Single-token check (no spaces) discriminates from body text ("PAUL, the apostle").
    # Apostrophe-agnostic: OCR may produce U+2019 or straight quote.
    m = re.match(r"^([A-Z][A-Z ,\-]*),\s+([a-z].*)$", norm)
    if m and re.match(r"^[a-z][^\s.]+\.$", m.group(2)):
        return True
    return False


def is_running_header(norm: str) -> bool:
    """True if line is a structural header to skip (running page headers, section headers).

    Uses fragment matching (not exact strings) to handle OCR digit-substitution
    and truncation across all 9 IA volumes.  Fragments tested:

      - SCHAFF|CHAFF + HERZ: left-side running header 'THE NEW SCHAFF-HERZOG'
        and variants like '8CHAFF-HERZ0G' (digits sub for letters).
      - TH[A-Z] prefix + SCHAFF|CHAFF or HERZ: covers 'THE' OCR'd to 'THB',
        'TH?' etc. when only one name fragment survives.
      - ENCY|NCYCL + RELIG or short line: right-side header 'RELIGIOUS ENCYCLOPEDIA'
        and variants like 'ENCYCLOPEDU', 'BNCYCLOFEDIA'.
      - RELIG + KNOWLEDGE: right-side header 'RELIGIOUS KNOWLEDGE' (8 of 9 volumes).
      - Lines starting with 'THE ': no legitimate article begins this way.

    Article headings always contain ':'; these structural headers never do.
    """
    if ":" in norm:
        return False
    if norm.upper().startswith("THE "):
        return True

    # Strip non-alpha characters and normalize whitespace for fuzzy matching
    alpha_only = re.sub(r"[^A-Z ]", "", norm.upper())
    alpha_only = re.sub(r"\s+", " ", alpha_only).strip()

    # SCHAFF-HERZOG variants: require both fragments so 'SCHAFF, PHILIP' is not caught.
    # After stripping digits/punctuation '8CHAFF-HERZ0G' -> 'CHAFF HERZG' etc.
    schaff_frag = bool(re.search(r"SCHAFF|CHAFF", alpha_only))
    herz_frag = "HERZ" in alpha_only
    if schaff_frag and herz_frag:
        return True
    # 'THB NEW SCHAFF-HERZOQ' etc: 'THE' OCR'd to 'THB', 'TH?' etc.
    if re.match(r"^TH[A-Z] ", alpha_only) and (schaff_frag or herz_frag):
        return True

    # RELIGIOUS ENCYCLOPEDIA variants (fragment matching):
    # 'ENCY' covers ENCYCLOP*, ENCVCLOPEDIA, ENCTCLOPEDIA, ENCYCLOPEDU, etc.
    # 'NCYCL' covers left-edge corruption: 'BNCYCLOFEDIA' etc.
    has_encycl = bool(re.search(r"ENCY|NCYCL", alpha_only))
    # 'RELIG' covers RELIGIOUS, REUGIOUS, RBUGIOUS, EEUQIOUS etc. after stripping non-alpha
    has_relig = "RELIG" in alpha_only
    if has_encycl and (has_relig or len(alpha_only) < 30):
        return True

    # 'RELIGIOUS KNOWLEDGE' standalone right-side header (appears in 8 of 9 volumes)
    if has_relig and "KNOWLEDGE" in alpha_only:
        return True

    return False


def is_page_marker(norm: str) -> bool:
    """True if line is a page/column marker to skip (not body text).

    Matches:
      - Standalone year or page numbers ('1900', '244')
      - Volume-chapter markers ('III.- 1', 'VIII.- 32', 'VIII.- 1')
      - Very short lines that are OCR artifacts (<= 3 chars)
    """
    stripped = norm.strip()
    if not stripped:
        return False
    # Standalone digits (page numbers, years)
    if re.match(r"^\d+\s*$", stripped):
        return True
    # Volume-chapter marker: Roman numerals + separator + digits
    if re.match(r"^[IVXLCDM]+[\s.\u2014\u2013-]+\d", stripped.upper()):
        return True
    # Very short (likely OCR garbage)
    if len(stripped) <= 3 and not any(c.isalpha() for c in stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# Term extraction helpers
# ---------------------------------------------------------------------------


def extract_term_and_inline_body(norm: str) -> tuple:
    """Split an article heading line into (term, inline_body).

    Three forms:
      Form 1 (inline):       'TERM: body text here' -> ('TERM', 'body text here')
      Form 2 (standalone+:): 'TERM:'               -> ('TERM', None)
      Form 3 (standalone):   'TERM' or 'TERM.'     -> ('TERM', None)

    The term is cleaned: pronunciation guides (lowercase segments) stripped.
    """
    # Form 2: line ends with ':' (no body on this line)
    if norm.endswith(":"):
        raw_term = norm[:-1].strip()
        inline_body = None
    else:
        # Form 1: split on first colon followed by one or more spaces.
        # Use re.search to handle OCR whitespace variants (': ', ':  ', ':\t').
        _m = re.search(r":\s+", norm)
        if _m:
            # Form 1: colon-space = term/body boundary
            raw_term = norm[:_m.start()].strip()
            inline_body = norm[_m.end():].strip() or None
        else:
            # Form 3: standalone ALL CAPS, no colon (long article names)
            raw_term = norm.strip()
            # Strip trailing period (article names sometimes end with '.')
            if raw_term.endswith("."):
                raw_term = raw_term[:-1].strip()
            inline_body = None

    term = clean_term(raw_term)
    return term, inline_body


_CORRECTIONS_FILE = (
    Path(__file__).resolve().parent.parent
    / "tools" / "ocr_scanner" / "corrections" / "schaff-herzog.json"
)


def _load_ocr_corrections(path: Path) -> dict[str, str]:
    """Load corrections table as {normalized_upper_bad: good} dict.

    Returns empty dict if the file doesn't exist (graceful degradation).
    Key is the bad value after double-space normalisation and upper-casing,
    matching the normalisation applied in clean_term().
    """
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        re.sub(r"  +", " ", c["bad"]).strip().upper(): c["good"]
        for c in data.get("corrections", [])
    }


_OCR_CORRECTIONS = _load_ocr_corrections(_CORRECTIONS_FILE)


def clean_term(raw_term: str) -> str:
    """Extract the article name from raw heading text.

    Strips pronunciation guides (lowercase segments interspersed in the heading).
    Example: 'CHAMIER, ahd/mye, DANIEL' -> 'CHAMIER, DANIEL'

    If no uppercase segments survive, returns the full raw_term as fallback.
    """
    # Apply corrections from the scanner corrections table before anything else
    normalized_upper = re.sub(r"  +", " ", raw_term).strip().upper()
    if normalized_upper in _OCR_CORRECTIONS:
        return _OCR_CORRECTIONS[normalized_upper]

    # Normalize double-spaces first
    normalized = re.sub(r"  +", " ", raw_term).strip()

    # Split on commas and check each segment
    parts = [p.strip() for p in normalized.split(",")]
    upper_parts = []
    for part in parts:
        if not part:
            continue
        # Keep if all alphabetic characters are uppercase (allows digits, punctuation)
        alpha_chars = [c for c in part if c.isalpha()]
        if not alpha_chars:
            continue
        upper_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        if upper_ratio >= 0.70:
            upper_parts.append(part)

    if upper_parts:
        return ", ".join(upper_parts)

    # Fallback: return normalized raw term
    return normalized


# ---------------------------------------------------------------------------
# Slugify and ID helpers (replicated from ccel_schaff_herzog.py -- DO NOT import)
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Convert term text to URL-safe lowercase slug (same as ccel_schaff_herzog.py)."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text.strip())
    text = text.strip("-")
    return text or "entry"


def make_unique_id(base: str, seen: set) -> str:
    """Return base if not in seen, else base-2, base-3, etc. (PIPE-04)."""
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Volume text parser
# ---------------------------------------------------------------------------


def parse_volume_text(text: str, vol_num: int) -> list:
    """Parse all encyclopedia articles from _djvu.txt text.

    Returns a list of raw article dicts:
      {term, definition_blocks, vol_num}
    """
    lines = text.splitlines()
    logger.info("  Vol %d: %d lines total", vol_num, len(lines))

    # --- Find front matter boundary ---
    # Strategy 1: look for 'ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE', a section header that
    # reliably marks the start of the A-Z article body in every volume. Start parsing
    # from the first non-empty line after this marker.
    # Strategy 2 (fallback): first line where is_article_heading() returns True.
    # Strategy 1 is needed because some volumes (e.g. vol 8) have contributor entries
    # in the format 'NAME: DEGREE' that would falsely trigger is_article_heading.
    BODY_MARKER = "ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE"
    body_start = None

    _BODY_MARKER_RE = re.compile(
        r"ENCYCLOPEDIA\s+OF\s+RELI\w+\s+KNOWLEDGE", re.IGNORECASE
    )

    for i, line in enumerate(lines):
        norm = normalize_line(line).strip()
        # Use regex to tolerate OCR variants:
        #   vol 10: "ENCYCLOPEDIA OF RELIGIODS KNOWLEDGE" (RELI→RELIGIODS)
        #   vol 12: "ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE^" (trailing artifact)
        if _BODY_MARKER_RE.search(norm) and len(norm) < 50:
            # Found section header. body_start = first non-empty line after it.
            for j in range(i + 1, len(lines)):
                norm_j = normalize_line(lines[j]).strip()
                if norm_j:
                    body_start = j
                    break
            logger.info(
                "  Vol %d: body marker found at line %d; body starts at line %d",
                vol_num, i + 1, body_start + 1 if body_start is not None else -1,
            )
            break

    if body_start is None:
        # Fallback: first is_article_heading line
        logger.warning(
            "  Vol %d: body marker not found -- falling back to first heading detection",
            vol_num,
        )
        for i, line in enumerate(lines):
            norm = normalize_line(line)
            if is_article_heading(norm):
                body_start = i
                break

    if body_start is None:
        logger.error("  Vol %d: no article body start found -- check file format", vol_num)
        return []

    logger.info("  Vol %d: front matter ends at line %d; first content: %s",
                vol_num, body_start + 1, normalize_line(lines[body_start])[:60])

    # --- Main parsing loop ---
    articles = []
    current_term = None
    current_inline_body = None  # remainder of heading line after ': '
    current_body_parts = []     # accumulated non-empty lines for this article
    current_source_body_parts = []
    current_paragraph = []      # current paragraph (lines since last blank)
    current_source_paragraph = []

    def _flush_article() -> None:
        """Commit current_paragraph into current_body_parts."""
        nonlocal current_paragraph, current_source_paragraph
        if current_paragraph:
            current_body_parts.append(" ".join(current_paragraph))
            current_paragraph = []
        if current_source_paragraph:
            current_source_body_parts.append(" ".join(current_source_paragraph))
            current_source_paragraph = []

    def _save_article() -> None:
        """Save the current article to the articles list."""
        nonlocal current_term, current_body_parts, current_source_body_parts, current_paragraph, current_source_paragraph, current_inline_body
        _flush_article()
        if current_term is not None:
            blocks = [b for b in current_body_parts if b.strip()]
            source_blocks = [b for b in current_source_body_parts if b.strip()]
            # Reject numeric table fragments: entries whose entire body contains
            # no alphabetic characters (e.g. "36,770" — OCR table rows ingested as articles)
            body_text = " ".join(blocks)
            if blocks and not re.search(r"[A-Za-z]", body_text):
                logger.debug(
                    "  Vol %d: skipping numeric-body entry %r (body: %r)",
                    vol_num, current_term, body_text[:80],
                )
                current_term = None
                current_inline_body = None
                current_body_parts = []
                current_source_body_parts = []
                current_paragraph = []
                current_source_paragraph = []
                return
            articles.append({
                "term": current_term,
                "definition_blocks": blocks,
                "source_raw_definition_blocks": source_blocks,
                "vol_num": vol_num,
            })
        current_term = None
        current_inline_body = None
        current_body_parts = []
        current_source_body_parts = []
        current_paragraph = []
        current_source_paragraph = []

    for line in lines[body_start:]:
        norm = normalize_line(line)
        source_line = line.strip()

        # Empty line: paragraph boundary
        if not norm.strip():
            _flush_article()
            continue

        # Running header: skip entirely
        if is_running_header(norm):
            continue

        # Page marker: skip entirely
        if is_page_marker(norm):
            continue

        # Check for new article heading
        if is_article_heading(norm):
            _save_article()
            term, inline_body = extract_term_and_inline_body(norm)
            current_term = term
            current_inline_body = inline_body
            # Inline body starts the first paragraph
            if inline_body:
                current_paragraph.append(inline_body)
                current_source_paragraph.append(inline_body)
        else:
            # Body text: append to current paragraph
            if current_term is not None:
                current_paragraph.append(norm.strip())
                current_source_paragraph.append(source_line)

    # Save the last article
    _save_article()

    logger.info("  Vol %d: parsed %d raw articles", vol_num, len(articles))
    return articles


def parse_volume(vol_num: int) -> list:
    """Download and parse one volume. Returns list of raw article dicts."""
    local_path = download_volume(vol_num)
    logger.info("  Parsing vol %d from %s ...", vol_num, local_path.name)

    raw_bytes = local_path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("  Vol %d: UTF-8 decode failed, falling back to latin-1", vol_num)
        text = raw_bytes.decode("latin-1", errors="replace")

    return parse_volume_text(text, vol_num)


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------


def compute_combined_source_hash() -> str:
    """Hash all cached source files (CCEL + IA) for a deterministic fingerprint."""
    combined = hashlib.sha256()
    # CCEL files (vols 1, 2, 9 -- already processed)
    if CCEL_RAW_DIR.exists():
        for path in sorted(CCEL_RAW_DIR.glob("*.xml")):
            combined.update(path.read_bytes())
    # IA files (vols 3-8, 10-12)
    for path in sorted(IA_RAW_DIR.glob("*.txt")):
        combined.update(path.read_bytes())
    return "sha256:" + combined.hexdigest()


def build_meta(ia_vols_processed: list) -> dict:
    """Build updated meta envelope for the combined CCEL + IA output file."""
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_hash = compute_combined_source_hash()
    ia_vol_labels = ", ".join(f"vol{v}" for v in sorted(ia_vols_processed))
    return {
        "id": DICTIONARY_ID,
        "title": "New Schaff-Herzog Encyclopedia of Religious Knowledge",
        "author": "Samuel Macauley Jackson",
        "original_publication_year": 1908,
        "language": "en",
        "tradition": ["ecumenical", "evangelical"],
        "tradition_notes": (
            "The New Schaff-Herzog (1908-1914) is the leading English-language Protestant "
            "reference work of the early 20th century, edited by Samuel Macauley Jackson. "
            "It reflects broadly ecumenical Reformed and Lutheran scholarship, drawing on "
            "German Realencyklopaedie fuer protestantische Theologie und Kirche (3rd ed.) "
            "with significant English additions."
        ),
        "license": "public-domain",
        "schema_type": "reference_entry",
        "schema_version": SCHEMA_VERSION,
        "text_layer_shape": "multi_field",
        "completeness": "full",
        "provenance": {
            "source_url": (
                "https://www.ccel.org/ccel/schaff/ (vols 1, 2, 9); "
                "https://archive.org/details/NewSchaffHerzogEncyclopediaOfReligious (vols 3-8, 10-12)"
            ),
            "source_format": "ThML XML (CCEL vols 1, 2, 9); _djvu.txt OCR (IA vols 3-8, 10-12)",
            "source_edition": (
                "New Schaff-Herzog Encyclopedia of Religious Knowledge, 13 vols, 1908-1914"
            ),
            "download_date": process_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": "build/parsers/ia_schaff_herzog.py@v1.0.0",
            "processing_date": process_date,
            "notes": (
                f"Complete acquisition: vols 1, 2, 9 from CCEL ThML XML (2,386 entries); "
                f"vols 3-8, 10-12 from IA _djvu.txt OCR ({ia_vol_labels}). "
                "Vols 3-8 and 10-12 are image-only on CCEL (no machine-readable text). "
                "Vol 13 is the index (0 usable entries). "
                "IA OCR: ABBYY FineReader ~95-97% character accuracy. "
                "All volumes US public domain (1908-1914, pre-1928). "
                "Permission confirmed: CCEL (Quincy, 2026-04-01). "
                "source_hash is combined SHA-256 of all downloaded source files (CCEL + IA)."
            ),
        },
    }


def build_entry(raw_article: dict, seen_ids: set, *, emit_layers: bool = False) -> dict:
    """Convert raw article dict to OCD reference_entry record."""
    term = raw_article["term"]
    base_id = f"schaff-herzog.{slugify(term)}"
    entry_id = make_unique_id(base_id, seen_ids)
    seen_ids.add(entry_id)

    blocks = raw_article["definition_blocks"]
    word_count = sum(len(b.split()) for b in blocks)

    entry = {
        "entry_id": entry_id,
        "dictionary_id": DICTIONARY_ID,
        "term": term,
        "alt_terms": [],
        "definition_blocks": blocks,
        "scripture_references": [],
        "related_terms": [],
        "word_count": word_count,
    }
    if emit_layers:
        layers = build_reference_layers(
            term=term,
            alt_terms=[],
            definition_blocks=blocks,
            source_raw_term=raw_article.get("source_raw_term", term),
            normalised_term=raw_article.get("normalised_term", term),
            source_raw_blocks=raw_article.get("source_raw_definition_blocks", blocks),
            normalised_blocks=raw_article.get("normalised_definition_blocks", blocks),
            source_raw_origin="observed",
        )
        if layers:
            entry["layers"] = layers
        assert_surface_field_invariant(entry, text_layer_shape="multi_field")
    return entry


# ---------------------------------------------------------------------------
# Load / merge / save
# ---------------------------------------------------------------------------


def load_existing_output() -> tuple:
    """Load existing output file. Returns (meta_or_None, entries_by_id_dict)."""
    if not OUTPUT_FILE.exists():
        return None, {}

    try:
        with open(str(OUTPUT_FILE), encoding="utf-8") as f:
            existing = json.load(f)
        entries_by_id = {e["entry_id"]: e for e in existing.get("data", [])}
        meta = existing.get("meta")
        logger.info("  Loaded existing output: %d entries", len(entries_by_id))
        return meta, entries_by_id
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("  Could not read existing output (%s) -- starting fresh", exc)
        return None, {}


def save_output(entries_by_id: dict, ia_vols_processed: list) -> None:
    """Write merged output JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = build_meta(ia_vols_processed)
    data = list(entries_by_id.values())
    output = {"meta": meta, "data": data}

    with open(str(OUTPUT_FILE), "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    logger.info("  Wrote %d entries -> %s (%.0f KB)", len(data), OUTPUT_FILE.name, size_kb)


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(entries: list, label: str) -> None:
    """Print quality stats for entries from one volume (PIPE-02)."""
    n = len(entries)
    if n == 0:
        logger.warning("  No entries to report quality stats for (%s)", label)
        return

    empty_blocks = sum(1 for e in entries if not e["definition_blocks"])
    words = sorted(e["word_count"] for e in entries)
    median_words = words[n // 2]
    short_entries = sum(1 for e in entries if e["word_count"] < 5)
    empty_rate = 100 * empty_blocks / n

    logger.info("  Quality stats for %s (%d entries):", label, n)
    logger.info("    definition_blocks empty: %d/%d (%.1f%%)", empty_blocks, n, empty_rate)
    logger.info(
        "    word_count: min=%d median=%d max=%d",
        words[0], median_words, words[-1],
    )
    if short_entries:
        logger.info("    entries under 5 words (cross-ref stubs): %d/%d", short_entries, n)

    # Threshold checks
    if empty_rate >= 5.0:
        logger.warning("  THRESHOLD FAIL: empty_rate %.1f%% >= 5%% for %s", empty_rate, label)
    if median_words < 50:
        logger.warning(
            "  THRESHOLD FAIL: median word_count %d < 50 for %s", median_words, label
        )


# ---------------------------------------------------------------------------
# Main processing logic
# ---------------------------------------------------------------------------


def process_volume(vol_num: int, dry_run: bool = False, *, emit_layers: bool = False) -> dict:
    """Process one IA volume: download, parse, merge into output file.

    In dry-run mode: parse only, do not write files. Prints first 3 entries.
    Returns a stats dict.
    """
    logger.info("--- Processing vol %d ---", vol_num)

    raw_articles = parse_volume(vol_num)

    if not raw_articles:
        logger.error("  Vol %d: no articles found -- check file format", vol_num)
        return {"vol": vol_num, "status": "error", "entry_count": 0}

    # Filter: skip entries with empty definition_blocks (schema requires minItems: 1)
    valid_articles = [a for a in raw_articles if a["definition_blocks"]]
    skipped_empty = len(raw_articles) - len(valid_articles)
    if skipped_empty:
        logger.warning(
            "  Vol %d: skipping %d entries with empty definition_blocks",
            vol_num, skipped_empty,
        )

    if dry_run:
        seen_ids: set = set()
        entries = [build_entry(a, seen_ids, emit_layers=emit_layers) for a in valid_articles]
        logger.info("  [dry-run] vol %d: %d articles -> %d entries", vol_num, len(raw_articles), len(entries))
        for e in entries[:3]:
            logger.info(
                "  [dry-run]   id=%s  blocks=%d  words=%d",
                e["entry_id"], len(e["definition_blocks"]), e["word_count"],
            )
        print_quality_stats(entries, f"vol{vol_num}")
        return {"vol": vol_num, "status": "dry-run", "entry_count": len(entries)}

    # Load existing, merge new
    _existing_meta, entries_by_id = load_existing_output()
    pre_merge_count = len(entries_by_id)

    # Initialize seen_ids from existing entries. Re-run idempotency: when base_id
    # already exists in the output, discard it from seen_ids first so make_unique_id
    # returns the original base_id (overwriting the existing entry) rather than
    # generating a base_id-2 duplicate (same fix as ccel_schaff_herzog.py).
    seen_ids = set(entries_by_id.keys())
    new_entries = []
    overwritten = 0

    for raw_article in valid_articles:
        base_id = f"schaff-herzog.{slugify(raw_article['term'])}"
        if base_id in entries_by_id:
            seen_ids.discard(base_id)
            overwritten += 1
        entry = build_entry(raw_article, seen_ids, emit_layers=emit_layers)
        entries_by_id[entry["entry_id"]] = entry
        new_entries.append(entry)

    post_merge_count = len(entries_by_id)
    added_count = post_merge_count - pre_merge_count
    truly_new = len(new_entries) - overwritten

    if added_count != truly_new:
        logger.warning(
            "  MERGE MISMATCH: added_count=%d but truly_new=%d "
            "(unexpected duplicates or missing entries -- total: %d)",
            added_count, truly_new, post_merge_count,
        )

    logger.info(
        "  Merged: %d pre-existing + %d new = %d total (added %d, overwrote %d)",
        pre_merge_count, len(new_entries), post_merge_count, added_count, overwritten,
    )

    # Determine which IA vols are now represented
    # (read from stats tracking, not from meta parsing)
    save_output(entries_by_id, [vol_num])  # updated below

    print_quality_stats(new_entries, f"vol{vol_num}")

    # PIPE-19: verify entry count after merge
    with open(str(OUTPUT_FILE), encoding="utf-8") as f:
        on_disk = json.load(f)
    on_disk_count = len(on_disk.get("data", []))
    if on_disk_count != post_merge_count:
        logger.error(
            "  PIPE-19 FAIL: on-disk count %d != in-memory count %d",
            on_disk_count, post_merge_count,
        )
    else:
        logger.info("  PIPE-19 OK: on-disk count matches in-memory (%d)", on_disk_count)

    return {
        "vol": vol_num,
        "status": "ok",
        "entry_count": len(new_entries),
        "skipped_empty": skipped_empty,
        "total_after_merge": post_merge_count,
    }


def rebuild_meta_with_all_ia_vols(ia_vols: list) -> None:
    """After all volumes processed, rewrite meta with complete IA vol list.

    Called once at end of --all run to update provenance notes with the full
    set of processed IA volumes (individual per-volume saves only pass one vol).
    """
    with open(str(OUTPUT_FILE), encoding="utf-8") as f:
        existing = json.load(f)
    entries_by_id = {e["entry_id"]: e for e in existing.get("data", [])}
    save_output(entries_by_id, ia_vols)
    logger.info("  Meta updated with all IA vols: %s", ia_vols)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description=(
            "Parse Internet Archive _djvu.txt volumes of the New Schaff-Herzog "
            "Encyclopedia of Religious Knowledge into OCD reference_entry schema. "
            "Merges additively into the existing encyclopedia JSON file."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--volume",
        type=int,
        metavar="VOL_NUM",
        choices=sorted(IA_VOLUMES.keys()),
        help=f"IA volume number to process. Valid: {sorted(IA_VOLUMES.keys())}",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all 9 IA volumes (3-8, 10-12).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report -- do not write output files.",
    )
    parser.add_argument(
        "--emit-layers",
        action="store_true",
        help="Emit Phase C sparse text layers.",
    )
    args = parser.parse_args()

    if args.all:
        volumes = sorted(IA_VOLUMES.keys())
    else:
        volumes = [args.volume]

    logger.info("Schaff-Herzog IA parser starting")
    logger.info("Output file: %s", OUTPUT_FILE)
    logger.info("Log file: %s", LOG_PATH)
    logger.info("Dry-run: %s", args.dry_run)
    logger.info("Volumes: %s", volumes)

    all_stats = []
    failed = []
    ia_vols_ok = []
    start_time = time.time()

    for idx, vol_num in enumerate(volumes, 1):
        if idx > 1 and not args.dry_run:
            logger.info(
                "  Waiting %ds between downloads (crawl delay)...",
                DOWNLOAD_DELAY_SECONDS,
            )
            time.sleep(DOWNLOAD_DELAY_SECONDS)

        logger.info("Volume %d of %d: vol %d", idx, len(volumes), vol_num)

        try:
            stats = process_volume(vol_num, dry_run=args.dry_run, emit_layers=args.emit_layers)
        except Exception as exc:
            logger.error("Unhandled error processing vol %d: %s", vol_num, exc, exc_info=True)
            stats = {"vol": vol_num, "status": "error", "entry_count": 0}

        all_stats.append(stats)
        if stats.get("status") == "error":
            failed.append(vol_num)
        elif stats.get("status") == "ok":
            ia_vols_ok.append(vol_num)

    # After --all completes, rewrite meta with the full IA vol list
    if args.all and not args.dry_run and ia_vols_ok:
        rebuild_meta_with_all_ia_vols(ia_vols_ok)

    # Cross-volume quality stats (PIPE-02: completeness metrics in summary)
    if not args.dry_run and ia_vols_ok and len(volumes) > 1:
        try:
            with open(str(OUTPUT_FILE), encoding="utf-8") as _f:
                _all_entries = json.load(_f).get("data", [])
            print_quality_stats(_all_entries, "full combined output")
        except Exception as _exc:
            logger.warning("Could not compute cross-volume quality stats: %s", _exc)

    elapsed = time.time() - start_time
    total_entries = sum(s.get("entry_count", 0) for s in all_stats)
    processed = [s for s in all_stats if s.get("status") not in ("error",)]

    lines = [
        "=== SUMMARY ===",
        f"  Volumes processed: {len(processed)}/{len(volumes)}",
    ]
    # Per-volume entry counts (REL-07)
    for stat in all_stats:
        vol = stat.get("vol", "?")
        ec = stat.get("entry_count", 0)
        sk = stat.get("skipped_empty", 0)
        status = stat.get("status", "?")
        skip_note = f" (skipped {sk} empty)" if sk else ""
        lines.append(f"    vol{vol}: {ec} entries{skip_note}  [{status}]")
    lines += [
        f"  Total entries this run: {total_entries}",
        f"  Elapsed: {elapsed:.1f}s",
    ]
    if not args.dry_run and all_stats:
        # Find the last successful stat with total_after_merge
        for stat in reversed(all_stats):
            if "total_after_merge" in stat:
                lines.append(f"  Total entries in output file: {stat['total_after_merge']}")
                break
    if failed:
        lines.append(f"  FAILED volumes: {', '.join(str(v) for v in failed)}")

    summary = "\n".join(lines)
    if failed:
        logger.error(summary)
    else:
        logger.info(summary)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
