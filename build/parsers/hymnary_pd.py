"""hymnary_pd.py
Parser for Hymnary.org public-domain hymn dataset.

Reads oldest_pd_instances.csv.zip (received 2026-04-22 directly from Hymnary.org),
extracts 34,918 public-domain hymn records, and writes a single OCD hymn_collection
JSON file.

Source: https://hymnary.org
License: Hymn texts are public domain. OCD curation is CC0-1.0.
Credit: Please link to https://hymnary.org when using this dataset, and encourage
        application developers to submit their projects at https://hymnary.org/contact.

Usage:
    py -3 build/parsers/hymnary_pd.py --dry-run   (parse, validate, print stats)
    py -3 build/parsers/hymnary_pd.py              (full run, writes output file)
"""

import argparse
import csv
import hashlib
import io
import json
import logging
import re
import sys
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.config_validation import validate_config_enums  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "hymnary-pd"
OUTPUT_DIR = REPO_ROOT / "data" / "hymns" / "hymnary-pd"
SCHEMA_PATH = REPO_ROOT / "schemas" / "v1" / "hymn_collection.schema.json"
CONFIG_PATH = REPO_ROOT / "sources" / "hymns" / "hymnary-pd" / "config.json"

RAW_ZIP = RAW_DIR / "oldest_pd_instances.csv.zip"
CSV_MEMBER = "oldest_pd_instances.csv"
OUTPUT_FILE = OUTPUT_DIR / "collection.json"
LOG_FILE = Path(__file__).with_suffix(".log")

COLLECTION_ID = "hymnary-pd"
SCHEMA_VERSION = "1.0.0"
SCRIPT_VERSION = "v1.0.0"
DOWNLOAD_DATE = "2026-04-22"  # date raw file was received from Hymnary.org

PROGRESS_INTERVAL = 5000  # log a progress line every N entries

# Reasonable year range for hymns
YEAR_MIN = 1000
YEAR_MAX = 2030

# One non-ASCII letter (Unicode category L*) in the sample triggers 'mul'.
# Typographic punctuation (curly quotes, em-dash) does NOT count.
_LANG_NONASCII_LETTER_THRESHOLD = 1

# ---------------------------------------------------------------------------
# Pure helper functions (importable, no side effects)
# ---------------------------------------------------------------------------


def parse_stanzas(full_text: str) -> list[str]:
    """Split hymn full_text into stanzas on blank lines. Normalises \\r\\n to \\n."""
    if not full_text or not full_text.strip():
        return []
    normalised = full_text.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n{2,}", normalised)
    return [p.strip() for p in parts if p.strip()]


def parse_year_str(s: str) -> int | None:
    """Parse a year string to an integer, or None if invalid/ambiguous."""
    s = (s or "").strip()
    if not s:
        return None
    # Reject multi-value strings (multi-author placeholders like "1783; 1877" or ";")
    if ";" in s:
        return None
    # Must be a plain integer
    if not re.fullmatch(r"-?\d+", s):
        return None
    year = int(s)
    if year < YEAR_MIN or year > YEAR_MAX:
        return None
    return year


def parse_author_years(
    birth_str: str, death_str: str
) -> tuple[int | None, int | None]:
    """
    Parse author birth and death years for single-author rows.
    Returns (None, None) for multi-author rows (semicolons in either string).
    """
    birth_str = (birth_str or "").strip()
    death_str = (death_str or "").strip()
    # Multi-author: both strings may contain semicolons
    if ";" in birth_str or ";" in death_str:
        return None, None
    return parse_year_str(birth_str), parse_year_str(death_str)


def detect_language(title: str, text: str) -> str:
    """
    Return 'en' if no non-ASCII letters appear in the title + first 500 chars of text.
    Typographic punctuation (curly quotes, em-dash) is ignored; only Unicode letter
    categories (L*) are counted, so German 'ü', Spanish 'á', etc. trigger 'mul'.
    """
    sample = (title or "") + (text or "")[:500]
    non_ascii_letters = sum(
        1 for c in sample if ord(c) > 127 and unicodedata.category(c).startswith("L")
    )
    return "en" if non_ascii_letters < _LANG_NONASCII_LETTER_THRESHOLD else "mul"


def slugify_title(text: str) -> str:
    """
    Convert a hymn title to a kebab-case ASCII slug.
    Non-ASCII characters are decomposed then stripped.
    """
    if not text:
        return "untitled"
    # NFKD decomposition + strip non-ASCII bytes
    normalised = unicodedata.normalize("NFKD", text)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    lower = ascii_only.lower()
    # Replace anything that is not alphanumeric with a hyphen
    slug = re.sub(r"[^a-z0-9]+", "-", lower)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    return slug if slug else "untitled"


