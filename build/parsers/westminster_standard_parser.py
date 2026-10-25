"""build/parsers/westminster_standard_parser.py

Enriches Westminster Standards data files with proof texts scraped from
thewestminsterstandard.org.

Task 5: WSC proof text enrichment (--enrich-wsc).
Task 6: Parse 5 new Westminster Standards documents (--document / --all-documents).

Usage:
    py -3 build/parsers/westminster_standard_parser.py --enrich-wsc
    py -3 build/parsers/westminster_standard_parser.py --document directory-for-family-worship
    py -3 build/parsers/westminster_standard_parser.py --all-documents
    py -3 build/parsers/westminster_standard_parser.py --document directory-for-family-worship --dry-run
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib._generated_enums import (  # noqa: E402
    DOCTRINAL_DOCUMENT__DATA__DOCUMENT_KIND,
    DOCTRINAL_DOCUMENT__META__COMPLETENESS,
    DOCTRINAL_DOCUMENT__META__TRADITION,
)
from build.lib.text_utils import compute_source_hash  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402
from build.lib import writer_manifest  # noqa: E402
from build.parsers.westminster_witnesses import parse_wsc_witness_document  # noqa: E402

WSC_HTML = REPO_ROOT / "raw" / "westminster-standard-org" / "westminster-shorter-catechism.html"
WSC_JSON = REPO_ROOT / "data" / "catechisms" / "westminster-shorter-catechism.json"
WSC_CONFIG = REPO_ROOT / "sources" / "catechisms" / "westminster-shorter-catechism" / "config.json"

LOG_FILE = Path(__file__).resolve().parent / "westminster_standard_parser.log"

RAW_DIR = REPO_ROOT / "raw" / "westminster-standard-org"
DOCS_OUT_DIR = REPO_ROOT / "data" / "doctrinal-documents"
SOURCES_OUT_DIR = REPO_ROOT / "sources" / "doctrinal-documents"
MANIFEST_PATH = REPO_ROOT / "data" / "doctrinal-documents" / "_manifest.json"

SCRIPT_VERSION = "build/parsers/westminster_standard_parser.py@v2.0.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure file + console logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ---------------------------------------------------------------------------
# Continuation-reference handling
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# JSON enrichment
# ---------------------------------------------------------------------------

def enrich_wsc(dry_run: bool = False) -> None:
    """Read the WSC JSON, populate proofs from the HTML, and write it back."""
    start_time = datetime.now(timezone.utc)
    log.info("=== WSC enrichment started at %s ===", start_time.isoformat())

    # Step 1: Parse proofs from HTML
    witness_document = parse_wsc_witness_document(WSC_HTML)
    proofs_by_index = witness_document.proofs_by_index
    parse_errors = witness_document.parse_errors

    # Step 2: Read existing JSON
    log.info("Reading: %s", WSC_JSON)
    with open(WSC_JSON, encoding="utf-8") as f:
        data = json.load(f)

    entries = data["data"]
    log.info("Loaded %d JSON entries", len(entries))

    # Step 3: Match by sort_key and populate proofs
    # The i-th Q&A block in the HTML corresponds to sort_key i (1-indexed)
    matched = 0
    skipped_no_proofs = 0
    skipped_not_in_html = 0

    for entry in entries:
        sort_key = entry["sort_key"]
        if sort_key not in proofs_by_index:
            log.warning("sort_key %d not found in HTML extraction", sort_key)
            skipped_not_in_html += 1
            continue

        refs = proofs_by_index[sort_key]
        if refs:
            entry["proofs"] = [
                {
                    "id": 1,
                    "references": refs,
                }
            ]
            matched += 1
        else:
            # Keep proofs as empty list; log it
            entry["proofs"] = []
            skipped_no_proofs += 1
            log.warning("sort_key %d has no proof references", sort_key)

    # Step 4: Update provenance notes
    data["meta"]["provenance"]["notes"] = (
        "Dual-source provenance: Q&A text from Creeds.json (NonlinearFruit/Creeds.json, "
        "download date 2026-03-27). Scripture proof texts added 2026-03-28 from "
        "thewestminsterstandard.org (https://thewestminsterstandard.org/westminster-shorter-catechism/), "
        "parsed by build/parsers/westminster_standard_parser.py."
    )

    # Step 5: Print quality stats (ASCII only -- Windows cp1252 console)
    total_questions = len(entries)
    questions_with_proofs = matched
    questions_without = skipped_no_proofs
    accounted = matched + skipped_no_proofs + skipped_not_in_html
    if accounted != total_questions:
        log.error(
            "Stats mismatch: matched=%d + no_proofs=%d + not_in_html=%d = %d != total=%d",
            matched, skipped_no_proofs, skipped_not_in_html, accounted, total_questions,
        )
    total_refs = sum(
        len(r["references"])
        for e in entries
        for r in e.get("proofs", [])
    )
    total_parse_errors = sum(len(v) for v in parse_errors.values())

    print("")
    print("=== WSC Enrichment Quality Stats ===")
    print(f"Total questions:         {total_questions}")
    print(f"Questions with proofs:   {questions_with_proofs}")
    print(f"Questions without proofs:{questions_without}")
    if skipped_not_in_html:
        print(f"Not in HTML (skipped):   {skipped_not_in_html}  <-- check HTML source")
    print(f"Total references:        {total_refs}")
    print(f"Parse errors (refs):     {total_parse_errors}")
    if parse_errors:
        for qnum, errs in parse_errors.items():
            print(f"  Q{qnum} errors: {errs}")
    print("")

    if dry_run:
        log.info("DRY RUN -- no files written")
        print("DRY RUN: no files written.")
        return

    # Step 6: Write updated JSON
    log.info("Writing: %s", WSC_JSON)
    with open(WSC_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("JSON written successfully")

    end_time = datetime.now(timezone.utc)
    elapsed = (end_time - start_time).total_seconds()
    log.info("=== WSC enrichment complete in %.1fs ===", elapsed)
    print(f"Done. Elapsed: {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Document parsing — Task 6
# ---------------------------------------------------------------------------

DOCUMENT_CONFIGS: dict[str, dict] = {
    "directory-for-family-worship": {
        "title": "The Directory for Family Worship",
        "document_kind": "directory",
        "completeness": "full",
        "original_publication_year": 1647,
        "tradition_notes": (
            "Produced by the Westminster Assembly (1647). Part of the Westminster Standards; "
            "adopted by the Church of Scotland. Guides family piety and worship practice."
        ),
    },
    "solemn-league-and-covenant": {
        "title": "The Solemn League and Covenant",
        "document_kind": "covenant",
        "completeness": "partial",
        "original_publication_year": 1643,
        "tradition_notes": (
            "Adopted by the General Assembly of the Church of Scotland (1643) and the English "
            "Parliament. A political and religious covenant binding Scotland and England to "
            "Presbyterian reformation. Part of the Westminster Standards context. "
            "Completeness: partial -- prefatory matter (Assembly Approbation, Parliamentary Act) "
            "is included as introductory sections; inline proof texts deferred to Phase 2."
        ),
    },
    "directory-for-publick-worship": {
        "title": "The Directory for the Publick Worship of God",
        "document_kind": "directory",
        "completeness": "full",
        "original_publication_year": 1645,
        "tradition_notes": (
            "Produced by the Westminster Assembly (1645) as a replacement for the Book of "
            "Common Prayer. Adopted by the Church of Scotland and used by English "
            "Presbyterians and Nonconformists. Part of the Westminster Standards."
        ),
    },
    "form-of-church-government": {
        "title": "The Form of Presbyterial Church-Government",
        "document_kind": "declaration",
        "completeness": "partial",
        "original_publication_year": 1645,
        "tradition_notes": (
            "Produced by the Westminster Assembly (1645). Defines Presbyterian polity including "
            "officers, assemblies, and ordination. Part of the Westminster Standards. "
            "Completeness: partial -- inline proof texts deferred to Phase 2."
        ),
    },
    "sum-of-saving-knowledge": {
        "title": "The Sum of Saving Knowledge",
        "document_kind": "declaration",
        "completeness": "partial",
        "original_publication_year": 1650,
        "tradition_notes": (
            "Attributed to David Dickson and James Durham (c. 1650). Appended to the Westminster "
            "Standards by the Church of Scotland. An evangelistic summary of Reformed soteriology "
            "arranged around four Heads. Completeness: partial -- inline proof texts deferred to Phase 2."
        ),
    },
}


def _validate_configs() -> None:
    for slug, cfg in DOCUMENT_CONFIGS.items():
        assert (document_kind := cfg["document_kind"]) in DOCTRINAL_DOCUMENT__DATA__DOCUMENT_KIND, (
            f"{slug}: invalid document_kind value {document_kind!r}"
        )
        for tradition in ("reformed", "presbyterian"):
            assert tradition in DOCTRINAL_DOCUMENT__META__TRADITION, (
                f"{slug}: invalid tradition value {tradition!r}"
            )
        assert (completeness := cfg["completeness"]) in DOCTRINAL_DOCUMENT__META__COMPLETENESS, (
            f"{slug}: invalid completeness value {completeness!r}"
        )


_validate_configs()




def _html_sections_to_text(h1_elem) -> str:
    """Collect all sibling paragraph text after an h1 until the next h1."""
    parts = []
    sib = h1_elem.find_next_sibling()
    while sib and sib.name != "h1":
        text = sib.get_text(separator="\n", strip=True)
        if text:
            parts.append(text)
        sib = sib.find_next_sibling()
    return "\n\n".join(parts)


def _html_sections_between(start_elem, stop_tags: list[str]) -> str:
    """Collect sibling paragraph text after start_elem until a stop tag is found."""
    parts = []
    sib = start_elem.find_next_sibling()
    while sib and sib.name not in stop_tags:
        text = sib.get_text(separator="\n", strip=True)
        if text:
            parts.append(text)
        sib = sib.find_next_sibling()
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Per-document parsers
# ---------------------------------------------------------------------------

def _parse_directory_for_family_worship(soup: BeautifulSoup) -> list[dict]:
    """Parse Directory for Family Worship.

    Structure: h1 elements with Roman numeral titles (I. through XIV.)
    The first h1 is the document title; the second is the preamble text (no title needed).
    """
    units = []
    h1s = soup.find_all("h1")

    # Skip document title h1 (index 0) and h2 (assembly header)
    # Sections are the Roman numeral h1s
    section_num = 0
    for h1 in h1s:
        text = h1.get_text(strip=True)
        # Skip document title
        if not re.match(r"^[IVXLC]+\.$", text):
            continue
        section_num += 1
        content = _html_sections_to_text(h1)
        units.append({
            "unit_type": "section",
            "number": str(section_num),
            "title": text,
            "content": content,
        })

    return units


def _parse_solemn_league_and_covenant(soup: BeautifulSoup) -> list[dict]:
    """Parse Solemn League and Covenant.

    Structure:
    - h1 'THE SOLEMN LEAGUE AND COVENANT' -- intro/preamble
    - h1 'I.' through 'VI.' -- articles
    """
    units = []
    h1s = soup.find_all("h1")

    # Find preamble: 'THE SOLEMN LEAGUE AND COVENANT' (second h1 with that title)
    preamble_added = False
    article_num = 0

    for h1 in h1s:
        text = h1.get_text(strip=True)
        if text == "THE SOLEMN LEAGUE AND COVENANT" and not preamble_added:
            content = _html_sections_to_text(h1)
            if content.strip():
                units.append({
                    "unit_type": "section",
                    "number": "preamble",
                    "title": "Preamble",
                    "content": content,
                })
            preamble_added = True
        elif re.match(r"^[IVXLC]+\.$", text):
            article_num += 1
            content = _html_sections_to_text(h1)
            units.append({
                "unit_type": "article",
                "number": str(article_num),
                "title": text,
                "content": content,
            })

    return units


def _parse_directory_for_publick_worship(soup: BeautifulSoup) -> list[dict]:
    """Parse Directory for Publick Worship.

    Structure: h1 elements for each major section. Skip title h1 and Contents h1.
    """
    units = []
    h1s = soup.find_all("h1")

    skip_titles = {
        "Directory for the Publick Worship of God",
        "Contents",
    }

    section_num = 0
    for h1 in h1s:
        text = h1.get_text(strip=True)
        if text in skip_titles or not text:
            continue
        section_num += 1
        content = _html_sections_to_text(h1)
        units.append({
            "unit_type": "section",
            "number": str(section_num),
            "title": text,
            "content": content,
        })

    return units


def _parse_form_of_church_government(soup: BeautifulSoup) -> list[dict]:
    """Parse Form of Church Government.

    Structure: h1 elements for each major section. Skip title and Contents h1s.
    """
    units = []
    h1s = soup.find_all("h1")

    skip_titles = {
        "Form of Presbyterial Church-Government",
        "Contents:",
        "",
    }

    section_num = 0
    for h1 in h1s:
        text = h1.get_text(strip=True)
        if text in skip_titles:
            continue
        section_num += 1
        content = _html_sections_to_text(h1)
        units.append({
            "unit_type": "section",
            "number": str(section_num),
            "title": text,
            "content": content,
        })

    return units


def _parse_sum_of_saving_knowledge(soup: BeautifulSoup) -> list[dict]:
    """Parse Sum of Saving Knowledge.

    Structure:
    - h2 'Preface'
    - h2 'The Sum of Saving Knowledge is this:' (intro paragraph)
    - h3 'Head I.' - 'Head IV.'
    - h2 'The Practical Use of Saving Knowledge' (large section)
    - h2 'Warrants to Believe' (parent)
      - h3 'Section 1' - 'Section 4'
    - h2 'The Evidences of True Faith' (parent)
      - h3 'Section 1' - 'Section 4'
    """
    units = []
    body = soup.find("div", class_="entry-content") or soup.find("main") or soup.body
    elems = body.find_all(["h2", "h3"])

    skip_h2 = {"Contents:"}
    section_num = 0

    i = 0
    while i < len(elems):
        elem = elems[i]
        text = elem.get_text(strip=True)

        if not text or text in skip_h2:
            i += 1
            continue

        if elem.name == "h2":
            # Check if this h2 is a parent with h3 children
            # Look ahead to see if next non-empty elem is an h3
            next_i = i + 1
            while next_i < len(elems) and not elems[next_i].get_text(strip=True):
                next_i += 1

            has_h3_children = (
                next_i < len(elems) and elems[next_i].name == "h3"
                and text in {"Warrants to Believe", "The Evidences of True Faith"}
            )

            if has_h3_children:
                # Collect h3 children
                children = []
                child_num = 0
                i += 1
                while i < len(elems) and elems[i].name == "h3":
                    h3 = elems[i]
                    h3_text = h3.get_text(strip=True)
                    child_num += 1
                    child_content = _html_sections_between(h3, ["h2", "h3"])
                    children.append({
                        "unit_type": "section",
                        "number": str(child_num),
                        "title": h3_text,
                        "content": child_content,
                    })
                    i += 1
                section_num += 1
                units.append({
                    "unit_type": "section",
                    "number": str(section_num),
                    "title": text,
                    "children": children,
                })
                continue
            else:
                # Regular h2 section
                section_num += 1
                content = _html_sections_between(elem, ["h2", "h3"])
                units.append({
                    "unit_type": "section",
                    "number": str(section_num),
                    "title": text,
                    "content": content,
                })

        elif elem.name == "h3":
            # Standalone h3 (Head I - Head IV under 'The Sum of Saving Knowledge is this:')
            section_num += 1
            content = _html_sections_between(elem, ["h2", "h3"])
            units.append({
                "unit_type": "section",
                "number": str(section_num),
                "title": text,
                "content": content,
            })

        i += 1

    return units


# ---------------------------------------------------------------------------
# Document builder
# ---------------------------------------------------------------------------

PARSER_FN_MAP = {
    "directory-for-family-worship": _parse_directory_for_family_worship,
    "solemn-league-and-covenant": _parse_solemn_league_and_covenant,
    "directory-for-publick-worship": _parse_directory_for_publick_worship,
    "form-of-church-government": _parse_form_of_church_government,
    "sum-of-saving-knowledge": _parse_sum_of_saving_knowledge,
}

# Guard: PARSER_FN_MAP and DOCUMENT_CONFIGS must stay in sync; a mismatch means
# a slug has config but no parser (KeyError at runtime) or a parser with no config.
# Use raise instead of assert so this fires even under python -O.
_map_only = PARSER_FN_MAP.keys() - DOCUMENT_CONFIGS.keys()
_cfg_only = DOCUMENT_CONFIGS.keys() - PARSER_FN_MAP.keys()
if _map_only or _cfg_only:
    raise SystemExit(
        f"PARSER_FN_MAP and DOCUMENT_CONFIGS are out of sync. "
        f"In PARSER_FN_MAP only: {_map_only}. "
        f"In DOCUMENT_CONFIGS only: {_cfg_only}."
    )
del _map_only, _cfg_only


def _build_doctrinal_document(slug: str, units: list[dict]) -> dict:
    """Assemble the full doctrinal document JSON structure for a slug."""
    processing_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    config = DOCUMENT_CONFIGS[slug]
    source = _load_document_source(slug)
    download_date = source["download_date"]

    return {
        "meta": {
            "id": slug,
            "title": config["title"],
            "author": "Westminster Assembly",
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": [],
            "original_publication_year": config["original_publication_year"],
            "language": "en",
            "tradition": ["reformed", "presbyterian"],
            "tradition_notes": config["tradition_notes"],
            "license": "cc0-1.0",
            "schema_type": "doctrinal_document",
            "schema_version": "2.1.0",
            "completeness": config["completeness"],
            "provenance": {
                "source_url": source["url"],
                "source_format": "html",
                "source_edition": f"thewestminsterstandard.org (web edition, {download_date})",
                "download_date": download_date,
                "source_hash": source["source_hash"],
                "processing_method": "automated",
                "processing_script_version": SCRIPT_VERSION,
                "processing_date": processing_date,
                "notes": (
                    f"Text parsed from thewestminsterstandard.org HTML cache. "
                    f"Completeness: {config['completeness']}."
                ),
            },
        },
        "data": {
            "document_id": slug,
            "document_kind": config["document_kind"],
            "revision_history": [],
            "units": units,
        },
    }


def _load_document_source(slug: str) -> dict:
    """Load a document's source config and prove its pin matches the HTML cache."""
    config_path = SOURCES_OUT_DIR / slug / "config.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValueError(f"{slug}: source config is missing a source object")

    required = ("url", "download_date", "source_hash")
    missing = [key for key in required if not source.get(key)]
    if missing:
        raise ValueError(f"{slug}: source config is missing {', '.join(missing)}")

    html_path = RAW_DIR / f"{slug}.html"
    actual_hash = compute_source_hash(html_path)
    if actual_hash != source["source_hash"]:
        raise ValueError(
            f"{slug}: cached HTML hash {actual_hash} does not match "
            f"config pin {source['source_hash']}"
        )
    return source


