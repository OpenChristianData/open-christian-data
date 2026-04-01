"""validate_osis.py
Importable utility for validating OSIS verse references against the canonical
verse index derived from BSB data.

Supported OSIS formats:
  - Single verse:     Gen.1.1
  - Verse range:      Gen.1.1-Gen.1.31   (cross-chapter: Matt.5.48-Matt.6.1)
  - Chapter-level:    Gen.1              (validated to chapter level only)
  - Book-level:       Gen                (validated to book existence only)

Degrades gracefully when the verse index is unavailable (validate_osis_ref
returns True with reason="index unavailable"; validate_osis_array reports 0
invalid items). Run build/scripts/build_verse_index.py to generate the index.

The index stores explicit verse sets per chapter (build/bible_data/verse_index.json).
Textually-disputed verses absent from BSB (e.g. Matt.17.21) are not in the verse
set; they are caught by the KNOWN_OMISSIONS table below and return a downgraded
"known omission" status rather than "invalid".

Usage (import):
    from build.scripts.validate_osis import validate_osis_ref, validate_osis_array

Usage (standalone):
    py -3 build/scripts/validate_osis.py Gen.1.1
    py -3 build/scripts/validate_osis.py Gen.1.1-Gen.1.3
    py -3 build/scripts/validate_osis.py Ezek.48.40
"""

import json
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSE_INDEX_PATH = REPO_ROOT / "build" / "bible_data" / "verse_index.json"
KJV_INDEX_PATH = REPO_ROOT / "build" / "bible_data" / "kjv_verse_index.json"
APOCRYPHA_INDEX_PATH = REPO_ROOT / "build" / "bible_data" / "apocrypha_verse_index.json"

# OSIS book codes for deuterocanonical/apocryphal books that are absent from the
# BSB-derived verse index (Protestant 66-book canon). When a book code is in this
# set, existence checks are skipped rather than reported as "unknown book code".
# Covers: Catholic, Eastern Orthodox, Slavonic, and Ethiopian Orthodox canons.
DEUTEROCANONICAL_BOOK_CODES = frozenset({
    # Catholic deuterocanonical
    "Tob", "Jdt", "Wis", "Sir", "Bar", "EpJer",
    "1Macc", "2Macc",
    # Additions to Daniel
    "PrAzar", "SgThree", "Sus", "Bel",
    # Additions to Esther
    "AddEsth", "EsthGr",
    # Prayer of Manasseh (in some Catholic/Orthodox editions)
    "PrMan",
    # Eastern Orthodox / Slavonic additions
    "1Esd", "2Esd", "3Macc", "4Macc", "Ps151", "Odes", "PsSol",
    # Ethiopian Orthodox canon
    "1En", "Jub",
})

# ---------------------------------------------------------------------------
# Known textually-disputed verses absent from modern critical texts (BSB).
# This table is the fallback for when kjv_verse_index.json is unavailable.
# When the KJV index IS available it supersedes this table automatically --
# any verse present in KJV but absent from BSB is returned as
# (True, "in KJV/TR - not in BSB critical text") without a manual entry here.
# ---------------------------------------------------------------------------
KNOWN_OMISSIONS: dict = {}  # Replaced by dynamic KJV index lookup; kept as empty fallback.

# ---------------------------------------------------------------------------
# Versification offsets -- verses that are in the SWORD/MT KJV numbering but
# absent from BSB because the SWORD module counts Psalm superscriptions as
# verse 1, shifting subsequent verse numbers up by one.  These are NOT
# manuscript disputes -- the underlying text is identical.
# Format: frozenset of (book_osis, chapter_str, verse_int) tuples.
# ---------------------------------------------------------------------------
VERSIFICATION_OFFSETS: frozenset = frozenset({
    ("Ps", "140", 14),   # superscription "To the Chief Musician..." counted as v.1 in MT
    ("Ps", "142", 8),    # superscription "Maschil of David..." counted as v.1 in MT
})
# Private alias used internally (public name allows generate_disputed_verses.py to import it).
_VERSIFICATION_OFFSETS = VERSIFICATION_OFFSETS

