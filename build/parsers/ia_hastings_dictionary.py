"""ia_hastings_dictionary.py
Parser for Internet Archive _djvu.txt OCR files of Hastings' Dictionary of the Bible.

Internet Archive has OCR plain text for all 5 volumes.

This is a standalone script modelled on ia_schaff_herzog.py.

Format: Google Books DjVu-derived plain text (_djvu.txt).
  - Words use double-spaces (OCR artifact from typeset source), normalized to single.
  - Article headings come in two forms:
      Inline: 'TERM_IN_CAPS: body text starts here'  (most common)
      Standalone: 'TERM_IN_CAPS:' on its own line, body follows on next lines
  - Running page headers and Google Books watermarks appear without colons --
    always excluded from body text.
  - Front matter (~first 400-1500 lines): Google Books watermark, title page, preface,
    editor lists, abbreviation tables, transliteration/pronunciation keys -- skipped
    by two-phase detection: find "LIST OF ABBREVIATIONS", then find first article heading.
  - Page markers (standalone digits, volume markers like 'III.- 1') are skipped.
  - Vol 5 (Extra Volume): British Library scan whose OCR substituted Latin characters
    with Greek Unicode homoglyphs throughout (Α→A, Β→B, Ε→E, Η→H, Ι→I, Κ→K, Μ→M,
    Ν→N, Ο→O, Ρ→P, Τ→T, Υ→U, Χ→X). Requires a transliteration pre-processing pass
    before it can be parsed. The non-ASCII ratio guard detects this and raises
    HomoglyphSkip; output completeness = "partial" until Vol 5 is recovered.

Source:
  URL: https://archive.org/download/<identifier>/<filename>
  Format: _djvu.txt (ABBYY FineReader OCR, ~95-97% accuracy)
  All volumes US public domain (1898-1904, pre-1928).

Merges additively into data/reference/hastings-dictionary-of-the-bible.json.
Re-run safe: existing entry_ids are preserved.

Usage:
    py -3 build/parsers/ia_hastings_dictionary.py --volume 1
    py -3 build/parsers/ia_hastings_dictionary.py --volume 1 --dry-run
    py -3 build/parsers/ia_hastings_dictionary.py --all
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
from build.lib.text_utils import normalize_line

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
IA_RAW_DIR = REPO_ROOT / "raw" / "ia" / "hastings-dictionary"
OUTPUT_DIR = REPO_ROOT / "data" / "reference"
OUTPUT_FILE = OUTPUT_DIR / "hastings-dictionary-of-the-bible.json"
LOG_PATH = REPO_ROOT / "logs" / "ia_hastings_dictionary.log"

SCHEMA_VERSION = "2.1.0"
DICTIONARY_ID = "hastings-dictionary-of-the-bible"
SCRIPT_VERSION = "build/parsers/ia_hastings_dictionary.py@v1.0.1"

for _t in ["ecumenical", "evangelical"]:
    assert _t in REFERENCE_ENTRY__META__TRADITION, f"invalid tradition {_t!r}"
assert "full" in REFERENCE_ENTRY__META__COMPLETENESS, "invalid completeness 'full'"
assert "automated" in REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD, "invalid processing_method 'automated'"

USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)
DOWNLOAD_DELAY_SECONDS = 10
DOWNLOAD_DATE = "2026-04-29"

IA_BASE_URL = "https://archive.org/download/{identifier}/{filename}"

# Ordered map of volume number -> (IA identifier, IA _djvu.txt filename)
IA_VOLUMES = {
    1: ("DictionaryOfTheBibleV1", "DictionaryOfTheBibleV1_djvu.txt"),
    2: ("DictionaryOfTheBibleV2", "DictionaryOfTheBibleV2_djvu.txt"),
    3: ("DictionaryOfTheBibleV3", "DictionaryOfTheBibleV3_djvu.txt"),
    4: ("DictionaryOfTheBibleV4", "DictionaryOfTheBibleV4_djvu.txt"),
    5: ("b24749163_0005_20171026", "b24749163_0005_djvu.txt"),
}

# Volume-keyed minimum line index for the front-matter "DICTIONARY OF THE BIBLE"
# marker scan. Vol 4's title-page dedication at line 128 contains a false ALL-CAPS
# match; the real content running header is at ~line 1049. Vols 1-3 don't need a
# skip — their first match IS the real boundary. Default 0 = no skip for any
# volume not explicitly listed. (Adding a new volume? Census the OCR first; only
# raise the threshold if a verified false match exists.)
_FRONT_MATTER_MIN_LINE = {1: 0, 2: 0, 3: 0, 4: 400, 5: 0}

# Vol 5 (British Library scan) is the only volume known to fail the OCR
# homoglyph check. Adding a new volume that triggers the guard? Investigate
# first — return [] only for known-bad vols, raise for everything else.
_HOMOGLYPH_KNOWN_BAD_VOLS = frozenset([5])

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure file + console logging."""
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
    identifier, filename = IA_VOLUMES[vol_num]
    local_path = IA_RAW_DIR / filename

    if local_path.exists():
        logger.info("  Cached: %s (%s)", filename, _human_size(local_path.stat().st_size))
        return local_path

    url = IA_BASE_URL.format(identifier=identifier, filename=filename)
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
            with local_path.open("wb") as f:
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