def _count_words_in_units(units: list[dict]) -> int:
    """Count total words in all units recursively."""
    total = 0
    for unit in units:
        content = unit.get("content", "")
        if content:
            total += len(content.split())
        children = unit.get("children", [])
        if children:
            total += _count_words_in_units(children)
    return total


def _find_empty_sections(units: list[dict], _prefix: str = "") -> list[str]:
    """Recursively collect qualified section numbers with no content and no children.

    Returns dotted paths (e.g. "3.1") so child section numbers are unambiguous
    in quality stats output.
    """
    empty = []
    for unit in units:
        num = unit.get("number", "?")
        qualified = num if not _prefix else f"{_prefix}.{num}"
        children = unit.get("children", [])
        if children:
            empty.extend(_find_empty_sections(children, qualified))
        elif not unit.get("content", "").strip():
            empty.append(qualified)
    return empty


# Words that should never open a section's content — indicate nav/footer bleed
# or a title being captured as body text.
_WRONG_BLOCK_OPENERS = frozenset([
    "home", "about", "contact", "copyright", "search",
    "menu", "navigation", "contents", "table", "skip", "back",
    "next", "previous", "share", "print", "download", "subscribe",
])


def _check_content_plausibility(units: list[dict], slug: str) -> list[str]:
    """Scan first word of every unit's content against a blocklist of nav/footer openers.

    Returns a list of warning strings (empty if all clear).
    """
    warnings: list[str] = []

    def _check(unit_list: list[dict], prefix: str) -> None:
        for unit in unit_list:
            num = unit.get("number", "?")
            label = f"{prefix}{num}" if prefix else num
            content = unit.get("content", "").strip()
            if content:
                first_word = content.split()[0].lower().rstrip(".,;:")
                if first_word in _WRONG_BLOCK_OPENERS:
                    warnings.append(
                        f"  Section {label}: content opens with suspicious word {first_word!r}"
                    )
            for child in unit.get("children", []):
                _check([child], f"{label}.")

    _check(units, "")
    return warnings


