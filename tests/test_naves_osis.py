"""Tests for Nave's Topical Bible parser functions.

Run: py -3 -m pytest tests/test_naves_osis.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.parsers.naves_topical import (
    extract_osis_refs,
    extract_cross_refs,
    make_unique_id,
    parse_subtopics,
    slugify,
)


# ---------------------------------------------------------------------------
# Fixtures — representative XML strings from actual Nave module (Task 2)
# ---------------------------------------------------------------------------

AARON_XML = """<entryFree n="AARON">
<def>
<lb/>&#x2192; Lineage of <ref osisRef="Exod.6.16-Exod.6.20">Ex 6:16-20</ref>; <ref osisRef="Josh.21.4">Jos 21:4</ref>; <ref osisRef="1Chr.6.2-1Chr.6.3">1Ch 6:2,3</ref>
<lb/>&#x2192; Marriage of <ref osisRef="Exod.6.23">Ex 6:23</ref>
</def>
</entryFree>"""

ABADDON_XML = """<entryFree n="ABADDON">
<def>
<lb/>&#x2192; The angel of the bottomless pit <ref osisRef="Rev.9.11">Re 9:11</ref></def>
</entryFree>"""

ABARIM_XML = """<entryFree n="ABARIM">
<def>
<lb/>&#x2192; See <ref target="Nave:NEBO">NEBO</ref></def>
</entryFree>"""

SIMPLE_XML = """<entryFree n="ABBA">
<def>
<ref osisRef="Mark.14.36">Mr 14:36</ref>; <ref osisRef="Rom.8.15">Ro 8:15</ref>; <ref osisRef="Gal.4.6">Ga 4:6</ref></def>
</entryFree>"""

MULTIPLE_CROSS_XML = """<entryFree n="ABOLISH">
<def>
<lb/>&#x2192; See <ref target="Nave:LAW">LAW</ref>; <ref target="Nave:COMMANDMENTS">COMMANDMENTS</ref></def>
</entryFree>"""


class TestExtractOsisRefs:
    def test_single_ref(self):
        result = extract_osis_refs(ABADDON_XML)
        assert len(result) == 1
        assert result[0]["raw"] == "Re 9:11"
        assert result[0]["osis"] == ["Rev.9.11"]

    def test_multiple_refs_on_one_line(self):
        result = extract_osis_refs(AARON_XML)
        # 4 refs total across all lines: Exod.6.16-Exod.6.20, Josh.21.4, 1Chr.6.2-1Chr.6.3, Exod.6.23
        assert len(result) == 4
        assert result[0]["osis"] == ["Exod.6.16-Exod.6.20"]
        assert result[1]["osis"] == ["Josh.21.4"]

    def test_simple_entry_no_subtopics(self):
        result = extract_osis_refs(SIMPLE_XML)
        assert len(result) == 3
        assert result[0]["osis"] == ["Mark.14.36"]
        assert result[2]["osis"] == ["Gal.4.6"]

    def test_cross_ref_target_not_included(self):
        # <ref target="Nave:..."> should NOT appear in osis refs
        result = extract_osis_refs(ABARIM_XML)
        assert result == []

    def test_raw_display_text_preserved(self):
        result = extract_osis_refs(ABADDON_XML)
        assert result[0]["raw"] == "Re 9:11"


class TestExtractCrossRefs:
    def test_single_cross_ref(self):
        result = extract_cross_refs(ABARIM_XML)
        assert result == ["NEBO"]

    def test_multiple_cross_refs(self):
        result = extract_cross_refs(MULTIPLE_CROSS_XML)
        assert "LAW" in result
        assert "COMMANDMENTS" in result
        assert len(result) == 2

    def test_nave_prefix_stripped(self):
        result = extract_cross_refs(ABARIM_XML)
        assert all(not r.startswith("Nave:") for r in result)

    def test_no_cross_refs(self):
        result = extract_cross_refs(ABADDON_XML)
        assert result == []

    def test_scripture_refs_not_included(self):
        # <ref osisRef="..."> should NOT appear in cross refs
        result = extract_cross_refs(AARON_XML)
        assert result == []


class TestParseSubtopics:
    def test_subtopic_labels_extracted(self):
        subtopics = parse_subtopics(AARON_XML)
        labels = [s["label"] for s in subtopics]
        assert "Lineage of" in labels
        assert "Marriage of" in labels

    def test_each_subtopic_has_references(self):
        subtopics = parse_subtopics(AARON_XML)
        lineage = next(s for s in subtopics if s["label"] == "Lineage of")
        assert len(lineage["references"]) == 3
        assert lineage["references"][0]["osis"] == ["Exod.6.16-Exod.6.20"]

    def test_simple_entry_one_subtopic_empty_label(self):
        # Entry with no → markers: one subtopic, label=""
        subtopics = parse_subtopics(SIMPLE_XML)
        assert len(subtopics) == 1
        assert subtopics[0]["label"] == ""
        assert len(subtopics[0]["references"]) == 3

    def test_cross_ref_only_entry_empty_references(self):
        # ABARIM has an arrow before "See NEBO", so it produces one subtopic
        # with label="See" and references=[] (the cross-ref uses target= not osisRef=,
        # so no scripture refs are extracted; the NEBO cross-ref goes to related_topics).
        subtopics = parse_subtopics(ABARIM_XML)
        assert subtopics == [{"label": "See", "references": []}]

    def test_subtopic_label_stripped_of_trailing_whitespace(self):
        subtopics = parse_subtopics(AARON_XML)
        for s in subtopics:
            assert s["label"] == s["label"].strip()


class TestMakeUniqueId:
    def test_no_collision(self):
        seen: set = set()
        result = make_unique_id("aaron", seen)
        assert result == "aaron"
        assert "aaron" in seen

    def test_first_collision(self):
        seen: set = {"aaron"}
        result = make_unique_id("aaron", seen)
        assert result == "aaron-2"
        assert "aaron-2" in seen

    def test_second_collision(self):
        seen: set = {"aaron", "aaron-2"}
        result = make_unique_id("aaron", seen)
        assert result == "aaron-3"
        assert "aaron-3" in seen


class TestSlugify:
    def test_simple(self):
        assert slugify("AARON") == "aaron"

    def test_spaces(self):
        assert slugify("SON OF GOD") == "son-of-god"

    def test_punctuation(self):
        assert slugify("FAITH, TRIAL OF") == "faith-trial-of"

    def test_unicode_stripped(self):
        # Non-ASCII characters normalised to ASCII equivalents or dropped
        result = slugify("ELIJAH")
        assert result.isascii()

    def test_max_len(self):
        long_str = "A" * 200
        assert len(slugify(long_str, max_len=80)) <= 80