_SEE_APPARATUS_PATTERN = re.compile(
    r"^(?:[A-Z][A-Z0-9 ,.'()&\-]{0,120}[.:—–-]\s*)?"
    r"See(?:\s+also|\s+further,?|\s+further)?\s+([^.;]+)"
)


def _clean_related_term(raw_term: str) -> str:
    """Clean one Hastings See/See-also target into a reference-entry term."""
    term = re.sub(r"\([^)]*\)", "", raw_term)
    term = re.sub(r"\[[^\]]*\]", "", term)
    term = re.sub(r"\s+", " ", term).strip(" ,:;.-")
    if not term or not any(c.isalpha() for c in term):
        return ""
    if any(c.isdigit() for c in term):
        return ""
    if len(term.split()) > 8:
        return ""
    return term


def extract_related_terms(blocks: list[str]) -> list[str]:
    """Extract Hastings See/See-also apparatus targets from definition text."""
    related: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        if len(block.split()) > 30:
            continue
        for match in _SEE_APPARATUS_PATTERN.finditer(block):
            target_text = match.group(1)
            target_text = re.sub(r"\s+\band\b\s+", ", ", target_text)
            target_text = target_text.replace("| also", ",")
            target_text = target_text.replace(" also ", ", ")
            for raw_target in target_text.split(","):
                term = _clean_related_term(raw_target)
                key = term.casefold()
                if term and key not in seen:
                    related.append(term)
                    seen.add(key)
    return related


# ---------------------------------------------------------------------------
# Line classification helpers
# ---------------------------------------------------------------------------


# Body labels that share Form-1 shape ("LXX:", "RV:", etc.) but are in-article
# annotations, not headwords. The pre-colon prefix of a Form-1 candidate is
# rejected if it upper-cases to one of these.
_BODY_LABEL_TERMS = frozenset([
    "LXX", "RV", "AV", "RVM", "AVM", "MT", "NT", "OT",
    "LXXA", "LXXB", "NOTE", "NB", "CF", "I.E", "E.G",
    "VG", "TR", "HEB", "GR", "GREEK", "HEBREW",
])

# Form-3 (ALL CAPS, no colon) article terms in Hastings are short — single
# headword phrases like "ACTS OF THE APOSTLES" or "SONG OF SOLOMON". Anything
# longer is almost certainly a stray ALL-CAPS body sentence.
_FORM3_MAX_TOKENS = 6

