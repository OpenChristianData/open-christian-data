"""bcp_full_text.py -- Book of Common Prayer full liturgical text (1549, 1559, 1662).

Downloads service pages from:
  1549/1559: http://justus.anglican.org/resources/bcp/<year>/  (HTTP only)
  1662:      https://www.eskimo.com/~lhowell/bcp1662/           (HTTPS via curl)

Python 3.14 on Windows cannot TLS-handshake with either remote using stdlib SSL.
justus.anglican.org is accessible via plain HTTP; eskimo.com requires subprocess curl.
The 1662 path list is sourced from the site's directory.html; it deliberately uses singular
directory names such as occasion/ and misc/ where the source site does.

Usage:
    py -3 build/parsers/bcp_full_text.py --dry-run           (preview all three)
    py -3 build/parsers/bcp_full_text.py                      (full run)
    py -3 build/parsers/bcp_full_text.py --edition bcp-1662  (one edition)
    py -3 build/parsers/bcp_full_text.py --force-download     (re-download cache)
"""

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from build.lib.paths import REPO_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_DIR = REPO_ROOT / "raw" / "bcp-full-text"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).with_suffix(".log")

USER_AGENT = (
    "OpenChristianData/1.0 "
    "(research; open-source data project; contact: openchristiandata@gmail.com)"
)
CRAWL_DELAY_SECONDS = 2
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
SCRIPT_REL_PATH = "build/parsers/bcp_full_text.py"
MIN_FETCHED_WORDS = 40
ERROR_PAGE_PATTERNS = (
    re.compile(r"\bError\s+404\b", re.IGNORECASE),
    re.compile(r"\bFile\s+Not\s+Found\b", re.IGNORECASE),
)

# ---------------------------------------------------------------------------
# Edition definitions
# ---------------------------------------------------------------------------

# 1662 service pages: eskimo.com/~lhowell/bcp1662/ (from known TOC)
_ESKIMO_1662_SERVICES = [
    ("daily/morning.html",         "Morning Prayer"),
    ("daily/evening.html",         "Evening Prayer"),
    ("daily/athanasian.html",      "The Athanasian Creed"),
    ("daily/litany.html",          "The Litany"),
    ("daily/prayers.html",         "Prayers and Thanksgivings"),
    ("communion/index.html",       "Holy Communion"),
    ("baptism/index.html",         "Public Baptism of Infants"),
    ("baptism/riper.html",         "Baptism of Adults"),
    ("baptism/private.html",       "Private Baptism of Children"),
    ("baptism/catechism.html",     "A Catechism"),
    ("baptism/confirm.html",       "Confirmation"),
    ("occasions/marriage.html",    "Solemnization of Matrimony"),
    ("occasion/sick_visit.html",   "Visitation of the Sick"),
    ("occasions/burial.html",      "Burial of the Dead"),
    ("occasions/women.html",       "Churching of Women"),
    ("occasions/commination.html", "Commination"),
    ("misc/sea.html",              "Forms of Prayer to be Used at Sea"),
    ("ordinal/deacons.html",       "Ordination of Deacons"),
    ("ordinal/priests.html",       "Ordering of Priests"),
    ("ordinal/bishops.html",       "Consecration of Bishops"),
]

EDITIONS: dict = {
    "bcp-1549": {
        "title": "The Book of Common Prayer (1549)",
        "author": "Church of England",
        "year": 1549,
        "era": "reformation",
        "source": "justus",
        "base_url": "http://justus.anglican.org/resources/bcp/1549/",
    },
    "bcp-1559": {
        "title": "The Book of Common Prayer (1559)",
        "author": "Church of England",
        "year": 1559,
        "era": "reformation",
        "source": "justus",
        "base_url": "http://justus.anglican.org/resources/bcp/1559/",
    },
    "bcp-1662": {
        "title": "The Book of Common Prayer (1662)",
        "author": "Church of England",
        "year": 1662,
        "era": "post-reformation",
        "source": "eskimo",
        "base_url": "https://www.eskimo.com/~lhowell/bcp1662/",
        "services": _ESKIMO_1662_SERVICES,
    },
}

# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------


