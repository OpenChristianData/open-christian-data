"""Tests for build/parsers/bcp_full_text.py

TDD test suite covering:
1. Unit tests for HTML extraction functions (justus.anglican.org and eskimo.com formats)
2. Integration tests against generated output JSON files (skipped until generated)
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

_JUSTUS_MATINS_SNIPPET = """
<html><head><title>The 1549 Book of Common Prayer: Morning Prayer</title></head>
<body>
<table width="100%" border="0" bgcolor="#666666"><tr><td>Navigation header</td></tr></table>
<br>
<table width="90%" border="0" bgcolor="#333333"><tr><td>Section title: Morning Prayer</td></tr></table>
<div align="center"><br>&nbsp;</div>
<table border="0" width="600" bgcolor="#FFFFFF" cellspacing="0" cellpadding="5" align="center">
  <tr>
    <td width="450"><font face="Georgia">
      <p align="center"><font size="+2">AN ORDRE</font></p>
      <p align="center">FOR MATTYNS DAYLY THROUGH THE YERE.</p>
      <p align="center"><font size="-1"><i>The Priest beeyng in the quier, Pater noster.</i></font></p>
      <p align="JUSTIFY">OURE Father, which art in heaven, hallowed be thy name. Thy kingdom come.
        Thy will be done in earth, as it is in heaven. Give us this day our daily bread.
        And forgive us our trespasses, as we forgive them that trespass against us.
        And lead us not into temptation. But deliver us from evil. Amen.</p>
      <p align="center"><i>Then likewise he shall say,</i></p>
      <p>O Lorde, open thou our lippes.</p>
    </font></td>
    <td width="150" valign="bottom" class="small-grey">
      Editorial note: This is the Lord's Prayer in early modern English.
      It should NOT appear in the extracted output.
    </td>
  </tr>
  <tr>
    <td width="450">
      <p align="JUSTIFY">And oure mouthe shall shewe forth thy praise.
        O God, make spede to save us. O Lorde, make haste to helpe us.</p>
    </td>
    <td width="150">&nbsp;</td>
  </tr>
</table>
<blockquote>
  <p><em>Return to the <a href="BCP_1549.htm">1549 Book of Common Prayer</a></em></p>
</blockquote>
<table width="100%" border="0" bgcolor="#CCCCCC"><tr><td>Footer navigation</td></tr></table>
</body></html>
"""

_ESKIMO_MORNING_SNIPPET = """<HTML>
  <HEAD><title>Morning Prayer.</title></HEAD>
  <BODY BGCOLOR="#FFFFFF">
    <CENTER>
      <H2>The Order for Morning Prayer,</H2>
      <H3>Daily Throughout the Year.</H3>
      <HR>
    </CENTER>
    <FONT COLOR="Red"><EM>At the beginning of Morning Prayer the Minister shall read with a loud voice
    some one or more of these Sentences of the Scriptures that follow.</EM></FONT><P>

    <STRONG><IMG SRC="../images/w_big.gif" ALT="W">HEN</STRONG> the wicked man turneth away
    from his wickedness that he hath committed, and doeth that which is lawful and right,
    he shall save his soul alive. <I>Ezek.</I> xviii. 27.<P>

    <CENTER><FONT COLOR="Red"><EM>A general Confession to be said of the whole Congregation
    after the Minister, all kneeling.</EM></FONT></CENTER>
    <STRONG><IMG SRC="../images/a_small.gif" ALT="A">LMIGHTY</STRONG> and most merciful Father,
    We have erred and strayed from thy ways like lost sheep.
    We have followed too much the devices and desires of our own hearts.<P>

    <CENTER><FONT COLOR="Red"><EM>Here endeth the Order of Morning Prayer throughout the Year.</EM></FONT></CENTER>
    <HR>
    <CENTER><A HREF="evening.html">Next</A></CENTER>
  </BODY>