# Form-1 article terms can carry parenthetical pronunciation tokens
# ("ABI-ALBON  (^a-3({,  A  'A«e\\8ur)") so the term + parenthetical combined
# can run several tokens; cap generously but reject anything longer than 8.
_FORM1_PRECOLON_MAX_TOKENS = 8


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
      - Form 1/2: pre-colon prefix is ALL CAPS, <= 8 tokens, NOT a known body label
      - Form 3: entire stripped line is ALL CAPS, <= 6 tokens, >= 4 alpha chars

    Notes:
      - Running headers are excluded by is_running_header.
      - Body labels like "LXX:", "RV 'should have their freedom':" are body
        annotations inside other articles — rejected via _BODY_LABEL_TERMS plus
        a pre-colon-token cap and lowercase-prose check.
      - ALL-CAPS body sentences (e.g. "BIRTH TO AND CONTROLLED THE EVOLUTION OI")
        are rejected by the Form-3 token cap.
    """
    # Must start with 2+ consecutive uppercase letters
    if not re.match(r"^[A-Z]{2}", norm):
        return False
    # Skip running headers and section headers
    if is_running_header(norm):
        return False
    # Roman-numeral section headers within article body (e.g. 'I. History:', 'II. Doctrine:')
    if re.match(r"^[IVXLCDM]+\.?\s", norm):
        return False
    # Form 1 & 2: contains ':'
    if ":" in norm:
        pre_colon = norm.split(":", 1)[0].strip()
        if not pre_colon:
            return False
        # Body-label exclusion: "LXX:", "RV:", "NOTE:", "Cf.:", "MT:".
        # Compare on the alpha-only upper of the first token of the prefix.
        first_token_upper = re.sub(r"[^A-Z]", "", pre_colon.split()[0].upper())
        if first_token_upper in _BODY_LABEL_TERMS:
            return False
        # Token cap: real article terms are short (1-6 tokens; allow 7-8 to
        # accommodate parentheticals). Longer prefix = body text with a colon.
        if len(pre_colon.split()) > _FORM1_PRECOLON_MAX_TOKENS:
            return False
        # Lowercase content in the prefix indicates body prose with an embedded
        # quoted body-label, e.g. "RV 'should have their freedom':" — the prefix
        # 'RV \'should have their freedom\'' carries lowercase tokens that aren't
        # pronunciation guides. Reject.
        alpha_chars = [c for c in pre_colon if c.isalpha()]
        if alpha_chars:
            lower_ratio = sum(1 for c in alpha_chars if c.islower()) / len(alpha_chars)
            if lower_ratio > 0.30:
                return False
        return True
    # Form 3: entire line is ALL CAPS with enough alpha content
    stripped = norm.strip()
    if stripped == stripped.upper():
        alpha_count = sum(1 for c in stripped if c.isalpha())
        if alpha_count >= 4:
            # Reject running headers with appended page number:
            # "ACTS OF THE APOSTLES 27" — the trailing 1-3 digits are a page number,
            # not part of the article title.
            if re.search(r"\s\d{1,3}$", stripped):
                return False
            # Apply the same body-label exclusion as Form 1/2.
            # A standalone "NOTE", "LXXA", "LXXB" without a colon is a body
            # annotation marker, not an article headword. Without this guard it
            # would pass all other Form-3 checks and create a fake article that
            # silently absorbs all following text.
            first_alpha_token = re.sub(r"[^A-Z]", "", stripped.split()[0].upper()) if stripped.split() else ""
            if first_alpha_token in _BODY_LABEL_TERMS:
                return False
            # Token cap: real Form-3 article terms (ACTS OF THE APOSTLES,
            # SONG OF SOLOMON, FIRST BOOK OF KINGS) are <= 6 tokens. Anything
            # longer is an ALL-CAPS body sentence fragment.
            if len(stripped.split()) > _FORM3_MAX_TOKENS:
                return False
            return True
    return False


# Common OCR confusions for "THE" in scanned typeset text. The leading word of a
# running header like "THE MOABITE STONE" can be misread as "THB", "THK", "TIIE",
# "TBE", "THS", "THE." (trailing punctuation), etc. This set is intentionally
# narrow — only patterns observed in Hastings vols 1-4.
_THE_OCR_VARIANTS = frozenset(["THE", "THB", "THK", "TIIE", "TBE", "THS"])

# Front-matter boundary fallback pattern: matches abbreviation tables and
# transliteration scheme headings that appear near the content start of each volume.
_ABBR_RE = re.compile(
    r"LIST\s+OF\s+ABBREVIATIONS|TRANSLITERATION\s+SCHEME", re.IGNORECASE
)


def _starts_with_the_variant(norm: str) -> bool:
    """True if the first whitespace-delimited token is an OCR variant of 'THE '."""
    parts = norm.split(None, 1)
    if not parts:
        return False
    first = re.sub(r"[^A-Za-z]", "", parts[0]).upper()
    return first in _THE_OCR_VARIANTS


def is_running_header(norm: str) -> bool:
    """True if line is a structural header to skip (running page headers, section headers).

      - Lines beginning with 'THE ' or a known OCR variant ('THB ', 'THK ', 'TIIE ',
        'TBE ', 'THS '): no legitimate Hastings article begins this way, but page
        running headers like "THE MOABITE STONE" do — and OCR garbles the leading
        "THE" frequently enough that we tolerate the common variants.
      - Volume-page markers like 'VOL. I. — 1', 'VOL. II.- 5'.
      - Google Books / Internet Archive running headers for Hastings.

    Implementation note: content-pattern checks (THE-variants, DICTIONARY OF THE
    BIBLE, DIGITIZED BY GOOGLE) run BEFORE the colon early-exit so that a rare
    colon-bearing running header like "DICTIONARY OF THE BIBLE: Vol. I" is still
    caught rather than being passed through to is_article_heading as a false article.
    """
    # OCR-tolerant THE-prefix detection. The variants are alpha-only after
    # stripping punctuation, and must be followed by whitespace so words like
    # "THEBES" or "THERE" (which start with "THE" but are real headwords) stay
    # in scope as headings — those have no whitespace between THE and the rest.
    if _starts_with_the_variant(norm):
        return True

    # Strip non-alpha characters and normalize whitespace for fuzzy matching.
    # These patterns are checked before the colon guard because a colon-bearing
    # variant of "DICTIONARY OF THE BIBLE:" would escape detection otherwise.
    alpha_only = re.sub(r"[^A-Z ]", "", norm.upper())
    alpha_only = re.sub(r"\s+", " ", alpha_only).strip()

    if "DICTIONARY OF THE BIBLE" in alpha_only:
        return True
    if "DIGITIZED BY GOOGLE" in alpha_only:
        return True
    if alpha_only == "GOOGLE":
        return True

    # Colon in the line almost always means it is a body annotation or article
    # heading — not a running header. Pass through to is_article_heading.
    if ":" in norm:
        return False

    # Volume-page running markers (never a valid article heading)
    if re.match(r"^VOL\.?\s+[IVXLCDM]", norm, re.IGNORECASE):
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


def extract_term_and_inline_body(norm: str) -> tuple[str, str | None]:
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
    / "tools" / "ocr_scanner" / "corrections" / "hastings-dictionary.json"
)


def _load_ocr_corrections(path: Path) -> dict[str, str]:
    """Load corrections table as {normalized_upper_bad: good} dict.

    Returns empty dict if the file doesn't exist (graceful degradation).
    Key is the bad value after double-space normalisation and upper-casing,
    matching the normalisation applied in clean_term().

    Logs the result so a missing or empty corrections file is visible in the
    parser log — not invisibly skipped.
    """
    if not path.exists():
        logger.info(
            "  No OCR corrections file at %s — proceeding with zero corrections",
            path,
        )
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    table = {
        re.sub(r"  +", " ", c["bad"]).strip().upper(): c["good"]
        for c in data.get("corrections", [])
    }
    logger.info("  Loaded %d OCR corrections from %s", len(table), path)
    return table


# Module-level _OCR_CORRECTIONS is initialised lazily by main() so the load is
# captured by the configured logger. _load_ocr_corrections() falls back to
# whatever logger config exists when called early (e.g. from tests).
_OCR_CORRECTIONS: dict[str, str] = {}


def clean_term(raw_term: str) -> str:
    """Extract the article name from raw heading text.

    Strips pronunciation guides (lowercase segments interspersed in the heading).
    Example: 'CHAMIER, ahd/mye, DANIEL' -> 'CHAMIER, DANIEL'

    If no uppercase comma-segments survive, falls back to the longest leading
    run of ALL-CAPS-with-punctuation tokens. If even that yields nothing,
    returns "" — caller MUST treat as "skip this article".
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

    # Fallback: longest leading run of ALL-CAPS tokens (token = whitespace-split,
    # alpha chars must all be upper if any exist). Stops at the first token with
    # any lowercase content. Prevents the old fallback that returned the entire
    # OCR'd line ("IMNA (yj?:).— An Asherite chief, 1 Ch 7\". See") as a "term".
    leading_caps: list[str] = []
    for tok in normalized.split():
        alpha_chars = [c for c in tok if c.isalpha()]
        if alpha_chars and any(c.islower() for c in alpha_chars):
            break
        leading_caps.append(tok)
    if leading_caps:
        candidate = " ".join(leading_caps).strip(",.- ")
        if candidate:
            return candidate

    logger.warning(
        "  clean_term fallback yielded no uppercase tokens — raw_term=%r", raw_term,
    )
    return ""


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


