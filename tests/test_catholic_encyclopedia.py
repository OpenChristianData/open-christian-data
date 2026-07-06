"""
Tests for the Catholic Encyclopedia parser (build/parsers/catholic_encyclopedia.py).

Fixtures live at tests/fixtures/catholic_encyclopedia/ and model the real
newadvent.org/cathen/ article HTML structure.
"""

from pathlib import Path

import pytest

from build.parsers.catholic_encyclopedia import (
    article_url,
    build_entry,
    build_meta,
    parse_article_html,
    slugify,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "catholic_encyclopedia"


# ---------------------------------------------------------------------------
# URL pattern
# ---------------------------------------------------------------------------

def test_article_url_vol1_page1():
    assert article_url(1, 1) == "https://www.newadvent.org/cathen/01001a.htm"


def test_article_url_vol1_page48():
    assert article_url(1, 48, "a") == "https://www.newadvent.org/cathen/01048a.htm"


def test_article_url_vol2_page100_suffix_b():
    assert article_url(2, 100, "b") == "https://www.newadvent.org/cathen/02100b.htm"


def test_article_url_vol15_page999():
    assert article_url(15, 999, "a") == "https://www.newadvent.org/cathen/15999a.htm"


# ---------------------------------------------------------------------------
# HTML parsing — 5 known fixtures
# ---------------------------------------------------------------------------

class TestParseAachen:
    def setup_method(self):
        html = (FIXTURE_DIR / "cathen_01001a.html").read_text(encoding="utf-8")
        self.result = parse_article_html(html)

    def test_not_none(self):
        assert self.result is not None

    def test_title(self):
        assert self.result["title"] == "Aachen"

    def test_contributor_contains_schaaf(self):
        assert "Schaaf" in self.result["contributor"]

    def test_body_contains_prussian_valley(self):
        body = " ".join(self.result["body_blocks"])
        assert "Prussian valley" in body


class TestParseAbraham:
    def setup_method(self):
        html = (FIXTURE_DIR / "cathen_01048a.html").read_text(encoding="utf-8")
        self.result = parse_article_html(html)

    def test_title(self):
        assert self.result["title"] == "Abraham"

    def test_contributor_contains_arendzen(self):
        assert "Arendzen" in self.result["contributor"]

    def test_body_contains_patriarch(self):
        body = " ".join(self.result["body_blocks"])
        assert "patriarch" in body


class TestParseAbsolution:
    def setup_method(self):
        html = (FIXTURE_DIR / "cathen_01100a.html").read_text(encoding="utf-8")
        self.result = parse_article_html(html)

    def test_title(self):
        assert self.result["title"] == "Absolution"

    def test_contributor_contains_tanquerey(self):
        assert "Tanquerey" in self.result["contributor"]

    def test_body_contains_sacrament_of_penance(self):
        body = " ".join(self.result["body_blocks"])
        assert "sacrament of penance" in body


class TestParseAcolyte:
    def setup_method(self):
        html = (FIXTURE_DIR / "cathen_01150a.html").read_text(encoding="utf-8")
        self.result = parse_article_html(html)

    def test_title(self):
        assert self.result["title"] == "Acolyte"

    def test_contributor_contains_thurston(self):
        assert "Thurston" in self.result["contributor"]

    def test_body_contains_minor_order(self):
        body = " ".join(self.result["body_blocks"])
        assert "minor order" in body


class TestParseAdvocate:
    def setup_method(self):
        html = (FIXTURE_DIR / "cathen_01200a.html").read_text(encoding="utf-8")
        self.result = parse_article_html(html)

    def test_title(self):
        assert self.result["title"] == "Advocate"

    def test_contributor_contains_healy(self):
        assert "Healy" in self.result["contributor"]

    def test_body_contains_latin_advocatus(self):
        body = " ".join(self.result["body_blocks"])
        assert "Latin advocatus" in body


# ---------------------------------------------------------------------------
# Body quality: no empty body, no empty blocks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "cathen_01001a.html",
    "cathen_01048a.html",
    "cathen_01100a.html",
    "cathen_01150a.html",
    "cathen_01200a.html",
])
def test_body_blocks_nonempty(filename):
    html = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
    result = parse_article_html(html)
    assert result is not None
    assert len(result["body_blocks"]) > 0
    for block in result["body_blocks"]:
        assert block.strip(), f"Empty block found in {filename}"