def _document_delta_payload(document: dict | None) -> dict | None:
    """Adapt a doctrinal document to the shared manifest delta contract.

    ``writer_manifest.diff_counts`` compares a list of entries. A doctrinal
    document stores its entries under ``data.units`` and also has meaningful
    metadata and data-level fields, so represent those real objects as entries
    without adding synthetic fields that would inflate ``fields_changed``.
    Nested children remain part of their parent unit's direct ``children``
    field, which matches ``diff_counts``' direct-field semantics.
    """
    if document is None:
        return None

    meta = document["meta"]
    data = document["data"]
    entries = [meta, {key: value for key, value in data.items() if key != "units"}]
    entries.extend(data.get("units", []))
    return {"meta": {}, "data": entries}


def _document_delta_key(entry: dict) -> str:
    """Return a stable key for one flattened doctrinal-document entry."""
    if "document_id" in entry:
        return f"data:{entry['document_id']}"
    if "unit_type" in entry and "number" in entry:
        return f"unit:{entry['unit_type']}:{entry['number']}"
    return f"meta:{entry['id']}"


def _document_delta_counts(before: dict | None, after: dict) -> tuple[int, int]:
    """Measure changed document entries and direct fields for a parser run."""
    return writer_manifest.diff_counts(
        _document_delta_payload(before),
        _document_delta_payload(after) or {},
        key=_document_delta_key,
    )


