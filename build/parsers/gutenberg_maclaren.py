"""gutenberg_maclaren.py
Parse Alexander Maclaren's "Expositions of Holy Scripture" from Project Gutenberg.

15 volumes covering Genesis through the Epistles.  Each volume is a collection
of verse-by-verse exposition sermons preached at Union Chapel, Manchester.
Maclaren died 1910 -- all text is public domain.

Sources (raw/gutenberg/sermons/maclaren/):
  pg7069.txt   -- Genesis, Exodus, Leviticus and Numbers
  pg8068.txt   -- Deuteronomy to 2 Kings VII
  pg7883.txt   -- 2 Kings VIII-End, Chronicles, Ezra, Nehemiah, Esther, Job, Proverbs, Ecclesiastes
  pg7925.txt   -- Psalms
  pg8069.txt   -- Isaiah and Jeremiah
  pg15836.txt  -- Ezekiel, Daniel, Minor Prophets, Matthew I-VIII
  pg7351.txt   -- Matthew IX-XXVIII
  pg8071.txt   -- Mark
  pg8200.txt   -- Luke
  pg8070.txt   -- John I-XIV
  pg8381.txt   -- John XV-XXI
  pg8397.txt   -- The Acts
  pg13601.txt  -- Romans and Corinthians (to 2 Cor V)
  pg21190.txt  -- 2 Corinthians, Galatians, Philippians, Colossians, Thessalonians, 1 Timothy
  pg24674.txt  -- Ephesians, 1 Peter and 1 John

Output (data/sermons/):
  maclaren-expositions.json  -- All 15 volumes, one entry per exposition sermon

Schema: sermon (schemas/v1/sermon.schema.json)
Tradition: reformed, baptist, evangelical

Usage:
    py -3 build/parsers/gutenberg_maclaren.py --dry-run
    py -3 build/parsers/gutenberg_maclaren.py
    py -3 build/parsers/gutenberg_maclaren.py --volume 7069    (single volume)
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib._generated_enums import (  # noqa: E402
    SERMON__META__AUDIENCE,
    SERMON__META__COMPLETENESS,
    SERMON__META__ERA,
    SERMON__META__PROVENANCE__PROCESSING_METHOD,
    SERMON__META__TRADITION,
)
from build.lib.text_utils import compute_source_hash, smart_title  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib.pg_inline_markup import (  # noqa: E402
    append_pg_inline_markup_note,
    decode_pg_inline_markup,
)

RAW_DIR = REPO_ROOT / "raw" / "gutenberg" / "sermons" / "maclaren"
OUTPUT_DIR = REPO_ROOT / "data" / "sermons"
OUTPUT_FILE = OUTPUT_DIR / "maclaren-expositions.json"
LOG_FILE = Path(__file__).resolve().parent / "gutenberg_maclaren.log"

SCHEMA_VERSION = "2.1.0"
PROCESSING_SCRIPT_VERSION = "build/parsers/gutenberg_maclaren.py@v1.0.0"
DOWNLOAD_DATE = "2026-04-15"
USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
REQUEST_DELAY = 2.0  # seconds between requests (robots.txt: no crawl-delay; 2s is courteous)

# PG markers (same as gutenberg_theology.py)
PG_START_RE = re.compile(r"\*\*\*\s*START OF", re.IGNORECASE)
PG_END_RE = re.compile(r"\*\*\*\s*END OF", re.IGNORECASE)

# Volume catalogue: (pg_id, series_label_for_output)
# Ordered OT -> NT
MACLAREN_VOLUMES = [
    ("7069",  "Genesis, Exodus, Leviticus and Numbers"),
    ("8068",  "Deuteronomy, Joshua, Judges, Ruth, Samuel and Kings (to 2 Kings VII)"),
    ("7883",  "2 Kings VIII-End, Chronicles, Ezra, Nehemiah, Esther, Job, Proverbs and Ecclesiastes"),
    ("7925",  "Psalms"),
    ("8069",  "Isaiah and Jeremiah"),
    ("15836", "Ezekiel, Daniel and the Minor Prophets; Matthew I-VIII"),
    ("7351",  "Matthew IX-XXVIII"),
    ("8071",  "Mark"),
    ("8200",  "Luke"),
    ("8070",  "John I-XIV"),
    ("8381",  "John XV-XXI"),
    ("8397",  "The Acts"),
    ("13601", "Romans and Corinthians (to 2 Corinthians V)"),
    ("21190", "2 Corinthians, Galatians, Philippians, Colossians, Thessalonians and 1 Timothy"),
    ("24674", "Ephesians, 1 Peter and 1 John"),
]

# Download URL patterns (tried in order; {pg_id} substituted at call time)
PG_URL_PATTERNS = [
    "https://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt",
    "https://www.gutenberg.org/files/{pg_id}/{pg_id}-0.txt",
    "https://www.gutenberg.org/files/{pg_id}/{pg_id}.txt",
]
RETRY_DELAYS = (2.0, 4.0, 8.0)      # exponential backoff for transient failures
RETRY_STATUS_CODES = frozenset([429, 500, 502, 503])

for _t in ["reformed", "baptist", "evangelical"]:
    assert _t in SERMON__META__TRADITION, f"invalid tradition {_t!r}"
assert "modern" in SERMON__META__ERA, "invalid era 'modern'"
assert "lay" in SERMON__META__AUDIENCE, "invalid audience 'lay'"
assert "full" in SERMON__META__COMPLETENESS, "invalid completeness 'full'"
assert "automated" in SERMON__META__PROVENANCE__PROCESSING_METHOD, "invalid processing_method 'automated'"

# Prose-paren prefixes that should NOT be treated as scripture references
_PROSE_PAREN_PREFIXES = ("(As ", "(In ", "(See ", "(Cf.", "(Note", "(From")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(message: str, log_lines: list) -> None:
    """Print to console (ASCII-safe) and append to log list."""
    safe = message.encode("ascii", errors="replace").decode("ascii")
    print(safe)
    log_lines.append(message)




def strip_pg_wrapper(text: str) -> list:
    """Strip PG header/footer. Returns body lines. Raises ValueError if markers not found."""
    lines = text.splitlines()
    start_idx = end_idx = None
    for i, line in enumerate(lines):
        if PG_START_RE.search(line) and start_idx is None:
            start_idx = i
        if PG_END_RE.search(line):
            end_idx = i
            break
    if start_idx is None or end_idx is None:
        raise ValueError("Could not find PG *** START OF / *** END OF markers")
    return lines[start_idx + 1 : end_idx]


def word_count(blocks: list) -> int:
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_pg_text(pg_id: str, dest_path: Path, log_lines: list) -> bool:
    """Download a PG plain-text file. Skips if already cached. Returns True on success.

    Retries transient HTTP errors (429, 500, 502, 503) and network timeouts using
    exponential backoff (2s / 4s / 8s) before falling through to the next URL pattern.
    """
    if dest_path.exists() and dest_path.stat().st_size > 0:
        log(f"    Cached: {dest_path.name}", log_lines)
        return True

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    for url in [p.format(pg_id=pg_id) for p in PG_URL_PATTERNS]:
        log(f"    GET {url}", log_lines)
        delays = [0.0, *RETRY_DELAYS]  # first attempt: no pre-delay
        for attempt, delay in enumerate(delays):
            if delay:
                log(f"    Retry {attempt}/{len(RETRY_DELAYS)} after {delay:.0f}s...", log_lines)
                time.sleep(delay)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as response:
                    raw = response.read()
                dest_path.write_bytes(raw)
                log(f"    Saved {dest_path.name} ({len(raw):,} bytes)", log_lines)
                time.sleep(REQUEST_DELAY)
                return True
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_STATUS_CODES:
                    log(f"    HTTP {exc.code} (transient) for {url}", log_lines)
                    # fall through to next delay (retry same URL)
                else:
                    log(f"    HTTP {exc.code} (permanent) for {url}", log_lines)
                    break  # non-retryable: skip to next URL pattern
            except Exception as exc:
                log(f"    WARN: {url} failed: {exc}", log_lines)
                # fall through to next delay (retry on timeout / network error)

    log(f"    ERROR: All URLs failed for PG#{pg_id}", log_lines)
    return False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def blocks_from_lines(body_lines: list) -> list:
    """Split body lines into paragraphs (blank-line-separated blocks).

    Each returned item is a string: lines within the block joined with a space
    and whitespace-normalised.
    """
    blocks = []
    current: list = []
    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            if current:
                text = " ".join(current)
                text = " ".join(text.split())
                blocks.append(decode_pg_inline_markup(text))
                current = []
        else:
            current.append(stripped)
    if current:
        text = " ".join(current)
        blocks.append(decode_pg_inline_markup(" ".join(text.split())))
    return blocks


def is_all_caps_heading(block: str) -> bool:
    """Heuristic: return True if block looks like an all-caps exposition heading.

    Maclaren's exposition headings follow the pattern:
      SOME TITLE WORDS (Book chapter. verse)

    They are:
    - Short (at most ~12 words before the parenthetical reference)
    - Uppercase (> 85% of alphabetic chars are upper)
    - Not starting with a quote character (scripture quotations are excluded)
    """
    s = block.strip()

    # Scripture quotations start with a quote character -- not a heading
    if s and s[0] in ("'", "\u2018", "\u2019", '"', "\u201c", "\u201d"):
        return False

    # Remove trailing parenthetical reference (e.g., " (John xv. 1-4)")
    s_no_paren = re.sub(r"\s*\([^)]+\)\s*$", "", s).strip()

    if not s_no_paren or len(s_no_paren) < 5:
        return False

    # Headings are short (< 13 words) -- long blocks are content paragraphs
    if len(s_no_paren.split()) > 12:
        return False

    # Alpha character count and uppercase ratio
    alpha = [c for c in s_no_paren if c.isalpha()]
    if len(alpha) < 4:
        return False

    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    return upper_ratio >= 0.85


def _paren_from_heading(heading_block: str) -> str | None:
    """Extract parenthetical scripture ref from heading: 'TITLE (Book chap. verse)'."""
    m = re.search(r"\(([^)]+)\)", heading_block)
    return m.group(1).strip() if m else None


def _dash_ref_from_content(content_blocks: list) -> str | None:
    """Extract scripture ref from the first few content blocks.

    The scripture quotation sometimes spans multiple blank-line-separated blocks.
    Check up to the first 3 blocks. Two patterns tried in order; first match wins.

    Pattern A (dash-prefixed): handles '--', '-', and U+2014 (em dash) separators,
      digit-prefixed book names (1 Samuel, 2 Peter), and (R.V.) annotation suffix.
    Pattern B (inline, no sep): handles refs after sentence-terminal punctuation
      with no dash, e.g. 'Thee! GENESIS xvii. 18.'
    """
    for block in content_blocks[:3]:
        # Strip (R.V.) / (A.V.) / (R. V.) / (R.V. margin) annotations before
        # Pattern A -- they trail the verse range and defeat the $ anchor.
        normalised = re.sub(r"\s*\([RA]\.\s*V\.[^)]*\)", "", block)

        # Pattern A: dash or em-dash separator
        m = re.search(
            r"(?:--?|\u2014)\s*([\dA-Z][a-zA-Z .;,:\d\u2013\u2014\-]+?)\.?\s*$",
            normalised,
        )
        if m:
            ref = m.group(1).strip().rstrip(".")
            if any(c.isdigit() for c in ref) and any(c.isalpha() for c in ref):
                return ref

        # Pattern B (fallback): inline ref after sentence-terminal punctuation.
        # Guard: requires [.!?] + optional closing quote + space immediately
        # before the book name, to avoid false-positives on ALL-CAPS prose words.
        m2 = re.search(
            r"[.!?][\u201d\u2019\"']?\s+((?:\d\s+)?[A-Z][A-Z.]+\s+[ivxlcIVXLC]+\.?\s*[\d][a-zA-Z0-9 .,;:-]*?)\.?\s*$",
            block,
        )
        if m2:
            ref = m2.group(1).strip().rstrip(".")
            if any(c.isdigit() for c in ref) and any(c.isalpha() for c in ref):
                return ref

    return None


def extract_scripture_raw(
    heading_block: str,
    standalone_ref: str | None,
    content_blocks: list,
) -> str | None:
    """Extract the scripture reference for an exposition.

    Priority:
      1. Parenthetical in the heading: "TITLE (Genesis i. 26--ii. 3)"
      2. Standalone parenthetical block: block containing only "(Genesis i. 26--ii. 3)"
      3. '--BOOK ref.' at end of the scripture quotation (first few content blocks)
    """
    return (
        _paren_from_heading(heading_block)
        or standalone_ref
        or _dash_ref_from_content(content_blocks)
    )


def parse_maclaren_volume(
    pg_id: str,
    series: str,
    body_lines: list,
    start_sermon_num: int,
    log_lines: list,
) -> list:
    """Parse one Maclaren volume into a list of sermon entry dicts.

    Algorithm:
      1. Split body into paragraph blocks.
      2. Find all-caps blocks as potential exposition headings.
      3. Gather content blocks between consecutive headings.
      4. Keep entries where content word count >= 100 (filters out ToC entries,
         book-name dividers like "GENESIS", and "CONTENTS" header).
      5. Skip single-word headings (e.g., "PSALMS", "GENESIS").
    """
    blocks = blocks_from_lines(body_lines)

    # Identify heading block indices
    heading_indices = [i for i, b in enumerate(blocks) if is_all_caps_heading(b)]
    if not heading_indices:
        log(f"  WARNING: No all-caps headings found in PG#{pg_id}", log_lines)
        return []

    entries = []
    sermon_num = start_sermon_num

    for h_pos, hi in enumerate(heading_indices):
        next_hi = (
            heading_indices[h_pos + 1] if h_pos + 1 < len(heading_indices) else len(blocks)
        )
        content_blocks = blocks[hi + 1 : next_hi]
        heading = blocks[hi]

        # --- Detect and consume standalone parenthetical reference block ---
        # Many volumes put the scripture ref on its own line after the title:
        #   Block 0 (heading): "THE VISION OF CREATION"
        #   Block 1 (standalone ref): "(Genesis i. 26--ii. 3)"
        #   Block 2+ (content): "'And God said...'" + exposition paragraphs
        #
        # Identify: block <= 80 chars, starts with '(' and ends with ')',
        # and does NOT start with common prose phrases like "(As", "(In", "(See".
        standalone_ref: str | None = None
        if content_blocks:
            fb = content_blocks[0].strip()
            if (
                fb.startswith("(")
                and fb.endswith(")")
                and len(fb) <= 80
                and not any(fb.startswith(p) for p in _PROSE_PAREN_PREFIXES)
            ):
                standalone_ref = fb[1:-1].strip()
                content_blocks = content_blocks[1:]

        # Recompute word count after potentially removing the standalone ref block
        total_words = word_count(content_blocks)

        # Skip ToC entries, book dividers, etc. (< 100 words of content)
        if total_words < 100:
            continue

        # Strip parenthetical reference from title
        raw_title = re.sub(r"\s*\([^)]+\)\s*$", "", heading).strip()

        # Skip single-word book-name dividers (GENESIS, PSALMS, CONTENTS, etc.)
        if len(raw_title.split()) <= 1:
            continue

        # Skip book-level ToC sections ("THE BOOK OF DEUTERONOMY" etc.) — these appear
        # as ALL-CAPS section headings whose "content" is just a dense ToC listing of
        # sermon titles; they pass the 100-word threshold but are not sermons.
        if re.match(r"^THE (?:FIRST |SECOND |THIRD )?BOOK OF ", raw_title):
            continue
        # Skip volume/section intros whose content starts with "Vols." (e.g. "ST. JOHN")
        if content_blocks and content_blocks[0].strip().startswith("Vols."):
            continue

        # Title-case: e.g. "THE VISION OF CREATION" -> "The Vision of Creation"
        title = smart_title(raw_title)

        # Scripture reference (priority: heading paren > standalone block > --REF. in first blocks)
        scripture_raw = extract_scripture_raw(heading, standalone_ref, content_blocks)

        entry = {
            "collection_id": "maclaren-expositions",
            "sermon_id": str(sermon_num),
            "series": series,
            "title": title,
            "content_blocks": content_blocks,
            "word_count": total_words,
        }
        if scripture_raw:
            entry["primary_reference"] = {"raw": scripture_raw, "osis": []}
            entry["primary_reference_text"] = None
        entries.append(entry)
        sermon_num += 1

    return entries


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(entries: list, label: str, log_lines: list) -> None:
    total = len(entries)
    with_ref = sum(1 for e in entries if e.get("primary_reference"))
    ref_pct = round(100 * with_ref / total) if total else 0
    min_wc = min((e["word_count"] for e in entries), default=0)
    max_wc = max((e["word_count"] for e in entries), default=0)
    avg_wc = sum(e["word_count"] for e in entries) // total if total else 0
    log(
        f"  {label}: {total} expositions, {with_ref}/{total} ({ref_pct}%) with scripture ref, "
        f"wc min={min_wc} max={max_wc} avg={avg_wc}",
        log_lines,
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


def run(dry_run: bool, target_volume: str | None, log_lines: list) -> bool:
    """Download, parse and write maclaren-expositions.json. Returns True on success."""
    start = time.time()

    volumes_to_run = (
        [v for v in MACLAREN_VOLUMES if v[0] == target_volume]
        if target_volume
        else MACLAREN_VOLUMES
    )

    if not volumes_to_run:
        log(f"ERROR: Volume PG#{target_volume} not in catalogue", log_lines)
        return False

    log("\n=== Maclaren Expositions of Holy Scripture ===", log_lines)
    log(f"  Volumes: {len(volumes_to_run)} of {len(MACLAREN_VOLUMES)}", log_lines)

    # --- Step 1: Download all volumes ---
    # A single volume failure is logged and skipped; remaining volumes continue.
    log("\n-- Downloading --", log_lines)
    hashes: dict = {}
    failed_download: list = []
    for pg_id, series in volumes_to_run:
        dest = RAW_DIR / f"pg{pg_id}.txt"
        ok = download_pg_text(pg_id, dest, log_lines)
        if not ok:
            log(f"  ERROR: Could not download PG#{pg_id} -- skipping", log_lines)
            failed_download.append(pg_id)
            continue
        hashes[pg_id] = compute_source_hash(dest)
        log(f"    Hash PG#{pg_id}: {hashes[pg_id]}", log_lines)

    if failed_download:
        log(
            f"\n  WARNING: {len(failed_download)} volume(s) failed to download: {failed_download}",
            log_lines,
        )

    # Continue only with successfully downloaded volumes
    volumes_to_run = [(pg_id, s) for pg_id, s in volumes_to_run if pg_id not in set(failed_download)]
    if not volumes_to_run:
        log("  ERROR: No volumes available to parse -- aborting", log_lines)
        return False

    # --- Step 2: Parse all volumes ---
    log("\n-- Parsing --", log_lines)
    all_entries: list = []
    serial = 1
    failed_parse: list = []

    for i, (pg_id, series) in enumerate(volumes_to_run, 1):
        src = RAW_DIR / f"pg{pg_id}.txt"
        log(f"\n  [{i}/{len(volumes_to_run)}] PG#{pg_id} -- {series}", log_lines)

        # Read with UTF-8 fallback to latin-1
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = src.read_text(encoding="latin-1")

        try:
            body_lines = strip_pg_wrapper(text)
        except ValueError as exc:
            log(f"  ERROR: strip_pg_wrapper failed -- {exc} -- skipping", log_lines)
            failed_parse.append(pg_id)
            continue

        log(f"  Body lines: {len(body_lines)}", log_lines)

        vol_entries = parse_maclaren_volume(pg_id, series, body_lines, serial, log_lines)
        if not vol_entries:
            log(f"  WARNING: Zero expositions extracted from PG#{pg_id}", log_lines)
        print_quality_stats(vol_entries, f"PG#{pg_id}", log_lines)

        all_entries.extend(vol_entries)
        serial += len(vol_entries)

    log(f"\n-- Total expositions: {len(all_entries)} --", log_lines)

    if all_entries:
        print_quality_stats(all_entries, "Combined", log_lines)

        # Warn on entries with empty content_blocks or zero word_count
        bad = [e for e in all_entries if not e["content_blocks"] or e["word_count"] == 0]
        if bad:
            log(f"  WARNING: {len(bad)} entries with empty content_blocks", log_lines)
        no_ref = [e for e in all_entries if not e.get("primary_reference")]
        if no_ref:
            log(
                f"  NOTE: {len(no_ref)} entries without primary_reference "
                f"(normal for a small number of expositions)",
                log_lines,
            )

    any_failure = bool(failed_download or failed_parse)

    if dry_run:
        log("\nDRY RUN -- first 3 entries:", log_lines)
        for e in all_entries[:3]:
            log(
                f"  [{e['sermon_id']}] \"{e['title']}\" | series={e['series'][:40]} "
                f"| wc={e['word_count']} | ref={e.get('primary_reference', {}).get('raw', 'None')}",
                log_lines,
            )
        elapsed = time.time() - start
        log(f"DRY RUN -- no files written (elapsed: {elapsed:.1f}s)", log_lines)
        return not any_failure

    # --- Step 3: Build combined hash ---
    # Hash all volume hashes together for the multi-source provenance record
    hash_str = hashlib.sha256(
        "".join(hashes[pg_id] for pg_id, _ in volumes_to_run).encode()
    ).hexdigest()
    combined_hash = f"sha256:{hash_str}"

    # --- Step 4: Build source_url and volume hash notes ---
    # Schema requires source_url as a single string; use canonical PG URL for the first volume.
    # All 15 volume URLs and hashes are documented in raw/gutenberg/sermons/PG_SERMON_INVENTORY.md.
    primary_pg_id = volumes_to_run[0][0]
    source_url = f"https://www.gutenberg.org/cache/epub/{primary_pg_id}/pg{primary_pg_id}.txt"
    # Build per-volume hash notes string for provenance
    volume_hash_notes = "; ".join(
        f"pg{pg_id}.txt={hashes[pg_id]}" for pg_id, _ in volumes_to_run
    )

    # --- Step 5: Build meta envelope ---
    meta = {
        "id": "maclaren-expositions",
        "title": "Expositions of Holy Scripture",
        "author": "Alexander Maclaren",
        "author_id": "maclaren-alexander",
        "author_birth_year": 1826,
        "author_death_year": 1910,
        "contributors": [],
        "original_publication_year": 1892,
        "language": "en",
        "original_language": "en",
        "tradition": ["reformed", "baptist", "evangelical"],
        "tradition_notes": (
            "Alexander Maclaren (1826-1910) was a Baptist minister who served at Union Chapel, "
            "Manchester, from 1858 to 1903. His Expositions of Holy Scripture (serialised 1892-1910, "
            "Hodder & Stoughton) covers most of the Bible in detailed verse-by-verse expository "
            "sermons. Maclaren was president of the Baptist World Alliance in 1905. His theology "
            "is broadly evangelical and Reformed, emphasising scripture, grace, and the believer's "
            "union with Christ."
        ),
        "era": "modern",
        "audience": "lay",
        "license": "public-domain",
        "schema_type": "sermon",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": source_url,
            "source_format": "plain text (UTF-8)",
            "source_edition": (
                "Project Gutenberg digitisations of 15 volumes of Expositions of Holy Scripture "
                "(Hodder & Stoughton, 1892-1910). All 15 PG IDs listed in "
                "raw/gutenberg/sermons/PG_SERMON_INVENTORY.md."
            ),
            "download_date": DOWNLOAD_DATE,
            "source_hash": combined_hash,
            "processing_method": "automated",
            "processing_script_version": PROCESSING_SCRIPT_VERSION,
            "processing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "notes": append_pg_inline_markup_note(
                "15 volumes covering Genesis through the Pastoral and General Epistles "
                "(PG#7069, 8068, 7883, 7925, 8069, 15836, 7351, 8071, 8200, 8070, 8381, "
                "8397, 13601, 21190, 24674). "
                "Parsed by all-caps exposition heading detection. Scripture references extracted "
                "from parenthetical in heading or --REF. marker in scripture quotation block. "
                "word_count threshold >= 100 filters ToC entries and section dividers. "
                f"Volume hashes: {volume_hash_notes}"
            ),
        },
    }

    # --- Step 6: Write output ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = {"meta": meta, "data": all_entries}

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start
    log(f"\nWritten: {OUTPUT_FILE}", log_lines)
    log(f"  Total entries: {len(all_entries)}", log_lines)
    log(f"  Elapsed: {elapsed:.1f}s", log_lines)
    if any_failure:
        log(
            f"  WARNING: Completed with failures -- "
            f"download={failed_download} parse={failed_parse}",
            log_lines,
        )
    return not any_failure


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse PG Maclaren Expositions to sermon JSON"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download but do not write output files",
    )
    parser.add_argument(
        "--volume",
        metavar="PG_ID",
        help="Process only this PG volume (e.g. 7069). Default: all 15.",
    )
    args = parser.parse_args()

    log_lines: list = []
    try:
        success = run(dry_run=args.dry_run, target_volume=args.volume, log_lines=log_lines)
    except Exception as exc:
        log_lines.append(f"FATAL: Unhandled exception: {exc}")
        success = False
    finally:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
