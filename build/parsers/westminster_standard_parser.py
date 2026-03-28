"""build/parsers/westminster_standard_parser.py

Enriches Westminster Standards data files with proof texts scraped from
thewestminsterstandard.org.

Current scope (Task 5): WSC proof text enrichment only.
Extended in Task 6 to handle the 5 additional Westminster Standards documents.

Usage:
    py -3 build/parsers/westminster_standard_parser.py --enrich-wsc
"""

import argparse
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
        "--dry-run",
        action="store_true",
        help="Parse and report without writing any files.",
    )
    args = parser.parse_args()

    if args.enrich_wsc:
        enrich_wsc(dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