def _fetch_http_url(url: str) -> bytes:
    """Fetch URL via plain HTTP using urllib (no TLS required)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        status = getattr(resp, "status", 200)
        if status != 200:
            raise ValueError(f"{url}: HTTP status {status}")
        return resp.read()


def _fetch_via_curl(url: str) -> bytes:
    """Fetch URL via subprocess curl (for HTTPS when Python 3.14 TLS is incompatible)."""
    result = subprocess.run(
        ["curl", "-f", "-s", "-L", "--ssl-no-revoke", "-A", USER_AGENT, url],
        capture_output=True,
        check=True,
        timeout=60,
    )
    return result.stdout


def _validate_fetched_content(url: str, data: bytes) -> None:
    """Reject source fetches that are HTTP error bodies or too small to be real services."""
    html = data.decode("latin-1", errors="replace")
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    normalized = _nws(text)
    for pattern in ERROR_PAGE_PATTERNS:
        if pattern.search(normalized):
            raise ValueError(f"{url}: source returned an error page ({pattern.pattern})")
    word_count = len(normalized.split())
    if word_count < MIN_FETCHED_WORDS:
        raise ValueError(
            f"{url}: fetched content is too small to be a service page "
            f"({word_count} words, minimum {MIN_FETCHED_WORDS})"
        )


def _cache_path(edition_slug: str, cache_name: str) -> Path:
    return RAW_DIR / edition_slug / cache_name


def _fetch_and_cache(
    edition_slug: str, url: str, cache_name: str, source: str, force: bool = False
) -> bytes:
    """Fetch URL, cache to disk, return raw bytes."""
    dest = _cache_path(edition_slug, cache_name)
    if dest.exists() and not force:
        data = dest.read_bytes()
        _validate_fetched_content(url, data)
        return data
    logging.info("Fetching %s", url)
    if source == "justus":
        data = _fetch_http_url(url)
    else:
        data = _fetch_via_curl(url)
    _validate_fetched_content(url, data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(dest)
    time.sleep(CRAWL_DELAY_SECONDS)
    return data


# ---------------------------------------------------------------------------
# HTML extraction
# ---------------------------------------------------------------------------


def _nws(text: str) -> str:
    """Normalize whitespace and strip."""
    return re.sub(r"\s+", " ", text).strip()


def extract_paragraphs_from_justus_html(html: str) -> list:
    """Extract liturgical paragraphs from justus.anglican.org HTML.

    Main content is inside <table width="600" bgcolor="#FFFFFF">.
    Each row has a wide cell (width=450, liturgical text) and a narrow cell
    (width=150, editorial notes to exclude).
    Returns one string per paragraph/heading; navigation excluded.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")

    # Locate main content table (width=600). bgcolor may be on table or on cells.
    main_table = None
    for table in soup.find_all("table"):
        if str(table.get("width", "")) == "600":
            main_table = table
            break

    if main_table is None:
        return []

    paragraphs = []
    for row in main_table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if not cells:
            continue
        # Take only the first (wide) cell; skip the narrow editorial-notes cell
        first_cell = cells[0]
        if str(first_cell.get("width", "")) == "150":
            continue

        for elem in first_cell.find_all(["p", "div"]):
            text = _nws(elem.get_text(" ", strip=True))
            if not text or len(text) < 3:
                continue
            if text.lower().startswith("return to"):
                continue
            paragraphs.append(text)

        # Catch text in <font> elements not nested inside <p>/<div>
        for elem in first_cell.find_all("font"):
            parent_name = elem.parent.name if elem.parent else ""
            if parent_name in ("p", "div"):
                continue
            text = _nws(elem.get_text(" ", strip=True))
            if text and len(text) >= 3 and not text.lower().startswith("return to"):
                paragraphs.append(text)

    # Deduplicate consecutive duplicates (structural artefacts)
    deduped = []
    for p in paragraphs:
        if not deduped or deduped[-1] != p:
            deduped.append(p)
    return deduped


def _elem_text_eskimo(elem) -> str:
    """Recursively extract text, reconstructing drop-cap IMG alt tags."""
    if not isinstance(elem, Tag):
        return _nws(str(elem))
    parts = []
    for child in elem.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag) and child.name == "img":
            parts.append(child.get("alt", ""))
        else:
            parts.append(_elem_text_eskimo(child))
    return _nws("".join(parts))


