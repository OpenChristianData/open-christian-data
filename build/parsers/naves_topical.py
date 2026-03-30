"""naves_topical.py
Parser for Nave's Topical Bible -- SWORD zLD binary module.

Confirmed format (binary inspection Task 2, 2026-03-30):
  dict.idx  -- 8-byte entries: struct.unpack('<II') -> (offset_in_dat, size)
  dict.dat  -- variable-length entries: TOPICNAME\r\n + 8 bytes ->
               struct.unpack('<II') -> (block_num, entry_in_block)
  dict.zdx  -- 8-byte entries: struct.unpack('<II') -> (zdt_offset, compressed_size)
  dict.zdt  -- concatenated zlib-compressed blocks

Block internal structure (confirmed by inspection):
  Bytes 0..7: (count:4)(data_start:4) header
  Bytes 8..(8 + count*8 - 1): count * (eoff:4, esz:4) index
    eoff = size of this entry (the gap to the next entry's start)
    esz  = cumulative size from this entry to end of block (not used for slicing)
  Data section starts at offset data_start; entry i starts at the cumulative
  sum of eoff[0..i-1] bytes into the data section.

TEI XML content format:
  <entryFree n="TOPICNAME">
  <def>
  <lb/>&#x2192; Subtopic label <ref osisRef="Exod.1.1">Ex 1:1</ref>
  </def>
  </entryFree>
  - U+2192 (&#x2192;, UTF-8 e2 86 92) marks the start of each subtopic line
  - <ref osisRef="...">display</ref> -- scripture reference
  - <ref target="Nave:TOPICNAME">...</ref> -- cross-reference to another topic
  - Entries with no arrow markers: one subtopic with label="" containing all refs

Usage:
    py -3 build/parsers/naves_topical.py --dry-run
    py -3 build/parsers/naves_topical.py --dry-run --limit 10
    py -3 build/parsers/naves_topical.py
"""

import argparse
import hashlib
import json
import logging
import re
import struct
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "naves_topical" / "modules" / "lexdict" / "zld" / "nave"
OUTPUT_DIR = REPO_ROOT / "data" / "topical-reference" / "naves"
LOG_FILE = Path(__file__).parent / "naves_topical.log"
REQUEST_LOG = REPO_ROOT / "research" / "reference" / "request_log.csv"

INDEX_ID = "naves-topical-bible"
SCRIPT_VERSION = "v1.0.0"
SCHEMA_VERSION = "2.1.0"

# Unicode arrow that marks subtopic line starts (U+2192, UTF-8 encoded)
ARROW = "\u2192"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Configure logging to both file and stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# ID helpers (CODING_DEFAULTS Rule 45)
# ---------------------------------------------------------------------------

def slugify(text: str, max_len: int = 80) -> str:
    """
    Convert a topic name to a URL-safe slug.
    - Lowercased
    - Non-ASCII normalised/dropped via ASCII-safe encode
    - Punctuation replaced with hyphens
    - Consecutive hyphens collapsed
    - Truncated to max_len
    """
    import unicodedata
    # Normalise Unicode to ASCII-compatible form, then drop non-ASCII
    normalised = unicodedata.normalize("NFKD", text)
    ascii_bytes = normalised.encode("ascii", errors="ignore")
    slug = ascii_bytes.decode("ascii").lower()
    # Replace non-alphanumeric runs with a single hyphen
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:max_len]


def make_unique_id(base: str, seen: set) -> str:
    """
    Return base if not in seen, otherwise base-2, base-3, etc.
    Adds the chosen ID to seen.
    """
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    seen.add(candidate)
    return candidate


# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

# Match only scripture refs (those with osisRef attribute)
_OSIS_REF_RE = re.compile(r'<ref\s+osisRef="([^"]+)">([^<]*)</ref>')

# Match only cross-refs (those with target="Nave:..." attribute)
_CROSS_REF_RE = re.compile(r'<ref\s+target="Nave:([^"]+)">')


