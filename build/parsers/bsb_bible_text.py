"""bsb_bible_text.py
Parse the Berean Standard Bible (CC0) from raw/bible_databases/formats/json/BSB.json
into OCD bible_text schema files -- one JSON per book.

Output: data/bible-text/bsb/<book-slug>.json

Usage:
    py -3 build/parsers/bsb_bible_text.py --dry-run
    py -3 build/parsers/bsb_bible_text.py
    py -3 build/parsers/bsb_bible_text.py --book Gen
    py -3 build/parsers/bsb_bible_text.py --book Ps

Before running all 66 books for the first time, verify the source structure
across representative categories:
    py -3 build/parsers/bsb_bible_text.py --dry-run --book Ps   (OT poetry)
    py -3 build/parsers/bsb_bible_text.py --dry-run --book Rom  (NT epistle)
If verse counts in the dry-run look wrong (0 or suspiciously low), stop and
inspect the BSB.json structure before proceeding to the full run.
"""

import argparse
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
BSB_PATH = REPO_ROOT / "raw" / "bible_databases" / "formats" / "json" / "BSB.json"
OUTPUT_DIR = REPO_ROOT / "data" / "bible-text" / "bsb"
CONFIG_PATH = REPO_ROOT / "sources" / "bible-text" / "bsb" / "config.json"
LOG_PATH = REPO_ROOT / "build" / "parsers" / "bsb_bible_text.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

# Spot-check expected verse counts for key books (Gen=OT prose, Ps=OT poetry, Rev=NT apocalyptic).
# These reflect actual BSB.json counts -- do NOT hard-fail on a different total,
# but DO report any mismatch so it surfaces immediately.
SPOT_CHECKS = [
    # (osis_code, expected_verse_count_including_textual_critical)
    ("Gen", 1533),
    ("Ps", 2461),
    ("Rev", 404),
]

# ---------------------------------------------------------------------------
# Book code mappings
# ---------------------------------------------------------------------------

# BSB.json uses Roman numeral prefixes and "Revelation of John"
BSB_NAME_TO_OSIS = {
    "Genesis": "Gen", "Exodus": "Exod", "Leviticus": "Lev",
    "Numbers": "Num", "Deuteronomy": "Deut", "Joshua": "Josh",
    "Judges": "Judg", "Ruth": "Ruth",
    "I Samuel": "1Sam", "II Samuel": "2Sam",
    "I Kings": "1Kgs", "II Kings": "2Kgs",
    "I Chronicles": "1Chr", "II Chronicles": "2Chr",
    "Ezra": "Ezra", "Nehemiah": "Neh", "Esther": "Esth",
    "Job": "Job", "Psalms": "Ps", "Proverbs": "Prov",
    "Ecclesiastes": "Eccl", "Song of Solomon": "Song",
    "Isaiah": "Isa", "Jeremiah": "Jer", "Lamentations": "Lam",
    "Ezekiel": "Ezek", "Daniel": "Dan", "Hosea": "Hos",
    "Joel": "Joel", "Amos": "Amos", "Obadiah": "Obad",
    "Jonah": "Jonah", "Micah": "Mic", "Nahum": "Nah",
    "Habakkuk": "Hab", "Zephaniah": "Zeph", "Haggai": "Hag",
    "Zechariah": "Zech", "Malachi": "Mal",
    "Matthew": "Matt", "Mark": "Mark", "Luke": "Luke",
    "John": "John", "Acts": "Acts", "Romans": "Rom",
    "I Corinthians": "1Cor", "II Corinthians": "2Cor",
    "Galatians": "Gal", "Ephesians": "Eph", "Philippians": "Phil",
    "Colossians": "Col", "I Thessalonians": "1Thess",
    "II Thessalonians": "2Thess", "I Timothy": "1Tim",
    "II Timothy": "2Tim", "Titus": "Titus", "Philemon": "Phlm",
    "Hebrews": "Heb", "James": "Jas",
    "I Peter": "1Pet", "II Peter": "2Pet",
    "I John": "1John", "II John": "2John", "III John": "3John",
    "Jude": "Jude", "Revelation of John": "Rev",
}

