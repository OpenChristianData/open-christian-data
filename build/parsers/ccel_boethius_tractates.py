"""ccel_boethius_tractates.py
Parser for Boethius: The Theological Tractates from CCEL ThML XML.

Five tractates in the H.F. Stewart and E.K. Rand (1918) translation.
Print source: London: W. Heinemann; New York: G.P. Putnam's Sons (Loeb Classical Library), 1918.
Source URL: https://www.ccel.org/ccel/boethius/tracts.xml

CCEL confirmed OK to parse (Quincy, 2026-04-01). robots.txt crawl-delay 10 for all agents.

XML structure (confirmed from live download):
  Root: <ThML> — no namespaces; DOCTYPE stripped before parsing.
  Header: <ThML.head> (metadata, skipped).
  Body: <ThML.body>
    div1 id="iv" title="The Theological Tractates"
      div2 id="iv.i"   — De Trinitate
      div2 id="iv.ii"  — Utrum Pater et Filius
      div2 id="iv.iii" — Quomodo Substantiae (De Hebdomadibus)
      div2 id="iv.iv"  — De Fide Catholica
      div2 id="iv.v"   — Contra Eutychen et Nestorium

  Each div2 contains flat <p> and <pb> children (no div3 sub-elements).
  Heading elements (h2, h3) and page breaks (pb) are skipped.
  Short centered p elements (< 9 words) are title/section-marker fragments and are skipped.
  Section numbers (I., II., etc.) appear as centered p elements with style="text-align:center".

Usage:
    py -3 build/parsers/ccel_boethius_tractates.py --download --dry-run
    py -3 build/parsers/ccel_boethius_tractates.py --parse
    py -3 build/parsers/ccel_boethius_tractates.py --download --parse
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.contributors import normalize_contributors  # noqa: E402
from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_FILE = REPO_ROOT / "raw" / "ccel" / "boethius" / "tracts.xml"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
SOURCES_DIR = REPO_ROOT / "sources" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_boethius_tractates.log"

SLUG = "boethius-theological-tractates"
SOURCE_URL = "https://www.ccel.org/ccel/boethius/tracts.xml"
DIV1_ID = "iv"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"

SOURCE_EDITION = (
    "Boethius: The Theological Tractates. H.F. Stewart and E.K. Rand (translators). "
    "London: W. Heinemann; New York: G.P. Putnam's Sons (Loeb Classical Library), 1918."
)

WORK_CFG = {
    "slug": SLUG,
    "title": "The Theological Tractates",
    "author": "Boethius",
    "author_id": "boethius",
    "author_birth_year": 480,
    "author_death_year": 524,
    "original_publication_year": None,
    "contributors": [
        "H.F. Stewart (translator, 1918)",
        "E.K. Rand (translator, 1918)",
    ],
    "language": "en",
    "original_language": "la",
    "tradition": ["patristic", "ecumenical"],
    "tradition_notes": (
        "Boethius (c. 480-524) was a late Roman philosopher and statesman whose "
        "Theological Tractates address speculative theology: the Trinity, divine "
        "predication, ontology of the good, Catholic faith, and Christology (against "
        "Eutyches and Nestorius). Translated by H.F. Stewart and E.K. Rand (1918) "
        "for the Loeb Classical Library."
    ),
    "era": "patristic",
    "audience": "scholarly",
    "work_kind": "theological-work",
    "completeness": "full",
}

# Roman numeral labels for the five tractates (keyed on div2 id)
TRACTATE_LABELS = {
    "iv.i": "I",
    "iv.ii": "II",
    "iv.iii": "III",
    "iv.iv": "IV",
    "iv.v": "V",
}

# ---------------------------------------------------------------------------
# Validate enums at import time
# ---------------------------------------------------------------------------

_TRADITIONS = get_enum("structured_text", "meta", "tradition")
_ERAS = get_enum("structured_text", "meta", "era")
_AUDIENCES = get_enum("structured_text", "meta", "audience")
_COMPLETENESS = get_enum("structured_text", "meta", "completeness")
_WORK_KINDS = get_enum("structured_text", "data", "work_kind")

for _t in WORK_CFG["tradition"]:
    assert _t in _TRADITIONS, f"Invalid tradition: {_t!r}"
assert WORK_CFG["era"] in _ERAS, f"Invalid era: {WORK_CFG['era']!r}"
assert WORK_CFG["audience"] in _AUDIENCES, f"Invalid audience: {WORK_CFG['audience']!r}"
assert WORK_CFG["completeness"] in _COMPLETENESS, f"Invalid completeness: {WORK_CFG['completeness']!r}"
assert WORK_CFG["work_kind"] in _WORK_KINDS, f"Invalid work_kind: {WORK_CFG['work_kind']!r}"

# ---------------------------------------------------------------------------
# ThML entity map
# ---------------------------------------------------------------------------

THML_ENTITY_MAP = {
    "&mdash;": "—",
    "&ndash;": "–",
    "&lsquo;": "‘",
    "&rsquo;": "’",
    "&ldquo;": "“",
    "&rdquo;": "”",
    "&nbsp;": " ",
    "&hellip;": "…",
    "&emdash;": "—",
    "&copy;": "©",
    "&reg;": "®",
    "&trade;": "™",
    "&deg;": "°",
    "&para;": "¶",
    "&sect;": "§",
    "&dagger;": "†",
    "&Dagger;": "‡",
    "&bull;": "•",
    "&prime;": "′",
    "&Prime;": "″",
    "&aelig;": "æ",
    "&AElig;": "Æ",
    "&agrave;": "à",
    "&aacute;": "á",
    "&egrave;": "è",
    "&eacute;": "é",
    "&iacute;": "í",
    "&oacute;": "ó",
    "&uacute;": "ú",
    "&ccedil;": "ç",
    "&ntilde;": "ñ",
    "&auml;": "ä",
    "&euml;": "ë",
    "&iuml;": "ï",
    "&ouml;": "ö",
    "&uuml;": "ü",
    "&oslash;": "ø",
    "&aring;": "å",
    "&szlig;": "ß",
    "&laquo;": "«",
    "&raquo;": "»",
    "&pound;": "£",
    "&euro;": "€",
    "&alpha;": "α",
    "&beta;": "β",
    "&gamma;": "γ",
    "&delta;": "δ",
    "&epsilon;": "ε",
    "&zeta;": "ζ",
    "&eta;": "η",
    "&theta;": "θ",
    "&iota;": "ι",
    "&kappa;": "κ",
    "&lambda;": "λ",
    "&mu;": "μ",
    "&nu;": "ν",
    "&xi;": "ξ",
    "&omicron;": "ο",
    "&pi;": "π",
    "&rho;": "ρ",
    "&sigma;": "σ",
    "&tau;": "τ",
    "&upsilon;": "υ",
    "&phi;": "φ",
    "&chi;": "χ",
    "&psi;": "ψ",
    "&omega;": "ω",
    "&Alpha;": "Α",
    "&Beta;": "Β",
    "&Gamma;": "Γ",
    "&Delta;": "Δ",
    "&Epsilon;": "Ε",
    "&Zeta;": "Ζ",
    "&Eta;": "Η",
    "&Theta;": "Θ",
    "&Iota;": "Ι",
    "&Kappa;": "Κ",
    "&Lambda;": "Λ",
    "&Mu;": "Μ",
    "&Nu;": "Ν",
    "&Xi;": "Ξ",
    "&Omicron;": "Ο",
    "&Pi;": "Π",
    "&Rho;": "Ρ",
    "&Sigma;": "Σ",
    "&Tau;": "Τ",
    "&Upsilon;": "Υ",
    "&Phi;": "Φ",
    "&Chi;": "Χ",
    "&Psi;": "Ψ",
    "&Omega;": "Ω",
}

_XML_SAFE = {"&amp;", "&lt;", "&gt;", "&quot;", "&apos;"}
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector",
                         "scripContext", "index", "h2", "h3", "h4"])
_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])

# ---------------------------------------------------------------------------
# ThML preprocessing
# ---------------------------------------------------------------------------


def _replace_entity(match: re.Match) -> str:
    ent = match.group(0)
    if ent in _XML_SAFE:
        return ent
    return THML_ENTITY_MAP.get(ent, "")


def preprocess_thml(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("utf-8")
        if "�" in text:
            raise UnicodeDecodeError("utf-8", raw_bytes, 0, 1, "replacement chars found")
    except UnicodeDecodeError:
        text = raw_bytes.decode("cp1252", errors="replace")
    text = re.sub(r"<!DOCTYPE\s[^[>]*(?:\[[^\]]*\])?>", "", text, flags=re.DOTALL)
    text = re.sub(r"&[A-Za-z][A-Za-z0-9]*;", _replace_entity, text)
    return text


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def get_all_text(elem: ET.Element) -> str:
    parts: list[str] = []
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


def is_centered(elem: ET.Element) -> bool:
    style = elem.get("style", "")
    return "text-align:center" in style or "text-align: center" in style


def get_scriptrefs(elem: ET.Element) -> list[dict]:
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


def count_words(blocks: list[str]) -> int:
    return sum(len(re.findall(r"\w+", b)) for b in blocks)


# ---------------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------------


def parse_tractate(div2: ET.Element) -> dict:
    """Parse a single div2 tractate element into a section dict."""
    div_id = div2.get("id", "")
    title = clean_text(div2.get("title", ""))
    label = TRACTATE_LABELS.get(div_id)

    content_blocks: list[str] = []
    scripture_refs: list[dict] = []

    for child in div2:
        if child.tag in _SKIP_TAGS:
            continue
        if child.tag in _HEADING_TAGS:
            continue
        if child.tag != "p":
            continue
        text = clean_text(get_all_text(child))
        if not text:
            continue
        word_count = len(re.findall(r"\w+", text))
        # Skip title-page fragments and section markers: centered p elements < 9 words
        if is_centered(child) and word_count < 9:
            continue
        content_blocks.append(text)
        scripture_refs.extend(get_scriptrefs(child))

    return {
        "section_type": "part",
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "scripture_references": scripture_refs,
        "word_count": count_words(content_blocks),
        "children": [],
    }


def parse_tractates(raw_bytes: bytes) -> dict:
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    root = ET.fromstring(preprocess_thml(raw_bytes))

    body = None
    for child in root:
        if child.tag == "ThML.body":
            body = child
            break
    if body is None:
        raise RuntimeError("No <ThML.body> found in Boethius ThML")

    div1 = None
    for child in body:
        if child.tag == "div1" and child.get("id") == DIV1_ID:
            div1 = child
            break
    if div1 is None:
        raise RuntimeError(f"No div1 id={DIV1_ID!r} found in ThML.body")

    sections = []
    for child in div1:
        if child.tag == "div2" and child.get("id") in TRACTATE_LABELS:
            sections.append(parse_tractate(child))

    if len(sections) != 5:
        found_ids = [c.get("id") for c in div1 if c.tag == "div2"]
        raise RuntimeError(
            f"Expected 5 tractate div2 elements, found {len(sections)}. "
            f"div2 ids in document: {found_ids}"
        )

    return {"sections": sections, "source_hash": source_hash}


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------


def _download_date() -> str:
    return datetime.fromtimestamp(RAW_FILE.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def build_output(parse_result: dict) -> dict:
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_hash = parse_result["source_hash"]
    sections = parse_result["sections"]

    meta = {
        "id": WORK_CFG["slug"],
        "title": WORK_CFG["title"],
        "author": WORK_CFG["author"],
        "author_id": WORK_CFG["author_id"],
        "author_birth_year": WORK_CFG["author_birth_year"],
        "author_death_year": WORK_CFG["author_death_year"],
        "contributors": normalize_contributors(WORK_CFG["contributors"]),
        "original_publication_year": WORK_CFG["original_publication_year"],
        "language": WORK_CFG["language"],
        "original_language": WORK_CFG["original_language"],
        "tradition": WORK_CFG["tradition"],
        "tradition_notes": WORK_CFG["tradition_notes"],
        "era": WORK_CFG["era"],
        "audience": WORK_CFG["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": WORK_CFG["completeness"],
        "provenance": {
            "source_url": SOURCE_URL,
            "source_format": "ThML XML",
            "source_edition": SOURCE_EDITION,
            "download_date": _download_date(),
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/ccel_boethius_tractates.py@{SCRIPT_VERSION}",
            "processing_date": processing_date,
            "notes": (
                "ThML HTML entities replaced with Unicode equivalents. DOCTYPE stripped. "
                "Page breaks (pb), footnotes (note), and heading elements (h2/h3/h4) excluded. "
                "Short centered p elements (< 9 words) filtered as title-page fragments or "
                "section markers (I., II., etc.). robots.txt crawl-delay 10s honoured."
            ),
            "source_type": "ccel_thml",
            "source_file": "raw/ccel/boethius/tracts.xml",
            "translator": "H.F. Stewart and E.K. Rand, 1918",
        },
    }

    data = {
        "work_id": WORK_CFG["slug"],
        "work_kind": WORK_CFG["work_kind"],
        "sections": sections,
    }

    return {"meta": meta, "data": data}


def write_source_config(source_hash: str) -> None:
    cfg_dir = SOURCES_DIR / SLUG
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        "resource_id": WORK_CFG["slug"],
        "title": WORK_CFG["title"],
        "author": WORK_CFG["author"],
        "author_id": WORK_CFG["author_id"],
        "author_birth_year": WORK_CFG["author_birth_year"],
        "author_death_year": WORK_CFG["author_death_year"],
        "contributors": WORK_CFG["contributors"],
        "original_publication_year": WORK_CFG["original_publication_year"],
        "language": WORK_CFG["language"],
        "original_language": WORK_CFG["original_language"],
        "tradition": WORK_CFG["tradition"],
        "tradition_notes": WORK_CFG["tradition_notes"],
        "era": WORK_CFG["era"],
        "audience": WORK_CFG["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "work_kind": WORK_CFG["work_kind"],
        "source_url": SOURCE_URL,
        "source_format": "ThML XML",
        "source_edition": SOURCE_EDITION,
        "source_hash": source_hash,
        "download_date": _download_date(),
        "output_file": f"data/structured-text/{SLUG}.json",
        "notes": (
            "CCEL confirmed OK to parse. Crawl-delay 10s per robots.txt. "
            "Extracted from div1 id='iv' (all five div2 tractates)."
        ),
    }
    with (cfg_dir / "config.json").open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download(force: bool = False) -> None:
    if RAW_FILE.exists() and not force:
        size_kb = RAW_FILE.stat().st_size // 1024
        print(f"  Cached: {RAW_FILE.name} ({size_kb} KB)")
        return
    RAW_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {SOURCE_URL} ...")
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    RAW_FILE.write_bytes(data)
    print(f"  Downloaded {len(data)} bytes -> {RAW_FILE.name}")


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------


def report_quality(parse_result: dict) -> None:
    sections = parse_result["sections"]
    total_words = sum(s["word_count"] for s in sections)
    print(f"  Parsed {len(sections)} tractates, {total_words} total words")
    for s in sections:
        label = s.get("label", "?")
        title = (s.get("title") or "")[:55]
        blocks = len(s["content_blocks"])
        wc = s["word_count"]
        print(f"    [{label}] {title!r}: {blocks} blocks, {wc} words")
    # Quality checks
    problems = []
    for s in sections:
        if not s["content_blocks"]:
            problems.append(f"empty tractate: {s.get('label')} {s.get('title')}")
        if s["word_count"] < 50:
            problems.append(f"suspiciously short tractate: {s.get('label')} ({s['word_count']} words)")
    if problems:
        raise RuntimeError("Quality check failed: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse Boethius Theological Tractates from CCEL ThML XML"
    )
    parser.add_argument("--download", action="store_true", help="Download XML from CCEL")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    parser.add_argument("--parse", action="store_true", help="Parse and write output")
    parser.add_argument("--dry-run", action="store_true", help="Parse but do not write")
    args = parser.parse_args()
    if args.dry_run:
        args.parse = True

    if not args.download and not args.parse:
        parser.print_help()
        return

    log_lines: list[str] = []

    def log(msg: str) -> None:
        safe = msg.encode("ascii", errors="replace").decode("ascii")
        print(safe)
        log_lines.append(msg)

    errors = 0
    files_written = 0
    start = time.time()
    try:
        if args.download:
            log("=== Download phase ===")
            download(force=args.force)
            log("")

        if args.parse:
            if not RAW_FILE.exists():
                raise RuntimeError(f"Missing raw file: {RAW_FILE}. Run --download first.")
            log("=== Parse phase ===")
            raw_bytes = RAW_FILE.read_bytes()
            log(f"  Parsing {RAW_FILE.name} ({len(raw_bytes) // 1024} KB) ...")
            result = parse_tractates(raw_bytes)
            report_quality(result)

            total_words = sum(s["word_count"] for s in result["sections"])
            if len(result["sections"]) == 0:
                raise RuntimeError("Zero sections parsed -- aborting before any write.")
            if total_words == 0:
                raise RuntimeError("Zero words parsed -- aborting before any write.")

            if args.dry_run:
                log("  DRY RUN: skipping output write")
            else:
                output = build_output(result)
                out_path = OUTPUT_DIR / f"{SLUG}.json"
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                tmp_path = out_path.with_suffix(".json.tmp")
                with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
                    json.dump(output, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                tmp_path.replace(out_path)
                write_source_config(result["source_hash"])
                files_written += 1
                log(f"  Wrote {out_path}")
    except Exception as exc:
        errors += 1
        log(f"ERROR: {exc}")
    finally:
        summary = (
            f"Done in {time.time() - start:.1f}s. "
            f"Files written: {files_written}. Errors: {errors}."
        )
        log(summary)
        with LOG_FILE.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(log_lines) + "\n")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
