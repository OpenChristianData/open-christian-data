"""TDD tests for build/tools/probe_abbyy_confidence.py.

Tests cover:
- probe_gz_confidence: streams a GZ, returns per-leaf confidence data
- download_gz_if_needed: caches GZ locally, skip-existing
"""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from build.tools import probe_abbyy_confidence as pac

ABBYY_NS = "http://www.abbyy.com/FineReader_xml/FineReader6-schema-v1.xml"

# ---------------------------------------------------------------------------
# Minimal ABBYY XML helpers
# ---------------------------------------------------------------------------

def _make_abbyy_doc(pages: list[str]) -> bytes:
    """Build a minimal ABBYY GZ document with the given page XML snippets."""
    header = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<document version="1.0" producer="ABBYY FineReader 11" '
        f'xmlns="{ABBYY_NS}">\n'
    )
    body = "\n".join(pages)
    return (header + body + "\n</document>\n").encode("utf-8")


def _make_page(words: list[tuple[str, int]]) -> str:
    """Minimal <page> with one block, one line, one charParams per word char.

    words: list of (text, confidence) pairs.
    """
    chars = []
    x = 100
    for word_text, conf in words:
        is_first = True
        for ch in word_text:
            word_start = "true" if is_first else "false"
            chars.append(
                f'<charParams l="{x}" t="100" r="{x+10}" b="130" '
                f'charConfidence="{conf}" wordStart="{word_start}">{ch}</charParams>'
            )
            x += 11
            is_first = False
        # space between words
        chars.append(
            f'<charParams l="{x}" t="100" r="{x+5}" b="130" '
            f'charConfidence="255" wordStart="false"> </charParams>'
        )
        x += 6
    chars_xml = "\n".join(chars)
    return (
        '<page width="1000" height="1200">'
        '<block blockType="Text" l="100" t="100" r="900" b="1100">'
        "<text><par>"
        '<line l="100" t="100" r="900" b="130" baseline="125">'
        f"<formatting>{chars_xml}</formatting>"
        "</line></par></text>"
        "</block></page>"
    )


def _make_empty_page() -> str:
    """A page with no text blocks."""
    return '<page width="1000" height="1200"></page>'


def _write_gz(tmp_path: Path, pages: list[str]) -> Path:
    doc = _make_abbyy_doc(pages)
    gz_path = tmp_path / "test_item_abbyy.gz"
    with gzip.open(gz_path, "wb") as fh:
        fh.write(doc)
    return gz_path


# ---------------------------------------------------------------------------
# probe_gz_confidence
# ---------------------------------------------------------------------------

def test_probe_gz_confidence_all_leaves(tmp_path):
    gz = _write_gz(tmp_path, [
        _make_page([("hello", 90), ("world", 100)]),
        _make_page([("foo", 80)]),
        _make_page([("bar", 70), ("baz", 60)]),
    ])
    results = pac.probe_gz_confidence(gz)
    assert len(results) == 3
    leaf_indices = [r["leaf_index"] for r in results]
    assert leaf_indices == [0, 1, 2]


def test_probe_gz_confidence_filters_by_leaf_set(tmp_path):
    gz = _write_gz(tmp_path, [
        _make_page([("hello", 90)]),   # leaf 0
        _make_page([("world", 80)]),   # leaf 1
        _make_page([("foo", 70)]),     # leaf 2
    ])
    results = pac.probe_gz_confidence(gz, leaf_indices={0, 2})
    assert len(results) == 2
    assert results[0]["leaf_index"] == 0
    assert results[1]["leaf_index"] == 2


def test_probe_gz_confidence_empty_page_returns_none_mean(tmp_path):
    gz = _write_gz(tmp_path, [_make_empty_page()])
    results = pac.probe_gz_confidence(gz)
    assert len(results) == 1
    assert results[0]["confidence_mean"] is None
    assert results[0]["word_count"] == 0


def test_probe_gz_confidence_mean_is_arithmetic_mean(tmp_path):
    # Two words: confidences 90 and 100 -> mean 95.0
    gz = _write_gz(tmp_path, [_make_page([("ab", 90), ("cd", 100)])])
    results = pac.probe_gz_confidence(gz)
    assert len(results) == 1
    # "ab" has 2 chars at conf 90, "cd" has 2 chars at conf 100 -> mean of [90,90,100,100]
    assert results[0]["confidence_mean"] == pytest.approx(95.0)


def test_probe_gz_confidence_excludes_sentinel_255(tmp_path):
    # Space chars have charConfidence=255 and should be excluded
    gz = _write_gz(tmp_path, [_make_page([("x", 80)])])
    results = pac.probe_gz_confidence(gz)
    # Only "x" char counted, space excluded
    assert results[0]["confidence_mean"] == pytest.approx(80.0)
    assert results[0]["word_count"] == 1


def test_probe_gz_confidence_result_has_required_keys(tmp_path):
    gz = _write_gz(tmp_path, [_make_page([("test", 92)])])
    results = pac.probe_gz_confidence(gz)
    assert results[0].keys() >= {"leaf_index", "confidence_mean", "word_count"}


# ---------------------------------------------------------------------------
# download_gz_if_needed
# ---------------------------------------------------------------------------

def test_download_gz_skip_existing(tmp_path):
    """If the GZ already exists on disk, no HTTP call is made."""
    gz_path = tmp_path / "myitem_abbyy.gz"
    gz_path.write_bytes(b"dummy")

    calls = []
    def fake_fetch(url, dest, **kwargs):  # noqa: ARG001
        calls.append(url)

    result = pac.download_gz_if_needed("myitem", tmp_path, _fetch_fn=fake_fetch)
    assert result == gz_path
    assert calls == [], "HTTP should not be called when file already exists"


def test_download_gz_writes_to_cache(tmp_path):
    """When GZ absent, fetch is called and path returned."""
    fetched = {}

    def fake_fetch(url, dest, **kwargs):  # noqa: ARG001
        fetched["url"] = url
        fetched["dest"] = dest
        Path(dest).write_bytes(b"fake-gz-data")

    result = pac.download_gz_if_needed("cu31924091768196", tmp_path, _fetch_fn=fake_fetch)
    assert "cu31924091768196" in fetched["url"]
    assert result.exists()
    assert result.name == "cu31924091768196_abbyy.gz"


def test_download_gz_url_includes_item_id():
    """abbyy_gz_url builds the correct IA download URL."""
    url = pac.abbyy_gz_url("cu31924091768196")
    assert "cu31924091768196" in url
    assert url.startswith("https://archive.org/")
    assert url.endswith("_abbyy.gz")


def test_download_gz_url_encodes_custom_filename():
    """abbyy_gz_url percent-encodes spaces and special chars in gz_filename."""
    url = pac.abbyy_gz_url(
        "TheItem",
        gz_filename="My File & Name_abbyy.gz",
    )
    assert " " not in url
    assert "&" not in url
    assert "My%20File" in url or "My+File" in url or "%20" in url
    assert "TheItem" in url