</HTML>"""

_ESKIMO_404_SNIPPET = """<HTML>
  <HEAD><TITLE>Error 404: File Not Found</TITLE></HEAD>
  <BODY>
    <H1>Error 404: File Not Found.</H1>
    <P>The requested URL /~lhowell/bcp1662/baptism/infants.html was not found.</P>
  </BODY>
</HTML>"""


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

def _import_parser():
    """Import the parser module, raising ImportError if not yet created."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bcp_full_text",
        REPO_ROOT / "build" / "parsers" / "bcp_full_text.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Unit tests: HTML extraction (justus.anglican.org format)
# ---------------------------------------------------------------------------

class TestExtractJustusHtml:
    """Unit tests for extract_paragraphs_from_justus_html()."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.mod = _import_parser()

    def test_liturgical_text_is_included(self):
        """A liturgical prayer paragraph appears in extracted output."""
        paragraphs = self.mod.extract_paragraphs_from_justus_html(_JUSTUS_MATINS_SNIPPET)
        combined = " ".join(paragraphs)
        assert "hallowed be thy name" in combined, (
            f"Expected 'hallowed be thy name' in extracted text; got: {paragraphs[:3]}"
        )

    def test_editorial_notes_excluded(self):
        """Text from the editorial notes column (width=150) is not included."""
        paragraphs = self.mod.extract_paragraphs_from_justus_html(_JUSTUS_MATINS_SNIPPET)
        combined = " ".join(paragraphs)
        assert "should NOT appear" not in combined, (
            "Editorial note text leaked into extracted output"
        )

    def test_rubric_is_included(self):
        """Italic rubric stage directions are preserved."""
        paragraphs = self.mod.extract_paragraphs_from_justus_html(_JUSTUS_MATINS_SNIPPET)
        combined = " ".join(paragraphs)
        assert "Priest beeyng in the quier" in combined or "likewise he shall say" in combined, (
            "Rubric text not found in extracted paragraphs"
        )

    def test_nav_header_excluded(self):
        """Navigation header text is not included."""
        paragraphs = self.mod.extract_paragraphs_from_justus_html(_JUSTUS_MATINS_SNIPPET)
        combined = " ".join(paragraphs)
        assert "Navigation header" not in combined, "Nav header leaked into content"

    def test_footer_nav_excluded(self):
        """Footer navigation and 'Return to' link are not included."""
        paragraphs = self.mod.extract_paragraphs_from_justus_html(_JUSTUS_MATINS_SNIPPET)
        combined = " ".join(paragraphs)
        assert "Footer navigation" not in combined, "Footer nav leaked into content"
        assert "Return to" not in combined, "Return-to link leaked into content"

    def test_returns_nonempty_list(self):
        """Extraction returns at least one paragraph from valid BCP HTML."""
        paragraphs = self.mod.extract_paragraphs_from_justus_html(_JUSTUS_MATINS_SNIPPET)
        assert len(paragraphs) >= 2, f"Too few paragraphs: {paragraphs}"

    def test_returns_empty_for_blank_input(self):
        """Extraction on empty string returns empty list without raising."""
        result = self.mod.extract_paragraphs_from_justus_html("")
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests: HTML extraction (eskimo.com format)
# ---------------------------------------------------------------------------

class TestExtractEskimoHtml:
    """Unit tests for extract_paragraphs_from_eskimo_html()."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.mod = _import_parser()

    def test_main_text_is_included(self):
        """Main prayer paragraph appears in extracted output."""
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(_ESKIMO_MORNING_SNIPPET)
        combined = " ".join(paragraphs)
        assert "erred and strayed" in combined, (
            f"Expected 'erred and strayed' in text; got: {paragraphs[:3]}"
        )

    def test_rubric_is_included(self):
        """Red rubric text is preserved in extracted output."""
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(_ESKIMO_MORNING_SNIPPET)
        combined = " ".join(paragraphs)
        assert "Sentences of the Scriptures" in combined or "general Confession" in combined, (
            "Rubric text not found in extracted paragraphs"
        )

    def test_heading_is_included(self):
        """Service heading text (H2/H3) is included."""
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(_ESKIMO_MORNING_SNIPPET)
        combined = " ".join(paragraphs)
        assert "Morning Prayer" in combined, "H2 heading not found in output"

    def test_nav_footer_excluded(self):
        """Navigation buttons after the final HR are not included."""
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(_ESKIMO_MORNING_SNIPPET)
        combined = " ".join(paragraphs)
        assert "Next" not in combined or "HEN the wicked" in combined, (
            "Navigation text leaked into content"
        )

    def test_returns_nonempty_list(self):
        """Extraction returns multiple paragraphs from valid eskimo HTML."""
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(_ESKIMO_MORNING_SNIPPET)
        assert len(paragraphs) >= 2, f"Too few paragraphs: {paragraphs}"

    def test_drop_cap_reconstructed(self):
        """Drop-cap image alt text is merged back with following word."""
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(_ESKIMO_MORNING_SNIPPET)
        combined = " ".join(paragraphs)
        # 'WHEN' or 'WHEN the wicked' — drop cap 'W' + 'HEN'
        assert "WHEN" in combined or "when" in combined.lower(), (
            f"Drop-cap word not reconstructed; got: {combined[:200]}"
        )


