"""Polite jewishencyclopedia.com article fetcher for JE surrogate pipeline.

Fetches article text and page lists from jewishencyclopedia.com.
Caches results under raw/jewish-encyclopedia/articles/<slug>/.

Polite-crawl contract (as locked in Phase 0 of the JE surrogate project):
  - Normal browser User-Agent
  - Sequential requests with >= DEFAULT_MIN_DELAY_S delay between calls
  - Fetch only the sample articles + their facsimiles (not the whole site)
  - Skip-existing: no re-fetch if cached text.txt and pages.json are present
  - Honor any future Disallow on robots.txt

Non-circularity guard (CRITICAL): this fetcher produces the human diplomatic
transcription used as the measurement reference. Never use IA djvu.txt or
ABBYY GZ output as the reference -- those are engine inputs, not this fetcher.
"""

from __future__ import annotations

import html as _html_module
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.paths import REPO_ROOT  # noqa: E402

JE_BASE_URL = "https://www.jewishencyclopedia.com/articles/{slug}"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "raw" / "jewish-encyclopedia" / "articles"
DEFAULT_MIN_DELAY_S = 3.0
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_last_fetch_time: float = 0.0


def _http_get(url: str, **kwargs: Any) -> Any:
    """HTTP GET with a real browser User-Agent.

    Kept as a named module-level function so tests can monkeypatch it.
    """
    import requests  # type: ignore[import]

    resp = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=30,
        **kwargs,
    )
    resp.raise_for_status()
    return resp


class _ColumnParser(HTMLParser):
    """State-machine parser for the JE.com two-column article layout.

    Body column: class ``yui3-u-17-24`` -- article text.
    Sidebar:     class ``yui3-u-7-24``  -- facsimile page links.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_body: bool = False
        self._body_depth: int = 0
        self._in_sidebar: bool = False
        self._sidebar_depth: int = 0
        self._in_link: bool = False
        self._current_link_href: str = ""
        self._body_parts: list[str] = []
        self._links: list[tuple[str, str]] = []
        self._link_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attr_dict = dict(attrs)
        classes = attr_dict.get("class", "").split()

        if tag == "div":
            if not self._in_body and "yui3-u-17-24" in classes:
                self._in_body = True
                self._body_depth = 1
            elif self._in_body:
                self._body_depth += 1
            if not self._in_sidebar and "yui3-u-7-24" in classes:
                self._in_sidebar = True
                self._sidebar_depth = 1
            elif self._in_sidebar:
                self._sidebar_depth += 1

        if tag == "a" and self._in_sidebar:
            href = _html_module.unescape(attr_dict.get("href", ""))
            self._in_link = True
            self._current_link_href = href
            self._link_text_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            if self._in_body:
                self._body_depth -= 1
                if self._body_depth == 0:
                    self._in_body = False
            if self._in_sidebar:
                self._sidebar_depth -= 1
                if self._sidebar_depth == 0:
                    self._in_sidebar = False
        if tag == "a" and self._in_link:
            link_text = "".join(self._link_text_parts).strip()
            if link_text:
                self._links.append((self._current_link_href, link_text))
            self._in_link = False
            self._current_link_href = ""
            self._link_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_body:
            self._body_parts.append(data)
        if self._in_link:
            self._link_text_parts.append(data)

    def get_body_text(self) -> str:
        raw = "".join(self._body_parts)
        lines = [line.strip() for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)

    def get_links(self) -> list[tuple[str, str]]:
        return list(self._links)


_PAGE_PATTERN = re.compile(r"^V:(\d+)\s+P:(\d+)$")


def extract_article(html_text: str) -> dict:
    """Extract article text and page list from JE.com article HTML.

    Returns a dict with:
      ``text``  -- plain text of the body column (Greek/Hebrew preserved).
      ``pages`` -- list of (volume, page, facsimile_href) tuples.
    """
    parser = _ColumnParser()
    parser.feed(html_text)
    text = parser.get_body_text()
    pages: list[tuple[int, int, str]] = []
    for href, link_text in parser.get_links():
        m = _PAGE_PATTERN.match(link_text.strip())
        if m:
            pages.append((int(m.group(1)), int(m.group(2)), href))
    return {"text": text, "pages": pages}


def fetch_article(
    slug: str,
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    min_delay_s: float = DEFAULT_MIN_DELAY_S,
) -> dict:
    """Fetch one article from JE.com; return cached data if already present.

    On a cache hit (text.txt + pages.json both exist): returns immediately,
    no network call, no delay enforced.

    On a cache miss: enforces ``min_delay_s`` since the previous network call,
    fetches, caches text.txt and pages.json atomically, returns the result.

    Args:
        slug: Article slug as it appears in the URL (e.g. ``1740-apostasy``).
        output_dir: Root cache directory. Article goes under ``output_dir/slug/``.
        min_delay_s: Minimum wall-clock seconds between consecutive network calls.
    """
    global _last_fetch_time
    output_dir = Path(output_dir)
    article_dir = output_dir / slug
    text_path = article_dir / "text.txt"
    pages_path = article_dir / "pages.json"

    if text_path.exists() and pages_path.exists():
        text = text_path.read_text(encoding="utf-8")
        pages_raw = json.loads(pages_path.read_text(encoding="utf-8"))
        pages = [tuple(p) for p in pages_raw]
        return {"slug": slug, "text": text, "pages": pages}

    now = time.monotonic()
    wait = _last_fetch_time + min_delay_s - now
    if wait > 0:
        time.sleep(wait)

    url = JE_BASE_URL.format(slug=slug)
    response = _http_get(url)
    _last_fetch_time = time.monotonic()

    result = extract_article(response.text)

    article_dir.mkdir(parents=True, exist_ok=True)
    tmp_text = text_path.with_suffix(".txt.tmp")
    tmp_pages = pages_path.with_suffix(".json.tmp")
    tmp_text.write_text(result["text"], encoding="utf-8")
    tmp_pages.write_text(
        json.dumps(result["pages"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp_text, text_path)
    os.replace(tmp_pages, pages_path)

    return {"slug": slug, "text": result["text"], "pages": result["pages"]}


def save_manifest(path: Path, manifest: dict) -> None:
    """Write a manifest JSON atomically, UTF-8 without BOM."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def load_manifest(path: Path) -> dict:
    """Read a manifest JSON file."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="+", help="Article slug(s) from the URL path")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY_S)
    args = parser.parse_args()

    results = []
    for slug in args.slugs:
        print(f"  {slug}...", end=" ", flush=True)
        data = fetch_article(slug, output_dir=args.output_dir, min_delay_s=args.min_delay)
        print(f"pages={len(data['pages'])} chars={len(data['text'])}", flush=True)
        results.append({"slug": slug, "pages": data["pages"], "text_len": len(data["text"])})

    manifest = {"schema": "je-article-manifest-v1", "articles": results}
    manifest_path = Path(args.output_dir) / "manifest.json"
    save_manifest(manifest_path, manifest)
    print(f"manifest -> {manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