# Canonical English names keyed by OSIS code (used for output file naming)
OSIS_TO_NAME = {
    "Gen": "Genesis", "Exod": "Exodus", "Lev": "Leviticus",
    "Num": "Numbers", "Deut": "Deuteronomy", "Josh": "Joshua",
    "Judg": "Judges", "Ruth": "Ruth", "1Sam": "1 Samuel",
    "2Sam": "2 Samuel", "1Kgs": "1 Kings", "2Kgs": "2 Kings",
    "1Chr": "1 Chronicles", "2Chr": "2 Chronicles", "Ezra": "Ezra",
    "Neh": "Nehemiah", "Esth": "Esther", "Job": "Job",
    "Ps": "Psalms", "Prov": "Proverbs", "Eccl": "Ecclesiastes",
    "Song": "Song of Solomon", "Isa": "Isaiah", "Jer": "Jeremiah",
    "Lam": "Lamentations", "Ezek": "Ezekiel", "Dan": "Daniel",
    "Hos": "Hosea", "Joel": "Joel", "Amos": "Amos",
    "Obad": "Obadiah", "Jonah": "Jonah", "Mic": "Micah",
    "Nah": "Nahum", "Hab": "Habakkuk", "Zeph": "Zephaniah",
    "Hag": "Haggai", "Zech": "Zechariah", "Mal": "Malachi",
    "Matt": "Matthew", "Mark": "Mark", "Luke": "Luke",
    "John": "John", "Acts": "Acts", "Rom": "Romans",
    "1Cor": "1 Corinthians", "2Cor": "2 Corinthians",
    "Gal": "Galatians", "Eph": "Ephesians", "Phil": "Philippians",
    "Col": "Colossians", "1Thess": "1 Thessalonians",
    "2Thess": "2 Thessalonians", "1Tim": "1 Timothy",
    "2Tim": "2 Timothy", "Titus": "Titus", "Phlm": "Philemon",
    "Heb": "Hebrews", "Jas": "James", "1Pet": "1 Peter",
    "2Pet": "2 Peter", "1John": "1 John", "2John": "2 John",
    "3John": "3 John", "Jude": "Jude", "Rev": "Revelation",
}

OSIS_BOOK_NUMBER = {
    "Gen": 1, "Exod": 2, "Lev": 3, "Num": 4, "Deut": 5, "Josh": 6,
    "Judg": 7, "Ruth": 8, "1Sam": 9, "2Sam": 10, "1Kgs": 11, "2Kgs": 12,
    "1Chr": 13, "2Chr": 14, "Ezra": 15, "Neh": 16, "Esth": 17, "Job": 18,
    "Ps": 19, "Prov": 20, "Eccl": 21, "Song": 22, "Isa": 23, "Jer": 24,
    "Lam": 25, "Ezek": 26, "Dan": 27, "Hos": 28, "Joel": 29, "Amos": 30,
    "Obad": 31, "Jonah": 32, "Mic": 33, "Nah": 34, "Hab": 35, "Zeph": 36,
    "Hag": 37, "Zech": 38, "Mal": 39, "Matt": 40, "Mark": 41, "Luke": 42,
    "John": 43, "Acts": 44, "Rom": 45, "1Cor": 46, "2Cor": 47, "Gal": 48,
    "Eph": 49, "Phil": 50, "Col": 51, "1Thess": 52, "2Thess": 53,
    "1Tim": 54, "2Tim": 55, "Titus": 56, "Phlm": 57, "Heb": 58,
    "Jas": 59, "1Pet": 60, "2Pet": 61, "1John": 62, "2John": 63,
    "3John": 64, "Jude": 65, "Rev": 66,
}