def extract_osis_refs(entry_xml: str) -> list:
    """
    Extract all scripture references from an entryFree XML string.

    Returns a list of dicts: [{raw: str, osis: [str]}]
    Only processes <ref osisRef="..."> elements; cross-ref targets are excluded.
    """
    refs = []
    for m in _OSIS_REF_RE.finditer(entry_xml):
        osis_str = m.group(1).strip()
        raw_text = m.group(2).strip()
        refs.append({"raw": raw_text, "osis": [osis_str]})
    return refs


def extract_cross_refs(entry_xml: str) -> list:
    """
    Extract all cross-reference topic names from an entryFree XML string.

    Returns a list of topic name strings (Nave: prefix stripped).
    Only processes <ref target="Nave:..."> elements.
    """
    return [m.group(1).strip() for m in _CROSS_REF_RE.finditer(entry_xml)]


def parse_subtopics(entry_xml: str) -> list:
    """
    Parse an entryFree XML string into a list of subtopic dicts.

    Each subtopic: {label: str, references: [{raw, osis}]}

    Rules:
    - If the entry contains U+2192 arrow markers (either as the literal Unicode
      character or as the HTML entity &#x2192;), each arrow introduces a new
      subtopic. The text immediately after the arrow (before the first <ref>)
      is the subtopic label.
    - If there are no arrow markers, the entry is treated as one subtopic
      with label="" containing all scripture refs.
    - Subtopics that contain only cross-refs (no osisRef) produce an entry with
      references=[] (they are still emitted so the cross-ref can be captured
      elsewhere; callers may filter these out).
    - Pure cross-ref-only entries (no arrows, no osisRef) return [].
    """
    import html as _html

    # Unescape HTML entities so &#x2192; becomes the actual U+2192 character.
    # This handles both test fixtures (HTML entities) and real data (raw UTF-8).
    entry_xml = _html.unescape(entry_xml)

    # Extract the <def> block
    def_match = re.search(r"<def>(.*?)</def>", entry_xml, re.DOTALL)
    if not def_match:
        return []
    content = def_match.group(1)

    if ARROW not in content:
        # No subtopic divisions -- check if there are any scripture refs at all
        refs = extract_osis_refs(entry_xml)
        if not refs:
            # Cross-ref only or empty -- return empty list
            return []
        return [{"label": "", "references": refs}]

    # Split on arrow markers. Each segment after splitting starts a new subtopic.
    # The <lb/> tags precede each arrow; we split on the arrow itself.
    segments = content.split(ARROW)

    subtopics = []
    for seg in segments[1:]:  # segments[0] is text before the first arrow (preamble)
        # Extract the subtopic label: text before the first <ref> or <lb/>
        # Strip leading/trailing whitespace
        seg_stripped = seg.strip()

        # Label = text up to the first tag or end of line
        # In practice: "Lineage of <ref ...>" -> label = "Lineage of"
        label_match = re.match(r"^([^<]*)", seg_stripped)
        label = label_match.group(1).strip() if label_match else ""
        # Remove trailing punctuation from label (colons, semicolons, commas)
        label = label.rstrip(";:,").strip()

        # Collect scripture refs within this segment only
        refs = []
        for m in _OSIS_REF_RE.finditer(seg):
            osis_str = m.group(1).strip()
            raw_text = m.group(2).strip()
            refs.append({"raw": raw_text, "osis": [osis_str]})

        subtopics.append({"label": label, "references": refs})

    return subtopics


# ---------------------------------------------------------------------------
# Block reader
# ---------------------------------------------------------------------------

def load_block_cache() -> dict:
    """Preload all compressed blocks into a dict keyed by block number."""
    zdx_path = RAW_DIR / "dict.zdx"
    zdt_path = RAW_DIR / "dict.zdt"

    zdx_data = zdx_path.read_bytes()
    zdt_data = zdt_path.read_bytes()

    n_blocks = len(zdx_data) // 8
    cache = {}
    for i in range(n_blocks):
        zdt_offset, comp_size = struct.unpack("<II", zdx_data[i * 8 : i * 8 + 8])
        comp_bytes = zdt_data[zdt_offset : zdt_offset + comp_size]
        try:
            plain = zlib.decompress(comp_bytes)
        except zlib.error as exc:
            logging.warning("Block %d: decompression failed: %s", i, exc)
            plain = b""
        cache[i] = plain
    return cache


