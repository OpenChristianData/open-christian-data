"""build/parsers/schleitheim_confession.py

Parse the Schleitheim Confession (1527) from anabaptists.org and emit a
doctrinal_document JSON conforming to schemas/v1/doctrinal_document.schema.json.

Usage:
    py -3 build/parsers/schleitheim_confession.py
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap REPO_ROOT into sys.path
# ---------------------------------------------------------------------------

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SOURCE_URL = "https://www.anabaptists.org/history/the-schleitheim-confession.html"
OUTPUT_PATH = REPO_ROOT / "data" / "doctrinal-documents" / "schleitheim-confession-1527.json"
RAW_HTML_PATH = REPO_ROOT / "raw" / "anabaptists.org" / "schleitheim-confession-1527.html"
SCRIPT_VERSION = "build/parsers/schleitheim_confession.py@v1.1.0"

DOCUMENT_CONFIG = {
    "document_id": "schleitheim-confession-1527",
    "document_kind": "confession",
    "title": "The Schleitheim Confession",
    "author": "Swiss Brethren",
    "original_publication_year": 1527,
    "language": "en",
    "original_language": "de",
    "tradition": ["anabaptist", "mennonite"],
    "tradition_notes": (
        "Adopted at the Schleitheim conference on February 24, 1527. "
        "Drafted by Michael Sattler, it became the foundational confessional document "
        "of the Swiss Brethren and subsequently shaped Mennonite and Amish theology."
    ),
    "era": "reformation",
    "license": "public-domain",
    "completeness": "full",
    "schema_version": "2.1.0",
}

# Matches green-highlighted article headers: <font color="#008000"><b>...</b></font>
_HEADER_RE = re.compile(
    r'<font[^>]+#008000[^>]*>\s*<b>(.*?)</b>\s*</font>',
    re.DOTALL | re.IGNORECASE,
)

# Extracts Roman numeral and title from a header string like "I.  Observe concerning baptism:"
_ARTICLE_NUM_RE = re.compile(r'^([IVXLCDM]+)\.\s+(.*?)[\s:]*$', re.DOTALL | re.IGNORECASE)

_DOCUMENT_TERMINUS_RE = re.compile(
    r"The Seven Articles of Schleitheim\s*<br\s*/?>\s*"
    r"Canton Schaffhausen, Switzerland,\s*<br\s*/?>\s*"
    r"February 24, 1527",
    re.IGNORECASE,
)

# Matches any HTML tag for stripping
_TAG_RE = re.compile(r'<[^>]+>')


def _strip_tags(text: str) -> str:
    """Remove all HTML tags and normalize whitespace (including source line breaks)."""
    text = _TAG_RE.sub(' ', text)
    text = re.sub(r'[\s]+', ' ', text)  # collapse all whitespace including \n from HTML source wrapping
    return text.strip()


def _clean_paragraph(raw: str) -> str:
    """Strip tags and clean a paragraph-level text block."""
    return _strip_tags(raw).strip()


def extract_articles(html_bytes: bytes) -> list[dict]:
    """Parse Schleitheim Confession HTML and return 7 article dicts.

    Each dict has:
      number  -- Roman numeral string (e.g. "I", "II")
      title   -- article heading (e.g. "Observe concerning baptism")
      content -- full article body text, paragraphs joined with double newline
    """
    html = html_bytes.decode("utf-8", errors="replace")

    # Split on each green-header marker; first chunk is the preamble
    parts = _HEADER_RE.split(html)
    # parts: [preamble, header1_text, body1_text, header2_text, body2_text, ...]
    # Odd indices are header strings, even indices > 0 are body strings

    articles = []
    i = 1  # skip preamble at index 0
    while i < len(parts) - 1:
        header_raw = parts[i].strip()
        body_raw = parts[i + 1] if i + 1 < len(parts) else ""

        m = _ARTICLE_NUM_RE.match(header_raw.replace("\n", " "))
        if not m:
            i += 2
            continue

        number = m.group(1).upper()
        title_raw = m.group(2).strip().rstrip(":")
        title = re.sub(r'\s+', ' ', title_raw).strip()

        # The source's own closing imprint is the confession terminus. It
        # precedes a typed-by note and unrelated site chrome, so this is a
        # content-based boundary rather than a site-markup heuristic.
        if number == "VII":
            terminus = _DOCUMENT_TERMINUS_RE.search(body_raw)
            if terminus is None:
                raise RuntimeError(
                    "Article VII is missing the Schleitheim confession closing imprint."
                )
            body_raw = body_raw[: terminus.end()]

        # Clean body: split on <p> or <P> paragraph separators, strip tags, drop empties
        body_paras = re.split(r'<[Pp]\s*>', body_raw)
        body_paras = [_clean_paragraph(p) for p in body_paras]
        body_paras = [p for p in body_paras if p]
        content = "\n\n".join(body_paras)

        articles.append({"number": number, "title": title, "content": content})
        i += 2

    return articles


def build_output(articles: list[dict], source_hash: str, download_date: str) -> dict:
    """Assemble the doctrinal_document JSON envelope."""
    cfg = DOCUMENT_CONFIG
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    units = [
        {
            "unit_type": "article",
            "number": a["number"],
            "title": a["title"],
            "content": a["content"],
        }
        for a in articles
    ]

    return {
        "meta": {
            "id": cfg["document_id"],
            "title": cfg["title"],
            "author": cfg["author"],
            "author_birth_year": None,
            "author_death_year": None,
            "contributors": [],
            "original_publication_year": cfg["original_publication_year"],
            "language": cfg["language"],
            "tradition": cfg["tradition"],
            "tradition_notes": cfg["tradition_notes"],
            "license": cfg["license"],
            "schema_type": "doctrinal_document",
            "schema_version": cfg["schema_version"],
            "completeness": cfg["completeness"],
            "provenance": {
                "source_url": SOURCE_URL,
                "source_format": "HTML",
                "source_edition": (
                    "Rod and Staff Publishers, Inc., Crockett, KY (Sixth Printing, 1985). "
                    "English translation hosted at anabaptists.org."
                ),
                "download_date": download_date,
                "source_hash": source_hash,
                "processing_method": "automated",
                "processing_script_version": SCRIPT_VERSION,
                "processing_date": today,
                "notes": None,
            },
        },
        "data": {
            "document_id": cfg["document_id"],
            "document_kind": cfg["document_kind"],
            "units": units,
        },
    }


def main() -> None:
    if not RAW_HTML_PATH.exists():
        raise FileNotFoundError(
            f"Missing cached raw witness: {RAW_HTML_PATH.relative_to(REPO_ROOT)}"
        )
    print(f"Reading cached witness {RAW_HTML_PATH.relative_to(REPO_ROOT)} ...")
    html_bytes = RAW_HTML_PATH.read_bytes()
    source_hash = "sha256:" + hashlib.sha256(html_bytes).hexdigest()
    download_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    articles = extract_articles(html_bytes)
    if len(articles) != 7:
        raise RuntimeError(
            f"Expected 7 articles, got {len(articles)}. "
            "Check HTML structure at the source URL."
        )

    for i, art in enumerate(articles, 1):
        word_count = len(art["content"].split())
        print(f"  Article {art['number']}: {art['title']!r} ({word_count} words)")

    output = build_output(articles, source_hash=source_hash, download_date=download_date)

    total_words = sum(len(a["content"].split()) for a in articles)
    print(f"\nTotal: {len(articles)} articles, {total_words} words")
    print(f"Source hash: {source_hash}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUTPUT_PATH)
    print(f"Written: {OUTPUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
