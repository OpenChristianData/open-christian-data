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

# ---------------------------------------------------------------------------
# Hebrew (MT) → English versification translation
# ---------------------------------------------------------------------------

# Psalm numbers (1-150) that have a superscription in the MT canon.
# For these Psalms, Hebrew verse N = English verse N-1.
# The complement (34 Psalms WITHOUT superscriptions) is:
#   1, 2, 10, 33, 43, 71, 91, 93, 94, 95, 96, 97, 99, 104, 105, 106, 107,
#   111, 112, 113, 114, 115, 116, 117, 118, 119, 135, 136, 137, 146, 147,
#   148, 149, 150
_PSALMS_WITH_SUPERSCRIPTION: frozenset = frozenset({
    3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22,
    23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38, 39, 40,
    41, 42, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58,
    59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 72, 73, 74, 75, 76,
    77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 92, 98, 100,
    101, 102, 103, 108, 109, 110, 120, 121, 122, 123, 124, 125, 126, 127,
    128, 129, 130, 131, 132, 133, 134, 138, 139, 140, 141, 142, 143, 144,
    145,
})

# Psalms where the superscription occupies TWO Hebrew verses rather than one.
# These are Psalms with both a liturgical direction ("To the chief Musician...")
# AND a historical/circumstantial note ("when David fled from...").  The Keil-
# Delitzsch and some other 19th-century commentaries used a Hebrew psalter that
# counted both parts as separate verses, so verse N in those sources maps to
# English verse N-2 instead of N-1.
# Currently confirmed: 51 ("after he had gone in to Bathsheba"), 52 ("when
# Doeg the Edomite came and told Saul"), 60 ("when he strove with Aram-
# naharaim..."). Expand this set if additional Psalms drop with a similar
# one-off-by-two pattern.
_PSALMS_WITH_DOUBLE_SUPERSCRIPTION: frozenset = frozenset({51, 52, 60})


