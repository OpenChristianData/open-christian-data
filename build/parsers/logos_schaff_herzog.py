"""logos_schaff_herzog.py
Parser for the New Schaff-Herzog Encyclopedia of Religious Knowledge
scraped from the Logos web reader (limited view mode HTML).

Input:  raw/logos/nsherk/articles/{idx:05d}_{slug}.html
        -- HTML fragment scraped by build/tools/fetch_logos_nsherk.py.
Output: entries appended to data/reference/schaff-herzog-encyclopedia.json,
        same file and schema as ccel_schaff_herzog.py (reference_entry v2.1.0).

Provenance
----------
source_url:    https://app.logos.com/books/LLS%3ANSHERK
source_format: Logos web reader (limited view mode HTML)

Usage
-----
    py -3 build/parsers/logos_schaff_herzog.py              # parse all
    py -3 build/parsers/logos_schaff_herzog.py --dry-run    # no writes
    py -3 build/parsers/logos_schaff_herzog.py --validate   # validate output
"""

import argparse
import copy
import json
import logging
import re
import sys
import unicodedata
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from build.lib.scripture_canon import all_osis_books

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = _REPO_ROOT / "raw" / "logos" / "nsherk" / "articles"
OUTPUT_FILE = _REPO_ROOT / "data" / "reference" / "schaff-herzog-encyclopedia.json"
LOG_PATH = _REPO_ROOT / "logs" / "logos_schaff_herzog.log"

DICTIONARY_ID = "schaff-herzog-encyclopedia"
SOURCE_URL = "https://app.logos.com/books/LLS%3ANSHERK"
SOURCE_FORMAT = "Logos web reader (limited view mode HTML)"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Slug / ID helpers (copied from ccel_schaff_herzog.py per prompt spec)
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Convert term text to a URL-safe lowercase slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text.strip())
    text = text.strip("-")
    return text or "entry"


def make_unique_id(base: str, seen: set) -> str:
    """Return base if not in seen, else base-2, base-3, etc. (PIPE-04)."""
    candidate = base
    n = 2
    while candidate in seen:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


# ---------------------------------------------------------------------------
# HTML parsing helpers
# ---------------------------------------------------------------------------


def _is_attribution_paragraph(p: Tag) -> bool:
    """Return True for <p style*='text-align:right'> -- the author attribution line."""
    style = p.get("style", "")
    return "text-align:right" in style


def _is_bibliography_paragraph(p: Tag) -> bool:
    """Return True for <p style*='font-size:.925em'> -- the bibliography line."""
    style = p.get("style", "")
    return "font-size:.925em" in style


def _is_body_paragraph(p: Tag) -> bool:
    """Return True for body paragraphs (not attribution, not bibliography)."""
    return not _is_attribution_paragraph(p) and not _is_bibliography_paragraph(p)


def _strip_empty_spans(p: Tag) -> None:
    """Remove offset-marker spans and headword spans (empty, no text content)."""
    for span in p.find_all("span", class_="offset-marker"):
        span.decompose()
    for span in p.find_all("span", attrs={"rel": "headword"}):
        span.decompose()


def _extract_term(p: Tag) -> str:
    """Extract the headword term from the leading body paragraph.

    Joins all <strong> text in the paragraph, separated by ', '.
    Strips pronunciation phonetic spans (lang-x-tl) and popup asterisk links.
    """
    strong_tags = p.find_all("strong")
    parts = [s.get_text(strip=True) for s in strong_tags]
    # Filter empty strings (belt-and-suspenders for malformed HTML)
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else ""


def _extract_alt_terms(p: Tag) -> list:
    """Extract data-headword values from <span rel='headword'> elements."""
    return [
        span["data-headword"]
        for span in p.find_all("span", attrs={"rel": "headword"})
        if span.get("data-headword")
    ]


