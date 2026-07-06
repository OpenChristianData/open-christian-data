"""ccel_robertson_word_pictures.py
Parser for A.T. Robertson's Word Pictures in the New Testament, Vol. I
(Matthew and Mark) from CCEL ThML XML.

Downloads wp_matt.xml and wp_mark.xml from the Christian Classics Ethereal
Library once (cached in raw/ccel/robertson-word-pictures/), parses the
<scripCom>-keyed chapter commentary blocks, and writes one JSON file per
Bible book to data/commentaries/robertson-word-pictures-vol1/ following the
OCD commentary schema v1.

Source: ccel.org/ccel/robertson_at/wp_matt and wp_mark
CCEL robots.txt: crawl-delay 10 for all agents (checked 2026-06-17).

A.T. Robertson (1863-1934). Vol. I published 1930 by R.H. Revell.
US public domain as of Jan 1, 2026.

XML structure (inspected 2026-06-17 against wp_matt.xml, wp_mark.xml):

  Root: <ThML> with DOCTYPE declaration (stripped before parsing).

  Body: <ThML.body>
    Front matter div1 (e.g. "Introduction") -- no <scripCom>, automatically
    skipped by the parser.

    Chapter divs (one per chapter):
      <div1 title="Chapter 1" id="iii">
        <scripCom type="Commentary" passage="Matthew 1"
                  osisRef="Bible:Matt.1" id="iii-p0.1"
                  parsed="|Matt|1|0|0|0" />
        <h2 id="iii-p0.2">Chapter 1</h2>
        <p id="iii-p1">1:1 <b>The Book</b> [<i>biblos</i>]. ...</p>
        <p id="iii-p2">...</p>
        ...
      </div1>

    The <scripCom> is always self-closing; the chapter commentary text
    follows as sibling <p> elements. Cross-refs use:
      <scripRef osisRef="Bible:Luke.4.17">Lu 4:17</scripRef>

  wp_matt.xml: 800 KB, 28 chapters (28 <scripCom> elements).
  wp_mark.xml: 554 KB, 16 chapters (16 <scripCom> elements).

  Entries are keyed at chapter granularity (one entry per <div1> / chapter).
  verse_range = "1"; verse_range_osis = "Matt.N.1" (OSIS chapter anchor,
  first-verse convention used throughout OCD for chapter-level entries).

Usage:
    py -3 build/parsers/ccel_robertson_word_pictures.py --dry-run
    py -3 build/parsers/ccel_robertson_word_pictures.py
    py -3 build/parsers/ccel_robertson_word_pictures.py --force-download
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Paths and bootstrap
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib._generated_enums import COMMENTARY__META__TRADITION  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "robertson-word-pictures"
OUTPUT_DIR = REPO_ROOT / "data" / "commentaries" / "robertson-word-pictures-vol1"
LOG_FILE = Path(__file__).with_suffix(".log")

RESOURCE_ID = "robertson-word-pictures-vol1"
SCHEMA_VERSION = "1.0.0"
SCRIPT_VERSION = "v1.0.0"

UA = (
    "OpenChristianData/1.0 (research; open-source data project; "
    "contact: openchristiandata@gmail.com)"
)
CRAWL_DELAY = 10  # seconds -- CCEL robots.txt crawl-delay

AUTHOR = "A.T. Robertson"
AUTHOR_DEATH_YEAR = 1934
ORIGINAL_PUBLICATION_YEAR = 1930
TRADITION = ["baptist"]

# ---------------------------------------------------------------------------
# Volume registry
# ---------------------------------------------------------------------------

VOLUMES = {
    "robertson_at/wp_matt": {
        "title": "Word Pictures in the New Testament, Vol. I -- Matthew",
        "book_osis": "Matt",
        "book_name": "Matthew",
        "book_number": 40,
    },
    "robertson_at/wp_mark": {
        "title": "Word Pictures in the New Testament, Vol. I -- Mark",
        "book_osis": "Mark",
        "book_name": "Mark",
        "book_number": 41,
    },
}


def _validate_enums() -> None:
    for t in TRADITION:
        assert t in COMMENTARY__META__TRADITION, (
            f"Invalid tradition {t!r}. Allowed: {sorted(COMMENTARY__META__TRADITION)}"
        )


_validate_enums()

ROBERTSON_OSIS_CORRECTIONS: dict[str, str | None] = {
    # CCEL ThML has a small number of impossible osisRef values. Correct only
    # where the visible citation or local context identifies the intended ref.
    "1Kgs.28.9": None,
    "1Sam.22.29": "1Sam.22.20",
    "Deut.18.26": None,
    "Gal.2.26": None,
    "Heb.20.28": "Matt.20.28",
    "John.2.29": "John.3.29",
    "John.24.11": "Luke.24.11",
    "John.31.42": "John.19.42",
    "Luke.19.39-Luke.19.55": "Luke.19.39-Luke.19.48",
    "Mark.8.311": "Mark.8.31",
    "Mark.11.38": "John.11.38",
    "Mark.18.34": "Luke.18.34",
    "Matt.10.43": None,
    "Matt.19.36": None,
    "Matt.22.69": "Matt.26.69",
    "Ps.4.9": "Ps.41.9",
    "Ps.22.36": "Ps.22.22",
    "Zech.17.4": "Zech.4.7",
}

# ---------------------------------------------------------------------------
# ThML entity preprocessing -- covers the full HTML entity set Robertson uses
# ---------------------------------------------------------------------------

THML_ENTITY_MAP = {
    "&mdash;": "—", "&ndash;": "–", "&lsquo;": "‘",
    "&rsquo;": "’", "&ldquo;": "“", "&rdquo;": "”",
    "&nbsp;": " ", "&hellip;": "…", "&emdash;": "—",
    "&copy;": "©", "&reg;": "®", "&trade;": "™",
    "&deg;": "°", "&para;": "¶", "&sect;": "§",
    "&dagger;": "†", "&Dagger;": "‡", "&bull;": "•",
    "&prime;": "′", "&Prime;": "″", "&oline;": "‾",
    "&frasl;": "⁄",
    "&aelig;": "æ", "&AElig;": "Æ",
    "&oslash;": "ø", "&Oslash;": "Ø",
    "&agrave;": "à", "&aacute;": "á", "&acirc;": "â",
    "&atilde;": "ã", "&auml;": "ä", "&aring;": "å",
    "&egrave;": "è", "&eacute;": "é", "&ecirc;": "ê",
    "&euml;": "ë", "&igrave;": "ì", "&iacute;": "í",
    "&icirc;": "î", "&iuml;": "ï", "&ograve;": "ò",
    "&oacute;": "ó", "&ocirc;": "ô", "&otilde;": "õ",
    "&ouml;": "ö", "&ugrave;": "ù", "&uacute;": "ú",
    "&ucirc;": "û", "&uuml;": "ü", "&yacute;": "ý",
    "&yuml;": "ÿ", "&Agrave;": "À", "&Aacute;": "Á",
    "&Acirc;": "Â", "&Atilde;": "Ã", "&Auml;": "Ä",
    "&Aring;": "Å", "&Egrave;": "È", "&Eacute;": "É",
    "&Ecirc;": "Ê", "&Euml;": "Ë", "&Igrave;": "Ì",
    "&Iacute;": "Í", "&Icirc;": "Î", "&Iuml;": "Ï",
    "&Ograve;": "Ò", "&Oacute;": "Ó", "&Ocirc;": "Ô",
    "&Otilde;": "Õ", "&Ouml;": "Ö", "&Ugrave;": "Ù",
    "&Uacute;": "Ú", "&Ucirc;": "Û", "&Uuml;": "Ü",
    "&Yacute;": "Ý", "&ntilde;": "ñ", "&Ntilde;": "Ñ",
    "&ccedil;": "ç", "&Ccedil;": "Ç",
    "&szlig;": "ß", "&thorn;": "þ", "&Thorn;": "Þ",
    "&eth;": "ð", "&ETH;": "Ð",
    "&acute;": "´", "&cedil;": "¸", "&uml;": "¨",
    "&macr;": "¯", "&sup1;": "¹", "&sup2;": "²",
    "&sup3;": "³", "&frac14;": "¼", "&frac12;": "½",
    "&frac34;": "¾", "&ordm;": "º", "&ordf;": "ª",
    "&laquo;": "«", "&raquo;": "»", "&not;": "¬",
    "&shy;": "­", "&plusmn;": "±", "&times;": "×",
    "&divide;": "÷", "&micro;": "µ", "&middot;": "·",
    "&pound;": "£", "&yen;": "¥", "&euro;": "€",
    "&cent;": "¢", "&curren;": "¤",
    "&alpha;": "α", "&beta;": "β", "&gamma;": "γ",
    "&delta;": "δ", "&epsilon;": "ε", "&zeta;": "ζ",
    "&eta;": "η", "&theta;": "θ", "&iota;": "ι",
    "&kappa;": "κ", "&lambda;": "λ", "&mu;": "μ",
    "&nu;": "ν", "&xi;": "ξ", "&omicron;": "ο",
    "&pi;": "π", "&rho;": "ρ", "&sigma;": "σ",
    "&tau;": "τ", "&upsilon;": "υ", "&phi;": "φ",
    "&chi;": "χ", "&psi;": "ψ", "&omega;": "ω",
    "&Alpha;": "Α", "&Beta;": "Β", "&Gamma;": "Γ",
    "&Delta;": "Δ", "&Epsilon;": "Ε", "&Zeta;": "Ζ",
    "&Eta;": "Η", "&Theta;": "Θ", "&Iota;": "Ι",
    "&Kappa;": "Κ", "&Lambda;": "Λ", "&Mu;": "Μ",
    "&Nu;": "Ν", "&Xi;": "Ξ", "&Omicron;": "Ο",
    "&Pi;": "Π", "&Rho;": "Ρ", "&Sigma;": "Σ",
    "&Tau;": "Τ", "&Upsilon;": "Υ", "&Phi;": "Φ",
    "&Chi;": "Χ", "&Psi;": "Ψ", "&Omega;": "Ω",
}


def preprocess_thml(raw_bytes: bytes) -> str:
    """Strip DOCTYPE declaration, replace HTML entities. Returns clean XML string."""
    text = raw_bytes.decode("utf-8", errors="replace")
    text = re.sub(r"<!DOCTYPE[^>]*>", "", text, flags=re.IGNORECASE | re.DOTALL)
    for entity, char in THML_ENTITY_MAP.items():
        text = text.replace(entity, char)
    # Remove remaining unresolved HTML entities -- but keep XML built-in entities
    # (&amp; &lt; &gt; &quot; &apos;) which ElementTree requires for correct parsing.
    text = re.sub(r"&(?!(?:amp|lt|gt|quot|apos);)[a-zA-Z][a-zA-Z0-9]*;", "", text)
    return text


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def get_all_text(elem) -> str:
    """
    Recursively collect text from elem.
    Skips: <note> footnotes, <pb> page breaks, <scripCom> chapter markers,
           <h2>-<h5> headings (chapter titles, not commentary).
    """
    parts = []
    _SKIP_TAGS = frozenset(("note", "pb", "scripCom", "h2", "h3", "h4", "h5"))
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
    """Collapse whitespace and strip."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_cross_refs(div: ET.Element) -> list[str]:
    """
    Extract OSIS cross-references from <scripRef osisRef=...> elements.
    Robertson's ThML uses osisRef="Bible:Book.ch.v" consistently.
    """
    refs: list[str] = []
    seen: set[str] = set()
    for sr in div.iter("scripRef"):
        osis_raw = sr.get("osisRef", "")
        for token in osis_raw.split():
            # Strip "Bible:" or "Bible.gr:" namespace prefix
            clean = re.sub(r"^Bible(?:\.[a-z]+)?:", "", token)
            clean = ROBERTSON_OSIS_CORRECTIONS.get(clean, clean)
            if not clean or clean.count(".") < 2:
                continue
            if clean not in seen:
                seen.add(clean)
                refs.append(clean)
    return refs


