"""test_ccel_robertson_word_pictures.py
Tests for ccel_robertson_word_pictures.py -- Robertson Word Pictures Vol. I.

Covers:
  - preprocess_thml: DOCTYPE stripping, entity replacement
  - get_all_text: skips headings, chapter markers, footnotes
  - extract_cross_refs: osisRef parsing
  - parse_div_scripcom: entry builder with and without <scripCom>
  - parse_volume: minimal XML fixture (smoke test)
  - TRADITION enum validity
  - Output file integrity when committed data exists
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
from build.lib._generated_enums import COMMENTARY__META__TRADITION  # noqa: E402
from build.parsers.ccel_robertson_word_pictures import (  # noqa: E402
    RESOURCE_ID,
    TRADITION,
    VOLUMES,
    clean_text,
    extract_cross_refs,
    get_all_text,
    parse_div_scripcom,
    preprocess_thml,
)

# ---------------------------------------------------------------------------
# preprocess_thml
# ---------------------------------------------------------------------------


def test_preprocess_strips_doctype():
    raw = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE ThML PUBLIC "-//CCEL//DTD ThML 1.0//EN" "">'
        b"<ThML><ThML.body/></ThML>"
    )
    result = preprocess_thml(raw)
    assert "<!DOCTYPE" not in result
    assert "<ThML>" in result


def test_preprocess_replaces_mdash():
    raw = b'<?xml version="1.0"?><ThML><ThML.body><p>word&mdash;end</p></ThML.body></ThML>'
    result = preprocess_thml(raw)
    assert "—" in result  # em-dash


def test_preprocess_replaces_greek():
    raw = b'<?xml version="1.0"?><ThML><ThML.body><p>&alpha;&beta;</p></ThML.body></ThML>'
    result = preprocess_thml(raw)
    assert "α" in result  # alpha
    assert "β" in result  # beta


def test_preprocess_preserves_xml_safe_entities():
    raw = b'<?xml version="1.0"?><ThML><ThML.body><p>a &amp; b</p></ThML.body></ThML>'
    result = preprocess_thml(raw)
    assert "&amp;" in result


# ---------------------------------------------------------------------------
# get_all_text
# ---------------------------------------------------------------------------


def test_get_all_text_basic():
    elem = ET.fromstring("<div1><p>Hello world.</p></div1>")
    assert "Hello world." in get_all_text(elem)


def test_get_all_text_skips_h2():
    elem = ET.fromstring("<div1><h2>Chapter 1</h2><p>Commentary text.</p></div1>")
    text = get_all_text(elem)
    assert "Commentary text." in text
    assert "Chapter 1" not in text


def test_get_all_text_skips_note():
    elem = ET.fromstring("<div1><p>Text <note>footnote</note> continues.</p></div1>")
    text = get_all_text(elem)
    assert "footnote" not in text
    assert "Text" in text
    assert "continues" in text


def test_get_all_text_skips_scripcom():
    elem = ET.fromstring(
        '<div1>'
        '<scripCom type="Commentary" osisRef="Bible:Matt.1" />'
        "<p>Commentary text here.</p>"
        "</div1>"
    )
    text = get_all_text(elem)
    assert "Commentary text here." in text
    # scripCom has no text content so nothing to exclude; just verify it doesn't crash


def test_get_all_text_includes_b_and_i():
    """Bold and italic inline elements should be included in the text."""
    elem = ET.fromstring("<p>1:1 <b>The Book</b> [<i>biblos</i>]. Text.</p>")
    text = get_all_text(elem)
    assert "The Book" in text
    assert "biblos" in text


# ---------------------------------------------------------------------------
# extract_cross_refs
# ---------------------------------------------------------------------------


def test_extract_cross_refs_empty():
    elem = ET.fromstring("<p>No scripture here.</p>")
    assert extract_cross_refs(elem) == []


def test_extract_cross_refs_osis_ref():
    elem = ET.fromstring(
        '<div1>'
        '<p>See <scripRef osisRef="Bible:Luke.4.17">Lu 4:17</scripRef>.</p>'
        "</div1>"
    )
    refs = extract_cross_refs(elem)
    assert "Luke.4.17" in refs


def test_extract_cross_refs_strips_bible_prefix():
    elem = ET.fromstring(
        '<p><scripRef osisRef="Bible:1Kgs.2.10">1Ki 2:10</scripRef></p>'
    )
    refs = extract_cross_refs(elem)
    assert len(refs) == 1
    assert refs[0] == "1Kgs.2.10"
    assert "Bible" not in refs[0]


def test_extract_cross_refs_strips_bible_gr_prefix():
    elem = ET.fromstring(
        '<p><scripRef osisRef="Bible.gr:John.1.1">Joh 1:1</scripRef></p>'
    )
    refs = extract_cross_refs(elem)
    assert len(refs) == 1
    assert refs[0] == "John.1.1"


def test_extract_cross_refs_deduplicates():
    elem = ET.fromstring(
        "<p>"
        '<scripRef osisRef="Bible:Matt.1.21">Mt 1:21</scripRef>'
        " and again "
        '<scripRef osisRef="Bible:Matt.1.21">Mt 1:21</scripRef>'
        "</p>"
    )
    refs = extract_cross_refs(elem)
    assert refs.count("Matt.1.21") == 1


def test_extract_cross_refs_requires_two_dots():
    """Refs without chapter.verse (fewer than 2 dots) should be skipped."""
    elem = ET.fromstring(
        '<p><scripRef osisRef="Bible:Matt">whole book ref</scripRef></p>'
    )
    refs = extract_cross_refs(elem)
    assert refs == []


def test_extract_cross_refs_corrects_known_robertson_osis_typos():
    elem = ET.fromstring(
        '<p>'
        '<scripRef osisRef="Bible:Mark.8.311">8:31</scripRef>'
        '<scripRef osisRef="Bible:John.2.29">Joh 2:29</scripRef>'
        '<scripRef osisRef="Bible:Ps.4.9">Ps 4:9</scripRef>'
        '</p>'
    )
    refs = extract_cross_refs(elem)
    assert refs == ["Mark.8.31", "John.3.29", "Ps.41.9"]


def test_extract_cross_refs_drops_irrecoverable_robertson_osis_typos():
    elem = ET.fromstring(
        '<p>'
        '<scripRef osisRef="Bible:Matt.19.36">19:36f.</scripRef>'
        '<scripRef osisRef="Bible:Matt.19.24">19:24</scripRef>'
        '</p>'
    )
    refs = extract_cross_refs(elem)
    assert refs == ["Matt.19.24"]


# ---------------------------------------------------------------------------
# parse_div_scripcom
# ---------------------------------------------------------------------------

_CHAPTER1_XML = (
    b'<div1 title="Chapter 1" id="iii">'
    b'<scripCom type="Commentary" passage="Matthew 1"'
    b' osisRef="Bible:Matt.1" id="iii-p0.1" parsed="|Matt|1|0|0|0" />'
    b"<h2>Chapter 1</h2>"
    b"<p>1:1 The Book. Commentary on the first verse.</p>"
    b"<p>1:2 Another verse. Some commentary text here.</p>"
    b"</div1>"
)


def test_parse_div_scripcom_returns_entry():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry is not None


def test_parse_div_scripcom_entry_id():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["entry_id"] == f"{RESOURCE_ID}.Matt-1-1"


def test_parse_div_scripcom_book_fields():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["book"] == "Matthew"
    assert entry["book_osis"] == "Matt"
    assert entry["book_number"] == 40


def test_parse_div_scripcom_chapter():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["chapter"] == 1


def test_parse_div_scripcom_verse_range():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["verse_range"] == "1"
    assert entry["verse_range_osis"] == "Matt.1.1"


def test_parse_div_scripcom_has_commentary_text():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["commentary_text"]
    assert "verse" in entry["commentary_text"].lower()


def test_parse_div_scripcom_excludes_chapter_heading():
    """h2 'Chapter 1' text must not appear in commentary_text."""
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    # "Chapter 1" from h2 should be stripped
    assert "Chapter 1" not in entry["commentary_text"]


def test_parse_div_scripcom_word_count_positive():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["word_count"] > 0


def test_parse_div_scripcom_summary_withheld():
    div = ET.fromstring(_CHAPTER1_XML)
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry["summary"] is None
    assert entry["summary_review_status"] == "withheld"


def test_parse_div_scripcom_no_scripcom_returns_none():
    """div1 without <scripCom> (e.g. Introduction) should return None."""
    div = ET.fromstring(
        "<div1 title='Introduction' id='ii'>"
        "<h2>Introduction</h2>"
        "<p>Introductory material about Matthew.</p>"
        "</div1>"
    )
    assert parse_div_scripcom(div, "Matt", "Matthew", 40) is None


def test_parse_div_scripcom_cross_refs():
    div = ET.fromstring(
        '<div1 title="Chapter 1" id="iii">'
        '<scripCom osisRef="Bible:Matt.1" />'
        '<p>See <scripRef osisRef="Bible:Luke.3.23">Lu 3:23</scripRef>.</p>'
        "</div1>"
    )
    entry = parse_div_scripcom(div, "Matt", "Matthew", 40)
    assert entry is not None
    assert "Luke.3.23" in entry["cross_references"]


# ---------------------------------------------------------------------------
# Smoke test: minimal full-volume parse
# ---------------------------------------------------------------------------

_MINIMAL_MATT_XML = b"""<?xml version="1.0"?>
<ThML>
<ThML.head/>
<ThML.body>
  <div1 title="Introduction" id="ii">
    <h2>Introduction</h2>
    <p>Introductory material about this work.</p>
  </div1>
  <div1 title="Chapter 1" id="iii">
    <scripCom type="Commentary" passage="Matthew 1"
              osisRef="Bible:Matt.1" id="iii-p0.1" parsed="|Matt|1|0|0|0" />
    <h2>Chapter 1</h2>
    <p>1:1 Commentary on Matthew chapter one verse one here.</p>
  </div1>
  <div1 title="Chapter 2" id="iv">
    <scripCom type="Commentary" passage="Matthew 2"
              osisRef="Bible:Matt.2" id="iv-p0.1" parsed="|Matt|2|0|0|0" />
    <h2>Chapter 2</h2>
    <p>2:1 Commentary on Matthew chapter two verse one here.</p>
  </div1>
