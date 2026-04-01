"""build_apocrypha_verse_index.py
Build build/bible_data/apocrypha_verse_index.json from pysword's KJVA canon.

The KJVA canon includes the deuterocanonical / apocryphal books in addition to
the standard 66-book Protestant canon.  This script extracts only the non-
Protestant books and writes their verse structure to a separate index.

Used by validate_osis.py as an existence oracle for refs with deuterocanonical
book codes (e.g. Wis.1.1, Sir.24.3, 1Macc.1.59).  Before this index existed,
any deuterocanonical ref passed validation unconditionally with
"deuterocanonical - not in verse index".  With this index, invalid refs
(wrong chapter/verse) are caught.

Data source: pysword canons['kjva'] -- the same library used by the SWORD
module parser.  Reading from pysword directly avoids transcription errors.

The index shape matches build/bible_data/verse_index.json:
    {
        "name": "Wisdom of Solomon",
        "book_osis": "Wis",
        "book_number": 1,    (ordinal within apocrypha, not canon-wide)
        "chapter_count": 19,
        "verses": {
            "1": [1, 2, ..., 16],
            ...
        }
    }

Usage:
    py -3 build/scripts/build_apocrypha_verse_index.py
"""

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FILE = REPO_ROOT / "build" / "bible_data" / "apocrypha_verse_index.json"
LOG_FILE = Path(__file__).resolve().parent / "build_apocrypha_verse_index.log"

# OSIS codes for the standard 66-book Protestant canon.
# Any book in the KJVA canon that is NOT in this set is deuterocanonical.
# ---------------------------------------------------------------------------
# Pysword KJVA data corrections.
# The KJVA canon in pysword has a known error: PrMan (Prayer of Manasseh) is
# listed as [1] (1 chapter, 1 verse), but the actual text has 15 verses.
# Other pysword canons (vulg, german, luther) correctly list PrMan as [15].
# Override here so the apocrypha index has the correct verse structure.
# ---------------------------------------------------------------------------
PYSWORD_OVERRIDES: dict = {
    "PrMan": [15],  # pysword KJVA says [1]; correct count is 15 verses
}

PROTESTANT_OSIS_CODES: frozenset = frozenset({
    "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "Ruth",
    "1Sam", "2Sam", "1Kgs", "2Kgs", "1Chr", "2Chr", "Ezra", "Neh",
    "Esth", "Job", "Ps", "Prov", "Eccl", "Song", "Isa", "Jer", "Lam",
    "Ezek", "Dan", "Hos", "Joel", "Amos", "Obad", "Jonah", "Mic", "Nah",
    "Hab", "Zeph", "Hag", "Zech", "Mal",
    "Matt", "Mark", "Luke", "John", "Acts", "Rom", "1Cor", "2Cor",
    "Gal", "Eph", "Phil", "Col", "1Thess", "2Thess", "1Tim", "2Tim",
    "Titus", "Phlm", "Heb", "Jas", "1Pet", "2Pet", "1John", "2John",
    "3John", "Jude", "Rev",
})

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def load_pysword_kjva() -> list:
    """Load the KJVA canon from pysword and return all book entries.

    Returns a list of (name, osis_code, chapter_lengths) tuples for every
    book in the KJVA canon (Protestant + deuterocanonical).
    """
    try:
        import pysword.canons as pysword_canons
    except ImportError:
        log.error("pysword is not installed. Run: pip install pysword")
        sys.exit(1)

    # pysword canons dict is named 'canons' inside pysword.canons
    canon_dict = getattr(pysword_canons, "canons", None)
    if canon_dict is None:
        log.error("pysword.canons has no 'canons' attribute -- unexpected structure.")
        log.error("  pysword attributes: %s", dir(pysword_canons))
        sys.exit(1)

    kjva = canon_dict.get("kjva")
    if kjva is None:
        log.error("pysword canons has no 'kjva' key. Available: %s", list(canon_dict.keys()))
        sys.exit(1)

    # Merge OT + NT lists (KJVA interleaves apocrypha within OT)
    all_books: list = []
    for testament_key in ("ot", "nt"):
        entries = kjva.get(testament_key, [])
        for entry in entries:
            # pysword entry: (name, osis_code, osis_alt, [chapter_verse_counts])
            name = entry[0]
            osis = entry[1]
            chapter_lengths = entry[3]
            all_books.append((name, osis, chapter_lengths))

    log.info("KJVA canon loaded from pysword: %d total books", len(all_books))
    return all_books


def main() -> None:
    start = time.time()
    log.info("=== build_apocrypha_verse_index.py ===")

    all_books = load_pysword_kjva()

    # Extract only the deuterocanonical books
    books: dict = {}
    ordinal = 0
    total_verses = 0

    for name, osis, chapter_lengths in all_books:
        if osis in PROTESTANT_OSIS_CODES:
            continue  # skip Protestant canon books

        # Apply overrides for known pysword KJVA data errors.
        if osis in PYSWORD_OVERRIDES:
            original = chapter_lengths
            chapter_lengths = PYSWORD_OVERRIDES[osis]
            log.info("  OVERRIDE %s: pysword %s -> corrected %s", osis, original, chapter_lengths)

        ordinal += 1
        chapter_verses: dict = {}
        for ch_idx, n_verses in enumerate(chapter_lengths):
            chapter = ch_idx + 1
            chapter_verses[str(chapter)] = list(range(1, n_verses + 1))

        ch_total = sum(len(v) for v in chapter_verses.values())
        total_verses += ch_total

        books[osis] = {
            "name": name,
            "book_osis": osis,
            "book_number": ordinal,
            "chapter_count": len(chapter_verses),
            "verses": chapter_verses,
        }
        log.info(
            "  %10s  %-30s  %3d chapters  %5d verses",
            osis, name, len(chapter_verses), ch_total,
        )

    if not books:
        log.error("No deuterocanonical books found in KJVA canon.")
        sys.exit(1)

    # Quality check: flag any book with suspiciously few verses.
    # A single-chapter deuterocanonical book should have at least 5 verses (the smallest
    # real book, PrMan, has 15).  Books with fewer likely have a pysword data error.
    MIN_PLAUSIBLE_VERSES = 5
    suspect_books = [
        (osis, sum(len(v) for v in b["verses"].values()))
        for osis, b in books.items()
        if sum(len(v) for v in b["verses"].values()) < MIN_PLAUSIBLE_VERSES
    ]
    if suspect_books:
        log.error(
            "Books with fewer than %d total verses (likely pysword data error -- "
            "add to PYSWORD_OVERRIDES if confirmed): %s",
            MIN_PLAUSIBLE_VERSES, suspect_books,
        )
        sys.exit(1)

    log.info("---")
    log.info("Deuterocanonical books: %d, total verses: %d", len(books), total_verses)

    # Write output
    index = {
        "generated": str(date.today()),
        "source": "pysword canons['kjva'] -- deuterocanonical books only",
        "description": (
            "Verse existence index for deuterocanonical / apocryphal books. "
            "Used by validate_osis.py to existence-check refs with book codes "
            "outside the Protestant 66-book canon (e.g. Wis.1.1, Sir.24.3). "
            "Derived from pysword KJVA canon -- same versification as the SWORD Project."
        ),
        "total_verses": total_verses,
        "book_count": len(books),
        "books": books,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start
    log.info("Output written to %s", OUTPUT_FILE)
    log.info("Completed in %.2fs", elapsed)


if __name__ == "__main__":
    main()
