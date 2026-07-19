"""spurgeon_mtp.py
Downloader and parser for Spurgeon's Metropolitan Tabernacle Pulpit sermons from
The Kingdom Collective (thekingdomcollective.com/spurgeon/sermon/).

Downloads up to 3,563 HTML sermon pages and parses them into OCD sermon schema JSON.

HTML structure (confirmed 2026-04-12 by inspecting sermons #1, #100, #1000, #3000, #3563):
  - Page container: <div id="content" class="content-column">
  - Sermon article: <article class="sermon">
  - Title: first <h1> inside article
  - Scripture reference: first <blockquote> inside article
      - Quote text: <p> children that do NOT contain span.reference
      - Citation: <p><span class="reference">Book Chapter:Verse</span></p>
  - Body: remaining <p> and <blockquote> elements in source order

Source:
  Site: The Kingdom Collective (thekingdomcollective.com)
  Author: C. H. Spurgeon (1834-1892, public domain in all jurisdictions)
  Transcription: Emmett O'Donnell (from SpurgeonGems PDFs), HTML by Benry Yip
  robots.txt: 404 (no robots.txt on this domain -- 2-second default delay applied)
  ToS: no ToS page found on the site

Usage:
    py -3 build/parsers/spurgeon_mtp.py --download-only   # hours-long; run in background
    py -3 build/parsers/spurgeon_mtp.py --parse --dry-run # parse first 10 files, no write
    py -3 build/parsers/spurgeon_mtp.py --parse            # full parse to data/sermons/
    py -3 build/parsers/spurgeon_mtp.py                    # download then parse (sequential)

Required:
    pip install beautifulsoup4==4.14.3
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore  -- checked inside main() to avoid import-time side effects

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.config_validation import validate_config_enums  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "spurgeon_sermons" / "html"
REQUEST_LOG = REPO_ROOT / "raw" / "spurgeon_sermons" / "request_log.csv"
OUTPUT_DIR = REPO_ROOT / "data" / "sermons" / "spurgeon-mtp"
CONFIG_PATH = REPO_ROOT / "sources" / "sermons" / "spurgeon-mtp" / "config.json"
LOG_FILE = REPO_ROOT / "build" / "parsers" / "spurgeon_mtp.log"

BASE_URL = "https://thekingdomcollective.com/spurgeon/sermon/{n}/"
MAX_SERMON_N = 3563
MIN_DELAY_SECONDS = 2.0  # no robots.txt found -- apply 2-second minimum delay
RETRY_DELAYS = [2, 4, 8]  # seconds between retries on 5xx or network errors

COLLECTION_ID = "spurgeon-metropolitan-tabernacle-pulpit"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v2.1.0"
LOCATION_DEFAULT = "Metropolitan Tabernacle, London"
LIST_PROJECTION_NOTE = (
    "List projection: direct ordered and unordered sermon-body list items are "
    "flattened into content_blocks in source order; list container and "
    "numbering/bullet boundaries are not represented."
)

USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)

# DRY_RUN is set via --dry-run flag in main(). When True, parse reads only the
# first 10 cached HTML files and prints samples without writing any output file.
DRY_RUN = False

# ---------------------------------------------------------------------------
# Book name -> OSIS code mapping
# ---------------------------------------------------------------------------

BOOK_NAME_TO_OSIS = {
    # Old Testament
    "Genesis": "Gen", "Exodus": "Exod", "Leviticus": "Lev",
    "Numbers": "Num", "Deuteronomy": "Deut", "Joshua": "Josh",
    "Judges": "Judg", "Ruth": "Ruth",
    "1 Samuel": "1Sam", "2 Samuel": "2Sam",
    "1 Kings": "1Kgs", "2 Kings": "2Kgs",
    "1 Chronicles": "1Chr", "2 Chronicles": "2Chr",
    "Ezra": "Ezra", "Nehemiah": "Neh", "Esther": "Esth",
    "Job": "Job",
    "Psalm": "Ps", "Psalms": "Ps",
    "Proverbs": "Prov", "Ecclesiastes": "Eccl",
    "Song of Solomon": "Song", "Song of Songs": "Song",
    "Isaiah": "Isa", "Jeremiah": "Jer", "Lamentations": "Lam",
    "Ezekiel": "Ezek", "Daniel": "Dan",
    "Hosea": "Hos", "Joel": "Joel", "Amos": "Amos",
    "Obadiah": "Obad", "Jonah": "Jonah", "Micah": "Mic",
    "Nahum": "Nah", "Habakkuk": "Hab", "Zephaniah": "Zeph",
    "Haggai": "Hag", "Zechariah": "Zech", "Malachi": "Mal",
    # New Testament
    "Matthew": "Matt", "Mark": "Mark", "Luke": "Luke", "John": "John",
    "Acts": "Acts", "Romans": "Rom",
    "1 Corinthians": "1Cor", "2 Corinthians": "2Cor",
    "Galatians": "Gal", "Ephesians": "Eph", "Philippians": "Phil",
    "Colossians": "Col",
    "1 Thessalonians": "1Thess", "2 Thessalonians": "2Thess",
    "1 Timothy": "1Tim", "2 Timothy": "2Tim",
    "Titus": "Titus", "Philemon": "Phlm", "Hebrews": "Heb",
    "James": "Jas",
    "1 Peter": "1Pet", "2 Peter": "2Pet",
    "1 John": "1John", "2 John": "2John", "3 John": "3John",
    "Jude": "Jude",
    "Revelation": "Rev", "The Revelation": "Rev",
}

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    """Print a timestamped message to stdout and append to the log file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{timestamp} {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_request(url: str, status: int, bytes_received: int, notes: str = "") -> None:
    """Append one row to request_log.csv. Writes header on first call."""
    write_header = not REQUEST_LOG.exists()
    with open(REQUEST_LOG, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "url", "http_status", "bytes_received", "notes"])
        writer.writerow([
            datetime.now(timezone.utc).isoformat(),
            url,
            str(status),
            str(bytes_received),
            notes,
        ])


