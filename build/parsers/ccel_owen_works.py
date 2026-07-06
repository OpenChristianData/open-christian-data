"""ccel_owen_works.py
Parser for John Owen's theological works (32 titles) from CCEL ThML XML.

Downloads {ccel_id}.xml from CCEL once per work, then parses the full section
tree into OCD structured_text JSON files (one per work).

Source: Works of John Owen, ed. William H. Goold, Johnstone and Hunter,
Edinburgh, 1850-1853. CCEL confirmed OK to parse (Quincy, 2026-04-01).
robots.txt: crawl-delay 10 for all agents (confirmed 2026-04-12).

XML structure (census across 5 sampled works -- mort, deathofdeath, communion,
pneum, sermons):
  Root: <ThML> with no namespaces; DOCTYPE stripped before parsing.
  Body: <ThML.body> containing div1..div4 elements.
  div type= attribute is the reliable structural signal (not div depth).
  Observed type= values and handling:
    Work       -> root container; walk children, do not create section node
    Part       -> section_type='part'
    Chapter    -> section_type='chapter'
    Section    -> section_type='section'
    Sermon     -> section_type='chapter' (per-sermon divs in sermons.xml)
    Preface    -> include (Owen's own) or exclude (Goold's) -- see is_editorial_div
    Appendix   -> section_type='appendix'
    Appendices -> walk children, do not create section node
    Titlepage  -> SKIP
    Back       -> SKIP
    Index      -> SKIP
    Indexes    -> SKIP
  Heading elements: h1 (parts/books), h2 (chapters, sermons), h3 (rare).
    The div title= attribute is a reliable fallback.
  osisRef prefix variants: 'Bible:Book.ch.v' (mort) and
    'Bible.kjv:Book.ch.v' (deathofdeath, communion, pneum, sermons).
  <argument> elements appear alongside <p> (chapter synopses); treated as
    content_blocks.
  <scripContext> sets default Bible version; skipped.
  No section-sign heading pattern (section-sign is Hodge-specific, not Owen).

Usage:
    py -3 build/parsers/ccel_owen_works.py --download mort
    py -3 build/parsers/ccel_owen_works.py --download
    py -3 build/parsers/ccel_owen_works.py --parse mort
    py -3 build/parsers/ccel_owen_works.py --parse
    py -3 build/parsers/ccel_owen_works.py --download --parse mort
    py -3 build/parsers/ccel_owen_works.py --download --parse
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
from build.lib._generated_enums import (  # noqa: E402
    STRUCTURED_TEXT__DATA__WORK_KIND,
    STRUCTURED_TEXT__META__AUDIENCE,
    STRUCTURED_TEXT__META__COMPLETENESS,
    STRUCTURED_TEXT__META__ERA,
    STRUCTURED_TEXT__META__TRADITION,
)
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "owen"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_owen_works.log"

SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"
CCEL_BASE = "https://www.ccel.org/ccel/owen"

WORK_CONFIG = [
    # Priority works (census-sampled in Phase 1)
    {"slug": "mortification",         "ccel_id": "mort",               "title": "Of the Mortification of Sin in Believers",                                          "work_kind": "treatise",           "pub_year": 1656},
    {"slug": "death-of-death",        "ccel_id": "deathofdeath",       "title": "Death of Death in the Death of Christ",                                             "work_kind": "treatise",           "pub_year": 1647},
    {"slug": "communion",             "ccel_id": "communion",          "title": "Of Communion with God the Father, Son and Holy Ghost",                               "work_kind": "treatise",           "pub_year": 1657},
    {"slug": "pneumatologia",         "ccel_id": "pneum",              "title": "Pneumatologia: A Discourse Concerning the Holy Spirit",                              "work_kind": "treatise",           "pub_year": 1674},
    {"slug": "justification",         "ccel_id": "just",               "title": "The Doctrine of Justification by Faith",                                            "work_kind": "treatise",           "pub_year": 1677},
    {"slug": "indwelling-sin",        "ccel_id": "indwellingsin",      "title": "Indwelling Sin in Believers",                                                       "work_kind": "treatise",           "pub_year": 1668},
    {"slug": "glory",                 "ccel_id": "glory",              "title": "Meditations and Discourses on the Glory of Christ",                                  "work_kind": "devotional-classic", "pub_year": 1684},
    {"slug": "spiritually-minded",    "ccel_id": "spirituallyminded",  "title": "Grace and Duty of being Spiritually Minded",                                        "work_kind": "treatise",           "pub_year": 1681},
    # Remaining works
    {"slug": "temptation",            "ccel_id": "temptation",         "title": "Of Temptation: The Nature and Power of It",                                         "work_kind": "treatise",           "pub_year": 1658},
    {"slug": "apostasy",              "ccel_id": "apostasy",           "title": "Nature and Causes of Apostasy from the Gospel",                                     "work_kind": "treatise",           "pub_year": 1676},
    {"slug": "display-arminianism",   "ccel_id": "display",            "title": "A Display of Arminianism",                                                          "work_kind": "treatise",           "pub_year": 1642},
    {"slug": "trinity",               "ccel_id": "trinity",            "title": "Brief Declaration and Vindication of the Doctrine of the Trinity",                  "work_kind": "treatise",           "pub_year": 1669},
    {"slug": "divine-justice",        "ccel_id": "justice",            "title": "A Dissertation on Divine Justice",                                                  "work_kind": "treatise",           "pub_year": 1653},
    {"slug": "perseverance",          "ccel_id": "perseverance",       "title": "The Doctrine of the Saints' Perseverance",                                          "work_kind": "treatise",           "pub_year": 1654},
    {"slug": "schism",                "ccel_id": "schism",             "title": "Of Schism",                                                                         "work_kind": "treatise",           "pub_year": 1657},
    {"slug": "worship",               "ccel_id": "worship",            "title": "A Brief Instruction in the Worship of God",                                         "work_kind": "treatise",           "pub_year": 1667},
    {"slug": "evangelical-churches",  "ccel_id": "evangelicalchurches","title": "An Inquiry into the Original, Nature, and Communion of Evangelical Churches",      "work_kind": "treatise",           "pub_year": 1681},
    {"slug": "church-love",           "ccel_id": "churchlove",         "title": "Discourse concerning Evangelical Love, Church Peace, and Unity",                   "work_kind": "treatise",           "pub_year": 1672},
    {"slug": "liturgies",             "ccel_id": "liturgies",          "title": "Discourse Concerning Liturgies, and their Imposition",                             "work_kind": "treatise",           "pub_year": 1662},
    {"slug": "psalm130",              "ccel_id": "psalm130",           "title": "A Practical Exposition upon Psalm CXXX",                                            "work_kind": "treatise",           "pub_year": 1668},
    {"slug": "faith-elect",           "ccel_id": "faith",              "title": "Gospel Grounds and Evidences of the Faith of God's Elect",                         "work_kind": "treatise",           "pub_year": 1695},
    {"slug": "sin-grace",             "ccel_id": "sin_grace",          "title": "A Treatise of the Dominion of Sin and Grace",                                       "work_kind": "treatise",           "pub_year": 1688},
    {"slug": "pastors-people",        "ccel_id": "pastorspeople",      "title": "The Duty of Pastors and People Distinguished",                                      "work_kind": "treatise",           "pub_year": 1644},
    {"slug": "vindiciae-evangelicae", "ccel_id": "vindicevang",        "title": "Vindiciae Evangelicae: The Mystery of the Gospel Vindicated",                      "work_kind": "treatise",           "pub_year": 1655},
    {"slug": "grotius",               "ccel_id": "grotius",            "title": "A Review of the Annotations of Hugo Grotius",                                       "work_kind": "treatise",           "pub_year": 1656},
    {"slug": "conscience",            "ccel_id": "conscience",         "title": "Several Practical Cases of Conscience Resolved",                                    "work_kind": "treatise",           "pub_year": 1720},
    {"slug": "sacramental-discourses","ccel_id": "discourses",         "title": "Sacramental Discourses",                                                            "work_kind": "treatise",           "pub_year": 1727},
    {"slug": "eshcol",                "ccel_id": "eshcol",             "title": "Eshcol: A Cluster of the Fruit of Canaan",                                          "work_kind": "treatise",           "pub_year": 1648},
    {"slug": "truth-innocence",       "ccel_id": "truthinnocence",     "title": "Truth and Innocence Vindicated",                                                    "work_kind": "treatise",           "pub_year": 1669},
    {"slug": "sermons",               "ccel_id": "sermons",            "title": "Sermons of John Owen",                                                              "work_kind": "treatise",           "pub_year": None},
    # catechism-prose: Q&A content; could feed catechism_qa schema in a future pass
    {"slug": "two-catechisms",        "ccel_id": "catechisms",         "title": "Two Short Catechisms",                                                              "work_kind": "catechism-prose",    "pub_year": 1645},
    # poema: Latin poem -- if confirmed Latin-only with no PD English translation,
    # parse produces a stub with sections=[] and a note in provenance
    {"slug": "poema",                 "ccel_id": "poema",              "title": "Poema",                                                                             "work_kind": "treatise",           "pub_year": None},
]

# Shared author metadata applied to all works
AUTHOR_META = {
    "author": "John Owen",
    "author_birth_year": 1616,
    "author_death_year": 1683,
    "contributors": ["William H. Goold (editor, Johnstone and Hunter, Edinburgh, 1850-1853)"],
    "language": "en",
    "original_language": "en",
    "tradition": ["reformed", "puritan", "nonconformist"],
    "tradition_notes": (
        "Owen served as Dean of Christ Church, Oxford and Vice-Chancellor of the"
        " University. The preeminent English Calvinist systematic theologian of the"
        " 17th century."
    ),
    "era": "post-reformation",
    "audience": "scholarly",
    "license": "public-domain",
    "schema_type": "structured_text",
    "schema_version": SCHEMA_VERSION,
    "completeness": "full",
}


def _validate_work_configs() -> None:
    for cfg in WORK_CONFIG:
        slug = cfg.get("slug", "?")
        if wk := cfg.get("work_kind"):
            assert wk in STRUCTURED_TEXT__DATA__WORK_KIND, f"{slug}: invalid work_kind {wk!r}"
    for t in AUTHOR_META.get("tradition", []):
        assert t in STRUCTURED_TEXT__META__TRADITION, f"AUTHOR_META: invalid tradition {t!r}"
    if era := AUTHOR_META.get("era"):
        assert era in STRUCTURED_TEXT__META__ERA, f"AUTHOR_META: invalid era {era!r}"
    if aud := AUTHOR_META.get("audience"):
        assert aud in STRUCTURED_TEXT__META__AUDIENCE, f"AUTHOR_META: invalid audience {aud!r}"
    if comp := AUTHOR_META.get("completeness"):
        assert comp in STRUCTURED_TEXT__META__COMPLETENESS, f"AUTHOR_META: invalid completeness {comp!r}"


_validate_work_configs()

# ---------------------------------------------------------------------------
# ThML entity map (HTML entities not valid XML without the external DTD)
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

# Matches "Book I.", "Part I. Title text", "Chapter III.", "Sermon V. Title" etc.
HEADING_RE = re.compile(
    r"^((?:Book|Part|Chapter|Sermon|Section|Discourse|Treatise)\s+[IVXLC\d]+\.?)\s*(.*)",
    re.IGNORECASE,
)

# Tags skipped entirely when collecting text content (Hodge set + scripContext)
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])

# Regex matching a div* tag: div, div1, div2, div3, div4, div5
_DIV_TAG_RE = re.compile(r"^div\d?$")

# Module-level list for warnings collected during parse_div; reset per work in parse_work
_parse_warnings: list = []


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_work(work_cfg: dict, force: bool = False) -> None:
    """Download a single Owen work XML from CCEL if not already cached."""
    dest = RAW_DIR / f"{work_cfg['ccel_id']}.xml"
    if dest.exists() and not force:
        size_kb = dest.stat().st_size // 1024
        print(f"  Source cached: {dest.name} ({size_kb} KB)")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{CCEL_BASE}/{work_cfg['ccel_id']}.xml"
    print(f"  Downloading {url} ...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with open(dest, "wb") as fh:
            fh.write(data)
        download_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        work_cfg["download_date"] = download_date
        print(f"  Downloaded {len(data) // 1024} KB -> {dest.name}")
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for {work_cfg['ccel_id']}: {exc}. "
            "Check network access and CCEL availability."
        ) from exc


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------

def _replace_entity(match: re.Match) -> str:
    """Replace a named HTML entity if known; drop unknown ones silently."""
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """
    Prepare raw ThML bytes for ElementTree:
    1. Decode -- UTF-8 with cp1252 fallback.
    2. Strip DOCTYPE declaration (prevents external DTD fetch attempt).
    3. Replace HTML entities with Unicode equivalents.
    """
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
    """Collapse internal whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def get_scriptrefs(elem) -> list:
    """
    Collect scripture references from <scripRef> elements within elem.
    Handles both 'Bible:Book.ch.v' and 'Bible.kjv:Book.ch.v' prefix forms.
    """
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
    """Count words across a list of text strings."""
    return sum(len(b.split()) for b in blocks)


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

