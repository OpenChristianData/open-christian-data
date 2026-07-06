"""ccel_whitefield_sermon.py
Parser for George Whitefield's Selected Sermons from CCEL ThML XML.

Parses whitefield_sermons.xml (already cached at raw/ccel/whitefield_sermons.xml)
into a single OCD sermon JSON file with 59 sermons (CCEL source only).
Run build/scripts/add_pg_whitefield_sermons.py afterward to append 2 PG-unique sermons
(total = 61).

Source: https://www.ccel.org/ccel/whitefield/sermons.xml (ThML XML, public domain)
CCEL permission confirmed 2026-04-01 (Quincy).

XML structure (differs from Wesley -- pre-inspected 2026-04-12):
  - Root: <ThML> with no XML namespaces; DTD-declared entities (handled below)
  - Sermons: <div1> elements (62 total; first two and last one are skipped)
  - Title: <h1> -- may include occasion text and/or trailing parenthetical note
  - Scripture ref: first <p> child -- "Book N:M -- 'quote text...'" (free text)
  - osisRef is EMPTY in CCEL's Whitefield source -- osis list is always []
  - Body: remaining <p> and <verse><l>...</l></verse> elements
  - Footnotes: <note> -- excluded from content_blocks
  - Skipped: <scripCom>, <h1>-<h5>, <note>, <sync>, <a>

div1 ids to skip: 'i' (title page), 'ii' (Table of Contents)
Also skip the final div1 (Indexes entry).

Usage:
    py -3 build/parsers/ccel_whitefield_sermon.py --dry-run   (parse 3 sermons, no write)
    py -3 build/parsers/ccel_whitefield_sermon.py             (full run)
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.config_validation import validate_config_enums  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel"
OUTPUT_DIR = REPO_ROOT / "data" / "sermons"
CONFIG_PATH = (
    REPO_ROOT / "sources" / "sermons" / "george-whitefield-sermons" / "config.json"
)

RAW_FILE = RAW_DIR / "whitefield_sermons.xml"
OUTPUT_FILE = OUTPUT_DIR / "george-whitefield-sermons.json"
LOG_FILE = Path(__file__).resolve().parent / "ccel_whitefield_sermon.log"

COLLECTION_ID = "george-whitefield-sermons"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

# div1 ids that are NOT sermons (title page and Table of Contents)
SKIP_IDS = {"i", "ii"}

# Expected sermon count after skipping non-sermon div1s
EXPECTED_COUNT = 59

# HTML entities that ThML uses but are not valid XML without the external DTD.
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
    "&agrave;": "\u00E0",
    "&Agrave;": "\u00C0",
    "&aacute;": "\u00E1",
    "&Aacute;": "\u00C1",
    "&eacute;": "\u00E9",
    "&Eacute;": "\u00C9",
    "&egrave;": "\u00E8",
    "&ecirc;": "\u00EA",
    "&ouml;": "\u00F6",
    "&Ouml;": "\u00D6",
    "&uuml;": "\u00FC",
    "&Uuml;": "\u00DC",
    "&auml;": "\u00E4",
    "&Auml;": "\u00C4",
    "&ccedil;": "\u00E7",
    "&ntilde;": "\u00F1",
    "&oacute;": "\u00F3",
    "&iacute;": "\u00ED",
    "&uacute;": "\u00FA",
    "&szlig;": "\u00DF",
    "&AElig;": "\u00C6",
    "&aelig;": "\u00E6",
    "&OElig;": "\u0152",
    "&oelig;": "\u0153",
}

XML_SAFE = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}

# Split title at occasion text starting with "Preached" (keep content before it)
PREACHED_RE = re.compile(r"\bPreached\b")

# Strip trailing parenthetical editorial notes: "(...)"
TRAILING_PAREN_RE = re.compile(r"\s*\(.*?\)\s*$")

# Dash variants used as separator in the scripture reference paragraph
DASH_RE = re.compile(r"[\u2014\u2013]")  # em-dash or en-dash

# Fallback: comma-quote separator (e.g. "1 Corinthians 13:8, 'Charity never faileth.'")
# Matches a scripture reference at the start of the paragraph when no dash is present.
# Group 1 captures the raw reference (book + chapter:verse).
COMMA_REF_RE = re.compile(
    r"^((?:\d+\s+)?[A-Z][a-zA-Z]+(?:\s+[A-Za-z]+)*\s+\d+:\d+(?:[,\-\u2013\u2014]\d+)?)"
    r"\s*[,;]\s*[\"\u201C\u2018]"
)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> logging.Logger:
    """Configure logging to both console and log file."""
    logger = logging.getLogger("whitefield_parser")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    # File handler -- durable record for post-run diagnosis
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _replace_entity(match: re.Match) -> str:
    """Replace a named entity if it is in our map; drop unknown ones."""
    ent = match.group(0)
    if ent in XML_SAFE:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """
    Prepare raw ThML bytes for ElementTree parsing:
    1. Decode bytes -- try UTF-8 first; fall back to cp1252 if replacement chars appear.
    2. Strip DOCTYPE declaration (prevents external DTD fetch).
    3. Replace HTML entities with Unicode equivalents.
    """
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
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
    """Convert <verse><l>...</l></verse> to a newline-joined text block."""
    lines = []
    for child in verse_elem:
        line_text = clean_text(get_all_text(child))
        if line_text:
            lines.append(line_text)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------

def extract_title(div1) -> str:
    """
    Extract sermon title from the <h1> element of a div1.

    Cleaning applied:
    - Strip occasion text starting at "Preached" (keep everything before it)
    - Strip trailing parenthetical editorial notes: "(The last sermon...)"
    - Strip trailing period or comma
    """
    h1_elem = div1.find("h1")
    if h1_elem is None:
        return "Untitled"

    title = clean_text(get_all_text(h1_elem))

    # Strip occasion info starting with "Preached"
    m = PREACHED_RE.search(title)
    if m and m.start() > 0:
        title = title[: m.start()].strip()

    # Strip trailing parenthetical editorial note
    title = TRAILING_PAREN_RE.sub("", title).strip()

    # Strip trailing period or comma
    return title.rstrip(".,;").strip()


# ---------------------------------------------------------------------------
# Primary reference extraction
# ---------------------------------------------------------------------------

def extract_primary_reference(div1) -> dict | None:
    """
    Extract the scripture reference from the first <p> child of a div1.

    Two patterns handled:
    - Dash separator: "Book N:M -- 'quote text...'" (most common)
    - Comma-quote separator: "Book N:M, 'quote text...'" (1 case: sermon 47)

    Returns {"raw": "Genesis 3:15", "osis": []} or None if no ref found.
    Note: osisRef is empty in the CCEL Whitefield source -- osis is always [].
    """
    first_p = div1.find("p")
    if first_p is None:
        return None
    full_text = clean_text(get_all_text(first_p))

    # Primary pattern: em-dash or en-dash separator
    m = DASH_RE.search(full_text)
    if m is not None:
        raw = full_text[: m.start()].strip().rstrip(".")
        if raw:
            return {"raw": raw, "osis": []}

    # Fallback: comma-quote separator (e.g. "1 Corinthians 13:8, 'Charity never faileth.'")
    m2 = COMMA_REF_RE.match(full_text)
    if m2 is not None:
        raw = m2.group(1).strip().rstrip(".")
        if raw:
            return {"raw": raw, "osis": []}

    return None


# ---------------------------------------------------------------------------
# Content block collection
# ---------------------------------------------------------------------------

def collect_content_blocks(div1) -> list:
    """
    Walk direct children of a div1 sermon and collect text blocks in source order.

    The first <p> is the scripture ref paragraph. Its quote portion (everything
    after the first separator) becomes the first content block -- it is sermon content.
    Three cases for the first <p>:
      1. Dash separator: "Book N:M -- 'quote...'" -> add quote part only
      2. Comma-quote separator: "Book N:M, 'quote...'" -> add quote part only
      3. No separator: first paragraph is plain body text -> add all of it

    Skipped elements:
      <scripCom>  -- structural placeholder (osisRef is empty in Whitefield)
      <h1>-<h5>  -- headings (structural)
      <note>      -- editorial footnotes
      <sync>, <a> -- navigation/metadata
    """
    blocks = []
    first_p_seen = False

    for child in div1:
        tag = child.tag
        if tag in ("scripCom", "h1", "h2", "h3", "h4", "h5", "note", "sync", "a"):
            continue
        elif tag == "p":
            if not first_p_seen:
                first_p_seen = True
                full_text = clean_text(get_all_text(child))

                m = DASH_RE.search(full_text)
                if m is not None:
                    # Case 1: dash separator -- add quote part only
                    quote_part = full_text[m.end():].strip()
                    quote_part = quote_part.strip('"\u201C\u201D\u2018\u2019\'').strip()
                    if quote_part:
                        blocks.append(quote_part)
                else:
                    m2 = COMMA_REF_RE.match(full_text)
                    if m2 is not None:
                        # Case 2: comma-quote separator -- quote starts right after match end
                        quote_part = full_text[m2.end():].strip()
                        quote_part = quote_part.strip('"\u201C\u201D\u2018\u2019\'').strip()
                        if quote_part:
                            blocks.append(quote_part)
                    else:
                        # Case 3: no scripture ref separator -- whole paragraph is body text
                        if full_text:
                            blocks.append(full_text)
            else:
                # Subsequent <p>: collect as-is
                text = clean_text(get_all_text(child))
                if text:
                    blocks.append(text)
        elif tag == "verse":
            first_p_seen = True  # verse after first element counts as body
            verse_text = get_verse_block(child)
            if verse_text:
                blocks.append(verse_text)

    return blocks


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------

def extract_entry(div1, position: int) -> dict | None:
    """
    Parse a <div1> element into an OCD sermon entry dict.
    Position is 1-indexed within the list of actual sermon div1s.
    Returns None if the div1 has no content blocks.
    """
    title = extract_title(div1)
    primary_ref = extract_primary_reference(div1)
    content_blocks = collect_content_blocks(div1)

    if not content_blocks:
        return None

    all_text = " ".join(content_blocks)
    word_count = len(all_text.split()) if all_text.strip() else 0

    return {
        "collection_id": COLLECTION_ID,
        "sermon_id": str(position),
        "series": None,
        "title": title,
        "primary_reference": primary_ref,
        "primary_reference_text": None,
        "content_blocks": content_blocks,
        "date_preached": None,
        "location": None,
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# Main parse loop
# ---------------------------------------------------------------------------

def parse_entries(
    xml_path: Path, logger: logging.Logger, dry_run: bool = False
) -> tuple[list, int, int]:
    """
    Parse all sermon entries from the ThML XML file.
    If dry_run=True, parse only the first 3 sermons.
    Returns (entries, skipped_count, error_count).
    """
    print(f"Parsing {xml_path} ...")
    logger.info("Parsing %s", xml_path)
    raw_bytes = xml_path.read_bytes()
    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise RuntimeError(
            f"XML parse failed: {exc}. "
            f"Check {xml_path} is a valid ThML file."
        ) from exc

    # Collect all div1 elements, skip SKIP_IDS, drop the last one (Indexes)
    all_div1s = list(root.iter("div1"))
    sermon_div1s = [d for d in all_div1s if d.get("id") not in SKIP_IDS][:-1]
    total_to_process = min(3, len(sermon_div1s)) if dry_run else len(sermon_div1s)

    entries = []
    skipped = 0
    errors = 0
    limit = 3 if dry_run else None

    for position, div1 in enumerate(sermon_div1s, start=1):
        if limit is not None and len(entries) >= limit:
            break
        print(f"  Processing sermon {position} of {total_to_process}...")
        try:
            entry = extract_entry(div1, position)
        except Exception as exc:
            div_id = div1.get("id", "<unknown>")
            msg = (
                f"ERROR parsing div1 id={div_id!r} in {xml_path}: "
                f"{type(exc).__name__}: {exc} -- skipping. "
                f"Check the element structure at that id."
            )
            print(f"  {msg}")
            logger.error(msg)
            errors += 1
            continue
        if entry is None:
            logger.debug("Skipped div1 id=%r (no content blocks)", div1.get("id"))
            skipped += 1
            continue
        logger.info(
            "Parsed sermon %d: %r (words=%d)",
            position, entry["title"], entry["word_count"]
        )
        entries.append(entry)

    print(
        f"  Parsed {len(entries)} sermons "
        f"({skipped} skipped, {errors} parse errors)"
    )
    logger.info(
        "Parse complete: %d entries, %d skipped, %d errors",
        len(entries), skipped, errors
    )
    return entries, skipped, errors


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def report_quality(entries: list, logger: logging.Logger) -> bool:
    """
    Print quality statistics and warn on suspicious entries.
    Returns True if output is safe to write, False if a blocking issue is found.
    """
    total = len(entries)
    if total == 0:
        return True

    words = [e["word_count"] for e in entries]
    no_ref = sum(1 for e in entries if e["primary_reference"] is None)
    no_content = sum(1 for e in entries if not e["content_blocks"])
    short = sum(1 for e in entries if 0 < e["word_count"] < 100)
    untitled = sum(1 for e in entries if e["title"] == "Untitled")
    ok = True

    sorted_words = sorted(words)
    print(f"  Entry count:  {total} (expected {EXPECTED_COUNT})")
    print(
        f"  Word count:   min={min(words)} "
        f"median={sorted_words[total // 2]} "
        f"max={max(words)}"
    )
    print(f"  Missing ref:  {no_ref}/{total} entries (11 expected -- body-text-first sermons)")
    print(f"  Untitled:     {untitled}/{total} entries")

    logger.info("Quality: count=%d expected=%d no_ref=%d untitled=%d",
                total, EXPECTED_COUNT, no_ref, untitled)

    if total != EXPECTED_COUNT:
        msg = f"Expected {EXPECTED_COUNT} sermons, got {total} -- blocking write"
        print(f"  WARNING: {msg}")
        logger.warning(msg)
        ok = False
    if untitled:
        msg = f"{untitled}/{total} entries have 'Untitled' title (title extraction failed)"
        print(f"  WARNING: {msg}")
        logger.warning(msg)
    if no_content:
        msg = f"{no_content}/{total} entries with no content_blocks"
        print(f"  WARNING: {msg}")
        logger.warning(msg)
        ok = False
    if short:
        msg = f"{short}/{total} entries under 100 words (suspiciously short)"
        print(f"  WARNING: {msg}")
        logger.warning(msg)

    # osis is always [] for Whitefield -- confirm and note (not a warning)
    has_ref = sum(1 for e in entries if e["primary_reference"] is not None)
    all_empty_osis = has_ref == 0 or all(
        not e["primary_reference"]["osis"]
        for e in entries
        if e["primary_reference"] is not None
    )
    if all_empty_osis and has_ref > 0:
        print(
            f"  NOTE: primary_reference.osis is [] for all {has_ref} entries "
            f"with refs (expected -- osisRef not populated in CCEL Whitefield source)"
        )

    null_ref_text = sum(1 for e in entries if e.get("primary_reference_text") is None)
    if null_ref_text == total:
        print(
            f"  NOTE: primary_reference_text is null for all {total} entries "
            f"(expected -- BSB enrichment is a separate step)"
        )

    # Variant spot-check: sample one entry from each known ref-format category.
    # This confirms all three code paths produced correct output, not just that counts look right.
    if total >= 48:
        print()
        print("  -- Variant spot-check (one per category) --")
        # Category 1: dash-ref (sermon 1, always present)
        e1 = next((e for e in entries if e["sermon_id"] == "1"), None)
        if e1:
            ref = e1["primary_reference"]["raw"] if e1["primary_reference"] else "MISSING"
            blk = e1["content_blocks"][0][:60] if e1["content_blocks"] else "EMPTY"
            print(f"  Dash-ref  (s1):  ref={ref!r}")
            print(f"             blk={blk!r}")
        # Category 2: comma-ref (sermon 47, "Charity")
        e47 = next((e for e in entries if e["sermon_id"] == "47"), None)
        if e47:
            ref = e47["primary_reference"]["raw"] if e47["primary_reference"] else "MISSING"
            blk = e47["content_blocks"][0][:60] if e47["content_blocks"] else "EMPTY"
            print(f"  Comma-ref (s47): ref={ref!r}")
            print(f"             blk={blk!r}")
        # Category 3: body-text-first (sermon 7, no ref)
        e7 = next((e for e in entries if e["sermon_id"] == "7"), None)
        if e7:
            ref = e7["primary_reference"]["raw"] if e7["primary_reference"] else "None (expected)"
            blk = e7["content_blocks"][0][:60] if e7["content_blocks"] else "EMPTY"
            print(f"  Body-text (s7):  ref={ref!r}")
            print(f"             blk={blk!r}")

    return ok


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
        "contributors": normalize_contributors(config.get("contributors", [])),
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
        "completeness": "full",
        "provenance": {
            "source_url": config["source_url"],
            "source_format": config["source_format"],
            "source_edition": config["source_edition"],
            "download_date": processing_date,
            "source_hash": f"sha256:{data_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_whitefield_sermon.py@{SCRIPT_VERSION}"
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
        description="Parse Whitefield Selected Sermons from CCEL ThML XML"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 3 sermons and print sample output -- do not write files",
    )
    args = parser.parse_args()

    logger = setup_logging()
    start_time = time.time()
    logger.info("=== ccel_whitefield_sermon.py started ===")

    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        logger.error("Config not found: %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    validate_config_enums(config, "sermon")

    if not RAW_FILE.exists():
        print(f"ERROR: Raw XML file not found: {RAW_FILE}")
        print("The file should already be cached. Check raw/ccel/whitefield_sermons.xml.")
        logger.error("Raw XML not found: %s", RAW_FILE)
        sys.exit(1)

    print(f"Source:  {config['title']}")
    print(f"Author:  {config['author']}")
    print(f"Output:  {OUTPUT_FILE}")
    if args.dry_run:
        print("Mode:    dry-run (first 3 sermons, no write)")
    print()

    entries, skipped, errors = parse_entries(RAW_FILE, logger, dry_run=args.dry_run)
    print()

    ok = report_quality(entries, logger)
    print()

    if args.dry_run:
        elapsed = time.time() - start_time
        print("--- Sample entries (dry-run, first 2 shown) ---")
        for entry in entries[:2]:
            sample = dict(entry)
            # Truncate long content_blocks for readability
            sample["content_blocks"] = [
                b[:100] + "..." if len(b) > 100 else b
                for b in sample["content_blocks"][:3]
            ]
            print(json.dumps(sample, ensure_ascii=False, indent=2))
        print(f"Dry-run complete -- no files written. ({elapsed:.1f}s)")
        logger.info("Dry-run complete. No files written.")
        return

    # Block write if quality checks failed (prevents a broken output file)
    if not ok:
        print("ERROR: Quality checks failed -- output not written. Fix the parser and re-run.")
        logger.error("Quality check failed -- output not written.")
        sys.exit(1)

    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data_bytes = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    data_hash = hashlib.sha256(data_bytes).hexdigest()

    meta = build_meta(config, data_hash, processing_date)
    output = {"meta": meta, "data": entries}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    elapsed = time.time() - start_time

    summary = (
        f"Wrote {len(entries)} sermons "
        f"({skipped} skipped, {errors} errors) -> {OUTPUT_FILE} "
        f"({size_kb:.0f} KB, {elapsed:.1f}s)"
    )
    print(summary)
    logger.info(summary)
    logger.info("=== ccel_whitefield_sermon.py finished ===")


if __name__ == "__main__":
    main()