def _extract_paragraph_text(p: Tag) -> str:
    """Extract plain text from a body paragraph.

    Strips:
    - offset-marker spans (no text content)
    - headword spans (no text content)
    - pronunciation phonetic spans (lang-x-tl)
    - popup asterisk links (<a rel='popup' ...>*</a>)

    Keeps:
    - article body text
    - cross-reference link text (<a data-articleid> inner span text)
    - inline popup link text when it has real content (e.g. <a rel=popup><em>MGH</em></a>)
    - Bible reference link text (<a class='bibleref'>)
    """
    p_copy = copy.deepcopy(p)

    # Remove offset-markers and headword spans (structurally empty)
    for span in p_copy.find_all("span", class_="offset-marker"):
        span.decompose()
    for span in p_copy.find_all("span", attrs={"rel": "headword"}):
        span.decompose()

    # Remove phonetic pronunciation spans (lang-x-tl)
    for span in p_copy.find_all("span", class_="lang-x-tl"):
        span.decompose()

    # Remove pronunciation popup asterisk links (inner text is just '*')
    for a in p_copy.find_all("a", rel="popup"):
        inner = a.get_text(strip=True)
        if inner == "*":
            a.decompose()

    return p_copy.get_text(" ", strip=True)


def _extract_related_terms(paragraphs: list) -> list:
    """Collect cross-reference link text, grouping by data-articleid.

    Multiple consecutive <a data-articleid="X"> tags with the same ID (e.g.
    "Nicholas" + " I" split across two anchors) are joined into one term.
    """
    by_id: dict = {}   # articleid -> accumulated text parts (in order)
    order: list = []   # insertion-order list of unique articleids
    for p in paragraphs:
        for a in p.find_all("a", attrs={"data-articleid": True}):
            article_id = a["data-articleid"]
            text = a.get_text(" ", strip=True)
            if article_id not in by_id:
                by_id[article_id] = []
                order.append(article_id)
            if text:
                by_id[article_id].append(text)

    seen_text: set = set()
    terms: list = []
    for article_id in order:
        text = " ".join(by_id[article_id]).strip()
        if text and text not in seen_text:
            seen_text.add(text)
            terms.append(text)
    return terms


def _osis_from_logos_ref(data_ref: str) -> list:
    """Convert a Logos data-reference string to an OSIS reference list.

    Format: 'bible.{book_num}.{chapter}.{verse}' → ['BookName.ch.v']
    Example: 'bible.18.26.6' → ['Job.26.6']

    Uses the structured attribute directly rather than parsing display text,
    so abbreviation variants in the display text cannot cause mismatches.
    Returns [] for malformed or non-bible references.
    """
    parts = data_ref.split(".")
    if len(parts) < 4 or parts[0] != "bible":
        return []
    try:
        book_num = int(parts[1])
        books = all_osis_books()
        if 1 <= book_num <= len(books):
            return [f"{books[book_num - 1]}.{'.'.join(parts[2:])}"]
    except (ValueError, IndexError):
        pass
    return []


def _extract_scripture_references(paragraphs: list) -> list:
    """Extract <a class='bibleref'> links as scripture_references objects.

    Uses data-reference='bible.{book}.{ch}.{v}' for OSIS conversion rather
    than parsing the display text -- the attribute is structured data already
    in the right form, so no display-text ambiguity.
    """
    seen: set = set()
    refs: list = []
    for p in paragraphs:
        for a in p.find_all("a", class_="bibleref"):
            raw = a.get_text(strip=True)
            if not raw or raw in seen:
                continue
            seen.add(raw)
            data_ref = a.get("data-reference", "")
            osis = _osis_from_logos_ref(data_ref) if data_ref else []
            refs.append({"raw": raw, "osis": osis})
    return refs


# ---------------------------------------------------------------------------
# Core parse function (public API -- tested directly)
# ---------------------------------------------------------------------------