def build_output_id(slug: str) -> str:
    """Build the output ID for a work from its slug."""
    return f"john-owen-{slug}"


def _first_heading_text(div_elem) -> str:
    """Return text of first h1/h2/h3/h4/title direct child, or ''."""
    for child in div_elem:
        if child.tag in _HEADING_TAGS:
            return clean_text(get_all_text(child))
    return ""


def is_editorial_div(div_elem, is_top_level: bool) -> bool:
    """
    Return True if this div should be excluded as editorial apparatus.

    Exclusion criteria:
      1. is_top_level AND type='Preface' (all top-level Prefaces are Goold's)
      2. type in ('Titlepage', 'Back', 'Index', 'Indexes')
      3. type='Preface' AND first heading matches /prefatory note/i
      4. first heading matches /^indexes?$/i
    """
    div_type = div_elem.get("type", "")
    # Criterion 1: top-level Preface divs are always Goold's collection preface
    if is_top_level and div_type == "Preface":
        return True
    # Criterion 2: structural back-matter types
    if div_type in ("Titlepage", "Back", "Index", "Indexes"):
        return True
    heading = _first_heading_text(div_elem)
    # Criterion 3: non-top-level Preface with "prefatory note" heading
    if div_type == "Preface" and re.search(r"prefatory note", heading, re.IGNORECASE):
        return True
    # Criterion 4: any div whose first heading is literally "index" or "indexes"
    if re.match(r"^indexes?$", heading, re.IGNORECASE):
        return True
    return False


