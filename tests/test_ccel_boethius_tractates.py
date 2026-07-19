"""test_ccel_boethius_tractates.py
Tests for ccel_boethius_tractates.py — Boethius Theological Tractates from CCEL ThML.

Covers:
  - preprocess_thml: DOCTYPE stripping, entity replacement
  - is_centered + filtering: short centered p elements are excluded
  - get_scriptrefs: empty and populated variants
  - parse_tractates: minimal XML smoke test (5 sections, correct labels)
  - build_output: meta field shape, no identity leakage
  - Schema enum validity for WORK_CFG
  - Section count lock against committed output
"""

import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.pytest_skips import skip_if_missing_data  # noqa: E402
from ocd_kernel.lib.schema_enums import get_enum  # noqa: E402
from build.parsers.ccel_boethius_tractates import (  # noqa: E402
    SLUG,
    WORK_CFG,
    TRACTATE_LABELS,
    clean_text,
    get_all_text,
    get_scriptrefs,
    is_centered,
    parse_tractate,
    parse_tractates,
    preprocess_thml,
)

# ---------------------------------------------------------------------------
# Schema enum constants (loaded from schema at test-discovery time)
# ---------------------------------------------------------------------------

_VALID_TRADITIONS = get_enum("structured_text", "meta", "tradition")
_VALID_WORK_KINDS = get_enum("structured_text", "data", "work_kind")
_VALID_ERAS = get_enum("structured_text", "meta", "era")
_VALID_AUDIENCES = get_enum("structured_text", "meta", "audience")
_VALID_COMPLETENESS = get_enum("structured_text", "meta", "completeness")


# ---------------------------------------------------------------------------
# preprocess_thml
# ---------------------------------------------------------------------------


def test_preprocess_strips_doctype():
    raw = b'<?xml version="1.0"?><!DOCTYPE ThML PUBLIC "-//CCEL//DTD ThML 1.0//EN" ""><ThML><ThML.body/></ThML>'
    result = preprocess_thml(raw)
    assert "<!DOCTYPE" not in result
    assert "<ThML>" in result


def test_preprocess_replaces_mdash():
    raw = b'<?xml version="1.0"?><ThML><ThML.body><p>word&mdash;end</p></ThML.body></ThML>'
    result = preprocess_thml(raw)
    assert "—" in result


def test_preprocess_replaces_ldquo():
    raw = b'<?xml version="1.0"?><ThML><ThML.body><p>&ldquo;quote&rdquo;</p></ThML.body></ThML>'
    result = preprocess_thml(raw)
    assert "“" in result
    assert "”" in result


def test_preprocess_preserves_xml_safe_entities():
    raw = b'<?xml version="1.0"?><ThML><ThML.body><p>a &amp; b</p></ThML.body></ThML>'
    result = preprocess_thml(raw)
    assert "&amp;" in result


# ---------------------------------------------------------------------------
# is_centered
# ---------------------------------------------------------------------------


def test_is_centered_style_attr():
    elem = ET.fromstring('<p style="text-align:center">I.</p>')
    assert is_centered(elem)


def test_is_centered_with_space():
    elem = ET.fromstring('<p style="text-align: center">I.</p>')
    assert is_centered(elem)


def test_is_centered_false_no_style():
    elem = ET.fromstring("<p>Normal paragraph text here.</p>")
    assert not is_centered(elem)


# ---------------------------------------------------------------------------
# get_scriptrefs
# ---------------------------------------------------------------------------


def test_get_scriptrefs_empty():
    elem = ET.fromstring("<p>No scripture here at all.</p>")
    assert get_scriptrefs(elem) == []


def test_get_scriptrefs_with_osis_ref():
    elem = ET.fromstring(
        '<p>See <scripRef osisRef="Bible:John.3.16">John 3:16</scripRef>.</p>'
    )
    refs = get_scriptrefs(elem)
    assert len(refs) == 1
    assert refs[0]["osis"] == ["John.3.16"]
    assert refs[0]["raw"] == "John 3:16"


def test_get_scriptrefs_strips_bible_prefix():
    elem = ET.fromstring(
        '<p><scripRef osisRef="Bible.gr:Rom.1.20">Rom. 1:20</scripRef></p>'
    )
    refs = get_scriptrefs(elem)
    assert len(refs) == 1
    assert "Bible" not in refs[0]["osis"][0]


