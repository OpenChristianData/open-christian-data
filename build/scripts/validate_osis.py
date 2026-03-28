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

# Module-level cache -- loaded once on first use
_INDEX = None
_INDEX_LOADED = False


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
        return False, f"unknown book code '{book}'"

    if chapter_str is None:
        return True, ""  # book-level ref -- valid if book exists

    book_data = index_books[book]
    if chapter_str not in book_data["verse_counts"]:
        max_ch = book_data["chapter_count"]
        return False, f"{book} has no chapter {chapter_str} (book has {max_ch} chapters)"

    if verse_str is None:
        return True, ""  # chapter-level ref -- valid if chapter exists

    max_verse = book_data["verse_counts"][chapter_str]
    try:
        verse_int = int(verse_str)
    except ValueError:
        return False, f"non-integer verse '{verse_str}'"

    if verse_int < 1:
        return False, f"verse must be >= 1 (got {verse_str})"
    if verse_int > max_verse:
        return False, f"{book}.{chapter_str} has verses 1-{max_verse} (got {verse_str})"

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

    A range dash is preceded by a digit (end of a verse/chapter number) and
    followed by an upper-case letter or digit (start of a book code).
    Returns None if the string is not a range.

    Examples:
      Gen.1.1-Gen.1.3   -> dash at index 7
      1Thess.1.1-2Cor.1 -> dash found correctly
      1John.1.1         -> None (no dash in ref)
    """
    for i, ch in enumerate(osis_str):
        if ch == "-" and i > 0:
            prev_ch = osis_str[i - 1]
            next_ch = osis_str[i + 1] if i + 1 < len(osis_str) else ""
            if prev_ch.isdigit() and (next_ch.isupper() or next_ch.isdigit()):
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