def translate_hebrew_to_english(osis_ref: str) -> "Optional[str]":
    """Translate a Hebrew (MT) versification OSIS ref to its English equivalent.

    Handles several systematic versification differences between Hebrew/MT and
    English (KJV/BSB) editions:

    1. Psalms with superscriptions: Hebrew verse N = English verse N-1
       (superscription is counted as v.1 in MT).
    2. Psalms with double superscriptions: Hebrew verse N = English verse N-2
       (both a liturgical direction AND a historical note counted as separate
       verses in some 19th-century Hebrew psalters — see
       _PSALMS_WITH_DOUBLE_SUPERSCRIPTION).
    3. Joel ch.4: Hebrew Joel has 4 chapters; English has 3.
       Hebrew Joel 4:x = English Joel 3:x.
    4. Isaiah 8:23: Hebrew Isa 8 has 23 verses; English ch.8 ends at v.22
       and Hebrew 8:23 becomes English 9:1.
    5. Malachi 3:19-24: Hebrew Malachi has no ch.4; KJV splits at v.19.
       Hebrew Mal 3:19 = English Mal 4:1, ..., Hebrew Mal 3:24 = English Mal 4:6.
    6. Hosea 14:10: Hebrew Hos 14 has 10 verses; English has 9.
       Hebrew Hos 14:10 = English Hos 14:9.
    7. Hosea ch.2: Hebrew Hos 2:1-2 = English Hos 1:10-11; body of Hebrew
       ch.2 starts at v.3 = English 2:1. Hebrew Hos 2:N (N >= 3) = English
       Hos 2:(N-2).
    8. Job ch.40 (Keil-Delitzsch / Luther Bible boundary): in the Luther Bible
       and KD's source, Job ch.40 continues through English ch.41 verses 1-8.
       Hebrew Job 40:N (N >= 25) = English Job 41:(N-24).
    9. Esther additions (LXX continuous numbering): commentaries cite the six
       deuterocanonical Esther additions using 'Esth' + extended chapter numbers
       (ch.10-16). OSIS uses 'AddEsth' for these. No verse offset needed.
    10. Daniel additions (LXX continuous numbering): the Prayer of Azariah is
        inserted after Dan 3:23 in LXX editions. Dan.3.24 = PrAzar.1.1, etc.
        Offset: subtract 23 from the verse number.

    Returns None if no mapping applies (e.g. NT refs, Psalms without a
    superscription, genuinely invalid refs).

    This function is **pure** — no index loading, no validation, no side effects.
    Callers must re-validate the translated ref themselves.

    Examples:
        translate_hebrew_to_english("Ps.44.27")   -> "Ps.44.26"
        translate_hebrew_to_english("Ps.51.21")   -> "Ps.51.19"  (double superscription)
        translate_hebrew_to_english("Ps.3.1")     -> None  (superscription itself)
        translate_hebrew_to_english("Ps.1.6")     -> None  (Ps.1 has no superscription)
        translate_hebrew_to_english("Joel.4.16")  -> "Joel.3.16"
        translate_hebrew_to_english("Isa.8.23")   -> "Isa.9.1"
        translate_hebrew_to_english("Mal.3.22")   -> "Mal.4.4"
        translate_hebrew_to_english("Hos.2.24")   -> "Hos.2.22"
        translate_hebrew_to_english("Hos.14.10")  -> "Hos.14.9"
        translate_hebrew_to_english("Job.40.27")  -> "Job.41.3"
        translate_hebrew_to_english("Esth.14.11") -> "AddEsth.14.11"
        translate_hebrew_to_english("Dan.3.31")   -> "PrAzar.1.8"
        translate_hebrew_to_english("John.3.16")  -> None
    """
    parts = osis_ref.split(".")
    if len(parts) != 3:
        return None
    book, chapter_str, verse_str = parts
    try:
        chapter = int(chapter_str)
        verse = int(verse_str)
    except ValueError:
        return None

    # Psalms with double superscription: v.1 and v.2 are both superscription
    # verses (liturgical direction + historical note), body starts at v.3.
    # Hebrew verse N = English verse N-2. Verses 1-2 have no English equivalent.
    if book == "Ps" and chapter in _PSALMS_WITH_DOUBLE_SUPERSCRIPTION:
        if verse <= 2:
            return None
        return f"Ps.{chapter}.{verse - 2}"

    # Psalms with single superscription: superscription counted as v.1 in MT.
    # Hebrew verse N = English verse N-1.
    if book == "Ps" and chapter in _PSALMS_WITH_SUPERSCRIPTION:
        if verse <= 1:
            return None  # v1 is the superscription itself — no English equivalent
        return f"Ps.{chapter}.{verse - 1}"

    # Joel: Hebrew has 4 chapters, English has 3 — ch.4 becomes ch.3
    if book == "Joel" and chapter == 4:
        return f"Joel.3.{verse}"

    # Isaiah: Hebrew Isa 8 ends at v.23; English ch.8 ends at v.22, 8:23 → 9:1
    if book == "Isa" and chapter == 8 and verse == 23:
        return "Isa.9.1"

    # Malachi: Hebrew has no ch.4; KJV splits Heb 3:19-24 into Eng ch.4
    if book == "Mal" and chapter == 3 and verse >= 19:
        return f"Mal.4.{verse - 18}"

    # Hosea 2: Hebrew Hos 2:1-2 = English Hos 1:10-11 (not Hosea 2).
    # Body of Hebrew ch.2 starts at v.3 = English 2:1. Offset: -2.
    # Verses 1-2 map to English Hos 1:10-11 — valid refs, no translation needed
    # since translate_hebrew_to_english is only called for INVALID refs.
    if book == "Hos" and chapter == 2 and verse >= 3:
        return f"Hos.2.{verse - 2}"

    # Hosea 14: Hebrew has 10 verses, English has 9 — last verse offset -1
    if book == "Hos" and chapter == 14 and verse == 10:
        return "Hos.14.9"

    # Job 40 (Keil-Delitzsch / Luther Bible): ch.40 continues through English
    # ch.41:1-8. Hebrew Job 40:25+ = English Job 41:(verse-24).
    if book == "Job" and chapter == 40 and verse >= 25:
        return f"Job.41.{verse - 24}"

    # Esther additions (LXX continuous numbering): commentaries cite AddEsth using
    # canonical 'Esth' book code with extended chapter numbers (10-16).
    # Canonical Esther has 9 chapters; ch.10+ are the LXX additions in KJVA.
    # No verse offset — KJVA AddEsth uses the same chapter/verse numbers.
    if book == "Esth" and chapter >= 10:
        return f"AddEsth.{chapter}.{verse}"

    # Daniel additions (LXX continuous numbering): the Prayer of Azariah (PrAzar)
    # is inserted after Dan 3:23 in LXX editions, so Dan.3.24 = PrAzar.1.1, etc.
    # Offset: subtract 23 to get the PrAzar verse number.
    if book == "Dan" and chapter == 3 and verse >= 24:
        return f"PrAzar.1.{verse - 23}"

    return None


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
