"""build_kjv_verse_index.py
Build build/bible_data/kjv_verse_index.json from the KJV SWORD module.

Derives the verse set for every book in the Protestant 66-book canon from the
KJV versification table (same canon used by build/parsers/sword_commentary.py).
Used by validate_osis.py as a secondary oracle: if a verse fails the BSB
(critical text) existence check but is present here, it is a textually-disputed
verse (KJV/TR tradition) rather than an invalid ref.

The KJV SWORD module from CrossWire is downloaded and unzipped to confirm the
module is present and valid.  The mods.d/kjv.conf entry is read as a sanity
check.  Verse structure is derived from the KJV_CANON table (not the BZV
binary) because the NT BZV in the CrossWire module is truncated at Rev.19.1
(module defect -- chapters 19-22 missing from binary index).

The index shape matches build/bible_data/verse_index.json exactly:
    {
        "name": "Matthew",
        "book_osis": "Matt",
        "book_number": 40,
        "chapter_count": 28,
        "verses": {
            "1": [1, 2, ..., 25],
            "17": [1, 2, ..., 20, 21, 22, ..., 27],   # 21 present in KJV
            ...
        }
    }

Usage:
    py -3 build/scripts/build_kjv_verse_index.py
"""

import json
import logging
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
KJV_ZIP = REPO_ROOT / "raw" / "sword_modules" / "KJV.zip"
KJV_DIR = REPO_ROOT / "raw" / "sword_modules" / "KJV"
MODULE_DATA_DIR = KJV_DIR / "modules" / "texts" / "ztext" / "kjv"
OUTPUT_FILE = REPO_ROOT / "build" / "bible_data" / "kjv_verse_index.json"
LOG_FILE = Path(__file__).parent / "build_kjv_verse_index.log"

EXPECTED_BOOK_COUNT = 66

# ---------------------------------------------------------------------------
# KJV versification table
# Derived from pysword canons['kjv'] -- the same table used by sword_commentary.py.
# Each entry: (canonical_name, osis_code, book_number, [chapter_verse_counts ...])
# ---------------------------------------------------------------------------

