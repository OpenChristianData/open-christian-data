"""ccel_sermon.py
Parser for Wesley's Sermons on Several Occasions from CCEL ThML XML.

Downloads sermons.xml from CCEL (once) to raw/ccel/wesley_sermons.xml, then
parses 141 sermons across 5 series into a single OCD sermon JSON file.

Source: https://www.ccel.org/ccel/wesley/sermons.xml (ThML XML, public domain)

XML structure (inspected 2026-04-12 via CCEL):
  - Root: <ThML> with no XML namespaces; DTD-declared entities (handled below)
  - Series containers: <div1 id='v'> through <div1 id='ix'> (5 series)
  - Sermons: <div2> elements within each series div1 (141 total)
  - Number heading: <h2> matching "Sermon N [edition]" -- skipped from title
  - Title heading: <h2> (second, or third when Discourse subtitle present)
  - Scripture reference: <h3><scripRef osisRef="Bible:Book.ch.v">text</scripRef></h3>
  - Body: <p> and <verse><l>...</l></verse> elements (all classes)
  - Footnotes: <note> -- excluded from content_blocks
  - Skipped: <scripCom>, <h*>, <note>, <sync>, <a> (navigation/structural)

Usage:
    py -3 build/parsers/ccel_sermon.py --dry-run      (parse 3 sermons, no write)
    py -3 build/parsers/ccel_sermon.py                (full run)
    py -3 build/parsers/ccel_sermon.py --force-download
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import urllib.request  # standards: download only
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

RAW_DIR = REPO_ROOT / "raw" / "ccel"
OUTPUT_DIR = REPO_ROOT / "data" / "sermons"
CONFIG_PATH = (
    REPO_ROOT / "sources" / "sermons" / "john-wesley-sermons" / "config.json"
)

SOURCE_URL = "https://www.ccel.org/ccel/wesley/sermons.xml"
RAW_FILE = RAW_DIR / "wesley_sermons.xml"
OUTPUT_FILE = OUTPUT_DIR / "john-wesley-sermons.json"

COLLECTION_ID = "john-wesley-sermons"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
LOG_FILE = Path(__file__).with_suffix(".log")

# div1 ids that contain actual sermon series (in source order)
SERIES_MAP = {
    "v": (1, "First Series"),
    "vi": (2, "Second Series"),
    "vii": (3, "Third Series"),
    "viii": (4, "Fourth Series"),
    "ix": (5, "Fifth Series"),
}

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

# Heading that identifies the "Sermon N [edition]" number line (not a title)
SERMON_NUM_RE = re.compile(r"^Sermon\s+\d+", re.IGNORECASE)

# Extract the global sermon number from the number heading
SERMON_NUM_EXTRACT = re.compile(r"\d+")

# Subtitle h2 is only appended to title if it looks like "Discourse I", "Part 2", etc.
SUBTITLE_RE = re.compile(r"^(Discourse|Part|Section|Chapter)\b", re.IGNORECASE)

# Marks the start of an editorial note embedded in a title h2 with no separator period.
# Wesley source XML sometimes puts publisher notes directly inside the title element.
EDITORIAL_MARKER_RE = re.compile(
    r"\b(The following\b|I have\b|I did\b|I then\b|Advertisement\b)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_source(force: bool = False) -> None:
    """Download sermons.xml from CCEL if not already cached."""
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

def extract_title(div2) -> str:
    """
    Extract sermon title from <div2> headings.

    The first h2 matching "Sermon N [edition info]" is the number line -- skip it.
    The next h2 is the base title. A further h2 is only appended as a subtitle if it
    matches "Discourse N", "Part N", etc. (short structured label); editorial notes
    like "Advertisement ..." and occasion lines like "Preached at ..." are dropped.

    Also handles two source artifacts:
    - Editorial notes embedded without a separator period in the title h2
      (e.g. "The Duty of Constant Communion The following discourse was written ...")
    - Possessive apostrophe-S rendered as capital S in some source entries
      (e.g. "Lord'S" -> "Lord's")
    """
    h2_texts = [clean_text(get_all_text(h)) for h in div2 if h.tag == "h2"]
    title_parts = [h for h in h2_texts if not SERMON_NUM_RE.match(h)]
    if not title_parts:
        return h2_texts[0] if h2_texts else "Untitled"

    # Base title: first non-number h2, truncated at any embedded editorial note
    title = title_parts[0]
    em = EDITORIAL_MARKER_RE.search(title)
    if em and em.start() > 10:
        title = title[: em.start()].strip()

    # Fix possessive apostrophe-S source artifact (e.g. "Lord\u2019S" -> "Lord\u2019s")
    title = re.sub(r"(['\u2019])S\b", r"\1s", title)

    # Subtitle: only include if it is a short structured label ("Discourse I", "Part 2"...)
    if len(title_parts) > 1:
        subtitle = title_parts[1]
        if SUBTITLE_RE.match(subtitle) and len(subtitle) <= 50:
            title = f"{title}: {subtitle}"

    # Strip occasion info starting with "Preached" (keep content before it)
    m = re.search(r"\bPreached\b", title)
    if m and m.start() > 0:
        title = title[: m.start()].strip()

    # Strip editorial bracket notes at the end: "[i.e., ...] " or "[This Sermon ...]"
    title = re.sub(r"\s*\[.*?\]\s*$", "", title).strip()

    # Strip trailing period or comma
    return title.rstrip(".,;").strip()


# ---------------------------------------------------------------------------
# OSIS reference parsing
# ---------------------------------------------------------------------------

def parse_osis_attr(osis_ref: str) -> list:
    """
    Parse the osisRef attribute from a <scripRef> element into a list of OSIS strings.

    Examples:
      "Bible:Eph.2.8"            -> ["Eph.2.8"]
      "Bible:Rom.10.5-Rom.10.8"  -> ["Rom.10.5-Rom.10.8"]
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
# Content block collection
# ---------------------------------------------------------------------------

