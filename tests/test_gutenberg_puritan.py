"""test_gutenberg_puritan.py
Unit tests for gutenberg_puritan.py pure functions.

Covers the key invariants for the T6-1 Puritan batch parser:
  - strip_pg_wrapper: body extraction between PG markers
  - _split_charnock_volumes: volume boundary detection
  - CHARNOCK_DISCOURSE_RE: anchor-tagged headings only (no TOC match)
  - SIBBES_CHAPTER_RE: 'Chap. I.' format in body (not 'Chapter I.' from TOC)
  - BURROUGHS_SECTION_RE: uppercase Roman numerals only (not lowercase sub-points)
  - gather_paragraphs: blank-line-separated paragraph collection
  - clean_content_block: PG anchor stripping and whitespace normalization
  - normalize_ocr_spaces: double-space collapsing

Added 2026-04-23 for T6-1.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.gutenberg_puritan import (  # noqa: E402
    CHARNOCK_DISCOURSE_RE,
    GURNALL_CHAPTER_RE,
    BROOKS_CHAP_RE,
    BURROUGHS_SECTION_RE,
    SIBBES_CHAPTER_RE,
    _split_charnock_volumes,
    strip_pg_wrapper,
    gather_paragraphs,
    clean_content_block,
    normalize_ocr_spaces,
    check_structural_plausibility,
)


# ---------------------------------------------------------------------------
# strip_pg_wrapper
# ---------------------------------------------------------------------------

def test_strip_pg_wrapper_extracts_body():
    text = (
        "Some preamble\n"
        "*** START OF THE PROJECT GUTENBERG EBOOK ***\n"
        "Body line 1\n"
        "Body line 2\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK ***\n"
        "Postamble\n"
    )
    body = strip_pg_wrapper(text)
    assert "Body line 1" in body
    assert "Body line 2" in body
    assert "preamble" not in "\n".join(body)
    assert "Postamble" not in "\n".join(body)


def test_strip_pg_wrapper_raises_if_no_markers():
    import pytest
    with pytest.raises(ValueError):
        strip_pg_wrapper("No markers here at all.")


# ---------------------------------------------------------------------------
# _split_charnock_volumes
# ---------------------------------------------------------------------------

def _charnock_vol_lines():
    lines = ["some front matter"] * 10
    lines += ["Volume 1", "disc I content"] * 5
    lines += ["Volume 2", "disc X content"] * 5
    return lines


def test_split_charnock_volumes_returns_two_parts():
    lines = (
        ["preamble"] * 3
        + ["Volume 1"]
        + ["content vol1"] * 10
        + ["Volume 2"]
        + ["content vol2"] * 10
    )
    vol1, vol2 = _split_charnock_volumes(lines)
    assert "content vol1" in "\n".join(vol1)
    assert "content vol2" not in "\n".join(vol1)
    assert "content vol2" in "\n".join(vol2)


def test_split_charnock_volumes_raises_if_fewer_than_two():
    import pytest
    with pytest.raises(ValueError, match="Expected 2"):
        _split_charnock_volumes(["Volume 1", "only one volume"])


# ---------------------------------------------------------------------------
# CHARNOCK_DISCOURSE_RE -- only matches anchor-prefixed body headings
# ---------------------------------------------------------------------------

def test_charnock_discourse_re_matches_anchor_prefix():
    """Body headings have {a23} or {b5} anchor prefix."""
    assert CHARNOCK_DISCOURSE_RE.match("{a23}                        DISCOURSE I.")
    assert CHARNOCK_DISCOURSE_RE.match("{b5}                       DISCOURSE X.")
    assert CHARNOCK_DISCOURSE_RE.match("{a89}                       DISCOURSE II.")


def test_charnock_discourse_re_rejects_toc_entries():
    """TOC entries have no anchor prefix and must not match."""
    assert CHARNOCK_DISCOURSE_RE.match("DISCOURSE I.") is None
    assert CHARNOCK_DISCOURSE_RE.match("                DISCOURSE VI.") is None


def test_charnock_discourse_re_captures_roman():
    m = CHARNOCK_DISCOURSE_RE.match("{a23}                        DISCOURSE I.")
    assert m is not None
    assert m.group(1) == "I"

    m2 = CHARNOCK_DISCOURSE_RE.match("{b108}                       DISCOURSE XI.")
    assert m2 is not None
    assert m2.group(1) == "XI"


# ---------------------------------------------------------------------------
# GURNALL_CHAPTER_RE
# ---------------------------------------------------------------------------

def test_gurnall_chapter_re_matches_full_chapter():
    assert GURNALL_CHAPTER_RE.match("CHAPTER I.")
    assert GURNALL_CHAPTER_RE.match("CHAPTER  I.")  # double space (OCR artifact)
    assert GURNALL_CHAPTER_RE.match("CHAPTER XII.")


def test_gurnall_chapter_re_rejects_abbreviated():
    assert GURNALL_CHAPTER_RE.match("CHAP. I.") is None
    assert GURNALL_CHAPTER_RE.match("CHAP. XII.") is None


# ---------------------------------------------------------------------------
# BROOKS_CHAP_RE
# ---------------------------------------------------------------------------

def test_brooks_chap_re_matches_abbreviated():
    assert BROOKS_CHAP_RE.match("CHAP. I.")
    assert BROOKS_CHAP_RE.match("CHAP. XXIX.")


def test_brooks_chap_re_rejects_full_chapter():
    assert BROOKS_CHAP_RE.match("CHAPTER I.") is None


# ---------------------------------------------------------------------------
# BURROUGHS_SECTION_RE -- case-sensitive: uppercase only
# ---------------------------------------------------------------------------

def test_burroughs_section_re_matches_uppercase():
    """Main sections use uppercase Roman numerals and ALL-CAPS descriptions."""
    assert BURROUGHS_SECTION_RE.match("I. THE DEFINITION OF THIS CONTENTMENT")
    assert BURROUGHS_SECTION_RE.match("IV. IT IS NOT SO MUCH THE REMOVING")
    assert BURROUGHS_SECTION_RE.match("XX. SOME COROLLARIES FROM THIS")


def test_burroughs_section_re_rejects_lowercase():
    """Sub-points use lowercase Roman numerals and must NOT match."""
    assert BURROUGHS_SECTION_RE.match("i. Jesus Christ is your elder brother") is None
    assert BURROUGHS_SECTION_RE.match("iv. He is your elder brother likewise") is None
    assert BURROUGHS_SECTION_RE.match("vii. The relation in which you stand") is None


# ---------------------------------------------------------------------------
# SIBBES_CHAPTER_RE -- matches 'Chap.' body format, not 'Chapter' TOC format
# ---------------------------------------------------------------------------

def test_sibbes_chapter_re_matches_body_format():
    """Body uses 'Chap. I.' with title on same line."""
    assert SIBBES_CHAPTER_RE.match("Chap. I. - The Text opened and divided.")
    assert SIBBES_CHAPTER_RE.match("Chap. XI. - Signs of smoking flax")
    assert SIBBES_CHAPTER_RE.match("Chap. XXVIII. - Be encouraged to go on cheerfully")


def test_sibbes_chapter_re_rejects_toc_format():
    """TOC uses 'Chapter I.' (no title on same line) — already a different format."""
    # The TOC format 'Chapter I.' matches 'Chapter' not 'Chap.' so is correctly rejected
    assert SIBBES_CHAPTER_RE.match("Chapter I.") is None
    assert SIBBES_CHAPTER_RE.match("Chapter IX.") is None


def test_sibbes_chapter_re_captures_roman():
    m = SIBBES_CHAPTER_RE.match("Chap. VII. - Christ will not quench")
    assert m is not None
    assert m.group(1).upper() == "VII"


# ---------------------------------------------------------------------------
# gather_paragraphs
# ---------------------------------------------------------------------------

def test_gather_paragraphs_collects_blocks():
    lines = [
        "First paragraph line 1.",
        "First paragraph line 2.",
        "",
        "Second paragraph.",
        "",
        "Third paragraph.",
    ]
    paras = gather_paragraphs(lines, 0, len(lines))
    assert len(paras) == 3
    assert "First paragraph line 1." in paras[0]
    assert "First paragraph line 2." in paras[0]


def test_gather_paragraphs_respects_stop():
    # stop is exclusive; lines 0,1 = ["Para A.", ""] → one paragraph
    lines = ["Para A.", "", "Para B.", "", "Para C."]
    paras = gather_paragraphs(lines, 0, 2)
    assert len(paras) == 1
    assert "Para A." in paras[0]


def test_gather_paragraphs_strips_pg_anchors():
    lines = ["{a1} Some content with {a2} anchor tags."]
    paras = gather_paragraphs(lines, 0, 1, strip_pg_anchors=True)
    assert len(paras) == 1
    assert "{a1}" not in paras[0]
    assert "{a2}" not in paras[0]


# ---------------------------------------------------------------------------
# clean_content_block
# ---------------------------------------------------------------------------

def test_clean_content_block_strips_anchors():
    result = clean_content_block("{a1}The text here{a2} continues.", strip_pg_anchors=True)
    assert "{a1}" not in result
    assert "{a2}" not in result
    assert "The text here" in result


def test_clean_content_block_normalizes_whitespace():
    result = clean_content_block("  spaced   out   text  ")
    assert result == "spaced out text"


def test_clean_content_block_no_anchor_strip():
    result = clean_content_block("{a1}kept", strip_pg_anchors=False)
    assert "{a1}" in result


# ---------------------------------------------------------------------------
# normalize_ocr_spaces
# ---------------------------------------------------------------------------

def test_normalize_ocr_spaces_collapses_doubles():
    assert normalize_ocr_spaces("CHAPTER  I.") == "CHAPTER I."
    assert normalize_ocr_spaces("word   spacing") == "word spacing"


def test_normalize_ocr_spaces_leaves_single_spaces():
    assert normalize_ocr_spaces("normal text") == "normal text"


# ---------------------------------------------------------------------------
# check_structural_plausibility
# ---------------------------------------------------------------------------

def _make_sections(word_counts):
    return [
        {"section_type": "chapter", "label": f"Ch {i+1}", "word_count": wc, "children": []}
        for i, wc in enumerate(word_counts)
    ]


def test_structural_plausibility_flags_dominant_section():
    """One section with >50% of words in a 5+-section work should warn."""
    sections = _make_sections([100, 100, 100, 100, 100, 50000])
    data = {"sections": sections}
    log_lines = []
    assert check_structural_plausibility(data, "test-work", log_lines) is False
    assert any("WARNING" in l for l in log_lines)
    assert any("Output blocked" in l for l in log_lines)


def test_structural_plausibility_passes_even_distribution():
    """Equal-length sections should pass."""
    sections = _make_sections([3000, 3000, 3000, 3000, 3000])
    data = {"sections": sections}
    assert check_structural_plausibility(data, "test-work", []) is True


def test_structural_plausibility_passes_moderate_variation():
    """A section with <50% of total words should pass even if much larger than others."""
    # 14k out of 80k total = 17.5% -- legitimately large but not dominant
    sections = _make_sections([5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 5000, 14000])
    data = {"sections": sections}
    assert check_structural_plausibility(data, "test-work", []) is True


def test_structural_plausibility_skips_small_works():
    """Works with fewer than 5 sections are not checked (valid for short works)."""
    sections = _make_sections([100, 100, 50000])
    data = {"sections": sections}
    assert check_structural_plausibility(data, "test-work", []) is True