KJV_OT = [
    ("Genesis",        "Gen",    1,  [31,25,24,26,32,22,24,22,29,32,32,20,18,24,21,16,27,33,38,18,34,24,20,67,34,35,46,22,35,43,55,32,20,31,29,43,36,30,23,23,57,38,34,34,28,34,31,22,33,26]),
    ("Exodus",         "Exod",   2,  [22,25,22,31,23,30,25,32,35,29,10,51,22,31,27,36,16,27,25,26,36,31,33,18,40,37,21,43,46,38,18,35,23,35,35,38,29,31,43,38]),
    ("Leviticus",      "Lev",    3,  [17,16,17,35,19,30,38,36,24,20,47,8,59,57,33,34,16,30,37,27,24,33,44,23,55,46,34]),
    ("Numbers",        "Num",    4,  [54,34,51,49,31,27,89,26,23,36,35,16,33,45,41,50,13,32,22,29,35,41,30,25,18,65,23,31,40,16,54,42,56,29,34,13]),
    ("Deuteronomy",    "Deut",   5,  [46,37,29,49,33,25,26,20,29,22,32,32,18,29,23,22,20,22,21,20,23,30,25,22,19,19,26,68,29,20,30,52,29,12]),
    ("Joshua",         "Josh",   6,  [18,24,17,24,15,27,26,35,27,43,23,24,33,15,63,10,18,28,51,9,45,34,16,33]),
    ("Judges",         "Judg",   7,  [36,23,31,24,31,40,25,35,57,18,40,15,25,20,20,31,13,31,30,48,25]),
    ("Ruth",           "Ruth",   8,  [22,23,18,22]),
    ("1 Samuel",       "1Sam",   9,  [28,36,21,22,12,21,17,22,27,27,15,25,23,52,35,23,58,30,24,42,15,23,29,22,44,25,12,25,11,31,13]),
    ("2 Samuel",       "2Sam",   10, [27,32,39,12,25,23,29,18,13,19,27,31,39,33,37,23,29,33,43,26,22,51,39,25]),
    ("1 Kings",        "1Kgs",   11, [53,46,28,34,18,38,51,66,28,29,43,33,34,31,34,34,24,46,21,43,29,53]),
    ("2 Kings",        "2Kgs",   12, [18,25,27,44,27,33,20,29,37,36,21,21,25,29,38,20,41,37,37,21,26,20,37,20,30]),
    ("1 Chronicles",   "1Chr",   13, [54,55,24,43,26,81,40,40,44,14,47,40,14,17,29,43,27,17,19,8,30,19,32,31,31,32,34,21,30]),
    ("2 Chronicles",   "2Chr",   14, [17,18,17,22,14,42,22,18,31,19,23,16,22,15,19,14,19,34,11,37,20,12,21,27,28,23,9,27,36,27,21,33,25,33,27,23]),
    ("Ezra",           "Ezra",   15, [11,70,13,24,17,22,28,36,15,44]),
    ("Nehemiah",       "Neh",    16, [11,20,32,23,19,19,73,18,38,39,36,47,31]),
    ("Esther",         "Esth",   17, [22,23,15,17,14,14,10,17,32,3]),
    ("Job",            "Job",    18, [22,13,26,21,27,30,21,22,35,22,20,25,28,22,35,22,16,21,29,29,34,30,17,25,6,14,23,28,25,31,40,22,33,37,16,33,24,41,30,24,34,17]),
    ("Psalms",         "Ps",     19, [6,12,8,8,12,10,17,9,20,18,7,8,6,7,5,11,15,50,14,9,13,31,6,10,22,12,14,9,11,12,24,11,22,22,28,12,40,22,13,17,13,11,5,26,17,11,9,14,20,23,19,9,6,7,23,13,11,11,17,12,8,12,11,10,13,20,7,35,36,5,24,20,28,23,10,12,20,72,13,19,16,8,18,12,13,17,7,18,52,17,16,15,5,23,11,13,12,9,9,5,8,28,22,35,45,48,43,13,31,7,10,10,9,8,18,19,2,29,176,7,8,9,4,8,5,6,5,6,8,8,3,18,3,3,21,26,9,8,24,14,10,8,12,15,21,10,20,14,9,6]),
    ("Proverbs",       "Prov",   20, [33,22,35,27,23,35,27,36,18,32,31,28,25,35,33,33,28,24,29,30,31,29,35,34,28,28,27,28,27,33,31]),
    ("Ecclesiastes",   "Eccl",   21, [18,26,22,16,20,12,29,17,18,20,10,14]),
    ("Song of Solomon","Song",   22, [17,17,11,16,16,13,13,14]),
    ("Isaiah",         "Isa",    23, [31,22,26,6,30,13,25,22,21,34,16,6,22,32,9,14,14,7,25,6,17,25,18,23,12,21,13,29,24,33,9,20,24,17,10,22,38,22,8,31,29,25,28,28,25,13,15,22,26,11,23,15,12,17,13,12,21,14,21,22,11,12,19,12,25,24]),
    ("Jeremiah",       "Jer",    24, [19,37,25,31,31,30,34,22,26,25,23,17,27,22,21,21,27,23,15,18,14,30,40,10,38,24,22,17,32,24,40,44,26,22,19,32,21,28,18,16,18,22,13,30,5,28,7,47,39,46,64,34]),
    ("Lamentations",   "Lam",    25, [22,22,66,22,22]),
    ("Ezekiel",        "Ezek",   26, [28,10,27,17,17,14,27,18,11,22,25,28,23,23,8,63,24,32,14,49,32,31,49,27,17,21,36,26,21,26,18,32,33,31,15,38,28,23,29,49,26,20,27,31,25,24,23,35]),
    ("Daniel",         "Dan",    27, [21,49,30,37,31,28,28,27,27,21,45,13]),
    ("Hosea",          "Hos",    28, [11,23,5,19,15,11,16,14,17,15,12,14,16,9]),
    ("Joel",           "Joel",   29, [20,32,21]),
    ("Amos",           "Amos",   30, [15,16,15,13,27,14,17,14,15]),
    ("Obadiah",        "Obad",   31, [21]),
    ("Jonah",          "Jonah",  32, [17,10,10,11]),
    ("Micah",          "Mic",    33, [16,13,12,13,15,16,20]),
    ("Nahum",          "Nah",    34, [15,13,19]),
    ("Habakkuk",       "Hab",    35, [17,20,19]),
    ("Zephaniah",      "Zeph",   36, [18,15,20]),
    ("Haggai",         "Hag",    37, [15,23]),
    ("Zechariah",      "Zech",   38, [21,13,10,14,11,15,14,23,17,12,17,14,9,21]),
    ("Malachi",        "Mal",    39, [14,17,18,6]),
]

