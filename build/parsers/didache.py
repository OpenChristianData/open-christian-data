"""didache.py
Parser for Didache prayers, Kirsopp Lake translation (1912).

Downloads the Wikisource page via its MediaWiki API and extracts the prayer
content from Chapters 8-10 into OCD prayer schema records:
  - Chapter VIII.2  The Lord's Prayer
  - Chapter IX.2    Eucharistic Prayer over the Cup
  - Chapter IX.3-4  Eucharistic Prayer over the Bread
  - Chapter X.2-6   Thanksgiving after the Eucharist

Source: https://en.wikisource.org/wiki/Didache_(Lake_translation)
        via https://en.wikisource.org/w/api.php?action=parse&prop=wikitext

License:
  Original Didache text: public domain (c. 50-120 AD).
  Kirsopp Lake translation (1912): published >70 years ago, public domain in US.

Wikitext structure (inspected 2026-03-28):
  Chapters are marked ==Chapter VIII==, ==Chapter IX==, ==Chapter X==
  Verses are marked with {{verse|chapter=N|verse=N}} templates
  Sidebar labels: |<small>Label</small>
  Footnotes: <ref>...</ref>
  Prayer text is in double quotes within the verse prose

Usage:
    py -3 build/parsers/didache.py --dry-run    (parse, no write)
    py -3 build/parsers/didache.py               (full run)
    py -3 build/parsers/didache.py --force-download
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "wikisource"
OUTPUT_DIR = REPO_ROOT / "data" / "prayers" / "didache"
CONFIG_PATH = REPO_ROOT / "sources" / "prayers" / "didache" / "config.json"

RAW_FILE = RAW_DIR / "didache.json"
OUTPUT_FILE = OUTPUT_DIR / "prayers.json"

API_URL = (
    "https://en.wikisource.org/w/api.php"
    "?action=parse&page=Didache_(Lake_translation)&prop=wikitext&format=json"
)
USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)

COLLECTION_ID = "didache-prayers"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

# Chapters to extract (Roman numeral heading, decimal chapter number)
TARGET_CHAPTERS = [("VIII", 8), ("IX", 9), ("X", 10)]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_api_json(force: bool = False) -> None:
    """Download Didache wikitext from Wikisource API to raw/wikisource/didache.json."""
    if RAW_FILE.exists() and not force:
        print(f"Source file cached: {RAW_FILE}")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {API_URL} ...")
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(RAW_FILE, "wb") as fh:
            fh.write(data)
        size_kb = len(data) / 1024
        print(f"Downloaded {size_kb:.1f} KB -> {RAW_FILE}")
    except Exception as exc:
        raise RuntimeError(
            f"Wikisource API call failed: {exc}. "
            "Check network access or retry with --force-download."
        ) from exc


# ---------------------------------------------------------------------------
# Wikitext extraction helpers
# ---------------------------------------------------------------------------

def load_wikitext() -> str:
    """Load and return the wikitext string from the cached API JSON."""
    with open(RAW_FILE, encoding="utf-8") as fh:
        api_data = json.load(fh)
    try:
        return api_data["parse"]["wikitext"]["*"]
    except KeyError as exc:
        raise RuntimeError(
            f"Unexpected API JSON structure -- missing key {exc}. "
            f"Inspect {RAW_FILE} manually."
        ) from exc


def extract_chapter(wikitext: str, roman: str) -> str:
    """
    Return the raw wikitext for a single chapter.
    Finds ==Chapter ROMAN== and slices to the start of the next chapter
    (or ==Original footnotes==).
    """
    heading = f"==Chapter {roman}=="
    start = wikitext.find(heading)
    if start == -1:
        raise RuntimeError(f"Chapter {roman} heading not found in wikitext")

    # End at the next == heading
    end_match = re.search(r"\n==", wikitext[start + len(heading):])
    if end_match:
        end = start + len(heading) + end_match.start()
    else:
        end = len(wikitext)

    return wikitext[start:end]


def clean_wikitext(raw: str) -> str:
    """
    Strip wikitext markup from a text fragment and return clean prose.

    MediaWiki table syntax wraps each verse like:
      |{{verse|chapter=9|verse=2}}Prayer text here...
      |<small>The Cup</small>
    The leading | is a table-cell marker; the content after it is the verse text.

    Removes:
      - <ref>...</ref> footnote blocks (including multi-line)
      - {{verse|...}} verse markers (keep surrounding prose)
      - {{template}} blocks
      - Sidebar label cells |<small>...</small>
      - Pure table-control lines: {|, |}, |-, |width=...
    Strips the leading | from content lines (table cell markers).
    Normalizes whitespace.
    """
    text = raw
    # Remove footnotes (may span lines)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.DOTALL)
    # Remove verse markers (preserve the prose that follows them)
    text = re.sub(r"\{\{verse\|[^}]+\}\}", "", text)
    # Remove chapter-header templates like {{chapter|8}}
    text = re.sub(r"\{\{chapter\|[^}]+\}\}", "", text)
    # Remove remaining single-level {{templates}}
    text = re.sub(r"\{\{[^{}]+\}\}", "", text)
    # Remove sidebar label cells: |<small>...</small>
    text = re.sub(r"\|<small>.*?</small>", "", text, flags=re.DOTALL)
    # Remove pure table-control lines: table open {|, close |}, row separator |-
    text = re.sub(r"^\s*\{\|.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|\}.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\|-.*$", "", text, flags=re.MULTILINE)
    # Remove column-width declarations: |width="..."|
    text = re.sub(r"^\s*\|width=[^\n]*$", "", text, flags=re.MULTILINE)
    # Strip the leading table-cell | from content lines (verse content)
    text = re.sub(r"^\s*\|", "", text, flags=re.MULTILINE)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_quoted_text(text: str) -> str:
    """
    Extract the text that appears between the first and last double-quote
    character in a string.  The Didache prayer texts are all in quotes.
    Returns an empty string if no quotes are found.
    """
    first = text.find('"')
    last = text.rfind('"')
    if first == -1 or last <= first:
        return ""
    return text[first + 1:last].strip()


def word_count(text: str) -> int:
    """Count whitespace-delimited words."""
    return len(text.split()) if text.strip() else 0


def make_incipit(text: str, n: int = 10) -> str:
    """Return the first N words followed by '...'."""
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "..."


# ---------------------------------------------------------------------------
# Prayer extraction
# ---------------------------------------------------------------------------

def extract_prayers(wikitext: str) -> list:
    """
    Extract 4 prayer records from chapters 8-10 of the Didache wikitext.

    Returns a list of dicts with keys:
      prayer_id, title, occasion, content, location
    """
    prayers = []

    # --- Chapter VIII: Lord's Prayer (verse 2) ---
    ch8 = extract_chapter(wikitext, "VIII")
    ch8_clean = clean_wikitext(ch8)

    # The Lord's Prayer appears in quotes after "pray thus:"
    lords_prayer_match = re.search(
        r'pray thus:\s*"(Our Father[^"]+)"',
        ch8_clean,
        re.IGNORECASE,
    )
    if lords_prayer_match:
        lp_text = lords_prayer_match.group(1).strip()
        prayers.append(
            {
                "prayer_id": "8-lords-prayer",
                "title": "The Lord's Prayer",
                "occasion": "Daily Prayer",
                "content": lp_text,
                "location": "Chapter VIII.2",
            }
        )
    else:
        print("  WARNING: Lord's Prayer not found in Chapter VIII")

    # --- Chapter IX: Eucharistic prayers (verses 2 and 3-4) ---
    ch9 = extract_chapter(wikitext, "IX")
    ch9_clean = clean_wikitext(ch9)

    # Cup prayer: appears after "First concerning the Cup,"
    cup_match = re.search(
        r'First concerning the Cup[^"]*"([^"]+)"',
        ch9_clean,
        re.IGNORECASE,
    )
    if cup_match:
        prayers.append(
            {
                "prayer_id": "9-cup",
                "title": "Eucharistic Prayer over the Cup",
                "occasion": "Eucharist",
                "content": cup_match.group(1).strip(),
                "location": "Chapter IX.2",
            }
        )
    else:
        print("  WARNING: Cup prayer not found in Chapter IX")

    # Bread prayer: appears after "concerning the broken Bread:"
    # spans verses 3-4, closed with a single closing quote
    bread_match = re.search(
        r'concerning the broken Bread[^"]*"(.*?)"(?:\s*But let none)',
        ch9_clean,
        re.DOTALL | re.IGNORECASE,
    )
    if bread_match:
        bread_text = re.sub(r"\s+", " ", bread_match.group(1)).strip()
        prayers.append(
            {
                "prayer_id": "9-bread",
                "title": "Eucharistic Prayer over the Bread",
                "occasion": "Eucharist",
                "content": bread_text,
                "location": "Chapter IX.3-4",
            }
        )
    else:
        print("  WARNING: Bread prayer not found in Chapter IX")

    # --- Chapter X: Post-Eucharist thanksgiving (verses 2-6) ---
    ch10 = extract_chapter(wikitext, "X")
    ch10_clean = clean_wikitext(ch10)

    # The thanksgiving spans verses 2-6, begins after "thus give thanks:"
    thanksgiving_match = re.search(
        r'thus give thanks[^"]*"(.*?Amen\.)"',
        ch10_clean,
        re.DOTALL | re.IGNORECASE,
    )
    if thanksgiving_match:
        thanksgiving_text = re.sub(r"\s+", " ", thanksgiving_match.group(1)).strip()
        prayers.append(
            {
                "prayer_id": "10-thanksgiving",
                "title": "Thanksgiving after the Eucharist",
                "occasion": "Eucharist",
                "content": thanksgiving_text,
                "location": "Chapter X.2-6",
            }
        )
    else:
        print("  WARNING: Thanksgiving prayer not found in Chapter X")

    return prayers


# ---------------------------------------------------------------------------
# Prayer record builder
# ---------------------------------------------------------------------------

def build_prayer_record(item: dict) -> dict:
    """Build an OCD prayer schema record from an extracted prayer dict."""
    text = item["content"]
    wc = word_count(text)
    return {
        "collection_id": COLLECTION_ID,
        "prayer_id": item["prayer_id"],
        "title": item["title"],
        "incipit": make_incipit(text),
        "author": None,
        "year": None,
        "occasion": item["occasion"],
        "content_blocks": [text],
        "scripture_references": [],
        "context": {
            "work": "Didache (Lake translation, 1912)",
            "location": item["location"],
        },
        "word_count": wc,
    }


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def report_quality(records: list, expected_count: int = None) -> None:
    """Print quality statistics."""
    total = len(records)
    print(f"  Record count: {total}", end="")
    if expected_count is not None:
        print(f" (expected {expected_count})", end="")
        if total != expected_count:
            print(f" -- WARNING: mismatch!", end="")
    print()

    for r in records:
        wc = r["word_count"]
        title = r["title"] or r["prayer_id"]
        print(f"    {r['prayer_id']}: {wc} words -- {title}")
        if wc < 10:
            print(f"      WARNING: word count suspiciously low")


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(config: dict, source_hash: str, processing_date: str) -> dict:
    """Build the OCD metadata envelope from source config."""
    return {
        "id": config["resource_id"],
        "title": config["title"],
        "author": config.get("author"),
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
        "schema_type": "prayer",
        "schema_version": SCHEMA_VERSION,
        "completeness": "partial",
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": processing_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/didache.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Parse Didache prayers (Lake 1912) into OCD prayer schema"
    )
    arg_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print samples, do not write output file",
    )
    arg_parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download the Wikisource API JSON even if already cached",
    )
    args = arg_parser.parse_args()

    start_time = time.time()

    # Load source config
    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        config = json.load(fh)

    print(f"Source:  {config['title']}")
    print(f"Output:  {OUTPUT_FILE}")
    if args.dry_run:
        print("Mode:    dry-run (no write)")
    print()

    # Download
    if args.dry_run and not RAW_FILE.exists():
        print("Dry-run: raw file not cached. Run without --dry-run to download first.")
        sys.exit(0)
    download_api_json(force=args.force_download)
    print()

    # Compute hash of raw file
    raw_bytes = RAW_FILE.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()

    # Parse
    print("Parsing wikitext ...")
    wikitext = load_wikitext()
    prayer_items = extract_prayers(wikitext)
    records = [build_prayer_record(item) for item in prayer_items]
    print()

    # Quality report
    expected_count = config.get("expected_count")
    print("Quality report:")
    report_quality(records, expected_count=expected_count)
    print()

    if args.dry_run:
        elapsed = time.time() - start_time
        print("--- Sample records ---")
        for r in records:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print()
        print(f"Dry-run complete -- {len(records)} records. ({elapsed:.1f}s)")
        return

    # Validate expected count
    if expected_count is not None and len(records) != expected_count:
        print(
            f"ERROR: Expected {expected_count} prayers, got {len(records)}. "
            "Check parse output above for WARNING messages."
        )
        sys.exit(1)

    # Build output
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    meta = build_meta(config, source_hash, processing_date)
    output = {"meta": meta, "data": records}

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    elapsed = time.time() - start_time
    print(f"Wrote {len(records)} records -> {OUTPUT_FILE}")
    print(f"File size: {size_kb:.0f} KB")
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
