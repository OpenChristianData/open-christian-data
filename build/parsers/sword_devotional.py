"""sword_devotional.py
Parser for the SWORD rawLD devotional module: Daily Light on the Daily Path.

Reads extracted SWORD module files from raw/sword_modules/Daily/
and outputs data/devotionals/daily-light/daily-light.json
following the OCD devotional schema v2.1.0.

rawLD format (from binary inspection 2026-03-28):
  IDX: 6-byte entries per day: struct.unpack('<IH') = (offset_in_dat:4, size:2)
  DAT: entries of the form: "MM.DD\\r\\n<ThML HTML content>"
       Each entry has both <i>Morning</i>: and <i>Evening</i>: sections
       Scripture refs: <scripRef passage="...">...</scripRef>
  Index [0] = header entry (offset=0, size=0) -- skip
  Index [1..366] = one entry per day (Jan 1 through Dec 31 + Feb 29)

Usage:
    py -3 build/parsers/sword_devotional.py --dry-run
    py -3 build/parsers/sword_devotional.py
"""

import argparse
import hashlib
import json
import logging
import re
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SWORD_RAW_DIR = REPO_ROOT / "raw" / "sword_modules"
OUTPUT_DIR = REPO_ROOT / "data" / "devotionals" / "daily-light"
CONFIG_PATH = REPO_ROOT / "sources" / "devotionals" / "daily-light" / "config.json"
LOG_FILE = Path(__file__).parent / "sword_devotional.log"

MODULE_NAME = "Daily"
COLLECTION_ID = "daily-light"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Days per month (non-leap year); Feb has 28 + 1 extra entry for Feb 29
DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

# Strip all HTML/XML tags
_TAG_PATTERN = re.compile(r"<[^>]+>")

# Collapse runs of whitespace
_WS_PATTERN = re.compile(r"\s+")

# Detect morning/evening section boundary:
# <i>Evening</i>: or <i>EVENING</i>: etc.
_EVENING_PATTERN = re.compile(r"<i>\s*Evening\s*</i>\s*:", re.IGNORECASE)
# Detect morning section start
_MORNING_PATTERN = re.compile(r"<i>\s*Morning\s*</i>\s*:", re.IGNORECASE)


def _clean_block(text: str) -> str:
    """Strip HTML tags from a text block and normalize whitespace."""
    plain = _TAG_PATTERN.sub(" ", text)
    plain = _WS_PATTERN.sub(" ", plain).strip()
    return plain


def split_morning_evening(raw_content: str) -> tuple:
    """
    Split a day's rawLD content string into morning and evening sections.
    The key (e.g. '01.01') and CRLF appear at the start.
    Structure: key + CRLF + <i>Morning</i>: content + <i>Evening</i>: content

    Returns (morning_html, evening_html) or ('', '') if split fails.
    """
    # Find evening boundary
    eve_match = _EVENING_PATTERN.search(raw_content)
    if not eve_match:
        # No evening section found -- treat entire content as morning
        return raw_content, ""

    # Split at the <i>Evening</i>: marker
    morning_html = raw_content[: eve_match.start()]
    evening_html = raw_content[eve_match.start() :]

    # Strip the <i>Morning</i>: leader from morning section
    morn_match = _MORNING_PATTERN.search(morning_html)
    if morn_match:
        morning_html = morning_html[morn_match.end() :]

    # Strip the <i>Evening</i>: leader from evening section
    morning_html = morning_html.strip()
    evening_html = _EVENING_PATTERN.sub("", evening_html, count=1).strip()

    return morning_html, evening_html


# ---------------------------------------------------------------------------
# Entry parser
# ---------------------------------------------------------------------------

def parse_dat_entry(raw_bytes: bytes, expected_month: int, expected_day: int) -> tuple:
    """
    Parse one rawLD DAT entry (starting with 'MM.DD\r\n...').
    Returns (month, day, morning_html, evening_html) or None if malformed.
    """
    try:
        raw_str = raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None

    # First line is the key: MM.DD
    # Strip it before processing content
    if "\r\n" in raw_str:
        first_line, rest = raw_str.split("\r\n", 1)
    elif "\n" in raw_str:
        first_line, rest = raw_str.split("\n", 1)
    else:
        return None

    key = first_line.strip()
    # Validate key format MM.DD
    if not re.match(r"^\d{2}\.\d{2}$", key):
        logging.warning("  Unexpected key format: %r", key)
        return None

    month = int(key[:2])
    day = int(key[3:])

    if month != expected_month or day != expected_day:
        logging.warning(
            "  Key mismatch: expected %02d.%02d, got %s", expected_month, expected_day, key
        )

    morning_html, evening_html = split_morning_evening(rest)
    return month, day, morning_html, evening_html


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------