# ---------------------------------------------------------------------------
# HTTP download
# ---------------------------------------------------------------------------


def fetch_url(url: str, timeout: int = 30):
    """
    Fetch a URL and return (http_status, content_bytes).
    Returns (404, b"") for 404s.
    Retries up to len(RETRY_DELAYS) times on 5xx / network errors.
    Raises RuntimeError after retry exhaustion.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_exc = None

    # 1 original attempt + len(RETRY_DELAYS) retries
    for attempt in range(1, len(RETRY_DELAYS) + 2):
        if attempt > 1:
            wait = RETRY_DELAYS[attempt - 2]
            log(f"  Retry {attempt - 1}/{len(RETRY_DELAYS)} for {url} (waiting {wait}s)")
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200, resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, b""
            if exc.code in (429, 500, 502, 503, 504):
                last_exc = exc
                continue
            raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
        except Exception as exc:
            last_exc = exc
            continue

    raise RuntimeError(f"Exhausted retries fetching {url}: {last_exc}")


def download_all(start_n: int = 1, end_n: int = MAX_SERMON_N) -> None:
    """
    Download HTML for sermon numbers start_n through end_n (inclusive).
    Skips sermons whose HTML file already exists (resume-safe).
    Logs every request to request_log.csv.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    REQUEST_LOG.parent.mkdir(parents=True, exist_ok=True)

    total = end_n - start_n + 1
    downloaded = 0
    skipped = 0
    not_found = 0
    errors = 0

    log(f"Download phase: sermons {start_n}-{end_n} ({total} total)")
    log(f"  Output: {RAW_DIR}")
    log(f"  Delay:  {MIN_DELAY_SECONDS}s between requests")

    last_request_time = 0.0

    for n in range(start_n, end_n + 1):
        html_file = RAW_DIR / f"{n}.html"

        # Unified progress every 100 sermons -- fires regardless of which branch below runs,
        # ensuring output in partially-resumed runs where cached/new/404 counts are mixed.
        if n % 100 == 0:
            log(
                f"  Progress: {n}/{end_n} -- "
                f"{downloaded} downloaded, {skipped} cached, {not_found} 404s, {errors} errors"
            )

        if html_file.exists():
            # Resume: skip cached file
            skipped += 1
            continue

        url = BASE_URL.format(n=n)

        # Enforce minimum delay between HTTP requests
        elapsed_since_last = time.time() - last_request_time
        if elapsed_since_last < MIN_DELAY_SECONDS:
            time.sleep(MIN_DELAY_SECONDS - elapsed_since_last)

        try:
            status, data = fetch_url(url)
            last_request_time = time.time()
        except RuntimeError as exc:
            log(f"  ERROR sermon {n}: {exc}")
            log_request(url, -1, 0, f"error: {exc}")
            errors += 1
            continue

        log_request(url, status, len(data), "404-not-in-collection" if status == 404 else "")

        if status == 404:
            not_found += 1
            if not_found % 50 == 0:
                log(f"  Progress: {n}/{end_n} -- {not_found} 404s so far")
            continue

        # Compute SHA-256 and write raw HTML
        sha256 = hashlib.sha256(data).hexdigest()
        html_file.write_bytes(data)
        downloaded += 1

        if downloaded % 100 == 0:
            log(
                f"  Progress: {n}/{end_n} -- {downloaded} downloaded, "
                f"{not_found} 404s, {skipped} cached -- sha256:{sha256[:12]}..."
            )

    log(
        f"Download complete: {downloaded} downloaded, {skipped} already cached, "
        f"{not_found} 404s, {errors} errors"
    )


