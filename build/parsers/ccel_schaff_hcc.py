"""ccel_schaff_hcc.py
Parser for Schaff's History of the Christian Church (8 vols, 1882-1910) from CCEL ThML.

Downloads hcc{1..8}.xml from CCEL once per volume, then parses the full
section tree (chapters > sections) into 8 OCD structured_text JSON files.

Sources:
  https://www.ccel.org/ccel/schaff/hcc1.xml  (Vol. 1: Apostolic Christianity, A.D. 1-100)
  https://www.ccel.org/ccel/schaff/hcc2.xml  (Vol. 2: Ante-Nicene Christianity, A.D. 100-325)
  https://www.ccel.org/ccel/schaff/hcc3.xml  (Vol. 3: Nicene and Post-Nicene Christianity, A.D. 311-600)
  https://www.ccel.org/ccel/schaff/hcc4.xml  (Vol. 4: Medieval Christianity, A.D. 590-1073)
  https://www.ccel.org/ccel/schaff/hcc5.xml  (Vol. 5: The Middle Ages, A.D. 1049-1294)
  https://www.ccel.org/ccel/schaff/hcc6.xml  (Vol. 6: The Middle Ages, A.D. 1294-1517)
  https://www.ccel.org/ccel/schaff/hcc7.xml  (Vol. 7: Modern Christianity -- The German Reformation)
  https://www.ccel.org/ccel/schaff/hcc8.xml  (Vol. 8: Modern Christianity -- The Swiss Reformation)

Source permission: CCEL confirmed OK to parse (Quincy, 2026-04-01).
robots.txt: crawl-delay 10 for all agents (confirmed 2026-04-22).

XML structure (censused 2026-04-22 from hcc1.xml):
  Root: <ThML> with no namespaces; DOCTYPE stripped before parsing.
  Body: <ThML.body>
    <div1 id="i" title="[period name]"> -- entire volume content (one content div1)
      <div2 type="Preface" ...>          -- skip
      <div2 type="Table of Contents" ...> -- skip
      <div2 id="i.v" title="Addenda">   -- may contain intro sections
      <div2 type="Chapter" n="I" title="..."> -- chapters (12 per vol 1)
        <div3 type="Section" n="1" title="..."> -- sections within each chapter
          <p> content paragraphs
          <scripRef> scripture references
          <note> footnotes (skip)
          <pb>  page breaks (skip)
    <div1 id="ii" title="Indexes"> -- skip

  Chapter id pattern: can be "i.I_1" or "i.VI" (n= attribute is canonical)
  Section id pattern: "i.I_1.8" (sequential numbering, not nested under chapter n)

  Key diff from Hodge: HCC has only 1 content div1 per volume (not 2 parts).
  Chapters are at div2 level (not div3). Sections at div3 level.

Usage:
    py -3 build/parsers/ccel_schaff_hcc.py --volume 1 --download --parse --dry-run
    py -3 build/parsers/ccel_schaff_hcc.py --volume 1 --download --parse
    py -3 build/parsers/ccel_schaff_hcc.py --all --download --parse
    py -3 build/parsers/ccel_schaff_hcc.py --volume 1 --parse --dry-run
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request  # standards: download only
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
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "schaff"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_schaff_hcc.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

VOLUME_CONFIG = {
    1: {
        "url": "https://www.ccel.org/ccel/schaff/hcc1.xml",
        "raw_file": RAW_DIR / "hcc1.xml",
        "work_id": "schaff-history-vol-1",
        "title": "History of the Christian Church, Vol. 1: Apostolic Christianity, A.D. 1-100",
        "output_file": OUTPUT_DIR / "schaff-history-vol-1.json",
    },
    2: {
        "url": "https://www.ccel.org/ccel/schaff/hcc2.xml",
        "raw_file": RAW_DIR / "hcc2.xml",
        "work_id": "schaff-history-vol-2",
        "title": "History of the Christian Church, Vol. 2: Ante-Nicene Christianity, A.D. 100-325",
        "output_file": OUTPUT_DIR / "schaff-history-vol-2.json",
    },
    3: {
        "url": "https://www.ccel.org/ccel/schaff/hcc3.xml",
        "raw_file": RAW_DIR / "hcc3.xml",
        "work_id": "schaff-history-vol-3",
        "title": "History of the Christian Church, Vol. 3: Nicene and Post-Nicene Christianity, A.D. 311-600",
        "output_file": OUTPUT_DIR / "schaff-history-vol-3.json",
    },
    4: {
        "url": "https://www.ccel.org/ccel/schaff/hcc4.xml",
        "raw_file": RAW_DIR / "hcc4.xml",
        "work_id": "schaff-history-vol-4",
        "title": "History of the Christian Church, Vol. 4: Medieval Christianity, A.D. 590-1073",
        "output_file": OUTPUT_DIR / "schaff-history-vol-4.json",
    },
    5: {
        "url": "https://www.ccel.org/ccel/schaff/hcc5.xml",
        "raw_file": RAW_DIR / "hcc5.xml",
        "work_id": "schaff-history-vol-5",
        "title": "History of the Christian Church, Vol. 5: The Middle Ages, A.D. 1049-1294",
        "output_file": OUTPUT_DIR / "schaff-history-vol-5.json",
    },
    6: {
        "url": "https://www.ccel.org/ccel/schaff/hcc6.xml",
        "raw_file": RAW_DIR / "hcc6.xml",
        "work_id": "schaff-history-vol-6",
        "title": "History of the Christian Church, Vol. 6: The Middle Ages, A.D. 1294-1517",
        "output_file": OUTPUT_DIR / "schaff-history-vol-6.json",
    },
    7: {
        "url": "https://www.ccel.org/ccel/schaff/hcc7.xml",
        "raw_file": RAW_DIR / "hcc7.xml",
        "work_id": "schaff-history-vol-7",
        "title": "History of the Christian Church, Vol. 7: Modern Christianity -- The German Reformation",
        "output_file": OUTPUT_DIR / "schaff-history-vol-7.json",
    },
    8: {
        "url": "https://www.ccel.org/ccel/schaff/hcc8.xml",
        "raw_file": RAW_DIR / "hcc8.xml",
        "work_id": "schaff-history-vol-8",
        "title": "History of the Christian Church, Vol. 8: Modern Christianity -- The Swiss Reformation",
        "output_file": OUTPUT_DIR / "schaff-history-vol-8.json",
    },
}

WORK_META = {
    "author": "Philip Schaff",
    "author_birth_year": 1819,
    "author_death_year": 1893,
    "contributors": ["Electronic Bible Society (digital edition)"],
    "original_publication_year": 1882,
    "language": "en",
    "original_language": "en",
    "tradition": ["ecumenical"],
    "tradition_notes": (
        "Schaff was a Swiss-American Reformed theologian and church historian. "
        "His HCC is the standard English-language multi-volume church history of the 19th century."
    ),
    "era": "modern",
    "audience": "scholarly",
    "license": "public-domain",
    "schema_type": "structured_text",
    "schema_version": SCHEMA_VERSION,
    "completeness": "full",
}


def _validate_configs() -> None:
    slug = "schaff-history-of-the-christian-church"
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

# ---------------------------------------------------------------------------
# ThML entity map
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Tag sets and skip patterns
# ---------------------------------------------------------------------------

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])
_DIV_TAG_RE = re.compile(r"^div\d?$")

# div2 types to skip (editorial front/back matter)
_SKIP_DIV2_TYPES = frozenset(["Preface", "Table of Contents"])

# div1 title patterns that indicate index / non-content volumes
_SKIP_DIV1_TITLE_RE = re.compile(r"^(title page|index|indexes|general index)\b", re.IGNORECASE)

# Section heading in the first <p> of a div3: "§ N. Title" or "N. Title" (Roman/Arabic)
# Matches the same leading text already captured from n= and title= attributes.
# These first-<p> headings are duplicates and must be stripped from content_blocks.
_SEC_HEADING_P_RE = re.compile(
    r"^[\u00a7\s]*(?:\d+|[ivxlcdmIVXLCDM]+)\.\s+",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_volume(vol_num: int, force: bool = False) -> None:
    """Download a single HCC volume XML from CCEL if not already cached."""
    cfg = VOLUME_CONFIG[vol_num]
    dest = cfg["raw_file"]
    if dest.exists() and not force:
        print(f"  Cached: {dest.name} ({dest.stat().st_size // 1024} KB)")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = cfg["url"]
    print(f"  Downloading {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
        with open(dest, "wb") as fh:
            fh.write(data)
        download_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cfg["download_date"] = download_date
        print(f"  Downloaded {len(data) // 1024} KB -> {dest.name}")
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for vol {vol_num}: {exc}. "
            "Check network access or retry with --force."
        ) from exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------


def _replace_entity(match: re.Match) -> str:
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    return replacement if replacement is not None else ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """Decode, strip DOCTYPE, replace HTML entities."""
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------


def get_all_text(elem) -> str:
    """Recursively collect text content, skipping footnote/metadata tags."""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag in _SKIP_TAGS:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(get_all_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def get_scriptrefs(elem) -> list:
    refs = []
    for sr in elem.iter("scripRef"):
        osis_raw = sr.get("osisRef", "")
        raw_text = clean_text(get_all_text(sr))
        osis_list = []
        for part in osis_raw.split():
            cleaned = re.sub(r"^Bible(?:\.[a-z]+)?:", "", part).strip()
            if cleaned:
                osis_list.append(cleaned)
        if raw_text or osis_list:
            refs.append({"raw": raw_text, "osis": osis_list})
    return refs


def count_words(blocks: list) -> int:
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def get_chapter_label_title(div2) -> tuple:
    """Extract chapter label and title from a div2 element."""
    n = div2.get("n", "")
    title_attr = clean_text(div2.get("title", ""))

    # Label: "Chapter N"
    label = f"Chapter {n}" if n else None

    # Title from title= attribute; strip "Chapter N" prefix if present
    title = title_attr
    if title and label and title.lower().startswith(label.lower()):
        title = title[len(label):].strip().lstrip(".").strip()

    # Fallback: h3 child
    if not title:
        h3 = div2.find("h3")
        if h3 is not None:
            title = clean_text(get_all_text(h3)).rstrip(".")

    return label, title or None


def collect_intro_blocks(div2) -> list:
    """Collect <p> children of div2 that appear before any div3 children."""
    blocks = []
    for child in div2:
        if _DIV_TAG_RE.match(child.tag):
            break  # stop at first child div
        if child.tag in _SKIP_TAGS or child.tag in _HEADING_TAGS:
            continue
        if child.tag in ("p", "argument", "q"):
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
    return blocks


def parse_section(div3) -> dict | None:
    """Parse a div3 element into a section dict."""
    n = div3.get("n", "")
    title_attr = clean_text(div3.get("title", ""))
    div_type = div3.get("type", "Section")

    # Label: "sec N" using section sign if available, else plain "N"
    label = f"\u00a7 {n}" if n else None
    title = title_attr or None

    content_blocks = []
    first_p_seen = False
    for child in div3:
        if child.tag in _SKIP_TAGS or child.tag in _HEADING_TAGS:
            continue
        if _DIV_TAG_RE.match(child.tag):
            continue
        if child.tag in ("p", "argument", "q"):
            text = clean_text(get_all_text(child))
            if not text:
                continue
            # Skip the first <p> if it repeats the section heading (§ N. Title pattern).
            # HCC div3 title= attribute already captures this; the first <p> is a duplicate.
            if not first_p_seen and _SEC_HEADING_P_RE.match(text):
                first_p_seen = True
                continue
            first_p_seen = True
            content_blocks.append(text)
        elif child.tag in ("ul", "ol"):
            items = [
                clean_text(get_all_text(li))
                for li in child.findall("li")
                if clean_text(get_all_text(li))
            ]
            if items:
                content_blocks.append("; ".join(items))
        elif child.tag in ("h3", "h4"):
            text = clean_text(get_all_text(child))
            if text:
                content_blocks.append(text)

    if not content_blocks:
        return None

    scripture_refs = get_scriptrefs(div3)
    return {
        "section_type": "section",
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": count_words(content_blocks),
        "children": [],
    }


def parse_chapter(div2) -> dict | None:
    """Parse a div2 chapter into a chapter dict with section children."""
    div_type = div2.get("type", "")

    # Skip editorial div2 types
    if div_type in _SKIP_DIV2_TYPES:
        return None

    # Only process div2 with type="Chapter" as chapters;
    # other non-skipped types (e.g. untyped or unusual) are treated as chapters too
    label, title = get_chapter_label_title(div2)
    intro_blocks = collect_intro_blocks(div2)

    children = []
    for child in div2:
        if not _DIV_TAG_RE.match(child.tag):
            continue
        sec = parse_section(child)
        if sec is not None:
            children.append(sec)

    # Include if has content or children
    if not intro_blocks and not children:
        return None

    scripture_refs = get_scriptrefs(div2)
    own_wc = count_words(intro_blocks)
    total_wc = own_wc + sum(s["word_count"] for s in children)

    return {
        "section_type": "chapter",
        "label": label,
        "title": title,
        "content_blocks": intro_blocks,
        "scripture_references": scripture_refs,
        "word_count": total_wc,
        "children": children,
    }


# ---------------------------------------------------------------------------
# Volume parsing
# ---------------------------------------------------------------------------


def parse_volume(vol_num: int, dry_run: bool = False) -> dict:
    """
    Parse one HCC volume into a structured_text data dict.

    Returns {"work_id": ..., "work_kind": ..., "sections": [...], "_source_hash": ...}.
    """
    cfg = VOLUME_CONFIG[vol_num]
    raw_file = cfg["raw_file"]

    print(f"  Parsing {raw_file.name} ({raw_file.stat().st_size // 1024} KB) ...")
    raw_bytes = raw_file.read_bytes()
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse failed for vol {vol_num}: {exc}. "
            "Try --force to re-download the file."
        ) from exc

    # Find the content div1 (skip index/title-page div1s)
    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(f"No <ThML.body> in vol {vol_num}.")

    chapters = []
    content_div1_count = 0

    for div1 in body:
        if not _DIV_TAG_RE.match(div1.tag):
            continue
        div1_title = clean_text(div1.get("title", ""))
        if _SKIP_DIV1_TITLE_RE.match(div1_title):
            continue  # skip Index div1s

        content_div1_count += 1
        print(f"  Processing div1: {div1.get('id', '?')} title={div1_title!r}")

        # Walk div2 children for chapters
        for div2 in div1:
            if not _DIV_TAG_RE.match(div2.tag):
                continue
            ch = parse_chapter(div2)
            if ch is not None:
                chapters.append(ch)
            if dry_run and len(chapters) >= 2:
                break  # parse 2 chapters on dry run and stop
        if dry_run:
            break

    if content_div1_count == 0:
        raise RuntimeError(
            f"Vol {vol_num}: no content div1 found. "
            "XML structure may differ from census. Check the raw file."
        )

    return {
        "work_id": cfg["work_id"],
        "work_kind": "church-history",
        "sections": chapters,
        "_source_hash": source_hash,
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_meta(vol_num: int, source_hash: str) -> dict:
    cfg = VOLUME_CONFIG[vol_num]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    raw_file = cfg["raw_file"]
    download_date = cfg.get("download_date", "")
    if not download_date and raw_file.exists():
        mtime = raw_file.stat().st_mtime
        download_date = datetime.fromtimestamp(
            mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    return {
        "id": cfg["work_id"],
        "title": cfg["title"],
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
                "Original edition: New York: Charles Scribner's Sons, 1882-1910."
            ),
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_schaff_hcc.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents. "
                "DOCTYPE stripped before parsing. "
                "Footnotes (<note>) and page breaks (<pb>) excluded from content. "
                "Editorial prefaces, tables of contents, and index volumes excluded. "
                "robots.txt crawl-delay 10s honoured."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------


def report_quality(vol_num: int, data: dict) -> None:
    chapters = data["sections"]
    all_sections = [s for ch in chapters for s in ch.get("children", [])]
    total_blocks = sum(
        len(s.get("content_blocks", [])) for s in all_sections
    ) + sum(len(ch.get("content_blocks", [])) for ch in chapters)
    total_words = sum(ch.get("word_count", 0) for ch in chapters)
    null_ch_titles = sum(1 for ch in chapters if not ch.get("title"))
    null_sec_titles = sum(1 for s in all_sections if not s.get("title"))

    print(f"  Vol {vol_num}: {len(chapters)} chapters, {len(all_sections)} sections")
    print(f"  Content blocks: {total_blocks}, Total words: {total_words:,}")
    if null_ch_titles:
        print(f"  WARNING: {null_ch_titles} chapters with no title")
    if null_sec_titles:
        print(f"  WARNING: {null_sec_titles} sections with no title")

    sec_wcs = [s.get("word_count", 0) for s in all_sections if s.get("word_count", 0) > 0]
    if sec_wcs:
        wc_min = min(sec_wcs)
        wc_med = sorted(sec_wcs)[len(sec_wcs) // 2]
        wc_max = max(sec_wcs)
        print(f"  Section wc (min/med/max): {wc_min}/{wc_med}/{wc_max}")
    empty_secs = sum(1 for s in all_sections if not s.get("content_blocks"))
    if empty_secs:
        print(f"  WARNING: {empty_secs} sections with empty content_blocks")


# ---------------------------------------------------------------------------
# Source config writer
# ---------------------------------------------------------------------------


def write_source_config(vol_num: int, source_hash: str) -> None:
    cfg = VOLUME_CONFIG[vol_num]
    config_dir = REPO_ROOT / "sources" / "structured-text" / cfg["work_id"]
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"

    raw_file = cfg["raw_file"]
    download_date = cfg.get("download_date", "")
    if not download_date and raw_file.exists():
        mtime = raw_file.stat().st_mtime
        download_date = datetime.fromtimestamp(
            mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    config = {
        "resource_id": cfg["work_id"],
        "title": cfg["title"],
        "author": WORK_META["author"],
        "author_birth_year": WORK_META["author_birth_year"],
        "author_death_year": WORK_META["author_death_year"],
        "contributors": normalize_contributors(WORK_META["contributors"]),
        "original_publication_year": WORK_META["original_publication_year"],
        "language": WORK_META["language"],
        "original_language": WORK_META["original_language"],
        "tradition": WORK_META["tradition"],
        "era": WORK_META["era"],
        "audience": WORK_META["audience"],
        "license": WORK_META["license"],
        "schema_type": "structured_text",
        "work_kind": "church-history",
        "source_url": cfg["url"],
        "source_format": "ThML XML",
        "source_edition": (
            "Christian Classics Ethereal Library (CCEL) ThML edition. "
            "Original edition: New York: Charles Scribner's Sons, 1882-1910."
        ),
        "source_hash": source_hash,
        "download_date": download_date,
        "output_file": f"data/structured-text/{cfg['work_id']}.json",
        "notes": (
            "CCEL confirmed OK to parse (Quincy, 2026-04-01). "
            "Crawl-delay 10s per robots.txt. "
            "ThML entities replaced; DOCTYPE stripped; footnotes and prefaces excluded."
        ),
    }
    with open(config_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"  Config written -> {config_path}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Schaff History of the Christian Church (8 vols) from CCEL ThML XML"
    )
    vol_group = parser.add_mutually_exclusive_group()
    vol_group.add_argument(
        "--volume",
        type=int,
        choices=list(VOLUME_CONFIG.keys()),
        default=None,
        help="Process only this volume (1-8)",
    )
    vol_group.add_argument(
        "--all",
        action="store_true",
        help="Process all 8 volumes",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download volume XML from CCEL",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse cached XML and write JSON output",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse 2 chapters only; print stats -- do not write output files",
    )
    args = parser.parse_args()

    if not args.download and not args.parse and not args.dry_run:
        parser.print_help()
        sys.exit(0)

    if args.dry_run:
        args.parse = True

    if args.all or (not args.volume):
        volumes = list(VOLUME_CONFIG.keys())
    else:
        volumes = [args.volume]

    start_time = time.time()
    log_lines = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    vols_done = 0

    try:
        log(f"Schaff HCC parser {SCRIPT_VERSION}")
        log(f"Volumes: {volumes}  download={args.download}  parse={args.parse}  dry_run={args.dry_run}")
        log("")

        # --- Download phase ---
        if args.download:
            log("=== Download phase ===")
            for i, vol_num in enumerate(volumes):
                cfg = VOLUME_CONFIG[vol_num]
                if cfg["raw_file"].exists() and not args.force:
                    log(f"  Vol {vol_num}: already cached, skipping")
                    continue
                if i > 0:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                log(f"  [{i + 1}/{len(volumes)}] Vol {vol_num} ...")
                try:
                    download_volume(vol_num, force=args.force)
                except RuntimeError as exc:
                    log(f"  ERROR (download): {exc}")
                    errors += 1
            log("")

        # --- Parse phase ---
        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            for vol_num in volumes:
                cfg = VOLUME_CONFIG[vol_num]
                if not cfg["raw_file"].exists():
                    log(f"  ERROR: raw file missing: {cfg['raw_file']}. Run --download first.")
                    errors += 1
                    continue

                log(f"--- Vol {vol_num} ({cfg['title'][:60]}...) ---")
                try:
                    data = parse_volume(vol_num, dry_run=args.dry_run)
                except RuntimeError as exc:
                    log(f"  ERROR (parse): {exc}")
                    errors += 1
                    continue

                report_quality(vol_num, data)

                if args.dry_run:
                    # Print 2 sample sections from first chapter
                    if data["sections"]:
                        first_ch = data["sections"][0]
                        for sec in first_ch.get("children", [])[:2]:
                            sample = dict(sec)
                            sample["content_blocks"] = sec["content_blocks"][:1]
                            log("  SAMPLE: " + json.dumps(sample, ensure_ascii=False)[:300])
                    log(f"  DRY RUN: skipping file write for vol {vol_num}")
                    log("")
                    continue

                out_path = cfg["output_file"]
                try:
                    meta = build_meta(vol_num, data["_source_hash"])
                    output_data = {
                        "work_id": data["work_id"],
                        "work_kind": data["work_kind"],
                        "sections": data["sections"],
                    }
                    output = {"meta": meta, "data": output_data}
                    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                        json.dump(output, fh, ensure_ascii=False, indent=2)
                        fh.write("\n")
                except Exception as exc:
                    if out_path.exists():
                        out_path.unlink()  # standards: log/temp rotation
                    log(f"  ERROR (write): {exc}")
                    errors += 1
                    continue

                size_kb = out_path.stat().st_size // 1024
                log(f"  Wrote {size_kb} KB -> {out_path.name}")
                files_written += 1
                vols_done += 1

                try:
                    write_source_config(vol_num, data["_source_hash"])
                except Exception as exc:
                    log(f"  WARNING: source config write failed: {exc}")

                log("")

    finally:
        elapsed = time.time() - start_time
        summary = (
            f"Done in {elapsed:.1f}s. "
            f"Volumes parsed: {vols_done}/{len(volumes)}. "
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