# Module-level cache -- loaded once on first use
_INDEX = None
_INDEX_LOADED = False
_KJV_INDEX = None
_KJV_INDEX_LOADED = False
_APOCRYPHA_INDEX = None
_APOCRYPHA_INDEX_LOADED = False


def _load_index() -> Optional[dict]:
    """Load verse index from disk. Returns the index dict or None if unavailable."""
    global _INDEX, _INDEX_LOADED
    if _INDEX_LOADED:
        return _INDEX
    _INDEX_LOADED = True
    if not VERSE_INDEX_PATH.exists():
        _INDEX = None
        return None
    try:
        with open(VERSE_INDEX_PATH, encoding="utf-8") as f:
            _INDEX = json.load(f)
    except Exception as exc:
        print(f"WARN: Failed to load verse index from {VERSE_INDEX_PATH}: {exc}", file=sys.stderr)
        _INDEX = None
    return _INDEX


def _load_kjv_index() -> Optional[dict]:
    """Load KJV verse index from disk. Returns the index dict or None if unavailable."""
    global _KJV_INDEX, _KJV_INDEX_LOADED
    if _KJV_INDEX_LOADED:
        return _KJV_INDEX
    _KJV_INDEX_LOADED = True
    if not KJV_INDEX_PATH.exists():
        _KJV_INDEX = None
        return None
    try:
        with open(KJV_INDEX_PATH, encoding="utf-8") as f:
            _KJV_INDEX = json.load(f)
    except Exception as exc:
        print(f"WARN: Failed to load KJV index from {KJV_INDEX_PATH}: {exc}", file=sys.stderr)
        _KJV_INDEX = None
    return _KJV_INDEX


def _load_apocrypha_index() -> Optional[dict]:
    """Load apocrypha verse index from disk. Returns the index dict or None if unavailable."""
    global _APOCRYPHA_INDEX, _APOCRYPHA_INDEX_LOADED
    if _APOCRYPHA_INDEX_LOADED:
        return _APOCRYPHA_INDEX
    _APOCRYPHA_INDEX_LOADED = True
    if not APOCRYPHA_INDEX_PATH.exists():
        _APOCRYPHA_INDEX = None
        return None
    try:
        with open(APOCRYPHA_INDEX_PATH, encoding="utf-8") as f:
            _APOCRYPHA_INDEX = json.load(f)
    except Exception as exc:
        print(f"WARN: Failed to load apocrypha index from {APOCRYPHA_INDEX_PATH}: {exc}", file=sys.stderr)
        _APOCRYPHA_INDEX = None
    return _APOCRYPHA_INDEX