# ---------------------------------------------------------------------------
# Entry builder
# ---------------------------------------------------------------------------

def parse_div_scripcom(
    div: ET.Element, book_osis: str, book_name: str, book_number: int,
) -> dict | None:
    """
    Parse a <div1> containing a <scripCom> chapter marker.

    Returns a commentary schema entry or None if no <scripCom> is present
    (introduction or appendix divs naturally fall through here).
    """
    scripcom = div.find("scripCom")
    if scripcom is None:
        return None

    osis_raw = scripcom.get("osisRef", "")
    # "Bible:Matt.1" -> "Matt.1"
    osis_ref = re.sub(r"^Bible(?:\.[a-z]+)?:", "", osis_raw)
    parts = osis_ref.split(".")
    if len(parts) < 2:
        logging.warning("  Unexpected osisRef format: %r", osis_raw)
        return None

    try:
        chapter = int(parts[1])
    except (ValueError, IndexError):
        logging.warning("  Cannot parse chapter from osisRef: %r", osis_ref)
        return None

    commentary_text = clean_text(get_all_text(div))
    if not commentary_text:
        logging.debug("  Empty commentary text for %s chapter %d", book_osis, chapter)
        return None

    cross_refs = extract_cross_refs(div)
    verse_range_osis = f"{book_osis}.{chapter}.1"
    passage_slug = verse_range_osis.replace(".", "-")
    entry_id = f"{RESOURCE_ID}.{passage_slug}"

    return {
        "entry_id": entry_id,
        "book": book_name,
        "book_osis": book_osis,
        "book_number": book_number,
        "chapter": chapter,
        "verse_range": "1",
        "verse_range_osis": verse_range_osis,
        "verse_text": None,
        "commentary_text": commentary_text,
        "summary": None,
        "summary_review_status": "withheld",
        "cross_references": cross_refs,
        "word_count": len(commentary_text.split()),
    }


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_volume(ccel_author: str, ccel_work: str, force: bool = False) -> Path:
    """Download CCEL ThML XML, cache in raw dir. Returns local path."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    dest = RAW_DIR / f"{ccel_author}_{ccel_work}.xml"
    if dest.exists() and not force:
        logging.info("  Cached: %s (%d KB)", dest.name, dest.stat().st_size // 1024)
        return dest
    url = f"https://www.ccel.org/ccel/{ccel_author}/{ccel_work}.xml"
    logging.info("  Downloading %s ...", url)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    logging.info("  -> %s (%d KB) sha256:%s...", dest.name, len(data) // 1024, sha[:16])
    return dest


# ---------------------------------------------------------------------------
# Parse volume
# ---------------------------------------------------------------------------

def parse_volume(
    volume_key: str,
    dry_run: bool = False,
    force_download: bool = False,
) -> tuple[list[dict], str]:
    """
    Parse one Robertson volume. Downloads XML if not cached.
    Returns (entries, source_hash).
    """
    if volume_key not in VOLUMES:
        raise ValueError(f"Unknown volume: {volume_key!r}")

    vol = VOLUMES[volume_key]
    ccel_author, ccel_work = volume_key.split("/")
    book_osis = vol["book_osis"]
    book_name = vol["book_name"]
    book_number = vol["book_number"]

    logging.info("Parsing %s ...", vol["title"])

    xml_path = download_volume(ccel_author, ccel_work, force=force_download)
    raw_bytes = xml_path.read_bytes()
    xml_text = preprocess_thml(raw_bytes)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RuntimeError(f"XML parse failed for {volume_key}: {exc}") from exc

    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(f"No <ThML.body> found in {volume_key}")

    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    entries: list[dict] = []
    limit = 3 if dry_run else None

    for div1 in body:
        if limit and len(entries) >= limit:
            break
        if div1.tag != "div1":
            continue
        entry = parse_div_scripcom(div1, book_osis, book_name, book_number)
        if entry:
            entries.append(entry)

    logging.info("  Parsed %d entries for %s", len(entries), book_osis)
    return entries, source_hash


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def build_meta(
    vol: dict, volume_key: str, source_hash: str, processing_date: str
) -> dict:
    """Build OCD commentary meta envelope."""
    ccel_author, ccel_work = volume_key.split("/")
    return {
        "id": RESOURCE_ID,
        "title": "Word Pictures in the New Testament, Vol. I",
        "author": AUTHOR,
        "author_death_year": AUTHOR_DEATH_YEAR,
        "original_publication_year": ORIGINAL_PUBLICATION_YEAR,
        "language": "en",
        "tradition": TRADITION,
        "license": "public-domain",
        "schema_type": "commentary",
        "schema_version": SCHEMA_VERSION,
        "verse_text_source": "none",
        "verse_reference_standard": "OSIS",
        "completeness": "partial",
        "provenance": {
            "source_url": (
                f"https://www.ccel.org/ccel/{ccel_author}/{ccel_work}.xml"
            ),
            "source_format": "CCEL ThML XML",
            "source_edition": vol["title"],
            "download_date": processing_date,
            "source_hash": f"sha256:{source_hash}",
            "processing_method": "automated",
            "processing_script_version": (
                f"build/parsers/ccel_robertson_word_pictures.py@{SCRIPT_VERSION}"
            ),
            "processing_date": processing_date,
            "notes": (
                "A.T. Robertson (1863-1934). Word Pictures in the New Testament, "
                "Vol. I (Matthew and Mark), published 1930 by R.H. Revell. "
                "US public domain as of Jan 1, 2026. "
                "CCEL robots.txt: crawl-delay 10 (checked 2026-06-17). "
                "Entries are keyed at chapter granularity via <scripCom> markers."
            ),
        },
    }


def write_output(
    vol: dict,
    volume_key: str,
    entries: list[dict],
    source_hash: str,
    processing_date: str,
    dry_run: bool = False,
) -> Path | None:
    """Write OCD commentary JSON for one book. Returns output path or None (dry-run)."""
    if dry_run:
        book_osis = vol["book_osis"]
        logging.info(
            "  [dry-run] %d entries for %s", len(entries), book_osis,
        )
        if entries:
            logging.info("  Sample entry_id: %s", entries[0]["entry_id"])
            logging.info(
                "  Sample text (first 200 chars): %.200s",
                entries[0]["commentary_text"],
            )
        return None

    if not entries:
        logging.warning("  WARNING: 0 entries for %s, skipping write", vol["book_osis"])
        return None

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    book_slug = vol["book_osis"].lower()
    output_path = OUTPUT_DIR / f"{book_slug}.json"

    meta = build_meta(vol, volume_key, source_hash, processing_date)
    entries_sorted = sorted(entries, key=lambda e: e["chapter"])
    output = {"meta": meta, "data": entries_sorted}

    # Atomic write (OUT-02)
    tmp = output_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(output_path)

    logging.info("  Written %d entries -> %s", len(entries), output_path)
    return output_path


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------

def report_quality(entries: list[dict], volume_key: str) -> None:
    """Log quality stats for parsed entries."""
    total = len(entries)
    if total == 0:
        logging.warning("  WARNING: 0 entries for %s", volume_key)
        return
    with_refs = sum(1 for e in entries if e["cross_references"])
    wc = sorted(e["word_count"] for e in entries)
    logging.info(
        "  Quality: %d entries, %d with cross-refs (%.0f%%), "
        "word_count median=%d min=%d max=%d",
        total, with_refs, 100 * with_refs / total,
        wc[total // 2], wc[0], wc[-1],
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    fh = logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[fh, sh],
        format="%(levelname)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(
        description=(
            "Parse Robertson Word Pictures in the NT Vol. I from CCEL ThML XML "
            "into OCD commentary JSON"
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse first 3 entries per volume, do not write files",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download XML even if cached",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    volume_keys = list(VOLUMES.keys())

    total_entries = 0
    for i, vkey in enumerate(volume_keys):
        vol = VOLUMES[vkey]
        logging.info("")
        logging.info("=== Volume %d/%d: %s ===", i + 1, len(volume_keys), vkey)

        if i > 0 and not args.dry_run:
            logging.info("  Sleeping %ds (CCEL crawl-delay) ...", CRAWL_DELAY)
            time.sleep(CRAWL_DELAY)

        try:
            entries, source_hash = parse_volume(
                vkey, dry_run=args.dry_run, force_download=args.force_download,
            )
        except Exception as exc:
            logging.error("  FAILED: %s", exc)
            continue

        report_quality(entries, vkey)

        if args.dry_run:
            logging.info("  --- Dry-run sample ---")
            for e in entries[:2]:
                print(json.dumps(e, ensure_ascii=False, indent=2))
        else:
            write_output(vol, vkey, entries, source_hash, processing_date)

        total_entries += len(entries)

    logging.info("")
    logging.info("=== Summary ===")
    logging.info("  Volumes processed: %d", len(volume_keys))
    logging.info("  Total entries: %d", total_entries)


if __name__ == "__main__":
    main()