# ---------------------------------------------------------------------------
# OSIS reference parsing
# ---------------------------------------------------------------------------

# Matches: "Book Name Chapter:Verse[-EndVerse]"
# Examples: "Malachi 3:6", "1 Corinthians 13:1-13", "Song of Solomon 2:4"
_REF_RE = re.compile(r"^(.+?)\s+(\d+):(\d+)(?:-(\d+))?$")

# Matches: "Book Name Chapter:V1, V2[, V3...]"
# Examples: "John 14:16, 17", "1 Corinthians 1:23, 24"
_COMMA_VERSE_RE = re.compile(r"^(.+?)\s+(\d+):([\d]+(?:,\s*\d+)+)$")


def text_to_osis(ref_text: str):
    """
    Convert a plain-text scripture reference to a list of OSIS ID strings.

    "Malachi 3:6"         -> ["Mal.3.6"]
    "John 3:16"           -> ["John.3.16"]
    "Matthew 5:3-12"      -> ["Matt.5.3-Matt.5.12"]
    "John 14:16, 17"      -> ["John.14.16", "John.14.17"]
    "1 Cor 1:23, 24"      -> ["1Cor.1.23", "1Cor.1.24"]

    Returns an empty list if the reference cannot be parsed or the book is
    unrecognised. The caller wraps the result in primary_reference["osis"].
    """
    ref = ref_text.strip()

    # Try simple format: "Book Chapter:Verse[-EndVerse]"
    m = _REF_RE.match(ref)
    if m:
        book_name = m.group(1).strip()
        chapter = m.group(2)
        verse_start = m.group(3)
        verse_end = m.group(4)
        osis_book = BOOK_NAME_TO_OSIS.get(book_name)
        if not osis_book:
            return []
        if verse_end:
            return [f"{osis_book}.{chapter}.{verse_start}-{osis_book}.{chapter}.{verse_end}"]
        return [f"{osis_book}.{chapter}.{verse_start}"]

    # Try comma-separated verses: "Book Chapter:V1, V2"
    m = _COMMA_VERSE_RE.match(ref)
    if m:
        book_name = m.group(1).strip()
        chapter = m.group(2)
        verses_raw = m.group(3)
        osis_book = BOOK_NAME_TO_OSIS.get(book_name)
        if not osis_book:
            return []
        verses = [v.strip() for v in verses_raw.split(",") if v.strip().isdigit()]
        return [f"{osis_book}.{chapter}.{v}" for v in verses]

    return []


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------