def _validate_endpoint(
    book: str,
    chapter_str: Optional[str],
    verse_str: Optional[str],
    index_books: dict,
) -> Tuple[bool, str]:
    """Check a parsed OSIS endpoint against the verse index.

    Returns (valid, reason). reason is empty string when valid.
    """
    if book not in index_books:
        if book in DEUTEROCANONICAL_BOOK_CODES:
            # Check the apocrypha verse index for existence if available.
            apocrypha_index = _load_apocrypha_index()
            if apocrypha_index is not None:
                apoc_books = apocrypha_index.get("books", {})
                if book not in apoc_books:
                    # Book code is valid (in DEUTEROCANONICAL_BOOK_CODES) but absent from
                    # the KJVA-derived apocrypha index.  This covers Orthodox/Ethiopian canon
                    # books (e.g. 1En, Jub, Ps151, 3Macc) that pysword KJVA does not include.
                    # These pass with a note rather than failing -- we simply have no index to
                    # check them against.
                    return True, f"deuterocanonical '{book}' - no verse index (extended canon)"
                if chapter_str is None:
                    return True, ""  # book-level ref
                apoc_ch = apoc_books[book].get("verses", {})
                if chapter_str not in apoc_ch:
                    max_ch = apoc_books[book]["chapter_count"]
                    return False, f"{book} has no chapter {chapter_str} (book has {max_ch} chapters)"
                if verse_str is None:
                    return True, ""  # chapter-level ref
                verse_base = verse_str.rstrip("abcdefghijklmnopqrstuvwxyz") if verse_str else verse_str
                try:
                    verse_int = int(verse_base)
                except ValueError:
                    return False, f"non-integer verse '{verse_str}'"
                if verse_int < 1:
                    return False, f"verse must be >= 1 (got {verse_str})"
                if verse_int not in apoc_ch[chapter_str]:
                    present = apoc_ch[chapter_str]
                    return False, (
                        f"{book}.{chapter_str} does not contain verse {verse_str} "
                        f"(present in apocrypha index: {present})"
                    )
                return True, ""
            return True, "deuterocanonical - apocrypha index unavailable"
        return False, f"unknown book code '{book}'"

    if chapter_str is None:
        return True, ""  # book-level ref -- valid if book exists

    book_data = index_books[book]
    chapter_data = book_data.get("verses")
    if chapter_data is None:
        # Fallback: support legacy indices that stored verse_counts (max-verse ints).
        # This path is exercised only when the index predates Fix 4; rebuild to remove it.
        chapter_data = book_data.get("verse_counts", {})
        use_legacy = True
    else:
        use_legacy = False

    if chapter_str not in chapter_data:
        max_ch = book_data["chapter_count"]
        return False, f"{book} has no chapter {chapter_str} (book has {max_ch} chapters)"

    if verse_str is None:
        return True, ""  # chapter-level ref -- valid if chapter exists

    # Strip optional half-verse suffix (e.g. "2b" -> 2) before integer lookup.
    # Half-verse notation (Ps.21.2b = second half of v.2) is standard scholarly convention.
    verse_base = verse_str.rstrip("abcdefghijklmnopqrstuvwxyz") if verse_str else verse_str
    try:
        verse_int = int(verse_base)
    except ValueError:
        return False, f"non-integer verse '{verse_str}'"

    if verse_int < 1:
        return False, f"verse must be >= 1 (got {verse_str})"

    if use_legacy:
        # Legacy index: chapter_data[chapter_str] is the max verse int.
        max_verse = chapter_data[chapter_str]
        if verse_int > max_verse:
            return False, f"{book}.{chapter_str} has verses 1-{max_verse} (got {verse_str})"
    else:
        # Current index: chapter_data[chapter_str] is a sorted list of verse ints.
        verse_set = chapter_data[chapter_str]
        if verse_int not in verse_set:
            # 1. Check the KJV index: if the verse is present in KJV/TR versification
            #    it is a textually-disputed verse, not an invalid ref.
            kjv_index = _load_kjv_index()
            if kjv_index is not None:
                kjv_books = kjv_index.get("books", {})
                kjv_ch_data = kjv_books.get(book, {}).get("verses", {})
                kjv_verse_set = kjv_ch_data.get(chapter_str, [])
                if verse_int in kjv_verse_set:
                    if (book, chapter_str, verse_int) in _VERSIFICATION_OFFSETS:
                        return True, "versification offset - SWORD/MT superscription numbering differs from printed KJV/BSB"
                    return True, "in KJV/TR - not in BSB critical text"
            # 2. Fall back to KNOWN_OMISSIONS table (active when KJV index unavailable).
            chapter_int = int(chapter_str)
            book_omissions = KNOWN_OMISSIONS.get(book, {})
            if verse_int in book_omissions.get(chapter_int, set()):
                return True, "known omission - not in critical text"
            present = verse_set
            return False, (
                f"{book}.{chapter_str} does not contain verse {verse_str} "
                f"(present in BSB: {present})"
            )

    return True, ""


