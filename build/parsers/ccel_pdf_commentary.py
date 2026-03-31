"""build/parsers/ccel_pdf_commentary.py
Parser for CCEL/archive.org PDF-extracted commentary Markdown into OCD schema.

Reads clean Markdown from raw/{source}/{id}/markdown/*.md (produced by
build/extract_pdf.py) and outputs commentary JSON matching
schemas/v1/commentary.schema.json.

Currently targets Spurgeon's Treasury of David. The psalm identification logic
handles Treasury of David vol PDFs from archive.org (OCR, GlyphLessFont).

Structure of extracted Markdown:
  - Running headers like "PSALM THE FIFTY-THIRD. [page_num]" appear on each page
  - H3 headings (### Verse N. or ### Verses N, M.) mark verse commentary entries
  - Body text between H3 headings is the commentary for that verse group

Usage:
    py -3 build/parsers/ccel_pdf_commentary.py --commentary treasury-of-david --all-books
    py -3 build/parsers/ccel_pdf_commentary.py --commentary treasury-of-david --all-books --dry-run
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root + sys.path
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT_VERSION = "v1.0.0"
SCHEMA_VERSION = "2.1.0"

# Log file (Rule 3: same folder as script)
LOG_FILE = Path(__file__).with_suffix(".log")

# Output base dir (Rule 14); full path: OUTPUT_BASE/{commentary_id}/psalms.json
OUTPUT_BASE = REPO_ROOT / "data" / "commentaries"


# ---------------------------------------------------------------------------
# Bible constants (Psalms only for this parser)
# ---------------------------------------------------------------------------

BOOK_OSIS = "Ps"
BOOK_NAME = "Psalms"
BOOK_NUMBER = 19

# Verse counts per psalm (1-150)
PSALM_VERSE_COUNTS = {
    1: 6, 2: 12, 3: 8, 4: 8, 5: 12, 6: 10, 7: 17, 8: 9, 9: 20, 10: 18,
    11: 7, 12: 8, 13: 6, 14: 7, 15: 5, 16: 11, 17: 15, 18: 50, 19: 14,
    20: 9, 21: 13, 22: 31, 23: 6, 24: 10, 25: 22, 26: 12, 27: 14, 28: 9,
    29: 11, 30: 12, 31: 24, 32: 11, 33: 22, 34: 22, 35: 28, 36: 12,
    37: 40, 38: 22, 39: 13, 40: 17, 41: 13, 42: 11, 43: 5, 44: 26,
    45: 17, 46: 11, 47: 9, 48: 14, 49: 20, 50: 23, 51: 19, 52: 9,
    53: 6, 54: 7, 55: 23, 56: 13, 57: 11, 58: 11, 59: 17, 60: 12,
    61: 8, 62: 12, 63: 11, 64: 10, 65: 13, 66: 20, 67: 7, 68: 35,
    69: 36, 70: 5, 71: 24, 72: 20, 73: 28, 74: 23, 75: 10, 76: 12,
    77: 20, 78: 72, 79: 13, 80: 19, 81: 16, 82: 8, 83: 18, 84: 12,
    85: 13, 86: 17, 87: 7, 88: 18, 89: 52, 90: 17, 91: 16, 92: 15,
    93: 5, 94: 23, 95: 11, 96: 13, 97: 12, 98: 9, 99: 9, 100: 5,
    101: 8, 102: 28, 103: 22, 104: 35, 105: 45, 106: 48, 107: 43,
    108: 13, 109: 31, 110: 7, 111: 10, 112: 10, 113: 9, 114: 8,
    115: 18, 116: 19, 117: 2, 118: 29, 119: 176, 120: 7, 121: 8,
    122: 9, 123: 4, 124: 8, 125: 5, 126: 6, 127: 5, 128: 6, 129: 8,
    130: 8, 131: 3, 132: 18, 133: 3, 134: 3, 135: 21, 136: 26,
    137: 9, 138: 8, 139: 24, 140: 13, 141: 10, 142: 7, 143: 12,
    144: 15, 145: 21, 146: 10, 147: 20, 148: 14, 149: 9, 150: 6,
}

# ---------------------------------------------------------------------------
# Psalm number lookup: ordinal name -> int
# ---------------------------------------------------------------------------

TENS = {
    "TWENT": 20, "THIRTY": 30, "THIRT": 30, "FORT": 40, "FIFTY": 50, "FIFTIETH": 50,
    "SIXT": 60, "SIXTY": 60, "SEVENTIETH": 70, "SEVENTY": 70,
    "EIGHTY": 80, "EIGHTIETH": 80, "NINETY": 90, "NINETIETH": 90,
    "HUNDREDTH": 100, "HUNDRED": 100,
}

ONES = {
    "FIRST": 1, "SECOND": 2, "THIRD": 3, "FOURTH": 4, "FIFTH": 5,
    "SIXTH": 6, "SEVENTH": 7, "EIGHTH": 8, "NINTH": 9, "TENTH": 10,
    "ELEVENTH": 11, "TWELFTH": 12, "THIRTEENTH": 13, "FOURTEENTH": 14,
    "FIFTEENTH": 15, "SIXTEENTH": 16, "SEVENTEENTH": 17, "EIGHTEENTH": 18,
    "NINETEENTH": 19, "TWENTIETH": 20, "ONE": 1, "TWO": 2, "THREE": 3,
    "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9,
}

ROMAN_NUMS = {
    "I": 1, "IV": 4, "V": 5, "IX": 9, "X": 10, "XL": 40, "L": 50,
    "XC": 90, "C": 100, "CD": 400, "D": 500, "CM": 900, "M": 1000,
}

# OCR error corrections for psalm ordinals
OCR_CORRECTIONS = {
    "TPIFTY": "FIFTY", "FIFLH": "FIFTH", "FIFTII": "FIFTH",
    "SIXIH": "SIXTH", "SIXTLI": "SIXTY", "SEVENT11": "SEVENTH",
    "EIGHTI": "EIGHTH", "EIGUTH": "EIGHTH",
    "SEVENTLI": "SEVENTY", "NIGHTIETH": "NINETIETH",
}


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to integer. Returns 0 on failure."""
    s = s.upper().strip()
    result = 0
    i = 0
    vals = [(v, k) for k, v in sorted(ROMAN_NUMS.items(), key=lambda x: -x[1])]
    while i < len(s):
        matched = False
        for value, sym in vals:
            if s[i:i + len(sym)] == sym:
                result += value
                i += len(sym)
                matched = True
                break
        if not matched:
            return 0
    return result