def make_entry(
    month: int,
    day: int,
    period: str,
    html_content: str,
    config: dict,
) -> dict:
    """Build one OCD devotional entry from a morning or evening HTML block."""
    plain = _clean_block(html_content)
    word_count = len(plain.split()) if plain else 0

    entry_id = f"{month:02d}-{day:02d}-{period}"
    title = f"{MONTH_NAMES[month - 1]} {day} -- {period.capitalize()}"

    return {
        "collection_id": COLLECTION_ID,
        "entry_id": entry_id,
        "month": month,
        "day": day,
        "period": period,
        "title": title,
        "primary_reference": None,   # Daily Light has no single primary ref per entry
        "primary_reference_text": None,
        "content_blocks": [plain] if plain else [],
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Meta envelope builder
# ---------------------------------------------------------------------------

def build_meta(config: dict, source_hash: str, processing_date: str) -> dict:
    return {
        "id": config["resource_id"],
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config.get("author_birth_year"),
        "author_death_year": config.get("author_death_year"),
        "contributors": config.get("contributors", []),
        "original_publication_year": config.get("original_publication_year"),
        "language": config["language"],
        "original_language": config.get("original_language"),
        "tradition": config["tradition"],
        "tradition_notes": config.get("tradition_notes"),
        "era": config.get("era"),
        "audience": config.get("audience"),
        "license": config["license"],
        "schema_type": "devotional",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": processing_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/sword_devotional.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# Schema validation gate
# ---------------------------------------------------------------------------

class SchemaValidationError(Exception):
    """Output failed in-memory schema validation. Stops the run before writing any files."""


def _check_output_schema(output: dict) -> None:
    """
    Validate the complete output dict against the devotional schema in-memory.
    Raises SchemaValidationError if any errors found — prevents writing a bad file.
    Runs in both dry-run and production mode.
    """
    repo_str = str(REPO_ROOT)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
    try:
        from build.validate import validate_devotional_file  # noqa: PLC0415
    except ImportError as exc:
        logging.warning("Schema check skipped (could not import validate): %s", exc)
        return

    fake_path = OUTPUT_DIR / "daily-light.json"
    errors, _warnings = validate_devotional_file(fake_path, output)
    if errors:
        logging.error("SCHEMA CHECK FAILED -- %d error(s):", len(errors))
        for e in errors[:10]:
            logging.error("  %s", e)
        if len(errors) > 10:
            logging.error("  ... and %d more -- run validate.py for full list", len(errors) - 10)
        raise SchemaValidationError(
            f"daily-light: {len(errors)} schema errors -- see log for details"
        )
    logging.info(
        "Schema check OK (%d entries validated)", len(output.get("data", []))
    )


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def report_quality(entries: list, expected: int) -> None:
    """Print quality statistics."""
    total = len(entries)
    words = [e["word_count"] for e in entries]
    no_content = sum(1 for e in entries if not e["content_blocks"])
    short = sum(1 for e in entries if e["word_count"] < 20)

    sorted_words = sorted(words)
    print(f"  Entry count: {total} (expected {expected})")
    if total > 0:
        print(
            f"  Word count: min={min(words)} median={sorted_words[total // 2]} max={max(words)}"
        )
    if total != expected:
        logging.warning("  WARNING: Expected %d entries, got %d", expected, total)
    if no_content:
        logging.warning("  WARNING: %d/%d entries have no content", no_content, total)
    if short:
        logging.warning("  WARNING: %d/%d entries under 20 words", short, total)
    print(
        f"  NOTE: primary_reference is null for all entries (Daily Light = pure KJV scripture, "
        f"no single anchor verse per entry)"
    )


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
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
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Parse SWORD rawLD Daily Light devotional into OCD devotional schema"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report stats without writing output files",
    )
    args = parser.parse_args()

    start_time = time.time()

    # Load source config
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)

    print(f"Source:  {config['title']}")
    print(f"Author:  {config['author']}")
    print(f"Output:  {OUTPUT_DIR / 'daily-light.json'}")
    if args.dry_run:
        print("Mode:    dry-run (no files written)")
    print()

    # Module data files
    dat_path = SWORD_RAW_DIR / MODULE_NAME / "modules" / "lexdict" / "rawld" / "devotionals" / "daily" / "daily.dat"
    idx_path = SWORD_RAW_DIR / MODULE_NAME / "modules" / "lexdict" / "rawld" / "devotionals" / "daily" / "daily.idx"

    if not dat_path.exists():
        print(f"ERROR: DAT file not found: {dat_path}")
        sys.exit(1)

    dat_data = dat_path.read_bytes()
    idx_data = idx_path.read_bytes()

    print(f"daily.idx: {len(idx_data)} bytes ({len(idx_data) // 6} entries)")
    print(f"daily.dat: {len(dat_data)} bytes")
    print()

    # Compute source zip hash
    zip_path = SWORD_RAW_DIR / f"{MODULE_NAME}.zip"
    source_hash = ""
    if zip_path.exists():
        h = hashlib.sha256()
        with open(zip_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        source_hash = h.hexdigest()

    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Parse all 366 day entries (IDX[1..366]; IDX[0] is module header)
    n_idx_entries = len(idx_data) // 6
    entries = []
    errors = 0
    skipped = 0

    # Build expected (month, day) sequence: Jan 1..31, Feb 1..29, Mar 1..31, ...
    # SWORD IDX entries are sorted alphabetically by key ("01.01", "01.02", ...)
    # so they naturally go Jan->Dec with Feb having 29 days
    expected_days = []
    for month in range(1, 13):
        n_days = DAYS_IN_MONTH[month - 1]
        if month == 2:
            n_days = 29  # include Feb 29
        for day in range(1, n_days + 1):
            expected_days.append((month, day))

    # IDX[1] = first real entry (Jan 1), IDX[0] = header
    for i in range(1, n_idx_entries):
        if i - 1 >= len(expected_days):
            logging.warning("  IDX entry %d exceeds expected day count", i)
            break

        expected_month, expected_day = expected_days[i - 1]

        off, sz = struct.unpack_from("<IH", idx_data, i * 6)
        if sz == 0:
            skipped += 1
            continue

        raw_bytes = dat_data[off : off + sz]
        parsed = parse_dat_entry(raw_bytes, expected_month, expected_day)
        if parsed is None:
            logging.warning("  Failed to parse IDX[%d]", i)
            errors += 1
            continue

        month, day, morning_html, evening_html = parsed

        # Morning entry
        if morning_html.strip():
            entries.append(make_entry(month, day, "morning", morning_html, config))
        else:
            logging.warning("  Empty morning content for %02d.%02d", month, day)

        # Evening entry
        if evening_html.strip():
            entries.append(make_entry(month, day, "evening", evening_html, config))
        else:
            logging.warning("  Empty evening content for %02d.%02d", month, day)

        # Progress
        if (i % 100) == 0:
            print(f"  Processed {i}/{n_idx_entries - 1} days ...")

    print(f"  Parsed {len(entries)} entries ({errors} parse errors, {skipped} skipped)")
    print()

    # Quality report
    expected_entries = config.get("expected_entries", 732)
    report_quality(entries, expected_entries)
    print()

    # Build output now (before dry-run exit) so we can validate the full dict.
    meta = build_meta(config, source_hash, processing_date)
    output = {"meta": meta, "data": entries}

    # Schema validation -- always runs (dry-run and production alike).
    # Catches schema drift before writing any files.
    _check_output_schema(output)

    if args.dry_run:
        elapsed = time.time() - start_time
        # Print first 2 entries as sample
        print("--- Sample entries (dry-run, first 2 shown) ---")
        for e in entries[:2]:
            sample = dict(e)
            sample["content_blocks"] = [b[:200] + "..." if len(b) > 200 else b for b in sample["content_blocks"]]
            print(json.dumps(sample, ensure_ascii=True, indent=2))
        print(f"Dry-run complete -- no files written. ({elapsed:.1f}s)")
        return

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "daily-light.json"
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = out_file.stat().st_size / 1024
    elapsed = time.time() - start_time
    msg = f"Wrote {len(entries)} entries -> {out_file} ({size_kb:.0f} KB, {elapsed:.1f}s)"
    print(msg)
    logging.info(msg)


if __name__ == "__main__":
    main()