# ---------------------------------------------------------------------------
# parse_tractate — unit level
# ---------------------------------------------------------------------------

_DIV2_MINIMAL = b"""<div2 id="iv.i" title="The Trinity is One God Not Three Gods">
  <h2>TRACTATE I</h2>
  <pb/>
  <p style="text-align:center">I.</p>
  <p>The question is proposed by you in the following terms.</p>
  <p>For there are predicaments which are applied to all things.</p>
  <p>Thus the predicaments of substance, quality, quantity, relation,
     place, time, condition, activity, and passivity are applicable to all things.</p>
</div2>"""


def test_parse_tractate_label():
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    assert section["label"] == "I"


def test_parse_tractate_title():
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    assert "Trinity" in section["title"]


def test_parse_tractate_filters_centered_short():
    """Single-word centered p like 'I.' must be excluded."""
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    for block in section["content_blocks"]:
        # The centered 'I.' must not appear as its own block
        assert block.strip() not in ("I.", "II.", "III.", "IV.", "V.")


def test_parse_tractate_filters_pb():
    """Page breaks (pb) must not appear in content."""
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    # pb produces no text; verify content blocks are non-empty text
    for block in section["content_blocks"]:
        assert block.strip()


def test_parse_tractate_section_type():
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    assert section["section_type"] == "part"


def test_parse_tractate_children_empty():
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    assert section["children"] == []


def test_parse_tractate_word_count_positive():
    div2 = ET.fromstring(_DIV2_MINIMAL)
    section = parse_tractate(div2)
    assert section["word_count"] > 0


# ---------------------------------------------------------------------------
# parse_tractates — full document smoke test
# ---------------------------------------------------------------------------

_MINIMAL_THML = b"""<?xml version="1.0"?>
<ThML>
<ThML.head/>
<ThML.body>
  <div1 id="iv" title="The Theological Tractates">
    <div2 id="iv.i" title="Tractate One">
      <p>First tractate paragraph with enough words here.</p>
    </div2>
    <div2 id="iv.ii" title="Tractate Two">
      <p>Second tractate paragraph with enough words to count properly.</p>
    </div2>
    <div2 id="iv.iii" title="Tractate Three">
      <p>Third tractate paragraph content is here for testing purposes.</p>
    </div2>
    <div2 id="iv.iv" title="Tractate Four">
      <p>Fourth tractate paragraph text appears here in the document.</p>
    </div2>
    <div2 id="iv.v" title="Tractate Five">
      <p>Fifth tractate paragraph closes out the five theological tractates.</p>
    </div2>
  </div1>
</ThML.body>
</ThML>"""


def test_parse_tractates_returns_five_sections():
    result = parse_tractates(_MINIMAL_THML)
    assert len(result["sections"]) == 5


def test_parse_tractates_labels():
    result = parse_tractates(_MINIMAL_THML)
    labels = [s["label"] for s in result["sections"]]
    assert labels == ["I", "II", "III", "IV", "V"]


def test_parse_tractates_section_type():
    result = parse_tractates(_MINIMAL_THML)
    for s in result["sections"]:
        assert s["section_type"] == "part"


def test_parse_tractates_source_hash_prefix():
    result = parse_tractates(_MINIMAL_THML)
    assert result["source_hash"].startswith("sha256:")


def test_parse_tractates_all_have_content():
    result = parse_tractates(_MINIMAL_THML)
    for s in result["sections"]:
        assert s["content_blocks"], f"Section {s['label']!r} has no content_blocks"


def test_parse_tractates_missing_div1_raises():
    bad_xml = b"""<?xml version="1.0"?>
<ThML><ThML.head/><ThML.body><div1 id="wrong"/></ThML.body></ThML>"""
    with pytest.raises(RuntimeError, match="No div1 id="):
        parse_tractates(bad_xml)


# ---------------------------------------------------------------------------
# WORK_CFG schema enum guards
# ---------------------------------------------------------------------------


def test_work_cfg_traditions_valid():
    for t in WORK_CFG["tradition"]:
        assert t in _VALID_TRADITIONS, (
            f"Invalid tradition {t!r}. Allowed: {sorted(_VALID_TRADITIONS)}"
        )


def test_work_cfg_work_kind_valid():
    assert WORK_CFG["work_kind"] in _VALID_WORK_KINDS, (
        f"Invalid work_kind {WORK_CFG['work_kind']!r}. Allowed: {sorted(_VALID_WORK_KINDS)}"
    )