class HomoglyphSkip(Exception):
    """Raised by parse_volume_text when a volume in _HOMOGLYPH_KNOWN_BAD_VOLS
    fails the non-ASCII ratio check. Lets process_volume distinguish a documented
    skip (Vol 5 BL scan) from a real parse failure (no articles found)."""


def parse_volume_text(text: str, vol_num: int) -> list:
    """Parse all encyclopedia articles from _djvu.txt text.

    Returns a list of raw article dicts:
      {term, definition_blocks, vol_num}

    Raises:
      HomoglyphSkip: vol_num is in _HOMOGLYPH_KNOWN_BAD_VOLS and the non-ASCII
        ratio check fires (documented skip — Vol 5 British Library scan).
      RuntimeError: any other vol trips the non-ASCII guard. We do NOT want to
        silently skip an unfamiliar volume — investigate the OCR first.
    """
    lines = text.splitlines()
    logger.info("  Vol %d: %d lines total", vol_num, len(lines))

    # --- Detect unreadable OCR (Vol 5 British Library scan) ---
    # Vol 5 was digitised by the British Library using an OCR engine that substituted
    # Latin characters with visually similar Greek Unicode code points (A→Α, E→Ε, etc.).
    # The result is entirely non-ASCII text that cannot be parsed with the standard Latin
    # heading detector. We tolerate this only for known-bad volumes; anything else
    # raises so the human investigates rather than silently dropping data.
    first_nonempty = [l for l in lines[:500] if l.strip()][:100]
    if first_nonempty:
        total_chars = sum(len(l) for l in first_nonempty)
        non_ascii_chars = sum(1 for l in first_nonempty for c in l if ord(c) > 127)
        non_ascii_ratio = non_ascii_chars / max(total_chars, 1)
        if non_ascii_ratio > 0.4:
            msg = (
                f"  Vol {vol_num}: {non_ascii_ratio * 100:.0f}% of first 100 non-empty "
                f"lines are non-ASCII. OCR has substituted Latin characters with Greek "
                f"Unicode homoglyphs (British Library scan pattern)."
            )
            if vol_num in _HOMOGLYPH_KNOWN_BAD_VOLS:
                logger.error("%s This format cannot be parsed. Skipping.", msg)
                raise HomoglyphSkip(
                    f"vol {vol_num} (known-bad homoglyph format)"
                )
            logger.error(
                "%s Vol %d is NOT a known-bad homoglyph source — investigate the "
                "OCR before adding it to _HOMOGLYPH_KNOWN_BAD_VOLS.", msg, vol_num,
            )
            raise RuntimeError(
                f"vol {vol_num}: non-ASCII ratio {non_ascii_ratio:.2f} > 0.4 in an "
                f"unrecognised volume; refusing to silently return [] (see "
                f"_HOMOGLYPH_KNOWN_BAD_VOLS in {Path(__file__).name})."
            )

    # --- Find body start (two-phase) ---
    # Vol 1 structure: Google Books notice (~130 lines), title page, PREFACE,
    # LIST OF ABBREVIATIONS section (~line 438), AUTHORS OF ARTICLES lists, then the
    # ALL CAPS running page header 'DICTIONARY OF THE BIBLE' (~line 1320) which marks
    # the exact start of dictionary content. Earlier mentions of "Dictionary of the Bible"
    # in the preface are mixed-case and therefore excluded by the ALL CAPS check.
    #
    # Vol 4 structure: title page dedication at line 128 contains ALL CAPS
    # "DICTIONARY OF THE BIBLE" — that occurrence must be skipped via the
    # volume-keyed `_FRONT_MATTER_MIN_LINE` threshold. The content running header
    # at ~line 1049 is the correct front matter boundary.
    #
    # The skip threshold MUST be volume-keyed: a global `i < 400` cutoff would
    # silently drop a real early marker in any other volume that happens to
    # have its DICTIONARY-OF-THE-BIBLE marker before line 400.
    #
    # Phase 1a: scan for the ALL CAPS standalone 'DICTIONARY OF THE BIBLE' running
    # header — appears at the front matter / content boundary in Vols 1-4.
    # Phase 1b: fallback to 'LIST OF ABBREVIATIONS'. When BOTH primary and
    # fallback markers fire, prefer the EARLIEST (primary preferred only when
    # they're roughly co-located; if the fallback is earlier we trust the
    # earlier marker).
    primary_idx = None
    for i, line in enumerate(lines[:3000]):
        if i < _FRONT_MATTER_MIN_LINE.get(vol_num, 0):
            continue
        norm = normalize_line(line).strip()
        if not norm or norm != norm.upper():
            continue
        alpha_only = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", "", norm)).strip()
        if alpha_only == "DICTIONARY OF THE BIBLE":
            primary_idx = i
            break

    fallback_idx = None
    for i, line in enumerate(lines):
        if _ABBR_RE.search(normalize_line(line)):
            fallback_idx = i
            break

    if primary_idx is not None and fallback_idx is not None:
        # Both found — pick the earliest. Either one is a reasonable boundary,
        # and the earliest is the conservative choice (won't skip body content).
        front_matter_end = min(primary_idx, fallback_idx)
    elif primary_idx is not None:
        front_matter_end = primary_idx
    elif fallback_idx is not None:
        front_matter_end = fallback_idx
    else:
        front_matter_end = None

    search_from = front_matter_end if front_matter_end is not None else 0
    if front_matter_end is not None:
        logger.info("  Vol %d: front matter end marker at line %d", vol_num, front_matter_end + 1)
    else:
        logger.warning("  Vol %d: no front matter end marker found -- scanning from top", vol_num)

    body_start = None
    for i, line in enumerate(lines[search_from:], search_from):
        norm = normalize_line(line)
        if is_article_heading(norm):
            body_start = i
            break

    if body_start is None:
        logger.error("  Vol %d: no article body start found -- check file format", vol_num)
        return []

    logger.info("  Vol %d: body starts at line %d; first content: %s",
                vol_num, body_start + 1, normalize_line(lines[body_start])[:60])

    # --- Main parsing loop ---
    articles = []
    current_term = None
    current_slug = None         # slugified form of current_term for same-term detection
    current_inline_body = None  # remainder of heading line after ': '
    current_body_parts = []     # accumulated non-empty lines for this article
    current_paragraph = []      # current paragraph (lines since last blank)

    def _flush_article() -> None:
        """Commit current_paragraph into current_body_parts."""
        nonlocal current_paragraph
        if current_paragraph:
            current_body_parts.append(" ".join(current_paragraph))
            current_paragraph = []

    def _save_article() -> None:
        """Save the current article to the articles list."""
        nonlocal current_term, current_slug, current_body_parts, current_paragraph, current_inline_body
        _flush_article()
        if current_term is not None:
            blocks = [b for b in current_body_parts if b.strip()]
            articles.append({
                "term": current_term,
                "definition_blocks": blocks,
                "vol_num": vol_num,
            })
        current_term = None
        current_slug = None
        current_inline_body = None
        current_body_parts = []
        current_paragraph = []

    for line in lines[body_start:]:
        norm = normalize_line(line)

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
            term, inline_body = extract_term_and_inline_body(norm)
            if not term:
                # clean_term fell through with no uppercase content — treat the
                # line as junk (probably mixed-case OCR garbage that fooled the
                # heading detector). Don't start a new article.
                continue
            term_slug = slugify(term)
            if term_slug == current_slug:
                # Hastings uses the article title itself as the running page header.
                # Compare by slug (not literal term) to tolerate OCR space/hyphen
                # variants like "ABI-ALBON" vs "ABI ALBON" as the same article.
                # When the slug matches, it's a page break — flush paragraph, continue.
                _flush_article()
                if inline_body:
                    current_paragraph.append(inline_body)
            else:
                _save_article()
                current_term = term
                current_slug = term_slug
                current_inline_body = inline_body
                # Inline body starts the first paragraph
                if inline_body:
                    current_paragraph.append(inline_body)
        else:
            # Body text: append to current paragraph
            if current_term is not None:
                current_paragraph.append(norm.strip())

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
    """Hash all cached IA source files for a deterministic fingerprint."""
    combined = hashlib.sha256()
    for path in sorted(IA_RAW_DIR.glob("*.txt")):
        combined.update(path.read_bytes())
    return "sha256:" + combined.hexdigest()