def get_entry_from_block(plain: bytes, entry_in_block: int, topic: str) -> str:
    """
    Extract one entry's XML text from a decompressed block.

    Block layout:
      bytes 0..3: count (number of entries in block)
      bytes 4..7: data_start (offset where entry data begins)
      bytes 8..8+count*8-1: index of (eoff, esz) per entry
        eoff = size of this entry (cumulative start = sum of previous eoffs)
        esz  = cumulative size from this entry to end (not used for slicing)
      data region starts at offset data_start

    Returns the decoded entry XML string, or "" on failure.
    """
    if len(plain) < 8:
        logging.warning("  Block too short for header (topic=%s)", topic)
        return ""

    count, data_start = struct.unpack("<II", plain[0:8])

    if entry_in_block >= count:
        logging.warning(
            "  entry_in_block=%d >= count=%d (topic=%s) -- using regex fallback",
            entry_in_block, count, topic,
        )
        return _regex_extract(plain, topic)

    if len(plain) < 8 + count * 8:
        logging.warning("  Block index truncated (topic=%s)", topic)
        return ""

    # Compute the start position of the requested entry
    start_in_data = 0
    for i in range(entry_in_block):
        eoff, _ = struct.unpack("<II", plain[8 + i * 8 : 8 + i * 8 + 8])
        start_in_data += eoff

    # The size of the requested entry is its own eoff
    entry_eoff, _ = struct.unpack("<II", plain[8 + entry_in_block * 8 : 8 + entry_in_block * 8 + 8])

    # Handle last entry: eoff value may be invalid for the final entry in some blocks.
    # Use regex fallback to find the true end.
    abs_start = data_start + start_in_data
    if entry_eoff > len(plain) or abs_start + entry_eoff > len(plain):
        # Likely the last entry with a corrupted eoff -- read to end of block
        entry_bytes = plain[abs_start:]
    else:
        entry_bytes = plain[abs_start : abs_start + entry_eoff]

    try:
        return entry_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        logging.warning("  Decode error (topic=%s): %s", topic, exc)
        return ""


def _regex_extract(plain: bytes, topic: str) -> str:
    """
    Fallback: find the entry for `topic` by scanning all entryFree tags in the block.
    Used when block indexing fails (entry_in_block >= count).
    """
    try:
        text = plain.decode("utf-8", errors="replace")
    except Exception:
        return ""

    pattern = re.compile(
        r'<entryFree[^>]*n="' + re.escape(topic) + r'">(.*?)</entryFree>',
        re.DOTALL,
    )
    m = pattern.search(text)
    if m:
        return m.group(0)
    # If exact match fails, try case-insensitive
    pattern_ci = re.compile(
        r'<entryFree[^>]*n="' + re.escape(topic) + r'">(.*?)</entryFree>',
        re.DOTALL | re.IGNORECASE,
    )
    m_ci = pattern_ci.search(text)
    if m_ci:
        return m_ci.group(0)
    logging.warning("  Regex fallback: topic %r not found in block", topic)
    return ""


# ---------------------------------------------------------------------------
# Meta builder
# ---------------------------------------------------------------------------

