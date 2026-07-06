"""
Catholic Encyclopedia (1907-1914) parser.

Source: https://www.newadvent.org/cathen/
Vol 1 pilot: ~750-900 articles.
Rate limit: 1-2 seconds between requests. Stops immediately on 429/403.
"""

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.bible_ref_normalizer import parse_thml_refs
from build.lib.paths import REPO_ROOT

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DICTIONARY_ID = "catholic-encyclopedia"
SCHEMA_VERSION = "2.1.0"
BASE_URL = "https://www.newadvent.org/cathen/"
USER_AGENT = (
    "OCD-Crawler/1.0 (Open Christian Data; public domain text research; "
    "contact openchristiandata@gmail.com)"
)
OUTPUT_DIR = REPO_ROOT / "data" / "reference"
SCRIPT_VERSION = "build/parsers/catholic_encyclopedia.py@v1.0.0"
RATE_DELAY_MIN = 1.0
RATE_DELAY_MAX = 2.0
LIGATURE_TRANSLITERATIONS = str.maketrans({
    "Æ": "AE",
    "æ": "ae",
    "Œ": "OE",
    "œ": "oe",
})
SCRIPTURE_REF_RE = re.compile(
    r"\b(\d?\s*[A-Za-z][A-Za-z]+\d?)\s+(\d+:\d+(?:-\d+)?)\b"
)
ARTICLE_HREF_RE = re.compile(r"(?:^|/)\d{5}[a-z]\.htm$", re.IGNORECASE)
SEE_TERM_RE = re.compile(
    r"\b[Ss]ee(?: also)?\s+([A-Z][A-Za-z][A-Za-z' -]{1,80}?)(?=\s+and\b|[.;,]|$)"
)
SEE_CONTEXT_RE = re.compile(r"\b[Ss]ee(?: also)?\b[^.?!;:]*$")


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def article_url(vol: int, page: int, suffix: str = "a") -> str:
    """Return the canonical newadvent.org URL for an article."""
    return f"{BASE_URL}{vol:02d}{page:03d}{suffix}.htm"


def _is_volume_href(href: str, vol: int) -> bool:
    """Return True if a bare href matches the article pattern for this volume."""
    prefix = f"{vol:02d}"
    pattern = re.compile(rf"^{re.escape(prefix)}\d{{3}}[a-z]\.htm$", re.IGNORECASE)
    return bool(pattern.match(href))


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _add_related_term(term: str, related_terms: list[str], seen_related: set[str]) -> None:
    term = term.strip(" .;,")
    if term and term not in seen_related:
        seen_related.add(term)
        related_terms.append(term)


def _extract_see_link_terms(paragraph) -> list[str]:
    terms: list[str] = []
    for link in paragraph.find_all("a", href=True):
        href = link["href"].strip()
        if not ARTICLE_HREF_RE.search(href):
            continue
        prefix = _paragraph_text_before(paragraph, link)
        if not SEE_CONTEXT_RE.search(prefix):
            continue
        term = link.get_text(separator=" ", strip=True)
        if term:
            terms.append(term)
    return terms


def _paragraph_text_before(paragraph, target) -> str:
    pieces: list[str] = []
    for descendant in paragraph.descendants:
        if descendant is target:
            break
        if isinstance(descendant, str):
            pieces.append(descendant)
    return " ".join("".join(pieces).split())


def parse_article_html(html: str) -> dict | None:
    """Parse one article page and return extracted fields.

    Returns dict(title, contributor, body_blocks) or None if structure is
    unrecognised.  contributor has MLA trailing period stripped.
    """
    soup = BeautifulSoup(html, "html.parser")

    main_div = soup.find("div", id="springfield2")
    if main_div is None:
        return None

    h1 = main_div.find("h1")
    if h1 is None:
        return None

    title = h1.get_text(strip=True)
    pub_div = main_div.find("div", class_="pub")

    # Iterate direct children, collecting <p> after <h1> and before <div.pub>.
    body_blocks: list[str] = []
    related_terms: list[str] = []
    seen_related: set[str] = set()
    for child in main_div.children:
        if not hasattr(child, "name"):
            continue
        if child.name == "div" and "pub" in (child.get("class") or []):
            break
        if child.name == "p":
            text = child.get_text(separator=" ", strip=True)
            if not text:
                continue
            # Skip the donation / gumroad callout paragraph
            if "Please help support" in text or "gumroad" in str(child):
                continue
            body_blocks.append(text)
            for term in _extract_see_link_terms(child):
                _add_related_term(term, related_terms, seen_related)
            for match in SEE_TERM_RE.finditer(text):
                _add_related_term(match.group(1), related_terms, seen_related)

    contributor = ""
    if pub_div:
        mla_span = pub_div.find("span", id="mlaauthor")
        if mla_span:
            contributor = mla_span.get_text(strip=True).rstrip(".")

    return {
        "title": title,
        "contributor": contributor,
        "body_blocks": body_blocks,
        "related_terms": related_terms,
    }


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.translate(LIGATURE_TRANSLITERATIONS)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "-", text)
    text = re.sub(r"[\s_-]+", "-", text.strip())
    text = text.strip("-")
    return text or "entry"