def build_meta(ia_vols_processed: list) -> dict:
    """Build meta envelope for the Hastings output file."""
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_hash = compute_combined_source_hash()
    vol_labels = ", ".join(f"vol{v}" for v in sorted(ia_vols_processed))
    completeness = "full" if sorted(ia_vols_processed) == [1, 2, 3, 4, 5] else "partial"
    return {
        "id": DICTIONARY_ID,
        "title": "Dictionary of the Bible",
        "author": "James Hastings (ed.)",
        "original_publication_year": 1898,
        "language": "en",
        "tradition": ["ecumenical", "evangelical"],
        "tradition_notes": (
            "Hastings Dictionary of the Bible (1898-1904) is a major Victorian Protestant "
            "reference work edited by James Hastings of the Free Church of Scotland."
        ),
        "license": "public-domain",
        "schema_type": "reference_entry",
        "schema_version": SCHEMA_VERSION,
        "completeness": completeness,
        "provenance": {
            "source_url": "https://archive.org/download/DictionaryOfTheBibleV1/",
            "source_format": "_djvu.txt OCR (Internet Archive / Google Books digitisation)",
            "source_edition": (
                "Dictionary of the Bible, 5 vols, 1898-1904 (James Hastings, ed.)"
            ),
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": process_date,
            "notes": (
                f"Processed volumes: {vol_labels}. "
                "All volumes sourced from Internet Archive _djvu.txt OCR. "
                "CCEL Hastings files are image-only (no machine-readable text). "
                "Vols 1-4 from 1911 reprint digitised by Google Books (ABBYY FineReader, ~96-97% page confidence). "
                "Vol 5 (Extra Volume: articles + index) from British Library scan. "
                "All volumes US public domain (1898-1904, pre-1928). "
                "Permission confirmed: CCEL (Quincy, 2026-04-01). "
                "source_hash is combined SHA-256 of all downloaded source files."
            ),
        },
    }