def build_entry_id(
    title: str,
    author: str | None,
    hymnal_year: int | None,
    used_ids: set[str],
) -> str:
    """
    Build a unique kebab-case entry_id. Tries successively longer variants
    to resolve collisions, recording the chosen id in used_ids.

    Strategy: title-slug -> title+author-word -> title+author+year -> title+counter
    """
    base = slugify_title(title)

    # Attempt 1: bare title slug
    if base not in used_ids:
        used_ids.add(base)
        return base

    # Attempt 2: title + first word of author surname
    author_slug = ""
    if author:
        first_part = (author or "").split(";")[0].split(",")[0].strip()
        author_slug = slugify_title(first_part)

    if author_slug:
        candidate = f"{base}-{author_slug}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate

    # Attempt 3: title + author + year
    if author_slug and hymnal_year:
        candidate = f"{base}-{author_slug}-{hymnal_year}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate

    # Attempt 4+: title + counter
    suffix_base = f"{base}-{author_slug}" if author_slug else base
    counter = 2
    while True:
        candidate = f"{suffix_base}-{counter}"
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------


def build_entry(row: dict, used_ids: set[str]) -> dict:
    """Convert one CSV row dict into an OCD hymn entry dict."""
    title = (row.get("Title") or "").strip()
    author_raw = (row.get("Author name") or "").strip() or None
    birth_str = (row.get("Author birth") or "").strip()
    death_str = (row.get("Author death") or "").strip()
    year_written_str = (row.get("Year written") or "").strip()
    full_text = (row.get("Full text") or "").strip()
    hymnal_title = (row.get("Hymnal title") or "").strip() or None
    hymnal_year_str = (row.get("Hymnal publication year") or "").strip()

    birth_year, death_year = parse_author_years(birth_str, death_str)
    year_written = parse_year_str(year_written_str)
    hymnal_year = parse_year_str(hymnal_year_str)

    stanzas = parse_stanzas(full_text)
    lang = detect_language(title, full_text)

    all_text = " ".join(stanzas)
    word_count = len(all_text.split()) if all_text.strip() else 0

    entry_id = build_entry_id(title, author_raw, hymnal_year, used_ids)

    entry: dict = {
        "entry_id": entry_id,
        "collection_id": COLLECTION_ID,
        "title": title,
        "author": author_raw,
        "author_birth_year": birth_year,
        "author_death_year": death_year,
        "year_written": year_written,
        "stanzas": stanzas,
        "language": lang,
        "hymnal_title": hymnal_title,
        "hymnal_year": hymnal_year,
        "word_count": word_count,
    }

    # Token count via tiktoken if available (cl100k_base)
    try:
        import tiktoken  # noqa: PLC0415
        enc = tiktoken.get_encoding("cl100k_base")
        entry["token_count"] = len(enc.encode(all_text))
    except ImportError:
        pass
    except Exception as exc:
        logging.warning("tiktoken error for %r: %s", entry_id, exc)

    return entry


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    validate_config_enums(config, "hymn_collection")
    return config


def parse_csv(zip_path: Path) -> list[dict]:
    """Read CSV rows from zip. Returns list of raw row dicts."""
    with zipfile.ZipFile(zip_path, "r") as z:
        with z.open(CSV_MEMBER) as f:
            content = f.read().decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


def build_output(rows: list[dict], config: dict, source_hash: str) -> dict:
    """Build the complete OCD hymn_collection output dict."""
    used_ids: set[str] = set()
    entries = []
    skipped_no_text = 0

    for row in rows:
        full_text = (row.get("Full text") or "").strip()
        if not full_text:
            skipped_no_text += 1
            logging.warning("Skipping row with no text: title=%r", row.get("Title", ""))
            continue
        entry = build_entry(row, used_ids)
        entries.append(entry)
        if len(entries) % PROGRESS_INTERVAL == 0:
            logging.info("  ... %d entries built", len(entries))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    output = {
        "meta": {
            "id": config["resource_id"],
            "title": config["title"],
            "contributors": normalize_contributors(config.get("contributors", [])),
            "language": config["language"],
            "tradition": config["tradition"],
            "tradition_notes": config.get("tradition_notes"),
            "license": config["license"],
            "schema_type": "hymn_collection",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",
            "provenance": {
                "source_url": config["source_url"],
                "source_format": config["source_format"],
                "source_edition": config["source_edition"],
                "download_date": DOWNLOAD_DATE,
                "source_hash": source_hash,
                "processing_method": "automated",
                "processing_script_version": SCRIPT_VERSION,
                "processing_date": today,
                "notes": config.get("notes"),
            },
        },
        "data": entries,
    }

    return output, skipped_no_text