def test_work_cfg_era_valid():
    assert WORK_CFG["era"] in _VALID_ERAS, (
        f"Invalid era {WORK_CFG['era']!r}. Allowed: {sorted(_VALID_ERAS)}"
    )


def test_work_cfg_audience_valid():
    assert WORK_CFG["audience"] in _VALID_AUDIENCES, (
        f"Invalid audience {WORK_CFG['audience']!r}. Allowed: {sorted(_VALID_AUDIENCES)}"
    )


def test_work_cfg_completeness_valid():
    assert WORK_CFG["completeness"] in _VALID_COMPLETENESS, (
        f"Invalid completeness {WORK_CFG['completeness']!r}. Allowed: {sorted(_VALID_COMPLETENESS)}"
    )


# ---------------------------------------------------------------------------
# WORK_CFG field presence
# ---------------------------------------------------------------------------


def test_work_cfg_required_fields():
    required = {
        "slug", "title", "author", "author_id", "language", "original_language",
        "tradition", "era", "audience", "work_kind", "completeness",
    }
    missing = required - set(WORK_CFG.keys())
    assert not missing, f"WORK_CFG missing required fields: {missing}"


def test_work_cfg_slug():
    assert WORK_CFG["slug"] == "boethius-theological-tractates"


def test_work_cfg_language():
    assert WORK_CFG["language"] == "en"
    assert WORK_CFG["original_language"] == "la"


def test_work_cfg_author_id():
    assert WORK_CFG["author_id"] == "boethius"


# ---------------------------------------------------------------------------
# TRACTATE_LABELS
# ---------------------------------------------------------------------------


def test_tractate_labels_five_entries():
    assert len(TRACTATE_LABELS) == 5


def test_tractate_labels_roman_numerals():
    assert set(TRACTATE_LABELS.values()) == {"I", "II", "III", "IV", "V"}


def test_tractate_labels_keys():
    assert "iv.i" in TRACTATE_LABELS
    assert "iv.v" in TRACTATE_LABELS


# ---------------------------------------------------------------------------
# Section count lock — guards against filter regressions on committed output
# ---------------------------------------------------------------------------

_EXPECTED_TOP_SECTIONS = {
    "boethius-theological-tractates": 5,
}


@pytest.mark.parametrize("slug,expected", sorted(_EXPECTED_TOP_SECTIONS.items()))
def test_top_section_counts(slug, expected):
    out_path = REPO_ROOT / "data" / "structured-text" / f"{slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["data"]["sections"]) == expected, (
        f"{slug}: expected {expected} top sections, got {len(data['data']['sections'])}"
    )


# ---------------------------------------------------------------------------
# Output file integrity — when committed output exists
# ---------------------------------------------------------------------------


def test_output_meta_fields_present():
    out_path = REPO_ROOT / "data" / "structured-text" / f"{SLUG}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    meta = doc["meta"]
    for field in ("id", "title", "author", "language", "schema_type", "schema_version",
                  "license", "tradition", "era", "audience", "completeness", "provenance"):
        assert field in meta, f"Missing meta field: {field!r}"


def test_output_work_kind_in_data():
    out_path = REPO_ROOT / "data" / "structured-text" / f"{SLUG}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert "work_kind" in doc["data"]
    assert "work_kind" not in doc["meta"], "work_kind must not appear in meta"


def test_output_no_empty_sections():
    out_path = REPO_ROOT / "data" / "structured-text" / f"{SLUG}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    for s in doc["data"]["sections"]:
        assert s.get("content_blocks"), (
            f"Section {s.get('label')!r} {s.get('title')!r} has no content_blocks"
        )


def test_output_total_words_substantial():
    """Sanity check: 5 theological tractates should exceed 15,000 words."""
    out_path = REPO_ROOT / "data" / "structured-text" / f"{SLUG}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    total = sum(s.get("word_count", 0) for s in doc["data"]["sections"])
    assert total > 15_000, f"Total word count {total} is suspiciously low for 5 tractates"


def test_output_source_hash_format():
    out_path = REPO_ROOT / "data" / "structured-text" / f"{SLUG}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    source_hash = doc["meta"]["provenance"]["source_hash"]
    assert source_hash.startswith("sha256:"), f"Expected sha256: prefix, got {source_hash!r}"
    assert len(source_hash) == 71, f"Expected sha256:<64hex> (71 chars), got len={len(source_hash)}"
