"""church_fathers.py
Parse HistoricalChristianFaith/Commentaries-Database TOML files into OCD church_fathers schema.

Source: raw/Commentaries-Database/
  - One directory per author (338 total)
  - Each directory contains TOML files named {Book} {Chapter}_{Verse(s)}.toml
  - Each TOML file has one or more [[commentary]] blocks with quote, source_url, source_title
  - Some blocks also have append_to_author_name (-> attribution_note) and context

Output: data/church-fathers/{author-slug}.json (one file per author)

Usage:
    py -3 build/parsers/church_fathers.py --all-authors
    py -3 build/parsers/church_fathers.py --author "John Chrysostom"
    py -3 build/parsers/church_fathers.py --author "Ambrose of Milan" --dry-run
    py -3 build/parsers/church_fathers.py --all-authors --dry-run
"""

import argparse
import hashlib
import json
import re
import time
import tomllib
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "Commentaries-Database"
OUTPUT_DIR = REPO_ROOT / "data" / "church-fathers"
BOOK_CODES_PATH = REPO_ROOT / "build" / "bible_data" / "osis_book_codes.json"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
SOURCE_REPO = "https://github.com/HistoricalChristianFaith/Commentaries-Database"
PROCESS_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Max character length for slug segments in entry_ids.
SOURCE_SLUG_MAX_LEN = 50   # source title slug
RAW_REF_SLUG_MAX_LEN = 40  # raw ref slug (non-canonical books only)

# ---------------------------------------------------------------------------
# Book name -> OSIS code mapping (loaded from osis_book_codes.json)
# ---------------------------------------------------------------------------

if not BOOK_CODES_PATH.exists():
    raise FileNotFoundError(
        f"OSIS book codes file not found: {BOOK_CODES_PATH}\n"
        f"Expected at build/bible_data/osis_book_codes.json in the repo root. "
        f"Run: py -3 build/parsers/church_fathers.py after verifying the file exists."
    )

with open(BOOK_CODES_PATH, encoding="utf-8") as _f:
    _raw_map = json.load(_f)

# Strip the comment key from the JSON
BOOK_NAME_TO_OSIS = {k: v for k, v in _raw_map.items() if not k.startswith("_")}

OSIS_BOOK_NUMBER = {
    "Gen": 1, "Exod": 2, "Lev": 3, "Num": 4, "Deut": 5, "Josh": 6,
    "Judg": 7, "Ruth": 8, "1Sam": 9, "2Sam": 10, "1Kgs": 11, "2Kgs": 12,
    "1Chr": 13, "2Chr": 14, "Ezra": 15, "Neh": 16, "Esth": 17, "Job": 18,
    "Ps": 19, "Prov": 20, "Eccl": 21, "Song": 22, "Isa": 23, "Jer": 24,
    "Lam": 25, "Ezek": 26, "Dan": 27, "Hos": 28, "Joel": 29, "Amos": 30,
    "Obad": 31, "Jonah": 32, "Mic": 33, "Nah": 34, "Hab": 35, "Zeph": 36,
    "Hag": 37, "Zech": 38, "Mal": 39, "Matt": 40, "Mark": 41, "Luke": 42,
    "John": 43, "Acts": 44, "Rom": 45, "1Cor": 46, "2Cor": 47, "Gal": 48,
    "Eph": 49, "Phil": 50, "Col": 51, "1Thess": 52, "2Thess": 53, "1Tim": 54,
    "2Tim": 55, "Titus": 56, "Phlm": 57, "Heb": 58, "Jas": 59, "1Pet": 60,
    "2Pet": 61, "1John": 62, "2John": 63, "3John": 64, "Jude": 65, "Rev": 66,
}

# Regex to extract book name + chapter from filename stem.
# Handles: "Genesis 1", "1 Corinthians 10", "Song of Solomon 3"
# Greedy (.+) backtracks to the last space-before-digits sequence before the underscore.
_FILENAME_RE = re.compile(r"^(.+)\s+(\d+)_(.+)$")

# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

_SLUG_STRIP_RE = re.compile(r"[^\w\s-]")
_SLUG_SPACE_RE = re.compile(r"[\s]+")
_SLUG_HYPHEN_RE = re.compile(r"-+")