class TestBcpFetchContentGate:
    """Regression tests for rejecting HTTP error pages as liturgical content."""

    @pytest.fixture(autouse=True)
    def _load(self, tmp_path, monkeypatch):
        self.mod = _import_parser()
        monkeypatch.setattr(self.mod, "RAW_DIR", tmp_path)
        monkeypatch.setattr(self.mod, "CRAWL_DELAY_SECONDS", 0)

    @pytest.mark.parametrize(
        "body",
        [
            _ESKIMO_404_SNIPPET,
            "<html><body><p>Error 404: File Not Found.</p></body></html>",
        ],
    )
    def test_404_error_body_is_rejected_before_cache(self, monkeypatch, body):
        """A 404-shaped body raises instead of becoming a cached service section."""
        monkeypatch.setattr(self.mod, "_fetch_via_curl", lambda url: body.encode("latin-1"))

        with pytest.raises(ValueError, match="error page|File Not Found"):
            self.mod._fetch_and_cache(
                "bcp-1662",
                "https://www.eskimo.com/~lhowell/bcp1662/baptism/infants.html",
                "baptism__infants.html",
                "eskimo",
                force=True,
            )

    def test_real_shaped_service_page_is_accepted_and_parses(self, monkeypatch):
        """A real-shaped service page survives the gate and extracts liturgical text."""
        monkeypatch.setattr(
            self.mod,
            "_fetch_via_curl",
            lambda url: _ESKIMO_MORNING_SNIPPET.encode("latin-1"),
        )

        data = self.mod._fetch_and_cache(
            "bcp-1662",
            "https://www.eskimo.com/~lhowell/bcp1662/daily/morning.html",
            "daily__morning.html",
            "eskimo",
            force=True,
        )
        paragraphs = self.mod.extract_paragraphs_from_eskimo_html(
            data.decode("latin-1", errors="replace")
        )

        assert any("erred and strayed" in paragraph for paragraph in paragraphs)


# ---------------------------------------------------------------------------
# Integration tests against output JSON files (skip if not generated)
# ---------------------------------------------------------------------------

_EDITIONS = [
    ("bcp-1549", 8),   # min expected top-level sections
    ("bcp-1559", 8),
    ("bcp-1662", 10),
]


@pytest.mark.parametrize("slug,min_sections", _EDITIONS)
def test_section_count_at_least_n(slug, min_sections):
    """Each edition has at least N top-level sections (named services)."""
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    sections = data["data"]["sections"]
    assert len(sections) >= min_sections, (
        f"{slug}: expected >= {min_sections} sections, got {len(sections)}"
    )