# ---------------------------------------------------------------------------
# Donation paragraph excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "cathen_01001a.html",
    "cathen_01048a.html",
])
def test_donation_paragraph_excluded(filename):
    html = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
    result = parse_article_html(html)
    body = " ".join(result["body_blocks"])
    assert "Please help support" not in body
    assert "gumroad" not in body


# ---------------------------------------------------------------------------
# pub div content excluded
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    "cathen_01001a.html",
    "cathen_01048a.html",
])
def test_pub_div_excluded_from_body(filename):
    html = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
    result = parse_article_html(html)
    body = " ".join(result["body_blocks"])
    assert "MLA citation" not in body
    assert "transcribed for New Advent" not in body


# ---------------------------------------------------------------------------
# Missing container returns None
# ---------------------------------------------------------------------------

def test_parse_returns_none_for_missing_container():
    html = "<html><body><p>No springfield2 div here.</p></body></html>"
    assert parse_article_html(html) is None


def test_parse_returns_none_for_missing_h1():
    html = '<html><body><div id="springfield2"><p>No h1 here.</p></div></body></html>'
    assert parse_article_html(html) is None


def test_slugify_transliterates_ligature_at_start():
    assert slugify("Æons") == "aeons"
    assert slugify("Æsthetics") == "aesthetics"


def test_parse_ignores_generic_in_prose_internal_article_links():
    html = """
    <html><body><div id="springfield2">
      <h1>Aachen</h1>
      <p>The <a href="01234a.htm">French</a> and
      <a href="/cathen/05678b.htm">Prussian</a> governments discussed
      <a href="07890a.htm">Catholics</a> in the region.</p>
      <div class="pub"></div>
    </div></body></html>
    """
    result = parse_article_html(html)
    assert result is not None
    assert result["related_terms"] == []


def test_parse_extracts_related_terms_from_see_also_hyperlinks():
    html = """
    <html><body><div id="springfield2">
      <h1>Angels</h1>
      <p>See also <a href="01234a.htm">Archangels</a> and
      <a href="/cathen/05678b.htm">Demonology</a>.</p>
      <div class="pub"></div>
    </div></body></html>
    """
    result = parse_article_html(html)
    assert result is not None
    assert result["related_terms"] == ["Archangels", "Demonology"]


def test_parse_extracts_related_terms_from_see_prose_pattern():
    html = """
    <html><body><div id="springfield2">
      <h1>Angels</h1>
      <p>See Angelology.</p>
      <div class="pub"></div>
    </div></body></html>
    """
    result = parse_article_html(html)
    assert result is not None
    assert result["related_terms"] == ["Angelology"]


def test_build_entry_extracts_scripture_references_from_body():
    article = {
        "title": "Test",
        "contributor": "",
        "body_blocks": ["The article cites Genesis 1:1 and John 3:16."],
        "related_terms": [],
    }
    entry = build_entry(article, set())
    assert entry["scripture_references"] == [
        {"raw": "Genesis 1:1", "osis": ["Gen.1.1"]},
        {"raw": "John 3:16", "osis": ["John.3.16"]},
    ]


def test_build_entry_uses_related_terms_from_article():
    article = {
        "title": "Test",
        "contributor": "",
        "body_blocks": ["See also Archangels."],
        "related_terms": ["Archangels"],
    }
    entry = build_entry(article, set())
    assert entry["related_terms"] == ["Archangels"]


def test_ce_meta_notes_mark_apparatus_extraction_status():
    meta = build_meta(1, 1, "sha256:" + "0" * 64, [], apparatus_stats={
        "scripture_populated": 1,
        "related_populated": 0,
        "entry_count": 1,
    })
    notes = meta["provenance"]["notes"]
    assert "scripture_references extracted" in notes
    assert "related_terms extracted from explicit See/See also cross-references" in notes