def ordinal_to_psalm_number(name: str) -> int:
    """
    Convert an ordinal psalm name to its number.
    Handles: FIFTY-THIRD (53), LXIV (64 Roman), etc.
    Returns 0 if not parseable.
    """
    name = name.upper().strip().rstrip(".")
    # Remove trailing page-number artifacts (digits/letters at end)
    name = re.sub(r"\s+[\d\w]{1,4}$", "", name).strip()

    # Apply OCR corrections (word-boundary match prevents "EIGHTI" corrupting "EIGHTIETH")
    for bad, good in OCR_CORRECTIONS.items():
        name = re.sub(r"\b" + re.escape(bad) + r"\b", good, name)

    # Try Roman numeral
    roman_match = re.match(r"^[IVXLCDM]+$", name.replace("-", "").replace(" ", ""))
    if roman_match:
        n = roman_to_int(name.replace("-", "").replace(" ", ""))
        if 1 <= n <= 150:
            return n

    # Try English ordinal: e.g. "FIFTY-THIRD" or "FIFTY THIRD"
    # Split on hyphen or space
    parts = re.split(r"[\s-]+", name)
    total = 0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part in ONES:
            total += ONES[part]
        else:
            # Try tens prefix match
            matched = False
            for prefix, val in TENS.items():
                if part.startswith(prefix):
                    total += val
                    matched = True
                    break
            if not matched and part.isdigit():
                total += int(part)

    if 1 <= total <= 150:
        return total
    return 0


# Regex to match running header psalm title lines
# Matches: "PSALM THE FIFTY-THIRD. 3" or "PSALM LXIV." or "PSALM THE SEVENTY-NINTH."
PSALM_TITLE_RE = re.compile(
    r"^PSALM\s+(THE\s+)?([A-Z][A-Z\s\-]+?)\.?\s*[\d\w]{0,6}$",
    re.IGNORECASE,
)

# H3 verse heading pattern: "### Verse 1." or "### Verses 1, 2."
H3_VERSE_RE = re.compile(
    r"^###\s+[Vv]erses?\s*\.?\s*([\d,\s\-]+)",
    re.IGNORECASE,
)


def parse_verse_range(verse_str: str) -> tuple:
    """
    Parse verse reference string to (start, end) integers.
    Handles: "1", "1, 2", "1-3", "2, 3, 4" (comma-list -> min-max range)
    Returns (0, 0) on failure.
    """
    # Normalise: replace commas with spaces, collapse whitespace
    nums = re.findall(r"\d+", verse_str)
    if not nums:
        return 0, 0
    ints = [int(n) for n in nums]
    return min(ints), max(ints)


