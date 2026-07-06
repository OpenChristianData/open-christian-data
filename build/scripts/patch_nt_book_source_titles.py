"""
Patch source_title for NT-book author files (18 files, 329 entries).

Each file (romans.json, matthew.json, etc.) contains OT cross-reference entries
whose 'author' field is the NT book name. The entries are OT passages quoted IN
that NT book; source_title is definitionally the NT book itself.

PIPE-12 verification: no external lookup required. The 'author' field in each
entry is already set to the NT book name (e.g. "Romans", "Matthew") by the
upstream corpus; source_title is the canonical title of that same book. The
mapping is deterministic and requires no inference. All assignments are HIGH
confidence.

Run twice to verify idempotency (TEST-05).
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "church-fathers"

HIGH = "HIGH"

# Maps filename stem → (author field, source_title to assign)
NT_BOOK_MAP: dict[str, tuple[str, str]] = {
    "romans":         ("Romans",         "THE EPISTLE TO THE ROMANS"),
    "matthew":        ("Matthew",        "THE GOSPEL ACCORDING TO MATTHEW"),
    "acts":           ("Acts",           "THE ACTS OF THE APOSTLES"),
    "hebrews":        ("Hebrews",        "THE EPISTLE TO THE HEBREWS"),
    "mark":           ("Mark",           "THE GOSPEL ACCORDING TO MARK"),
    "luke":           ("Luke",           "THE GOSPEL ACCORDING TO LUKE"),
    "1-corinthians":  ("1 Corinthians",  "THE FIRST EPISTLE TO THE CORINTHIANS"),
    "2-corinthians":  ("2 Corinthians",  "THE SECOND EPISTLE TO THE CORINTHIANS"),
    "galatians":      ("Galatians",      "THE EPISTLE TO THE GALATIANS"),
    "ephesians":      ("Ephesians",      "THE EPISTLE TO THE EPHESIANS"),
    "james":          ("James",          "THE EPISTLE OF JAMES"),
    "revelation":     ("Revelation",     "THE REVELATION OF JOHN"),
    "1-peter":        ("1 Peter",        "THE FIRST EPISTLE OF PETER"),
    "john":           ("John",           "THE GOSPEL ACCORDING TO JOHN"),
    "philippians":    ("Philippians",    "THE EPISTLE TO THE PHILIPPIANS"),
    "2-peter":        ("2 Peter",        "THE SECOND EPISTLE OF PETER"),
    "jude":           ("Jude",           "THE EPISTLE OF JUDE"),
    "1-timothy":      ("1 Timothy",      "THE FIRST EPISTLE TO TIMOTHY"),
}

_EXPECTED_FILE_COUNT = 18


def patch_file(stem: str, expected_author: str, source_title: str) -> tuple[int, int, int]:
    """Patch one NT-book file. Returns (patched, skipped, unexpected)."""
    path = DATA_DIR / f"{stem}.json"
    if not path.exists():
        print(f"  [ERROR] {path.name} not found")
        return 0, 0, -1  # -1 signals missing file

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    patched = 0
    skipped = 0
    unexpected = 0

    for entry in entries:
        if entry.get("source_title"):
            skipped += 1
            continue
        author = entry.get("author", "")
        if author != expected_author:
            print(f"  [WARN] {entry['entry_id']}: unexpected author '{author}' (expected '{expected_author}')")
            unexpected += 1
            continue
        entry["source_title"] = source_title
        patched += 1

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return patched, skipped, unexpected


def main() -> None:
    assert len(NT_BOOK_MAP) == _EXPECTED_FILE_COUNT, (
        f"NT_BOOK_MAP has {len(NT_BOOK_MAP)} entries, expected {_EXPECTED_FILE_COUNT}. "
        "Update _EXPECTED_FILE_COUNT after adding or removing entries."
    )

    total_patched = 0
    total_skipped = 0
    total_unexpected = 0
    files_changed = 0
    files_already_done = 0
    files_missing = 0

    for stem, (expected_author, source_title) in NT_BOOK_MAP.items():
        patched, skipped, unexpected = patch_file(stem, expected_author, source_title)
        if unexpected == -1:
            # -1 signals missing file
            files_missing += 1
            continue
        if patched > 0:
            print(f"  {stem}: {patched} patched -> '{source_title}'")
            files_changed += 1
        elif skipped > 0 and patched == 0 and unexpected == 0:
            files_already_done += 1
        total_patched += patched
        total_skipped += skipped
        total_unexpected += unexpected

    print(f"\nSummary:")
    print(f"  Files changed:      {files_changed}")
    print(f"  Files already done: {files_already_done}")
    print(f"  Files missing:      {files_missing}")
    print(f"  Entries patched:    {total_patched}")
    print(f"  Entries skipped:    {total_skipped}")
    print(f"  Unexpected author:  {total_unexpected}")

    if files_missing > 0:
        print(f"\nERROR: {files_missing} expected file(s) not found -- review above.")
        return

    if total_patched == 0 and total_unexpected == 0:
        print("\nNo changes needed -- all entries already fully patched (idempotent re-run).")
        return

    if total_unexpected > 0:
        print(f"\nWARNING: {total_unexpected} entries had unexpected author values -- review above.")

    print("\nDone.")


if __name__ == "__main__":
    main()