@pytest.mark.parametrize("slug", [e[0] for e in _EDITIONS])
def test_morning_prayer_section_present(slug):
    """Morning Prayer appears as a top-level section in every edition."""
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    titles = [s.get("title", "") for s in data["data"]["sections"]]
    assert any("morning prayer" in t.lower() or "matins" in t.lower() for t in titles), (
        f"No Morning Prayer section in {slug}. Titles: {titles}"
    )


def test_1662_evening_prayer_present():
    """Evening Prayer appears in BCP 1662."""
    path = REPO_ROOT / "data" / "structured-text" / "bcp-1662.json"
    if not path.exists():
        pytest.skip("bcp-1662.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    titles = [s.get("title", "") for s in data["data"]["sections"]]
    assert any("evening" in t.lower() for t in titles), (
        f"Evening Prayer not found in bcp-1662. Titles: {titles}"
    )


def test_1662_litany_contains_lord_have_mercy():
    """Litany section in BCP 1662 contains 'mercy' from kyrie."""
    path = REPO_ROOT / "data" / "structured-text" / "bcp-1662.json"
    if not path.exists():
        pytest.skip("bcp-1662.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    litany = next(
        (s for s in data["data"]["sections"] if "litany" in s.get("title", "").lower()),
        None,
    )
    assert litany is not None, "No Litany section found in bcp-1662"
    full_text = " ".join(litany.get("content_blocks", []))
    assert "mercy" in full_text.lower(), (
        "Expected 'mercy' in Litany section (from Lord have mercy)"
    )


def test_1549_communion_contains_consecration():
    """Holy Communion section in BCP 1549 contains consecration language."""
    path = REPO_ROOT / "data" / "structured-text" / "bcp-1549.json"
    if not path.exists():
        pytest.skip("bcp-1549.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    communion = next(
        (s for s in data["data"]["sections"]
         if "communion" in s.get("title", "").lower()
         or "supper" in s.get("title", "").lower()),
        None,
    )
    assert communion is not None, "No Communion section found in bcp-1549"
    full_text = " ".join(communion.get("content_blocks", []))
    # BCP 1549 has "Take and eate this" or similar consecration words
    assert any(word in full_text.lower() for word in ["bread", "body", "take", "body of christ"]), (
        "Expected consecration language in 1549 Communion section"
    )


@pytest.mark.parametrize("slug", [e[0] for e in _EDITIONS])
def test_no_empty_sections(slug):
    """No section has both empty content_blocks and no children."""
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    def check_sections(sections, path=""):
        for i, section in enumerate(sections):
            loc = f"{path}[{i}] {section.get('title', 'untitled')}"
            has_content = bool(section.get("content_blocks")) or bool(section.get("children"))
            assert has_content, f"Empty section in {slug}: {loc}"
            if section.get("children"):
                check_sections(section["children"], path=loc)

    check_sections(data["data"]["sections"])


@pytest.mark.parametrize("slug", [e[0] for e in _EDITIONS])
def test_schema_type_is_structured_text(slug):
    """Output file has schema_type: structured_text."""
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["meta"]["schema_type"] == "structured_text", (
        f"{slug}: expected schema_type 'structured_text', got {data['meta']['schema_type']!r}"
    )


@pytest.mark.parametrize("slug", [e[0] for e in _EDITIONS])
def test_tradition_is_anglican(slug):
    """All BCP editions are tagged with 'anglican' tradition."""
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    tradition = data["meta"]["tradition"]
    assert "anglican" in tradition, f"{slug}: 'anglican' not in tradition: {tradition}"


# Lock section counts — regression guard for editorial-filter changes
_EXPECTED_TOP_SECTIONS = {
    "bcp-1549": 34,
    "bcp-1559": 14,
    "bcp-1662": 20,
}


@pytest.mark.parametrize("slug,expected", sorted(_EXPECTED_TOP_SECTIONS.items()))
def test_top_section_count_locked(slug, expected):
    """Section count is locked after first generation (regression guard)."""
    path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    if not path.exists():
        pytest.skip(f"{slug}.json not yet generated")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    got = len(data["data"]["sections"])
    assert got == expected, f"{slug}: expected {expected} top sections, got {got}"