def print_quality_stats(entries: list[dict]) -> None:
    """Print completeness and distribution stats (PIPE-02)."""
    total = len(entries)
    no_author = sum(1 for e in entries if not e.get("author"))
    no_birth = sum(1 for e in entries if e.get("author_birth_year") is None)
    no_year_written = sum(1 for e in entries if e.get("year_written") is None)
    no_hymnal_year = sum(1 for e in entries if e.get("hymnal_year") is None)
    empty_stanzas = sum(1 for e in entries if not e.get("stanzas"))
    non_english = sum(1 for e in entries if e.get("language") != "en")
    word_counts = [e["word_count"] for e in entries]
    word_counts.sort()
    n = len(word_counts)
    p25 = word_counts[n // 4] if n else 0
    median = word_counts[n // 2] if n else 0
    p75 = word_counts[3 * n // 4] if n else 0

    has_tokens = sum(1 for e in entries if "token_count" in e)

    print(f"  Total entries:          {total:,}")
    print(f"  No author:              {no_author:,} ({100*no_author//total}%)")
    print(f"  No author birth year:   {no_birth:,} ({100*no_birth//total}%)")
    print(f"  No year written:        {no_year_written:,} ({100*no_year_written//total}%)")
    print(f"  No hymnal year:         {no_hymnal_year:,} ({100*no_hymnal_year//total}%)")
    print(f"  Empty stanzas:          {empty_stanzas}")
    print(f"  Non-English (mul):      {non_english:,} ({100*non_english//total}%)")
    print(f"  Word counts (p25/med/p75): {p25}/{median}/{p75}")
    print(f"  Token counts computed:  {has_tokens:,}")


def validate_output(output: dict) -> int:
    """Validate against JSON Schema. Returns error count."""
    try:
        import jsonschema  # noqa: PLC0415
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(output))
        if errors:
            for err in errors[:5]:
                logging.error("Schema error: %s", err.message)
        return len(errors)
    except ImportError:
        logging.warning("jsonschema not installed -- skipping schema validation")
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Hymnary PD hymn dataset")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate without writing output file",
    )
    args = parser.parse_args()

    # Reconfigure stdout to UTF-8 so non-ASCII hymn text (German umlauts,
    # Spanish accents, curly quotes) does not crash the cp1252 Windows console.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    start = datetime.now(timezone.utc)
    logging.info("hymnary_pd.py %s -- dry_run=%s", SCRIPT_VERSION, args.dry_run)

    if not RAW_ZIP.exists():
        logging.error("Raw file not found: %s", RAW_ZIP)
        sys.exit(1)

    logging.info("Computing source hash...")
    source_hash = compute_sha256(RAW_ZIP)
    logging.info("Source hash: %s", source_hash)

    logging.info("Parsing CSV from zip...")
    try:
        rows = parse_csv(RAW_ZIP)
    except Exception as exc:
        logging.error("Failed to parse CSV from zip: %s", exc)
        sys.exit(1)
    logging.info("Loaded %d rows", len(rows))

    config = load_config()

    logging.info("Building entries...")
    output, skipped = build_output(rows, config, source_hash)
    entries = output["data"]
    logging.info(
        "Built %d entries, skipped %d (no text)", len(entries), skipped
    )

    # Fail-fast guard: entry_ids must be unique
    ids = [e["entry_id"] for e in entries]
    unique_ids = set(ids)
    if len(ids) != len(unique_ids):
        logging.error(
            "Duplicate entry_ids detected: %d entries, %d unique",
            len(ids), len(unique_ids),
        )
        sys.exit(1)
    logging.info("All %d entry_ids unique", len(ids))

    print("\nQuality stats:")
    print_quality_stats(entries)

    print("\nSample entry (data[0]):")
    print(json.dumps(entries[0], indent=2, ensure_ascii=False))

    logging.info("Validating against schema...")
    error_count = validate_output(output)
    if error_count:
        logging.error("Schema validation: %d errors", error_count)
    else:
        logging.info("Schema validation: OK")

    if error_count:
        logging.error("Schema invalid -- output NOT written. Fix errors above and re-run.")
        sys.exit(1)

    if args.dry_run:
        logging.info("DRY RUN -- output not written")
    else:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        tmp = OUTPUT_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        tmp.replace(OUTPUT_FILE)
        size_mb = OUTPUT_FILE.stat().st_size / 1024 / 1024
        logging.info("Written: %s (%.1f MB)", OUTPUT_FILE, size_mb)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logging.info(
        "SUMMARY: %d entries, %d skipped, %d schema errors, %.1fs",
        len(entries),
        skipped,
        error_count,
        elapsed,
    )


if __name__ == "__main__":
    main()
