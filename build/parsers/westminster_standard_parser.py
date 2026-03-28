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
import hashlib
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

WSC_HTML = REPO_ROOT / "raw" / "westminster-standard-org" / "westminster-shorter-catechism.html"
WSC_JSON = REPO_ROOT / "data" / "catechisms" / "westminster-shorter-catechism.json"
WSC_CONFIG = REPO_ROOT / "sources" / "catechisms" / "westminster-shorter-catechism" / "config.json"

LOG_FILE = Path(__file__).resolve().parent / "westminster_standard_parser.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Citation parser import
# ---------------------------------------------------------------------------

# Add repo root to path so build.lib.citation_parser can be imported
sys.path.insert(0, str(REPO_ROOT))

from build.lib.citation_parser import _build_osis_entries, lookup_book, parse_citation_string  # noqa: E402


# ---------------------------------------------------------------------------
# Continuation-reference handling
# ---------------------------------------------------------------------------

def _normalise_citation(citation: str) -> str:
    """Pre-process a raw citation string before semicolon-splitting.

    Handles two WSC-specific edge cases:

    1. Comma-separated new-book refs: e.g. "Acts 4:24-28, Rev. 4:11" where the
       comma precedes a new book, not a verse continuation. Detected by checking
       if a comma-part begins with a recognisable book abbreviation. Converted
       to a semicolon separator so downstream splitting treats it as a new ref.

    2. Psalm title references: e.g. "Ps. 92 title" -- 'title' is not a verse
       number. Strip the word 'title' so it becomes a chapter-only ref "Ps. 92".
    """
    # Step 1: strip trailing period from whole string
    s = citation.strip().rstrip(".")

    # Step 2: normalise ' with ' to semicolon (same as citation_parser)
    s = s.replace(" with ", "; ")

    # Step 3: detect comma-book splits within each semicolon segment
    semi_parts = s.split(";")
    fixed_parts: list[str] = []
    for sp in semi_parts:
        sp = sp.strip()
        if not sp:
            continue
        comma_parts = [cp.strip() for cp in sp.split(",")]
        if len(comma_parts) <= 1:
            fixed_parts.append(sp)
            continue
        # Check each comma-part after the first: if it starts with a book
        # abbreviation, it is a new ref -- convert the preceding comma to semicolon
        accumulated = comma_parts[0]
        for cp in comma_parts[1:]:
            if _starts_with_book(cp):
                # Flush accumulated as one ref, start fresh
                old_accumulated = accumulated
                fixed_parts.append(accumulated)
                accumulated = cp
                log.info("  Comma-book split: %r -> %r + %r", sp, old_accumulated, cp)
            else:
                accumulated = accumulated + ", " + cp
        fixed_parts.append(accumulated)

    # Step 4: strip 'title' from Psalm title references (e.g. "Ps. 92 title")
    normalised: list[str] = []
    for part in fixed_parts:
        stripped = re.sub(r'\s+title\b', '', part, flags=re.IGNORECASE).strip()
        if stripped != part:
            log.info("  Psalm title ref normalised: %r -> %r", part, stripped)
        normalised.append(stripped)

    return "; ".join(normalised)


def _starts_with_book(token: str) -> bool:
    """Return True if token begins with a recognisable biblical book abbreviation."""
    toks = token.strip().split()
    if not toks:
        return False
    # Single-word book (e.g. "Rev.", "Ps.")
    cand = toks[0].rstrip(".")
    if lookup_book(cand) is not None:
        return True
    # Numbered book (e.g. "1 Cor.", "2 Tim.")
    if len(toks) >= 2 and toks[0].isdigit():
        cand2 = toks[0] + " " + toks[1].rstrip(".")
        if lookup_book(cand2) is not None:
            return True
    return False