def collect_content_blocks(div2) -> list:
    """
    Walk direct children of a div2 sermon and collect text blocks in source order.

    Collected:
      <p>  -- all paragraphs (all class attributes)
      <verse><l> -- poetry lines joined with newlines

    Skipped:
      <scripCom>  -- scripture commentary header (structural)
      <h1>-<h5>  -- headings (structural)
      <note>      -- editorial footnotes
      <sync>, <a> -- navigation/metadata
      <div3>+     -- recurse for nested sections
    """
    blocks = []
    for child in div2:
        tag = child.tag
        if tag in ("scripCom", "h1", "h2", "h3", "h4", "h5", "note", "sync", "a"):
            continue
        elif tag == "p":
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
        elif tag == "verse":
            verse_text = get_verse_block(child)
            if verse_text:
                blocks.append(verse_text)
        elif tag in ("div3", "div4", "div5"):
            for grandchild in child:
                gtag = grandchild.tag
                if gtag in ("h3", "h4", "h5", "note", "sync", "a"):
                    continue
                elif gtag == "p":
                    text = clean_text(get_all_text(grandchild))
                    if text:
                        blocks.append(text)
                elif gtag == "verse":
                    verse_text = get_verse_block(grandchild)
                    if verse_text:
                        blocks.append(verse_text)
    return blocks


# ---------------------------------------------------------------------------
# Primary reference extraction
# ---------------------------------------------------------------------------

def extract_primary_reference(div2) -> dict | None:
    """
    Extract the primary scripture reference from the first <h3> that contains
    a <scripRef osisRef="Bible:..."> element.

    Returns {"raw": "Eph. 2:8", "osis": ["Eph.2.8"]} or None if not found.
    """
    for child in div2:
        if child.tag != "h3":
            continue
        scr = child.find(".//scripRef")
        if scr is None:
            continue
        raw_text = clean_text(get_all_text(child))
        # Strip trailing period from the raw reference (e.g. "Eph. 2:8." -> "Eph. 2:8")
        raw_text = raw_text.rstrip(".")
        osis_list = parse_osis_attr(scr.get("osisRef", ""))
        if raw_text:
            return {"raw": raw_text, "osis": osis_list}
    return None


# ---------------------------------------------------------------------------
# Entry parsing
# ---------------------------------------------------------------------------

def extract_sermon_number(div2) -> int | None:
    """Extract the global Wesley sermon number from the 'Sermon N' h2."""
    for child in div2:
        if child.tag != "h2":
            continue
        text = clean_text(get_all_text(child))
        if SERMON_NUM_RE.match(text):
            m = SERMON_NUM_EXTRACT.search(text)
            if m:
                return int(m.group())
    return None


def make_sermon_id(series_number: int, position: int) -> str:
    return f"{series_number}-{position}"


