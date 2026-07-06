"""Tests for build/tools/fetch_je_articles.py.

Uses local HTML fixtures to avoid live network calls.
"""

from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

import pytest

# Import the module under test. This import will fail until the module exists,
# giving us the RED we need.
from build.tools.fetch_je_articles import (
    extract_article,
    fetch_article,
    load_manifest,
    save_manifest,
)

# ---------------------------------------------------------------------------
# HTML fixtures
# ---------------------------------------------------------------------------

_ARTICLE_HTML_MINIMAL = textwrap.dedent("""\
    <html>
    <body>
    <div class="yui3-u-17-24">
      <p>APOSTASY (Heb. <em>mered</em>). From the Greek.</p>
      <p>A second paragraph of body text.</p>
    </div>
    <div class="yui3-u-7-24">
      <a href="/facsimile/view?aid=1740-apostasy&amp;volume=2&amp;page=38">V:2 P:38</a>
      <a href="/facsimile/view?aid=1740-apostasy&amp;volume=2&amp;page=39">V:2 P:39</a>
    </div>
    </body>
    </html>
""")

_ARTICLE_HTML_GREEK = textwrap.dedent("""\
    <html>
    <body>
    <div class="yui3-u-17-24">
      <p>APOCRYPHA (from αποκρύπτω, to hide away).</p>
      <p>Transliteration: ḳolām, ḧaseṣdīm.</p>
    </div>
    <div class="yui3-u-7-24">
      <a href="/facsimile/view?aid=1600-apocrypha&amp;volume=2&amp;page=10">V:2 P:10</a>
    </div>
    </body>
    </html>
""")

_ARTICLE_HTML_NO_PAGES = textwrap.dedent("""\
    <html>
    <body>
    <div class="yui3-u-17-24">
      <p>Short article body.</p>
    </div>
    <div class="yui3-u-7-24">
      <p>No facsimile links here.</p>
    </div>
    </body>
    </html>
""")


# ---------------------------------------------------------------------------
# extract_article: text and page-list parsing
# ---------------------------------------------------------------------------


def test_extract_article_returns_body_text():
    result = extract_article(_ARTICLE_HTML_MINIMAL)
    assert "APOSTASY" in result["text"]
    assert "A second paragraph" in result["text"]


def test_extract_article_strips_html_tags():
    result = extract_article(_ARTICLE_HTML_MINIMAL)
    # <em> tags stripped, inner text preserved
    assert "<em>" not in result["text"]
    assert "mered" in result["text"]


def test_extract_article_preserves_greek_and_transliteration():
    result = extract_article(_ARTICLE_HTML_GREEK)
    # Greek codepoints preserved
    assert "αποκρύπτω" in result["text"]
    # Transliteration diacritics preserved
    assert "ḳ" in result["text"]  # k with dot below
    assert "ḧ" in result["text"]  # h with dot below


def test_extract_article_parses_page_list():
    result = extract_article(_ARTICLE_HTML_MINIMAL)
    pages = result["pages"]
    assert len(pages) == 2
    assert pages[0] == (2, 38, "/facsimile/view?aid=1740-apostasy&volume=2&page=38")
    assert pages[1] == (2, 39, "/facsimile/view?aid=1740-apostasy&volume=2&page=39")


def test_extract_article_single_page():
    result = extract_article(_ARTICLE_HTML_GREEK)
    assert result["pages"] == [(2, 10, "/facsimile/view?aid=1600-apocrypha&volume=2&page=10")]


def test_extract_article_empty_page_list():
    result = extract_article(_ARTICLE_HTML_NO_PAGES)
    assert result["pages"] == []


# ---------------------------------------------------------------------------
# fetch_article: caching and skip-existing
# ---------------------------------------------------------------------------


def test_fetch_article_writes_text_and_pages(tmp_path, monkeypatch):
    """fetch_article caches text and page list to disk on first call."""
    calls = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, _ARTICLE_HTML_MINIMAL)

    monkeypatch.setattr("build.tools.fetch_je_articles._http_get", _fake_get)

    result = fetch_article(
        "1740-apostasy",
        output_dir=tmp_path / "articles",
        min_delay_s=0,
    )

    assert result["slug"] == "1740-apostasy"
    assert len(result["pages"]) == 2
    assert "APOSTASY" in result["text"]
    assert (tmp_path / "articles" / "1740-apostasy" / "text.txt").exists()
    assert (tmp_path / "articles" / "1740-apostasy" / "pages.json").exists()
    assert len(calls) == 1


def test_fetch_article_skips_existing(tmp_path, monkeypatch):
    """fetch_article does not issue a network call when cached data exists."""
    calls = []

    def _fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, _ARTICLE_HTML_MINIMAL)

    monkeypatch.setattr("build.tools.fetch_je_articles._http_get", _fake_get)

    out = tmp_path / "articles"
    fetch_article("1740-apostasy", output_dir=out, min_delay_s=0)
    fetch_article("1740-apostasy", output_dir=out, min_delay_s=0)

    # Second call must not hit the network.
    assert len(calls) == 1


def test_fetch_article_respects_min_delay(tmp_path, monkeypatch):
    """fetch_article waits at least min_delay_s between consecutive calls."""
    times = []

    def _fake_get(url, **kwargs):
        times.append(time.monotonic())
        return _FakeResponse(200, _ARTICLE_HTML_MINIMAL)

    monkeypatch.setattr("build.tools.fetch_je_articles._http_get", _fake_get)

    out = tmp_path / "articles"
    min_delay = 0.05  # 50ms in tests; real usage is >=3s
    fetch_article("1740-apostasy", output_dir=out, min_delay_s=min_delay)
    fetch_article(
        "1741-apostasy-alt", output_dir=out, min_delay_s=min_delay
    )

    assert len(times) == 2
    assert times[1] - times[0] >= min_delay


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def test_save_and_load_manifest_roundtrip(tmp_path):
    manifest = {
        "schema": "je-article-manifest-v1",
        "articles": [
            {"slug": "1740-apostasy", "pages": [[2, 38, "/facsimile/..."]]},
        ],
    }
    path = tmp_path / "manifest.json"
    save_manifest(path, manifest)
    loaded = load_manifest(path)
    assert loaded["articles"][0]["slug"] == "1740-apostasy"


def test_save_manifest_is_utf8_clean(tmp_path):
    manifest = {"text_sample": "αḳḧ"}
    path = tmp_path / "manifest.json"
    save_manifest(path, manifest)
    raw = path.read_bytes()
    assert b"\xef\xbb\xbf" not in raw  # no BOM
    loaded = json.loads(raw.decode("utf-8"))
    assert loaded["text_sample"] == "αḳḧ"


# ---------------------------------------------------------------------------
# Helper stubs
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self._text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    @property
    def text(self) -> str:
        return self._text