def make_unique_id(base: str, seen: set) -> str:
    candidate = base
    counter = 2
    while candidate in seen:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Schema record builders
# ---------------------------------------------------------------------------

def extract_scripture_references(blocks: list[str]) -> list[dict]:
    refs: list[dict] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for block in blocks:
        for match in SCRIPTURE_REF_RE.finditer(block):
            raw = f"{match.group(1).strip()} {match.group(2)}"
            osis = parse_thml_refs(raw)
            if not osis:
                continue
            key = (raw, tuple(osis))
            if key in seen:
                continue
            seen.add(key)
            refs.append({"raw": raw, "osis": osis})
    return refs


def build_entry(article: dict, seen_ids: set) -> dict:
    term = article["title"]
    base_id = f"{DICTIONARY_ID}.{slugify(term)}"
    entry_id = make_unique_id(base_id, seen_ids)
    seen_ids.add(entry_id)
    blocks = article["body_blocks"]
    word_count = sum(len(b.split()) for b in blocks)
    return {
        "entry_id": entry_id,
        "dictionary_id": DICTIONARY_ID,
        "term": term,
        "alt_terms": [],
        "definition_blocks": blocks,
        "scripture_references": extract_scripture_references(blocks),
        "related_terms": article.get("related_terms", []),
        "word_count": word_count,
    }