def extract_heading(div_elem) -> tuple:
    """
    Extract (label, title) from a div element.

    Algorithm:
      1. Collect all h1/h2/h3/h4/title direct children.
      2. Scan each for HEADING_RE match (first match wins). Scanning all h*
         handles divs with decorative headings before the real chapter heading.
      3. If match and title non-empty: return (label, title).
      4. If match but title empty (e.g. 'CHAPTER I'): check title= attr for
         the descriptive subtitle.
      5. No h* matched HEADING_RE: try title= attr via HEADING_RE or raw text.
      6. Fall back to first h* raw text.
      7. Nothing: return ('', '').
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

def parse_div(div_elem, depth: int = 0):
    """
    Recursively parse a div element into a section dict (or list of dicts).

    Returns:
      None        -- editorial div, skip it
      list[dict]  -- Work/Appendices container; returns its children directly
      dict        -- a single section node
    """
    global _parse_warnings

    # Step 1: editorial check
    if is_editorial_div(div_elem, is_top_level=(depth == 0)):
        return None

    div_type = div_elem.get("type", "")

    # Step 3: Work and Appendices are containers -- return their children as a flat list
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

    # Step 4: determine section_type
    _type_map = {
        "Part": "part",
        "Chapter": "chapter",
        "Section": "section",
        "Sermon": "chapter",
        "Preface": "preface",
        "Appendix": "appendix",
    }
    section_type = _type_map.get(div_type, "section")

    # Step 5: extract label and title
    label, title = extract_heading(div_elem)

    # Step 10: prayer content warning
    if label and re.match(r"^a prayer", label, re.IGNORECASE):
        _parse_warnings.append(
            f"Prayer content at {div_elem.get('id', '?')}: {label}"
        )
    if title and re.match(r"^a prayer", title, re.IGNORECASE):
        _parse_warnings.append(
            f"Prayer content at {div_elem.get('id', '?')}: {title}"
        )

    # Step 6: collect content_blocks from direct <p> and <argument> children
    content_blocks = []
    for child in div_elem:
        if child.tag in _HEADING_TAGS or child.tag in _SKIP_TAGS:
            continue
        if child.tag in ("p", "argument"):
            text = clean_text(get_all_text(child))
            if text:
                content_blocks.append(text)

    # Step 7: collect child sections recursively
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

    # Filter orphan leaf nodes (e.g. image-only Specimen facsimile pages)
    if not content_blocks and not children:
        _parse_warnings.append(
            f"Skipping orphan leaf {div_elem.get('id', '?')} type={div_type!r} (no content)"
        )
        return None

    # Steps 8-9
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
    """
    Parse a single Owen work's raw XML bytes into a structured_text data dict.

    Returns a dict with work_id, work_kind, sections, _source_hash,
    _download_date, _warnings, and _is_stub keys.
    """
    global _parse_warnings
    _parse_warnings = []

    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()

    # Backfill download_date from file mtime for pre-cached files
    if not work_cfg.get("download_date"):
        raw_path = RAW_DIR / f"{work_cfg['ccel_id']}.xml"
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

    # Check for poema Latin-only edge case using lang="LA" attribute as primary signal
    is_stub = False
    stub_note = ""
    if work_cfg["ccel_id"] == "poema":
        # lang="LA" attributes appear on text elements when the content is Latin
        latin_lang_count = xml_text.count('lang="LA"')
        if latin_lang_count > 0:
            is_stub = True
            stub_note = (
                "Poema is a Latin poem with no known public-domain English"
                " translation. Sections excluded; stub entry written for"
                " catalogue completeness."
            )
            _parse_warnings.append(
                f"WARNING: poema confirmed Latin (lang=\"LA\" found {latin_lang_count} times)"
                " -- writing stub with sections=[]"
            )

    sections = []
    if not is_stub:
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
        "work_id": build_output_id(work_cfg["slug"]),
        "work_kind": work_cfg["work_kind"],
        "sections": sections,
        "_source_hash": source_hash,
        "_download_date": work_cfg.get("download_date", ""),
        "_warnings": list(_parse_warnings),
        "_is_stub": is_stub,
        "_stub_note": stub_note,
    }


# ---------------------------------------------------------------------------
# Metadata builder
# ---------------------------------------------------------------------------

def build_meta(work_cfg: dict, parse_result: dict) -> dict:
    """Build the meta envelope for a single Owen work."""
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    notes_parts = [
        "ThML HTML entities replaced with Unicode equivalents.",
        "DOCTYPE stripped before parsing.",
        "Footnotes (<note>) and page breaks (<pb>) excluded from content.",
        "Editorial prefaces (Goold) excluded; Owen's own prefaces included.",
        "robots.txt crawl-delay 10s honoured.",
    ]
    if work_cfg["ccel_id"] == "catechisms":
        notes_parts.append(
            "Q&A catechism content. Could feed catechism_qa schema in a future pass."
        )
    if parse_result.get("_stub_note"):
        notes_parts.append(parse_result["_stub_note"])

    return {
        "id": build_output_id(work_cfg["slug"]),
        "title": work_cfg["title"],
        "author": AUTHOR_META["author"],
        "author_birth_year": AUTHOR_META["author_birth_year"],
        "author_death_year": AUTHOR_META["author_death_year"],
        "contributors": normalize_contributors(AUTHOR_META["contributors"]),
        "original_publication_year": work_cfg.get("pub_year"),
        "language": AUTHOR_META["language"],
        "original_language": AUTHOR_META["original_language"],
        "tradition": AUTHOR_META["tradition"],
        "tradition_notes": AUTHOR_META["tradition_notes"],
        "era": AUTHOR_META["era"],
        "audience": AUTHOR_META["audience"],
        "license": AUTHOR_META["license"],
        "schema_type": AUTHOR_META["schema_type"],
        "schema_version": AUTHOR_META["schema_version"],
        "completeness": AUTHOR_META["completeness"],
        "provenance": {
            "source_url": f"{CCEL_BASE}/{work_cfg['ccel_id']}",
            "source_format": "ThML XML",
            "source_edition": (
                "Works of John Owen, ed. William H. Goold,"
                " Johnstone and Hunter, Edinburgh, 1850-1853"
            ),
            "download_date": parse_result.get("_download_date", ""),
            "source_hash": parse_result["_source_hash"],
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_owen_works.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": " ".join(notes_parts),
        },
    }


# ---------------------------------------------------------------------------
# Quality reporting
# ---------------------------------------------------------------------------

def _sum_tree_words(sections: list) -> int:
    """Recursively sum word_count across all section nodes."""
    total = 0
    for s in sections:
        total += s.get("word_count", 0)
        total += _sum_tree_words(s.get("children", []))
    return total


def _count_tree_sections(sections: list) -> int:
    """Recursively count all section nodes."""
    count = len(sections)
    for s in sections:
        count += _count_tree_sections(s.get("children", []))
    return count


def _count_chapters(sections: list) -> int:
    """Recursively count nodes with section_type='chapter'."""
    count = 0
    for s in sections:
        if s.get("section_type") == "chapter":
            count += 1
        count += _count_chapters(s.get("children", []))
    return count


def _find_orphans(sections: list) -> int:
    """Count nodes with 0 content_blocks AND 0 children."""
    count = 0
    for s in sections:
        if not s.get("content_blocks") and not s.get("children"):
            count += 1
        count += _find_orphans(s.get("children", []))
    return count


def _count_null_labels(sections: list) -> tuple:
    """Return (null_label_count, null_title_count) across all section nodes."""
    no_label = no_title = 0
    for s in sections:
        if s.get("label") is None:
            no_label += 1
        if s.get("title") is None:
            no_title += 1
        sub_l, sub_t = _count_null_labels(s.get("children", []))
        no_label += sub_l
        no_title += sub_t
    return no_label, no_title


def report_work_quality(work_cfg: dict, parse_result: dict) -> None:
    """Print per-work quality stats (PIPE-02)."""
    sections = parse_result["sections"]
    top_count = len(sections)
    chapter_count = _count_chapters(sections)
    total_words = _sum_tree_words(sections)
    total_sec = _count_tree_sections(sections)
    orphans = _find_orphans(sections)
    no_label, no_title = _count_null_labels(sections)

    slug = work_cfg["slug"]
    print(
        f"  john-owen-{slug}: {top_count} top-level sections,"
        f" {chapter_count} total chapters, ~{total_words // 1000}k words"
    )
    if total_sec > 0:
        print(
            f"  Quality: {total_sec} total nodes,"
            f" {no_label}/{total_sec} no-label,"
            f" {no_title}/{total_sec} no-title"
        )
    if orphans:
        print(f"  WARNING: {orphans} orphan nodes (0 content_blocks, 0 children)")
    for w in parse_result.get("_warnings", []):
        safe_w = w.encode("ascii", errors="replace").decode("ascii")
        print(f"  {safe_w}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse John Owen's works (32 titles) from CCEL ThML XML"
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download work(s) from CCEL",
    )
    parser.add_argument(
        "--parse",
        action="store_true",
        help="Parse cached raw files and write JSON output",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if already cached",
    )
    parser.add_argument(
        "ccel_id",
        nargs="?",
        default=None,
        metavar="CCEL_ID",
        help="Process only this work (e.g. mort). Omit to process all.",
    )
    args = parser.parse_args()

    if not args.download and not args.parse:
        parser.print_help()
        sys.exit(0)

    # Resolve which works to process
    if args.ccel_id:
        works = [w for w in WORK_CONFIG if w["ccel_id"] == args.ccel_id]
        if not works:
            print(f"ERROR: unknown ccel_id '{args.ccel_id}'")
            print(f"Valid IDs: {[w['ccel_id'] for w in WORK_CONFIG]}")
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
        log(f"John Owen works parser {SCRIPT_VERSION}")
        log(f"Works: {len(works)}  download={args.download}  parse={args.parse}")
        log("")

        # --- Download phase ---
        if args.download:
            log("=== Download phase ===")
            for i, work in enumerate(works):
                dest = RAW_DIR / f"{work['ccel_id']}.xml"
                if dest.exists() and not args.force:
                    log(f"  [{i+1}/{len(works)}] {work['ccel_id']}: cached, skipping")
                    continue
                if i > 0:
                    log(f"  Waiting {CRAWL_DELAY}s (robots.txt crawl-delay) ...")
                    time.sleep(CRAWL_DELAY)
                log(f"  [{i+1}/{len(works)}] {work['ccel_id']} ...")
                try:
                    download_work(work, force=args.force)
                except RuntimeError as exc:
                    log(f"  ERROR (download): {exc}")
                    errors += 1
            log("")

        # --- Parse phase ---
        if args.parse:
            log("=== Parse phase ===")
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            for i, work in enumerate(works):
                raw_path = RAW_DIR / f"{work['ccel_id']}.xml"
                if not raw_path.exists():
                    log(
                        f"  ERROR: raw file missing for {work['ccel_id']}."
                        " Run --download first."
                    )
                    errors += 1
                    continue

                log(f"  [{i+1}/{len(works)}] Parsing {work['ccel_id']} ...")
                try:
                    raw_bytes = raw_path.read_bytes()
                    parse_result = parse_work(work, raw_bytes)
                except RuntimeError as exc:
                    log(f"  ERROR (parse): {exc}")
                    errors += 1
                    continue

                report_work_quality(work, parse_result)

                # Latin-only works (poema): log and skip output file
                if parse_result.get("_is_stub"):
                    log(f"  SKIP (Latin-only): no output file written for {work['ccel_id']}")
                    for w in parse_result.get("_warnings", []):
                        log(f"  {w}")
                    log("")
                    continue

                # Build and write output (REL-08: guarded so one failure doesn't stop batch)
                out_path = OUTPUT_DIR / f"{parse_result['work_id']}.json"
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
                    # Remove partially-written file to avoid leaving corrupt output
                    if out_path.exists():
                        out_path.unlink()  # standards: log/temp rotation
                    log(f"  ERROR (write): {work['ccel_id']}: {exc}")
                    errors += 1
                    continue

                size_kb = out_path.stat().st_size // 1024
                log(f"  Wrote {size_kb} KB -> {out_path.name}")
                files_written += 1
                works_parsed += 1
                total_sections += _count_tree_sections(parse_result["sections"])
                total_words += _sum_tree_words(parse_result["sections"])
                log("")

            # Total summary
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