</ThML.body>
</ThML>"""


def _parse_minimal_volume():
    """Helper: parse minimal fixture and return entries list."""
    from build.parsers.ccel_robertson_word_pictures import (
        parse_div_scripcom,
        preprocess_thml,
    )
    from xml.etree import ElementTree as ET

    xml_text = preprocess_thml(_MINIMAL_MATT_XML)
    root = ET.fromstring(xml_text)
    body = root.find("ThML.body")
    entries = []
    for div1 in body:
        if div1.tag != "div1":
            continue
        entry = parse_div_scripcom(div1, "Matt", "Matthew", 40)
        if entry:
            entries.append(entry)
    return entries


def test_parse_minimal_volume_skips_introduction():
    entries = _parse_minimal_volume()
    # Introduction div (no scripCom) must be skipped; only 2 chapter entries
    assert len(entries) == 2


def test_parse_minimal_volume_chapters_ordered():
    entries = _parse_minimal_volume()
    chapters = [e["chapter"] for e in entries]
    assert chapters == sorted(chapters)


def test_parse_minimal_volume_entry_ids_unique():
    entries = _parse_minimal_volume()
    ids = [e["entry_id"] for e in entries]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# TRADITION enum validity
# ---------------------------------------------------------------------------


def test_tradition_values_are_valid():
    for t in TRADITION:
        assert t in COMMENTARY__META__TRADITION, (
            f"Invalid tradition {t!r}. Allowed: {sorted(COMMENTARY__META__TRADITION)}"
        )


def test_tradition_is_baptist():
    assert "baptist" in TRADITION


# ---------------------------------------------------------------------------
# VOLUMES registry sanity
# ---------------------------------------------------------------------------


def test_volumes_have_required_keys():
    required = {"title", "book_osis", "book_name", "book_number"}
    for vkey, vol in VOLUMES.items():
        missing = required - set(vol.keys())
        assert not missing, f"{vkey}: missing keys {missing}"


def test_volumes_cover_matthew_and_mark():
    osises = {v["book_osis"] for v in VOLUMES.values()}
    assert "Matt" in osises
    assert "Mark" in osises


# ---------------------------------------------------------------------------
# Output file integrity -- when committed data exists (skip if not generated)
# ---------------------------------------------------------------------------

_OUTPUT_DIR = REPO_ROOT / "data" / "commentaries" / "robertson-word-pictures-vol1"


@pytest.mark.parametrize("book_slug,expected_chapter_count", [
    ("matt", 28),
    ("mark", 16),
])
def test_output_entry_count(book_slug, expected_chapter_count):
    out_path = _OUTPUT_DIR / f"{book_slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert len(doc["data"]) == expected_chapter_count, (
        f"{book_slug}: expected {expected_chapter_count} entries, "
        f"got {len(doc['data'])}"
    )


@pytest.mark.parametrize("book_slug", ["matt", "mark"])
def test_output_meta_fields_present(book_slug):
    out_path = _OUTPUT_DIR / f"{book_slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    meta = doc["meta"]
    for field in (
        "id", "title", "author", "author_death_year", "original_publication_year",
        "language", "tradition", "license", "schema_type", "schema_version",
        "verse_text_source", "verse_reference_standard", "completeness", "provenance",
    ):
        assert field in meta, f"{book_slug}: Missing meta field {field!r}"


@pytest.mark.parametrize("book_slug", ["matt", "mark"])
def test_output_resource_id(book_slug):
    out_path = _OUTPUT_DIR / f"{book_slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["meta"]["id"] == RESOURCE_ID


@pytest.mark.parametrize("book_slug", ["matt", "mark"])
def test_output_no_empty_commentary_text(book_slug):
    out_path = _OUTPUT_DIR / f"{book_slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    for entry in doc["data"]:
        assert entry["commentary_text"], (
            f"{book_slug}: entry {entry['entry_id']} has empty commentary_text"
        )


@pytest.mark.parametrize("book_slug", ["matt", "mark"])
def test_output_total_words_substantial(book_slug):
    out_path = _OUTPUT_DIR / f"{book_slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    total_wc = sum(e["word_count"] for e in doc["data"])
    # Each chapter has substantial commentary; Matthew should exceed 20k words
    assert total_wc > 10_000, (
        f"{book_slug}: total word count {total_wc} is suspiciously low"
    )


@pytest.mark.parametrize("book_slug", ["matt", "mark"])
def test_output_source_hash_format(book_slug):
    out_path = _OUTPUT_DIR / f"{book_slug}.json"
    skip_if_missing_data(out_path)
    with open(out_path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    sh = doc["meta"]["provenance"]["source_hash"]
    assert sh.startswith("sha256:"), f"{book_slug}: source_hash must start with 'sha256:'"
    assert len(sh) == 71, f"{book_slug}: expected sha256:<64hex> (71 chars), got {len(sh)}"
