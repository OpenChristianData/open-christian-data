"""Tests for build/parsers/logos_schaff_herzog.py.

Fixtures are copied verbatim from downloaded raw HTML files (TEST-13):
  - raw/logos/nsherk/articles/00000_aachen-synods-of.html  (full article with attribution, bibliography)
  - raw/logos/nsherk/articles/00002_aaron-and-julius.html  (stub article, single cross-ref)
  - raw/logos/nsherk/articles/00003_abaddon.html           (body-only, bible refs, no attribution/bibliography)

FRAGMENT_DEDUP_HTML is a synthetic fixture that exercises the two-separate-<a>-same-ID
dedup path, which the real HTML can produce but the verbatim fixtures don't happen to contain.

Do NOT modify the verbatim fixture strings to match expected output -- the strings ARE the test.
"""

import json
import jsonschema
import pytest
from pathlib import Path

from ocd_kernel.lib.schema_enums import resolve_schema_path
from build.parsers.logos_schaff_herzog import parse_article

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = resolve_schema_path("reference_entry")

# ---------------------------------------------------------------------------
# Fixtures -- verbatim copies of actual downloaded HTML (TEST-13)
# ---------------------------------------------------------------------------

# Source: raw/logos/nsherk/articles/00000_aachen-synods-of.html
# Full article: body paragraph + attribution + bibliography + cross-references
AACHEN_HTML = (
    '<p class="lang-en" style="font-size:1em;margin:9pt 0 0 0;text-indent:18pt">'
    '<span id="marker2408630" data-offset="180874" class="offset-marker"></span>'
    '<span id="hw20894" rel="headword" data-headword="Aachen" data-headword-language="en"></span>'
    '<span id="hw20895" rel="headword" data-headword="Synods of Aachen" data-headword-language="en"></span>'
    '<strong>AACHEN</strong>, '
    '<span class="lang-x-tl" style="font-family:Charis SIL">ɑ̄′ken</span>'
    '<a rel="popup" data-resourcename="nsherk" href="#" data-content="...">*</a>, '
    '<strong>SYNODS OF</strong>: The political importance of the town of Aachen '
    "(Latin <em>Aquisgranum</em>; French, <em>Aix-la-Chapelle</em>) under Charlemagne "
    "and his successors made it a favorite meeting-place for various assemblies. "
    '<a data-resourceid="LLS:NSHERK" data-resourcetype="text.monograph.encyclopedia" '
    'data-articleid="A.ADOPT2" data-resourcename="nsherk" '
    'href="https://ref.ly/logosres/LLS:NSHERK?art=A.ADOPT2">'
    '<span style="font-variant:small-caps">Adoptionism</span></a> was discussed. '
    '<a data-resourceid="LLS:NSHERK" data-resourcetype="text.monograph.encyclopedia" '
    'data-articleid="N.NICHO.1" data-resourcename="nsherk" '
    'href="https://ref.ly/logosres/LLS:NSHERK?art=N.NICHO.1">'
    '<span style="font-variant:small-caps">Nicholas</span>'
    '<span style="font-variant:small-caps"> I</span></a>. '
    "</p>\n"
    '<p class="lang-en" style="font-size:1em;text-align:right;margin:0 18pt 0 0">'
    '(<span style="font-variant:small-caps">A. Hauck</span>.) </p>\n'
    '<p class="lang-en" style="font-size:.925em;margin:9pt 0 0 18pt;text-indent:-18pt">'
    '<span style="font-variant:small-caps">Bibliography</span>: '
    "Fragmentum historicum de concilio Aquisgranensi; A. J. Binterim. </p>"
)