def _parse_endpoint(part: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Parse one OSIS endpoint into (book, chapter_str, verse_str).

    Returns None for absent levels. Raises ValueError on bad format.
    """
    segments = part.split(".")
    if len(segments) == 1:
        return segments[0], None, None
    elif len(segments) == 2:
        return segments[0], segments[1], None
    elif len(segments) == 3:
        return segments[0], segments[1], segments[2]
    else:
        raise ValueError(f"unexpected format in '{part}' ({len(segments)} dot-segments)")


def _find_range_dash(osis_str: str) -> Optional[int]:
    """Return the index of the dash that separates two OSIS endpoints in a range.

    A range dash is preceded by a digit or a half-verse letter suffix (e.g. '2b')
    and followed by an upper-case letter or digit (start of a book code).
    Returns None if the string is not a range.

    Examples:
      Gen.1.1-Gen.1.3     -> dash at index 7
      1Thess.1.1-2Cor.1   -> dash found correctly
      Ps.21.2b-Ps.21.3    -> dash after 'b' suffix found correctly
      Ps.22.1a-Ps.22.1b   -> dash after 'a' suffix found correctly
      1John.1.1           -> None (no dash in ref)
    """
    for i, ch in enumerate(osis_str):
        if ch == "-" and i > 0:
            prev_ch = osis_str[i - 1]
            next_ch = osis_str[i + 1] if i + 1 < len(osis_str) else ""
            if (prev_ch.isdigit() or prev_ch.islower()) and (next_ch.isupper() or next_ch.isdigit()):
                return i
    return None


def validate_osis_ref(osis_str: str) -> Tuple[bool, str]:
    """Validate a single OSIS reference string.

    Returns (valid, reason). reason is an empty string when valid.

    If the verse index is unavailable, returns (True, "index unavailable") --
    format checks still catch malformed refs, existence checks are skipped.
    """
    if not osis_str or not isinstance(osis_str, str):
        return False, "empty or non-string OSIS reference"

    index = _load_index()
    if index is None:
        # Degrade gracefully -- can still do basic format checks
        return True, "index unavailable"

    index_books = index.get("books", {})

    dash_idx = _find_range_dash(osis_str)
    if dash_idx is not None:
        # Range ref: validate both endpoints
        start_part = osis_str[:dash_idx]
        end_part = osis_str[dash_idx + 1:]
        try:
            s_book, s_ch, s_vs = _parse_endpoint(start_part)
            e_book, e_ch, e_vs = _parse_endpoint(end_part)
        except ValueError as exc:
            return False, str(exc)
        valid, reason = _validate_endpoint(s_book, s_ch, s_vs, index_books)
        if not valid:
            return False, f"range start: {reason}"
        valid, reason = _validate_endpoint(e_book, e_ch, e_vs, index_books)
        if not valid:
            return False, f"range end: {reason}"
        return True, ""

    # Single ref
    try:
        book, chapter_str, verse_str = _parse_endpoint(osis_str)
    except ValueError as exc:
        return False, str(exc)

    return _validate_endpoint(book, chapter_str, verse_str, index_books)


def validate_osis_array(osis_list: List[str]) -> Tuple[int, List[Tuple[str, str]]]:
    """Validate a list of OSIS reference strings.

    Returns (valid_count, invalid_items) where invalid_items is a list of
    (osis_str, reason) tuples for refs that failed existence checks.

    Refs that pass 'index unavailable' are counted as valid (existence check
    was skipped, not failed).
    """
    valid_count = 0
    invalid_items = []
    for osis_str in osis_list:
        valid, reason = validate_osis_ref(osis_str)
        if valid:
            valid_count += 1
        else:
            invalid_items.append((osis_str, reason))
    return valid_count, invalid_items


def index_available() -> bool:
    """Return True if the verse index is loaded and available."""
    return _load_index() is not None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: py -3 build/scripts/validate_osis.py <OSIS-ref> [...]")
        print("Examples:")
        print("  py -3 build/scripts/validate_osis.py Gen.1.1")
        print("  py -3 build/scripts/validate_osis.py Gen.1.1-Gen.1.3")
        print("  py -3 build/scripts/validate_osis.py Ezek.48.40")
        print("  py -3 build/scripts/validate_osis.py Ps.21.2b")
        print("  py -3 build/scripts/validate_osis.py Ps.21.2b-Ps.21.3")
        print("  py -3 build/scripts/validate_osis.py Ps.22.1a-Ps.22.1b")
        sys.exit(1)

    index = _load_index()
    if index is None:
        print(f"WARN: Verse index not found at {VERSE_INDEX_PATH}")
        print("  Run: py -3 build/scripts/build_verse_index.py")
        print()

    all_valid = True
    for ref in sys.argv[1:]:
        valid, reason = validate_osis_ref(ref)
        if valid:
            if reason:
                print(f"  OK  {ref}  ({reason})")
            else:
                print(f"  OK  {ref}")
        else:
            print(f"  INVALID  {ref}  -- {reason}")
            all_valid = False

    sys.exit(0 if all_valid else 1)