def _unit_sibling_key(unit: dict) -> tuple[str, str]:
    """Return the parser's stable key for a unit within one sibling scope."""
    missing = [field for field in ("unit_type", "number") if field not in unit]
    if missing:
        raise ValueError(
            "cannot preserve token_count without a complete sibling key; "
            f"missing {', '.join(missing)}"
        )
    return str(unit["unit_type"]), str(unit["number"])


def _index_unit_siblings(
    units: list[dict], *, tree_name: str, scope: tuple[tuple[str, str], ...]
) -> dict[tuple[str, str], dict]:
    """Index one sibling list, rejecting keys that would make matching ambiguous."""
    indexed: dict[tuple[str, str], dict] = {}
    for unit in units:
        key = _unit_sibling_key(unit)
        if key in indexed:
            scope_label = "root" if not scope else " / ".join(
                f"{unit_type}:{number}" for unit_type, number in scope
            )
            raise ValueError(
                f"duplicate sibling key {key!r} in {tree_name} document at {scope_label}"
            )
        indexed[key] = unit
    return indexed


def _validate_unit_sibling_keys(
    units: list[dict], *, tree_name: str, scope: tuple[tuple[str, str], ...] = ()
) -> None:
    """Prove every sibling scope in a unit tree has deterministic keys."""
    indexed = _index_unit_siblings(units, tree_name=tree_name, scope=scope)
    for key, unit in indexed.items():
        _validate_unit_sibling_keys(
            unit.get("children", []),
            tree_name=tree_name,
            scope=(*scope, key),
        )