def _get_download_date() -> str:
    """
    Read download date from research/reference/request_log.csv.
    Looks for the row containing 'Nave.zip' and returns timestamp[:10].
    Falls back to today's date if not found.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not REQUEST_LOG.exists():
        logging.warning("request_log.csv not found; using today as download_date")
        return today

    with open(REQUEST_LOG, encoding="utf-8") as fh:
        for line in fh:
            if "Nave.zip" in line:
                parts = line.split(",")
                if parts:
                    ts = parts[0].strip()
                    if len(ts) >= 10:
                        return ts[:10]
    logging.warning("Nave.zip not found in request_log.csv; using today as download_date")
    return today


def _compute_source_hash() -> str:
    """SHA-256 of dict.zdt (the main data file)."""
    zdt_path = RAW_DIR / "dict.zdt"
    h = hashlib.sha256()
    with open(zdt_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def build_meta(source_hash: str, download_date: str, processing_date: str) -> dict:
    return {
        "id": INDEX_ID,
        "title": "Nave's Topical Bible",
        "author": "Orville J. Nave",
        "author_birth_year": 1841,
        "author_death_year": 1917,
        "original_publication_year": 1896,
        "language": "en",
        "tradition": ["evangelical", "non-denominational"],
        "tradition_notes": (
            "Nave was a U.S. Army chaplain who compiled this reference over 14 years of study. "
            "Broad evangelical Protestant audience."
        ),
        "license": "public-domain",
        "schema_type": "topical_reference",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": (
                "https://www.crosswire.org/ftpmirror/pub/sword/packages/rawzip/Nave.zip"
            ),
            "source_format": (
                "SWORD zLD binary (dict.idx/dat + dict.zdx/zdt), TEI XML content"
            ),
            "source_edition": (
                "CrossWire SWORD module Nave v3.0 (2008); "
                "text from CCEL (ccel.org/ccel/n/nave/bible.xml)"
            ),
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/naves_topical.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": None,
        },
    }


# ---------------------------------------------------------------------------
# Quality stats helpers
# ---------------------------------------------------------------------------

def _median(values: list) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2.0
    return float(s[mid])


# ---------------------------------------------------------------------------
# Main parsing loop
# ---------------------------------------------------------------------------

def parse_all_entries(limit: int = 0) -> tuple:
    """
    Read dict.idx + dict.dat to enumerate all topics, then extract each entry's
    TEI XML from the zLD blocks.

    Returns (entries, stats) where:
      entries -- list of OCD topical_reference data dicts
      stats   -- dict of quality metrics
    """
    idx_path = RAW_DIR / "dict.idx"
    dat_path = RAW_DIR / "dict.dat"

    idx_data = idx_path.read_bytes()
    dat_data = dat_path.read_bytes()

    n_idx = len(idx_data) // 8
    logging.info("dict.idx: %d bytes -> %d potential entries", len(idx_data), n_idx)
    logging.info("dict.dat: %d bytes", len(dat_data))

    # Preload all blocks
    logging.info("Loading and decompressing all zLD blocks ...")
    block_cache = load_block_cache()
    logging.info("Loaded %d blocks", len(block_cache))

    entries = []
    seen_ids: set = set()
    n_malformed = 0
    n_skipped = 0
    subtopic_counts = []
    ref_counts = []
    total_refs = 0

    process_up_to = limit if limit > 0 else n_idx

    for i in range(n_idx):
        if i >= process_up_to:
            break

        # Parse dict.idx entry
        off, sz = struct.unpack("<II", idx_data[i * 8 : i * 8 + 8])

        # Filter out zero-size or out-of-bounds entries
        if sz == 0 or off >= len(dat_data) or off + sz > len(dat_data):
            n_skipped += 1
            continue

        raw = dat_data[off : off + sz]

        # Split on CRLF (or LF as fallback) to get topic name and block pointer
        if b"\r\n" in raw:
            parts = raw.split(b"\r\n", 1)
        else:
            parts = raw.split(b"\n", 1)

        if len(parts) < 2 or len(parts[1]) < 8:
            logging.warning("idx[%d]: malformed dat entry (too short)", i)
            n_malformed += 1
            continue

        topic_bytes, ptr_and_rest = parts
        topic = topic_bytes.decode("utf-8", errors="replace").strip()

        block_num, entry_in_block = struct.unpack("<II", ptr_and_rest[:8])

        if block_num not in block_cache:
            logging.warning("idx[%d] topic=%r: block_num=%d not in cache", i, topic, block_num)
            n_malformed += 1
            continue

        # Extract entry XML from block
        plain = block_cache[block_num]
        entry_xml = get_entry_from_block(plain, entry_in_block, topic)

        if not entry_xml:
            logging.warning("idx[%d] topic=%r: empty entry XML", i, topic)
            n_malformed += 1
            continue

        # Parse the TEI XML into OCD structure
        subtopics = parse_subtopics(entry_xml)
        related = extract_cross_refs(entry_xml)

        # Count refs for quality stats
        n_refs = sum(len(s["references"]) for s in subtopics)
        subtopic_counts.append(len(subtopics))
        ref_counts.append(n_refs)
        total_refs += n_refs

        # Build the entry_id
        slug = slugify(topic)
        entry_id = make_unique_id(f"{INDEX_ID}.{slug}", seen_ids)

        entry = {
            "entry_id": entry_id,
            "index_id": INDEX_ID,
            "topic": topic,
            "alt_topics": [],
            "subtopics": subtopics,
            "related_topics": related,
        }
        entries.append(entry)

        if (i + 1) % 500 == 0:
            logging.info(
                "  Progress: %d/%d entries processed ...", i + 1, min(process_up_to, n_idx)
            )

    stats = {
        "total": len(entries),
        "malformed": n_malformed,
        "skipped": n_skipped,
        "total_refs": total_refs,
        "subtopics_min": min(subtopic_counts) if subtopic_counts else 0,
        "subtopics_med": _median(subtopic_counts),
        "subtopics_max": max(subtopic_counts) if subtopic_counts else 0,
        "refs_min": min(ref_counts) if ref_counts else 0,
        "refs_med": _median(ref_counts),
        "refs_max": max(ref_counts) if ref_counts else 0,
    }
    return entries, stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Parse Nave's Topical Bible SWORD zLD module into OCD topical_reference schema"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report stats without writing output files",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Only process the first N topics (for testing)",
    )
    args = parser.parse_args()

    start_time = time.time()

    logging.info("=== Nave's Topical Bible parser starting ===")
    logging.info("Source:  %s", RAW_DIR)
    logging.info("Output:  %s", OUTPUT_DIR / "naves-topical-bible.json")
    if args.dry_run:
        logging.info("Mode:    dry-run (no files written)")
    if args.limit:
        logging.info("Limit:   %d topics", args.limit)

    # Compute provenance metadata
    source_hash = _compute_source_hash()
    download_date = _get_download_date()
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logging.info("source_hash: %s", source_hash)
    logging.info("download_date: %s", download_date)

    # Parse all entries
    entries, stats = parse_all_entries(limit=args.limit)

    # Quality report
    logging.info("")
    logging.info("--- Quality Stats ---")
    logging.info("Topics parsed:    %d", stats["total"])
    logging.info("Malformed:        %d", stats["malformed"])
    logging.info("Skipped (empty):  %d", stats["skipped"])
    logging.info("Total refs:       %d", stats["total_refs"])
    logging.info(
        "Subtopics/entry:  min=%d  med=%.1f  max=%d",
        stats["subtopics_min"], stats["subtopics_med"], stats["subtopics_max"],
    )
    logging.info(
        "Refs/entry:       min=%d  med=%.1f  max=%d",
        stats["refs_min"], stats["refs_med"], stats["refs_max"],
    )

    if stats["malformed"] > 0:
        logging.warning("WARNING: %d malformed entries -- check log for details", stats["malformed"])

    # Build output object
    meta = build_meta(source_hash, download_date, processing_date)
    output = {"meta": meta, "data": entries}

    elapsed = time.time() - start_time

    if args.dry_run:
        logging.info("")
        logging.info("--- Sample entries (dry-run, first 3 shown) ---")
        for e in entries[:3]:
            logging.info(json.dumps(e, ensure_ascii=False, indent=2))
        summary = (
            f"=== DONE (dry-run): {stats['total']} topics, "
            f"{stats['total_refs']} refs, {elapsed:.1f}s ==="
        )
        logging.info(summary)
        return

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "naves-topical-bible.json"
    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = out_file.stat().st_size / 1024
    summary = (
        f"=== DONE: {stats['total']} topics, "
        f"{stats['total_refs']} refs, {elapsed:.1f}s ==="
    )
    logging.info("")
    logging.info("Wrote %d entries -> %s (%.0f KB)", stats["total"], out_file, size_kb)
    logging.info(summary)


if __name__ == "__main__":
    main()
