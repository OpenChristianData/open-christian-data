"""test_gutenberg_anglican.py
Unit tests for gutenberg_anglican.py pure functions.

Covers the key invariants for the T6-4 Anglican classics parser:
  - strip_ccel_header: only scans first 30 lines (not whole file)
  - gather_paragraphs: CCEL separator lines (____) are skipped
  - strip_pg_contributors: removes "Produced by" block, returns contributor dicts
  - _DONNE_STATION_RE / _DONNE_STATION_TITLED_RE: station heading detection
  - _DONNE_SUBSECTION_RE: MEDITATION/EXPOSTULATION/PRAYER sub-section headings
  - _TAYLOR_CHAPTER_RE: optional trailing period (Holy Living vs Holy Dying)
  - _NEWMAN_CHAPTER_RE / _newman_is_toc_chapter: excludes TOC chapter entries
  - _NEWMAN_NOTE_RE: case-sensitive (matches NOTE A. body headings, not TOC)
  - _andrewes_normalize: strips [n] footnotes and trailing colons
  - _is_andrewes_heading: normalized heading detection
  - _andrewes_slug: normalized slug lookup

Integration tests (skipped if raw source files are not present):
  - parse_donne_devotions: 23 stations
  - parse_newman_apologia: 13 sections
  - parse_taylor (holy-living): 5 sections
  - parse_taylor (holy-dying): 6 sections
  - parse_andrewes_prayers: 14 prayer records

Added 2026-04-24 for T6-4.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.gutenberg_anglican import (  # noqa: E402
    strip_pg_wrapper,
    strip_ccel_header,
    strip_pg_contributors,
    gather_paragraphs,
    parse_donne_devotions,
    parse_newman_apologia,
    parse_taylor,
    parse_andrewes_prayers,
    RAW_PG_DIR,
    RAW_CCEL_DIR,
    _DONNE_STATION_RE,
    _DONNE_STATION_TITLED_RE,
    _DONNE_SUBSECTION_RE,
    _TAYLOR_CHAPTER_RE,
    _TAYLOR_SECTION_RE,
    _NEWMAN_CHAPTER_RE,
    _NEWMAN_NOTE_RE,
    _newman_is_toc_chapter,
    _andrewes_normalize,
    _is_andrewes_heading,
    _andrewes_slug,
)


# ---------------------------------------------------------------------------
# strip_pg_wrapper
# ---------------------------------------------------------------------------

def test_strip_pg_wrapper_extracts_body():
    text = (
        "Preamble\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK DEVOTIONS ***\n"
        "Body text\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK DEVOTIONS ***\n"
        "Postamble\n"
    )
    body = strip_pg_wrapper(text)
    assert "Body text" in body
    assert "Preamble" not in "\n".join(body)
    assert "Postamble" not in "\n".join(body)


def test_strip_pg_wrapper_raises_if_no_markers():
    import pytest
    with pytest.raises(ValueError):
        strip_pg_wrapper("No markers here.")


# ---------------------------------------------------------------------------
# strip_ccel_header -- only inspects first 30 lines, not the whole file
# ---------------------------------------------------------------------------

def test_strip_ccel_header_removes_metadata():
    lines = [
        "     __________________________________________________________________",
        "",
        "           Title: Holy Living",
        "      Creator(s): Taylor, Jeremy (1613-1667)",
        "     __________________________________________________________________",
        "",
        "THE",
    ]
    body = strip_ccel_header(lines)
    assert body[0] == "THE"
    assert "Creator(s)" not in "\n".join(body)


def test_strip_ccel_header_ignores_late_separators():
    """Separators after line 30 must not be used as the strip point."""
    lines = [
        "     _______________",  # header sep at line 0
        "Title: Test",
        "     _______________",  # header sep at line 2
        "",
        "Content line 1",
        "Content line 2",
    ] + ["More content"] * 50 + [
        "     _______________",  # separator deep in the document (line >30)
        "Final content",
    ]
    body = strip_ccel_header(lines)
    # Must NOT strip to just ["Final content"]
    assert "Content line 1" in body
    assert "Content line 2" in body
    assert "More content" in body


def test_strip_ccel_header_no_separator_returns_all():
    lines = ["Content A", "Content B", "Content C"]
    body = strip_ccel_header(lines)
    assert body == lines


# ---------------------------------------------------------------------------
# gather_paragraphs -- CCEL separator lines (____) are treated as blank lines
# ---------------------------------------------------------------------------

def test_gather_paragraphs_skips_separator_lines():
    lines = [
        "Paragraph one.",
        "     __________________________________________________________________",
        "Paragraph two.",
    ]
    paras = gather_paragraphs(lines, 0, len(lines))
    assert len(paras) == 2
    assert all("_" not in p for p in paras)


def test_gather_paragraphs_collects_blocks():
    lines = ["Line A.", "Line B.", "", "Line C."]
    paras = gather_paragraphs(lines, 0, len(lines))
    assert len(paras) == 2
    assert "Line A." in paras[0]
    assert "Line B." in paras[0]
    assert paras[1] == "Line C."


# ---------------------------------------------------------------------------
# Donne: station and sub-section heading regexes
# ---------------------------------------------------------------------------

def test_donne_station_re_matches_lone_roman():
    assert _DONNE_STATION_RE.match("I")
    assert _DONNE_STATION_RE.match("IV")
    assert _DONNE_STATION_RE.match("XXIII")


def test_donne_station_re_rejects_with_extra_text():
    assert _DONNE_STATION_RE.match("I. MEDITATION.") is None
    assert _DONNE_STATION_RE.match("II. POST ACTIO LAESA.") is None


def test_donne_station_titled_re_matches_roman_plus_text():
    assert _DONNE_STATION_TITLED_RE.match("II. POST ACTIO LAESA.")
    assert _DONNE_STATION_TITLED_RE.match("XII. ------------------ Spirante columba")
    assert _DONNE_STATION_TITLED_RE.match("XXIII. METUSQUE, RELABI.")


def test_donne_station_titled_re_captures_groups():
    m = _DONNE_STATION_TITLED_RE.match("XVII. NUNC LENTO SONITU DICUNT, MORIERIS.")
    assert m is not None
    assert m.group(1) == "XVII"
    assert "NUNC LENTO" in m.group(2)


def test_donne_subsection_re_matches_all_three():
    assert _DONNE_SUBSECTION_RE.match("I. MEDITATION.")
    assert _DONNE_SUBSECTION_RE.match("I. EXPOSTULATION.")
    assert _DONNE_SUBSECTION_RE.match("I. PRAYER.")
    assert _DONNE_SUBSECTION_RE.match("XVII. MEDITATION.")
    assert _DONNE_SUBSECTION_RE.match("XVII. EXPOSTULATION.")
    assert _DONNE_SUBSECTION_RE.match("XVII. PRAYER.")


def test_donne_subsection_re_rejects_station_heading():
    assert _DONNE_SUBSECTION_RE.match("II. POST ACTIO LAESA.") is None
    assert _DONNE_SUBSECTION_RE.match("I") is None


# ---------------------------------------------------------------------------
# Taylor: CHAPTER regex allows optional trailing period
# ---------------------------------------------------------------------------

def test_taylor_chapter_re_matches_without_period():
    """Holy Living uses 'CHAPTER I' (no period)."""
    assert _TAYLOR_CHAPTER_RE.match("CHAPTER I")
    assert _TAYLOR_CHAPTER_RE.match("CHAPTER IV")


def test_taylor_chapter_re_matches_with_period():
    """Holy Dying uses 'CHAPTER I.' (with period)."""
    assert _TAYLOR_CHAPTER_RE.match("CHAPTER I.")
    assert _TAYLOR_CHAPTER_RE.match("CHAPTER V.")


def test_taylor_chapter_re_captures_roman():
    m = _TAYLOR_CHAPTER_RE.match("CHAPTER III.")
    assert m is not None
    assert m.group(1) == "III"

    m2 = _TAYLOR_CHAPTER_RE.match("CHAPTER II")
    assert m2 is not None
    assert m2.group(1) == "II"


def test_taylor_section_re_matches_sect():
    assert _TAYLOR_SECTION_RE.match("SECT. I.")
    assert _TAYLOR_SECTION_RE.match("SECTION IV.")


# ---------------------------------------------------------------------------
# Newman: CHAPTER regex and TOC exclusion
# ---------------------------------------------------------------------------

def test_newman_chapter_re_matches_body_heading():
    assert _NEWMAN_CHAPTER_RE.match("CHAPTER I.")
    assert _NEWMAN_CHAPTER_RE.match("CHAPTER V.")


def test_newman_toc_chapter_detects_mixed_case_next_line():
    """TOC entries have a mixed-case description on the next non-blank line."""
    lines = [
        "CHAPTER I.",
        "",
        "History of my Religious Opinions up to 1833",
    ]
    assert _newman_is_toc_chapter(lines, 0) is True


def test_newman_toc_chapter_passes_all_caps_next_line():
    """Real chapter headings are followed by an ALL-CAPS subtitle."""
    lines = [
        "CHAPTER I.",
        "",
        "HISTORY OF MY RELIGIOUS OPINIONS TO THE YEAR 1833.",
    ]
    assert _newman_is_toc_chapter(lines, 0) is False


def test_newman_note_re_matches_all_caps():
    """Body note headings are ALL CAPS: 'NOTE A. ON PAGE 14.'"""
    assert _NEWMAN_NOTE_RE.match("NOTE A. ON PAGE 14.")
    assert _NEWMAN_NOTE_RE.match("NOTE G. ON PAGE 279.")


def test_newman_note_re_rejects_mixed_case():
    """TOC entries use mixed case: 'Note A. On page 14. Liberalism'"""
    assert _NEWMAN_NOTE_RE.match("Note A. On page  14. Liberalism") is None
    assert _NEWMAN_NOTE_RE.match("note a.") is None


# ---------------------------------------------------------------------------
# Andrewes: heading normalization and detection
# ---------------------------------------------------------------------------

def test_andrewes_normalize_strips_footnotes():
    assert _andrewes_normalize("ORDER OF EVENING PRAYER [6]") == "ORDER OF EVENING PRAYER"
    assert _andrewes_normalize("A DEPRECATION [14]") == "A DEPRECATION"


def test_andrewes_normalize_strips_trailing_colon():
    assert _andrewes_normalize("DAILY PRAYERS PREPARATION:") == "DAILY PRAYERS PREPARATION"


def test_andrewes_normalize_strips_whitespace():
    assert _andrewes_normalize("  ORDER OF MATIN PRAYER  ") == "ORDER OF MATIN PRAYER"


def test_andrewes_normalize_combined():
    result = _andrewes_normalize("  ORDER OF EVENING PRAYER [6] : ")
    assert result == "ORDER OF EVENING PRAYER"


def test_is_andrewes_heading_matches_known_sections():
    assert _is_andrewes_heading("ORDER OF MATIN PRAYER")
    assert _is_andrewes_heading("ORDER OF EVENING PRAYER [6]")  # with footnote
    assert _is_andrewes_heading("DAILY PRAYERS PREPARATION:")  # with colon
    assert _is_andrewes_heading("THE FIRST DAY")
    assert _is_andrewes_heading("THE SEVENTH DAY")
    assert _is_andrewes_heading("MEDITATIONS")
    assert _is_andrewes_heading("FOR HOLY COMMUNION")
    assert _is_andrewes_heading("ADDITIONAL EXERCISES")


def test_is_andrewes_heading_rejects_sub_headings():
    """Internal sub-headings like LITANY, CONFESSION must not be detected."""
    assert not _is_andrewes_heading("LITANY")
    assert not _is_andrewes_heading("CONFESSION")
    assert not _is_andrewes_heading("COMMENDATION")
    assert not _is_andrewes_heading("PRAYER FOR GRACE")


def test_is_andrewes_heading_rejects_singular_meditation():
    """Singular MEDITATION is a sub-heading within Evening Prayer, not the main section."""
    assert not _is_andrewes_heading("MEDITATION")


def test_is_andrewes_heading_matches_plural_meditations():
    """Plural MEDITATIONS is the standalone section."""
    assert _is_andrewes_heading("MEDITATIONS")


def test_andrewes_slug_maps_known_headings():
    assert _andrewes_slug("ORDER OF MATIN PRAYER") == "order-of-matin-prayer"
    assert _andrewes_slug("ORDER OF EVENING PRAYER [6]") == "order-of-evening-prayer"
    assert _andrewes_slug("FOR HOLY COMMUNION") == "preparation-for-holy-communion"
    assert _andrewes_slug("THE FIRST DAY") == "first-day"
    assert _andrewes_slug("THE SEVENTH DAY") == "seventh-day"
    assert _andrewes_slug("MEDITATIONS") == "meditations"


# ---------------------------------------------------------------------------
# strip_pg_contributors
# ---------------------------------------------------------------------------

def test_strip_pg_contributors_removes_block_and_returns_names():
    body = [
        "",
        "",
        "Content starts here.",
        "",
        "Produced by Stacy Brown, John Hagerson, Juliet Sutherland",
        "and the Online Distributed Proofreading Team at",
        "http://www.pgdp.net",
        "",
        "More content.",
    ]
    cleaned, contributors = strip_pg_contributors(body)
    assert "More content." in cleaned
    assert "Content starts here." in cleaned
    assert all("Produced" not in line for line in cleaned)
    assert all("pgdp" not in line for line in cleaned)
    assert len(contributors) == 4
    names = [c["name"] for c in contributors]
    assert "Stacy Brown" in names
    assert "John Hagerson" in names
    assert "Juliet Sutherland" in names
    assert "Online Distributed Proofreading Team" in names


def test_strip_pg_contributors_role_is_transcriber():
    body = ["Produced by Alice Smith", ""]
    _, contributors = strip_pg_contributors(body)
    assert contributors[0]["role"] == "transcriber"


def test_strip_pg_contributors_attaches_url_to_team():
    body = [
        "Produced by Alice",
        "and the Some Team at",
        "http://example.com",
        "",
    ]
    _, contributors = strip_pg_contributors(body)
    team = next(c for c in contributors if "Team" in c["name"])
    assert team.get("url") == "http://example.com"


def test_strip_pg_contributors_no_block_returns_unchanged():
    body = ["Line one.", "Line two.", "Line three."]
    cleaned, contributors = strip_pg_contributors(body)
    assert cleaned == body
    assert contributors == []


def test_strip_pg_contributors_beyond_15_lines_ignored():
    """A 'Produced by' line after position 15 must not be treated as a credit block."""
    body = ["Content."] * 20 + ["Produced by Late Editor"]
    cleaned, contributors = strip_pg_contributors(body)
    assert contributors == []
    assert cleaned == body


# ---------------------------------------------------------------------------
# Integration tests — skipped if raw source files not downloaded
# ---------------------------------------------------------------------------

def _load_pg_body(pg_id: int) -> list:
    path = RAW_PG_DIR / f"pg{pg_id}.txt"
    text = path.read_text(encoding="utf-8", errors="replace")
    body = strip_pg_wrapper(text)
    body, _ = strip_pg_contributors(body)
    return body


def _load_ccel_body(slug: str) -> list:
    path = RAW_CCEL_DIR / f"{slug}.txt"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return strip_ccel_header(lines)


@pytest.mark.skipif(
    not (RAW_PG_DIR / "pg23772.txt").exists(),
    reason="raw/gutenberg/pg23772.txt not downloaded",
)
def test_integration_donne_station_count():
    body = _load_pg_body(23772)
    data = parse_donne_devotions(body, [])
    assert len(data["sections"]) == 23, (
        f"Expected 23 Donne stations, got {len(data['sections'])}"
    )


@pytest.mark.skipif(
    not (RAW_PG_DIR / "pg22088.txt").exists(),
    reason="raw/gutenberg/pg22088.txt not downloaded",
)
def test_integration_newman_section_count():
    body = _load_pg_body(22088)
    data = parse_newman_apologia(body, [])
    assert len(data["sections"]) == 13, (
        f"Expected 13 Newman sections (preface + 5 chapters + 7 notes), "
        f"got {len(data['sections'])}"
    )


@pytest.mark.skipif(
    not (RAW_CCEL_DIR / "taylor-holy-living.txt").exists(),
    reason="raw/ccel/taylor-holy-living.txt not downloaded",
)
def test_integration_taylor_holy_living_section_count():
    body = _load_ccel_body("taylor-holy-living")
    data = parse_taylor(body, "taylor-holy-living", [])
    assert len(data["sections"]) == 5, (
        f"Expected 5 Taylor Holy Living sections (preface + 4 chapters), "
        f"got {len(data['sections'])}"
    )


@pytest.mark.skipif(
    not (RAW_CCEL_DIR / "taylor-holy-dying.txt").exists(),
    reason="raw/ccel/taylor-holy-dying.txt not downloaded",
)
def test_integration_taylor_holy_dying_section_count():
    body = _load_ccel_body("taylor-holy-dying")
    data = parse_taylor(body, "taylor-holy-dying", [])
    assert len(data["sections"]) == 6, (
        f"Expected 6 Taylor Holy Dying sections (preface + 5 chapters), "
        f"got {len(data['sections'])}"
    )


@pytest.mark.skipif(
    not (RAW_CCEL_DIR / "andrewes-private-devotions.txt").exists(),
    reason="raw/ccel/andrewes-private-devotions.txt not downloaded",
)
def test_integration_andrewes_prayer_record_count():
    body = _load_ccel_body("andrewes-private-devotions")
    records = parse_andrewes_prayers(body, [])
    assert len(records) == 14, (
        f"Expected 14 Andrewes prayer records, got {len(records)}"
    )