def osis_range(psalm_num: int, start: int, end: int) -> str:
    if start == end:
        return f"Ps.{psalm_num}.{start}"
    return f"Ps.{psalm_num}.{start}-Ps.{psalm_num}.{end}"


def make_entry_id(resource_id: str, psalm_num: int, start: int, end: int) -> str:
    if start == end:
        return f"{resource_id}.Ps.{psalm_num}.{start}"
    return f"{resource_id}.Ps.{psalm_num}.{start}-{end}"


# ---------------------------------------------------------------------------
# Markdown parser
# ---------------------------------------------------------------------------

def parse_markdown(markdown_text: str, resource_id: str) -> list:
    """
    Parse extracted Treasury of David Markdown into commentary entry dicts.

    Strategy:
    1. Scan lines tracking current psalm number from running headers.
    2. When an H3 `### Verse N.` is found, start collecting a commentary entry.
    3. Accumulate body text until next H3 or psalm change.
    4. Emit the entry, merging into an existing entry if the same (psalm, verse)
       was already seen (multiple commentary sections per psalm share verse headings).
    """
    entries = []
    entries_by_id = {}  # entry_id -> index in entries list (for merge)
    lines = markdown_text.split("\n")

    current_psalm = None
    current_verse_start = 0
    current_verse_end = 0
    current_text_lines = []
    in_verse_block = False

    # Track psalms seen so we can deduplicate psalm transitions
    last_psalm_from_header = None

    def flush_entry():
        """Emit (or merge into) the current verse block as a commentary entry."""
        if not in_verse_block:
            return
        if not current_psalm or current_verse_start == 0:
            return
        text = "\n".join(current_text_lines).strip()
        if not text or len(text.split()) < 5:
            return

        total_verses = PSALM_VERSE_COUNTS.get(current_psalm, 0)
        end = current_verse_end if current_verse_end else current_verse_start
        # Clamp to valid verse range
        if total_verses:
            end = min(end, total_verses)
            start = min(current_verse_start, total_verses)
        else:
            start = current_verse_start

        if start == 0:
            return

        verse_range_str = str(start) if start == end else f"{start}-{end}"
        entry_id = make_entry_id(resource_id, current_psalm, start, end)

        if entry_id in entries_by_id:
            # Merge: append new section text to existing entry
            idx = entries_by_id[entry_id]
            existing = entries[idx]
            merged = existing["commentary_text"] + "\n\n---\n\n" + text
            existing["commentary_text"] = merged
            existing["word_count"] = len(merged.split())
        else:
            entry = {
                "entry_id": entry_id,
                "book": BOOK_NAME,
                "book_osis": BOOK_OSIS,
                "book_number": BOOK_NUMBER,
                "chapter": current_psalm,
                "verse_range": verse_range_str,
                "verse_range_osis": osis_range(current_psalm, start, end),
                "verse_text": None,
                "commentary_text": text,
                "summary": None,
                "summary_review_status": "withheld",
                "summary_source_span": None,
                "summary_reviewer": None,
                "key_quote": None,
                "key_quote_source_span": None,
                "key_quote_selection_criteria": None,
                "cross_references": [],
                "word_count": len(text.split()),
            }
            entries_by_id[entry_id] = len(entries)
            entries.append(entry)

    for line in lines:
        # Check for psalm running header (title on page)
        stripped = line.strip()
        m = PSALM_TITLE_RE.match(stripped)
        if m:
            ordinal_part = m.group(2).strip()
            psalm_num = ordinal_to_psalm_number(ordinal_part)
            if psalm_num and psalm_num != last_psalm_from_header:
                last_psalm_from_header = psalm_num
                if current_psalm != psalm_num:
                    flush_entry()
                    in_verse_block = False
                    current_text_lines = []
                    current_psalm = psalm_num
            continue

        # Check for H3 verse heading
        h3_m = H3_VERSE_RE.match(stripped)
        if h3_m:
            # Flush previous block
            flush_entry()
            # Start new verse block
            start, end = parse_verse_range(h3_m.group(1))
            if start > 0 and current_psalm:
                in_verse_block = True
                current_verse_start = start
                current_verse_end = end if end else start
                current_text_lines = []
            continue

        # Accumulate text for current verse block
        if in_verse_block:
            # Skip running header lines (short ALL-CAPS with digits)
            if re.match(r"^\d+\s+[A-Z\s]+\.$", stripped) or re.match(r"^[A-Z\s]+\.\s+\d+$", stripped):
                continue
            current_text_lines.append(line)

    # Flush final block
    flush_entry()

    return entries


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(commentary_id: str) -> dict:
    config_path = REPO_ROOT / "sources" / "commentaries" / commentary_id / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(config: dict, data_hash: str, processing_date: str) -> dict:
    resource_id = config["resource_id"]
    pdf_config = config.get("pdf_extraction", {})
    raw_dir = pdf_config.get("raw_dir", f"raw/ccel/{resource_id}")
    pdf_files = pdf_config.get("pdf_files", [])
    source_url = config.get("source_base_url", "")

    # Vol/edition metadata from config -- avoids hardcoding per-volume text here.
    # Add these keys to config.json for each volume:
    #   "source_edition":         "Funk & Wagnalls edition (1882), Vol. III, Psalms 53-78"
    #   "archive_org_identifier": "treasuryofdavidc0000spur"
    #   "psalm_range_note":       "Psalms 53-78"
    source_edition = config.get("source_edition", "")
    archive_org_id = config.get("archive_org_identifier", "")
    psalm_range_note = config.get("psalm_range_note", "")

    archive_note = f" (archive.org identifier: {archive_org_id})" if archive_org_id else ""
    coverage_note = f"Vol covers {psalm_range_note}{archive_note}. " if psalm_range_note else ""
    notes = (
        f"Sourced from archive.org OCR PDF via build/extract_pdf.py PDF pipeline. "
        f"PDF: {', '.join(pdf_files) if pdf_files else 'auto-discovered'}. "
        f"{coverage_note}"
        f"verse_text is null; BSB enrichment is a separate step."
    )

    return {
        "id": resource_id,
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config.get("author_birth_year"),
        "author_death_year": config.get("author_death_year"),
        "contributors": config.get("contributors", []),
        "original_publication_year": config["original_publication_year"],
        "language": config["language"],
        "tradition": config["tradition"],
        "tradition_notes": config.get("tradition_notes"),
        "license": config["license"],
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "verse_text_source": "none",
        "verse_reference_standard": "OSIS",
        "completeness": "partial",
        "provenance": {
            "source_url": source_url,
            "source_format": "PDF (archive.org OCR scanned text)",
            "source_edition": source_edition,
            "download_date": processing_date,
            "source_hash": f"sha256:{data_hash}",
            "processing_method": "ocr",
            "processing_script_version": (
                f"build/parsers/ccel_pdf_commentary.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": notes,
        },
        "summary_metadata": None,
    }


# ---------------------------------------------------------------------------
# Log tee (writes every print() to stdout + LOG_FILE simultaneously)
# ---------------------------------------------------------------------------

class _TeeWriter:
    """Duplicate stdout writes to an open log file."""
    def __init__(self, stdout, log_file):
        self._stdout = stdout
        self._log = log_file

    def write(self, data: str) -> None:
        self._stdout.write(data)
        self._log.write(data)

    def flush(self) -> None:
        self._stdout.flush()
        self._log.flush()

    def fileno(self) -> int:
        return self._stdout.fileno()

    def isatty(self) -> bool:
        return self._stdout.isatty()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point: sets up log tee then delegates to _main()."""
    with open(LOG_FILE, "a", encoding="utf-8") as _lf:
        _lf.write(
            f"\n=== {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')} ===\n"
        )
        _orig = sys.stdout
        sys.stdout = _TeeWriter(_orig, _lf)
        try:
            _main()
        finally:
            sys.stdout = _orig


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Treasury of David PDF Markdown into OCD commentary schema"
    )
    parser.add_argument(
        "--commentary",
        required=True,
        metavar="ID",
        help="Commentary ID (e.g. treasury-of-david)",
    )
    parser.add_argument(
        "--all-books",
        action="store_true",
        help="Process all available Markdown files (use this for Psalms commentary)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report stats; do not write output files",
    )
    args = parser.parse_args()

    commentary_id = args.commentary.lower()
    start_time = time.time()

    # Load config
    try:
        config = load_config(commentary_id)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    resource_id = config["resource_id"]
    pdf_config = config.get("pdf_extraction", {})
    raw_dir_str = pdf_config.get("raw_dir", f"raw/ccel/{commentary_id}")
    md_dir = REPO_ROOT / raw_dir_str / "markdown"

    print(f"Commentary: {config['title']}")
    print(f"Author:     {config['author']}")
    print(f"Markdown:   {md_dir}")
    if args.dry_run:
        print("Mode:       dry-run (no write)")
    print()

    # Find markdown files
    md_files = sorted(md_dir.glob("*.md"))
    md_files = [f for f in md_files if not f.name.startswith("_")]
    if not md_files:
        print(f"ERROR: No .md files found in {md_dir}")
        sys.exit(1)
    print(f"Markdown files: {[f.name for f in md_files]}")
    print()

    all_entries = []
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for md_file in md_files:
        print(f"Parsing {md_file.name}...")
        with open(md_file, encoding="utf-8") as f:
            text = f.read()

        entries = parse_markdown(text, resource_id)
        all_entries.extend(entries)

        # Per-file stats
        psalms_found = sorted(set(e["chapter"] for e in entries))
        print(f"  Entries parsed: {len(entries)}")
        print(f"  Psalms: {psalms_found}")
        if entries:
            words = [e["word_count"] for e in entries]
            print(
                f"  Words: min={min(words)} median={sorted(words)[len(words)//2]} "
                f"max={max(words)}"
            )
        print()

    print(f"Total entries: {len(all_entries)}")

    if not all_entries:
        print("WARNING: No entries produced. Check psalm title patterns and heading config.")
        return

    # Sort by (chapter, verse_start) so downstream consumers see verses in sequence
    all_entries.sort(key=lambda e: (e["chapter"], int(e["verse_range"].split("-")[0])))

    # Quality stats
    null_ct = sum(1 for e in all_entries if not (e.get("commentary_text") or "").strip())
    short = sum(1 for e in all_entries if e.get("word_count", 0) < 20)
    if null_ct:
        print(f"WARNING: {null_ct}/{len(all_entries)} entries missing commentary_text")
    if short:
        print(f"WARNING: {short}/{len(all_entries)} entries under 20 words")

    # Coverage assertion: if config declares expected_chapters [start, end], verify all present
    coverage_ok = True
    expected_range = pdf_config.get("expected_chapters")
    if expected_range and len(expected_range) == 2:
        start_ch, end_ch = expected_range
        expected_set = set(range(start_ch, end_ch + 1))
        found_set = set(e["chapter"] for e in all_entries)
        missing = sorted(expected_set - found_set)
        unexpected = sorted(found_set - expected_set)
        if missing:
            print(f"COVERAGE ERROR: Missing chapters {missing} (expected {start_ch}-{end_ch})")
            coverage_ok = False
        if unexpected:
            print(f"COVERAGE WARNING: Unexpected chapters {unexpected} (outside {start_ch}-{end_ch})")
        if not missing and not unexpected:
            print(f"Coverage: all {len(expected_set)} expected chapters present ({start_ch}-{end_ch})")

    if args.dry_run:
        elapsed = time.time() - start_time
        print()
        print("--- Sample entries (first 3) ---")
        for entry in all_entries[:3]:
            print(
                f"  entry_id: {entry['entry_id']}"
                f"  verse_range: {entry['verse_range']}"
                f"  words: {entry['word_count']}"
            )
            print(f"  text: {entry['commentary_text'][:100]!r}")
            print()
        print(f"Dry-run complete ({elapsed:.1f}s) -- no files written.")
        if not coverage_ok:
            sys.exit(1)
        return

    # Build and write output
    data_bytes = json.dumps(all_entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    data_hash = hashlib.sha256(data_bytes).hexdigest()
    meta = build_meta(config, data_hash, processing_date)
    output = {"meta": meta, "data": all_entries}

    out_dir = OUTPUT_BASE / commentary_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "psalms.json"

    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = out_file.stat().st_size / 1024
    elapsed = time.time() - start_time
    print(f"Wrote {len(all_entries)} entries -> {out_file}")
    print(f"File size: {size_kb:.0f} KB")

    # Update manifest
    manifest_path = out_dir / "_manifest.json"
    manifest = {
        "resource_id": resource_id,
        "title": config["title"],
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "books": [
            {
                "usfm_code": "PSA",
                "osis_code": BOOK_OSIS,
                "name": BOOK_NAME,
                "file": "psalms.json",
                "entry_count": len(all_entries),
                "status": "partial",
                "summary_status": "withheld",
            }
        ],
        "stats": {
            "total_books": 1,
            "total_entries": len(all_entries),
            "books_with_summaries": 0,
        },
        "last_updated": processing_date,
    }
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Manifest: {manifest_path.name}")
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