KJV_NT = [
    ("Matthew",        "Matt",   40, [25,23,17,25,48,34,29,34,38,42,30,50,58,36,39,28,27,35,30,34,46,46,39,51,46,75,66,20]),
    ("Mark",           "Mark",   41, [45,28,35,41,43,56,37,38,50,52,33,44,37,72,47,20]),
    ("Luke",           "Luke",   42, [80,52,38,44,39,49,50,56,62,42,54,59,35,35,32,31,37,43,48,47,38,71,56,53]),
    ("John",           "John",   43, [51,25,36,54,47,71,53,59,41,42,57,50,38,31,27,33,26,40,42,31,25]),
    ("Acts",           "Acts",   44, [26,47,26,37,42,15,60,40,43,48,30,25,52,28,41,40,34,28,41,38,40,30,35,27,27,32,44,31]),
    ("Romans",         "Rom",    45, [32,29,31,25,21,23,25,39,33,21,36,21,14,23,33,27]),
    ("1 Corinthians",  "1Cor",   46, [31,16,23,21,13,20,40,13,27,33,34,31,13,40,58,24]),
    ("2 Corinthians",  "2Cor",   47, [24,17,18,18,21,18,16,24,15,18,33,21,14]),
    ("Galatians",      "Gal",    48, [24,21,29,31,26,18]),
    ("Ephesians",      "Eph",    49, [23,22,21,28,20,12]),
    ("Philippians",    "Phil",   50, [30,30,21,23]),
    ("Colossians",     "Col",    51, [29,23,25,18]),
    ("1 Thessalonians","1Thess", 52, [10,20,13,18,28]),
    ("2 Thessalonians","2Thess", 53, [12,17,18]),
    ("1 Timothy",      "1Tim",   54, [20,15,16,16,25,21]),
    ("2 Timothy",      "2Tim",   55, [18,26,17,22]),
    ("Titus",          "Titus",  56, [16,15,15]),
    ("Philemon",       "Phlm",   57, [25]),
    ("Hebrews",        "Heb",    58, [14,18,19,16,14,20,28,13,28,39,40,29,25]),
    ("James",          "Jas",    59, [27,26,18,17,20]),
    ("1 Peter",        "1Pet",   60, [25,25,22,19,14]),
    ("2 Peter",        "2Pet",   61, [21,22,18]),
    ("1 John",         "1John",  62, [10,29,24,21,21]),
    ("2 John",         "2John",  63, [13]),
    ("3 John",         "3John",  64, [15]),
    ("Jude",           "Jude",   65, [25]),
    ("Revelation",     "Rev",    66, [20,29,22,11,14,17,17,13,21,11,19,17,18,20,8,21,18,24,21,15,27,21]),
]


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    _setup_logging()
    start_time = time.perf_counter()

    # 1. Unzip KJV module if not already extracted
    if not MODULE_DATA_DIR.exists():
        if not KJV_ZIP.exists():
            logging.error("KJV ZIP not found: %s", KJV_ZIP)
            logging.error("  Run: py -3 build/scripts/download_sword_modules.py")
            sys.exit(1)
        logging.info("Extracting %s ...", KJV_ZIP.name)
        with zipfile.ZipFile(KJV_ZIP) as z:
            z.extractall(KJV_DIR)
        logging.info("  Extracted to %s", KJV_DIR)
    else:
        logging.info("KJV module already extracted at %s", KJV_DIR)

    # 2. Sanity-check: confirm the conf file identifies this as the KJV text module
    conf_path = KJV_DIR / "mods.d" / "kjv.conf"
    if not conf_path.exists():
        logging.error("conf not found: %s", conf_path)
        logging.error("  The extracted KJV archive may be corrupt -- delete %s and re-run "
                      "download_sword_modules.py to re-download.", KJV_DIR)
        sys.exit(1)
    conf_text = conf_path.read_text(encoding="utf-8", errors="replace")
    if "ModDrv=zText" not in conf_text:
        logging.error("%s does not look like a zText Bible module -- "
                      "delete %s and re-run download_sword_modules.py.", conf_path.name, KJV_DIR)
        logging.error("  First 200 chars of conf: %s", conf_text[:200])
        sys.exit(1)
    logging.info("Module conf: %s OK (zText confirmed)", conf_path.name)

    # 2b. Compare actual BZV entry counts against expected to detect module truncation.
    #
    # Expected count formula (from pysword SWORD positional index):
    #   total = 2 (testament headers)
    #         + sum over books of: sum(chapter_lengths) + len(chapter_lengths) + 1
    # If actual < expected, the CrossWire module is truncated (known: NT ends at Rev.19.1).
    # This check is informational -- verse structure is still derived from KJV_CANON below.
    for testament_label, testament_books, bzv_filename in [
        ("OT", KJV_OT, "ot.bzv"),
        ("NT", KJV_NT, "nt.bzv"),
    ]:
        bzv_path = MODULE_DATA_DIR / bzv_filename
        if bzv_path.exists():
            actual_entries = bzv_path.stat().st_size // 10
            expected_entries = 2 + sum(
                sum(ch) + len(ch) + 1
                for _, _, _, ch in testament_books
            )
            diff = actual_entries - expected_entries
            if diff == 0:
                logging.info("  %s BZV: %d entries (matches canon)", testament_label, actual_entries)
            elif diff > 0:
                # Extra entries: likely empty positional slots for apocryphal books.
                # Benign -- verse structure is derived from canon table, not BZV.
                logging.info(
                    "  %s BZV: %d actual vs %d expected (+%d extra slots, likely apocrypha "
                    "placeholders -- benign)",
                    testament_label, actual_entries, expected_entries, diff,
                )
            else:
                # Fewer entries than expected: module is truncated.
                # Known CrossWire defect: NT BZV ends at Rev.19.1 (86 entries short).
                logging.warning(
                    "  %s BZV: %d actual vs %d expected (%d short -- module truncated). "
                    "If this defect is ever fixed, rebuild kjv_verse_index.json.",
                    testament_label, actual_entries, expected_entries, -diff,
                )

    # 3. Build verse index from KJV_CANON.
    #
    # We derive the verse set from the canon table rather than parsing the BZV
    # binary because the CrossWire NT BZV is truncated at Rev.19.1 (module
    # defect -- chapters 19-22 are missing from the binary index).  The canon
    # table is the authoritative source for KJV versification: for each chapter
    # with N verse slots, all verses 1..N are considered present in KJV.
    books = {}
    total_verses = 0

    for testament_label, testament_books in [("OT", KJV_OT), ("NT", KJV_NT)]:
        logging.info("")
        logging.info("Processing %s (%d books)...", testament_label, len(testament_books))

        for name, osis, book_num, chapter_lengths in testament_books:
            chapter_verses: dict[str, list[int]] = {}

            for ch_idx, n_verses in enumerate(chapter_lengths):
                chapter = ch_idx + 1
                chapter_verses[str(chapter)] = list(range(1, n_verses + 1))

            books[osis] = {
                "name": name,
                "book_osis": osis,
                "book_number": book_num,
                "chapter_count": len(chapter_verses),
                "verses": chapter_verses,
            }
            ch_total = sum(len(v) for v in chapter_verses.values())
            total_verses += ch_total
            logging.info(
                "  %8s  %-22s %5d verses  %3d chapters",
                osis, name, ch_total, len(chapter_verses),
            )

    # 4. Sanity-check expected book count
    if len(books) != EXPECTED_BOOK_COUNT:
        logging.error("Expected %d books, got %d", EXPECTED_BOOK_COUNT, len(books))
        sys.exit(1)

    # 4b. Chapter-count plausibility check.
    # Reference chapter counts for the 66-book Protestant canon -- these do not vary
    # between KJV and any modern English translation.  If the canon table has a
    # transcription error (wrong number of entries in the chapter-lengths array), this
    # catches it immediately.
    EXPECTED_CHAPTERS = {
        "Gen": 50, "Exod": 40, "Lev": 27, "Num": 36, "Deut": 34,
        "Josh": 24, "Judg": 21, "Ruth": 4, "1Sam": 31, "2Sam": 24,
        "1Kgs": 22, "2Kgs": 25, "1Chr": 29, "2Chr": 36, "Ezra": 10,
        "Neh": 13, "Esth": 10, "Job": 42, "Ps": 150, "Prov": 31,
        "Eccl": 12, "Song": 8, "Isa": 66, "Jer": 52, "Lam": 5,
        "Ezek": 48, "Dan": 12, "Hos": 14, "Joel": 3, "Amos": 9,
        "Obad": 1, "Jonah": 4, "Mic": 7, "Nah": 3, "Hab": 3,
        "Zeph": 3, "Hag": 2, "Zech": 14, "Mal": 4,
        "Matt": 28, "Mark": 16, "Luke": 24, "John": 21, "Acts": 28,
        "Rom": 16, "1Cor": 16, "2Cor": 13, "Gal": 6, "Eph": 6,
        "Phil": 4, "Col": 4, "1Thess": 5, "2Thess": 3, "1Tim": 6,
        "2Tim": 4, "Titus": 3, "Phlm": 1, "Heb": 13, "Jas": 5,
        "1Pet": 5, "2Pet": 3, "1John": 5, "2John": 1, "3John": 1,
        "Jude": 1, "Rev": 22,
    }
    ch_errors = []
    for osis, book_data in books.items():
        actual_ch = book_data["chapter_count"]
        expected_ch = EXPECTED_CHAPTERS.get(osis)
        if expected_ch is not None and actual_ch != expected_ch:
            ch_errors.append(f"{osis}: expected {expected_ch} chapters, got {actual_ch}")
    if ch_errors:
        for err in ch_errors:
            logging.error("Chapter-count mismatch: %s", err)
        logging.error("Fix the KJV_CANON table above before proceeding.")
        sys.exit(1)
    logging.info("  Chapter-count plausibility check: all %d books OK", len(books))

    # 5. Spot-check: all KNOWN_OMISSIONS verses (from validate_osis.py) must be present
    disputed = [
        ("Matt", "17", 21), ("Matt", "18", 11), ("Matt", "23", 14),
        ("Mark", "7",  16), ("Mark", "9",  44), ("Mark", "9",  46),
        ("Luke", "17", 36), ("John", "5",   4),
        ("Acts", "8",  37), ("Rom",  "16", 24),
    ]
    all_ok = True
    for osis, ch_str, v in disputed:
        ch_verses = books.get(osis, {}).get("verses", {}).get(ch_str, [])
        if v not in ch_verses:
            logging.error("Spot-check FAILED: %s.%s.%d not found in KJV index", osis, ch_str, v)
            all_ok = False
        else:
            logging.info("  Spot-check %s.%s.%d: OK", osis, ch_str, v)
    if not all_ok:
        sys.exit(1)

    # 6. Write output
    index = {
        "generated": date.today().isoformat(),
        "source": "KJV",
        "source_path": "raw/sword_modules/KJV/",
        "note": (
            "verses gives the complete set of verse numbers present in the KJV "
            "versification per chapter (derived from pysword KJV canon table). "
            "Used as a secondary oracle by validate_osis.py: if a verse is absent "
            "from BSB (critical text) but present here, it is a textually-disputed "
            "verse (KJV/TR tradition) rather than an invalid ref."
        ),
        "total_verses": total_verses,
        "book_count": len(books),
        "books": books,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    elapsed = time.perf_counter() - start_time
    logging.info("")
    logging.info("Written: %s", OUTPUT_FILE.relative_to(REPO_ROOT))
    logging.info("  %d books, %d total verses  (%.1fs)", len(books), total_verses, elapsed)


if __name__ == "__main__":
    main()
