"""ccel_evangelical_holiness.py
Parser for Evangelical & Holiness classics (8 titles, 4 authors) from CCEL ThML XML.

Downloads {ccel_id}.xml from CCEL once per work, then parses the full section
tree into OCD structured_text JSON files (one per work).

Source permission: CCEL confirmed OK to parse (Quincy, 2026-04-01). Copyright is on
CCEL's files/formatting only, not the PD texts. Attribution: "sourced via CCEL.org".
robots.txt: crawl-delay 10 for all agents (confirmed 2026-04-24).

Works covered:
  Finney x2 (theology, revivals), Bounds x4 (power, purpose, prayingmen, reality),
  Pascal x1 (pensees), Wesley x1 (perfection/plain_account)

URL census: research/prompts/t6-6-ccel-url-census.md (2026-04-24)

Skipped works (documented in census):
  bounds/necessity (first pub 1929 — post-1927, not US PD)
  bounds/weapon   (first pub 1931 — post-1927, not US PD)
  bounds/prayer   (404 on CCEL)
  fisher/marrow   (404 on CCEL — not available)

XML structure (census across 4 pilot works, 2026-04-24):

  Finney/revivals (heading-only, div1 container > div2 chapters):
    div1 "Title Page", "Prefatory Material", "Lectures" at top level.
    "Title Page" -> filtered by is_editorial_div (title= match).
    "Lectures" div1 contains 22 div2 chapters.
    Each div2: h2 carries "LECTURE I." label, h3 carries subtitle.
    HEADING_RE matches "Lecture I" in h2 -> section_type='chapter'.

  Finney/theology (heading-only -- structure inferred from work type):
    Expected: flat or nested div1/div2 similar to revivals.
    Large work (~300k words); may use Part/Chapter nesting.

  Bounds prayer works (flat div1 chapters, no nesting):
    All div1 at top level. Title Page div1 -> editorial.
    Content div1s: title= attr carries numbered chapter name
    (e.g. "1. Men of Prayer Needed"). h2 tag has same text.
    No HEADING_RE match -> falls back to title= attr -> ("", title).
    section_type inferred as 'chapter' (has content, no children).

  Pascal/pensees (flat div1 sections, no nesting):
    16 div1 elements. First div1 is title page (no p content -> orphan-filtered).
    Content div1s: title= carries "SECTION I: THOUGHTS ON MIND AND ON STYLE".
    h2 tag has same section title. No HEADING_RE match.
    Fallback: title= attr -> ("", title_attr). section_type='chapter'.

  Wesley/perfection (div1 container > div2 sub-sections):
    div1 "Title page" -> editorial (title= match, case-insensitive).
    div1 "A Plain Account of Christian Perfection" -> container with 6 div2.
    div1 "Indexes" -> editorial (title= match).

  Editorial patterns (all works):
    title= attribute: "Title Page", "Title page" -> re match ^title\\s*page$
    title= attribute: "Indexes" -> re match ^indexes?
    Orphan divs (no content, no children): filtered in parse_div step 8.
    These are inherited from ccel_puritan_works.py unchanged.

Usage:
    py -3 build/parsers/ccel_evangelical_holiness.py --dry-run
    py -3 build/parsers/ccel_evangelical_holiness.py --author finney --download
    py -3 build/parsers/ccel_evangelical_holiness.py --work bounds-power-through-prayer --download --parse
    py -3 build/parsers/ccel_evangelical_holiness.py --all --download --parse
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
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
SOURCES_DIR = REPO_ROOT / "sources" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_evangelical_holiness.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"
CCEL_BASE = "https://www.ccel.org/ccel"

# ---------------------------------------------------------------------------
# Author metadata
# ---------------------------------------------------------------------------

AUTHOR_CONFIG = {
    "finney": {
        "author": "Charles G. Finney",
        "author_id": "finney-charles",
        "author_birth_year": 1792,
        "author_death_year": 1875,
        "tradition": ["evangelical", "arminian", "revivalist", "congregationalist"],
        "tradition_notes": (
            "Finney was the leading revivalist of the Second Great Awakening."
            " President of Oberlin College 1851-1866. Known for 'new measures'"
            " revivalism and his systematic theology emphasizing human agency."
            " Theologically Arminian and anti-confessional; trained as a Congregationalist."
        ),
        "era": "modern",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "bounds": {
        "author": "E.M. Bounds",
        "author_id": "bounds-e-m",
        "author_birth_year": 1835,
        "author_death_year": 1913,
        "tradition": ["methodist", "evangelical", "wesleyan"],
        "tradition_notes": (
            "Edward McKendree Bounds was a Methodist Episcopal minister known for"
            " rising at 4am daily for three hours of prayer. He wrote nine books"
            " on prayer, most published posthumously by Fleming H. Revell."
            " Associated with the Holiness Movement within Methodism."
        ),
        "era": "modern",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "pascal": {
        "author": "Blaise Pascal",
        "author_id": "pascal-blaise",
        "author_birth_year": 1623,
        "author_death_year": 1662,
        "tradition": ["catholic", "jansenist"],
        "tradition_notes": (
            "Pascal was a French mathematician, physicist, and Christian apologist."
            " His Pensées, left unfinished at his death, present a defense of"
            " Christianity through sustained philosophical and rhetorical argument."
            " His theology was influenced by Jansenism (Port-Royal)."
        ),
        "era": "post-reformation",
        "audience": "scholarly",
        "language": "en",
        "original_language": "fr",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
    "wesley-extra": {
        "author": "John Wesley",
        "author_id": "john-wesley",
        "author_birth_year": 1703,
        "author_death_year": 1791,
        "tradition": ["wesleyan", "methodist"],
        "tradition_notes": (
            "Wesley was the founder of Methodism and principal theologian of the"
            " Wesleyan-Arminian tradition. His doctrine of entire sanctification"
            " (Christian perfection) shaped the Holiness movement."
        ),
        "era": "modern",
        "audience": "lay",
        "language": "en",
        "original_language": "en",
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": "full",
    },
}


def _validate_work_configs() -> None:
    for author_id, cfg in AUTHOR_CONFIG.items():
        for t in cfg.get("tradition", []):
            assert t in STRUCTURED_TEXT__META__TRADITION, f"{author_id}: invalid tradition {t!r}"
        if era := cfg.get("era"):
            assert era in STRUCTURED_TEXT__META__ERA, f"{author_id}: invalid era {era!r}"
        if aud := cfg.get("audience"):
            assert aud in STRUCTURED_TEXT__META__AUDIENCE, f"{author_id}: invalid audience {aud!r}"
        if comp := cfg.get("completeness"):
            assert comp in STRUCTURED_TEXT__META__COMPLETENESS, f"{author_id}: invalid completeness {comp!r}"
    for cfg in WORK_CONFIG:
        slug = cfg.get("slug", "?")
        if wk := cfg.get("work_kind"):
            assert wk in STRUCTURED_TEXT__DATA__WORK_KIND, f"{slug}: invalid work_kind {wk!r}"

# ---------------------------------------------------------------------------
# Work registry
# ---------------------------------------------------------------------------

WORK_CONFIG = [
    # Charles G. Finney -- 2 works
    {
        "author_id": "finney",
        "slug": "finney-systematic-theology",
        "ccel_id": "theology",
        "author_ccel_path": "finney",
        "title": "Systematic Theology",
        "work_kind": "systematic-theology",
        "pub_year": 1878,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " Based on the 1878 revised edition (Oberlin, Ohio)."
        ),
    },
    {
        "author_id": "finney",
        "slug": "finney-lectures-on-revivals",
        "ccel_id": "revivals",
        "author_ccel_path": "finney",
        "title": "Lectures on Revivals of Religion",
        "work_kind": "treatise",
        "pub_year": 1835,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: New York, 1835.",
    },
    # E.M. Bounds -- 7 works
    # Copyright resolved 2026-06-03: Baker Book House 1976 "uncopyrighted" reprint of
    # the Complete Works confirms no copyright renewal on any Bounds volume, including
    # Necessity of Prayer (1929) and Weapon of Prayer (1931). All 7 now treated as PD.
    {
        "author_id": "bounds",
        "slug": "bounds-power-through-prayer",
        "ccel_id": "power",
        "author_ccel_path": "bounds",
        "title": "Power Through Prayer",
        "work_kind": "devotional-classic",
        "pub_year": 1907,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: Marshall Brothers, London, 1907.",
    },
    {
        "author_id": "bounds",
        "slug": "bounds-purpose-in-prayer",
        "ccel_id": "purpose",
        "author_ccel_path": "bounds",
        "title": "Purpose in Prayer",
        "work_kind": "devotional-classic",
        "pub_year": 1920,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: Fleming H. Revell, 1920.",
    },
    {
        "author_id": "bounds",
        "slug": "bounds-prayer-and-praying-men",
        "ccel_id": "prayingmen",
        "author_ccel_path": "bounds",
        "title": "Prayer and Praying Men",
        "work_kind": "devotional-classic",
        "pub_year": 1921,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: Fleming H. Revell, 1921.",
    },
    {
        "author_id": "bounds",
        "slug": "bounds-reality-of-prayer",
        "ccel_id": "reality",
        "author_ccel_path": "bounds",
        "title": "The Reality of Prayer",
        "work_kind": "devotional-classic",
        "pub_year": 1924,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: Fleming H. Revell, 1924.",
    },
    {
        "author_id": "bounds",
        "slug": "bounds-essentials-of-prayer",
        "ccel_id": "essentials",
        "author_ccel_path": "bounds",
        "title": "The Essentials of Prayer",
        "work_kind": "devotional-classic",
        "pub_year": 1925,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: Fleming H. Revell, 1925.",
    },
    {
        "author_id": "bounds",
        "slug": "bounds-necessity-of-prayer",
        "ccel_id": "necessity",
        "author_ccel_path": "bounds",
        "title": "The Necessity of Prayer",
        "work_kind": "devotional-classic",
        "pub_year": 1929,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org). Original: Fleming H. Revell, 1929."
            " Baker 1976 uncopyrighted reprint confirms no renewal on any Bounds volume."
        ),
    },
    {
        "author_id": "bounds",
        "slug": "bounds-weapon-of-prayer",
        "ccel_id": "weapon",
        "author_ccel_path": "bounds",
        "title": "The Weapon of Prayer",
        "work_kind": "devotional-classic",
        "pub_year": 1931,
        "contributors": [],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org). Original: Fleming H. Revell, 1931."
            " Baker 1976 uncopyrighted reprint confirms no renewal on any Bounds volume."
        ),
    },
    # Blaise Pascal -- 1 work (W.F. Trotter translation, first published 1910, US PD)
    {
        "author_id": "pascal",
        "slug": "pascal-pensees",
        "ccel_id": "pensees",
        "author_ccel_path": "pascal",
        "title": "Pensées",
        "work_kind": "theological-work",
        "pub_year": 1660,
        "contributors": [
            {"name": "W.F. Trotter", "role": "translator"},
        ],
        "source_edition": (
            "CCEL ThML edition (sourced via CCEL.org)."
            " English translation by W.F. Trotter, first published 1910 by"
            " J.M. Dent & Sons (London) / E.P. Dutton (New York), Everyman's Library No. 874."
            " Translation is US public domain (first published 1910, pre-1928)."
        ),
    },
    # John Wesley -- Plain Account (distinct from Wesley Sermons already in OCD)
    {
        "author_id": "wesley-extra",
        "slug": "wesley-plain-account",
        "ccel_id": "perfection",
        "author_ccel_path": "wesley",
        "title": "A Plain Account of Christian Perfection",
        "work_kind": "theological-work",
        "pub_year": 1777,
        "contributors": [],
        "source_edition": "CCEL ThML edition (sourced via CCEL.org). Original: London, 1777.",
    },
]


_validate_work_configs()

# ---------------------------------------------------------------------------
# ThML entity map (HTML entities not valid XML without the external DTD)
# Copied from ccel_puritan_works.py -- shared infrastructure
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

# ---------------------------------------------------------------------------
# Parsing constants
# ---------------------------------------------------------------------------

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])

HEADING_RE = re.compile(
    r"^((?:Book|Part|Chapter|Sermon|Section|Discourse|Treatise|Lecture)\s+[IVXLC\d]+\.?)\s*:?\s*(.*)",
    re.IGNORECASE,
)

_HEADING_WORD_TO_TYPE = {
    "book": "book",
    "part": "part",
    "chapter": "chapter",
    "sermon": "chapter",
    "section": "section",
    "discourse": "chapter",
    "treatise": "chapter",
    "lecture": "chapter",
}

_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])

_DIV_TAG_RE = re.compile(r"^div\d?$")

_parse_warnings: list = []


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _raw_path(work_cfg: dict) -> Path:
    return REPO_ROOT / "raw" / "ccel" / work_cfg["author_ccel_path"] / f"{work_cfg['ccel_id']}.xml"


def download_work(work_cfg: dict, force: bool = False, log_fn=None) -> None:
    """Download a single work XML from CCEL if not already cached."""
    if log_fn is None:
        log_fn = lambda m: print(m.encode("ascii", errors="replace").decode("ascii"))
    dest = _raw_path(work_cfg)
    if dest.exists() and not force:
        size_kb = dest.stat().st_size // 1024
        log_fn(f"  Cached: {dest.name} ({size_kb} KB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['ccel_id']}.xml"
    log_fn(f"  Downloading {url} ...")
    _TRANSIENT_STATUS = frozenset([429, 500, 502, 503, 504])
    last_exc = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            with open(dest, "wb") as fh:
                fh.write(data)
            dl_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            work_cfg["download_date"] = dl_date
            log_fn(f"  Downloaded {len(data) // 1024} KB -> {dest.name}")
            return
        except urllib.error.HTTPError as exc:
            if exc.code in _TRANSIENT_STATUS:
                last_exc = exc
                wait = 2 ** attempt
                log_fn(f"  Transient HTTP {exc.code}; retrying in {wait}s (attempt {attempt}/3) ...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Download failed for {work_cfg['ccel_id']}: HTTP {exc.code}. "
                    "Check the CCEL URL in WORK_CONFIG."
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            wait = 2 ** attempt
            log_fn(f"  Network error ({exc}); retrying in {wait}s (attempt {attempt}/3) ...")
            time.sleep(wait)
    raise RuntimeError(
        f"Download failed after 3 attempts for {work_cfg['ccel_id']}: {last_exc}."
    ) from last_exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _replace_entity(match: re.Match) -> str:
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """Prepare raw ThML bytes for ElementTree."""
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
    """Recursively collect all text content, skipping footnote/metadata tags."""
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
    """Collect scripture references from <scripRef> elements within elem."""
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
# Parser helpers
# ---------------------------------------------------------------------------

def _first_heading_text(div_elem) -> str:
    for child in div_elem:
        if child.tag in _HEADING_TAGS:
            return clean_text(get_all_text(child))
    return ""


def is_editorial_div(div_elem, is_top_level: bool) -> bool:
    """
    Return True if this div should be excluded as editorial apparatus.

    Checks (in order):
      1. is_top_level AND type='Preface'
      2. type in ('Titlepage', 'Back', 'Index', 'Indexes')
      3. type='Preface' AND heading matches /prefatory note/i
      4. heading matches /^indexes?$/i
      5. title= matches /^title\\s*page$/i
      6. title= matches /^acknowledg/i
      7. title= matches /^contents?$/i
      8. title= matches /^indexes?/i or /^index\\s+of/i
      9. heading matches /^brief\\s+memoir/i
      10. heading matches /^to\\s+the\\s+reader$/i
      11. heading matches /advertisement\\s+to\\s+the\\s+reader/i
    """
    div_type = div_elem.get("type", "")

    if is_top_level and div_type == "Preface":
        return True
    if div_type in ("Titlepage", "Back", "Index", "Indexes"):
        return True
    heading = _first_heading_text(div_elem)
    if div_type == "Preface" and re.search(r"prefatory note", heading, re.IGNORECASE):
        return True
    if re.match(r"^indexes?$", heading, re.IGNORECASE):
        return True

    title_attr = (div_elem.get("title") or "").strip()
    if re.match(r"^title\s*page$", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^acknowledg", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^contents?$", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^indexes?", title_attr, re.IGNORECASE):
        return True
    if re.match(r"^index\s+of", title_attr, re.IGNORECASE):
        return True

    if re.search(r"^brief\s+memoir", heading, re.IGNORECASE):
        return True
    if re.match(r"^to\s+the\s+reader$", heading, re.IGNORECASE):
        return True
    if re.search(r"advertisement\s+to\s+the\s+reader", heading, re.IGNORECASE):
        return True

    return False


def extract_heading(div_elem) -> tuple:
    """
    Extract (label, title) from a div element.

    Algorithm (same as ccel_puritan_works.py):
      1. Collect all h1/h2/h3/h4/title direct children.
      2. Scan each h* for HEADING_RE match (first match wins).
         Scanning all h* handles works where decorative headings precede real ones.
      3. HEADING_RE matched + non-empty title: return (label, title).
      4. HEADING_RE matched + empty title: check title= attr for subtitle.
      5. No h* matched HEADING_RE:
         a. Try title= attribute — HEADING_RE match: return (label, title).
         b. title= exists, no match: return ('', title_attr).
         c. Fall back to first h* raw text: return ('', first_h_text).
      6. Nothing: return ('', '').
    """
    h_texts = []
    for child in div_elem:
        if child.tag in _HEADING_TAGS:
            h_texts.append(clean_text(get_all_text(child)))

    for h_text in h_texts:
        if not h_text:
            continue
        m = HEADING_RE.match(h_text)
        if m:
            label = m.group(1).rstrip(".").strip()
            title = m.group(2).rstrip(".").strip()
            if not title:
                title_attr = (div_elem.get("title") or "").strip()
                if title_attr:
                    m2 = HEADING_RE.match(title_attr)
                    if m2:
                        title = m2.group(2).rstrip(".").strip()
            return label, title

    title_attr = (div_elem.get("title") or "").strip()
    if title_attr:
        m = HEADING_RE.match(title_attr)
        if m:
            return m.group(1).rstrip(".").strip(), m.group(2).rstrip(".").strip()
        return "", title_attr.rstrip(".").strip()

    if h_texts:
        return "", (h_texts[0] or "").rstrip(".").strip()

    return "", ""


# ---------------------------------------------------------------------------
# Parse engine
# ---------------------------------------------------------------------------

def _infer_section_type_from_heading(heading_text: str) -> str:
    if not heading_text:
        return ""
    m = HEADING_RE.match(heading_text)
    if m:
        first_word = m.group(1).lower().split()[0]
        return _HEADING_WORD_TO_TYPE.get(first_word, "section")
    return ""


def parse_div(div_elem, depth: int = 0):
    """
    Recursively parse a div element into a section dict (or list of dicts).

    Returns:
      None        -- editorial div, skip it
      list[dict]  -- Work/Appendices container; returns its children
      dict        -- a single section node
    """
    global _parse_warnings

    if is_editorial_div(div_elem, is_top_level=(depth == 0)):
        return None

    div_type = div_elem.get("type", "")

    if div_type in ("Work", "Appendices"):
        children = []
        for ch in div_elem:
            if not _DIV_TAG_RE.match(ch.tag):
                continue
            result = parse_div(ch, depth + 1)
            if result is None:
                continue
            if isinstance(result, list):
                children.extend(result)
            else:
                children.append(result)
        return children

    _type_map = {
        "Part": "part",
        "Chapter": "chapter",
        "Section": "section",
        "Sermon": "chapter",
        "Preface": "preface",
        "Appendix": "appendix",
    }
    if div_type:
        section_type = _type_map.get(div_type, "section")
    else:
        section_type = ""

    label, title = extract_heading(div_elem)

    content_blocks = []
    for child in div_elem:
        if child.tag in _HEADING_TAGS or child.tag in _SKIP_TAGS:
            continue
        if child.tag in ("p", "argument"):
            text = clean_text(get_all_text(child))
            if text:
                content_blocks.append(text)

    children = []
    for child in div_elem:
        if not _DIV_TAG_RE.match(child.tag):
            continue
        result = parse_div(child, depth + 1)
        if result is None:
            continue
        if isinstance(result, list):
            children.extend(result)
        else:
            children.append(result)

    if not content_blocks and not children:
        _parse_warnings.append(
            f"Skipping orphan leaf {div_elem.get('id', '?')} type={div_type!r}"
            f" title={div_elem.get('title', '')!r} (no content)"
        )
        return None

    if not section_type:
        heading_text = (label + " " + title).strip() if label else title
        inferred = _infer_section_type_from_heading(heading_text)
        if inferred:
            section_type = inferred
        elif children and not content_blocks:
            section_type = "part"
        elif content_blocks:
            section_type = "chapter"
        else:
            section_type = "section"

    scripture_refs = get_scriptrefs(div_elem)
    word_count = count_words(content_blocks)

    return {
        "section_type": section_type,
        "label": label or None,
        "title": title or None,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": word_count,
        "children": children,
    }


def parse_work(work_cfg: dict, raw_bytes: bytes) -> dict:
    """Parse a single work's raw XML bytes into a structured_text data dict."""
    global _parse_warnings
    _parse_warnings = []

    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    if not work_cfg.get("download_date"):
        raw_path = _raw_path(work_cfg)
        if raw_path.exists():
            mtime = raw_path.stat().st_mtime
            work_cfg["download_date"] = datetime.fromtimestamp(
                mtime, tz=timezone.utc
            ).strftime("%Y-%m-%d")

    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse failed for {work_cfg['ccel_id']}: {exc}. "
            "Try re-downloading the file."
        ) from exc

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(
            f"No <ThML.body> found in {work_cfg['ccel_id']}. "
            "Unexpected XML structure."
        )

    sections = []
    for div in body:
        if not _DIV_TAG_RE.match(div.tag):
            continue
        result = parse_div(div, depth=0)
        if result is None:
            continue
        if isinstance(result, list):
            sections.extend(result)
        else:
            sections.append(result)

    if not sections:
        _parse_warnings.append(
            f"WARNING: 0 sections after editorial filtering for {work_cfg['ccel_id']}"
        )

    return {
        "work_id": work_cfg["slug"],
        "work_kind": work_cfg["work_kind"],
        "sections": sections,
        "_source_hash": source_hash,
        "_download_date": work_cfg.get("download_date", ""),
        "_warnings": list(_parse_warnings),
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(work_cfg: dict, parse_result: dict) -> dict:
    """Build the meta envelope for a single work."""
    author_cfg = AUTHOR_CONFIG[work_cfg["author_id"]]
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['ccel_id']}.xml"

    notes_parts = [
        "ThML HTML entities replaced with Unicode equivalents.",
        "DOCTYPE stripped before parsing.",
        "Footnotes (<note>) and page breaks (<pb>) excluded from content.",
        "robots.txt crawl-delay 10s honoured.",
        "Sourced via CCEL.org.",
    ]

    return {
        "id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": author_cfg["author"],
        "author_birth_year": author_cfg["author_birth_year"],
        "author_death_year": author_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("pub_year"),
        "language": author_cfg["language"],
        "original_language": author_cfg["original_language"],
        "tradition": author_cfg["tradition"],
        "tradition_notes": author_cfg["tradition_notes"],
        "era": author_cfg["era"],
        "audience": author_cfg["audience"],
        "license": author_cfg["license"],
        "schema_type": author_cfg["schema_type"],
        "schema_version": author_cfg["schema_version"],
        "completeness": work_cfg.get("completeness") or author_cfg["completeness"],
        "provenance": {
            "source_url": source_url,
            "source_format": "ThML XML",
            "source_edition": work_cfg.get("source_edition", "CCEL ThML edition (sourced via CCEL.org)."),
            "download_date": parse_result.get("_download_date", ""),
            "source_hash": parse_result["_source_hash"],
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_evangelical_holiness.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": " ".join(notes_parts),
        },
    }