def _ascii_safe(s: str) -> str:
    """Return an ASCII-safe version of s for print() output.

    Normalizes Unicode (e.g. e-acute -> e) to avoid UnicodeEncodeError
    on Windows cp1252 consoles when unusual characters are present.
    """
    normalized = unicodedata.normalize("NFKD", s)
    return normalized.encode("ascii", "ignore").decode("ascii")


def slugify(s: str, max_len: int = 60) -> str:
    """Convert a string to a URL-safe ASCII kebab-case slug.

    Normalizes accented characters (e.g. e-acute -> e) so slugs stay
    ASCII-only and safe for filenames and IDs across all platforms.
    """
    # Normalize accented characters: e-acute -> e, etc.
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = _SLUG_STRIP_RE.sub("", s)
    s = _SLUG_SPACE_RE.sub("-", s)
    s = _SLUG_HYPHEN_RE.sub("-", s)
    s = s.strip("-")
    return s[:max_len].rstrip("-")


def author_to_slug(name: str) -> str:
    return slugify(name)


# ---------------------------------------------------------------------------
# Filename parsing
# ---------------------------------------------------------------------------


def parse_filename(stem: str):
    """Parse a TOML filename stem into (book_name, ch1, v1, ch2, v2) or None.

    Handles:
      - "Genesis 1_1"             -> (Genesis, 1, 1, 1, 1)     single verse
      - "1 Corinthians 10_17"     -> (1 Corinthians, 10, 17, 10, 17)
      - "1 Corinthians 10_1-5"    -> (1 Corinthians, 10, 1, 10, 5)   same-chapter range
      - "Matthew 15_39-16_4"      -> (Matthew, 15, 39, 16, 4)   cross-chapter range

    Returns None if the stem does not match the expected pattern.
    """
    m = _FILENAME_RE.match(stem)
    if not m:
        return None
    book_name = m.group(1).strip()
    ch1 = int(m.group(2))
    verse_str = m.group(3)

    if "_" in verse_str:
        # Cross-chapter range: "39-16_4" -> ch1:39 to ch2:4
        pre, v2_str = verse_str.split("_", 1)
        v1_str, ch2_str = pre.split("-", 1)
        try:
            v1 = int(v1_str)
            ch2 = int(ch2_str)
            v2 = int(v2_str)
        except ValueError:
            return None
        return book_name, ch1, v1, ch2, v2
    elif "-" in verse_str:
        # Same-chapter range: "1-5"
        parts = verse_str.split("-", 1)
        try:
            v1 = int(parts[0])
            v2 = int(parts[1])
        except ValueError:
            return None
        return book_name, ch1, v1, ch1, v2
    else:
        # Single verse
        try:
            v = int(verse_str)
        except ValueError:
            return None
        return book_name, ch1, v, ch1, v


# ---------------------------------------------------------------------------
# Reference builders
# ---------------------------------------------------------------------------


def build_raw_ref(book_name: str, ch1: int, v1: int, ch2: int, v2: int) -> str:
    """Build a human-readable reference string from parsed filename parts."""
    if ch1 == ch2:
        if v1 == v2:
            return f"{book_name} {ch1}:{v1}"
        return f"{book_name} {ch1}:{v1}-{v2}"
    return f"{book_name} {ch1}:{v1}-{ch2}:{v2}"


def build_osis_ref(book_osis: str, ch1: int, v1: int, ch2: int, v2: int) -> str:
    """Build an abbreviated OSIS reference for entry_id use.

    Single: Gen.1.1
    Same-chapter range: 1Cor.10.1-5
    Cross-chapter range: Matt.15.39-16.4
    """
    if ch1 == ch2:
        if v1 == v2:
            return f"{book_osis}.{ch1}.{v1}"
        return f"{book_osis}.{ch1}.{v1}-{v2}"
    return f"{book_osis}.{ch1}.{v1}-{ch2}.{v2}"


def build_osis_full(book_osis: str, ch1: int, v1: int, ch2: int, v2: int) -> str:
    """Build a fully-qualified OSIS ref for the anchor_ref.osis array.

    Single: Gen.1.1
    Range: Gen.1.1-Gen.2.3
    """
    if ch1 == ch2 and v1 == v2:
        return f"{book_osis}.{ch1}.{v1}"
    return f"{book_osis}.{ch1}.{v1}-{book_osis}.{ch2}.{v2}"