def _tokenized_source_text(unit: dict) -> str:
    """Select source text using add_token_counts.py's doctrinal-unit semantics."""
    return unit.get("content") or unit.get("content_with_proofs") or ""


def _copy_unchanged_token_counts(
    previous_units: list[dict],
    current_units: list[dict],
    *,
    scope: tuple[tuple[str, str], ...] = (),
) -> None:
    """Copy verified token counts recursively between already-validated trees."""
    previous_by_key = _index_unit_siblings(
        previous_units, tree_name="previous", scope=scope
    )
    current_by_key = _index_unit_siblings(
        current_units, tree_name="current", scope=scope
    )

    for key, current_unit in current_by_key.items():
        previous_unit = previous_by_key.get(key)
        if previous_unit is None:
            continue

        if (
            "token_count" in previous_unit
            and _tokenized_source_text(previous_unit)
            == _tokenized_source_text(current_unit)
        ):
            current_unit["token_count"] = previous_unit["token_count"]

        _copy_unchanged_token_counts(
            previous_unit.get("children", []),
            current_unit.get("children", []),
            scope=(*scope, key),
        )


def _preserve_unchanged_token_counts(previous: dict | None, current: dict) -> None:
    """Preserve downstream token enrichment only across deterministic text matches."""
    if previous is None:
        return

    previous_units = previous.get("data", {}).get("units", [])
    current_units = current.get("data", {}).get("units", [])
    _validate_unit_sibling_keys(previous_units, tree_name="previous")
    _validate_unit_sibling_keys(current_units, tree_name="current")
    _copy_unchanged_token_counts(previous_units, current_units)