# ---------------------------------------------------------------------------
# Source config writer
# ---------------------------------------------------------------------------

def write_source_config(work_cfg: dict, parse_result: dict) -> None:
    """Write sources/structured-text/{slug}/config.json for this work."""
    author_cfg = AUTHOR_CONFIG[work_cfg["author_id"]]
    source_url = f"{CCEL_BASE}/{work_cfg['author_ccel_path']}/{work_cfg['ccel_id']}.xml"
    slug = work_cfg["slug"]
    cfg_dir = SOURCES_DIR / slug
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "resource_id": slug,
        "title": work_cfg["title"],
        "author": author_cfg["author"],
        "author_birth_year": author_cfg["author_birth_year"],
        "author_death_year": author_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("pub_year"),
        "language": author_cfg["language"],
        "original_language": author_cfg["original_language"],
        "tradition": author_cfg["tradition"],
        "tradition_notes": author_cfg["tradition_notes"],
        "era": author_cfg["era"],
        "audience": author_cfg["audience"],
        "license": author_cfg["license"],
        "schema_type": "structured_text",
        "work_kind": work_cfg["work_kind"],
        "source_url": source_url,
        "source_format": "ThML XML",
        "source_edition": work_cfg.get("source_edition", "CCEL ThML edition (sourced via CCEL.org)."),
        "source_hash": parse_result["_source_hash"],
        "download_date": parse_result.get("_download_date", ""),
        "output_file": f"data/structured-text/{slug}.json",
        "notes": (
            "CCEL confirmed OK to parse (Quincy, 2026-04-01)."
            " Crawl-delay 10s per robots.txt."
            " ThML entities replaced; DOCTYPE stripped; footnotes excluded."
        ),
    }
    cfg_path = cfg_dir / "config.json"
    with open(cfg_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def _sum_tree_words(sections: list) -> int:
    total = 0
    for s in sections:
        total += s.get("word_count", 0)
        total += _sum_tree_words(s.get("children", []))
    return total


def _count_tree_sections(sections: list) -> int:
    count = len(sections)
    for s in sections:
        count += _count_tree_sections(s.get("children", []))
    return count


def _count_chapters(sections: list) -> int:
    count = 0
    for s in sections:
        if s.get("section_type") == "chapter":
            count += 1
        count += _count_chapters(s.get("children", []))
    return count


def _find_orphans(sections: list) -> int:
    count = 0
    for s in sections:
        if not s.get("content_blocks") and not s.get("children"):
            count += 1
        count += _find_orphans(s.get("children", []))
    return count


def report_work_quality(work_cfg: dict, parse_result: dict, log_fn=None) -> None:
    if log_fn is None:
        log_fn = lambda m: print(m.encode("ascii", errors="replace").decode("ascii"))
    sections = parse_result["sections"]
    top_count = len(sections)
    chapter_count = _count_chapters(sections)
    total_words = _sum_tree_words(sections)
    total_sec = _count_tree_sections(sections)
    orphans = _find_orphans(sections)

    slug = work_cfg["slug"]
    log_fn(
        f"  {slug}: {top_count} top-level sections,"
        f" {chapter_count} chapters, ~{total_words // 1000}k words"
    )
    if total_sec > 0:
        log_fn(f"  Quality: {total_sec} total nodes, {orphans} orphans")
    for w in parse_result.get("_warnings", []):
        safe_w = w.encode("ascii", errors="replace").decode("ascii")
        log_fn(f"  WARN: {safe_w}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Evangelical & Holiness classics (8 titles, 4 authors) from CCEL ThML XML"
    )
    parser.add_argument("--author", metavar="AUTHOR_ID", help="Process all works for one author")
    parser.add_argument("--work", metavar="SLUG", help="Process a single work by slug")
    parser.add_argument("--all", action="store_true", dest="all_works", help="Process all works")
    parser.add_argument("--download", action="store_true", help="Download work(s) from CCEL")
    parser.add_argument("--parse", action="store_true", help="Parse cached raw files and write JSON")
    parser.add_argument("--force", action="store_true", help="Re-download even if already cached")
    parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run",
        help="Parse first work per author, print to stdout, no file writes",
    )
    args = parser.parse_args()

    if not args.download and not args.parse and not args.dry_run:
        parser.print_help()
        sys.exit(0)

    if args.work:
        works = [w for w in WORK_CONFIG if w["slug"] == args.work]
        if not works:
            print(f"ERROR: unknown slug '{args.work}'")
            print(f"Valid slugs: {[w['slug'] for w in WORK_CONFIG]}")
            sys.exit(1)
    elif args.author:
        works = [w for w in WORK_CONFIG if w["author_id"] == args.author]
        if not works:
            print(f"ERROR: unknown author_id '{args.author}'")
            print(f"Valid IDs: {sorted({w['author_id'] for w in WORK_CONFIG})}")
            sys.exit(1)
    else:
        works = list(WORK_CONFIG)

    start_time = time.time()
    log_lines = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    works_parsed = 0
    total_sections = 0
    total_words = 0

    try:
        log(f"Evangelical & Holiness parser {SCRIPT_VERSION}")
        log(
            f"Works: {len(works)}"
            f"  download={args.download}"
            f"  parse={args.parse}"
            f"  dry-run={args.dry_run}"
        )
        log("")

        if args.dry_run:
            log("=== Dry-run mode (first work per author) ===")
            seen_authors: set = set()
            for work in works:
                aid = work["author_id"]
                if aid in seen_authors:
                    continue
                seen_authors.add(aid)
                raw_path = _raw_path(work)
                if not raw_path.exists():
                    log(f"  SKIP (not cached): {work['slug']} -- run --download first")
                    continue
                log(f"  Parsing {work['slug']} ...")
                try:
                    raw_bytes = raw_path.read_bytes()
                    parse_result = parse_work(work, raw_bytes)
                except RuntimeError as exc:
                    log(f"  ERROR: {exc}")
                    errors += 1
                    continue
                report_work_quality(work, parse_result, log_fn=log)
                for i, sec in enumerate(parse_result["sections"][:3]):
                    safe_title = (sec.get("title") or "").encode("ascii", errors="replace").decode("ascii")
                    log(
                        f"    [{i}] type={sec['section_type']!r}"
                        f" label={sec.get('label')!r}"
                        f" title={safe_title!r}"
                        f" blocks={len(sec.get('content_blocks', []))}"
                        f" children={len(sec.get('children', []))}"
                    )
                    if sec.get("content_blocks"):
                        sample = sec["content_blocks"][0][:100].encode("ascii", errors="replace").decode("ascii")
                        log(f"         sample: {sample}")
                log("")
            log("=== Dry-run complete ===")
            return

        if args.download:
            log("=== Download phase ===")
            for i, work in enumerate(works):
                raw_path = _raw_path(work)
                if raw_path.exists() and not args.force:
                    log(f"  [{i+1}/{len(works)}] {work['ccel_id']}: cached, skipping")
                    continue
                if i > 0:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                log(f"  [{i+1}/{len(works)}] {work['slug']} ...")
                try:
                    download_work(work, force=args.force, log_fn=log)
                except RuntimeError as exc:
                    log(f"  ERROR (download): {exc}")
                    errors += 1
            log("")

        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            for i, work in enumerate(works):
                raw_path = _raw_path(work)
                if not raw_path.exists():
                    log(
                        f"  ERROR: raw file missing for {work['ccel_id']}."
                        " Run --download first."
                    )
                    errors += 1
                    continue

                log(f"  [{i+1}/{len(works)}] Parsing {work['slug']} ...")
                try:
                    raw_bytes = raw_path.read_bytes()
                    parse_result = parse_work(work, raw_bytes)
                except RuntimeError as exc:
                    log(f"  ERROR (parse): {exc}")
                    errors += 1
                    continue

                report_work_quality(work, parse_result, log_fn=log)

                out_path = OUTPUT_DIR / f"{work['slug']}.json"
                try:
                    meta = build_meta(work, parse_result)
                    data = {
                        "work_id": parse_result["work_id"],
                        "work_kind": parse_result["work_kind"],
                        "sections": parse_result["sections"],
                    }
                    output = {"meta": meta, "data": data}
                    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                        json.dump(output, fh, ensure_ascii=False, indent=2)
                        fh.write("\n")
                except Exception as exc:
                    if out_path.exists():
                        out_path.unlink()  # standards: log/temp rotation
                    log(f"  ERROR (write JSON): {work['slug']}: {exc}")
                    errors += 1
                    continue

                try:
                    write_source_config(work, parse_result)
                except Exception as exc:
                    log(f"  WARN (source config): {work['slug']}: {exc}")

                size_kb = out_path.stat().st_size // 1024
                log(f"  Wrote {size_kb} KB -> {out_path.name}")
                files_written += 1
                works_parsed += 1
                total_sections += _count_tree_sections(parse_result["sections"])
                total_words += _sum_tree_words(parse_result["sections"])
                log("")

            total_words_m = total_words / 1_000_000
            log(
                f"TOTAL: {works_parsed} works parsed,"
                f" {total_sections} total sections,"
                f" ~{total_words_m:.1f}M words"
            )

    finally:
        elapsed = time.time() - start_time
        summary = (
            f"Done in {elapsed:.1f}s. "
            f"Works parsed: {works_parsed}/{len(works)}. "
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
