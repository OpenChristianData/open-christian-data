"""standard_ebooks.py
Parse Standard Ebooks XHTML source files into OCD JSON schema.

Reads XHTML from raw/standard_ebooks/{se-identifier}/src/epub/text/ and
outputs structured JSON following the OCD schema conventions.

Handles two schema types:
  structured_text -- hierarchical prose works (theological, devotional classics)
  sermon          -- individual sermon collections (MacDonald's Unspoken Sermons)

Source markup conventions (Standard Ebooks):
  - Files are semantic XHTML with epub:type attributes for structure
  - Namespace: xmlns="http://www.w3.org/1999/xhtml"
               xmlns:epub="http://www.idpf.org/2007/ops"
  - epub:type="noteref" anchors are footnote references -- stripped from text
  - data-parent attribute links child sections to parent container files
  - Poem sections use <p><span> line structure

Usage:
    py -3 build/parsers/standard_ebooks.py --id john-bunyan_the-pilgrims-progress --dry-run
    py -3 build/parsers/standard_ebooks.py --id john-bunyan_the-pilgrims-progress
    py -3 build/parsers/standard_ebooks.py --all
    py -3 build/parsers/standard_ebooks.py --all --dry-run
    py -3 build/parsers/standard_ebooks.py --id george-macdonald_unspoken-sermons --list-files
    py -3 build/parsers/standard_ebooks.py --all --list-files
"""

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "raw" / "standard_ebooks"
SOURCES_DIR = REPO_ROOT / "sources" / "standard-ebooks"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"

# XHTML namespace constants
XHTML_NS = "http://www.w3.org/1999/xhtml"
EPUB_NS = "http://www.idpf.org/2007/ops"


def h(local):
    """Return fully-qualified XHTML tag name."""
    return f"{{{XHTML_NS}}}{local}"


def epub_type(elem):
    """Get epub:type attribute value, or empty string."""
    return elem.get(f"{{{EPUB_NS}}}type", "")


# Files to skip unconditionally (front/back matter with no content value).
# Exact stem matches or prefix matches (e.g. "dedication" covers "dedication-1-1").
SKIP_STEMS = {
    "titlepage", "halftitlepage", "imprint", "colophon",
    "uncopyright", "endnotes", "dedication", "epigraph",
}
# Additional prefix-based skip: any stem that starts with one of these
SKIP_PREFIXES = ("dedication", "endnotes", "titlepage", "halftitlepage")

# Map file id prefix -> section_type
SECTION_TYPE_MAP = {
    "book": "book",
    "part": "part",
    "chapter": "chapter",
    "series": "part",       # SE uses 'series' for MacDonald's series divisions
    "preface": "preface",
    "introduction": "introduction",
    "foreword": "preface",  # treat foreword as preface
    "conclusion": "conclusion",
    "appendix": "appendix",
}

# Known all-SE identifiers and their source dirs
ALL_SE_IDS = [
    "john-bunyan_the-pilgrims-progress",
    "augustine-of-hippo_the-city-of-god_marcus-dods_george-wilson_j-j-smith",
    "g-k-chesterton_orthodoxy",
    "g-k-chesterton_heretics",
    "g-k-chesterton_the-everlasting-man",
    "thomas-a-kempis_the-imitation-of-christ_william-benham",
    "george-macdonald_unspoken-sermons",
    "evelyn-underhill_practical-mysticism",
    "john-milton_paradise-lost",
]


# ---------------------------------------------------------------------------
# XHTML parsing utilities
# ---------------------------------------------------------------------------

def parse_xhtml(path):
    """Parse an XHTML file, returning the ElementTree root.
    Raises RuntimeError on parse failure."""
    content = path.read_bytes()
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML parse error in {path.name}: {exc}") from exc
    return root


