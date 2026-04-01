"""generate_disputed_verses.py
Generate build/bible_data/disputed_verses.json -- the exhaustive set of
verses present in KJV/TR versification but absent from the BSB critical text.

This is the definitive source for Layer 1 reference coverage: any verse ref
that passes KJV validation but fails BSB validation is classified here as
either a manuscript omission or a versification offset.

Two types are distinguished:

  manuscript_omission
    A verse present in the Textus Receptus / KJV tradition but absent from the
    modern critical text (Nestle-Aland / BSB base text).  These are genuine
    textual disputes -- e.g. Matt.17.21, John.5.4.

  versification_offset
    A verse number that exists in the SWORD/MT versification scheme but not in
    the standard English/BSB verse numbering.  The underlying text is the same;
    only the numbering differs.  Currently this affects a small number of
    Psalms where the SWORD KJV module follows the Hebrew Masoretic tradition of
    counting the superscription ("To the Chief Musician...") as verse 1,
    making subsequent verses one number higher than in the printed English KJV.
    These refs will not appear in a commentary citing the printed English KJV.

Output format:
    {
        "generated": "2026-04-01",
        "description": "...",
        "total_count": 19,
        "counts": {"manuscript_omission": 17, "versification_offset": 2},
        "books": {
            "Matt": {"17": [{"verse": 21, "type": "manuscript_omission"}], ...},
            "Ps":   {"140": [{"verse": 14, "type": "versification_offset"}], ...}
        }
    }

Usage:
    py -3 build/scripts/generate_disputed_verses.py
"""

import json
import logging
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSE_INDEX_PATH = REPO_ROOT / "build" / "bible_data" / "verse_index.json"
KJV_INDEX_PATH = REPO_ROOT / "build" / "bible_data" / "kjv_verse_index.json"
OUTPUT_FILE = REPO_ROOT / "build" / "bible_data" / "disputed_verses.json"
LOG_FILE = Path(__file__).resolve().parent / "generate_disputed_verses.log"

# Single source of truth for versification offsets lives in validate_osis.py
# (which is the module that acts on this classification at runtime).
sys.path.insert(0, str(REPO_ROOT))
from build.scripts.validate_osis import VERSIFICATION_OFFSETS  # noqa: E402

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


def load_index(path: Path, label: str) -> dict:
    """Load a verse index JSON file. Exits on failure."""
    if not path.exists():
        log.error("Index file not found: %s", path)
        log.error("Run the corresponding build script to generate it.")
        sys.exit(1)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        log.info("Loaded %s index from %s", label, path)
        return data
    except Exception as exc:
        log.error("Failed to load %s index from %s: %s", label, path, exc)
        sys.exit(1)


def compute_disputed(bsb_index: dict, kjv_index: dict) -> dict:
    """Compute verses present in KJV but absent from BSB.

    Returns {book_osis: {chapter_str: [{verse, type}, ...]}} containing only
    books and chapters with at least one disputed verse.
    """
    bsb_books = bsb_index.get("books", {})
    kjv_books = kjv_index.get("books", {})

    disputed: dict = {}

    for book_osis, kjv_book in kjv_books.items():
        kjv_chapters = kjv_book.get("verses", {})
        bsb_book = bsb_books.get(book_osis, {})
        bsb_chapters = bsb_book.get("verses", {})

        book_disputed: dict = {}
        for chapter_str, kjv_verses in kjv_chapters.items():
            kjv_set = set(kjv_verses)
            bsb_set = set(bsb_chapters.get(chapter_str, []))
            missing = sorted(kjv_set - bsb_set)
            if missing:
                book_disputed[chapter_str] = [
                    {
                        "verse": v,
                        "type": (
                            "versification_offset"
                            if (book_osis, chapter_str, v) in VERSIFICATION_OFFSETS
                            else "manuscript_omission"
                        ),
                    }
                    for v in missing
                ]

        if book_disputed:
            disputed[book_osis] = book_disputed

    return disputed


def main() -> None:
    start = __import__("time").time()
    log.info("=== generate_disputed_verses.py ===")

    # Load both indexes
    bsb_index = load_index(VERSE_INDEX_PATH, "BSB")
    kjv_index = load_index(KJV_INDEX_PATH, "KJV")

    # Compute diff
    disputed = compute_disputed(bsb_index, kjv_index)

    # Count totals by type
    total_count = 0
    type_counts: dict = {}
    for book_chapters in disputed.values():
        for verse_list in book_chapters.values():
            for entry in verse_list:
                total_count += 1
                t = entry["type"]
                type_counts[t] = type_counts.get(t, 0) + 1

    # Build output
    output = {
        "generated": str(date.today()),
        "description": (
            "Verses present in KJV/TR versification but absent from the BSB critical text. "
            "type='manuscript_omission': verse absent from modern critical text (textual dispute). "
            "type='versification_offset': verse numbering differs due to SWORD/MT superscription "
            "counting -- the underlying text is the same, only the verse number differs."
        ),
        "total_count": total_count,
        "counts": type_counts,
        "books": disputed,
    }

    # Write output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    elapsed = __import__("time").time() - start
    log.info("---")
    if total_count == 0:
        log.error(
            "No disputed verses found -- KJV and BSB indexes appear identical. "
            "This is known to be wrong. Check that both indexes were rebuilt correctly."
        )
        sys.exit(1)
    log.info("Disputed verses found: %d across %d book(s)", total_count, len(disputed))
    for t, cnt in sorted(type_counts.items()):
        log.info("  %s: %d", t, cnt)

    log.info("---")
    # Print per-book detail
    for book_osis, book_chapters in disputed.items():
        for chapter_str, verse_list in book_chapters.items():
            summary = [(e["verse"], e["type"][0]) for e in verse_list]
            log.info("  %s.%s: %s", book_osis, chapter_str, summary)

    log.info("---")
    log.info("Output written to %s", OUTPUT_FILE)
    log.info("Completed in %.2fs", elapsed)


if __name__ == "__main__":
    main()