def build_entry(raw_article: dict, seen_ids: set) -> dict:
    """Convert raw article dict to OCD reference_entry record."""
    term = raw_article["term"]
    base_id = f"hastings.{slugify(term)}"
    entry_id = make_unique_id(base_id, seen_ids)
    seen_ids.add(entry_id)

    blocks = raw_article["definition_blocks"]
    word_count = sum(len(b.split()) for b in blocks)
    related_terms = extract_related_terms(blocks)

    return {
        "entry_id": entry_id,
        "dictionary_id": DICTIONARY_ID,
        "term": term,
        "alt_terms": [],
        "definition_blocks": blocks,
        "scripture_references": [],
        "related_terms": related_terms,
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Load / merge / save
# ---------------------------------------------------------------------------


def load_existing_output() -> tuple:
    """Load existing output file. Returns (meta_or_None, entries_by_id_dict)."""
    if not OUTPUT_FILE.exists():
        return None, {}

    try:
        with OUTPUT_FILE.open(encoding="utf-8") as f:
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

    with OUTPUT_FILE.open("w", encoding="utf-8", newline="\n") as f:
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


def _filter_valid_articles(raw_articles: list[dict], vol_num: int) -> tuple[list[dict], int, int]:
    """Drop schema-invalid empty/fragment articles and return skip counts."""
    valid_articles = []
    skipped_empty = 0
    skipped_too_short = 0
    for article in raw_articles:
        if not article["definition_blocks"]:
            skipped_empty += 1
            continue
        wc = sum(len(block.split()) for block in article["definition_blocks"])
        if wc < 2:
            skipped_too_short += 1
            continue
        valid_articles.append(article)
    if skipped_empty:
        logger.warning(
            "  Vol %d: skipping %d entries with empty definition_blocks",
            vol_num, skipped_empty,
        )
    if skipped_too_short:
        logger.warning(
            "  Vol %d: skipping %d entries with body word_count < 2 (OCR fragments)",
            vol_num, skipped_too_short,
        )
    return valid_articles, skipped_empty, skipped_too_short


def process_volume(vol_num: int, dry_run: bool = False) -> dict:
    """Process one IA volume: download, parse, merge into output file.

    In dry-run mode: parse only, do not write files. Prints first 3 entries.
    Returns a stats dict with "status" in {"ok","dry-run","skipped-by-guard","error"}.
    """
    logger.info("--- Processing vol %d ---", vol_num)

    try:
        raw_articles = parse_volume(vol_num)
    except HomoglyphSkip as exc:
        logger.warning("  Vol %d: documented skip — %s", vol_num, exc)
        return {"vol": vol_num, "status": "skipped-by-guard", "entry_count": 0}

    if not raw_articles:
        logger.error("  Vol %d: no articles found -- check file format", vol_num)
        return {"vol": vol_num, "status": "error", "entry_count": 0}

    # Filter: skip entries with empty definition_blocks (schema requires minItems: 1)
    # AND entries with total word_count < 2. The latter catches OCR fragments where
    # a heading-like running header captured a single garbage token as its "body"
    # (e.g. term "SAMUEL, L AKD IL" with body 'k'). Real Hastings cross-references
    # are at least two words ("Stones, (Pbecious).", "See Genealogy.").
    valid_articles, skipped_empty, _skipped_too_short = _filter_valid_articles(
        raw_articles, vol_num
    )

    if dry_run:
        seen_ids: set = set()
        entries = [build_entry(a, seen_ids) for a in valid_articles]
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
    # already exists in the PRE-EXISTING output (from a prior run), discard it from
    # seen_ids so make_unique_id returns the original base_id, effectively overwriting
    # the old entry with the fresh parse. Within-run duplicates (two different articles
    # that hash to the same slug) must take the -2/-3 suffix via make_unique_id, even
    # if their base_id pre-existed on disk — so each pre-existing base_id may only be
    # "freed" once per run (consumed_pre_existing tracks that).
    pre_existing_ids = set(entries_by_id.keys())
    consumed_pre_existing: set[str] = set()
    seen_ids = set(entries_by_id.keys())
    new_entries = []
    overwritten = 0

    for raw_article in valid_articles:
        base_id = f"hastings.{slugify(raw_article['term'])}"
        if base_id in pre_existing_ids and base_id not in consumed_pre_existing:
            seen_ids.discard(base_id)
            consumed_pre_existing.add(base_id)
            overwritten += 1
        entry = build_entry(raw_article, seen_ids)
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
    with OUTPUT_FILE.open(encoding="utf-8") as f:
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


def rebuild_all_volumes(volumes: list[int]) -> list[dict]:
    """Rebuild the combined Hastings output from parsed IA volumes in one write."""
    entries_by_id: dict[str, dict] = {}
    seen_ids: set[str] = set()
    all_stats: list[dict] = []
    ia_vols_ok: list[int] = []

    for idx, vol_num in enumerate(volumes, 1):
        if idx > 1:
            logger.info(
                "  Waiting %ds between downloads (crawl delay)...",
                DOWNLOAD_DELAY_SECONDS,
            )
            time.sleep(DOWNLOAD_DELAY_SECONDS)

        logger.info("Volume %d of %d: vol %d", idx, len(volumes), vol_num)
        logger.info("--- Processing vol %d ---", vol_num)
        try:
            raw_articles = parse_volume(vol_num)
        except HomoglyphSkip as exc:
            logger.warning("  Vol %d: documented skip — %s", vol_num, exc)
            all_stats.append({"vol": vol_num, "status": "skipped-by-guard", "entry_count": 0})
            continue
        except Exception as exc:
            logger.error("Unhandled error processing vol %d: %s", vol_num, exc, exc_info=True)
            all_stats.append({"vol": vol_num, "status": "error", "entry_count": 0})
            continue

        if not raw_articles:
            logger.error("  Vol %d: no articles found -- check file format", vol_num)
            all_stats.append({"vol": vol_num, "status": "error", "entry_count": 0})
            continue

        valid_articles, skipped_empty, _skipped_too_short = _filter_valid_articles(
            raw_articles, vol_num
        )
        entries = []
        for raw_article in valid_articles:
            entry = build_entry(raw_article, seen_ids)
            entries_by_id[entry["entry_id"]] = entry
            entries.append(entry)

        print_quality_stats(entries, f"vol{vol_num}")
        ia_vols_ok.append(vol_num)
        all_stats.append({
            "vol": vol_num,
            "status": "ok",
            "entry_count": len(entries),
            "skipped_empty": skipped_empty,
        })

    failed = [stat["vol"] for stat in all_stats if stat.get("status") == "error"]
    if failed:
        logger.error(
            "Refusing to write combined output because volume(s) failed: %s",
            ", ".join(str(vol) for vol in failed),
        )
        return all_stats

    if ia_vols_ok:
        save_output(entries_by_id, ia_vols_ok)
        if all_stats:
            all_stats[-1]["total_after_merge"] = len(entries_by_id)
        print_quality_stats(list(entries_by_id.values()), "full combined output")
    return all_stats


def rebuild_meta_with_all_ia_vols(ia_vols: list) -> None:
    """After all volumes processed, rewrite meta with complete IA vol list.

    Called once at end of --all run to update provenance notes with the full
    set of processed IA volumes (individual per-volume saves only pass one vol).
    """
    with OUTPUT_FILE.open(encoding="utf-8") as f:
        existing = json.load(f)
    entries_by_id = {e["entry_id"]: e for e in existing.get("data", [])}
    save_output(entries_by_id, ia_vols)
    logger.info("  Meta updated with all IA vols: %s", ia_vols)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()

    # Load corrections AFTER setup_logging so the load result is captured.
    global _OCR_CORRECTIONS
    _OCR_CORRECTIONS = _load_ocr_corrections(_CORRECTIONS_FILE)

    parser = argparse.ArgumentParser(
        description=(
            "Parse Internet Archive _djvu.txt volumes of Hastings' Dictionary of "
            "the Bible into OCD reference_entry schema. "
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
        help="Process all 5 IA volumes (1-5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report -- do not write output files.",
    )
    args = parser.parse_args()

    if args.all:
        volumes = sorted(IA_VOLUMES.keys())
    else:
        volumes = [args.volume]

    logger.info("Hastings Dictionary IA parser starting")
    logger.info("Output file: %s", OUTPUT_FILE)
    logger.info("Log file: %s", LOG_PATH)
    logger.info("Dry-run: %s", args.dry_run)
    logger.info("Volumes: %s", volumes)

    all_stats = []
    failed = []
    ia_vols_ok = []
    start_time = time.time()
    rebuilt_all = args.all and not args.dry_run

    if rebuilt_all:
        all_stats = rebuild_all_volumes(volumes)
        for stats in all_stats:
            status = stats.get("status")
            if status == "error":
                failed.append(stats.get("vol"))
            elif status == "ok":
                ia_vols_ok.append(stats.get("vol"))
    else:
        for idx, vol_num in enumerate(volumes, 1):
            if idx > 1 and not args.dry_run:
                logger.info(
                    "  Waiting %ds between downloads (crawl delay)...",
                    DOWNLOAD_DELAY_SECONDS,
                )
                time.sleep(DOWNLOAD_DELAY_SECONDS)

            logger.info("Volume %d of %d: vol %d", idx, len(volumes), vol_num)

            try:
                stats = process_volume(vol_num, dry_run=args.dry_run)
            except Exception as exc:
                logger.error("Unhandled error processing vol %d: %s", vol_num, exc, exc_info=True)
                stats = {"vol": vol_num, "status": "error", "entry_count": 0}

            all_stats.append(stats)
            status = stats.get("status")
            if status == "error":
                failed.append(vol_num)
            elif status == "ok":
                ia_vols_ok.append(vol_num)
            # "skipped-by-guard" and "dry-run" are neither failures nor processed-OK.

    # After --all completes, rewrite meta with the full IA vol list
    if args.all and not args.dry_run and ia_vols_ok and not rebuilt_all:
        rebuild_meta_with_all_ia_vols(ia_vols_ok)

    # Cross-volume quality stats (PIPE-02: completeness metrics in summary)
    if not args.dry_run and ia_vols_ok and len(volumes) > 1 and not rebuilt_all:
        try:
            with OUTPUT_FILE.open(encoding="utf-8") as _f:
                _all_entries = json.load(_f).get("data", [])
            print_quality_stats(_all_entries, "full combined output")
        except Exception as _exc:
            logger.warning("Could not compute cross-volume quality stats: %s", _exc)

    elapsed = time.time() - start_time
    total_entries = sum(s.get("entry_count", 0) for s in all_stats)
    processed = [s for s in all_stats if s.get("status") not in ("error",)]
    skipped_by_guard = [s for s in all_stats if s.get("status") == "skipped-by-guard"]

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
    if skipped_by_guard:
        skipped_vols = ", ".join(str(s["vol"]) for s in skipped_by_guard)
        lines.append(f"  Skipped by guard (documented, not a failure): {skipped_vols}")
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