def book_slug(osis_code: str) -> str:
    """Return the output filename stem for a given OSIS code.

    Uses canonical English name: '1 Kings' -> '1-kings', 'Psalms' -> 'psalms'.
    Consistent with commentary file naming in helloao_commentary.py.
    """
    name = OSIS_TO_NAME.get(osis_code, osis_code)
    return name.lower().replace(" ", "-")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("bsb_bible_text")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(str(LOG_PATH), encoding="utf-8")
    fh.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def load_bsb() -> list:
    """Load BSB.json and return the books list."""
    if not BSB_PATH.exists():
        raise FileNotFoundError(f"BSB source not found: {BSB_PATH}")
    with open(BSB_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["books"]


def load_config() -> dict:
    """Load sources/bible-text/bsb/config.json."""
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: Path) -> str:
    """Return sha256:<hex> for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def build_meta(config: dict, osis_code: str, today: str, source_hash: str) -> dict:
    """Build the meta envelope for one book file."""
    book_name = OSIS_TO_NAME.get(osis_code, osis_code)
    book_number = OSIS_BOOK_NUMBER[osis_code]
    return {
        "id": config["resource_id"],
        "title": config["title"],
        "language": config["language"],
        "original_language": "en",
        "tradition": config["tradition"],
        "tradition_notes": config["tradition_notes"],
        "license": config["license"],
        "schema_type": "bible_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": today,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/bsb_bible_text.py@{SCRIPT_VERSION}",
            "processing_date": today,
            "notes": config.get("notes"),
        },
        "scope": {
            "book": book_name,
            "book_osis": osis_code,
            "book_number": book_number,
        },
    }


def process_book(book_data: dict, config: dict, today: str,
                 source_hash: str, dry_run: bool = False,
                 logger: logging.Logger = None) -> dict:
    """Process one BSB book dict into OCD format. Returns stats dict."""
    bsb_name = book_data["name"]
    osis_code = BSB_NAME_TO_OSIS.get(bsb_name)
    if not osis_code:
        msg = f"Unknown BSB book name: '{bsb_name}' -- skipping"
        print(f"  ERROR: {msg}")
        if logger:
            logger.error(msg)
        return {}

    book_name = OSIS_TO_NAME.get(osis_code, osis_code)
    slug = book_slug(osis_code)
    out_file = OUTPUT_DIR / f"{slug}.json"

    chapters = book_data.get("chapters", [])
    entries = []
    empty_text_count = 0

    for ch_data in chapters:
        ch_num = ch_data["chapter"]
        for v_data in ch_data.get("verses", []):
            v_num = v_data["verse"]
            raw_text = v_data.get("text", "")
            text = raw_text.strip()

            if not text:
                # BSB intentionally omits text for textual-critical verses
                # (e.g., Matt.17.21, Mark.7.16) that appear in the KJV
                # but lack manuscript support. Skip -- no text to record.
                empty_text_count += 1
                if logger:
                    logger.warning("Skipping empty text at %s.%s.%s", osis_code, ch_num, v_num)
                continue

            entries.append({
                "osis": f"{osis_code}.{ch_num}.{v_num}",
                "chapter": ch_num,
                "verse": v_num,
                "text": text,
                "word_count": len(text.split()) if text else 0,
            })

    verse_count = len(entries)
    source_verse_count = verse_count + empty_text_count  # total rows in BSB.json for this book
    chapter_count = len(chapters)

    if dry_run:
        # Show first 3 entries as sample
        print(f"  [dry-run] {book_name} ({osis_code}): {chapter_count} chapters, {verse_count} verses")
        for e in entries[:3]:
            print(f"    {e['osis']}: {e['text'][:60]!r}...")
        print(f"  [dry-run] Would write to: {out_file.name}")
        return {
            "osis_code": osis_code,
            "book": book_name,
            "chapter_count": chapter_count,
            "verse_count": verse_count,
            "source_verse_count": source_verse_count,
            "status": "dry-run",
        }

    meta = build_meta(config, osis_code, today, source_hash)
    output = {"meta": meta, "data": entries}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = out_file.stat().st_size / 1024
    words = [e["word_count"] for e in entries if e["word_count"] > 0]
    skipped_note = f" (skipped {empty_text_count} textual-critical)" if empty_text_count else ""
    print(f"  {book_name}: {verse_count} verses{skipped_note}, {size_kb:.0f} KB -> {out_file.name}")

    if words:
        sorted_words = sorted(words)
        print(
            f"    Words per verse: min={min(words)} "
            f"med={sorted_words[len(sorted_words)//2]} max={max(words)}"
        )

    if logger:
        logger.info(
            "Wrote %s: %d chapters, %d verses (%d skipped), %d KB",
            out_file.name, chapter_count, verse_count, empty_text_count, int(size_kb),
        )

    return {
        "osis_code": osis_code,
        "book": book_name,
        "chapter_count": chapter_count,
        "verse_count": verse_count,
        "source_verse_count": source_verse_count,
        "skipped_count": empty_text_count,
        "file": f"{slug}.json",
        "status": "complete" if not empty_text_count else "partial",
    }


# ---------------------------------------------------------------------------
# Spot-checks
# ---------------------------------------------------------------------------


def run_spot_checks(stats_by_osis: dict, logger: logging.Logger = None) -> None:
    """Verify expected verse counts for key books.

    Note: SPOT_CHECKS counts include textual-critical verses present in BSB.json.
    Written verse counts may be slightly lower (textual-critical entries are skipped).
    A mismatch here does not mean the run failed -- it means inspect the diff.
    """
    print()
    print("Spot-checks (total in source including textual-critical):")
    all_passed = True
    for osis_code, expected in SPOT_CHECKS:
        book_stats = stats_by_osis.get(osis_code, {})
        actual = book_stats.get("source_verse_count")
        if actual == expected:
            print(f"  PASS: {osis_code} -- {actual} verses in source (expected {expected})")
            if logger:
                logger.info("Spot-check PASS: %s -- %s verses", osis_code, actual)
        else:
            print(f"  FAIL: {osis_code} -- got {actual}, expected {expected}")
            if logger:
                logger.warning("Spot-check FAIL: %s -- got %s, expected %s", osis_code, actual, expected)
            all_passed = False
    if all_passed:
        print("  All spot-checks passed.")
    else:
        print("  WARNING: spot-check failures -- inspect BSB.json structure before trusting output.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse BSB.json into OCD bible_text schema (one file per book)"
    )
    parser.add_argument(
        "--book",
        metavar="OSIS",
        help="Process one book only (OSIS code, e.g. Gen, Ps, Rev)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process books but do not write output; show sample entries",
    )
    args = parser.parse_args()

    logger = setup_logging()
    logger.info("bsb_bible_text.py started -- dry_run=%s book=%s", args.dry_run, args.book)

    # Load inputs
    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return

    print(f"Source: {BSB_PATH}")
    print(f"Output: {OUTPUT_DIR}")
    print()

    try:
        bsb_books = load_bsb()
    except (FileNotFoundError, KeyError) as exc:
        print(f"ERROR loading BSB.json: {exc}")
        logger.error("Failed to load BSB.json: %s", exc)
        return

    # Compute source hash once (used in all book meta envelopes)
    source_hash = sha256_file(BSB_PATH)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Log provenance facts so log is self-contained for future debugging
    logger.info("Source: %s", BSB_PATH)
    logger.info("Source hash: %s", source_hash)
    logger.info("Output: %s", OUTPUT_DIR)
    logger.info("Input books in BSB.json: %d", len(bsb_books))

    # Filter to one book if --book specified
    if args.book:
        target_osis = args.book
        # Find the BSB book matching this OSIS code
        target_books = [
            b for b in bsb_books
            if BSB_NAME_TO_OSIS.get(b["name"]) == target_osis
        ]
        if not target_books:
            known = sorted(BSB_NAME_TO_OSIS.values())
            print(f"ERROR: OSIS code '{target_osis}' not found.")
            print(f"Known codes: {', '.join(known)}")
            return
        bsb_books = target_books
        print(f"Processing single book: {target_osis}")
    else:
        print(f"Processing all {len(bsb_books)} books...")

    print()
    start_time = time.time()
    all_stats = []
    errors = []

    # Category sampling: test one OT poetry book and one NT epistle in dry-run
    # (Rule 44: test one representative sample per category)
    # In full run, all books are processed regardless.

    for idx, book_data in enumerate(bsb_books, 1):
        bsb_name = book_data["name"]
        osis_code = BSB_NAME_TO_OSIS.get(bsb_name, "?")
        print(f"[{idx}/{len(bsb_books)}] {bsb_name} ({osis_code})")
        try:
            stats = process_book(
                book_data, config, today, source_hash,
                dry_run=args.dry_run, logger=logger,
            )
            all_stats.append(stats)
        except Exception as exc:
            msg = f"ERROR processing {bsb_name} ({type(exc).__name__}): {exc}"
            print(f"  {msg}")
            logger.error(msg)
            errors.append(bsb_name)

    elapsed = time.time() - start_time
    valid_stats = [s for s in all_stats if s]
    total_verses = sum(s.get("verse_count", 0) for s in valid_stats)
    total_source_verses = sum(s.get("source_verse_count", 0) for s in valid_stats)
    total_skipped = sum(s.get("skipped_count", 0) for s in valid_stats)
    total_books = len(valid_stats)

    print()
    print("=== SUMMARY ===")
    print(f"Books processed: {total_books}")
    print(f"Total verses written: {total_verses}")
    if total_skipped:
        skip_pct = total_skipped * 100 / total_source_verses if total_source_verses else 0
        print(
            f"Textual-critical omissions: {total_skipped} "
            f"({skip_pct:.2f}% of {total_source_verses} source verses)"
        )
    print(f"Time: {elapsed:.1f}s")
    if errors:
        print(f"Errors: {len(errors)} books failed: {errors}")
    if not args.dry_run and not args.book:
        # Spot-check source verse counts for key books
        stats_by_osis = {s["osis_code"]: s for s in valid_stats if s.get("osis_code")}
        run_spot_checks(stats_by_osis, logger=logger)

    logger.info(
        "Done -- %d books, %d verses written, %d skipped, %.1fs, %d errors",
        total_books, total_verses, total_skipped, elapsed, len(errors),
    )

    if errors:
        print()
        print(f"WARNING: {len(errors)} books had errors. Check {LOG_PATH} for details.")


if __name__ == "__main__":
    main()