def _parse_citation_with_continuation(citation: str) -> tuple[list[dict], list[str]]:
    """Parse a citation string, resolving bare chapter:verse continuation refs.

    Also handles:
    - Comma-separated new-book refs (e.g. "Acts 4:24-28, Rev. 4:11")
    - Psalm title references (e.g. "Ps. 92 title" -> chapter-only ref)
    - Bare continuation refs (e.g. "15:4" after "Rev. 4:8" -> Rev. 15:4)

    Returns:
        (references, errors) where errors is a list of unparseable parts.
    """
    # Pre-process to fix comma-book splits and title refs
    s = _normalise_citation(citation)

    parts = [p.strip() for p in s.split(";")]
    results: list[dict] = []
    errors: list[str] = []
    last_book_osis: str | None = None

    for part in parts:
        if not part:
            continue

        # Check for bare continuation ref: starts with digits + colon (e.g. "15:4")
        if re.match(r"^\d+:", part) and last_book_osis is not None:
            # Inherit book from the previous reference
            raw = part
            chapter, verse_portion = part.split(":", 1)
            chapter = chapter.strip()
            verse_portion = verse_portion.strip()
            osis_list = _build_osis_entries(last_book_osis, chapter, verse_portion)
            results.append({"raw": raw, "osis": osis_list})
            log.info("  Continuation ref resolved: %r -> book=%s osis=%s",
                     part, last_book_osis, osis_list)
            continue

        # Normal parse via citation_parser
        try:
            ref_dict = _parse_single_with_book_tracking(part)
            results.append(ref_dict["result"])
            last_book_osis = ref_dict["book"]
        except Exception as exc:
            errors.append(part)
            log.warning("  Could not parse reference %r: %s", part, exc)

    return results, errors



def _parse_single_with_book_tracking(ref: str) -> dict:
    """Wrap parse_single_reference and extract the book code for continuation tracking.

    Returns:
        dict with keys "result" (the reference dict) and "book" (OSIS book code).
    """
    from build.lib.citation_parser import parse_single_reference, _extract_book_and_remainder

    raw = ref.strip()
    book_code, _ = _extract_book_and_remainder(raw)
    result = parse_single_reference(raw)
    return {"result": result, "book": book_code}


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def extract_wsc_proofs_from_html(html_path: Path) -> tuple[dict[int, list[dict]], dict[int, list[str]], list[int]]:
    """Parse WSC HTML and return a mapping of {question_index: references_list}.

    question_index is 1-based, matching sort_key in the JSON.

    Returns:
        dict mapping sort_key (int) -> list of parsed reference dicts.
    """
    log.info("Parsing HTML: %s", html_path)
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # Locate all Q&A paragraphs: <p> elements containing a <b> starting with "Q."
    qa_paragraphs = [
        p for p in soup.find_all("p")
        if p.find("b") and p.find("b").get_text(strip=True).startswith("Q.")
    ]
    log.info("Found %d Q&A paragraphs in HTML", len(qa_paragraphs))

    proofs_by_index: dict[int, list[dict]] = {}
    parse_errors: dict[int, list[str]] = {}
    questions_without_proofs: list[int] = []

    for idx, qa_p in enumerate(qa_paragraphs, start=1):
        sibling = qa_p.find_next_sibling("p")

        if sibling is None or not sibling.find("em"):
            log.warning("Q%d: no proof text sibling found", idx)
            questions_without_proofs.append(idx)
            proofs_by_index[idx] = []
            continue

        citation_text = sibling.find("em").get_text(strip=True)
        if not citation_text:
            log.warning("Q%d: empty em tag in proof sibling", idx)
            questions_without_proofs.append(idx)
            proofs_by_index[idx] = []
            continue

        refs, errors = _parse_citation_with_continuation(citation_text)

        if errors:
            parse_errors[idx] = errors
        proofs_by_index[idx] = refs
        log.info("Q%d: %d references parsed from %r", idx, len(refs), citation_text[:60])

    # Log summary stats
    total_refs = sum(len(r) for r in proofs_by_index.values())
    log.info("Extraction complete: %d questions, %d with proofs, %d without, %d total refs",
             len(qa_paragraphs),
             len([v for v in proofs_by_index.values() if v]),
             len(questions_without_proofs),
             total_refs)
    if parse_errors:
        log.warning("Parse errors in %d questions: %s", len(parse_errors), parse_errors)

    return proofs_by_index, parse_errors, questions_without_proofs


# ---------------------------------------------------------------------------
# JSON enrichment
# ---------------------------------------------------------------------------