def extract_paragraphs_from_eskimo_html(html: str) -> list:
    """Extract liturgical paragraphs from eskimo.com/~lhowell/bcp1662/ HTML.

    Structure: headings in H2/H3, rubrics in FONT COLOR=Red+EM, body in P.
    Drop caps: <STRONG><IMG ALT="X">REST</STRONG> where ALT+REST=word.
    Navigation follows the final HR and is excluded.
    Returns one string per element in document order.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("body") or soup

    # Find the final HR to stop before navigation
    all_hrs = body.find_all("hr")
    final_hr = all_hrs[-1] if len(all_hrs) > 1 else None

    paragraphs = []

    def _walk(container):
        for elem in container.children:
            if not isinstance(elem, Tag):
                continue
            if final_hr is not None and elem is final_hr:
                return  # stop at nav separator
            tag = (elem.name or "").lower()

            if tag in ("h1", "h2", "h3", "h4"):
                text = _nws(elem.get_text(" ", strip=True))
                if text:
                    paragraphs.append(text)

            elif tag == "center":
                _walk(elem)

            elif tag == "p":
                text = _elem_text_eskimo(elem)
                if text and text.lower() not in ("next", "previous", "back"):
                    paragraphs.append(text)

            elif tag == "font":
                text = _elem_text_eskimo(elem)
                if text:
                    paragraphs.append(text)

            elif tag == "strong":
                # Drop-cap sentence opener outside a <p>
                text = _elem_text_eskimo(elem)
                if text:
                    following = elem.next_sibling
                    suffix = ""
                    if isinstance(following, NavigableString):
                        suffix = _nws(str(following))
                    full = (text + " " + suffix).strip() if suffix else text
                    paragraphs.append(full)

            elif tag in ("blockquote", "div", "table"):
                _walk(elem)

    _walk(body)

    # Deduplicate consecutive duplicates
    deduped = []
    for p in paragraphs:
        if not deduped or deduped[-1] != p:
            deduped.append(p)
    return deduped


# ---------------------------------------------------------------------------
# Service page discovery (justus.anglican.org)
# ---------------------------------------------------------------------------


def _discover_justus_services(edition_slug: str, cfg: dict, force: bool) -> list:
    """Fetch justus index page; return [(filename, title), ...] for service pages."""
    base_url = cfg["base_url"]
    index_data = _fetch_and_cache(edition_slug, base_url, "_index.html", "justus", force)
    index_html = index_data.decode("latin-1", errors="replace")
    soup = BeautifulSoup(index_html, "html.parser")
    services = []
    seen: set = set()
    skip_titles = {"back", "home", "index", "table of contents", "top", "contents"}
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        # Only local .htm/.html files
        if href.startswith("http") or href.startswith("..") or "/" in href:
            continue
        if not (href.lower().endswith(".htm") or href.lower().endswith(".html")):
            continue
        if href in seen:
            continue
        title = _nws(a.get_text(" ", strip=True))
        if not title or title.lower() in skip_titles:
            continue
        seen.add(href)
        services.append((href, title))
    return services


# ---------------------------------------------------------------------------
# Section / record builders
# ---------------------------------------------------------------------------


def _extract_page_title(html: str, fallback: str) -> str:
    """Extract service name from <title> tag; fall back to provided string.

    Preferred pattern: "The 1559 Book of Common Prayer: Morning Prayer" -> "Morning Prayer".
    Secondary: use full <title> text if non-empty.
    Last resort: use fallback (filename from index link).
    """
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag:
        text = _nws(title_tag.get_text())
        # Preferred: extract service name after colon
        if ": " in text:
            after_colon = text.split(": ", 1)[1].strip()
            if after_colon:
                return after_colon
        # Secondary: use full page title when it's meaningful
        if text and len(text) > 3:
            return text
    return fallback


def _build_section(title: str, paragraphs: list) -> dict:
    word_count = sum(len(p.split()) for p in paragraphs)
    return {
        "section_type": "chapter",
        "title": title,
        "content_blocks": paragraphs,
        "word_count": word_count,
    }


def _hash_cached_files(edition_slug: str, cache_names: list) -> str:
    """SHA-256 over all downloaded HTML files (sorted for determinism)."""
    h = hashlib.sha256()
    edition_raw = RAW_DIR / edition_slug
    for name in sorted(cache_names):
        path = edition_raw / name
        if path.exists():
            h.update(name.encode("utf-8"))
            h.update(b"\n")
            h.update(path.read_bytes())
            h.update(b"\n")
    return f"sha256:{h.hexdigest()}"


def _build_record(edition_slug: str, cfg: dict, sections: list, source_hash: str) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "meta": {
            "id": edition_slug,
            "title": cfg["title"],
            "author": cfg["author"],
            "language": "en",
            "tradition": ["anglican"],
            "era": cfg["era"],
            "license": "public-domain",
            "schema_type": "structured_text",
            "schema_version": SCHEMA_VERSION,
            "completeness": "full",
            "provenance": {
                "source_url": cfg["base_url"],
                "source_format": "HTML",
                "source_edition": f"BCP {cfg['year']} as transcribed by source site",
                "download_date": today,
                "source_hash": source_hash,
                "processing_method": "automated",
                "processing_script_version": SCRIPT_VERSION,
                "processing_date": today,
                "notes": (
                    "Public domain liturgical text. "
                    "Rubrics and stage directions preserved as prose paragraphs."
                ),
            },
        },
        "data": {
            "work_id": edition_slug,
            "work_kind": "devotional-classic",
            "sections": sections,
        },
    }


# ---------------------------------------------------------------------------
# Per-edition parse
# ---------------------------------------------------------------------------


def parse_edition(edition_slug: str, dry_run: bool = False, force: bool = False) -> int:
    """Parse one BCP edition; return section count (0 on error)."""
    cfg = EDITIONS[edition_slug]
    source = cfg["source"]
    base_url = cfg["base_url"]
    logging.info("Parsing %s from %s", edition_slug, base_url)

    if source == "justus":
        services = _discover_justus_services(edition_slug, cfg, force)
        if not services:
            logging.error("%s: no service pages found in index", edition_slug)
            return 0
    else:
        services = list(cfg["services"])

    sections = []
    fetched_names = []
    for rel_path, title in services:
        url = base_url + rel_path
        cache_name = rel_path.replace("/", "__")
        try:
            data = _fetch_and_cache(edition_slug, url, cache_name, source, force)
        except Exception as exc:
            logging.error("%s: failed to fetch %s (%s)", edition_slug, rel_path, exc)
            return 0

        html = data.decode("latin-1", errors="replace")
        fetched_names.append(cache_name)

        if source == "justus":
            # Override index-link title with the service name from the page's <title> tag
            title = _extract_page_title(html, title)
            paragraphs = extract_paragraphs_from_justus_html(html)
        else:
            paragraphs = extract_paragraphs_from_eskimo_html(html)

        if not paragraphs:
            logging.error("%s: zero paragraphs from %s", edition_slug, rel_path)
            return 0

        sections.append(_build_section(title, paragraphs))
        logging.info("  %s: %d paragraphs", title, len(paragraphs))

    if not sections:
        logging.error("%s: no sections produced -- aborting", edition_slug)
        return 0

    source_hash = _hash_cached_files(edition_slug, fetched_names)
    record = _build_record(edition_slug, cfg, sections, source_hash)

    print(f"{edition_slug}: {len(sections)} sections")
    if dry_run:
        return len(sections)

    out_path = OUTPUT_DIR / f"{edition_slug}.json"
    tmp_path = out_path.with_suffix(".tmp")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    logging.info("Wrote %s", out_path)
    return len(sections)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse BCP full liturgical texts (1549, 1559, 1662)")
    parser.add_argument("--dry-run", action="store_true", help="Parse without writing output files")
    parser.add_argument("--force-download", action="store_true", help="Re-download cached pages")
    parser.add_argument("--edition", choices=list(EDITIONS), help="Parse one edition only")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    editions_to_run = [args.edition] if args.edition else list(EDITIONS)
    ok = 0
    for slug in editions_to_run:
        n = parse_edition(slug, dry_run=args.dry_run, force=args.force_download)
        if n > 0:
            ok += 1
        else:
            logging.error("FAILED: %s", slug)

    print(f"Done: {ok}/{len(editions_to_run)} editions succeeded")
    return 0 if ok == len(editions_to_run) else 1


if __name__ == "__main__":
    raise SystemExit(main())
