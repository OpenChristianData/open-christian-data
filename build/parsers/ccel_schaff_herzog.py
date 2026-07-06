"""ccel_schaff_herzog.py
Parser for the New Schaff-Herzog Encyclopedia of Religious Knowledge (CCEL ThML XML).

Downloads individual volume XML files from CCEL, parses encyclopedia articles,
and writes OCD reference_entry schema output to a single merged JSON file.

Source: https://www.ccel.org/ccel/schaff/encycNN.xml (ThML XML, public domain)

XML structure (inspected 2026-04-12 via Vol. 1):
  - Root: <ThML> -- well-formed UTF-8 XML, no DOCTYPE, no namespace
  - Articles: <glossary> contains alternating <term type="Encyclopedia"> + <def> pairs
  - Body paragraphs: <p class="normal"> and <p class="continue"> inside <def>
  - Skip: <p class="author">, <p class="bib2">, <p class="bib2Cont">
  - Scripture refs: <scripRef osisRef="Bible:..."> -- extract osisRef when present
  - Cross-references: <span class="sc"> inside <a xml:link="simple"> -> related_terms
  - Page breaks: <pb> elements -- ignore

All 13 volumes US public domain (published 1908-1914, pre-1928).
Permission confirmed: CCEL (Quincy, 2026-04-01).

Usage:
    py -3 build/parsers/ccel_schaff_herzog.py --volume encyc01          # process vol 1
    py -3 build/parsers/ccel_schaff_herzog.py --volume encyc02          # process vol 2
    py -3 build/parsers/ccel_schaff_herzog.py --all                     # process all 13
    py -3 build/parsers/ccel_schaff_herzog.py --volume encyc01 --dry-run
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import unicodedata
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from xml.etree import ElementTree as ET

from build.lib._generated_enums import (
    REFERENCE_ENTRY__META__COMPLETENESS,
    REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD,
    REFERENCE_ENTRY__META__TRADITION,
)
from build.lib.text_layers import assert_surface_field_invariant, build_reference_layers

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

from build.lib.paths import REPO_ROOT  # noqa: E402
RAW_DIR = REPO_ROOT / "raw" / "ccel" / "schaff-herzog"
OUTPUT_DIR = REPO_ROOT / "data" / "reference"
OUTPUT_FILE = OUTPUT_DIR / "schaff-herzog-encyclopedia.json"
LOG_PATH = REPO_ROOT / "logs" / "ccel_schaff_herzog.log"

SCHEMA_VERSION = "2.1.0"
DICTIONARY_ID = "schaff-herzog-encyclopedia"

for _t in ["ecumenical", "evangelical"]:
    assert _t in REFERENCE_ENTRY__META__TRADITION, f"invalid tradition {_t!r}"
assert "full" in REFERENCE_ENTRY__META__COMPLETENESS, "invalid completeness 'full'"
assert "automated" in REFERENCE_ENTRY__META__PROVENANCE__PROCESSING_METHOD, "invalid processing_method 'automated'"

# User-Agent as agreed with CCEL contact (crawl-delay: 10s per robots.txt)
USER_AGENT = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)

# Download delay between multiple files (robots.txt specifies 10s)
DOWNLOAD_DELAY_SECONDS = 10

# All 13 volume IDs -- Vol. 13 is the index volume
ALL_VOLUMES = [
    "encyc01", "encyc02", "encyc03", "encyc04", "encyc05",
    "encyc06", "encyc07", "encyc08", "encyc09", "encyc10",
    "encyc11", "encyc12", "encyc13",
]

# Base URL pattern for CCEL volumes
CCEL_BASE_URL = "https://www.ccel.org/ccel/schaff/{volume_id}.xml"

# Download date -- set once per run (approximate; actual download may vary)
DOWNLOAD_DATE = "2026-04-13"

# XML-safe entities -- leave these alone during entity preprocessing
XML_SAFE_ENTITIES = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}

# ThML HTML entities not in base XML spec (same map as ccel_devotional.py)
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
    "&acirc;": "\u00e2",
    "&atilde;": "\u00e3",
    "&auml;": "\u00e4",
    "&aring;": "\u00e5",
    "&aelig;": "\u00e6",
    "&ccedil;": "\u00e7",
    "&egrave;": "\u00e8",
    "&eacute;": "\u00e9",
    "&ecirc;": "\u00ea",
    "&euml;": "\u00eb",
    "&igrave;": "\u00ec",
    "&iacute;": "\u00ed",
    "&icirc;": "\u00ee",
    "&iuml;": "\u00ef",
    "&eth;": "\u00f0",
    "&ntilde;": "\u00f1",
    "&ograve;": "\u00f2",
    "&oacute;": "\u00f3",
    "&ocirc;": "\u00f4",
    "&otilde;": "\u00f5",
    "&ouml;": "\u00f6",
    "&oslash;": "\u00f8",
    "&ugrave;": "\u00f9",
    "&uacute;": "\u00fa",
    "&ucirc;": "\u00fb",
    "&uuml;": "\u00fc",
    "&yacute;": "\u00fd",
    "&thorn;": "\u00fe",
    "&yuml;": "\u00ff",
    "&Agrave;": "\u00c0",
    "&Aacute;": "\u00c1",
    "&Acirc;": "\u00c2",
    "&Atilde;": "\u00c3",
    "&Auml;": "\u00c4",
    "&Aring;": "\u00c5",
    "&AElig;": "\u00c6",
    "&Ccedil;": "\u00c7",
    "&Egrave;": "\u00c8",
    "&Eacute;": "\u00c9",
    "&Ecirc;": "\u00ca",
    "&Euml;": "\u00cb",
    "&Igrave;": "\u00cc",
    "&Iacute;": "\u00cd",
    "&Icirc;": "\u00ce",
    "&Iuml;": "\u00cf",
    "&ETH;": "\u00d0",
    "&Ntilde;": "\u00d1",
    "&Ograve;": "\u00d2",
    "&Oacute;": "\u00d3",
    "&Ocirc;": "\u00d4",
    "&Otilde;": "\u00d5",
    "&Ouml;": "\u00d6",
    "&Oslash;": "\u00d8",
    "&Ugrave;": "\u00d9",
    "&Uacute;": "\u00da",
    "&Ucirc;": "\u00db",
    "&Uuml;": "\u00dc",
    "&Yacute;": "\u00dd",
    "&THORN;": "\u00de",
    "&szlig;": "\u00df",
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

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure file + console logging. Log file at logs/ccel_schaff_herzog.log."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
            logging.StreamHandler(),
        ],
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def download_volume(volume_id: str) -> Path:
    """Download one volume XML to raw/ccel/schaff-herzog/ if not already cached.

    Returns the local file path.
    Skips download if file already exists.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    local_path = RAW_DIR / f"{volume_id}.xml"

    if local_path.exists():
        logger.info("  Cached: %s (%s)", local_path.name, _human_size(local_path.stat().st_size))
        return local_path

    url = CCEL_BASE_URL.format(volume_id=volume_id)
    logger.info("  Downloading %s ...", url)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
        with open(str(local_path), "wb") as f:
            f.write(data)
        size_kb = len(data) / 1024
        file_hash = hashlib.sha256(data).hexdigest()
        logger.info("  Downloaded %.0f KB -> %s", size_kb, local_path.name)
        logger.info("  SHA-256: %s", file_hash)
        print(f"  SHA-256 ({volume_id}): {file_hash}")
        return local_path
    except Exception as exc:
        raise RuntimeError(
            f"Download failed for {volume_id}: {exc}. "
            f"Check network access and try again."
        ) from exc