# Source: raw/logos/nsherk/articles/00002_aaron-and-julius.html
# Stub article: one paragraph, no attribution, no bibliography, one cross-ref
AARON_JULIUS_HTML = (
    '<p class="lang-en" style="font-size:1em;margin:9pt 0 0 0;text-indent:18pt">'
    '<span id="marker3004799" data-offset="188742" class="offset-marker"></span>'
    '<span id="hw27559" rel="headword" data-headword="Aaron and Julius" data-headword-language="en"></span>'
    "<strong>AARON AND JULIUS</strong>: English Martyrs. See "
    '<a data-resourceid="LLS:NSHERK" data-resourcetype="text.monograph.encyclopedia" '
    'data-articleid="A.ALBAN2" data-resourcename="nsherk" '
    'href="https://ref.ly/logosres/LLS:NSHERK?art=A.ALBAN2">'
    '<span style="font-variant:small-caps">Alban, Saint, of Verulam</span></a>. </p>'
)

# Source: raw/logos/nsherk/articles/00003_abaddon.html
# Body-only article: phonetic, bible refs, no attribution, no bibliography, no article cross-refs
ABADDON_HTML = (
    '<p class="lang-en" style="font-size:1em;margin:9pt 0 0 0;text-indent:18pt">'
    '<span id="marker3004851" data-offset="188807" class="offset-marker"></span>'
    '<span id="hw27562" rel="headword" data-headword="Abaddon" data-headword-language="en"></span>'
    '<strong>ABADDON</strong>, '
    '<span class="lang-x-tl" style="font-family:Charis SIL">ɑ-bad′ɵn</span>'
    '<a rel="popup" data-resourcename="nsherk" href="#" data-content="...">*</a> '
    '("Destruction"): In the Old Testament a poetic name for the kingdom of the dead, '
    'Hades, or Sheol (<a class="bibleref" data-reference="bible.18.26.6">Job 26:6</a>). '
    "The rabbis used the name for the nethermost part of hell. "
    "In rabbinical writings Abaddon and Death are also personified "
    '(<a class="bibleref" data-reference="bible.66.9.11">Rev 9:11</a>). </p>'
)


# Synthetic fixture for the two-separate-<a>-same-articleid dedup path.
# The real HTML can produce "Nicholas" + " I" across two <a data-articleid="N.NICHO.1"> tags;
# the verbatim AACHEN fixture happens to have both spans inside one <a>.
FRAGMENT_DEDUP_HTML = (
    '<p class="lang-en">'
    '<strong>TEST ENTRY</strong>: Some text. '
    '<a data-articleid="X.NICHO.1" href="#"><span style="font-variant:small-caps">Nicholas</span></a>'
    '<a data-articleid="X.NICHO.1" href="#"><span style="font-variant:small-caps"> I</span></a>. '
    '<a data-articleid="X.OTHER.1" href="#"><span style="font-variant:small-caps">Adoptionism</span></a>.'
    "</p>"
)


# ---------------------------------------------------------------------------
# Tests: term extraction
# ---------------------------------------------------------------------------


def test_term_joins_multiple_strong_tags():
    """Term combines all <strong> tags in the leading <p>, separated by ', '."""
    entry = parse_article(AACHEN_HTML)
    # Should contain both strong-tag values in order
    assert "AACHEN" in entry["term"]
    assert "SYNODS OF" in entry["term"]


def test_term_strips_phonetic_lang_x_tl_spans():
    """Phonetic text inside <span class='lang-x-tl'> must not appear in term."""
    entry = parse_article(ABADDON_HTML)
    # The phonetic "ɑ-bad′ɵn" must not leak into term
    assert "ɑ" not in entry["term"]  # ɑ character
    assert "ɵ" not in entry["term"]  # ɵ character


def test_term_strips_pronunciation_popup_asterisk():
    """The '*' pronunciation popup link must not appear in term."""
    entry = parse_article(AACHEN_HTML)
    assert "*" not in entry["term"]


def test_term_single_strong_tag():
    """Single <strong> tag produces a non-empty term."""
    entry = parse_article(ABADDON_HTML)
    assert entry["term"].strip() != ""
    assert "ABADDON" in entry["term"]


def test_term_stub_article():
    """Stub article term extracted correctly."""
    entry = parse_article(AARON_JULIUS_HTML)
    assert "AARON AND JULIUS" in entry["term"]