def parse_article(html: str) -> dict:
    """Parse a raw Logos NSHERK article HTML fragment into a reference_entry dict.

    Parameters
    ----------
    html:
        Raw HTML content as scraped: a sequence of <p> elements.

    Returns
    -------
    dict matching the reference_entry data-item schema.
    """
    soup = BeautifulSoup(html, "html.parser")
    all_paragraphs = soup.find_all("p")
    body_paragraphs = [p for p in all_paragraphs if _is_body_paragraph(p)]

    # Term and alt_terms come from the FIRST body paragraph (leading <p>)
    leading_p = body_paragraphs[0] if body_paragraphs else None
    term = _extract_term(leading_p) if leading_p else ""
    alt_terms = _extract_alt_terms(leading_p) if leading_p else []

    # entry_id derived from term — same slug the scraper builds from the HTML headword
    article_slug = slugify(term) if term else "entry"

    # definition_blocks: plain text of each body paragraph (all but attribution/bibliography)
    definition_blocks: list = []
    for p in body_paragraphs:
        text = _extract_paragraph_text(p)
        if text:
            definition_blocks.append(text)

    # related_terms and scripture_references scan all paragraphs (including attribution)
    related_terms = _extract_related_terms(all_paragraphs)
    scripture_references = _extract_scripture_references(all_paragraphs)

    word_count = sum(len(block.split()) for block in definition_blocks)

    return {
        "entry_id": f"schaff-herzog.{article_slug}",
        "dictionary_id": DICTIONARY_ID,
        "term": term,
        "alt_terms": alt_terms,
        "definition_blocks": definition_blocks,
        "scripture_references": scripture_references,
        "related_terms": related_terms,
        "word_count": word_count,
    }


# ---------------------------------------------------------------------------
# File-level driver
# ---------------------------------------------------------------------------


def parse_file(html_path: Path) -> dict | None:
    """Parse one raw HTML file into a reference_entry dict.

    Returns None on unrecoverable error.
    """
    try:
        html = html_path.read_text(encoding="utf-8")
        return parse_article(html)
    except Exception as exc:
        logger.error("Error parsing %s: %s", html_path.name, exc)
        return None


# ---------------------------------------------------------------------------
# Main (dry-run and full write modes)
# ---------------------------------------------------------------------------


DRY_RUN = False  # Set True by --dry-run flag at startup; controls write path (API-01)


def main() -> int:
    global DRY_RUN
    parser = argparse.ArgumentParser(
        description="Parse Logos NSHERK raw HTML articles into the schaff-herzog JSON."
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse but write nothing.")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO"])
    args = parser.parse_args()
    DRY_RUN = args.dry_run

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        handlers=[
            logging.FileHandler(str(LOG_PATH), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    if not RAW_DIR.exists() or not any(RAW_DIR.glob("*.html")):
        logger.error("No HTML articles found in %s -- run fetch_logos_nsherk.py first.", RAW_DIR)
        return 1

    html_files = sorted(RAW_DIR.glob("*.html"))
    logger.info("Found %d article HTML files in %s", len(html_files), RAW_DIR)

    # Load existing output file to merge (add new entries only)
    if OUTPUT_FILE.exists():
        existing_data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    else:
        logger.error("Output file not found: %s -- run ccel_schaff_herzog.py first.", OUTPUT_FILE)
        return 1

    existing_ids: set = {e["entry_id"] for e in existing_data["data"]}
    seen_ids: set = set(existing_ids)

    new_entries: list = []
    errors = 0

    for i, html_path in enumerate(html_files):
        entry = parse_file(html_path)
        if entry is None:
            errors += 1
            continue

        entry_id = entry["entry_id"]
        if entry_id in seen_ids:
            logger.debug("Skipping duplicate %s", entry_id)
            continue

        # Deduplicate within this run
        unique_id = make_unique_id(entry_id, seen_ids)
        if unique_id != entry_id:
            logger.warning("ID collision -- remapped %s -> %s", entry_id, unique_id)
            entry["entry_id"] = unique_id
        seen_ids.add(unique_id)
        new_entries.append(entry)

        if (i + 1) % 100 == 0:
            logger.info("Progress: processed %d / %d", i + 1, len(html_files))

    logger.info(
        "Parsed %d new entries, %d errors, %d skipped duplicates.",
        len(new_entries), errors, len(html_files) - len(new_entries) - errors,
    )

    if DRY_RUN:
        logger.info("[DRY_RUN] Would add %d entries to %s -- no writes.", len(new_entries), OUTPUT_FILE)
        return 0

    if new_entries:
        existing_data["data"].extend(new_entries)
        tmp = OUTPUT_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(existing_data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(OUTPUT_FILE)
        logger.info("Wrote %d new entries to %s", len(new_entries), OUTPUT_FILE)
    else:
        logger.info("No new entries to write.")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