# ---------------------------------------------------------------------------
# TOML parsing
# ---------------------------------------------------------------------------


def load_toml_file(path: Path) -> list:
    """Load a TOML file and return the list of commentary blocks.

    Returns empty list on parse error (logged by caller).
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data.get("commentary", [])


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------


def build_entry(
    author_slug: str,
    author_name: str,
    book_name: str,
    ch1: int,
    v1: int,
    ch2: int,
    v2: int,
    book_osis: str,
    block: dict,
    entry_id: str,
) -> dict:
    """Build one church_fathers data entry from a [[commentary]] block."""
    quote = (block.get("quote") or "").strip()
    source_title = (block.get("source_title") or "").strip()
    source_url = (block.get("source_url") or "").strip()
    attribution_note = (block.get("append_to_author_name") or "").strip() or None
    context = (block.get("context") or "").strip() or None

    raw_ref = build_raw_ref(book_name, ch1, v1, ch2, v2)
    if book_osis:
        osis_full = build_osis_full(book_osis, ch1, v1, ch2, v2)
        osis_list = [osis_full]
    else:
        osis_list = []

    return {
        "entry_id": entry_id,
        "author": author_name,
        "anchor_ref": {
            "raw": raw_ref,
            "osis": osis_list,
        },
        "quote": quote,
        "source_title": source_title,
        "source_url": source_url,
        "attribution_note": attribution_note,
        "context": context,
        "word_count": len(quote.split()) if quote else 0,
    }


# ---------------------------------------------------------------------------
# Author processor
# ---------------------------------------------------------------------------


def process_author(author_dir: Path, dry_run: bool = False) -> dict:
    """Process all TOML files for one author. Returns a stats dict.

    In dry-run mode, processes only the first TOML file and does not write output.
    """
    author_name = author_dir.name
    author_slug = author_to_slug(author_name)

    toml_files = sorted(f for f in author_dir.iterdir() if f.suffix == ".toml")
    if not toml_files:
        return {
            "author": author_name,
            "slug": author_slug,
            "files": 0,
            "entries": 0,
            "skipped_files": 0,
            "unknown_books": set(),
            "status": "empty",
        }

    total_toml_count = len(toml_files)
    if dry_run:
        toml_files = toml_files[:1]
        print(f"  [dry-run] Sampling 1 of {total_toml_count} files for {_ascii_safe(author_name)}")

    entries = []
    skipped_files = 0
    unknown_books: set = set()
    # Track ALL used entry_ids to guarantee uniqueness.
    # A naive per-base counter can collide when a generated suffix (e.g. "against-praxeas-5")
    # matches a naturally-occurring slug (e.g. from "AGAINST PRAXEAS 5").
    seen_entry_ids: set = set()    # every entry_id committed so far
    id_counters: dict = {}         # base_id -> last counter tried (for O(n) amortized lookup)

    for tf in toml_files:
        stem = tf.stem
        parsed = parse_filename(stem)
        if parsed is None:
            print(f"    WARNING: Cannot parse filename '{stem}' -- skipping")
            skipped_files += 1
            continue

        book_name, ch1, v1, ch2, v2 = parsed
        book_osis = BOOK_NAME_TO_OSIS.get(book_name, "")
        if not book_osis:
            unknown_books.add(book_name)

        try:
            blocks = load_toml_file(tf)
        except Exception as exc:
            print(f"    WARNING: TOML parse error in '{tf.name}': {exc} -- skipping")
            skipped_files += 1
            continue

        if not blocks:
            skipped_files += 1
            continue

        for block in blocks:
            quote = (block.get("quote") or "").strip()
            if not quote:
                skipped_files += 1
                continue

            source_title = (block.get("source_title") or "").strip()
            source_slug = slugify(source_title, max_len=SOURCE_SLUG_MAX_LEN) if source_title else "unknown"

            if book_osis:
                osis_abbrev = build_osis_ref(book_osis, ch1, v1, ch2, v2)
            else:
                # Non-canonical book -- use raw ref slug for entry_id
                raw_slug = slugify(build_raw_ref(book_name, ch1, v1, ch2, v2), max_len=RAW_REF_SLUG_MAX_LEN)
                osis_abbrev = raw_slug

            base_id = f"{author_slug}.{osis_abbrev}.{source_slug}"

            # Disambiguate: try base_id first, then increment a counter until unique.
            # Using a set of all seen IDs (not just per-base counts) prevents collisions
            # when a generated suffix like "against-praxeas-5" matches a natural slug.
            if base_id not in seen_entry_ids:
                entry_id = base_id
            else:
                counter = id_counters.get(base_id, 1)
                while True:
                    counter += 1
                    candidate = f"{base_id}-{counter}"
                    if candidate not in seen_entry_ids:
                        entry_id = candidate
                        break
                id_counters[base_id] = counter
            seen_entry_ids.add(entry_id)

            entry = build_entry(
                author_slug, author_name,
                book_name, ch1, v1, ch2, v2,
                book_osis, block, entry_id,
            )
            entries.append(entry)

    if not entries:
        return {
            "author": author_name,
            "slug": author_slug,
            "files": len(toml_files),
            "entries": 0,
            "skipped_files": skipped_files,
            "unknown_books": unknown_books,
            "status": "no-entries",
        }

    if dry_run:
        print(f"  [dry-run] {_ascii_safe(author_name)}: {len(entries)} entries from {len(toml_files)} file(s)")
        if entries:
            e = entries[0]
            print(f"    entry_id:     {e['entry_id']}")
            print(f"    anchor_ref:   {_ascii_safe(e['anchor_ref']['raw'])} -> {e['anchor_ref']['osis']}")
            print(f"    source_title: {_ascii_safe(e['source_title'])}")
            print(f"    word_count:   {e['word_count']}")
        return {
            "author": author_name,
            "slug": author_slug,
            "files": len(toml_files),
            "entries": len(entries),
            "skipped_files": skipped_files,
            "unknown_books": unknown_books,
            "status": "dry-run",
        }

    # Build output file
    process_date = PROCESS_DATE
    data_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    data_hash = hashlib.sha256(data_bytes).hexdigest()

    output = {
        "meta": {
            "id": author_slug,
            "author": author_name,
            "tradition": [],
            "tradition_notes": None,
            "license": "public-domain",
            "schema_type": "church_fathers",
            "schema_version": SCHEMA_VERSION,
            "provenance": {
                "source_url": SOURCE_REPO,
                "source_format": "TOML",
                "source_edition": "HistoricalChristianFaith/Commentaries-Database (public domain)",
                "download_date": process_date,
                "source_hash": f"sha256:{data_hash}",
                "processing_method": "automated",
                "processing_script_version": (
                    f"build/parsers/church_fathers.py@{SCRIPT_VERSION}"
                ),
                "processing_date": process_date,
                "notes": (
                    f"Processed {len(entries)} quotes from {len(toml_files)} verse files. "
                    f"Source: HistoricalChristianFaith/Commentaries-Database. "
                    f"License: PUBLIC DOMAIN."
                ),
            },
        },
        "data": entries,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / f"{author_slug}.json"
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = out_file.stat().st_size / 1024

    # Quality stats
    word_counts = [e["word_count"] for e in entries]
    null_osis = sum(1 for e in entries if not e["anchor_ref"]["osis"])
    empty_source_title = sum(1 for e in entries if not e["source_title"])
    total = len(entries)
    sorted_wc = sorted(word_counts)
    median_wc = sorted_wc[total // 2]

    print(
        f"  {_ascii_safe(author_name)} ({author_slug}): "
        f"{total} entries, {size_kb:.0f} KB"
    )
    if null_osis:
        pct = null_osis * 100 / total
        print(
            f"    INFO: {null_osis}/{total} entries ({pct:.1f}%) have no OSIS ref "
            f"(unrecognized book names)"
        )
    if empty_source_title:
        print(f"    WARNING: {empty_source_title}/{total} entries missing source_title")
    print(
        f"    Quality: word_count min={min(word_counts)} "
        f"med={median_wc} max={max(word_counts)}"
    )
    if unknown_books:
        print(f"    Unknown books: {sorted(unknown_books)}")

    return {
        "author": author_name,
        "slug": author_slug,
        "files": len(toml_files),
        "entries": total,
        "skipped_files": skipped_files,
        "null_osis": null_osis,
        "empty_source_title": empty_source_title,
        "unknown_books": unknown_books,
        "status": "ok",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Parse HistoricalChristianFaith/Commentaries-Database TOML files "
            "into OCD church_fathers schema JSON."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all-authors",
        action="store_true",
        help="Process all author directories",
    )
    group.add_argument(
        "--author",
        metavar="NAME",
        help='Process one author by directory name, e.g. "John Chrysostom"',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process the first file only per author; do not write output",
    )
    args = parser.parse_args()

    if not RAW_DIR.exists():
        print(f"ERROR: Raw data directory not found: {RAW_DIR}")
        return

    print(f"Source:  {RAW_DIR}")
    print(f"Output:  {OUTPUT_DIR}")
    print(f"Dry-run: {args.dry_run}")
    print()

    if args.all_authors:
        author_dirs = sorted(
            d for d in RAW_DIR.iterdir()
            if d.is_dir()
        )
        print(f"Found {len(author_dirs)} author directories")
        print()
    else:
        target = RAW_DIR / args.author
        if not target.exists() or not target.is_dir():
            print(f"ERROR: Author directory not found: {target}")
            available = sorted(d.name for d in RAW_DIR.iterdir() if d.is_dir())
            matches = [n for n in available if args.author.lower() in n.lower()]
            if matches:
                print(f"  Possible matches: {matches[:5]}")
            return
        author_dirs = [target]

    start_time = time.time()
    all_stats = []
    total_files_processed = 0
    total_entries = 0
    total_skipped = 0
    total_null_osis = 0
    total_empty_source_title = 0
    all_unknown_books: set = set()
    author_exceptions = []

    for idx, adir in enumerate(author_dirs, 1):
        if args.all_authors:
            print(f"[{idx}/{len(author_dirs)}] Processing: {_ascii_safe(adir.name)}")
        try:
            stats = process_author(adir, dry_run=args.dry_run)
        except Exception as exc:
            # Log and continue -- one broken directory must not stop the rest
            print(f"  ERROR: Unexpected exception for {_ascii_safe(adir.name)}: {exc}")
            author_exceptions.append(adir.name)
            continue
        all_stats.append(stats)
        total_files_processed += stats.get("files", 0)
        total_entries += stats.get("entries", 0)
        total_skipped += stats.get("skipped_files", 0)
        total_null_osis += stats.get("null_osis", 0)
        total_empty_source_title += stats.get("empty_source_title", 0)
        all_unknown_books |= stats.get("unknown_books", set())

    elapsed = time.time() - start_time

    # Summary
    print()
    print("=" * 60)
    print(f"=== DONE: {len(all_stats)} authors, {total_entries} entries, {elapsed:.1f}s ===")
    print(f"=== TOML files processed: {total_files_processed} ===")
    if total_skipped:
        pct = total_skipped * 100 / max(total_files_processed, 1)
        print(f"=== Skipped (parse errors / empty quotes): {total_skipped} ({pct:.1f}%) ===")

    if total_null_osis:
        pct = total_null_osis * 100 / max(total_entries, 1)
        print(f"=== Entries with no OSIS ref (unrecognized books): {total_null_osis} ({pct:.1f}%) ===")
    if total_empty_source_title:
        pct = total_empty_source_title * 100 / max(total_entries, 1)
        print(f"=== Entries missing source_title: {total_empty_source_title} ({pct:.1f}%) ===")

    if all_unknown_books:
        # Book names are ASCII in this dataset; if not, make them safe
        safe_books = [_ascii_safe(b) for b in sorted(all_unknown_books)]
        print(f"=== Unknown book names (no OSIS mapping): {safe_books} ===")

    failed = [s["author"] for s in all_stats if s.get("status") not in ("ok", "dry-run", "empty")]
    if failed:
        failed_safe = [_ascii_safe(n) for n in failed]
        print(f"=== No-entries authors: {failed_safe} ===")
    if author_exceptions:
        exc_safe = [_ascii_safe(n) for n in author_exceptions]
        print(f"=== AUTHORS WITH EXCEPTIONS (not processed): {exc_safe} ===")

    # Top 20 authors by quote count (only meaningful for --all-authors)
    if args.all_authors and not args.dry_run:
        top20 = sorted(all_stats, key=lambda s: s.get("entries", 0), reverse=True)[:20]
        print()
        print("Top 20 authors by quote count:")
        for rank, s in enumerate(top20, 1):
            print(f"  {rank:2d}. {_ascii_safe(s['author'])}: {s['entries']} quotes")


if __name__ == "__main__":
    main()