def extract_entry(
    div2, series_number: int, series_name: str, position: int
) -> dict | None:
    """
    Parse a <div2> element into an OCD sermon entry dict.
    Returns None if the div2 looks like a non-sermon (no h3 scripture reference).
    """
    title = extract_title(div2)
    primary_ref = extract_primary_reference(div2)
    content_blocks = collect_content_blocks(div2)

    # Skip non-sermon div2s (index entries etc.) that have no primary reference
    if primary_ref is None and not content_blocks:
        return None

    all_text = " ".join(content_blocks)
    word_count = len(all_text.split()) if all_text.strip() else 0

    return {
        "collection_id": COLLECTION_ID,
        "sermon_id": make_sermon_id(series_number, position),
        "series": series_name,
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

def parse_entries(xml_path: Path, dry_run: bool = False) -> list:
    """
    Parse all sermon entries from the ThML XML file.
    If dry_run=True, parse only the first 3 sermons.
    Returns a list of entry dicts in source order (series 1-5, position 1-N).
    """
    print(f"Parsing {xml_path} ...")
    raw_bytes = xml_path.read_bytes()
    xml_text = preprocess_thml(raw_bytes)

    try:
        from xml.etree import ElementTree as ET
        root = ET.fromstring(xml_text)
    except Exception as exc:
        raise RuntimeError(f"XML parse failed: {exc}") from exc

    entries = []
    skipped = 0
    errors = 0
    limit = 3 if dry_run else None

    for div1 in root.iter("div1"):
        d1_id = div1.get("id", "")
        if d1_id not in SERIES_MAP:
            continue
        series_number, series_name = SERIES_MAP[d1_id]

        position = 0
        for div2 in div1.findall("div2"):
            if limit is not None and len(entries) >= limit:
                break
            position += 1
            try:
                entry = extract_entry(div2, series_number, series_name, position)
            except Exception as exc:
                div_id = div2.get("id", "<unknown>")
                print(f"  ERROR parsing div2 id={div_id!r}: {exc} -- skipping")
                errors += 1
                continue
            if entry is None:
                skipped += 1
                continue
            entries.append(entry)

        if limit is not None and len(entries) >= limit:
            break

    print(
        f"  Parsed {len(entries)} sermons "
        f"({skipped} skipped, {errors} parse errors)"
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
    empty_osis = sum(
        1 for e in entries
        if e["primary_reference"] and not e["primary_reference"]["osis"]
    )
    no_content = sum(1 for e in entries if not e["content_blocks"])
    short = sum(1 for e in entries if 0 < e["word_count"] < 100)

    sorted_words = sorted(words)
    print(f"  Entry count: {total} (expected 141)")
    print(
        f"  Word count: min={min(words)} "
        f"median={sorted_words[total // 2]} "
        f"max={max(words)}"
    )

    if total != 141:
        print(f"  WARNING: Expected 141 sermons, got {total}")
    if no_ref:
        print(f"  WARNING: {no_ref}/{total} entries missing primary_reference")
    if empty_osis:
        print(f"  WARNING: {empty_osis}/{total} entries with empty OSIS list")
    if no_content:
        print(f"  WARNING: {no_content}/{total} entries with no content_blocks")
    if short:
        print(f"  WARNING: {short}/{total} entries under 100 words (suspiciously short)")
    null_ref_text = sum(1 for e in entries if e.get("primary_reference_text") is None)
    if null_ref_text == total:
        print(
            f"  NOTE: primary_reference_text is null for all {total} entries "
            f"(expected -- BSB enrichment is a separate step)"
        )


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
                f"build/parsers/ccel_sermon.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def setup_logging() -> None:
    """Configure file + console logging."""
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG, handlers=[fh, sh],
                        format="%(levelname)s: %(message)s")


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Parse Wesley Sermons on Several Occasions from CCEL ThML XML"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 3 sermons and print sample output -- do not write files",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download sermons.xml even if already cached",
    )
    args = parser.parse_args()

    start_time = time.time()

    if not CONFIG_PATH.exists():
        print(f"ERROR: Config not found: {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    validate_config_enums(config, "sermon")

    print(f"Source:  {config['title']}")
    print(f"Author:  {config['author']}")
    print(f"Output:  {OUTPUT_FILE}")
    if args.dry_run:
        print("Mode:    dry-run (first 3 sermons, no write)")
    print()

    if args.dry_run and not RAW_FILE.exists():
        print("Dry-run: raw file not cached. Run without --dry-run to download first.")
        sys.exit(0)
    download_source(force=args.force_download)
    print()

    entries = parse_entries(RAW_FILE, dry_run=args.dry_run)
    print()

    report_quality(entries)
    print()

    if args.dry_run:
        elapsed = time.time() - start_time
        print("--- Sample entries (dry-run, first 2 shown) ---")
        for entry in entries[:2]:
            sample = dict(entry)
            # Truncate long content_blocks for readability
            sample["content_blocks"] = [b[:100] + "..." if len(b) > 100 else b for b in sample["content_blocks"][:3]]
            print(json.dumps(sample, ensure_ascii=False, indent=2))
        print(f"Dry-run complete -- no files written. ({elapsed:.1f}s)")
        return

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

    print(f"Wrote {len(entries)} sermons -> {OUTPUT_FILE}")
    print(f"File size: {size_kb:.0f} KB")
    print(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
