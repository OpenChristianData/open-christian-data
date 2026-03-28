"""ccel_devotional.py
Parser for Spurgeon's Morning and Evening Daily Readings from CCEL ThML XML.

Downloads morneve.xml from the Christian Classics Ethereal Library (once) to
raw/ccel/spurgeon/morneve.xml, then parses 732 entries (366 days x morning +
evening, including Feb 29) into a single OCD devotional JSON file.

Source: https://www.ccel.org/ccel/spurgeon/morneve.xml (ThML XML, public domain)

XML structure (inspected 2026-03-28 via CCEL):
  - Root: <ThML> with no XML namespaces; DTD-declared entities (handled below)
  - Daily entries: <div2 id="d{MM}{DD}{am|pm}"> -- 732 total
  - Non-daily div2s (intro, navigation): skipped via ID pattern match
  - Scripture ref: <h3 class="scripPassage"><scripRef osisRef="Bible:Book.ch.v">
  - Verse quote (before h3 in source order): <p class="passage">
  - Devotional text: <p class="normal">, <p class="crossref">, <p class="Center">
  - Poetry: <verse><l> ... </l></verse>

Usage:
    py -3 build/parsers/ccel_devotional.py --dry-run     (parse 6 entries, no write)
    py -3 build/parsers/ccel_devotional.py               (full run)
    py -3 build/parsers/ccel_devotional.py --force-download  (re-download even if cached)
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
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "ccel" / "spurgeon"
OUTPUT_DIR = REPO_ROOT / "data" / "devotionals" / "spurgeons-morning-evening"
CONFIG_PATH = (
    REPO_ROOT / "sources" / "devotionals" / "spurgeons-morning-evening" / "config.json"
)

SOURCE_URL = "https://www.ccel.org/ccel/spurgeon/morneve.xml"
RAW_FILE = RAW_DIR / "morneve.xml"
OUTPUT_FILE = OUTPUT_DIR / "morning-evening.json"

COLLECTION_ID = "spurgeons-morning-evening"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# HTML entities that ThML uses but are not valid XML without the external DTD.
# The XML-safe entities (&amp; &lt; &gt; &quot; &apos;) are left untouched.
THML_ENTITY_MAP = {
    "&mdash;": "\u2014",
    "&ndash;": "\u2013",
    "&lsquo;": "\u2018",
    "&rsquo;": "\u2019",
    "&ldquo;": "\u201C",
    "&rdquo;": "\u201D",
    "&nbsp;": "\u00A0",
    "&hellip;": "\u2026",
    "&emdash;": "\u2014",
    "&copy;": "\u00A9",
    "&reg;": "\u00AE",
    "&trade;": "\u2122",
    "&deg;": "\u00B0",
    "&para;": "\u00B6",
    "&sect;": "\u00A7",
    "&dagger;": "\u2020",
    "&Dagger;": "\u2021",
    "&bull;": "\u2022",
    "&prime;": "\u2032",
    "&Prime;": "\u2033",
    "&oline;": "\u203E",
    "&frasl;": "\u2044",
    "&spades;": "\u2660",
    "&clubs;": "\u2663",
    "&hearts;": "\u2665",
    "&diams;": "\u2666",
}

# Div2 IDs that match daily entries: d{MM}{DD}{am|pm}
ID_PATTERN = re.compile(r"^d(\d{2})(\d{2})(am|pm)$")

# XML-safe entities to leave alone
XML_SAFE = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_source(force: bool = False) -> None:
    """Download morneve.xml from CCEL if not already cached."""
    if RAW_FILE.exists() and not force:
        print(f"Source file cached: {RAW_FILE}")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {SOURCE_URL} ...")
    try:
        req = urllib.request.Request(
            SOURCE_URL,
            headers={"User-Agent": "open-christian-data/1.0 (data research project)"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with open(RAW_FILE, "wb") as f:
            f.write(data)
        size_kb = len(data) / 1024
        print(f"Downloaded {size_kb:.0f} KB -> {RAW_FILE}")
    except Exception as exc:
        raise RuntimeError(
            f"Download failed: {exc}. "
            f"Check network access or retry with --force-download."
        ) from exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _replace_entity(match: re.Match) -> str:
    """Replace a named entity if it's in our map; drop unknown ones."""
    ent = match.group(0)
    if ent in XML_SAFE:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    # Unknown entity -- drop it to avoid a parse failure
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """
    Prepare raw ThML bytes for ElementTree parsing:
    1. Decode bytes -- try UTF-8 first; fall back to cp1252 if replacement chars appear.
       CCEL files claim UTF-8 in the XML declaration but embed Windows-1252 smart quotes
       (0x91-0x94), so a cp1252 fallback is required to recover curly quotes correctly.
    2. Strip DOCTYPE declaration (prevents external DTD fetch)
    3. Replace HTML entities with Unicode equivalents
    """
    # Try UTF-8 strict; fall back to cp1252 for CCEL files with Windows-1252 smart quotes
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            # Replacement characters found -- the file has non-UTF-8 bytes; try cp1252
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    # Remove the DOCTYPE declaration (may span multiple lines)
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    # Replace named HTML entities not defined in base XML
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def get_all_text(elem) -> str:
    """Recursively collect all text content from an element and its children."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def clean_text(text: str) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def get_verse_block(verse_elem) -> str:
    """Convert <verse><l>...</l></verse> to a single newline-joined text block."""
    lines = []
    for child in verse_elem:
        line_text = clean_text(get_all_text(child))
        if line_text:
            lines.append(line_text)
    return "\n".join(lines)


def _is_nav_paragraph(p_elem) -> bool:
    """
    Return True if this <p> element is a navigation-only paragraph.
    CCEL inserts links like <p><a href="...">Go To Evening Reading</a></p>
    between entries. These have no direct text content and contain only <a> children.
    """
    # If the element has direct text content (not just whitespace), it's real content
    if p_elem.text and p_elem.text.strip():
        return False
    children = list(p_elem)
    if not children:
        return False
    # Navigation paragraphs contain only <a> tags with no tail text
    for child in children:
        if child.tag != "a":
            return False
        if child.tail and child.tail.strip():
            return False
    return True


def collect_content_blocks(div2_elem) -> list:
    """
    Walk direct children of a div2 entry and collect text blocks in source order.
    - <h2>, <h3>: skipped (structural headings)
    - <sync>, <a>: skipped (navigation/metadata)
    - <p> (navigation-only): skipped -- CCEL adds "Go To Evening/Morning Reading" links
    - <p>: collected as a text block (all classes: passage, normal, crossref, Center, etc.)
    - <verse>: lines joined with newlines into a single block
    - <div3>, <div4>: recurse to collect their p/verse children

    Returns a list of non-empty strings.
    """
    blocks = []
    for child in div2_elem:
        tag = child.tag
        if tag in ("h2", "h3", "h4", "h5", "sync", "a"):
            continue
        elif tag == "p":
            if _is_nav_paragraph(child):
                continue
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
        elif tag == "verse":
            verse_text = get_verse_block(child)
            if verse_text:
                blocks.append(verse_text)
        elif tag in ("div3", "div4", "div5"):
            # Nested section -- recurse one level
            for grandchild in child:
                gtag = grandchild.tag
                if gtag == "p":
                    if _is_nav_paragraph(grandchild):
                        continue
                    text = clean_text(get_all_text(grandchild))
                    if text:
                        blocks.append(text)
                elif gtag == "verse":
                    verse_text = get_verse_block(grandchild)
                    if verse_text:
                        blocks.append(verse_text)
    return blocks


# ---------------------------------------------------------------------------
# OSIS reference parsing
# ---------------------------------------------------------------------------

def parse_osis_attr(osis_ref: str) -> list:
    """
    Parse the osisRef attribute from a <scripRef> element into a list of OSIS strings.

    Examples:
      "Bible:Josh.5.12"        -> ["Josh.5.12"]
      "Bible:Ps.63.5-Ps.63.6" -> ["Ps.63.5-Ps.63.6"]
      "Bible:Ps.1.1 Bible:Ps.1.2" -> ["Ps.1.1", "Ps.1.2"]
    """
    if not osis_ref:
        return []
    refs = []
    for part in osis_ref.split():
        clean = part.replace("Bible:", "").strip()
        if clean:
            refs.append(clean)
    return refs


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------

def parse_div2_id(div2_id: str):
    """
    Parse a div2 id attribute into (month, day, period).
    e.g. 'd0101am' -> (1, 1, 'morning'), 'd1231pm' -> (12, 31, 'evening')
    Returns None if the id does not match the daily entry pattern.
    """
    m = ID_PATTERN.match(div2_id)
    if not m:
        return None
    month = int(m.group(1))
    day = int(m.group(2))
    period = "morning" if m.group(3) == "am" else "evening"
    return month, day, period


def make_entry_id(month: int, day: int, period: str) -> str:
    return f"{month:02d}-{day:02d}-{period}"


def make_title(month: int, day: int, period: str) -> str:
    return f"{MONTH_NAMES[month - 1]} {day} -- {period.capitalize()}"


def extract_entry(div2) -> dict:
    """
    Parse a <div2> element into an OCD devotional entry dict.
    Returns None if the div2 id does not match a daily entry pattern.
    """
    div_id = div2.get("id", "")
    parsed = parse_div2_id(div_id)
    if not parsed:
        return None
    month, day, period = parsed

    # --- Primary scripture reference ---
    # Appears in <h3 class="scripPassage"><scripRef ...>text</scripRef></h3>
    primary_ref = None
    for h3 in div2:
        if h3.tag != "h3":
            continue
        cls = h3.get("class", "")
        if "scripPassage" not in cls and "scrip" not in cls.lower():
            continue
        scr = h3.find(".//scripRef")
        if scr is not None:
            raw_text = clean_text(get_all_text(scr))
            osis_list = parse_osis_attr(scr.get("osisRef", ""))
            if raw_text:
                primary_ref = {"raw": raw_text, "osis": osis_list}
        break

    # --- Content blocks ---
    content_blocks = collect_content_blocks(div2)

    # Word count across all content
    all_text = " ".join(content_blocks)
    word_count = len(all_text.split()) if all_text.strip() else 0

    return {
        "collection_id": COLLECTION_ID,
        "entry_id": make_entry_id(month, day, period),
        "month": month,
        "day": day,
        "period": period,
        "title": make_title(month, day, period),
        "primary_reference": primary_ref,
        "primary_reference_text": None,
        "content_blocks": content_blocks,
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Main parse loop
# ---------------------------------------------------------------------------

def parse_entries(xml_path: Path, dry_run: bool = False) -> list:
    """
    Parse all daily entries from the ThML XML file.
    If dry_run=True, only parse the first 5 entries.
    Returns a list of entry dicts sorted by month, day, period.
    """
    print(f"Parsing {xml_path} ...")
    raw_bytes = xml_path.read_bytes()
    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML parse failed: {exc}") from exc

    entries = []
    skipped = 0
    errors = 0
    # Dry-run: parse 6 entries. The CCEL XML interleaves am/pm in source order
    # (d0101am, d0101pm, d0102am, d0102pm ...) so 6 entries covers 3 full days
    # and exercises both the morning and evening parsing paths.
    limit = 6 if dry_run else None

    # Walk all div2 elements in document order
    for div2 in root.iter("div2"):
        if limit is not None and len(entries) >= limit:
            break
        try:
            entry = extract_entry(div2)
        except Exception as exc:
            div_id = div2.get("id", "<unknown>")
            print(f"  ERROR parsing div2 id={div_id!r}: {exc} -- skipping")
            errors += 1
            continue
        if entry is None:
            skipped += 1
            continue
        entries.append(entry)
        # Progress counter every 100 entries
        if not dry_run and len(entries) % 100 == 0:
            print(f"  Parsed {len(entries)} entries ...")

    # Sort: January before December, morning before evening within each day
    entries.sort(key=lambda e: (e["month"], e["day"], 0 if e["period"] == "morning" else 1))

    print(
        f"  Parsed {len(entries)} entries "
        f"({skipped} non-daily skipped, {errors} parse errors)"
    )
    return entries


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def report_quality(entries: list) -> None:
    """Print quality statistics. Warns on suspicious entries."""
    total = len(entries)
    if total == 0:
        return

    words = [e["word_count"] for e in entries]
    no_ref = sum(1 for e in entries if e["primary_reference"] is None)
    no_osis = sum(
        1 for e in entries
        if e["primary_reference"] and not e["primary_reference"]["osis"]
    )
    empty_osis = sum(
        1 for e in entries
        if e["primary_reference"] and e["primary_reference"]["osis"] == []
    )
    no_content = sum(1 for e in entries if not e["content_blocks"])
    short = sum(1 for e in entries if e["word_count"] < 50)

    sorted_words = sorted(words)
    # 730 = without Feb 29; 732 = with Feb 29 (leap year reading included)
    print(f"  Entry count: {total} (expected 730 or 732)")
    print(
        f"  Word count: min={min(words)} median={sorted_words[total // 2]} max={max(words)}"
    )

    if total not in (730, 732):
        print(f"  WARNING: Expected 730 or 732 entries, got {total}")
    if no_ref:
        print(f"  WARNING: {no_ref}/{total} entries missing primary_reference")
    if no_osis or empty_osis:
        print(f"  WARNING: {no_osis + empty_osis}/{total} entries with empty OSIS list")
    if no_content:
        print(f"  WARNING: {no_content}/{total} entries with no content_blocks")
    if short:
        print(f"  WARNING: {short}/{total} entries under 50 words (suspiciously short)")
    # primary_reference_text is intentionally null at the source layer (BSB enrichment step)
    null_ref_text = sum(1 for e in entries if e.get("primary_reference_text") is None)
    if null_ref_text == total:
        print(f"  NOTE: primary_reference_text is null for all {total} entries (expected -- BSB enrichment is a separate step)")


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(config: dict, data_hash: str, processing_date: str) -> dict:
    """Build the meta envelope from source config."""
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
            "source_hash": f"sha256:{data_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_devotional.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Spurgeon Morning & Evening from CCEL ThML XML into OCD schema"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 5 entries and print sample output -- do not write files",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download morneve.xml even if it is already cached",
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
    print(f"Output:  {OUTPUT_FILE}")
    if args.dry_run:
        print("Mode:    dry-run (first 5 entries, no write)")
    print()

    # Download source
    if args.dry_run and not RAW_FILE.exists():
        print("Dry-run: raw file not cached. Run without --dry-run to download first.")
        sys.exit(0)
    download_source(force=args.force_download)
    print()

    # Parse
    entries = parse_entries(RAW_FILE, dry_run=args.dry_run)
    print()

    # Quality report
    report_quality(entries)
    print()

    if args.dry_run:
        elapsed = time.time() - start_time
        print("--- Sample entries (dry-run, first 2 shown) ---")
        for entry in entries[:2]:
            print(json.dumps(entry, ensure_ascii=False, indent=2))
        print(f"Dry-run complete -- no files written. ({elapsed:.1f}s)")
        return

    # Build output
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    data_hash = hashlib.sha256(data_bytes).hexdigest()

    meta = build_meta(config, data_hash, processing_date)
    output = {"meta": meta, "data": entries}

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    elapsed = time.time() - start_time

    print(f"Wrote {len(entries)} entries -> {OUTPUT_FILE}")
    print(f"File size: {size_kb:.0f} KB")
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
