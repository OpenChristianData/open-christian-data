"""ccel_church_history.py
Parser for NPNF2 church history works from CCEL ThML XML.

Covers 5 works across 3 NPNF2 volumes:
  npnf201: Eusebius -- Church History (div1 id="iii") + Life of Constantine (div1 id="iv")
  npnf202: Socrates Scholasticus (div1 id="ii") + Sozomen (div1 id="iii")
  npnf203: Theodoret of Cyrrhus (div1 id="iv") -- EH, Dialogues, and Letters

Source: Nicene and Post-Nicene Fathers, Series 2, Vols 1-3, Philip Schaff (ed.), 1890-1892.
CCEL confirmed OK to parse (Quincy, 2026-04-01).
robots.txt: crawl-delay 10 for all agents (confirmed 2026-04-22).

XML structure (censused 2026-04-22 from full downloads):
  Root: <ThML> with no namespaces; DOCTYPE stripped before parsing.
  Header: <ThML.head> (metadata, skipped)
  Body: <ThML.body> containing div1 elements, one per major work.

  Sub-work demarcation: div1 level, identified by id= and title= attributes.
  Skip criteria for div1:
    id="i" (always Title Page), and title containing "Index" or "Preface"

  div2 level: books/prolegomena/front-matter (within a work's div1)
    type="Book"    -> section_type="book" (EH, Socrates, Sozomen, Theodoret)
    type="Preface" -> skip (editorial)
    type="Table of Contents" -> skip
    other          -> included if not editorial (by title pattern)

  div3 level: chapters (within books/div2)
    type="Chapter"     -> section_type="chapter"
    type="Book"        -> section_type="book" (LoC only: books nest under div2 iv.vi)
    type="Letter"      -> section_type="letter" (Theodoret letters only)
    type="Dialogue"    -> section_type="chapter"
    type="Demonstration" -> section_type="chapter"

  div4 level: sections (within chapters, mainly in prolegomena)
    type="Section"     -> section_type="section"

  Heading elements: title= attribute on div is most reliable (used as fallback).
  h1/h2/h3/h4 elements also appear inside divs.
  <note> elements = footnotes (skipped from content_blocks).
  <pb> elements = page breaks (skipped).

Special structures:
  Life of Constantine (div1 id="iv"): Books appear at div3 level under div2 iv.vi.
    Other div2 elements (Orations) have prose content at div3/p level.
  Theodoret (div1 id="iv"): Three separate major works in one div1:
    div2 iv.viii = EH (books -> chapters), div2 iv.ix = Dialogues, div2 iv.x = Letters.

Translators (NPNF2 series, 1890-1892):
  Eusebius EH:       Arthur Cushman McGiffert
  Life of Constantine: Ernest Cushing Richardson
  Socrates:          Arthur Cleveland Zenos
  Sozomen:           Chester D. Hartranft
  Theodoret:         Blomfield Jackson

Note: Evagrius Scholasticus was listed in the prompt as being in npnf203, but a full
census of npnf203 revealed it contains Theodoret, Jerome, and Rufinus only. Evagrius's
Ecclesiastical History is in a different NPNF2 volume. Deferred to future investigation.

Usage:
    py -3 build/parsers/ccel_church_history.py --volume npnf201 --work eusebius-eh --download --parse
    py -3 build/parsers/ccel_church_history.py --volume npnf201 --download --parse
    py -3 build/parsers/ccel_church_history.py --volume npnf202 --download --parse
    py -3 build/parsers/ccel_church_history.py --volume npnf203 --download --parse
    py -3 build/parsers/ccel_church_history.py --download --parse
    py -3 build/parsers/ccel_church_history.py --dry-run
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
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "schaff"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_church_history.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

# Volume -> list of works to extract from that file
VOLUME_CONFIG = {
    "npnf201": {
        "url": "https://www.ccel.org/ccel/schaff/npnf201.xml",
        "raw_file": RAW_DIR / "npnf201.xml",
        "works": [
            {
                "slug": "eusebius-ecclesiastical-history",
                "div1_id": "iii",
                "title": "Church History of Eusebius",
                "author": "Eusebius of Caesarea",
                "author_birth_year": 260,
                "author_death_year": 339,
                "original_publication_year": None,
                "work_kind": "church-history",
                "contributors": [
                    "Arthur Cushman McGiffert (translator, 1890)",
                    "Philip Schaff (series editor)",
                ],
                "tradition": ["patristic", "ecumenical"],
                "era": "patristic",
                "original_language": "grc",
            },
            {
                "slug": "eusebius-life-of-constantine",
                "div1_id": "iv",
                "title": "The Life of Constantine with Orations",
                "author": "Eusebius of Caesarea",
                "author_birth_year": 260,
                "author_death_year": 339,
                "original_publication_year": None,
                "work_kind": "church-history",
                "contributors": [
                    "Ernest Cushing Richardson (translator, 1890)",
                    "Philip Schaff (series editor)",
                ],
                "tradition": ["patristic", "ecumenical"],
                "era": "patristic",
                "original_language": "grc",
            },
        ],
    },
    "npnf202": {
        "url": "https://www.ccel.org/ccel/schaff/npnf202.xml",
        "raw_file": RAW_DIR / "npnf202.xml",
        "works": [
            {
                "slug": "socrates-ecclesiastical-history",
                "div1_id": "ii",
                "title": "The Ecclesiastical History of Socrates Scholasticus",
                "author": "Socrates Scholasticus",
                "author_birth_year": 380,
                "author_death_year": 440,
                "original_publication_year": None,
                "work_kind": "church-history",
                "contributors": [
                    "Arthur Cleveland Zenos (translator, 1890)",
                    "Philip Schaff (series editor)",
                ],
                "tradition": ["patristic", "ecumenical"],
                "era": "patristic",
                "original_language": "grc",
            },
            {
                "slug": "sozomen-ecclesiastical-history",
                "div1_id": "iii",
                "title": "The Ecclesiastical History of Sozomen",
                "author": "Sozomen",
                "author_birth_year": 400,
                "author_death_year": 450,
                "original_publication_year": None,
                "work_kind": "church-history",
                "contributors": [
                    "Chester D. Hartranft (translator, 1890)",
                    "Philip Schaff (series editor)",
                ],
                "tradition": ["patristic", "ecumenical"],
                "era": "patristic",
                "original_language": "grc",
            },
        ],
    },
    "npnf203": {
        "url": "https://www.ccel.org/ccel/schaff/npnf203.xml",
        "raw_file": RAW_DIR / "npnf203.xml",
        "works": [
            {
                "slug": "theodoret-ecclesiastical-history",
                "div1_id": "iv",
                "title": "The Ecclesiastical History, Dialogues, and Letters of Theodoret",
                "author": "Theodoret of Cyrrhus",
                "author_birth_year": 393,
                "author_death_year": 457,
                "original_publication_year": None,
                "work_kind": "church-history",
                "contributors": [
                    "Blomfield Jackson (translator, 1892)",
                    "Philip Schaff (series editor)",
                ],
                "tradition": ["patristic", "ecumenical"],
                "era": "patristic",
                "original_language": "grc",
            },
        ],
    },
}


def _validate_work_configs() -> None:
    assert "scholarly" in STRUCTURED_TEXT__META__AUDIENCE, "invalid audience 'scholarly'"
    for volume_id, volume_cfg in VOLUME_CONFIG.items():
        for cfg in volume_cfg.get("works", []):
            slug = cfg.get("slug", volume_id)
            for t in cfg.get("tradition", []):
                assert t in STRUCTURED_TEXT__META__TRADITION, f"{slug}: invalid tradition {t!r}"
            if wk := cfg.get("work_kind"):
                assert wk in STRUCTURED_TEXT__DATA__WORK_KIND, f"{slug}: invalid work_kind {wk!r}"
            if era := cfg.get("era"):
                assert era in STRUCTURED_TEXT__META__ERA, f"{slug}: invalid era {era!r}"


_validate_work_configs()

# ---------------------------------------------------------------------------
# ThML entity map (same as Owen/Hodge parsers)
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
# Skip patterns: div2 titles that are editorial front/back matter
# ---------------------------------------------------------------------------

# Titles (lowercased) whose div2 elements should be skipped
_EDITORIAL_TITLE_PATTERNS = re.compile(
    r"^(title page|preface|prefatory|testimonies? of|supplementary notes|"
    r"manuscripts and editions|chronological tables|translator|memoir of|"
    r"address to the|general indexes?|subject index|index of|indexes?)\b",
    re.IGNORECASE,
)

_EDITORIAL_DIV2_TYPES = frozenset(["Preface", "Table of Contents"])

# div1 titles that are indexes/non-content at the volume level
_SKIP_DIV1_TITLE_RE = re.compile(
    r"^(title page|index|indexes|general index)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Tag sets
# ---------------------------------------------------------------------------

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])
_DIV_TAG_RE = re.compile(r"^div\d?$")

# section_type mapping from div type= attribute
_DIV_TYPE_MAP = {
    "Book": "book",
    "Chapter": "chapter",
    "Section": "section",
    "Letter": "letter",
    "Dialogue": "chapter",
    "Demonstration": "chapter",
    "Sermon": "chapter",
    "Note": None,  # skip
    "Table": None,  # skip
}

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_volume(vol_id: str, force: bool = False) -> None:
    """Download a NPNF2 volume XML from CCEL if not already cached."""
    cfg = VOLUME_CONFIG[vol_id]
    dest = cfg["raw_file"]
    if dest.exists() and not force:
        size_kb = dest.stat().st_size // 1024
        print(f"  Cached: {dest.name} ({size_kb} KB)")
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
            f"Download failed for {vol_id}: {exc}. "
            "Check network access and CCEL availability."
        ) from exc


# ---------------------------------------------------------------------------
# XML preprocessing (identical to Owen/Hodge parsers)
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
    """Collect scripture references from <scripRef> elements."""
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
# Structural helpers
# ---------------------------------------------------------------------------


def is_editorial_div(elem) -> bool:
    """Return True if a div element is editorial front/back matter to skip."""
    div_type = elem.get("type", "")
    if div_type in _EDITORIAL_DIV2_TYPES:
        return True
    title = clean_text(elem.get("title", ""))
    if title and _EDITORIAL_TITLE_PATTERNS.match(title):
        return True
    # Also skip by explicit title content check
    if title.lower() in ("title page.", "title page", "preface.", "preface"):
        return True
    return False


def get_div_label_title(elem) -> tuple:
    """Extract (label, title) from a div element using title= attr or h* children."""
    n = elem.get("n", "")
    div_type = elem.get("type", "")
    title_attr = clean_text(elem.get("title", ""))

    # Build label from type + n (e.g. "Book I", "Chapter III", "Letter 1")
    if div_type and n:
        label = f"{div_type} {n}"
    elif n:
        label = n
    else:
        label = ""

    # Title: use title= attr; strip redundant label prefix if present
    title = title_attr
    if title and label and title.lower().startswith(label.lower()):
        title = title[len(label):].strip().lstrip(".").strip()

    # Fallback: first h* child
    if not title:
        for child in elem:
            if child.tag in _HEADING_TAGS:
                child_text = clean_text(get_all_text(child))
                if child_text:
                    title = child_text
                    break

    return label or None, title or None


def collect_content_blocks(elem) -> list:
    """Collect direct <p> and <argument> children as content_blocks."""
    blocks = []
    for child in elem:
        if child.tag in _HEADING_TAGS or child.tag in _SKIP_TAGS:
            continue
        if _DIV_TAG_RE.match(child.tag):
            continue
        if child.tag in ("p", "argument", "q"):
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
        elif child.tag in ("ul", "ol"):
            items = []
            for li in child.findall("li"):
                t = clean_text(get_all_text(li))
                if t:
                    items.append(t)
            if items:
                blocks.append("; ".join(items))
    return blocks


# ---------------------------------------------------------------------------
# Parse engine
# ---------------------------------------------------------------------------


def parse_div_recursive(elem, max_depth: int = 4, depth: int = 0) -> dict | None:
    """
    Recursively parse a div element into a section dict.

    Returns None for editorial divs or divs with no content or children.
    """
    if is_editorial_div(elem):
        return None

    div_type = elem.get("type", "")
    section_type = _DIV_TYPE_MAP.get(div_type)

    # Unknown type= value: treat as generic section
    if div_type and section_type is None and div_type in ("Note", "Table"):
        return None  # explicitly skip
    if section_type is None:
        section_type = "section" if depth > 0 else "book"

    label, title = get_div_label_title(elem)
    content_blocks = collect_content_blocks(elem)

    # Recurse into child divs
    children = []
    if depth < max_depth:
        for child in elem:
            if not _DIV_TAG_RE.match(child.tag):
                continue
            result = parse_div_recursive(child, max_depth, depth + 1)
            if result is not None:
                children.append(result)

    # Skip entirely empty nodes
    if not content_blocks and not children:
        return None

    scripture_refs = get_scriptrefs(elem)
    word_count = count_words(content_blocks)

    return {
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": word_count,
        "children": children,
    }


def parse_work_from_div1(div1_elem, work_cfg: dict) -> list:
    """
    Extract sections from a specific div1 element for a single work.

    Walks direct div children of div1, skipping editorial front/back matter,
    and recursively parses included content divs.
    """
    sections = []
    for child in div1_elem:
        if not _DIV_TAG_RE.match(child.tag):
            continue
        if is_editorial_div(child):
            continue
        result = parse_div_recursive(child, max_depth=4, depth=0)
        if result is not None:
            sections.append(result)
    return sections


def parse_volume_work(vol_id: str, work_cfg: dict, raw_bytes: bytes) -> dict:
    """Parse one work from a NPNF2 volume XML."""
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse failed for {vol_id}: {exc}. Try re-downloading."
        ) from exc

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(f"No <ThML.body> in {vol_id}. Unexpected structure.")

    # Find the specific div1 for this work
    target_id = work_cfg["div1_id"]
    div1_elem = None
    for div1 in body:
        if not _DIV_TAG_RE.match(div1.tag):
            continue
        if div1.get("id") == target_id:
            div1_elem = div1
            break

    if div1_elem is None:
        raise RuntimeError(
            f"div1 id={target_id!r} not found in {vol_id}. "
            "Check census -- volume structure may have changed."
        )

    sections = parse_work_from_div1(div1_elem, work_cfg)
    return {
        "work_id": work_cfg["slug"],
        "sections": sections,
        "_source_hash": source_hash,
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------


def build_meta(vol_id: str, work_cfg: dict, source_hash: str) -> dict:
    cfg = VOLUME_CONFIG[vol_id]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw_file = cfg["raw_file"]
    download_date = cfg.get("download_date", "")
    if not download_date and raw_file.exists():
        mtime = raw_file.stat().st_mtime
        download_date = datetime.fromtimestamp(
            mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d")

    return {
        "id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_birth_year": work_cfg["author_birth_year"],
        "author_death_year": work_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg["contributors"]),
        "original_publication_year": work_cfg["original_publication_year"],
        "language": "en",
        "original_language": work_cfg["original_language"],
        "tradition": work_cfg["tradition"],
        "tradition_notes": "",
        "era": work_cfg["era"],
        "audience": "scholarly",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
        "provenance": {
            "source_url": cfg["url"],
            "source_format": "ThML XML",
            "source_edition": (
                "Nicene and Post-Nicene Fathers, Series 2. "
                "Philip Schaff (ed.). New York: Christian Literature Publishing Co., 1890-1892."
            ),
            "download_date": download_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_church_history.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents. "
                "DOCTYPE stripped before parsing. "
                "Footnotes (<note>) and page breaks (<pb>) excluded from content. "
                "Editorial front matter (title pages, prefaces, testimonies, indexes) excluded. "
                "robots.txt crawl-delay 10s honoured."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------


def _sum_tree(sections: list, key: str) -> int:
    total = 0
    for s in sections:
        total += s.get(key, 0)
        total += _sum_tree(s.get("children", []), key)
    return total


def _count_nodes(sections: list) -> int:
    count = len(sections)
    for s in sections:
        count += _count_nodes(s.get("children", []))
    return count


def report_quality(work_cfg: dict, sections: list) -> None:
    top_n = len(sections)
    total_n = _count_nodes(sections)
    total_words = _sum_tree(sections, "word_count")
    top_titles = [s.get("title") or s.get("label") or "(untitled)" for s in sections[:6]]
    print(
        f"  {work_cfg['slug']}: {top_n} top sections, "
        f"{total_n} total nodes, ~{total_words // 1000}k words"
    )
    print(f"  Top sections: {top_titles}")
    # Null title count
    null_titles = sum(1 for s in sections if not s.get("title") and not s.get("label"))
    if null_titles:
        print(f"  WARNING: {null_titles} top sections with no title or label")


# ---------------------------------------------------------------------------
# Source config writer
# ---------------------------------------------------------------------------


def write_source_config(vol_id: str, work_cfg: dict, source_hash: str) -> None:
    cfg = VOLUME_CONFIG[vol_id]
    config_dir = REPO_ROOT / "sources" / "structured-text" / work_cfg["slug"]
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
        "resource_id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_birth_year": work_cfg["author_birth_year"],
        "author_death_year": work_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg["contributors"]),
        "original_publication_year": work_cfg["original_publication_year"],
        "language": "en",
        "original_language": work_cfg["original_language"],
        "tradition": work_cfg["tradition"],
        "era": work_cfg["era"],
        "audience": "scholarly",
        "license": "public-domain",
        "schema_type": "structured_text",
        "work_kind": work_cfg["work_kind"],
        "source_url": cfg["url"],
        "source_format": "ThML XML",
        "source_edition": (
            "Nicene and Post-Nicene Fathers, Series 2. "
            "Philip Schaff (ed.). New York: Christian Literature Publishing Co., 1890-1892."
        ),
        "source_hash": source_hash,
        "download_date": download_date,
        "output_file": f"data/structured-text/{work_cfg['slug']}.json",
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
# CLI / main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse NPNF2 church history works from CCEL ThML XML"
    )
    parser.add_argument(
        "--volume",
        choices=list(VOLUME_CONFIG.keys()),
        default=None,
        help="Process only this volume (default: all volumes)",
    )
    parser.add_argument(
        "--work",
        default=None,
        metavar="SLUG",
        help="Process only this work slug (within the selected volume)",
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
        help="Parse but do not write output files; print quality stats only",
    )
    args = parser.parse_args()

    if not args.download and not args.parse and not args.dry_run:
        parser.print_help()
        sys.exit(0)

    if args.dry_run:
        args.parse = True

    # Determine which volumes/works to process
    if args.volume:
        vol_ids = [args.volume]
    else:
        vol_ids = list(VOLUME_CONFIG.keys())

    start_time = time.time()
    log_lines = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    works_done = 0

    try:
        log(f"NPNF2 Church History parser {SCRIPT_VERSION}")
        log(f"Volumes: {vol_ids}  download={args.download}  parse={args.parse}  dry_run={args.dry_run}")
        log("")

        # --- Download phase ---
        if args.download:
            log("=== Download phase ===")
            for i, vol_id in enumerate(vol_ids):
                if i > 0:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                log(f"  [{i + 1}/{len(vol_ids)}] {vol_id} ...")
                try:
                    download_volume(vol_id, force=args.force)
                except RuntimeError as exc:
                    log(f"  ERROR (download): {exc}")
                    errors += 1
            log("")

        # --- Parse phase ---
        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

            for vol_id in vol_ids:
                cfg = VOLUME_CONFIG[vol_id]
                raw_file = cfg["raw_file"]

                if not raw_file.exists():
                    log(f"  ERROR: raw file missing: {raw_file}. Run --download first.")
                    errors += 1
                    continue

                log(f"  Loading {raw_file.name} ({raw_file.stat().st_size // 1024} KB) ...")
                raw_bytes = raw_file.read_bytes()

                works = cfg["works"]
                if args.work:
                    works = [w for w in works if w["slug"] == args.work]
                    if not works:
                        log(f"  ERROR: work {args.work!r} not found in {vol_id}")
                        errors += 1
                        continue

                for work_cfg in works:
                    log(f"  Parsing {work_cfg['slug']} (div1 id={work_cfg['div1_id']!r}) ...")
                    try:
                        result = parse_volume_work(vol_id, work_cfg, raw_bytes)
                    except RuntimeError as exc:
                        log(f"  ERROR (parse): {exc}")
                        errors += 1
                        continue

                    report_quality(work_cfg, result["sections"])

                    if not result["sections"]:
                        log(f"  WARNING: 0 sections for {work_cfg['slug']}")

                    if args.dry_run:
                        log(f"  DRY RUN: skipping file write for {work_cfg['slug']}")
                        log("")
                        continue

                    out_path = OUTPUT_DIR / f"{work_cfg['slug']}.json"
                    try:
                        meta = build_meta(vol_id, work_cfg, result["_source_hash"])
                        data = {
                            "work_id": result["work_id"],
                            "work_kind": work_cfg["work_kind"],
                            "sections": result["sections"],
                        }
                        output = {"meta": meta, "data": data}
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
                    works_done += 1

                    try:
                        write_source_config(vol_id, work_cfg, result["_source_hash"])
                    except Exception as exc:
                        log(f"  WARNING: source config write failed: {exc}")

                    log("")

    finally:
        elapsed = time.time() - start_time
        summary = (
            f"Done in {elapsed:.1f}s. "
            f"Works parsed: {works_done}. "
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