def _human_size(n: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


# ---------------------------------------------------------------------------
# XML preprocessing
# ---------------------------------------------------------------------------


def _replace_entity(match: re.Match) -> str:
    """Replace a named HTML entity with its Unicode equivalent.

    Leaves XML-safe entities (&amp; etc.) untouched.
    Drops any unknown entities that would break ElementTree parsing.
    """
    ent = match.group(0)
    if ent in XML_SAFE_ENTITIES:
        return ent
    replacement = THML_ENTITY_MAP.get(ent)
    if replacement is not None:
        return replacement
    # Unknown entity -- drop it to avoid parse failure
    return ""


def preprocess_thml(raw_bytes: bytes) -> str:
    """Prepare raw ThML bytes for ElementTree parsing.

    1. Decode as UTF-8 (Schaff-Herzog volumes are well-formed UTF-8)
    2. Strip DOCTYPE declaration if present (prevents external DTD fetch)
    3. Replace HTML named entities with Unicode equivalents
    """
    try:
        text = raw_bytes.decode("utf-8")
        if "\ufffd" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        # Fall back to cp1252 for files with Windows-1252 smart quotes
        text = raw_bytes.decode("cp1252", errors="replace")

    # Strip DOCTYPE declaration (may span multiple lines)
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)

    # Replace named HTML entities not in base XML spec
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


