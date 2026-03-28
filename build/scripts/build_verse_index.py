"""build_verse_index.py
Build build/bible_data/verse_index.json from BSB data files.

The verse index records the max verse number per chapter for every book in the
Protestant canon, derived from the actual BSB data. It is used by validate_osis.py
to check that OSIS references resolve to real verses.

The index stores max_verse per chapter (not a flat list of all OSIS strings).
This means a ref like Gen.1.1 is valid if Gen chapter 1 exists and verse 1 <= max.
Note: BSB omits 16 textual-critical verses (e.g. Matt.17.21); their chapter's
max_verse still reflects the highest verse present in that chapter, so these
omitted verses will pass validation -- an acceptable false-positive for this
purpose (warnings, not errors).

Usage:
    py -3 build/scripts/build_verse_index.py
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BSB_DIR = REPO_ROOT / "data" / "bible-text" / "bsb"
OUTPUT_FILE = REPO_ROOT / "build" / "bible_data" / "verse_index.json"


def main():
    start_time = time.perf_counter()

    # Fail-fast: BSB data must exist
    if not BSB_DIR.exists():
        print(f"ERROR: BSB data directory not found: {BSB_DIR}")
        print("  Run prompt 0a (BSB bible_text schema + parser) first.")
        sys.exit(1)

    bsb_files = sorted(BSB_DIR.glob("*.json"))
    if not bsb_files:
        print(f"ERROR: No JSON files found in {BSB_DIR}")
        sys.exit(1)

    print(f"Building verse index from {len(bsb_files)} BSB files...")

    books = {}
    total_verses = 0
    problems = []

    for fpath in bsb_files:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)

        meta = data.get("meta", {})
        scope = meta.get("scope", {})
        book_name = scope.get("book", "")
        book_osis = scope.get("book_osis", "")
        book_number = scope.get("book_number", 0)
        entries = data.get("data", [])

        if not book_osis:
            problems.append(f"  SKIP {fpath.name}: missing meta.scope.book_osis")
            continue

        # Build max verse number per chapter from actual data entries.
        # Using max verse number (not count) so that the index reflects the canonical
        # verse numbering even when some verses are absent (textual-critical omissions).
        chapter_max_verse = {}  # {chapter_int: max_verse_int}
        for entry in entries:
            chapter = entry.get("chapter")
            verse = entry.get("verse")
            if isinstance(chapter, int) and isinstance(verse, int):
                if chapter not in chapter_max_verse:
                    chapter_max_verse[chapter] = verse
                else:
                    if verse > chapter_max_verse[chapter]:
                        chapter_max_verse[chapter] = verse

        # Represent verse_counts as {chapter_str: max_verse_int}, sorted by chapter number
        verse_counts = {
            str(ch): chapter_max_verse[ch]
            for ch in sorted(chapter_max_verse)
        }

        books[book_osis] = {
            "name": book_name,
            "book_osis": book_osis,
            "book_number": book_number,
            "chapter_count": len(verse_counts),
            "verse_counts": verse_counts,
        }
        total_verses += len(entries)
        print(f"  {book_osis:>8}  {book_name:<30} {len(entries):>5} verses  {len(verse_counts):>2} chapters")

    if problems:
        print()
        for p in problems:
            print(p)

    index = {
        "generated": date.today().isoformat(),
        "source": "BSB",
        "source_path": "data/bible-text/bsb/",
        "note": (
            "verse_counts gives max verse number per chapter from BSB data. "
            "The BSB omits 16 textual-critical verses; their chapter's max_verse "
            "still reflects the highest verse present."
        ),
        "total_verses": total_verses,
        "book_count": len(books),
        "books": books,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    print()
    elapsed = time.perf_counter() - start_time
    print(f"Written: {OUTPUT_FILE.relative_to(REPO_ROOT)}")
    print(f"  {len(books)} books, {total_verses} total verses  ({elapsed:.1f}s)")
    if problems:
        print(f"  {len(problems)} file(s) skipped (see above)")


if __name__ == "__main__":
    main()