# ---------------------------------------------------------------------------
# Tests: alt_terms from headword spans
# ---------------------------------------------------------------------------


def test_alt_terms_from_headword_spans():
    """All data-headword values from <span rel='headword'> are collected as alt_terms."""
    entry = parse_article(AACHEN_HTML)
    assert "Aachen" in entry["alt_terms"]
    assert "Synods of Aachen" in entry["alt_terms"]


def test_alt_terms_single_headword():
    """Single headword span produces one-item alt_terms list."""
    entry = parse_article(ABADDON_HTML)
    assert "Abaddon" in entry["alt_terms"]


# ---------------------------------------------------------------------------
# Tests: definition_blocks
# ---------------------------------------------------------------------------


def test_definition_blocks_is_non_empty_list():
    entry = parse_article(AACHEN_HTML)
    assert isinstance(entry["definition_blocks"], list)
    assert len(entry["definition_blocks"]) >= 1


def test_definition_blocks_contains_article_body_text():
    entry = parse_article(AACHEN_HTML)
    full_text = " ".join(entry["definition_blocks"])
    assert "Charlemagne" in full_text
    assert "Aachen" in full_text


def test_definition_blocks_excludes_attribution_paragraph():
    """The attribution paragraph (text-align:right / A. Hauck) must not appear in blocks."""
    entry = parse_article(AACHEN_HTML)
    full_text = " ".join(entry["definition_blocks"])
    assert "A. Hauck" not in full_text


def test_definition_blocks_excludes_bibliography_paragraph():
    """The bibliography paragraph (font-size:.925em) must not appear in blocks."""
    entry = parse_article(AACHEN_HTML)
    full_text = " ".join(entry["definition_blocks"])
    assert "Fragmentum historicum" not in full_text


def test_definition_blocks_body_only_article():
    """Article without attribution/bibliography still has definition_blocks."""
    entry = parse_article(ABADDON_HTML)
    assert len(entry["definition_blocks"]) >= 1
    full_text = " ".join(entry["definition_blocks"])
    assert "Hades" in full_text


def test_definition_blocks_stub_article():
    """Stub 'See X' article still has at least one definition block."""
    entry = parse_article(AARON_JULIUS_HTML)
    assert len(entry["definition_blocks"]) >= 1


# ---------------------------------------------------------------------------
# Tests: related_terms (from <a data-articleid> spans)
# ---------------------------------------------------------------------------


def test_related_terms_from_article_cross_references():
    """<a data-articleid> inner <span> text is extracted as related_terms."""
    entry = parse_article(AACHEN_HTML)
    assert "Adoptionism" in entry["related_terms"]


def test_related_terms_includes_all_cross_refs():
    """All <a data-articleid> cross-refs are collected."""
    entry = parse_article(AACHEN_HTML)
    # Both Adoptionism and Nicholas (I) should appear
    assert any("Nicholas" in t for t in entry["related_terms"])


def test_related_terms_stub_article():
    """Stub article related_terms includes its single cross-ref."""
    entry = parse_article(AARON_JULIUS_HTML)
    assert any("Alban" in t for t in entry["related_terms"])


def test_related_terms_empty_for_no_cross_refs():
    """Article with no <a data-articleid> links has empty related_terms list."""
    entry = parse_article(ABADDON_HTML)
    assert entry["related_terms"] == []


# ---------------------------------------------------------------------------
# Tests: word_count
# ---------------------------------------------------------------------------


def test_word_count_is_positive_integer():
    entry = parse_article(AACHEN_HTML)
    assert isinstance(entry["word_count"], int)
    assert entry["word_count"] > 0


def test_word_count_matches_definition_blocks():
    """word_count == sum of split() lengths over definition_blocks."""
    entry = parse_article(AACHEN_HTML)
    expected = sum(len(block.split()) for block in entry["definition_blocks"])
    assert entry["word_count"] == expected


