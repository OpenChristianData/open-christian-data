"""build_verse_index.py
Build build/bible_data/verse_index.json from BSB data files.

The verse index records the exact set of verse numbers present in BSB data for
every book in the Protestant canon.  It is used by validate_osis.py to check
that OSIS references resolve to real verses.

The index stores an explicit verse set per chapter (not a max-verse integer).
This means a ref like Gen.1.1 is valid only if verse 1 appears in the actual
BSB data for Gen chapter 1.  Textually-disputed verses absent from BSB (e.g.
Matt.17.21) will not appear in the verse set and will be caught at lookup time
— validate_osis.py consults a separate KNOWN_OMISSIONS table and returns a
downgraded "known omission" status rather than marking them invalid.

Index shape (per book):
    {
        "name": "Genesis",
        "book_osis": "Gen",
        "book_number": 1,
        "chapter_count": 50,
        "verses": {               # <-- explicit verse sets, not max-verse ints
            "1": [1, 2, ..., 31],
            "2": [1, 2, ..., 25],
            ...
        }
    }

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

EXPECTED_BOOK_COUNT = 66


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

        # Fix 1: record missing book_osis as a problem; abort after all files are
        # processed rather than writing a partial index.
        if not book_osis:
            problems.append(f"  SKIP {fpath.name}: missing meta.scope.book_osis")
            continue

        # Fix 2: detect duplicate book_osis values and abort immediately.
        if book_osis in books:
            existing_file = books[book_osis].get("_source_file", "<unknown>")
            print(
                f"ERROR: Duplicate book_osis '{book_osis}' in {fpath.name} — "
                f"already loaded from {existing_file}"
            )
            sys.exit(1)

        # Fix 3 + Fix 4: build the explicit verse set per chapter.
        # Any row where chapter or verse is not a positive int is a hard error —
        # the BSB data is expected to be clean and silent skips would corrupt the index.
        chapter_verses: dict[int, set[int]] = {}  # {chapter_int: {verse_int, ...}}
        for entry in entries:
            chapter = entry.get("chapter")
            verse = entry.get("verse")

            # Fix 3: fail loudly on malformed rows instead of silently skipping.
            if not isinstance(chapter, int) or chapter < 1:
                print(
                    f"ERROR: Malformed row in {fpath.name} — "
                    f"'chapter' is not a positive int: {entry!r}"
                )
                sys.exit(1)
            if not isinstance(verse, int) or verse < 1:
                print(
                    f"ERROR: Malformed row in {fpath.name} — "
                    f"'verse' is not a positive int: {entry!r}"
                )
                sys.exit(1)

            if chapter not in chapter_verses:
                chapter_verses[chapter] = set()
            chapter_verses[chapter].add(verse)

        # Fix 4: store sorted verse lists (explicit sets), not max-verse ints.
        verses = {
            str(ch): sorted(chapter_verses[ch])
            for ch in sorted(chapter_verses)
        }

        books[book_osis] = {
            "name": book_name,
            "book_osis": book_osis,
            "book_number": book_number,
            "chapter_count": len(verses),
            "verses": verses,
            "_source_file": fpath.name,  # used for duplicate-detection error message only
        }
        total_verses += len(entries)
        print(f"  {book_osis:>8}  {book_name:<30} {len(entries):>5} verses  {len(verses):>2} chapters")

    # Fix 1: abort if any files were skipped due to missing book_osis.
    if problems:
        print()
        for p in problems:
            print(p)
        print()
        print(
            f"ERROR: {len(problems)} file(s) skipped due to missing meta.scope.book_osis. "
            "Refusing to write a partial index."
        )
        sys.exit(1)

    # Fix 1: assert we collected exactly 66 books before writing.
    if len(books) != EXPECTED_BOOK_COUNT:
        expected_osis = {
            "Gen", "Exod", "Lev", "Num", "Deut", "Josh", "Judg", "Ruth",
            "1Sam", "2Sam", "1Kgs", "2Kgs", "1Chr", "2Chr", "Ezra", "Neh",
            "Esth", "Job", "Ps", "Prov", "Eccl", "Song", "Isa", "Jer",
            "Lam", "Ezek", "Dan", "Hos", "Joel", "Amos", "Obad", "Jonah",
            "Mic", "Nah", "Hab", "Zeph", "Hag", "Zech", "Mal",
            "Matt", "Mark", "Luke", "John", "Acts", "Rom",
            "1Cor", "2Cor", "Gal", "Eph", "Phil", "Col",
            "1Thess", "2Thess", "1Tim", "2Tim", "Titus", "Phlm",
            "Heb", "Jas", "1Pet", "2Pet", "1John", "2John", "3John",
            "Jude", "Rev",
        }
        missing = sorted(expected_osis - set(books))
        extra = sorted(set(books) - expected_osis)
        msg_parts = []
        if missing:
            msg_parts.append(f"missing books: {missing}")
        if extra:
            msg_parts.append(f"unexpected books: {extra}")
        print(
            f"ERROR: Expected {EXPECTED_BOOK_COUNT} books but got {len(books)}. "
            + "; ".join(msg_parts)
        )
        sys.exit(1)

    # Strip internal _source_file keys before writing the index.
    for book_data in books.values():
        book_data.pop("_source_file", None)

    index = {
        "generated": date.today().isoformat(),
        "source": "BSB",
        "source_path": "data/bible-text/bsb/",
        "note": (
            "verses gives the explicit set of verse numbers present in BSB data per chapter. "
            "Textually-disputed verses absent from BSB (e.g. Matt.17.21) will not appear "
            "in the verse set; validate_osis.py consults a KNOWN_OMISSIONS table and returns "
            "a downgraded 'known omission' status rather than 'invalid' for those refs."
        ),
        "total_verses": total_verses,
        "book_count": len(books),
        "books": books,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    elapsed = time.perf_counter() - start_time
    print()
    print(f"Written: {OUTPUT_FILE.relative_to(REPO_ROOT)}")
    print(f"  {len(books)} books, {total_verses} total verses  ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