def get_text_content(elem, skip_epub_types=None):
    """Recursively collect all text from element, skipping noteref anchors.

    skip_epub_types: set of epub:type values to skip (text and descendants).
    Defaults to {"noteref"} to strip footnote reference numbers.
    """
    if skip_epub_types is None:
        skip_epub_types = {"noteref"}

    parts = []
    if elem.text:
        parts.append(elem.text)

    for child in elem:
        child_etype = epub_type(child)
        # Check if any skip type appears in this element's epub:type token list
        should_skip = any(t in child_etype.split() for t in skip_epub_types)
        if should_skip:
            # Skip element text but still include tail (text after closing tag)
            if child.tail:
                parts.append(child.tail)
        else:
            parts.append(get_text_content(child, skip_epub_types))
            if child.tail:
                parts.append(child.tail)

    return "".join(parts)


def clean_text(text):
    """Collapse internal whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def clean_reference_text(text):
    """Clean a scripture reference string.

    Strips invisible formatting characters (U+2060 WORD JOINER) that Standard
    Ebooks uses to prevent line breaks in references. Also normalises en-dash
    (U+2013) to a plain hyphen in numeric ranges (e.g. '33--37' -> '33-37').
    """
    # Remove invisible word-joiner
    text = text.replace("\u2060", "")
    # Normalise en-dash in verse ranges (digit -- digit) to hyphen
    text = re.sub(r"(\d)\u2013(\d)", r"\1-\2", text)
    return text.strip()


def extract_poem_paragraph(p_elem):
    """Convert a poem <p> (with <span> verse lines) to a newline-joined block.

    Standard Ebooks poem markup uses <p><span>line</span><br/><span>line</span></p>.
    Each <p> represents a verse paragraph (stanza or verse block).
    """
    lines = []
    # Collect direct text if present
    if p_elem.text and p_elem.text.strip():
        lines.append(p_elem.text.strip())
    for child in p_elem:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "span":
            text = clean_text(get_text_content(child))
            if text:
                lines.append(text)
        # <br/> elements are skipped; their tail may have content
        if child.tail and child.tail.strip():
            lines.append(child.tail.strip())
    return "\n".join(lines)


def extract_blocks_from_section(section_elem):
    """Extract content_blocks from a section element.

    Handles:
    - Regular <p> paragraphs
    - Poem sections (<section epub:type="z3998:poem">) with span-per-line structure
    - Argument/preamble sections (preamble epub:type)
    - Header elements are skipped
    - blockquote elements (epigraph, pullquote) are included as regular paragraphs

    Returns a list of non-empty text strings.
    """
    blocks = []

    def _walk(elem):
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        etype = epub_type(elem)

        # Skip structural header elements (but not blockquote content)
        if local in ("h1", "h2", "h3", "h4", "h5", "h6", "header", "hgroup"):
            return

        # Detect poem sections
        if local == "section" and "z3998:poem" in etype:
            for child in elem:
                child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_local == "p":
                    block = extract_poem_paragraph(child)
                    if block.strip():
                        blocks.append(block)
            return

        # Regular paragraph
        if local == "p":
            text = clean_text(get_text_content(elem))
            if text:
                blocks.append(text)
            return

        # Recurse into other container elements
        for child in elem:
            _walk(child)

    for child in section_elem:
        _walk(child)

    return blocks


# ---------------------------------------------------------------------------
# File structure analysis
# ---------------------------------------------------------------------------

def natural_sort_key(name):
    """Sort key that orders filenames numerically.

    e.g. chapter-2 < chapter-10, chapter-1-2 < chapter-1-10 < chapter-2-1
    """
    parts = re.split(r"(\d+)", name)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def get_section_type_from_id(section_id):
    """Infer section_type from a section id string.

    Examples:
      "book-1"       -> "book"
      "chapter-1"    -> "chapter"
      "chapter-1-2"  -> "chapter"
      "series-1"     -> "part"
      "preface"      -> "preface"
      "conclusion"   -> "conclusion"
      "appendix-1"   -> "appendix"
    """
    if not section_id:
        return "chapter"
    # Strip trailing number (e.g. "appendix-1" -> "appendix")
    base = re.sub(r"-\d+(-\d+)*$", "", section_id)
    return SECTION_TYPE_MAP.get(base, "chapter")


def get_section_type_from_epub_type(etype):
    """Infer section_type from epub:type token list."""
    tokens = etype.split()
    if "part" in tokens:
        return "part"
    if "division" in tokens:
        return "book"  # SE uses division for book-level containers in some works
    if "chapter" in tokens:
        return "chapter"
    if "preface" in tokens:
        return "preface"
    if "introduction" in tokens:
        return "introduction"
    if "conclusion" in tokens:
        return "conclusion"
    if "appendix" in tokens:
        return "appendix"
    return None


def extract_label_and_title(head_title_text, section_id):
    """Extract (label, title) from the <head><title> element text.

    Patterns handled:
      "Book I: Admonitions Profitable..."  -> ("Book I", "Admonitions Profitable...")
      "Part II: On the Creature..."        -> ("Part II", "On the Creature...")
      "I: Introduction in Defence..."     -> ("I", "Introduction in Defence...")
      "First Series"                       -> (None, "First Series")
      "Conclusion"                         -> (None, "Conclusion")
      "Book I"                             -> ("Book I", None)
    """
    t = head_title_text.strip() if head_title_text else ""
    if not t:
        return None, None

    # Pattern: "Book/Part/Series + Roman: Title"
    m = re.match(r"^((?:Book|Part|Series)\s+[IVXLCDM]+):\s*(.+)$", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Pattern: "Book/Part/Series + Roman" (no subtitle)
    m = re.match(r"^((?:Book|Part|Series)\s+[IVXLCDM]+)$", t)
    if m:
        return m.group(1).strip(), None

    # Pattern: "Roman: Title" (chapter ordinal prefix)
    m = re.match(r"^([IVXLCDM]{1,8}):\s*(.+)$", t)
    if m and is_roman(m.group(1)):
        return m.group(1).strip(), m.group(2).strip()

    # No structural pattern -- title as-is
    return None, t


def is_roman(s):
    """Return True if s looks like a Roman numeral."""
    return bool(re.match(r"^[IVXLCDM]+$", s.upper())) and len(s) <= 8


def parse_section_file(xhtml_path):
    """Parse a single XHTML file and return a section dict.

    Returns a dict with:
      section_id, parent_id, section_type, label, title,
      content_blocks, is_container, body_epub_type
    """
    root = parse_xhtml(xhtml_path)

    # Extract <head><title>
    head = root.find(h("head"))
    head_title = ""
    if head is not None:
        title_elem = head.find(h("title"))
        if title_elem is not None and title_elem.text:
            head_title = title_elem.text.strip()

    # Find body
    body = root.find(h("body"))
    if body is None:
        return None

    body_etype = epub_type(body)

    # Find main section (first direct child section of body)
    main_section = None
    for child in body:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "section":
            main_section = child
            break

    if main_section is None:
        return None

    section_id = main_section.get("id", xhtml_path.stem)
    parent_id = main_section.get("data-parent")
    section_etype = epub_type(main_section)

    # Determine section_type
    section_type = get_section_type_from_id(section_id)
    # Override with epub:type if more specific
    from_etype = get_section_type_from_epub_type(section_etype)
    if from_etype and section_type == "chapter":
        section_type = from_etype

    # Extract label and title
    label, title = extract_label_and_title(head_title, section_id)

    # Extract content blocks
    content_blocks = extract_blocks_from_section(main_section)

    # A section is a pure container if it has no content_blocks
    is_container = len(content_blocks) == 0

    return {
        "section_id": section_id,
        "parent_id": parent_id,
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "is_container": is_container,
        "body_epub_type": body_etype,
    }


# ---------------------------------------------------------------------------
# Structured text processing
# ---------------------------------------------------------------------------

def build_section_hierarchy(parsed_files):
    """Build a recursive section tree from flat list of parsed file dicts.

    Returns a list of root-level section dicts (OCD schema format).
    """
    # Build lookup: section_id -> parsed file
    by_id = {}
    for pf in parsed_files:
        sid = pf["section_id"]
        if sid in by_id:
            # Duplicate ID -- skip (shouldn't happen in well-formed SE repos)
            continue
        by_id[sid] = pf

    # Assign children to parents
    roots = []
    children_map = {}  # parent_id -> [child section_id in order]
    for pf in parsed_files:
        pid = pf["parent_id"]
        if pid:
            children_map.setdefault(pid, []).append(pf["section_id"])
        else:
            roots.append(pf["section_id"])

    def make_section(sid):
        pf = by_id[sid]
        sec = {
            "section_type": pf["section_type"],
            "label": pf["label"],
            "title": pf["title"],
        }
        # Only include content_blocks if non-empty (leaf) or if the section
        # has content alongside children (e.g. Pilgrim's Progress parts)
        blocks = pf["content_blocks"]
        if blocks:
            sec["content_blocks"] = blocks
            all_text = " ".join(blocks)
            sec["word_count"] = len(all_text.split()) if all_text.strip() else 0
        else:
            sec["content_blocks"] = []
            sec["word_count"] = 0

        # Attach scripture_references placeholder (empty -- enrichment step)
        sec["scripture_references"] = []

        # Recurse into children
        child_ids = children_map.get(sid, [])
        if child_ids:
            sec["children"] = [make_section(cid) for cid in child_ids if cid in by_id]
        else:
            sec["children"] = []

        return sec

    sections = []
    for sid in roots:
        if sid in by_id:
            sections.append(make_section(sid))

    return sections


def process_structured_text(se_id, config, dry_run=False, list_files=False):
    """Parse a structured_text title and return (sections, stats) or raise."""
    text_dir = RAW_DIR / se_id / "src" / "epub" / "text"
    if not text_dir.exists():
        raise RuntimeError(f"Text dir not found: {text_dir}")

    xhtml_files = sorted(
        [f for f in text_dir.glob("*.xhtml")
         if f.stem not in SKIP_STEMS and not f.stem.startswith(SKIP_PREFIXES)],
        key=lambda f: natural_sort_key(f.stem),
    )

    if not xhtml_files:
        raise RuntimeError(f"No XHTML files found in {text_dir}")

    if list_files:
        print(f"  {len(xhtml_files)} content files:")
        for xf in xhtml_files:
            print(f"    {xf.name}")
        return None, None

    expected = config.get("expected_count")
    if expected is not None and len(xhtml_files) != expected:
        print(
            f"  WARNING: expected {expected} files but found {len(xhtml_files)} "
            f"-- check SKIP_STEMS/SKIP_PREFIXES filter"
        )

    print(f"  Found {len(xhtml_files)} content files")

    parsed = []
    errors = 0
    for xf in xhtml_files:
        try:
            section = parse_section_file(xf)
        except Exception as exc:
            print(f"  ERROR parsing {xf.name}: {exc} -- skipping")
            errors += 1
            continue
        if section is None:
            continue
        parsed.append(section)
        if dry_run and len(parsed) >= 3:
            print(f"  dry-run: stopping after 3 files")
            break

    sections = build_section_hierarchy(parsed)

    # Stats
    total_blocks = 0
    total_words = 0

    def count_blocks(sec_list):
        nonlocal total_blocks, total_words
        for sec in sec_list:
            total_blocks += len(sec.get("content_blocks", []))
            total_words += sec.get("word_count", 0)
            count_blocks(sec.get("children", []))

    count_blocks(sections)

    stats = {
        "files_parsed": len(parsed),
        "files_errored": errors,
        "sections": len(sections),
        "total_blocks": total_blocks,
        "total_words": total_words,
    }

    return sections, stats


# ---------------------------------------------------------------------------
# Sermon processing
# ---------------------------------------------------------------------------

def extract_scripture_reference(header_elem):
    """Extract primary scripture reference from a sermon <header>.

    SE sermon headers contain:
      <blockquote epub:type="epigraph">
        <p>...passage text...</p>
        <cite>Mark 9:33-37</cite>
      </blockquote>

    Returns {"raw": "Mark 9:33-37", "osis": []} or None.
    The osis list is left empty -- OSIS normalization is a separate enrichment step.
    """
    for blockquote in header_elem.iter(h("blockquote")):
        etype = epub_type(blockquote)
        if "epigraph" not in etype:
            continue
        for cite in blockquote.iter(h("cite")):
            raw = clean_reference_text(clean_text(get_text_content(cite)))
            if raw:
                return {"raw": raw, "osis": []}
    return None


def get_series_name(section_id):
    """Return the series name from a section id like 'series-1'."""
    m = re.match(r"series-(\d+)$", section_id)
    if not m:
        return None
    series_num = int(m.group(1))
    names = {1: "First Series", 2: "Second Series", 3: "Third Series"}
    return names.get(series_num, f"Series {series_num}")


def process_sermon_collection(se_id, config, dry_run=False, list_files=False):
    """Parse a sermon collection and return (sermons, stats) or raise."""
    text_dir = RAW_DIR / se_id / "src" / "epub" / "text"
    if not text_dir.exists():
        raise RuntimeError(f"Text dir not found: {text_dir}")

    # Sermon files: chapter-N-M.xhtml (skip series-N.xhtml which are containers)
    # Series containers have no body content -- detected by stem pattern
    all_files = sorted(
        [f for f in text_dir.glob("*.xhtml")
         if f.stem not in SKIP_STEMS and not f.stem.startswith(SKIP_PREFIXES)],
        key=lambda f: natural_sort_key(f.stem),
    )

    # Separate series headers from sermon content files
    series_headers = {}  # section_id -> series_name
    sermon_files = []
    for xf in all_files:
        if re.match(r"series-\d+$", xf.stem):
            series_headers[xf.stem] = get_series_name(xf.stem)
        else:
            sermon_files.append(xf)

    if list_files:
        print(f"  {len(sermon_files)} sermon files (+ {len(series_headers)} series containers):")
        for xf in sermon_files:
            print(f"    {xf.name}")
        return None, None

    expected = config.get("expected_count")
    if expected is not None and len(sermon_files) != expected:
        print(
            f"  WARNING: expected {expected} sermons but found {len(sermon_files)} "
            f"-- check SKIP_STEMS/SKIP_PREFIXES filter"
        )

    print(f"  Found {len(sermon_files)} sermon files")

    # Build mapping: child section_id -> series_name via data-parent
    # We need to read each sermon file's data-parent to assign series
    sermons = []
    errors = 0
    skipped = 0

    for i, xf in enumerate(sermon_files):
        if dry_run and i >= 3:
            print(f"  dry-run: stopping after 3 sermons")
            break
        try:
            root = parse_xhtml(xf)
        except Exception as exc:
            print(f"  ERROR parsing {xf.name}: {exc} -- skipping")
            errors += 1
            continue

        head = root.find(h("head"))
        head_title = ""
        if head is not None:
            title_elem = head.find(h("title"))
            if title_elem is not None and title_elem.text:
                head_title = title_elem.text.strip()

        body = root.find(h("body"))
        if body is None:
            skipped += 1
            continue

        main_section = None
        for child in body:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "section":
                main_section = child
                break

        if main_section is None:
            skipped += 1
            continue

        section_id = main_section.get("id", xf.stem)
        parent_id = main_section.get("data-parent")

        # Get series name from parent mapping
        series_name = series_headers.get(parent_id) if parent_id else None

        # Extract title from header h3 or head title
        title = head_title
        header_elem = main_section.find(h("header"))
        if header_elem is not None:
            h3 = header_elem.find(f".//{h('h3')}")
            if h3 is not None:
                etype = epub_type(h3)
                if "title" in etype:
                    t = clean_text(get_text_content(h3))
                    if t:
                        title = t

        # Extract primary scripture reference from header epigraph
        primary_ref = None
        if header_elem is not None:
            primary_ref = extract_scripture_reference(header_elem)

        # Extract content blocks (paragraphs after the header)
        content_blocks = []
        for child in main_section:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "header":
                continue
            if local == "p":
                text = clean_text(get_text_content(child))
                if text:
                    content_blocks.append(text)
            elif local == "section":
                # Nested section -- flatten into blocks
                inner_blocks = extract_blocks_from_section(child)
                content_blocks.extend(inner_blocks)

        if not content_blocks:
            skipped += 1
            continue

        all_text = " ".join(content_blocks)
        word_count = len(all_text.split()) if all_text.strip() else 0

        # Sermon ID: use the section id stem (e.g. "1-1", "2-12")
        sermon_id = re.sub(r"^chapter-", "", section_id)

        sermons.append({
            "collection_id": config["collection_id"],
            "sermon_id": sermon_id,
            "series": series_name,
            "title": title,
            "primary_reference": primary_ref,
            "primary_reference_text": None,
            "content_blocks": content_blocks,
            "date_preached": None,
            "location": None,
            "word_count": word_count,
        })

    word_counts = [s["word_count"] for s in sermons]
    stats = {
        "files_parsed": len(sermon_files),
        "sermons_extracted": len(sermons),
        "files_errored": errors,
        "files_skipped": skipped,
        "no_ref": sum(1 for s in sermons if s["primary_reference"] is None),
        "total_words": sum(word_counts),
        "min_words": min(word_counts) if word_counts else 0,
        "median_words": sorted(word_counts)[len(word_counts) // 2] if word_counts else 0,
        "max_words": max(word_counts) if word_counts else 0,
    }

    return sermons, stats


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def report_structured_text_quality(sections, stats):
    """Print quality stats for a structured_text output."""
    print(f"  Files parsed:     {stats['files_parsed']}")
    print(f"  Parse errors:     {stats['files_errored']}")
    print(f"  Root sections:    {stats['sections']}")
    print(f"  Content blocks:   {stats['total_blocks']}")
    print(f"  Total words:      {stats['total_words']}")

    if stats["files_errored"] > 0:
        print(f"  WARNING: {stats['files_errored']} files failed to parse")
    if stats["total_blocks"] == 0:
        print(f"  WARNING: No content blocks extracted -- check parser")
    if stats["total_words"] < 1000:
        print(f"  WARNING: Very low word count ({stats['total_words']}) -- possible extraction failure")
    if stats["sections"] == 0:
        print(f"  WARNING: No root sections -- structure may be flat or all files have data-parent")


def report_sermon_quality(sermons, stats):
    """Print quality stats for a sermon collection output."""
    print(f"  Sermon files:     {stats['files_parsed']}")
    print(f"  Sermons extracted:{stats['sermons_extracted']}")
    print(f"  Parse errors:     {stats['files_errored']}")
    print(f"  Skipped (empty):  {stats['files_skipped']}")
    print(f"  No scripture ref: {stats['no_ref']}")
    print(f"  Total words:      {stats['total_words']}")
    print(
        f"  Word count:       min={stats['min_words']} "
        f"median={stats['median_words']} max={stats['max_words']}"
    )

    if stats["sermons_extracted"] == 0:
        print(f"  WARNING: No sermons extracted")
    if stats["no_ref"] > stats["sermons_extracted"] // 2:
        print(f"  WARNING: More than half of sermons have no scripture reference")


# ---------------------------------------------------------------------------
# Output building
# ---------------------------------------------------------------------------

def build_meta(config, data_hash, processing_date):
    """Build the OCD metadata envelope from source config."""
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
        "schema_type": config["schema_type"],
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
                f"build/parsers/standard_ebooks.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": config.get("notes"),
        },
    }


# ---------------------------------------------------------------------------
# Single-title processing
# ---------------------------------------------------------------------------

def process_title(se_id, dry_run=False, list_files=False):
    """Load config and process one SE title. Returns True on success."""
    config_path = SOURCES_DIR / se_id / "config.json"
    if not config_path.exists():
        print(f"  ERROR: Config not found: {config_path}")
        return False

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    schema_type = config.get("schema_type")
    output_file = REPO_ROOT / config["output_file"]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"Title:   {config['title']}")
    print(f"Author:  {config['author']}")
    print(f"Type:    {schema_type}")
    print(f"Output:  {output_file}")
    if dry_run:
        print("Mode:    dry-run (first 3 files, no write)")

    if schema_type == "structured_text":
        sections, stats = process_structured_text(se_id, config, dry_run=dry_run, list_files=list_files)
        if list_files:
            return True

        data_payload = {
            "work_id": config["resource_id"],
            "work_kind": config.get("work_kind", "theological-work"),
            "sections": sections,
        }
        data_bytes = json.dumps(sections, ensure_ascii=False, sort_keys=True).encode("utf-8")
        data_hash = hashlib.sha256(data_bytes).hexdigest()

        meta = build_meta(config, data_hash, processing_date)
        output = {"meta": meta, "data": data_payload}

        print()
        report_structured_text_quality(sections, stats)

    elif schema_type == "sermon":
        sermons, stats = process_sermon_collection(se_id, config, dry_run=dry_run, list_files=list_files)
        if list_files:
            return True

        data_bytes = json.dumps(sermons, ensure_ascii=False, sort_keys=True).encode("utf-8")
        data_hash = hashlib.sha256(data_bytes).hexdigest()

        meta = build_meta(config, data_hash, processing_date)
        output = {"meta": meta, "data": sermons}

        print()
        report_sermon_quality(sermons, stats)

    else:
        print(f"  ERROR: Unknown schema_type '{schema_type}'")
        return False

    if dry_run:
        print()
        print("--- Sample output (dry-run) ---")
        if schema_type == "structured_text":
            # Show first section -- use ensure_ascii=True to avoid cp1252 console crash
            if sections:
                sample = {"meta": meta, "data": {"work_id": data_payload["work_id"],
                                                  "work_kind": data_payload["work_kind"],
                                                  "sections": sections[:1]}}
                print(json.dumps(sample, ensure_ascii=True, indent=2)[:2000])
        else:
            if output["data"]:
                print(json.dumps(output["data"][:1], ensure_ascii=True, indent=2)[:2000])
        print("dry-run complete -- no files written")
        return True

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = output_file.stat().st_size / 1024
    print(f"\nWrote {output_file.name} ({size_kb:.0f} KB)")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse Standard Ebooks XHTML into OCD schema (structured_text or sermon)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--id",
        dest="se_id",
        help="Standard Ebooks identifier (e.g. john-bunyan_the-pilgrims-progress)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all known SE titles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 3 files per title and print sample -- do not write",
    )
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="Print the filtered file list for each title and exit -- do not extract",
    )
    args = parser.parse_args()

    start_time = time.time()

    if args.se_id:
        ids_to_process = [args.se_id]
    else:
        ids_to_process = ALL_SE_IDS

    successes = 0
    failures = 0

    for i, se_id in enumerate(ids_to_process, 1):
        print()
        print(f"=== [{i}/{len(ids_to_process)}] {se_id} ===")
        try:
            ok = process_title(se_id, dry_run=args.dry_run, list_files=args.list_files)
            if ok:
                successes += 1
            else:
                failures += 1
        except Exception as exc:
            print(f"  FATAL ERROR: {exc}")
            failures += 1

    elapsed = time.time() - start_time
    print()
    print(f"Done: {successes} succeeded, {failures} failed ({elapsed:.1f}s)")

    if failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