def test_word_count_zero_for_empty_blocks():
    """word_count must be 0 only when definition_blocks is empty (stub yields > 0)."""
    entry = parse_article(AARON_JULIUS_HTML)
    # Stub has some words
    assert entry["word_count"] > 0


# ---------------------------------------------------------------------------
# Tests: entry metadata
# ---------------------------------------------------------------------------


def test_entry_id_format():
    """entry_id = 'schaff-herzog.{slugify(term)}' -- derived from HTML, not filename."""
    entry = parse_article(AACHEN_HTML)
    assert entry["entry_id"] == "schaff-herzog.aachen-synods-of"


def test_dictionary_id():
    entry = parse_article(AACHEN_HTML)
    assert entry["dictionary_id"] == "schaff-herzog-encyclopedia"


def test_scripture_references_is_list():
    """scripture_references is always a list (empty in initial pipeline pass)."""
    entry = parse_article(AACHEN_HTML)
    assert isinstance(entry["scripture_references"], list)


def test_alt_terms_is_list():
    entry = parse_article(AACHEN_HTML)
    assert isinstance(entry["alt_terms"], list)


def test_related_terms_is_list():
    entry = parse_article(AACHEN_HTML)
    assert isinstance(entry["related_terms"], list)


# ---------------------------------------------------------------------------
# Tests: related_terms fragment dedup (group by data-articleid)
# ---------------------------------------------------------------------------


def test_related_terms_dedup_joins_fragments_by_articleid():
    """Two <a data-articleid='X'> with same ID produce one joined term, not two fragments."""
    entry = parse_article(FRAGMENT_DEDUP_HTML)
    assert "Nicholas I" in entry["related_terms"]
    # The fragment "I" must not appear as a standalone entry
    assert "I" not in entry["related_terms"]


def test_related_terms_dedup_preserves_distinct_ids():
    """Different data-articleid values still produce separate related_terms entries."""
    entry = parse_article(FRAGMENT_DEDUP_HTML)
    assert "Adoptionism" in entry["related_terms"]
    assert len([t for t in entry["related_terms"] if t in ("Nicholas I", "Adoptionism")]) == 2


# ---------------------------------------------------------------------------
# Tests: scripture_references extraction
# ---------------------------------------------------------------------------


def test_scripture_references_extracted_from_bibleref_links():
    """<a class='bibleref'> links are extracted as scripture_references objects."""
    entry = parse_article(ABADDON_HTML)
    raws = [r["raw"] for r in entry["scripture_references"]]
    assert "Job 26:6" in raws
    assert "Rev 9:11" in raws


def test_scripture_references_osis_normalised():
    """Each scripture_reference includes a non-empty osis list."""
    entry = parse_article(ABADDON_HTML)
    job_ref = next(r for r in entry["scripture_references"] if r["raw"] == "Job 26:6")
    assert job_ref["osis"] == ["Job.26.6"]


def test_scripture_references_empty_when_no_bibleref_links():
    """Articles without bibleref links produce an empty scripture_references list."""
    entry = parse_article(AACHEN_HTML)
    assert entry["scripture_references"] == []


def test_scripture_references_each_has_raw_and_osis_keys():
    """Every scripture_reference dict has exactly 'raw' and 'osis' keys."""
    entry = parse_article(ABADDON_HTML)
    for ref in entry["scripture_references"]:
        assert set(ref.keys()) == {"raw", "osis"}
        assert isinstance(ref["raw"], str)
        assert isinstance(ref["osis"], list)


# ---------------------------------------------------------------------------
# Tests: schema validation
# ---------------------------------------------------------------------------


def test_parse_article_output_is_schema_valid():
    """parse_article output validates against the reference_entry data-item schema."""
    full_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    # Extract the per-entry sub-schema; include $defs so $ref resolves correctly.
    entry_schema = dict(full_schema["properties"]["data"]["items"])
    entry_schema["$defs"] = full_schema.get("$defs", {})

    for html in (AACHEN_HTML, AARON_JULIUS_HTML, ABADDON_HTML):
        entry = parse_article(html)
        jsonschema.validate(entry, entry_schema)