def clean_text(text: str) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def parse_sermon_html(html_bytes: bytes, sermon_n: int):
    """
    Parse the raw HTML bytes of one sermon page into an OCD sermon entry dict.
    Returns None if no sermon article is found (structural mismatch or 404 page).
    """
    # The site is Jekyll/UTF-8 but may embed Windows-1252 smart quotes in older sermons
    try:
        html_text = html_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html_text = html_bytes.decode("cp1252", errors="replace")

    soup = BeautifulSoup(html_text, "html.parser")
    article = soup.find("article", class_="sermon")
    if article is None:
        return None

    # --- Title (first h1 inside article) ---
    h1 = article.find("h1")
    if h1 is None:
        return None
    title = clean_text(h1.get_text())
    if not title:
        # Some pages have a structurally correct article but an empty <h1> (site formatting bug).
        # Fall back to the page <title> tag, stripping the site suffix.
        page_title_tag = soup.find("title")
        if page_title_tag:
            page_title = clean_text(page_title_tag.get_text())
            # Strip leading/trailing site name variations: "| Site" or "Title | Site"
            title = re.sub(r"^\s*\|.*$", "", page_title).strip()  # leading pipe = title is blank
            if not title:
                # Try stripping trailing site suffix to get the sermon title
                title = re.sub(r"\s*[|\-]\s*.*$", "", page_title).strip()
        if not title:
            title = f"Sermon No. {sermon_n}"
        log(f"  WARNING: sermon {sermon_n} has empty <h1> -- using fallback title: {title!r}")

    # --- Scripture reference (first blockquote in article) ---
    # Structure: <blockquote>
    #   <p>Quote text</p>
    #   <p><span class="reference">Malachi 3:6</span></p>
    # </blockquote>
    primary_reference = None
    primary_reference_text = None
    first_bq = article.find("blockquote")

    if first_bq is not None:
        ref_span = first_bq.find("span", class_="reference")
        if ref_span is not None:
            ref_text = clean_text(ref_span.get_text())
            primary_reference = {
                "raw": ref_text,
                "osis": text_to_osis(ref_text),
            }

        # Collect quote text from all <p> children that are NOT the reference paragraph
        quote_parts = []
        for p in first_bq.find_all("p", recursive=False):
            if p.find("span", class_="reference"):
                continue  # this is the citation paragraph
            text = clean_text(p.get_text())
            if text:
                quote_parts.append(text)
        if quote_parts:
            primary_reference_text = " ".join(quote_parts)

    # --- Content blocks (body paragraphs, blockquotes, and list items in source order) ---
    # Walk direct children of <article> in order:
    #   - Skip h1 (title already captured)
    #   - Skip first blockquote (scripture reference)
    #   - Include subsequent <p> tags as content blocks
    #   - Include subsequent <blockquote> tags as content blocks (poetry/hymns)
    #   - Flatten direct <ol>/<ul> children to their direct <li> text, as the
    #     sermon schema has string-only content blocks and cannot retain list
    #     container, ordinal, or bullet semantics.
    content_blocks = []
    seen_first_blockquote = False

    for elem in article.children:
        tag = getattr(elem, "name", None)
        if tag is None:
            continue  # NavigableString (whitespace between tags)
        if tag == "h1":
            continue  # title already captured above
        if tag == "blockquote":
            if not seen_first_blockquote:
                seen_first_blockquote = True
                continue  # skip the scripture reference blockquote
            # Inline poetry or hymn -- include as a single content block
            bq_text = clean_text(elem.get_text())
            if bq_text:
                content_blocks.append(bq_text)
        elif tag == "p":
            text = clean_text(elem.get_text())
            if text:
                content_blocks.append(text)
        elif tag in {"ol", "ul"}:
            for item in elem.find_all("li", recursive=False):
                text = clean_text(item.get_text())
                if text:
                    content_blocks.append(text)

    if not content_blocks:
        return None

    # Word count across all content blocks
    all_text = " ".join(content_blocks)
    word_count = len(all_text.split()) if all_text.strip() else 0

    return {
        "collection_id": COLLECTION_ID,
        "sermon_id": f"spurgeon-mtp.{sermon_n}",
        "series": None,
        "title": title,
        "primary_reference": primary_reference,
        "primary_reference_text": primary_reference_text,
        "content_blocks": content_blocks,
        "date_preached": None,
        "location": LOCATION_DEFAULT,
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Parse phase
# ---------------------------------------------------------------------------


def parse_all(dry_run: bool = False) -> list:
    """
    Read cached HTML files from RAW_DIR and parse them into sermon entry dicts.
    If dry_run=True, only process the first 10 files.
    Returns a list of entry dicts sorted by sermon number.
    """
    html_files = sorted(RAW_DIR.glob("*.html"), key=lambda p: int(p.stem))

    if not html_files:
        log(f"ERROR: no HTML files found in {RAW_DIR} -- run with --download-only first")
        sys.exit(1)

    if dry_run:
        html_files = html_files[:10]
        log(f"Dry-run: parsing first {len(html_files)} files only")
    else:
        log(f"Parse phase: {len(html_files)} HTML files in {RAW_DIR}")

    entries = []
    parse_errors = 0
    empty_pages = 0

    for i, html_file in enumerate(html_files, start=1):
        sermon_n = int(html_file.stem)
        try:
            html_bytes = html_file.read_bytes()
            entry = parse_sermon_html(html_bytes, sermon_n)
        except Exception as exc:
            log(f"  ERROR parsing sermon {sermon_n}: {exc}")
            parse_errors += 1
            continue

        if entry is None:
            empty_pages += 1
            continue

        entries.append(entry)

        if i % 500 == 0:
            log(f"  Parsed {i}/{len(html_files)} files ...")

    log(
        f"Parse complete: {len(entries)} entries, "
        f"{empty_pages} empty/structural-mismatch, {parse_errors} errors"
    )
    return entries


# ---------------------------------------------------------------------------
# Quality reporting (PIPE-02)
# ---------------------------------------------------------------------------


def report_quality(entries: list) -> None:
    """Print completeness and quality statistics. Flags entries below thresholds."""
    if not entries:
        log("WARNING: no entries -- cannot report quality")
        return

    total = len(entries)
    words = [e["word_count"] for e in entries]
    sorted_words = sorted(words)

    no_ref = sum(1 for e in entries if e["primary_reference"] is None)
    empty_osis = sum(
        1 for e in entries
        if e["primary_reference"] and not e["primary_reference"]["osis"]
    )
    no_ref_text = sum(1 for e in entries if e.get("primary_reference_text") is None)
    no_content = sum(1 for e in entries if not e["content_blocks"])
    short = sum(1 for e in entries if e["word_count"] < 100)
    zero_words = sum(1 for e in entries if e["word_count"] == 0)

    ref_coverage_pct = (total - no_ref) * 100.0 / total
    osis_parsed_pct = (total - no_ref - empty_osis) * 100.0 / total

    log(f"  Total entries: {total}")
    log(f"  Word count: min={min(words)} median={sorted_words[total // 2]} max={max(words)}")
    log(f"  Scripture ref coverage: {ref_coverage_pct:.1f}% ({total - no_ref}/{total}) -- target >=70%")
    log(f"  OSIS parsed: {osis_parsed_pct:.1f}% ({total - no_ref - empty_osis}/{total})")
    log(f"  OSIS unparseable (ref found but no OSIS): {empty_osis}")
    log(f"  Missing primary_reference_text: {no_ref_text}/{total}")
    log(f"  Missing content_blocks: {no_content}")
    log(f"  Zero word_count: {zero_words}")
    log(f"  Under 100 words (suspicious): {short}")

    if ref_coverage_pct < 70.0:
        log(f"  WARNING: scripture ref coverage {ref_coverage_pct:.1f}% is below 70% target")
    if no_content:
        log(f"  WARNING: {no_content} entries have no content_blocks")
    if zero_words:
        log(f"  WARNING: {zero_words} entries have word_count=0")
    if short:
        log(f"  WARNING: {short} entries are under 100 words")


# ---------------------------------------------------------------------------
# Metadata envelope builder
# ---------------------------------------------------------------------------


def build_meta(config: dict, data_hash: str, processing_date: str) -> dict:
    """Build the OCD metadata envelope from source config + runtime values."""
    raw_contributors = config.get("contributors", [])
    config_notes = config.get("notes")
    provenance_notes = " ".join(
        note for note in (config_notes, LIST_PROJECTION_NOTE) if note
    )
    return {
        "id": config["resource_id"],
        "title": config["title"],
        "author": config["author"],
        "author_birth_year": config.get("author_birth_year"),
        "author_death_year": config.get("author_death_year"),
        "contributors": normalize_contributors(raw_contributors),
        "original_publication_year": config.get("original_publication_year"),
        "language": config["language"],
        "original_language": config.get("original_language"),
        "tradition": config["tradition"],
        "tradition_notes": config.get("tradition_notes"),
        "era": config.get("era"),
        "audience": config.get("audience"),
        "license": config["license"],
        "schema_type": "sermon",
        "schema_version": SCHEMA_VERSION,
        "completeness": "partial",  # ~3,000 of 3,563 total MTP sermons
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": processing_date,
            "source_hash": f"sha256:{data_hash}",
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/spurgeon_mtp.py@{SCRIPT_VERSION}",
            "processing_date": processing_date,
            "notes": provenance_notes,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    global DRY_RUN

    # Guard optional dependency here (not at import time) to keep the module import-safe (PY-06)
    if BeautifulSoup is None:
        print("ERROR: beautifulsoup4 is required. Run: pip install beautifulsoup4==4.14.3")
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description=(
            "Download and parse Spurgeon MTP sermons from The Kingdom Collective "
            "into OCD sermon schema JSON."
        )
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help=(
            "Download HTML files only; do not parse. "
            "Hours-long run -- use run_in_background or a terminal."
        ),
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help=(
            "Parse cached HTML files into JSON output. "
            "Requires --download-only to have run first."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="(With --parse) Parse first 10 files only; print samples; do not write output.",
    )
    args = parser.parse_args()

    # Flag validation
    if args.dry_run and not args.parse:
        print("ERROR: --dry-run requires --parse. Example: --parse --dry-run")
        sys.exit(1)

    # Set module-level DRY_RUN flag (auto-checked: must appear in an if DRY_RUN: block)
    DRY_RUN = args.dry_run

    # Ensure log directory exists
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Determine which phases to run
    # No flags -> run both download and parse in sequence
    both = not args.download_only and not args.parse
    do_download = args.download_only or both
    do_parse = args.parse or both

    start_time = time.time()
    log("spurgeon_mtp.py started")
    log(f"  REPO_ROOT: {REPO_ROOT}")
    log(f"  Mode: {'download+parse' if both else 'download-only' if do_download else 'parse-only'}")

    if DRY_RUN:
        log("  DRY_RUN active: parse first 10 files, no output written")

    # Load source config (needed for parse phase output; skip in dry-run)
    config = None
    if do_parse and not DRY_RUN:
        if not CONFIG_PATH.exists():
            log(f"ERROR: source config not found: {CONFIG_PATH}")
            log("  Create it at sources/sermons/spurgeon-mtp/config.json before running --parse")
            sys.exit(1)
        with open(CONFIG_PATH, encoding="utf-8") as f:
            config = json.load(f)
        validate_config_enums(config, "sermon")

    # --- Download phase ---
    if do_download:
        download_all()
        log("")

    # --- Parse phase ---
    if do_parse:
        entries = parse_all(dry_run=DRY_RUN)
        log("")
        log("Quality report:")
        report_quality(entries)
        log("")

        if DRY_RUN:
            elapsed = time.time() - start_time
            log("--- Sample entries (first 2) ---")
            for entry in entries[:2]:
                print(json.dumps(entry, ensure_ascii=False, indent=2))
            log(f"Dry-run complete -- no files written ({elapsed:.1f}s)")
            return

        # Build output JSON
        processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        data_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
        data_hash = hashlib.sha256(data_bytes).hexdigest()

        meta = build_meta(config, data_hash, processing_date)

        # Clear stale chunk files before writing to prevent orphans on re-runs.
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for _stale in OUTPUT_DIR.glob("sermons-*.json"):
            _stale.unlink()  # standards: log/temp rotation

        # Write per-chunk files. Chunk size of 100 keeps each file ~3 MB for 3,550
        # sermons, well under GitHub's 100 MB hard limit (and 50 MB warning).
        written = write_chunked_output(entries, meta, OUTPUT_DIR, chunk_size=100)
        print(f"Wrote {len(entries)} entries across {len(written)} chunk files in {OUTPUT_DIR}")

    elapsed = time.time() - start_time
    log(f"Done in {elapsed:.1f}s")
    print("SUMMARY: spurgeon_mtp.py complete")


# ---------------------------------------------------------------------------
# Output-chunking helpers
# ---------------------------------------------------------------------------

_NATURAL_SORT_RE = re.compile(r"(\d+)")


def natural_sort_key(value: "str | Path") -> list:
    """Return a sort key that orders strings/paths numerically by embedded integers.

    Plain lexicographic sort puts ``sermons-1001-...`` before ``sermons-101-...``
    and ``sermons-1-...`` in the middle. Natural sort splits on digit runs and
    compares integer values.

    Accepts either a string or a ``pathlib.Path`` (uses the path name).
    """
    name = value.name if isinstance(value, Path) else str(value)
    parts = _NATURAL_SORT_RE.split(name)
    return [int(p) if p.isdigit() else p for p in parts]


def write_chunked_output(
    entries: list[dict],
    meta: dict,
    out_dir: Path,
    chunk_size: int = 100,
) -> list[Path]:
    """Write entries to ``out_dir`` as chunked JSON files.

    Each chunk file has shape ``{"meta": meta, "data": [entries...]}``.
    Files are named ``sermons-<start>-<end>.json`` where ``<start>`` and
    ``<end>`` are **1-indexed** sermon numbers derived from the chunk's
    position in the full entries list. For 3,550 entries at chunk_size=100,
    this produces ``sermons-1-100.json`` through ``sermons-3501-3550.json``
    (36 files).

    The ``<end>`` value reflects the actual last entry in the chunk, so the
    final file correctly shows its true range (e.g. ``sermons-3501-3550.json``
    for a 50-entry last chunk, not ``sermons-3501-3600.json``).

    Args:
        entries: Full list of sermon entries (already sorted by sermon number).
        meta: The meta block to embed in every chunk file.
        out_dir: Directory to write into. Created if it does not exist.
        chunk_size: Max entries per file. Last file may have fewer.

    Returns:
        List of written file Paths in natural-sort order.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    total_chunks = (len(entries) + chunk_size - 1) // chunk_size

    for i in range(total_chunks):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(entries))
        chunk = entries[start_idx:end_idx]

        start_n = start_idx + 1  # 1-indexed
        end_n = end_idx          # 1-indexed inclusive
        filename = f"sermons-{start_n}-{end_n}.json"
        path = out_dir / filename
        obj = {"meta": meta, "data": chunk}
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        written.append(path)

    return sorted(written, key=natural_sort_key)


if __name__ == "__main__":
    main()
