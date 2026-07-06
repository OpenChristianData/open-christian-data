"""ccel_hodge_systematic.py
Parser for Hodge's Systematic Theology (3 vols, 1872-1873) from CCEL ThML XML.

Downloads theology{1,2,3}.xml from CCEL once per volume, then parses the full
section tree (parts > chapters > sections) into three OCD structured_text JSON files.

Sources:
  https://www.ccel.org/ccel/hodge/theology1.xml  (Vol. 1: Introduction + Part I)
  https://www.ccel.org/ccel/hodge/theology2.xml  (Vol. 2: Part II + Part III)
  https://www.ccel.org/ccel/hodge/theology3.xml  (Vol. 3: Part III cont. + Part IV)

Source permission: CCEL confirmed OK to parse (Quincy, 2026-04-01).
robots.txt: crawl-delay 10 for all agents (checked 2026-04-12).

XML structure (inspected 2026-04-12 via direct CCEL download):
  Root element: <ThML> with no namespaces; DOCTYPE references external DTD (stripped).
  Header: <ThML.head> (metadata, skipped)
  Body: <ThML.body>
    <div1 id="i">   -- title page front matter, skipped
    <div1 id="ii">  -- table of contents, skipped
    <div1 id="iii"> -- Part label (Introduction / Part II / Part III / Part III cont.)
      Children before first div2: heading elements with PART N. / INTRODUCTION. label
      <div1> element sometimes has a <div> child with "PART I. THEOLOGY PROPER." text
      <div2 id="iii.i"> -- Chapter
        <h2> "CHAPTER I."
        <h3> "CHAPTER TITLE"
        <p>  intro paragraph(s) directly under div2 (before div3s)
        <div3 id="iii.i.i"> -- Section
          <p>  "sec 1. Section Title." (first <p> if starts with sec-pattern)
          <p>  content paragraphs...
          <scripRef osisRef="Bible:Book.ch.v"> inline scripture references
          <note> footnotes -- skipped from content_blocks
          <pb>  page breaks -- skipped
    <div1 id="iv">  -- Second content part per volume
    <div1 id="v">   -- Indexes, skipped
  Vol 1 div1 mapping:
    iii -> Introduction (6 chapters on theological method)
    iv  -> Part I: Theology Proper (13 chapters on God)
  Vol 2 div1 mapping:
    iii -> Part II: Anthropology (9 chapters on man)
    iv  -> Part III: Soteriology (14 chapters on salvation)
  Vol 3 div1 mapping:
    iii -> Part III: Soteriology (chapters XV-XX, continued from vol 2)
    iv  -> Part IV: Eschatology (4 chapters on last things)

  Section heading pattern: first <p> of div3 often starts with "sec N. Title."
  where sec is the section-sign character (U+00A7). This p is parsed into
  label="sec N" and title="Title" and excluded from content_blocks.

Usage:
    py -3 build/parsers/ccel_hodge_systematic.py --dry-run --volume 1
    py -3 build/parsers/ccel_hodge_systematic.py
    py -3 build/parsers/ccel_hodge_systematic.py --volume 2
    py -3 build/parsers/ccel_hodge_systematic.py --force-download
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request  # standards: download only
from datetime import datetime, timezone
from xml.etree import ElementTree as ET
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.text_utils import smart_title  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "hodge"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_hodge_systematic.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.1.0"

UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

# Per-volume configuration: URLs, file paths, identifiers, and part layout.
# "FALLBACK" label means the XML has no explicit PART heading -- inferred from content.
# Each volume has exactly 2 content div1 elements (id=iii and id=iv) -- asserted on parse.
VOLUME_CONFIG = {
    1: {
        "url": "https://www.ccel.org/ccel/hodge/theology1.xml",
        "raw_file": RAW_DIR / "theology1.xml",
        "output_file": OUTPUT_DIR / "hodge-systematic-theology-vol-1.json",
        "work_id": "hodge-systematic-theology-vol-1",
        "source_hash": "sha256:f01ffb5235657a0b21f56a1a4eb7ef95b836ba9d907f9acd1402e8a6fe450fc6",
        "download_date": "2026-04-12",
        # div1 ids to skip (front matter, contents, indexes)
        "skip_ids": {"i", "ii", "v"},
        # Fallback part labels when XML heading extraction fails
        # key = div1 id, value = (label, title)
        "fallback_parts": {
            "iii": ("Introduction", "Introduction"),
        },
        # Expected number of content parts (div1 elements not in skip_ids)
        "expected_parts": 2,
    },
    2: {
        "url": "https://www.ccel.org/ccel/hodge/theology2.xml",
        "raw_file": RAW_DIR / "theology2.xml",
        "output_file": OUTPUT_DIR / "hodge-systematic-theology-vol-2.json",
        "work_id": "hodge-systematic-theology-vol-2",
        "source_hash": "sha256:52a43581dcb7b75a6903c89c8e2496b8d754bdbcd6fa751ecaa4f065e933d942",
        "download_date": "2026-04-12",
        "skip_ids": {"i", "ii", "v"},
        "fallback_parts": {},
        "expected_parts": 2,
    },
    3: {
        "url": "https://www.ccel.org/ccel/hodge/theology3.xml",
        "raw_file": RAW_DIR / "theology3.xml",
        "output_file": OUTPUT_DIR / "hodge-systematic-theology-vol-3.json",
        "work_id": "hodge-systematic-theology-vol-3",
        "source_hash": "sha256:aeb92566e8ce5019f6f43c56585538c67bafcea177d9d6f1df286006f24dda54",
        "download_date": "2026-04-12",
        "skip_ids": {"i", "ii", "v"},
        # Vol 3 div1 iii has no explicit PART heading; it is Part III continued from vol 2
        "fallback_parts": {
            "iii": ("Part III", "Soteriology"),
        },
        "expected_parts": 2,
    },
}

# Shared work metadata (same for all 3 volumes)
WORK_META = {
    "author": "Charles Hodge",
    "author_birth_year": 1797,
    "author_death_year": 1878,
    "contributors": [],
    "original_publication_year": 1872,
    "language": "en",
    "original_language": "en",
    "tradition": ["reformed", "presbyterian", "evangelical"],
    "tradition_notes": (
        "Hodge's Systematic Theology is the defining 19th-century Reformed systematic."
        " Princeton Seminary tradition."
    ),
    "era": "modern",
    "audience": "scholarly",
    "license": "public-domain",
    "schema_type": "structured_text",
    "schema_version": SCHEMA_VERSION,
    "completeness": "full",
}


def _validate_configs() -> None:
    slug = "hodge-systematic-theology"
    for tradition in WORK_META.get("tradition", []):
        assert tradition in STRUCTURED_TEXT__META__TRADITION, f"{slug}: invalid tradition value {tradition!r}"
    assert (era := WORK_META["era"]) in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era value {era!r}"
    assert (audience := WORK_META["audience"]) in STRUCTURED_TEXT__META__AUDIENCE, (
        f"{slug}: invalid audience value {audience!r}"
    )
    assert (completeness := WORK_META["completeness"]) in STRUCTURED_TEXT__META__COMPLETENESS, (
        f"{slug}: invalid completeness value {completeness!r}"
    )


_validate_configs()

# ThML HTML entities that are not valid XML without the external DTD.
# XML-safe entities (&amp; &lt; &gt; &quot; &apos;) are handled separately.
THML_ENTITY_MAP = {
    "&mdash;": "\u2014",
    "&ndash;": "\u2013",
    "&lsquo;": "\u2018",
    "&rsquo;": "\u2019",
    "&ldquo;": "\u201c",
    "&rdquo;": "\u201d",
    "&nbsp;": "\u00a0",
    "&hellip;": "\u2026",
    "&emdash;": "\u2014",
    "&copy;": "\u00a9",
    "&reg;": "\u00ae",
    "&trade;": "\u2122",
    "&deg;": "\u00b0",
    "&para;": "\u00b6",
    "&sect;": "\u00a7",
    "&dagger;": "\u2020",
    "&Dagger;": "\u2021",
    "&bull;": "\u2022",
    "&prime;": "\u2032",
    "&Prime;": "\u2033",
    "&oline;": "\u203e",
    "&frasl;": "\u2044",
    "&spades;": "\u2660",
    "&clubs;": "\u2663",
    "&hearts;": "\u2665",
    "&diams;": "\u2666",
    "&agrave;": "\u00e0",
    "&aacute;": "\u00e1",
    "&egrave;": "\u00e8",
    "&eacute;": "\u00e9",
    "&iacute;": "\u00ed",
    "&oacute;": "\u00f3",
    "&uacute;": "\u00fa",
    "&Agrave;": "\u00c0",
    "&Aacute;": "\u00c1",
    "&Egrave;": "\u00c8",
    "&Eacute;": "\u00c9",
    "&Iacute;": "\u00cd",
    "&Oacute;": "\u00d3",
    "&Uacute;": "\u00da",
    "&auml;": "\u00e4",
    "&euml;": "\u00eb",
    "&iuml;": "\u00ef",
    "&ouml;": "\u00f6",
    "&uuml;": "\u00fc",
    "&Auml;": "\u00c4",
    "&Euml;": "\u00cb",
    "&Iuml;": "\u00cf",
    "&Ouml;": "\u00d6",
    "&Uuml;": "\u00dc",
    "&aelig;": "\u00e6",
    "&AElig;": "\u00c6",
    "&ccedil;": "\u00e7",
    "&Ccedil;": "\u00c7",
    "&ntilde;": "\u00f1",
    "&Ntilde;": "\u00d1",
    "&thorn;": "\u00fe",
    "&THORN;": "\u00de",
    "&eth;": "\u00f0",
    "&ETH;": "\u00d0",
    "&oslash;": "\u00f8",
    "&Oslash;": "\u00d8",
    "&aring;": "\u00e5",
    "&Aring;": "\u00c5",
    "&szlig;": "\u00df",
    "&laquo;": "\u00ab",
    "&raquo;": "\u00bb",
    "&iexcl;": "\u00a1",
    "&iquest;": "\u00bf",
    "&pound;": "\u00a3",
    "&euro;": "\u20ac",
    "&yen;": "\u00a5",
    "&cent;": "\u00a2",
    "&alpha;": "\u03b1",
    "&beta;": "\u03b2",
    "&gamma;": "\u03b3",
    "&delta;": "\u03b4",
    "&epsilon;": "\u03b5",
    "&zeta;": "\u03b6",
    "&eta;": "\u03b7",
    "&theta;": "\u03b8",
    "&iota;": "\u03b9",
    "&kappa;": "\u03ba",
    "&lambda;": "\u03bb",
    "&mu;": "\u03bc",
    "&nu;": "\u03bd",
    "&xi;": "\u03be",
    "&omicron;": "\u03bf",
    "&pi;": "\u03c0",
    "&rho;": "\u03c1",
    "&sigma;": "\u03c3",
    "&tau;": "\u03c4",
    "&upsilon;": "\u03c5",
    "&phi;": "\u03c6",
    "&chi;": "\u03c7",
    "&psi;": "\u03c8",
    "&omega;": "\u03c9",
    "&Alpha;": "\u0391",
    "&Beta;": "\u0392",
    "&Gamma;": "\u0393",
    "&Delta;": "\u0394",
    "&Epsilon;": "\u0395",
    "&Zeta;": "\u0396",
    "&Eta;": "\u0397",
    "&Theta;": "\u0398",
    "&Iota;": "\u0399",
    "&Kappa;": "\u039a",
    "&Lambda;": "\u039b",
    "&Mu;": "\u039c",
    "&Nu;": "\u039d",
    "&Xi;": "\u039e",
    "&Omicron;": "\u039f",
    "&Pi;": "\u03a0",
    "&Rho;": "\u03a1",
    "&Sigma;": "\u03a3",
    "&Tau;": "\u03a4",
    "&Upsilon;": "\u03a5",
    "&Phi;": "\u03a6",
    "&Chi;": "\u03a7",
    "&Psi;": "\u03a8",
    "&Omega;": "\u03a9",
}

XML_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}

# Section-sign heading: "\xa7 N. Title" (sect is U+00A7, also written as "&sect;")
# Also matches bare "N. Title" (Arabic numeral without sect sign -- used in Vol 1
# Introduction chapters III/IV for section 4 of each).
# Only applied to the first <p> of a div3, so false positives on numbered list items
# within sections are not possible.
SECTION_HEADING_RE = re.compile(
    r"^(?:\u00a7\s*(\d+)|(\d+))\.\s+(.+)$", re.DOTALL
)

# Part headings in pre-chapter div1 content
PART_HEADING_RE = re.compile(
    r"PART\s+(I{1,3}V?|VI{0,3}|IV|V)\s*[.\u2014\u2013]?\s*(.*)",
    re.IGNORECASE,
)
INTRO_HEADING_RE = re.compile(r"INTRODUCTION\.?\s*$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_volume(vol_num: int, force: bool = False) -> None:
    """Download a single volume XML from CCEL if not already cached."""
    cfg = VOLUME_CONFIG[vol_num]
    dest = cfg["raw_file"]
    if dest.exists() and not force:
        print(f"  Source cached: {dest.name} ({dest.stat().st_size // 1024} KB)")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = cfg["url"]
    print(f"  Downloading {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with open(dest, "wb") as fh:
            fh.write(data)
        actual_hash = "sha256:" + hashlib.sha256(data).hexdigest()
        print(f"  Downloaded {len(data) // 1024} KB -> {dest.name}")
        # Warn if hash differs from recorded value (content changed upstream)
        expected = cfg["source_hash"]
        if actual_hash != expected:
            print(
                f"  WARNING: hash mismatch for vol {vol_num}. "
                f"Expected {expected}, got {actual_hash}"
            )
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for vol {vol_num}: {exc}. "
            "Check network access or use --force-download to retry."
        ) from exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _replace_entity(match: re.Match) -> str:
    """Replace a named HTML entity if known; drop unknown ones to avoid parse errors."""
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    # Unknown entity -- drop to avoid ElementTree parse failure
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """
    Prepare raw ThML bytes for ElementTree:
    1. Decode bytes -- UTF-8 with cp1252 fallback for Windows smart quotes.
    2. Strip DOCTYPE declaration (prevents external DTD fetch attempt).
    3. Replace HTML entities with Unicode equivalents.
    """
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    # Strip DOCTYPE (may span multiple lines)
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    # Replace named HTML entities
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

# Tags to skip entirely when collecting text content
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector"])


def get_all_text(elem) -> str:
    """Recursively collect all text content, skipping footnote/metadata tags."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in _SKIP_TAGS:
            # Still capture tail text (text after the closing tag)
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def clean_text(text: str) -> str:
    """Collapse internal whitespace and strip leading/trailing whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def get_scriptrefs(elem) -> list:
    """
    Collect all scripture references from <scripRef> elements within elem.
    Returns a list of {"raw": str, "osis": [str, ...]} dicts.
    """
    refs = []
    for sr in elem.iter("scripRef"):
        osis_raw = sr.get("osisRef", "")
        raw_text = clean_text(get_all_text(sr))
        osis_list = []
        for part in osis_raw.split():
            cleaned = part.replace("Bible:", "").strip()
            if cleaned:
                osis_list.append(cleaned)
        if raw_text or osis_list:
            refs.append({"raw": raw_text, "osis": osis_list})
    return refs


def count_words(blocks: list) -> int:
    """Count words across a list of text strings."""
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Part label extraction
# ---------------------------------------------------------------------------

def extract_part_label_title(div1, vol_num: int) -> tuple:
    """
    Extract (label, title) for a div1 content section.

    Looks at direct children before the first <div2> for:
    - <h2> INTRODUCTION. -> ("Introduction", "Introduction")
    - <h2> PART N. [+ optional <h3> TITLE] -> ("Part N", "Title")
    - <div> PART N. TITLE. -> ("Part N", "Title")

    Falls back to VOLUME_CONFIG fallback_parts if nothing is found.
    """
    d1id = div1.get("id", "")
    label = ""
    title = ""
    pending_part = ""  # stores "Part N" while waiting for h3 title

    for ch in div1:
        if ch.tag == "div2":
            break
        if ch.tag not in ("h1", "h2", "h3", "h4", "title", "div", "p"):
            continue
        text = clean_text(get_all_text(ch))
        if not text:
            continue

        # INTRODUCTION heading
        if INTRO_HEADING_RE.match(text):
            return "Introduction", "Introduction"

        # PART N. heading (with optional inline title)
        m = PART_HEADING_RE.match(text)
        if m:
            roman = m.group(1).upper()
            part_title_inline = m.group(2).strip().rstrip(".")
            pending_part = f"Part {roman}"
            if part_title_inline:
                # e.g. "PART I. THEOLOGY PROPER." from a <div>
                label = pending_part
                title = smart_title(part_title_inline)
                return label, title
            else:
                label = pending_part
            continue

        # h3 following a PART h2 -- use as part title
        if pending_part and ch.tag == "h3" and not title:
            title = smart_title(text.rstrip(".").strip())
            return label, title

    # Apply fallback if extraction found nothing
    if not label:
        fallback = VOLUME_CONFIG[vol_num]["fallback_parts"].get(d1id)
        if fallback:
            return fallback

    return label or "", title or ""


# ---------------------------------------------------------------------------
# Chapter label/title extraction
# ---------------------------------------------------------------------------

_CHAPTER_H2_RE = re.compile(r"^CHAPTER\s+(\w+)\.?\s*$", re.IGNORECASE)


def extract_chapter_label(div2) -> str:
    """Extract chapter label from <h2> inside div2, e.g. 'Chapter I'."""
    h2 = div2.find("h2")
    if h2 is not None:
        text = clean_text(get_all_text(h2))
        m = _CHAPTER_H2_RE.match(text)
        if m:
            return f"Chapter {m.group(1).upper()}"
        # Fallback: use cleaned h2 text without trailing period
        return text.rstrip(".").strip()
    return ""


def extract_chapter_title(div2) -> str:
    """Extract chapter title from <h3> inside div2."""
    h3 = div2.find("h3")
    if h3 is not None:
        return clean_text(get_all_text(h3)).rstrip(".")
    return ""


# ---------------------------------------------------------------------------
# Section (div3) parsing
# ---------------------------------------------------------------------------

def parse_section(div3) -> dict:
    """
    Parse a <div3> element into a section dict.

    If the first <p> matches the section-heading pattern (U+00A7 N. Title),
    it is extracted as label/title and excluded from content_blocks.
    All other <p> elements become content_blocks.
    <note> and <pb> elements are skipped.
    """
    label = ""
    title = ""
    content_blocks = []
    first_p_consumed = False

    for ch in div3:
        tag = ch.tag
        if tag in _SKIP_TAGS:
            continue
        if tag == "p":
            text = clean_text(get_all_text(ch))
            if not text:
                continue
            if not first_p_consumed:
                first_p_consumed = True
                # Check if this is a section heading (sec N. Title or N. Title)
                m = SECTION_HEADING_RE.match(text)
                if m:
                    # group(1) = digit from sec-sign form; group(2) = digit from bare form
                    num = m.group(1) or m.group(2)
                    label = f"\u00a7 {num}"
                    title = m.group(3).rstrip(".").strip()
                    continue  # do not add to content_blocks
            content_blocks.append(text)
        elif tag in ("div4", "div5"):
            # Rare deeper nesting -- collect paragraphs from nested divs
            for gch in ch:
                if gch.tag == "p":
                    text = clean_text(get_all_text(gch))
                    if text:
                        content_blocks.append(text)
                elif gch.tag not in _SKIP_TAGS and gch.tag not in ("h1", "h2", "h3", "h4"):
                    text = clean_text(get_all_text(gch))
                    if text:
                        content_blocks.append(text)
        # <h3>, <h4> sub-headings within a section become content blocks
        elif tag in ("h3", "h4"):
            text = clean_text(get_all_text(ch))
            if text:
                content_blocks.append(text)
        # <ul>/<li> lists -- collect as one block
        elif tag == "ul":
            items = []
            for li in ch.findall("li"):
                t = clean_text(get_all_text(li))
                if t:
                    items.append(t)
            if items:
                content_blocks.append("; ".join(items))

    scripture_refs = get_scriptrefs(div3)
    wc = count_words(content_blocks)

    return {
        "section_type": "section",
        "label": label or None,
        "title": title or None,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": wc,
        "children": [],
    }


# ---------------------------------------------------------------------------
# Chapter (div2) parsing
# ---------------------------------------------------------------------------

def parse_chapter(div2) -> dict:
    """
    Parse a <div2> element into a chapter dict.

    Structure:
      - h2: chapter label (e.g. "Chapter I")
      - h3: chapter title (e.g. "Origin of the Idea of God")
      - p: intro paragraphs directly under div2 (before first div3)
      - div3: section children
    """
    label = extract_chapter_label(div2)
    title = extract_chapter_title(div2)
    intro_blocks = []
    children = []

    for ch in div2:
        tag = ch.tag
        if tag in ("h2", "h3", "h1", "h4"):
            continue  # already extracted above
        if tag in _SKIP_TAGS:
            continue
        if tag == "p":
            # Collect only direct <p> children before any <div3> appears
            if not children:
                text = clean_text(get_all_text(ch))
                if text:
                    intro_blocks.append(text)
        elif tag == "div3":
            sec = parse_section(ch)
            children.append(sec)

    scripture_refs = get_scriptrefs(div2)
    own_wc = count_words(intro_blocks)
    total_wc = own_wc + sum(s["word_count"] for s in children)

    return {
        "section_type": "chapter",
        "label": label or None,
        "title": title or None,
        "content_blocks": intro_blocks,
        "scripture_references": scripture_refs,
        "word_count": total_wc,
        "children": children,
    }


# ---------------------------------------------------------------------------
# Part (div1) parsing
# ---------------------------------------------------------------------------

def parse_part(div1, vol_num: int) -> dict:
    """
    Parse a <div1> content element into a part dict.

    Extracts part label/title from pre-chapter headings, then parses
    all <div2> children as chapters.
    """
    label, title = extract_part_label_title(div1, vol_num)
    chapters = [parse_chapter(div2) for div2 in div1.findall("div2")]
    total_wc = sum(ch["word_count"] for ch in chapters)

    return {
        "section_type": "part",
        "label": label or None,
        "title": title or None,
        "content_blocks": [],
        "scripture_references": [],
        "word_count": total_wc,
        "children": chapters,
    }


# ---------------------------------------------------------------------------
# Volume parsing
# ---------------------------------------------------------------------------

def parse_volume(vol_num: int, dry_run: bool = False) -> dict:
    """
    Parse a single volume XML file into a structured_text data dict.

    Returns {"work_id": ..., "work_kind": ..., "sections": [...]}.
    Raises RuntimeError on parse failure or unexpected part count (PIPE-10).
    """
    cfg = VOLUME_CONFIG[vol_num]
    raw_file = cfg["raw_file"]
    skip_ids = cfg["skip_ids"]

    print(f"  Parsing {raw_file.name} ...")
    try:
        raw_bytes = raw_file.read_bytes()
    except OSError as exc:
        raise RuntimeError(
            f"Cannot read raw file for vol {vol_num}: {raw_file}. "
            f"Cause: {exc}. Ensure the file was downloaded successfully."
        ) from exc

    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse failed for vol {vol_num}: {exc}. "
            "The file may be corrupt -- try --force-download."
        ) from exc

    # Collect content div1 elements in document order
    sections = []
    total_div1s = 0
    for div1 in root.iter("div1"):
        d1id = div1.get("id", "")
        if d1id in skip_ids:
            continue
        total_div1s += 1
        part = parse_part(div1, vol_num)
        print(f"  Parsed part {total_div1s}: {part['label']} ({len(part['children'])} chapters)")
        sections.append(part)
        if dry_run:
            # Only parse first part on dry run
            break

    # PIPE-10: assert expected part count before returning (dry-run skips this)
    if not dry_run:
        expected = cfg["expected_parts"]
        if len(sections) != expected:
            raise RuntimeError(
                f"Vol {vol_num}: expected {expected} content parts, "
                f"got {len(sections)}. "
                "XML structure may have changed -- check raw file."
            )

    work_id = cfg["work_id"]
    return {
        "work_id": work_id,
        "work_kind": "systematic-theology",
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(vol_num: int) -> dict:
    """Build the meta envelope for a volume."""
    cfg = VOLUME_CONFIG[vol_num]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    vol_titles = {1: "Vol. 1", 2: "Vol. 2", 3: "Vol. 3"}
    return {
        "id": cfg["work_id"],
        "title": f"Systematic Theology, {vol_titles[vol_num]}",
        "author": WORK_META["author"],
        "author_birth_year": WORK_META["author_birth_year"],
        "author_death_year": WORK_META["author_death_year"],
        "contributors": normalize_contributors(WORK_META["contributors"]),
        "original_publication_year": WORK_META["original_publication_year"],
        "language": WORK_META["language"],
        "original_language": WORK_META["original_language"],
        "tradition": WORK_META["tradition"],
        "tradition_notes": WORK_META["tradition_notes"],
        "era": WORK_META["era"],
        "audience": WORK_META["audience"],
        "license": WORK_META["license"],
        "schema_type": WORK_META["schema_type"],
        "schema_version": WORK_META["schema_version"],
        "completeness": WORK_META["completeness"],
        "provenance": {
            "source_url": cfg["url"],
            "source_format": "ThML XML",
            "source_edition": (
                "Christian Classics Ethereal Library (CCEL) ThML edition. "
                "Original edition: New York: Scribner, Armstrong, 1872-1873."
            ),
            "download_date": cfg["download_date"],
            "source_hash": cfg["source_hash"],
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_hodge_systematic.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents. "
                "DOCTYPE stripped before parsing. "
                "Footnotes (<note>) and page breaks (<pb>) excluded from content. "
                "robots.txt crawl-delay 10s honoured."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def report_quality(data: dict, vol_num: int) -> None:
    """Print quality statistics for a parsed volume (PIPE-02)."""
    sections = data["sections"]
    total_chapters = sum(len(p["children"]) for p in sections)
    all_leaf_sections = [
        s
        for p in sections
        for ch in p["children"]
        for s in ch["children"]
    ]
    total_sections = len(all_leaf_sections)

    # Collect all content_blocks across the tree
    all_blocks = []

    def collect_blocks(node):
        all_blocks.extend(node.get("content_blocks", []))
        for ch in node.get("children", []):
            collect_blocks(ch)

    for p in sections:
        collect_blocks(p)

    total_words = sum(len(b.split()) for b in all_blocks)
    empty_blocks = sum(1 for b in all_blocks if not b.strip())

    # Section-level word count stats (min/median/max)
    sec_wcs = [s["word_count"] for s in all_leaf_sections]
    if sec_wcs:
        sec_wcs_sorted = sorted(sec_wcs)
        wc_min = sec_wcs_sorted[0]
        wc_med = sec_wcs_sorted[len(sec_wcs_sorted) // 2]
        wc_max = sec_wcs_sorted[-1]
    else:
        wc_min = wc_med = wc_max = 0

    # Section label null rate (how many sections have no sec-sign heading)
    sections_no_label = sum(1 for s in all_leaf_sections if s.get("label") is None)

    # Scripture reference coverage (% of leaf sections with at least one ref)
    sections_with_refs = sum(
        1 for s in all_leaf_sections if s.get("scripture_references")
    )

    print(f"  Parts:    {len(sections)}")
    print(f"  Chapters: {total_chapters}")
    print(f"  Sections: {total_sections}")
    print(f"  Content blocks: {len(all_blocks)} (empty: {empty_blocks})")
    print(f"  Total words:    {total_words:,}")
    print(f"  Avg words/block: {total_words // max(len(all_blocks), 1)}")
    print(f"  Section wc (min/median/max): {wc_min}/{wc_med}/{wc_max}")
    print(
        f"  Sections with sec-heading label: "
        f"{total_sections - sections_no_label}/{total_sections} "
        f"({sections_no_label} unlabelled)"
    )
    print(
        f"  Sections with scripture refs: "
        f"{sections_with_refs}/{total_sections} "
        f"({100 * sections_with_refs // max(total_sections, 1)}%)"
    )

    # Warnings
    chapters_no_title = sum(
        1 for p in sections for ch in p["children"] if not ch.get("title")
    )
    sections_no_blocks = sum(
        1 for s in all_leaf_sections if not s.get("content_blocks")
    )
    short_sections = sum(1 for s in all_leaf_sections if s["word_count"] < 20)

    if chapters_no_title:
        print(f"  WARNING: {chapters_no_title} chapters with no title")
    if sections_no_blocks:
        print(f"  WARNING: {sections_no_blocks} sections with empty content_blocks")
    if short_sections:
        print(f"  WARNING: {short_sections} sections under 20 words (may be parse misses)")
    if empty_blocks:
        print(f"  WARNING: {empty_blocks} empty content blocks")

    # Part labels for review
    print(f"  Part labels: {[p['label'] for p in sections]}")


# ---------------------------------------------------------------------------
# Source config writer
# ---------------------------------------------------------------------------

def write_source_config(vol_num: int) -> None:
    """Write the source config.json for a volume."""
    cfg = VOLUME_CONFIG[vol_num]
    config_dir = REPO_ROOT / "sources" / "structured-text" / cfg["work_id"]
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    vol_titles = {1: "Vol. 1", 2: "Vol. 2", 3: "Vol. 3"}
    config = {
        "resource_id": cfg["work_id"],
        "title": f"Systematic Theology, {vol_titles[vol_num]}",
        "author": WORK_META["author"],
        "author_birth_year": WORK_META["author_birth_year"],
        "author_death_year": WORK_META["author_death_year"],
        "contributors": normalize_contributors(WORK_META["contributors"]),
        "original_publication_year": WORK_META["original_publication_year"],
        "language": WORK_META["language"],
        "original_language": WORK_META["original_language"],
        "tradition": WORK_META["tradition"],
        "tradition_notes": WORK_META["tradition_notes"],
        "era": WORK_META["era"],
        "audience": WORK_META["audience"],
        "license": WORK_META["license"],
        "schema_type": "structured_text",
        "work_kind": "systematic-theology",
        "source_url": cfg["url"],
        "source_format": "ThML XML",
        "source_edition": (
            "Christian Classics Ethereal Library (CCEL) ThML edition. "
            "Original edition: New York: Scribner, Armstrong, 1872-1873."
        ),
        "source_hash": cfg["source_hash"],
        "download_date": cfg["download_date"],
        "output_file": f"data/structured-text/{cfg['work_id']}.json",
        "notes": (
            "CCEL confirmed OK to parse (Quincy, 2026-04-01). "
            "Crawl-delay 10s per robots.txt. "
            "ThML entities replaced; DOCTYPE stripped; footnotes excluded."
        ),
    }
    with open(config_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"  Config written -> {config_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Hodge Systematic Theology (3 vols) from CCEL ThML XML"
    )
    parser.add_argument(
        "--volume",
        type=int,
        choices=[1, 2, 3],
        default=None,
        help="Parse only this volume (default: all 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first part only; print stats and sample output -- do not write files",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download XML even if cached",
    )
    args = parser.parse_args()

    volumes = [args.volume] if args.volume else [1, 2, 3]
    start_time = time.time()
    log_lines = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    vols_processed = 0

    try:
        log(f"Hodge Systematic Theology parser {SCRIPT_VERSION}")
        log(f"Volumes: {volumes}  dry_run={args.dry_run}")
        log("")

        for i, vol_num in enumerate(volumes):
            log(f"--- Volume {vol_num} ({i + 1} of {len(volumes)}) ---")

            # Download (respecting robots.txt 10s crawl-delay between requests)
            try:
                if i > 0 and not VOLUME_CONFIG[vol_num]["raw_file"].exists():
                    log("  Waiting 10s (robots.txt crawl-delay) ...")
                    time.sleep(10)
                download_volume(vol_num, force=args.force_download)
            except RuntimeError as exc:
                log(f"  ERROR (download): {exc}")
                errors += 1
                continue

            # Parse
            try:
                data = parse_volume(vol_num, dry_run=args.dry_run)
            except RuntimeError as exc:
                log(f"  ERROR (parse): {exc}")
                errors += 1
                continue

            vols_processed += 1
            log("")
            report_quality(data, vol_num)
            log("")

            if args.dry_run:
                # Print sample: first 2 sections of first chapter of first part
                sample_sections = []
                if data["sections"]:
                    first_part = data["sections"][0]
                    if first_part["children"]:
                        first_ch = first_part["children"][0]
                        sample_sections = first_ch["children"][:2]
                log("  Sample (first 2 sections of first chapter):")
                for sec in sample_sections:
                    sample = dict(sec)
                    sample["content_blocks"] = sec["content_blocks"][:2]
                    log("  " + json.dumps(sample, ensure_ascii=False)[:300])
                log("")
                continue

            # Build and write output
            meta = build_meta(vol_num)
            output = {"meta": meta, "data": data}

            cfg = VOLUME_CONFIG[vol_num]
            out_path = cfg["output_file"]
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(output, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            size_kb = out_path.stat().st_size // 1024
            log(f"  Wrote {size_kb} KB -> {out_path.name}")
            files_written += 1

            # Write source config (keep going if this fails -- output JSON is primary)
            try:
                write_source_config(vol_num)
            except Exception as exc:
                log(f"  WARNING: source config write failed for vol {vol_num}: {exc}")

            log("")

    finally:
        # Always write the log file, even if an unhandled exception occurred
        elapsed = time.time() - start_time
        summary = (
            f"Done in {elapsed:.1f}s. "
            f"Volumes processed: {vols_processed}/{len(volumes)}. "
            f"Files written: {files_written}. "
            f"Errors: {errors}."
        )
        log(summary)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(log_lines) + "\n")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