# ---------------------------------------------------------------------------
# Slugify and ID helpers
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Convert term text to a URL-safe lowercase slug.

    Normalizes Unicode to ASCII where possible, strips punctuation,
    collapses whitespace to hyphens.
    """
    # Normalize Unicode (e.g. accented chars -> ASCII base where possible)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    # Lowercase
    text = text.lower()
    # Replace non-alphanumeric chars (keep hyphens) with hyphens
    text = re.sub(r"[^\w\s-]", "-", text)
    # Collapse whitespace and hyphens to single hyphen
    text = re.sub(r"[\s_-]+", "-", text.strip())
    # Strip leading/trailing hyphens
    text = text.strip("-")
    return text or "entry"


def make_unique_id(base: str, seen: set) -> str:
    """Return base if not in seen, else base-2, base-3, etc.

    Uses a set as the source of truth (PIPE-04) to avoid silent duplicates.
    """
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Scripture reference extraction
# ---------------------------------------------------------------------------


def extract_scripture_refs(def_elem) -> list:
    """Extract scripture references from <scripRef osisRef="..."> elements.

    Only processes elements that have an osisRef attribute -- some scripRef
    elements tag dates (e.g. passage="Mar. 23, 789") with no osisRef.

    The osisRef value may be space-separated (multiple refs in one attribute).
    Each is split into its own Reference object.

    Returns a list of {"raw": str, "osis": [str]} objects.
    """
    refs = []
    for scripref in def_elem.iter("scripRef"):
        osis_attr = scripref.get("osisRef", "").strip()
        if not osis_attr:
            continue
        # Space-separated list of refs in a single osisRef value
        for raw_ref in osis_attr.split():
            # Strip "Bible:" prefix if present
            clean_ref = raw_ref.removeprefix("Bible:")
            if clean_ref:
                refs.append({"raw": clean_ref, "osis": [clean_ref]})
    return refs


# ---------------------------------------------------------------------------
# Related terms extraction
# ---------------------------------------------------------------------------


def extract_related_terms(def_elem) -> list:
    """Extract cross-reference terms from <a> elements.

    Vol. 1 uses <a xml:link="simple"><span class="sc">Target</span></a>.
    Vol. 2 omits xml:link but still uses <span class="sc"> inside <a>.

    Detection strategy: an <a> is a cross-reference if it either:
      (a) has xml:link="simple" attribute, OR
      (b) contains a <span class="sc"> child (reliable marker in both volumes)

    Returns a deduplicated list of term strings in document order.
    """
    seen = set()
    terms = []
    for a_elem in def_elem.iter("a"):
        # Strategy (a): xml:link="simple" attribute (Vol. 1 style)
        has_xmllink = any(
            attr_val == "simple"
            for attr_name, attr_val in a_elem.attrib.items()
            if attr_name in ("xml:link", "{http://www.w3.org/XML/1998/namespace}link")
        )

        # Find <span class="sc"> inside this anchor
        sc_spans = [
            span for span in a_elem.iter("span")
            if span.get("class") == "sc"
        ]

        # Strategy (b): contains a <span class="sc"> (Vol. 2 style)
        has_sc_span = bool(sc_spans)

        if not (has_xmllink or has_sc_span):
            continue  # Not a cross-reference anchor

        for span in sc_spans:
            term_text = clean_text(get_all_text(span))
            if term_text and term_text not in seen:
                seen.add(term_text)
                terms.append(term_text)
    return terms


# ---------------------------------------------------------------------------
# Definition blocks extraction
# ---------------------------------------------------------------------------


def extract_definition_blocks(def_elem) -> list:
    """Extract body text paragraphs from a <def> element.

    Uses a blacklist approach: skip known non-body elements, include everything
    else as body text. This handles structural variation across volumes -- Vol. 1
    uses class="normal"/"continue", Vol. 2 uses class="" and other class names.

    Included: <p> with body classes, <h1>-<h5> section headings, <div> wrappers,
              <table>, <verse> elements.
    Skipped:  <p class="author">, <p class="bib2"/"bib2Cont"/"bib3"/"center"/"skip">,
              <pb> page break markers.
    """
    # Classes that indicate non-body content (case-sensitive)
    SKIP_P_CLASSES = {"author", "bib2", "bib2Cont", "bib3", "center", "skip"}
    # Heading tags to include as body text blocks
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5"}
    # Tags to include by extracting all their text recursively
    INCLUDE_TAGS = {"p", "div", "table", "verse"} | HEADING_TAGS

    blocks = []

    for elem in def_elem:
        tag = elem.tag
        if tag == "pb":
            continue  # Page break marker -- ignore
        if tag not in INCLUDE_TAGS:
            continue  # Unknown/unexpected element -- skip safely
        p_class = elem.get("class", "")
        if tag == "p" and p_class in SKIP_P_CLASSES:
            continue  # Author, bibliography, etc. -- skip
        text = clean_text(get_all_text(elem))
        if text:
            blocks.append(text)
    return blocks


# ---------------------------------------------------------------------------
# Article parser (glossary-level)
# ---------------------------------------------------------------------------


def parse_glossary(glossary_elem) -> list:
    """Parse all term+def pairs from a single <glossary> element.

    Returns a list of raw article dicts:
      {term, definition_blocks, scripture_references, related_terms}
    """
    articles = []
    children = list(glossary_elem)

    i = 0
    while i < len(children):
        child = children[i]

        # Look for <term type="Encyclopedia">
        if child.tag == "term" and child.get("type") == "Encyclopedia":
            term_text = clean_text(get_all_text(child))
            i += 1

            # The next sibling should be <def>
            if i < len(children) and children[i].tag == "def":
                def_elem = children[i]
                i += 1

                definition_blocks = extract_definition_blocks(def_elem)
                scripture_refs = extract_scripture_refs(def_elem)
                related_terms = extract_related_terms(def_elem)

                articles.append({
                    "term": term_text,
                    "definition_blocks": definition_blocks,
                    "scripture_references": scripture_refs,
                    "related_terms": related_terms,
                })
            else:
                # <term> with no following <def> -- include with empty body
                logger.warning("  <term> with no <def>: '%s'", term_text[:60])
                articles.append({
                    "term": term_text,
                    "definition_blocks": [],
                    "scripture_references": [],
                    "related_terms": [],
                })
        else:
            i += 1

    return articles


# ---------------------------------------------------------------------------
# Volume parser
# ---------------------------------------------------------------------------


def parse_volume(volume_id: str) -> list:
    """Parse all encyclopedia articles from one volume XML file.

    Downloads the file if not already cached.
    Returns a list of raw article dicts.
    """
    local_path = download_volume(volume_id)
    logger.info("  Parsing %s ...", local_path.name)

    raw_bytes = local_path.read_bytes()
    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(
            f"XML parse error in {local_path.name}: {exc}. "
            f"Check entity preprocessing or file integrity."
        ) from exc

    # Collect all <glossary> elements anywhere in the tree
    articles = []
    glossary_count = 0
    for glossary_elem in root.iter("glossary"):
        glossary_count += 1
        batch = parse_glossary(glossary_elem)
        articles.extend(batch)

    logger.info(
        "  Parsed %d glossary elements, %d articles from %s",
        glossary_count, len(articles), volume_id,
    )
    return articles


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------


def compute_source_hash(volume_ids: list) -> str:
    """Compute a combined SHA-256 hash of all downloaded volume files.

    Concatenates individual file hashes in volume-id order to produce a
    single deterministic hash representing all downloaded source files.
    """
    combined = hashlib.sha256()
    for vid in sorted(volume_ids):
        local_path = RAW_DIR / f"{vid}.xml"
        if local_path.exists():
            combined.update(local_path.read_bytes())
    return "sha256:" + combined.hexdigest()


def build_meta(volumes_processed: list) -> dict:
    """Build the meta envelope for the output file."""
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_hash = compute_source_hash(volumes_processed)
    return {
        "id": DICTIONARY_ID,
        "title": "New Schaff-Herzog Encyclopedia of Religious Knowledge",
        # Schema uses 'author' field; Jackson was the general editor of this encyclopedia
        "author": "Samuel Macauley Jackson",
        "original_publication_year": 1908,
        "language": "en",
        "tradition": ["ecumenical", "evangelical"],
        "tradition_notes": (
            "The New Schaff-Herzog (1908-1914) is the leading English-language Protestant "
            "reference work of the early 20th century, edited by Samuel Macauley Jackson. "
            "It reflects broadly ecumenical Reformed and Lutheran scholarship, drawing on "
            "German Realencyklopaedie fuer protestantische Theologie und Kirche (3rd ed.) "
            "with significant English additions."
        ),
        "license": "public-domain",
        "schema_type": "reference_entry",
        "schema_version": SCHEMA_VERSION,
        "text_layer_shape": "multi_field",
        "completeness": "full",
        "provenance": {
            "source_url": "https://www.ccel.org/ccel/schaff/",
            "source_format": "ThML XML",
            "source_edition": (
                "CCEL ThML edition of New Schaff-Herzog Encyclopedia of Religious Knowledge "
                "(13 vols, 1908-1914)"
            ),
            "download_date": DOWNLOAD_DATE,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": "build/parsers/ccel_schaff_herzog.py@v1.0.0",
            "processing_date": process_date,
            "notes": (
                f"Full acquisition complete. Text available for vols 1, 2, 9 only "
                f"({', '.join(sorted(volumes_processed))}). "
                "Vols 3-8, 10-12 are CCEL 'Digital facsimile edition' (image-only page scans, "
                "no machine-readable text). Vol 13 is the index volume (0 usable entries). "
                "Permission confirmed: CCEL (Quincy, 2026-04-01). "
                "All volumes US public domain (1908-1914, pre-1928). "
                "source_hash is combined SHA-256 of all downloaded volume XML files."
            ),
        },
    }


def build_entry(raw_article: dict, seen_ids: set, *, emit_layers: bool = False) -> dict:
    """Convert a raw parsed article into an OCD reference_entry record.

    Generates a unique entry_id using the term slug, with -2, -3, etc.
    suffixes on collision (PIPE-04).
    """
    term = raw_article["term"]
    base_id = f"schaff-herzog.{slugify(term)}"
    entry_id = make_unique_id(base_id, seen_ids)
    seen_ids.add(entry_id)

    blocks = raw_article["definition_blocks"]
    word_count = sum(len(b.split()) for b in blocks)

    entry = {
        "entry_id": entry_id,
        "dictionary_id": DICTIONARY_ID,
        "term": term,
        "alt_terms": [],
        "definition_blocks": blocks,
        "scripture_references": raw_article["scripture_references"],
        "related_terms": raw_article["related_terms"],
        "word_count": word_count,
    }
    if emit_layers:
        layers = build_reference_layers(
            term=term,
            alt_terms=[],
            definition_blocks=blocks,
            source_raw_term=raw_article.get("source_raw_term", term),
            normalised_term=raw_article.get("normalised_term", term),
            source_raw_blocks=raw_article.get("source_raw_definition_blocks", blocks),
            normalised_blocks=raw_article.get("normalised_definition_blocks", blocks),
            source_raw_origin="observed",
        )
        if layers:
            entry["layers"] = layers
        assert_surface_field_invariant(entry, text_layer_shape="multi_field")
    return entry


# ---------------------------------------------------------------------------
# Load / merge / save
# ---------------------------------------------------------------------------


def load_existing_output() -> tuple:
    """Load the existing output file if present.

    Returns (meta_or_None, entries_by_id_dict).
    The entries dict is keyed by entry_id for deduplication.
    """
    if not OUTPUT_FILE.exists():
        return None, {}

    try:
        with open(str(OUTPUT_FILE), encoding="utf-8") as f:
            existing = json.load(f)
        entries_by_id = {e["entry_id"]: e for e in existing.get("data", [])}
        meta = existing.get("meta")
        logger.info("  Loaded existing output: %d entries", len(entries_by_id))
        return meta, entries_by_id
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("  Could not read existing output (%s) -- starting fresh", exc)
        return None, {}


def save_output(entries_by_id: dict, volumes_processed: list) -> None:
    """Write the merged output JSON file."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    meta = build_meta(volumes_processed)
    data = list(entries_by_id.values())
    output = {"meta": meta, "data": data}

    with open(str(OUTPUT_FILE), "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    logger.info("  Wrote %d entries -> %s (%.0f KB)", len(data), OUTPUT_FILE.name, size_kb)


# ---------------------------------------------------------------------------
# Quality stats
# ---------------------------------------------------------------------------


def print_quality_stats(entries: list, volume_id: str) -> None:
    """Print quality stats for entries from one volume (PIPE-02)."""
    n = len(entries)
    if n == 0:
        logger.warning("  No entries to report quality stats for")
        return

    empty_blocks = sum(1 for e in entries if not e["definition_blocks"])
    short_entries = sum(1 for e in entries if e["word_count"] < 5)
    words = sorted(e["word_count"] for e in entries)
    median_words = words[n // 2]
    has_scripture = sum(1 for e in entries if e["scripture_references"])
    has_related = sum(1 for e in entries if e["related_terms"])

    logger.info("  Quality stats for %s (%d entries):", volume_id, n)
    logger.info(
        "    definition_blocks empty: %d/%d (%.1f%%)",
        empty_blocks, n, 100 * empty_blocks / n,
    )
    logger.info(
        "    word_count: min=%d median=%d max=%d",
        words[0], median_words, words[-1],
    )
    logger.info(
        "    entries with scripture_refs: %d/%d",
        has_scripture, n,
    )
    logger.info(
        "    entries with related_terms: %d/%d",
        has_related, n,
    )
    if short_entries:
        logger.info(
            "    entries under 5 words (cross-ref stubs expected): %d/%d",
            short_entries, n,
        )
    if empty_blocks:
        logger.warning(
            "    WARNING: %d entries have empty definition_blocks",
            empty_blocks,
        )


# ---------------------------------------------------------------------------
# Main processing logic
# ---------------------------------------------------------------------------


def process_volume(volume_id: str, dry_run: bool = False, *, emit_layers: bool = False) -> dict:
    """Process one volume: download, parse, merge into output file.

    In dry-run mode: parse only, no file writes. Print first 3 entries.
    Returns a stats dict.
    """
    logger.info("--- Processing %s ---", volume_id)

    raw_articles = parse_volume(volume_id)

    if not raw_articles:
        logger.error("  No articles found in %s -- check XML structure", volume_id)
        return {"volume": volume_id, "status": "error", "entry_count": 0}

    if dry_run:
        # Build entries in memory to verify correctness -- do not write
        # Skip entries with empty definition_blocks (schema requires non-empty)
        seen_ids: set = set()
        valid_articles = [a for a in raw_articles if a["definition_blocks"]]
        skipped = len(raw_articles) - len(valid_articles)
        if skipped:
            logger.warning("  [dry-run] Skipping %d entries with empty definition_blocks", skipped)
        entries = [build_entry(a, seen_ids, emit_layers=emit_layers) for a in valid_articles]
        logger.info("  [dry-run] %d articles -> %d entries", len(raw_articles), len(entries))
        for e in entries[:3]:
            logger.info(
                "  [dry-run]   entry_id=%s  blocks=%d  words=%d  refs=%d  related=%d",
                e["entry_id"],
                len(e["definition_blocks"]),
                e["word_count"],
                len(e["scripture_references"]),
                len(e["related_terms"]),
            )
        logger.info("  [dry-run] Would write to: %s", OUTPUT_FILE)
        print_quality_stats(entries, volume_id)
        return {
            "volume": volume_id,
            "status": "dry-run",
            "entry_count": len(entries),
        }

    # Load existing output and merge new entries
    _existing_meta, entries_by_id = load_existing_output()
    pre_merge_count = len(entries_by_id)

    # Build new entries. seen_ids starts with existing IDs to prevent new entries
    # from colliding with pre-existing ones.
    # Re-run idempotency: when the base slug already exists in the output, temporarily
    # discard it from seen_ids before calling build_entry so make_unique_id returns the
    # original base_id (overwriting the existing entry) rather than base_id-2 (adding a
    # duplicate). build_entry re-adds the ID to seen_ids as a side effect.
    seen_ids = set(entries_by_id.keys())
    new_entries = []
    overwritten = 0
    skipped_empty = 0
    for raw_article in raw_articles:
        # Skip entries with no body content -- schema requires non-empty definition_blocks
        if not raw_article["definition_blocks"]:
            skipped_empty += 1
            logger.warning(
                "  Skipping entry with empty definition_blocks: '%s'",
                raw_article["term"][:60],
            )
            continue
        base_id = f"schaff-herzog.{slugify(raw_article['term'])}"
        if base_id in entries_by_id:
            # Re-run: discard temporarily so make_unique_id returns base_id, not base_id-2
            seen_ids.discard(base_id)
            overwritten += 1
        entry = build_entry(raw_article, seen_ids, emit_layers=emit_layers)
        entries_by_id[entry["entry_id"]] = entry
        new_entries.append(entry)

    if skipped_empty:
        logger.warning(
            "  Skipped %d entries with empty definition_blocks (source data gap)",
            skipped_empty,
        )

    post_merge_count = len(entries_by_id)
    added_count = post_merge_count - pre_merge_count
    truly_new = len(new_entries) - overwritten
    if added_count != truly_new:
        logger.warning(
            "  MERGE MISMATCH: added_count=%d but truly_new=%d "
            "(unexpected duplicates or missing entries -- total: %d)",
            added_count, truly_new, post_merge_count,
        )
    logger.info(
        "  Merged: %d pre-existing + %d new = %d total (added %d, overwrote %d)",
        pre_merge_count, len(new_entries), post_merge_count, added_count, overwritten,
    )

    # Track which volumes are represented by reading existing meta's provenance
    # and merging in the current volume ID
    existing_vols: list = []
    if _existing_meta and _existing_meta.get("provenance", {}).get("notes"):
        # Extract volume IDs from notes using a simple pattern match
        vol_match = re.search(r"Pilot: volumes? ([\w,\s-]+) only\.", _existing_meta["provenance"]["notes"])
        if vol_match:
            existing_vols = [v.strip() for v in vol_match.group(1).split(",") if v.strip()]

    if volume_id not in existing_vols:
        existing_vols.append(volume_id)

    # Save merged output
    save_output(entries_by_id, existing_vols)

    print_quality_stats(new_entries, volume_id)

    return {
        "volume": volume_id,
        "status": "ok",
        "entry_count": len(new_entries),
        "total_after_merge": post_merge_count,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(
        description=(
            "Parse CCEL ThML XML volumes of the New Schaff-Herzog Encyclopedia "
            "of Religious Knowledge into OCD reference_entry schema."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--volume",
        metavar="VOLUME_ID",
        help="Volume to process, e.g. encyc01",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all 13 volumes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report -- do not write output files.",
    )
    parser.add_argument(
        "--emit-layers",
        action="store_true",
        help="Emit Phase C sparse text layers.",
    )
    args = parser.parse_args()

    if args.all:
        volumes = list(ALL_VOLUMES)
    else:
        vol = args.volume.lower().strip()
        if vol not in ALL_VOLUMES:
            logger.error(
                "Unknown volume '%s'. Valid volumes: %s",
                vol, ", ".join(ALL_VOLUMES),
            )
            sys.exit(1)
        volumes = [vol]

    logger.info("Schaff-Herzog parser starting")
    logger.info("Output file: %s", OUTPUT_FILE)
    logger.info("Log file: %s", LOG_PATH)
    logger.info("Dry-run: %s", args.dry_run)

    all_stats = []
    failed = []
    start_time = time.time()

    for idx, volume_id in enumerate(volumes, 1):
        if idx > 1 and not args.dry_run:
            # Respect robots.txt crawl-delay between downloads
            logger.info("  Waiting %ds between downloads (robots.txt crawl-delay)...",
                        DOWNLOAD_DELAY_SECONDS)
            time.sleep(DOWNLOAD_DELAY_SECONDS)

        logger.info("Volume %d of %d: %s", idx, len(volumes), volume_id)

        try:
            stats = process_volume(volume_id, dry_run=args.dry_run, emit_layers=args.emit_layers)
        except Exception as exc:
            logger.error("Unhandled error processing %s: %s", volume_id, exc, exc_info=True)
            stats = {"volume": volume_id, "status": "error", "entry_count": 0}

        all_stats.append(stats)
        if stats.get("status") == "error":
            failed.append(volume_id)

    elapsed = time.time() - start_time
    total_entries = sum(s.get("entry_count", 0) for s in all_stats)
    processed = [s for s in all_stats if s.get("status") not in ("error",)]

    lines = [
        "=== SUMMARY ===",
        f"  Volumes processed: {len(processed)}/{len(volumes)}",
        f"  Total entries this run: {total_entries}",
        f"  Elapsed: {elapsed:.1f}s",
    ]
    if not args.dry_run and all_stats:
        last_stat = all_stats[-1]
        if "total_after_merge" in last_stat:
            lines.append(f"  Total entries in output file: {last_stat['total_after_merge']}")
    if failed:
        lines.append(f"  FAILED volumes: {', '.join(failed)}")

    summary = "\n".join(lines)
    if failed:
        logger.error(summary)
    else:
        logger.info(summary)


if __name__ == "__main__":
    main()