def build_meta(
    vol_num: int,
    article_count: int,
    source_hash: str,
    contributors: list,
    apparatus_stats: dict | None = None,
) -> dict:
    process_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contributor_objects = [
        {"name": name, "role": "contributor"}
        for name in sorted(set(contributors))
        if name
    ]
    notes = (
        "Catholic Encyclopedia (1907-1914), 15 vols. Public domain. "
        "Per-article contributor credits extracted from the MLA citation "
        "in each article's 'About this page' section; full list in contributors[]. "
        f"Volume {vol_num}, {article_count} articles ingested."
    )
    if apparatus_stats:
        notes += (
            " Apparatus extraction status: scripture_references extracted from "
            f"plain article text for {apparatus_stats['scripture_populated']}/"
            f"{apparatus_stats['entry_count']} entries; related_terms extracted "
            f"from explicit See/See also cross-references for "
            f"{apparatus_stats['related_populated']}/{apparatus_stats['entry_count']} "
            "entries. Empty arrays mean no citation/link was detected by this "
            "parser pass, not a verified absence in the source."
        )
    return {
        "id": f"{DICTIONARY_ID}-vol{vol_num:02d}",
        "title": "The Catholic Encyclopedia",
        "author": "Various contributors",
        "original_publication_year": 1907,
        "language": "en",
        "tradition": ["catholic"],
        "license": "public-domain",
        "schema_type": "reference_entry",
        "schema_version": SCHEMA_VERSION,
        "completeness": "partial",
        "contributors": contributor_objects,
        "provenance": {
            "source_url": BASE_URL,
            "source_format": "html",
            "source_edition": f"newadvent.org Volume {vol_num}",
            "download_date": process_date,
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": SCRIPT_VERSION,
            "processing_date": process_date,
            "notes": notes,
        },
    }


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def _fetch(url: str, log: logging.Logger) -> str | None:
    """Fetch URL with rate-limited user-agent.

    Returns HTML text, or None on skippable errors.
    Raises SystemExit on 403/429 (hard stop as required by task spec).
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            log.error("HTTP %s on %s — stopping crawl immediately per rate-limit policy.", exc.code, url)
            raise SystemExit(1)
        log.warning("HTTP %s on %s — skipping.", exc.code, url)
        return None
    except Exception as exc:
        log.warning("Fetch error for %s: %s", url, exc)
        return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_volume_urls(vol_num: int, log: logging.Logger) -> list:
    """Scrape the 26 letter-index pages and return deduplicated article URLs.

    The main cathen/ index only has per-letter links (a.htm, b.htm, …).
    Each letter page lists articles from all volumes; we filter to vol_num.
    """
    letters = "abcdefghijklmnopqrstuvwxyz"
    seen: set = set()
    urls: list = []

    for i, letter in enumerate(letters):
        letter_url = f"{BASE_URL}{letter}.htm"
        log.info("Fetching letter index: %s", letter_url)
        if i > 0:
            time.sleep(random.uniform(RATE_DELAY_MIN, RATE_DELAY_MAX))

        html = _fetch(letter_url, log)
        if not html:
            log.warning("Skipping letter %s — fetch failed.", letter)
            continue

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            basename = href.split("/")[-1]
            if _is_volume_href(basename, vol_num) and basename not in seen:
                seen.add(basename)
                urls.append(BASE_URL + basename)

    log.info("Discovered %d article URLs for volume %d.", len(urls), vol_num)
    return urls


# ---------------------------------------------------------------------------
# Main crawl
# ---------------------------------------------------------------------------

def crawl_volume(vol_num: int, output_path: Path, dry_run: bool = False) -> dict:
    """Crawl one volume. Returns a summary dict."""
    log = logging.getLogger(__name__)

    urls = discover_volume_urls(vol_num, log)

    if dry_run:
        log.info("DRY RUN: would crawl %d URLs for volume %d. Stopping here.", len(urls), vol_num)
        return {"discovered_urls": len(urls), "dry_run": True}

    entries: list = []
    seen_ids: set = set()
    all_contributors: list = []
    skipped = 0
    empty_body = 0
    content_hasher = hashlib.sha256()

    for i, url in enumerate(urls):
        if i > 0:
            delay = random.uniform(RATE_DELAY_MIN, RATE_DELAY_MAX)
            time.sleep(delay)

        log.info("[%d/%d] %s", i + 1, len(urls), url)
        html = _fetch(url, log)
        if html is None:
            skipped += 1
            continue

        # Hash content for source_hash (hashes URL + content for determinism)
        content_hasher.update(url.encode("utf-8"))
        content_hasher.update(html.encode("utf-8", errors="replace"))

        article = parse_article_html(html)
        if article is None:
            log.warning("Parse failed (unrecognised structure): %s", url)
            skipped += 1
            continue

        if not article["body_blocks"]:
            log.warning("Empty body for %r (%s) — skipping.", article["title"], url)
            empty_body += 1
            skipped += 1
            continue

        if article["contributor"]:
            all_contributors.append(article["contributor"])

        entries.append(build_entry(article, seen_ids))

    source_hash = f"sha256:{content_hasher.hexdigest()}"
    apparatus_stats = {
        "entry_count": len(entries),
        "scripture_populated": sum(1 for entry in entries if entry["scripture_references"]),
        "related_populated": sum(1 for entry in entries if entry["related_terms"]),
    }
    meta = build_meta(vol_num, len(entries), source_hash, all_contributors, apparatus_stats)

    output = {
        "meta": meta,
        "data": entries,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.json")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, output_path)

    # PIPE-19: verify written count matches in-memory count
    with output_path.open(encoding="utf-8") as fh:
        written = json.load(fh)
    assert len(written["data"]) == len(entries), (
        f"Write verification failed: wrote {len(entries)}, re-read {len(written['data'])}"
    )

    log.info(
        "Wrote %d entries to %s (skipped=%d, empty_body=%d).",
        len(entries), output_path, skipped, empty_body,
    )
    return {
        "discovered_urls": len(urls),
        "entries_written": len(entries),
        "skipped": skipped,
        "empty_body": empty_body,
        "output_path": str(output_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crawl The Catholic Encyclopedia (newadvent.org) for one volume."
    )
    parser.add_argument(
        "--volume",
        type=int,
        required=True,
        choices=range(1, 16),
        metavar="N",
        help="Volume number to crawl (1–15).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover article URLs but do not fetch or write output.",
    )
    args = parser.parse_args()

    setup_logging()
    output_path = OUTPUT_DIR / f"catholic-encyclopedia-vol{args.volume:02d}.json"

    result = crawl_volume(
        vol_num=args.volume,
        output_path=output_path,
        dry_run=args.dry_run,
    )

    if result.get("dry_run"):
        print(f"DRY RUN: {result['discovered_urls']} article URLs found for volume {args.volume}.")
    else:
        print(
            f"Done: {result['entries_written']} entries -> {result['output_path']} "
            f"(skipped={result['skipped']}, empty_body={result['empty_body']})"
        )


if __name__ == "__main__":
    main()