def parse_document(slug: str, dry_run: bool = False) -> None:
    """Parse a single Westminster Standards document from HTML and write JSON."""
    if slug not in DOCUMENT_CONFIGS:
        log.error("Unknown document slug: %s", slug)
        print(f"ERROR: Unknown slug {slug!r}. Valid slugs: {list(DOCUMENT_CONFIGS.keys())}")
        return

    start_time = datetime.now(timezone.utc)
    log.info("=== Parsing document: %s ===", slug)

    html_path = RAW_DIR / f"{slug}.html"
    if not html_path.exists():
        log.error("HTML not found: %s", html_path)
        print(f"ERROR: HTML not found: {html_path}")
        return

    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    parser_fn = PARSER_FN_MAP[slug]
    units = parser_fn(soup)

    # Quality stats
    section_count = len(units)
    word_count = _count_words_in_units(units)
    empty_sections = _find_empty_sections(units)

    print("")
    print(f"=== Document Quality Stats: {slug} ===")
    print(f"Section count:   {section_count}")
    print(f"Word count:      {word_count}")
    print(f"Empty sections:  {len(empty_sections)}")
    if empty_sections:
        print(f"  Empty nums: {empty_sections}")

    # Content plausibility: flag sections whose text opens with nav/footer words
    plausibility_warnings = _check_content_plausibility(units, slug)
    if plausibility_warnings:
        print(f"Plausibility warnings: {len(plausibility_warnings)}")
        for w in plausibility_warnings:
            print(w)
        log.warning("Plausibility warnings for %s: %s", slug, plausibility_warnings)
    print("")

    log.info("Stats: %d sections, %d words, %d empty, %d plausibility warnings",
             section_count, word_count, len(empty_sections), len(plausibility_warnings))

    out_path = DOCS_OUT_DIR / f"{slug}.json"
    previous = None
    if not dry_run and out_path.exists():
        previous = json.loads(out_path.read_text(encoding="utf-8"))

    doc = _build_doctrinal_document(slug, units)
    _preserve_unchanged_token_counts(previous, doc)

    if dry_run:
        log.info("DRY RUN -- no files written for %s", slug)
        print("DRY RUN: no files written.")
        return

    entries_changed, fields_changed = _document_delta_counts(previous, doc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Writing: %s", out_path)
    repo_root = DOCS_OUT_DIR.parents[1]
    with writer_manifest.run(
        writer_identity="westminster_standard_parser",
        writer_version=SCRIPT_VERSION,
        data_paths=[out_path],
        repo_root=repo_root,
        manifests_dir=repo_root / "review" / "writer-manifests",
    ) as manifest_run:
        out_path.write_text(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest_run.record_delta(
            out_path,
            entries_changed=entries_changed,
            fields_changed=fields_changed,
        )
    log.info("Written: %s", out_path)
    log.info(
        "Writer manifest: %d entries changed, %d fields changed",
        entries_changed,
        fields_changed,
    )

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    print(f"Done: {out_path.name} ({elapsed:.1f}s)")


def parse_all_documents(dry_run: bool = False) -> None:
    """Parse all 5 Westminster Standards documents."""
    slugs = list(DOCUMENT_CONFIGS.keys())
    log.info("=== Parsing all %d documents ===", len(slugs))

    # Preflight: verify all HTML source files exist before starting any writes
    missing = [slug for slug in slugs if not (RAW_DIR / f"{slug}.html").exists()]
    if missing:
        log.error("Preflight failed -- missing HTML files: %s", missing)
        print(f"ERROR: Missing HTML files for: {missing}")
        print("Run the downloader before parsing.")
        return

    failed = []
    for slug in slugs:
        try:
            parse_document(slug, dry_run=dry_run)
        except Exception as exc:
            log.error("Failed to parse %r: %s", slug, exc, exc_info=True)
            print(f"ERROR: {slug} failed: {exc}")
            failed.append(slug)

    if failed:
        log.error("=== %d document(s) failed: %s ===", len(failed), failed)
        print(f"Completed with {len(failed)} failure(s): {failed}")
    else:
        log.info("=== All documents complete ===")


# ---------------------------------------------------------------------------
# Manifest sync — Task 6 Step 8
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Manifest not found: {MANIFEST_PATH}\n"
            "Run --sync-manifest after generating at least one document, or create the file manually."
        )
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return json.load(f)


def _sync_manifest(dry_run: bool = False) -> None:
    """Rebuild the manifest from all JSON files in data/doctrinal-documents/."""
    log.info("Syncing manifest: %s", MANIFEST_PATH)

    manifest = _load_manifest()
    existing = {entry["id"]: entry for entry in manifest["documents"]}

    json_files = sorted(
        f for f in DOCS_OUT_DIR.glob("*.json")
        if not f.name.startswith("_")
    )

    new_documents = []
    for jf in json_files:
        with open(jf, encoding="utf-8") as f:
            doc = json.load(f)
        meta = doc.get("meta", {})
        data = doc.get("data", {})
        doc_id = meta.get("id", jf.stem)

        # Derive core fields from the JSON (source of truth), then overlay any
        # hand-added fields from the existing manifest entry so they are preserved.
        json_entry = {
            "id": doc_id,
            "title": meta.get("title", ""),
            "document_kind": data.get("document_kind", ""),
            "file": jf.name,
        }
        if doc_id in existing:
            merged = {**existing[doc_id], **json_entry}
            if merged != existing[doc_id]:
                log.info("Manifest entry updated for %r", doc_id)
            new_documents.append(merged)
        else:
            log.info("New manifest entry created for %r", doc_id)
            new_documents.append(json_entry)

    manifest["documents"] = new_documents
    log.info("Manifest: %d entries", len(new_documents))

    print(f"Manifest: {len(new_documents)} entries")

    if dry_run:
        print("DRY RUN: manifest not written.")
        return

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("Manifest written: %s", MANIFEST_PATH)
    print("Manifest updated.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    setup_logging()
    # Add repo root to sys.path so build.lib.citation_parser can be imported
    # inside helper functions (moved here from module level for PY-06 compliance).
    sys.path.insert(0, str(REPO_ROOT))
    parser = argparse.ArgumentParser(
        description="Enrich Westminster Standards data files with proof texts."
    )
    parser.add_argument(
        "--enrich-wsc",
        action="store_true",
        help="Enrich the Westminster Shorter Catechism with proof texts.",
    )
    parser.add_argument(
        "--document",
        metavar="SLUG",
        help="Parse a single document by slug (e.g. directory-for-family-worship).",
    )
    parser.add_argument(
        "--all-documents",
        action="store_true",
        help="Parse all 5 Westminster Standards documents.",
    )
    parser.add_argument(
        "--sync-manifest",
        action="store_true",
        help="Sync the manifest from all JSON files in data/doctrinal-documents/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report without writing any files.",
    )
    args = parser.parse_args()
    log.info("Args: %s", args)

    ran_any = False
    if args.enrich_wsc:
        enrich_wsc(dry_run=args.dry_run)
        ran_any = True
    if args.document:
        parse_document(args.document, dry_run=args.dry_run)
        ran_any = True
    if args.all_documents:
        parse_all_documents(dry_run=args.dry_run)
        ran_any = True
    if args.sync_manifest:
        _sync_manifest(dry_run=args.dry_run)
        ran_any = True
    if not ran_any:
        parser.print_help()


if __name__ == "__main__":
    main()
