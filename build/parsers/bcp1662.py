"""bcp1662.py
Parser for Book of Common Prayer (1662) Collects.

Downloads five HTML pages from eskimo.com/~lhowell/bcp1662/ (with 2-second
delays between requests) to raw/bcp1662/, then extracts the Collect for each
Sunday and Feast Day into a single OCD prayer JSON file.

Source: https://eskimo.com/~lhowell/bcp1662/communion/
License: Public domain in the US (no robots.txt crawl-delay restrictions).
User-Agent: OpenChristianData/1.0

HTML structure (inspected 2026-03-28, all five pages):
  - Each occasion: <center><strong><a name="ANCHOR">TITLE.</a></strong></center>
    Attributes use spaces around =: NAME = "Advent1" not NAME="Advent1".
  - Collect section: <multicol cols="2"><center><i>The Collect.</i></center>
    VARIANT: trinity.html uses <em>The Collect.</em> instead of <i>The Collect.</i>.
    The parser handles both via collect_tag = r"(?:i|em)".
  - Collect text begins with <strong><img alt="LETTER">REST</strong>
    where LETTER is the decorative capital and REST is the remainder of the
    first word (or empty if the first word is a single letter like "O").
  - Collect ends with <i>Amen.</i> followed by optional repetition notes.
  - Primary boundary: <center><i>The Epistle.</i> or <center><i>The Gospel.</i>
    VARIANT: saints.html and some other pages use "For the Epistle." not "The
    Epistle." -- the parser matches both via (?:For the|The) Epistle pattern.
  - Fallback boundary (no Epistle/Gospel): <hr>, <p>, or next <center><strong>.

Five source pages (Parts I-V of the Collects, Epistles, and Gospels):
  xmas.html    Advent, Christmas, Epiphany seasons
  lent.html    Lent, Holy Week, Easter Even
  easter.html  Easter, Ascension, Whitsuntide
  trinity.html Trinity Sunday through Trinity 25
  saints.html  Saints' Days

Usage:
    py -3 build/parsers/bcp1662.py --dry-run        (parse without writing)
    py -3 build/parsers/bcp1662.py                   (full run)
    py -3 build/parsers/bcp1662.py --force-download  (re-download cached files)
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
RAW_DIR = REPO_ROOT / "raw" / "bcp1662"
OUTPUT_DIR = REPO_ROOT / "data" / "prayers" / "bcp-1662"
CONFIG_PATH = REPO_ROOT / "sources" / "prayers" / "bcp-1662-collects" / "config.json"

OUTPUT_FILE = OUTPUT_DIR / "collects.json"

BASE_URL = "https://eskimo.com/~lhowell/bcp1662/communion/"
SOURCE_PAGES = [
    ("xmas.html", "Part I: Advent, Christmas, and Epiphany seasons"),
    ("lent.html", "Part II: Lent and Holy Week"),
    ("easter.html", "Part III: Easter through Whitsuntide"),
    ("trinity.html", "Part IV: Trinity Sunday through Trinity 25"),
    ("saints.html", "Part V: Saints' Days"),
]

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
CRAWL_DELAY_SECONDS = 2

COLLECTION_ID = "bcp-1662-collects"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_page(filename: str, force: bool = False) -> None:
    """Download one HTML page from eskimo.com to raw/bcp1662/."""
    dest = RAW_DIR / filename
    if dest.exists() and not force:
        print(f"  Cached: {filename}")
        return
    url = BASE_URL + filename
    print(f"  Fetching {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        print(f"  Saved {len(data):,} bytes -> {dest.name}")
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for {filename}: {exc}. "
            "Check network access or retry with --force-download."
        ) from exc


def download_all_pages(force: bool = False) -> None:
    """Download all five source pages with crawl-delay between requests."""
    print(f"Downloading {len(SOURCE_PAGES)} HTML pages ...")
    for i, (filename, _) in enumerate(SOURCE_PAGES):
        if i > 0:
            already_cached = (RAW_DIR / filename).exists() and not force
            if not already_cached:
                time.sleep(CRAWL_DELAY_SECONDS)
        download_page(filename, force=force)
    print()


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------

def strip_tags(html: str) -> str:
    """Remove all HTML tags from a string."""
    return re.sub(r"<[^>]+>", " ", html)


def normalize_ws(text: str) -> str:
    """Collapse internal whitespace and strip edges."""
    return re.sub(r"\s+", " ", text).strip()


def fix_initial_letter(html: str) -> str:
    """
    Reconstruct the decorative capital letter.

    The BCP 1662 pages use a large drop-cap image for the first letter of each
    collect, e.g. <strong><img alt="A">LMIGHTY</strong> -> ALMIGHTY.
    For single-letter words (e.g. "O God"), the img alt carries the whole
    first word and no text follows: <strong><img alt="O"></strong> -> O.
    """
    def _replace(m: re.Match) -> str:
        alt_letter = m.group(1)
        rest = m.group(2).strip()
        return alt_letter + rest

    return re.sub(
        r'<strong[^>]*>\s*<img[^>]+alt="([A-Z])"[^>]*>\s*([^<]*)\s*</strong>',
        _replace,
        html,
        flags=re.IGNORECASE,
    )


def remove_repetition_notes(html: str) -> str:
    """
    Strip rubric notes embedded in the HTML.
    These appear as: <center><font color="Red"><em>This Collect is ...</em></font></center>
    They explain which collects are to be repeated on following days.
    """
    # Colored font blocks inside center tags
    cleaned = re.sub(
        r"<center>\s*<font[^>]*>.*?</font>\s*</center>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return cleaned


def slugify(text: str) -> str:
    """
    Convert a CamelCase or word anchor name to kebab-case.

    Examples:
      Advent1      -> advent-1
      StStephen    -> st-stephen
      GoodFri1     -> good-fri-1
      EasterEven   -> easter-even
      Nativity     -> nativity
    """
    # Insert hyphen between a lowercase letter (or digit) and an uppercase letter
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", text)
    # Insert hyphen between consecutive uppercase runs followed by lowercase
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", text)
    # Lowercase everything
    text = text.lower()
    # Replace non-alphanumeric runs with a single hyphen
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def make_incipit(text: str, word_count: int = 10) -> str:
    """Return the first N words followed by '...'."""
    words = text.split()
    if len(words) <= word_count:
        return text
    return " ".join(words[:word_count]) + "..."


def word_count(text: str) -> int:
    """Count whitespace-delimited words."""
    return len(text.split()) if text.strip() else 0


# ---------------------------------------------------------------------------
# Collect extraction
# ---------------------------------------------------------------------------

def extract_collects_from_html(html_text: str, source_filename: str) -> list:
    """
    Parse one BCP 1662 HTML page and return a list of collect dicts.

    Each dict has:
      anchor, title, text, source_filename

    Strategy:
      1. Split HTML at each occasion heading (<center><strong><a name="...">) so
         each chunk contains exactly one occasion.
      2. Within each chunk, find the collect section between the
         <center><i>The Collect.</i></center> marker and the first
         <center><i>The Epistle. or Gospel.</i></center> marker.
      3. Fix the decorative initial letter, remove rubric notes, strip HTML.
    """
    results = []
    errors = 0

    # Split at each occasion heading, keeping the heading in each chunk.
    # The HTML uses spaces around = in attributes: NAME = "Advent1"
    parts = re.split(
        r'(?=<center>\s*<strong>\s*<a\s+name\s*=\s*")',
        html_text,
        flags=re.IGNORECASE,
    )

    for part in parts:
        # --- Occasion name ---
        anchor_match = re.search(
            r'<a\s+name\s*=\s*"([^"]+)"[^>]*>(.*?)</a>',
            part,
            re.IGNORECASE,
        )
        if not anchor_match:
            continue

        anchor_name = anchor_match.group(1)
        title_html = anchor_match.group(2)
        title = normalize_ws(strip_tags(title_html)).rstrip(".")

        if not title:
            continue

        # --- Collect text ---
        # The HTML uses either <I>The Collect.</I> or <EM>The Collect.</EM>.
        # Boundary: collect section ends at the Epistle or Gospel marker,
        # or at an <HR> / next occasion heading / end of chunk.
        collect_tag = r"(?:i|em)"  # <I> or <EM>
        collect_match = re.search(
            rf"The\s+Collect\s*\.\s*</{collect_tag}>\s*</center>\s*(.*?)"
            rf"(?=<center>\s*<{collect_tag}>\s*(?:For\s+the\s+|The\s+)(?:Epistle|Gospel))",
            part,
            re.DOTALL | re.IGNORECASE,
        )
        if not collect_match:
            # Fallback: no Epistle/Gospel -- capture up to <HR>, <P> boundary,
            # or the next CENTER heading that does NOT look like a collect.
            collect_match = re.search(
                rf"The\s+Collect\s*\.\s*</{collect_tag}>\s*</center>\s*(.*?)"
                rf"(?=<(?:hr|p)\s*/?>|<center>\s*<strong>|$)",
                part,
                re.DOTALL | re.IGNORECASE,
            )

        if not collect_match:
            # No collect found -- section may be a non-collect entry
            continue

        collect_html = collect_match.group(1)

        try:
            collect_html = fix_initial_letter(collect_html)
            collect_html = remove_repetition_notes(collect_html)
            text = normalize_ws(strip_tags(collect_html))
        except Exception as exc:
            print(f"  ERROR parsing collect for '{title}' in {source_filename}: {exc}")
            errors += 1
            continue

        # Sanity check: skip entries with very short text (likely parse failures)
        if not text or word_count(text) < 10:
            continue

        results.append(
            {
                "anchor": anchor_name,
                "title": title,
                "text": text,
                "source_filename": source_filename,
            }
        )

    return results, errors


# ---------------------------------------------------------------------------
# Prayer record builder
# ---------------------------------------------------------------------------

def build_prayer_record(item: dict) -> dict:
    """Build an OCD prayer schema record from a parsed collect dict."""
    text = item["text"]
    wc = word_count(text)
    return {
        "collection_id": COLLECTION_ID,
        "prayer_id": slugify(item["anchor"]),
        "title": item["title"],
        "incipit": make_incipit(text),
        "author": None,
        "year": None,
        "occasion": None,
        "content_blocks": [text],
        "scripture_references": [],
        "context": {
            "work": "Book of Common Prayer (1662)",
            "location": "Collects, Epistles, and Gospels",
        },
        "word_count": wc,
    }


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def report_quality(records: list) -> None:
    """Print quality statistics for the parsed collect records."""
    total = len(records)
    if total == 0:
        print("  WARNING: No records produced")
        return

    word_counts = [r["word_count"] for r in records]
    sorted_wc = sorted(word_counts)
    short = sum(1 for wc in word_counts if wc < 20)
    no_incipit = sum(1 for r in records if not r["incipit"])
    no_title = sum(1 for r in records if not r["title"])

    # Check for duplicate prayer_ids
    seen_ids = {}
    for r in records:
        pid = r["prayer_id"]
        seen_ids[pid] = seen_ids.get(pid, 0) + 1
    duplicates = {pid: cnt for pid, cnt in seen_ids.items() if cnt > 1}

    # BCP 1662 collects are typically 30-120 words; anything over 150 indicates
    # the boundary regex failed to stop at the Epistle/Gospel marker.
    WORD_COUNT_ALARM = 150
    long_records = [r for r in records if r["word_count"] > WORD_COUNT_ALARM]

    print(f"  Record count: {total}")
    print(
        f"  Word count:   min={min(word_counts)} "
        f"median={sorted_wc[total // 2]} "
        f"max={max(word_counts)}"
    )
    if long_records:
        print(
            f"  WARNING: {len(long_records)}/{total} records exceed {WORD_COUNT_ALARM} words "
            f"(boundary regex may have failed -- check these):"
        )
        for r in sorted(long_records, key=lambda x: x["word_count"], reverse=True):
            print(f"    {r['prayer_id']}: {r['word_count']} words")
    if short:
        print(f"  WARNING: {short}/{total} records under 20 words (suspiciously short)")
    if no_incipit:
        print(f"  WARNING: {no_incipit}/{total} records missing incipit")
    if no_title:
        print(f"  WARNING: {no_title}/{total} records missing title")
    if duplicates:
        for pid, cnt in sorted(duplicates.items()):
            print(f"  WARNING: Duplicate prayer_id '{pid}' appears {cnt} times")


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
                f"build/parsers/bcp1662.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# Combined hash helper
# ---------------------------------------------------------------------------

def compute_combined_hash(filenames: list) -> str:
    """
    SHA-256 of the concatenated raw bytes of all source files (in list order).
    Provides a single stable hash representing the complete source download.
    """
    hasher = hashlib.sha256()
    for filename in filenames:
        path = RAW_DIR / filename
        if path.exists():
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


# ---------------------------------------------------------------------------
# Main parse loop
# ---------------------------------------------------------------------------

def parse_all_pages(dry_run: bool = False) -> tuple:
    """
    Parse all five source HTML pages and return (records, total_errors).
    If dry_run=True, parse only the first page and return 3 records.
    """
    all_records = []
    total_errors = 0

    pages_to_process = [SOURCE_PAGES[0]] if dry_run else SOURCE_PAGES

    for filename, description in pages_to_process:
        path = RAW_DIR / filename
        if not path.exists():
            print(f"  ERROR: Raw file not found: {path}")
            print("  Run without --dry-run to download first.")
            total_errors += 1
            continue

        print(f"  Parsing {filename} ({description}) ...")
        html_bytes = path.read_bytes()

        # Decode: try UTF-8 first; fall back to latin-1 for older HTML
        try:
            html_text = html_bytes.decode("utf-8")
        except UnicodeDecodeError:
            html_text = html_bytes.decode("latin-1", errors="replace")

        items, page_errors = extract_collects_from_html(html_text, filename)
        records = [build_prayer_record(item) for item in items]

        print(f"    {len(records)} collects extracted, {page_errors} errors")
        total_errors += page_errors

        if dry_run:
            # Return only first 3 records for a quick preview
            all_records.extend(records[:3])
            break
        else:
            all_records.extend(records)

    return all_records, total_errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Parse BCP 1662 Collects into OCD prayer schema"
    )
    arg_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first page only, print samples, do not write output",
    )
    arg_parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download source HTML even if already cached",
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
        print("Mode:    dry-run (first page only, no write)")
    print()

    # Download
    if args.dry_run and not any((RAW_DIR / fn).exists() for fn, _ in SOURCE_PAGES):
        print("Dry-run: no cached files found. Run without --dry-run to download first.")
        sys.exit(0)

    if not args.dry_run or args.force_download:
        download_all_pages(force=args.force_download)
    else:
        # Dry-run: download only if first page is missing
        first_page = SOURCE_PAGES[0][0]
        if not (RAW_DIR / first_page).exists():
            print(f"Dry-run: downloading {first_page} (not cached) ...")
            download_page(first_page, force=False)
            print()

    # Parse
    print("Parsing ...")
    records, total_errors = parse_all_pages(dry_run=args.dry_run)
    print()

    # Quality report
    print("Quality report:")
    report_quality(records)
    print()

    if args.dry_run:
        elapsed = time.time() - start_time
        print("--- Sample records (first 2) ---")
        for r in records[:2]:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print()
        print(
            f"Dry-run complete -- {len(records)} sample records, "
            f"{total_errors} errors. ({elapsed:.1f}s)"
        )
        return

    if total_errors > 0:
        print(f"WARNING: {total_errors} parse errors encountered")

    # Build output
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_hash = compute_combined_hash([fn for fn, _ in SOURCE_PAGES])
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

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