def enrich_wsc(dry_run: bool = False) -> None:
    """Read the WSC JSON, populate proofs from the HTML, and write it back."""
    start_time = datetime.now(ZoneInfo("Australia/Melbourne"))
    log.info("=== WSC enrichment started at %s ===", start_time.isoformat())

    # Step 1: Parse proofs from HTML
    proofs_by_index, parse_errors, questions_without_proofs = extract_wsc_proofs_from_html(WSC_HTML)

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

    for entry in entries:
        sort_key = entry["sort_key"]
        if sort_key not in proofs_by_index:
            log.warning("sort_key %d not found in HTML extraction", sort_key)
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

    end_time = datetime.now(ZoneInfo("Australia/Melbourne"))
    elapsed = (end_time - start_time).total_seconds()
    log.info("=== WSC enrichment complete in %.1fs ===", elapsed)
    print(f"Done. Elapsed: {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Document parsing — Task 6
# ---------------------------------------------------------------------------

RAW_DIR = REPO_ROOT / "raw" / "westminster-standard-org"
DOCS_OUT_DIR = REPO_ROOT / "data" / "doctrinal-documents"
SOURCES_OUT_DIR = REPO_ROOT / "sources" / "doctrinal-documents"

PROCESSING_DATE = "2026-03-28"
SCRIPT_VERSION = "build/parsers/westminster_standard_parser.py@v2.0.0"

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


def _sha256_file(path: Path) -> str:
    """Return sha256:<hex> for a file."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


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


def _build_doctrinal_document(slug: str, units: list[dict]) -> dict:
    """Assemble the full doctrinal document JSON structure for a slug."""
    config = DOCUMENT_CONFIGS[slug]
    html_path = RAW_DIR / f"{slug}.html"
    source_hash = _sha256_file(html_path)

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
                "source_url": f"https://thewestminsterstandard.org/{slug}",
                "source_format": "html",
                "source_edition": "thewestminsterstandard.org (web edition, 2026-03-28)",
                "download_date": "2026-03-28",
                "source_hash": source_hash,
                "processing_method": "automated",
                "processing_script_version": SCRIPT_VERSION,
                "processing_date": PROCESSING_DATE,
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


def parse_document(slug: str, dry_run: bool = False) -> None:
    """Parse a single Westminster Standards document from HTML and write JSON."""
    if slug not in DOCUMENT_CONFIGS:
        log.error("Unknown document slug: %s", slug)
        print(f"ERROR: Unknown slug {slug!r}. Valid slugs: {list(DOCUMENT_CONFIGS.keys())}")
        return

    start_time = datetime.now(ZoneInfo("Australia/Melbourne"))
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
    empty_sections = [
        u.get("number", "?")
        for u in units
        if not u.get("content", "").strip() and not u.get("children")
    ]

    print("")
    print(f"=== Document Quality Stats: {slug} ===")
    print(f"Section count:   {section_count}")
    print(f"Word count:      {word_count}")
    print(f"Empty sections:  {len(empty_sections)}")
    if empty_sections:
        print(f"  Empty nums: {empty_sections}")
    print("")

    log.info("Stats: %d sections, %d words, %d empty", section_count, word_count, len(empty_sections))

    doc = _build_doctrinal_document(slug, units)

    if dry_run:
        log.info("DRY RUN -- no files written for %s", slug)
        print("DRY RUN: no files written.")
        return

    out_path = DOCS_OUT_DIR / f"{slug}.json"
    log.info("Writing: %s", out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    log.info("Written: %s", out_path)

    elapsed = (datetime.now(ZoneInfo("Australia/Melbourne")) - start_time).total_seconds()
    print(f"Done: {out_path.name} ({elapsed:.1f}s)")


def parse_all_documents(dry_run: bool = False) -> None:
    """Parse all 5 Westminster Standards documents."""
    slugs = list(DOCUMENT_CONFIGS.keys())
    log.info("=== Parsing all %d documents ===", len(slugs))
    for slug in slugs:
        parse_document(slug, dry_run=dry_run)
    log.info("=== All documents complete ===")


# ---------------------------------------------------------------------------
# Manifest sync — Task 6 Step 8
# ---------------------------------------------------------------------------

MANIFEST_PATH = REPO_ROOT / "data" / "doctrinal-documents" / "_manifest.json"


def _load_manifest() -> dict:
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

        if doc_id in existing:
            new_documents.append(existing[doc_id])
        else:
            new_documents.append({
                "id": doc_id,
                "title": meta.get("title", ""),
                "document_kind": data.get("document_kind", ""),
                "file": jf.name,
            })

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

    if args.enrich_wsc:
        enrich_wsc(dry_run=args.dry_run)
    elif args.document:
        parse_document(args.document, dry_run=args.dry_run)
    elif args.all_documents:
        parse_all_documents(dry_run=args.dry_run)
    elif args.sync_manifest:
        _sync_manifest(dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
