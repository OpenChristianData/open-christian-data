"""test_bible_ref_normalizer.py
Unit tests for ocd_kernel.lib.bible_ref_normalizer.parse_thml_refs and
extract_refs_from_text.

All cases derived from real examples confirmed in Barnes, Wesley, and HelloAO corpora.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so imports work when running directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.bible_ref_normalizer import (  # noqa: E402
    extract_refs_from_text,
    parse_maclaren_ref,
    parse_thml_refs,
)


# ---------------------------------------------------------------------------
# Single reference
# ---------------------------------------------------------------------------

def test_single_ref_abbreviated():
    """Abbreviated book + ch:v -> OSIS."""
    assert parse_thml_refs("1Chr 3:10") == ["1Chr.3.10"]


def test_single_ref_full_book_name():
    """Full book name -> correct OSIS code."""
    assert parse_thml_refs("Isaiah 29:13") == ["Isa.29.13"]


def test_single_ref_nt():
    """NT book abbreviation -> OSIS."""
    assert parse_thml_refs("Acts 12:1") == ["Acts.12.1"]


# ---------------------------------------------------------------------------
# Multi-reference, same book
# ---------------------------------------------------------------------------

def test_same_book_comma_verse():
    """Comma-separated bare verse numbers share the preceding chapter."""
    assert parse_thml_refs("Ps 132:10,11") == ["Ps.132.10", "Ps.132.11"]


def test_same_book_comma_chap_verse():
    """Comma-separated ch:v tokens share the preceding book."""
    result = parse_thml_refs("1Sam 1:1,19, 2:11, 8:4, 19:18")
    assert result == ["1Sam.1.1", "1Sam.1.19", "1Sam.2.11", "1Sam.8.4", "1Sam.19.18"]


# ---------------------------------------------------------------------------
# Multi-reference, book changes mid-string
# ---------------------------------------------------------------------------

def test_cross_book_comma():
    """Book changes within a comma-separated list."""
    result = parse_thml_refs("Lev 4:3, 6:20, Ex 28:41, 29:7")
    assert result == ["Lev.4.3", "Lev.6.20", "Exod.28.41", "Exod.29.7"]


def test_semicolon_separator():
    """Semicolon-separated refs within the same book."""
    assert parse_thml_refs("Gen 12:3; 21:12") == ["Gen.12.3", "Gen.21.12"]


def test_mixed_separator_cross_book():
    """Semicolon groups + comma continuation, book changes."""
    result = parse_thml_refs("Deut 24:1; Matt 19:7; Mark 10:2; Luke 16:18")
    assert result == ["Deut.24.1", "Matt.19.7", "Mark.10.2", "Luke.16.18"]


def test_semicolon_bare_chap_verse_continues_book():
    """Bare ch:v after semicolon uses the book set in a prior group."""
    result = parse_thml_refs("Dan 2:44; 7:13,14")
    assert result == ["Dan.2.44", "Dan.7.13", "Dan.7.14"]


# ---------------------------------------------------------------------------
# Verse ranges (start verse only)
# ---------------------------------------------------------------------------

def test_range_returns_start_verse():
    """ch:v-v2 range -> only the start verse is emitted."""
    assert parse_thml_refs("1Sam 14:24-27") == ["1Sam.14.24"]


def test_range_mid_list():
    """Range appearing in the middle of a multi-ref string."""
    result = parse_thml_refs("1Timm 4:8, 6:3-6")
    assert result == ["1Tim.4.8", "1Tim.6.3"]


# ---------------------------------------------------------------------------
# Known typo corrections
# ---------------------------------------------------------------------------

def test_typo_1timm():
    """'1Timm' corrected to '1Tim'."""
    assert parse_thml_refs("1Timm 3:2") == ["1Tim.3.2"]


def test_typo_1chron():
    """'1Chron' corrected to '1Chr'."""
    assert parse_thml_refs("1Chron 3:10") == ["1Chr.3.10"]


def test_typo_1kings():
    """'1Kings' corrected to '1Kgs'."""
    assert parse_thml_refs("1Kings 10:1") == ["1Kgs.10.1"]


def test_typo_2kings():
    """'2Kings' corrected to '2Kgs'."""
    assert parse_thml_refs("2Kings 5:1") == ["2Kgs.5.1"]


def test_typo_1thes():
    """'1Thes' corrected to '1Thess'."""
    assert parse_thml_refs("1Thes 4:13") == ["1Thess.4.13"]


def test_typo_2thes():
    """'2Thes' corrected to '2Thess'."""
    assert parse_thml_refs("2Thes 2:3") == ["2Thess.2.3"]


def test_typo_eze():
    """'Eze' corrected to 'Ezek'."""
    assert parse_thml_refs("Eze 37:1") == ["Ezek.37.1"]


def test_typo_ex():
    """'Ex' corrected to 'Exod'."""
    assert parse_thml_refs("Ex 20:1") == ["Exod.20.1"]


# ---------------------------------------------------------------------------
# OSIS Psalms code is 'Ps' not 'Psa'
# ---------------------------------------------------------------------------

def test_psalms_osis_code():
    """OSIS code for Psalms is 'Ps' (not 'Psa')."""
    assert parse_thml_refs("Ps 23:1") == ["Ps.23.1"]


def test_psalms_full_name():
    """Full name 'Psalms' also maps to 'Ps'."""
    assert parse_thml_refs("Psalms 119:105") == ["Ps.119.105"]


# ---------------------------------------------------------------------------
# Edge cases that return []
# ---------------------------------------------------------------------------

def test_partial_without_book_context():
    """Bare ch:v with no prior book context -> skip, return []."""
    assert parse_thml_refs("25:41") == []


def test_unknown_book():
    """Unrecognised book abbreviation -> skip, return []."""
    assert parse_thml_refs("Foo 1:1") == []


def test_empty_string():
    """Empty string -> []."""
    assert parse_thml_refs("") == []


def test_whitespace_only():
    """Whitespace-only string -> []."""
    assert parse_thml_refs("   ") == []


# ---------------------------------------------------------------------------
# Separator normalisation (discovered by probing raw corpus)
# ---------------------------------------------------------------------------

def test_dot_separator_simple():
    """Dot used as chapter.verse separator -> normalised to colon."""
    assert parse_thml_refs("Mt 15.28") == ["Matt.15.28"]


def test_dot_separator_in_mixed_string():
    """Dot and colon separators can appear in the same passage string."""
    result = parse_thml_refs("Ps 98:1, Is 51.9, 52:10, 63:5")
    assert result == ["Ps.98.1", "Isa.51.9", "Isa.52.10", "Isa.63.5"]


def test_verse_continuation_dot():
    """'De 32:11.12' -- .12 is a verse continuation, not a separator; returns start verse."""
    result = parse_thml_refs("De 32:11.12, Ps 91:4")
    assert result == ["Deut.32.11", "Ps.91.4"]


def test_semicolon_as_chv_separator():
    """Semicolon used as chapter:verse separator ('Jn 12;4' -> John 12:4)."""
    assert parse_thml_refs("Jn 12;4") == ["John.12.4"]


def test_semicolon_as_chv_does_not_affect_normal_refs():
    """'1Sam 28:3;2Kgs 21:18' -- semicolon is a group separator here, not ch:v."""
    result = parse_thml_refs("1Sam 28:3;2Kgs 21:18")
    assert result == ["1Sam.28.3", "2Kgs.21.18"]


def test_space_after_colon():
    """'Heb 10: 5' -- space after colon normalised before parsing."""
    assert parse_thml_refs("Heb 10: 5") == ["Heb.10.5"]


def test_space_after_colon_in_list():
    """Multiple refs with space-after-colon in a comma-separated list."""
    result = parse_thml_refs("Php 2: 8, 9, Heb 2: 9,10")
    assert result == ["Phil.2.8", "Phil.2.9", "Heb.2.9", "Heb.2.10"]


def test_cross_chapter_range():
    """Cross-chapter range like 'Acts 24:1-25:27' -> start verse only."""
    assert parse_thml_refs("Acts 24:1-25:27") == ["Acts.24.1"]


def test_bare_verse_range():
    """Bare verse range '7-9' uses current book + chapter, returns start."""
    result = parse_thml_refs("Isa 53:2,3,7-9,12")
    assert result == ["Isa.53.2", "Isa.53.3", "Isa.53.7", "Isa.53.12"]


def test_bare_verse_range_mid_list():
    """Bare verse range embedded in a longer multi-ref string."""
    result = parse_thml_refs("Mt 26:14-16,47-50")
    assert result == ["Matt.26.14", "Matt.26.47"]


# ---------------------------------------------------------------------------
# Corpus-confirmed abbreviations (high-frequency gaps from probe)
# ---------------------------------------------------------------------------

def test_abbrev_php_philippians():
    """'Php' (590 occurrences in corpus) -> Phil."""
    assert parse_thml_refs("Php 4:13") == ["Phil.4.13"]


def test_abbrev_de_deuteronomy():
    """'De' (407 occurrences) -> Deut."""
    assert parse_thml_refs("De 6:4") == ["Deut.6.4"]


def test_abbrev_nu_numbers():
    """'Nu' (235 occurrences) -> Num."""
    assert parse_thml_refs("Nu 6:24") == ["Num.6.24"]


def test_abbrev_he_hebrews():
    """'He' (47 occurrences) -> Heb (unambiguous inside scripRef tags)."""
    assert parse_thml_refs("He 11:1") == ["Heb.11.1"]


def test_abbrev_ro_romans():
    """'Ro' (23 occurrences) -> Rom."""
    assert parse_thml_refs("Ro 8:28") == ["Rom.8.28"]


def test_abbrev_ac_acts():
    """'Ac' (33 occurrences) -> Acts."""
    assert parse_thml_refs("Ac 2:38") == ["Acts.2.38"]


def test_abbrev_lu_luke():
    """'Lu' (58 occurrences) -> Luke."""
    assert parse_thml_refs("Lu 2:14") == ["Luke.2.14"]


def test_abbrev_mr_mark():
    """'Mr' (20 occurrences) -> Mark."""
    assert parse_thml_refs("Mr 16:16") == ["Mark.16.16"]


def test_abbrev_1jo_1john():
    """'1Jo' (17 occurrences) -> 1John."""
    assert parse_thml_refs("1Jo 3:16") == ["1John.3.16"]


def test_abbrev_joh_john():
    """'Joh' (16 occurrences) -> John."""
    assert parse_thml_refs("Joh 3:16") == ["John.3.16"]


def test_typo_gall_galatians():
    """'Gall' (64 occurrences) -> Gal."""
    assert parse_thml_refs("Gall 5:22") == ["Gal.5.22"]


def test_typo_hoss_hosea():
    """'Hoss' (45 occurrences) -> Hos."""
    assert parse_thml_refs("Hoss 11:1") == ["Hos.11.1"]


def test_typo_romm_romans():
    """'Romm' (18 occurrences) -> Rom."""
    assert parse_thml_refs("Romm 3:23") == ["Rom.3.23"]


# ---------------------------------------------------------------------------
# HelloAO digit-after-abbreviation format (parse_thml_refs)
# ---------------------------------------------------------------------------

def test_helloao_pe2():
    """'Pe2' (HelloAO 2 Peter) -> 2Pet."""
    assert parse_thml_refs("Pe2 3:5") == ["2Pet.3.5"]


def test_helloao_sa1():
    """'Sa1' (HelloAO 1 Samuel) -> 1Sam."""
    assert parse_thml_refs("Sa1 17:4") == ["1Sam.17.4"]


def test_helloao_co1():
    """'Co1' (HelloAO 1 Corinthians) -> 1Cor."""
    assert parse_thml_refs("Co1 1:9") == ["1Cor.1.9"]


def test_helloao_jo1():
    """'Jo1' (HelloAO 1 John) -> 1John."""
    assert parse_thml_refs("Jo1 1:1") == ["1John.1.1"]


def test_helloao_ch2():
    """'Ch2' (HelloAO 2 Chronicles) -> 2Chr."""
    assert parse_thml_refs("Ch2 7:14") == ["2Chr.7.14"]


def test_helloao_sol():
    """'Sol' (HelloAO Song of Solomon) -> Song."""
    assert parse_thml_refs("Sol 2:1") == ["Song.2.1"]


def test_helloao_plm():
    """'Plm' (HelloAO Philemon) -> Phlm."""
    assert parse_thml_refs("Plm 1:1") == ["Phlm.1.1"]


def test_helloao_jde():
    """'Jde' (HelloAO Jude) -> Jude."""
    assert parse_thml_refs("Jde 1:3") == ["Jude.1.3"]


def test_helloao_kg1():
    """'Kg1' (HelloAO 1 Kings) -> 1Kgs."""
    assert parse_thml_refs("Kg1 3:9") == ["1Kgs.3.9"]


def test_helloao_kg2():
    """'Kg2' (HelloAO 2 Kings) -> 2Kgs."""
    assert parse_thml_refs("Kg2 5:1") == ["2Kgs.5.1"]


def test_helloao_sa2():
    """'Sa2' (HelloAO 2 Samuel) -> 2Sam."""
    assert parse_thml_refs("Sa2 7:12") == ["2Sam.7.12"]


def test_helloao_th1():
    """'Th1' (HelloAO 1 Thessalonians) -> 1Thess."""
    assert parse_thml_refs("Th1 4:16") == ["1Thess.4.16"]


def test_helloao_ti2():
    """'Ti2' (HelloAO 2 Timothy) -> 2Tim."""
    assert parse_thml_refs("Ti2 3:16") == ["2Tim.3.16"]


def test_helloao_pe1():
    """'Pe1' (HelloAO 1 Peter) -> 1Pet."""
    assert parse_thml_refs("Pe1 5:7") == ["1Pet.5.7"]


def test_helloao_jo3():
    """'Jo3' (HelloAO 3 John) -> 3John."""
    assert parse_thml_refs("Jo3 1:4") == ["3John.1.4"]


# ---------------------------------------------------------------------------
# extract_refs_from_text
# ---------------------------------------------------------------------------

def test_extract_refs_simple():
    """Basic citation extracted from surrounding prose."""
    assert extract_refs_from_text("Compare Luk 1:2 in context.") == ["Luke.1.2"]


def test_extract_refs_range_drops_end():
    """Verse range: only start verse returned."""
    assert extract_refs_from_text("See Exo 20:9-11 for the commandment.") == ["Exod.20.9"]


def test_extract_refs_helloao_numbered_book():
    """HelloAO digit-after format extracted from text."""
    assert extract_refs_from_text("As in Pe2 3:5, the earth perished.") == ["2Pet.3.5"]


def test_extract_refs_multiple_citations():
    """Multiple citations extracted preserving order."""
    result = extract_refs_from_text("See Gen 12:3 and Gen 22:18 for the promise.")
    assert result == ["Gen.12.3", "Gen.22.18"]


def test_extract_refs_deduplication():
    """Duplicate citations returned only once."""
    result = extract_refs_from_text("Gen 12:3 repeats the promise of Gen 12:3.")
    assert result == ["Gen.12.3"]


def test_extract_refs_unknown_book_skipped():
    """Unknown abbreviation silently skipped; known ones still returned."""
    result = extract_refs_from_text("See Foo 1:1 and Luk 1:2 for details.")
    assert result == ["Luke.1.2"]


def test_extract_refs_empty():
    """Empty input returns []."""
    assert extract_refs_from_text("") == []


def test_extract_refs_no_citations():
    """Text with no scripture citations returns []."""
    assert extract_refs_from_text("This is a general theological statement.") == []


def test_extract_refs_lowercase_abbreviation():
    """Lowercase abbreviations matched case-insensitively."""
    assert extract_refs_from_text("as in gen 12:3 and luk 1:2") == ["Gen.12.3", "Luke.1.2"]


def test_extract_refs_full_book_name():
    """Full book names matched."""
    assert extract_refs_from_text("in Genesis 12:3 and Revelation 22:17") == ["Gen.12.3", "Rev.22.17"]


def test_extract_refs_mixed_case_forms():
    """Mix of uppercase, lowercase, and full-name forms."""
    result = extract_refs_from_text("Luk 1:2 and genesis 12:3 and Acts 2:38")
    assert result == ["Luke.1.2", "Gen.12.3", "Acts.2.38"]


def test_extract_refs_noise_words_not_matched():
    """Common English words near ch:v patterns are not matched as books."""
    # 'and', 'of', 'the' are 2-3 letter words but not in _BOOK_LOOKUP
    # single-letter words are excluded by the 2-char minimum
    result = extract_refs_from_text("and 12:3 or 5:6 a 1:1")
    assert result == []


def test_extract_refs_parenthesized():
    """Citations inside parentheses are extracted."""
    result = extract_refs_from_text("the Sabbath (Exo 20:9-11; Exo 31:12-17)")
    assert "Exod.20.9" in result
    assert "Exod.31.12" in result


# ---------------------------------------------------------------------------
# translate_hebrew_to_english
# ---------------------------------------------------------------------------

from build.scripts.validate_osis import (  # noqa: E402
    translate_hebrew_to_english,
    validate_osis_ref,
)


class TestTranslateHebrewToEnglish:
    def test_psalm_with_superscription_remaps(self):
        """Ps.44.27 (Hebrew) -> Ps.44.26 (English): Ps 44 has a superscription."""
        assert translate_hebrew_to_english("Ps.44.27") == "Ps.44.26"

    def test_psalm_superscription_verse1_returns_none(self):
        """Ps.3.1 -> None: v1 is the superscription itself, no English equivalent."""
        assert translate_hebrew_to_english("Ps.3.1") is None

    def test_psalm_without_superscription_returns_none(self):
        """Ps.1.6 -> None: Ps 1 has no superscription, numbering is identical."""
        assert translate_hebrew_to_english("Ps.1.6") is None

    def test_nt_ref_returns_none(self):
        """John.3.16 -> None: NT books are not affected by Hebrew superscription offset."""
        assert translate_hebrew_to_english("John.3.16") is None

    def test_lxx_esther_addition_remaps(self):
        """Esth.14.11 -> AddEsth.14.11: continuous-numbering LXX Esther addition."""
        assert translate_hebrew_to_english("Esth.14.11") == "AddEsth.14.11"

    def test_lxx_esther_all_dropped_refs_remap(self):
        """All 6 previously-dropped Esth addition refs reroute correctly."""
        assert translate_hebrew_to_english("Esth.14.2") == "AddEsth.14.2"
        assert translate_hebrew_to_english("Esth.14.13") == "AddEsth.14.13"
        assert translate_hebrew_to_english("Esth.14.16") == "AddEsth.14.16"
        assert translate_hebrew_to_english("Esth.15.1") == "AddEsth.15.1"
        assert translate_hebrew_to_english("Esth.16.18") == "AddEsth.16.18"

    def test_lxx_esther_chapter_boundary(self):
        """Esth ch.10+ -> AddEsth; Esth ch.9 is canonical and returns None."""
        assert translate_hebrew_to_english("Esth.10.1") == "AddEsth.10.1"
        assert translate_hebrew_to_english("Esth.9.1") is None

    def test_daniel_prazarah_remaps(self):
        """Dan.3.31 -> PrAzar.1.8: LXX Prayer of Azariah inserted after Dan 3:23."""
        assert translate_hebrew_to_english("Dan.3.31") == "PrAzar.1.8"
        assert translate_hebrew_to_english("Dan.3.32") == "PrAzar.1.9"
        assert translate_hebrew_to_english("Dan.3.33") == "PrAzar.1.10"
        assert translate_hebrew_to_english("Dan.3.39") == "PrAzar.1.16"

    def test_daniel_prazarah_boundary(self):
        """Dan.3.24 -> PrAzar.1.1 (first verse after the offset); Dan.3.23 is canonical."""
        assert translate_hebrew_to_english("Dan.3.24") == "PrAzar.1.1"
        assert translate_hebrew_to_english("Dan.3.23") is None

    def test_daniel_ch6_29_returns_none(self):
        """Dan.6.29 has no known addition mapping — left dropped."""
        assert translate_hebrew_to_english("Dan.6.29") is None

    # --- Double superscription Psalms (Ps 51, 52, 60) ---

    def test_psalm_double_superscription_51_21(self):
        """Ps.51.21 (KD source) -> Ps.51.19 via double-superscription offset."""
        assert translate_hebrew_to_english("Ps.51.21") == "Ps.51.19"

    def test_psalm_double_superscription_52_11(self):
        """Ps.52.11 (KD source) -> Ps.52.9 via double-superscription offset."""
        assert translate_hebrew_to_english("Ps.52.11") == "Ps.52.9"

    def test_psalm_double_superscription_60_14(self):
        """Ps.60.14 (KD source) -> Ps.60.12 via double-superscription offset."""
        assert translate_hebrew_to_english("Ps.60.14") == "Ps.60.12"

    def test_psalm_double_superscription_verse_2_returns_none(self):
        """Ps.51.2 -> None: v.2 is the second superscription, no English equivalent."""
        assert translate_hebrew_to_english("Ps.51.2") is None

    def test_psalm_double_superscription_verse_1_returns_none(self):
        """Ps.51.1 -> None: v.1 is the first superscription."""
        assert translate_hebrew_to_english("Ps.51.1") is None

    def test_psalm_double_superscription_body_start(self):
        """Ps.51.3 -> Ps.51.1: first body verse in double-super Psalm."""
        assert translate_hebrew_to_english("Ps.51.3") == "Ps.51.1"

    # --- Hosea 2 chapter boundary ---

    def test_hosea_2_24_remaps(self):
        """Hos.2.24 (KD source, Hebrew ch.2 body) -> Hos.2.22."""
        assert translate_hebrew_to_english("Hos.2.24") == "Hos.2.22"

    def test_hosea_2_body_start(self):
        """Hos.2.3 (Hebrew body start) -> Hos.2.1."""
        assert translate_hebrew_to_english("Hos.2.3") == "Hos.2.1"

    def test_hosea_2_verse_2_returns_none(self):
        """Hos.2.2 -> None: maps to English Hos 1:11, handled as valid by caller."""
        assert translate_hebrew_to_english("Hos.2.2") is None

    # --- Job 40 Luther Bible / KD chapter boundary ---

    def test_job_40_27_remaps(self):
        """Job.40.27 (KD/Luther Bible ch.40 extends into English ch.41) -> Job.41.3."""
        assert translate_hebrew_to_english("Job.40.27") == "Job.41.3"

    def test_job_40_29_remaps(self):
        """Job.40.29 -> Job.41.5."""
        assert translate_hebrew_to_english("Job.40.29") == "Job.41.5"

    def test_job_40_30_remaps(self):
        """Job.40.30 -> Job.41.6."""
        assert translate_hebrew_to_english("Job.40.30") == "Job.41.6"

    def test_job_40_boundary_verse_25(self):
        """Job.40.25 -> Job.41.1: first verse that crosses the chapter boundary."""
        assert translate_hebrew_to_english("Job.40.25") == "Job.41.1"

    def test_job_40_within_range_returns_none(self):
        """Job.40.24 -> None: last valid English verse, no translation needed."""
        assert translate_hebrew_to_english("Job.40.24") is None

    def test_remapped_ref_passes_validation(self):
        """Ps.44.27 translates to Ps.44.26, which must pass validate_osis_ref."""
        translated = translate_hebrew_to_english("Ps.44.27")
        assert translated == "Ps.44.26"
        ok, reason = validate_osis_ref(translated)
        assert ok, f"translated ref failed validation: {reason}"

    def test_psalm_2_no_offset(self):
        """Ps.2.12 -> None: Ps 2 is in the no-superscription set."""
        assert translate_hebrew_to_english("Ps.2.12") is None

    def test_psalm_3_verse2_remaps(self):
        """Ps.3.2 (Hebrew) -> Ps.3.1 (English): Ps 3 has superscription."""
        assert translate_hebrew_to_english("Ps.3.2") == "Ps.3.1"

    def test_malformed_ref_returns_none(self):
        """Non-OSIS-formatted string returns None without error."""
        assert translate_hebrew_to_english("not-a-ref") is None

    def test_two_segment_ref_returns_none(self):
        """Chapter-level ref (two segments) returns None."""
        assert translate_hebrew_to_english("Ps.44") is None


# ---------------------------------------------------------------------------
# parse_maclaren_ref  (Roman-numeral chapter format)
# All cases confirmed against real raw values in maclaren-expositions.json
# ---------------------------------------------------------------------------

def test_mac_empty_string():
    """Empty raw -> []."""
    assert parse_maclaren_ref("") == []


def test_mac_simple_comma_separated_verses():
    """GENESIS xii. 6, 7 -> two individual OSIS refs."""
    assert parse_maclaren_ref("GENESIS xii. 6, 7") == ["Gen.12.6", "Gen.12.7"]


def test_mac_verse_range_start_only():
    """ACTS i. 1-14 -> start verse only (matches existing normalizer convention)."""
    assert parse_maclaren_ref("ACTS i. 1-14") == ["Acts.1.1"]


def test_mac_all_caps_abbreviated_period():
    """MATT. vi. 11 -> Matt.6.11 (book abbreviated with trailing period)."""
    assert parse_maclaren_ref("MATT. vi. 11") == ["Matt.6.11"]


def test_mac_mixed_case_no_period():
    """Mark ix. 23 -> Mark.9.23."""
    assert parse_maclaren_ref("Mark ix. 23") == ["Mark.9.23"]


def test_mac_cross_chapter_range_roman():
    """GENESIS i. 26-ii. 3 -> Gen.1.26 (cross-chapter Roman range, start only)."""
    assert parse_maclaren_ref("GENESIS i. 26-ii. 3") == ["Gen.1.26"]


def test_mac_cross_chapter_range_roman_2():
    """Mark viii. 27-ix. 1 -> Mark.8.27 (cross-chapter Roman range)."""
    assert parse_maclaren_ref("Mark viii. 27-ix. 1") == ["Mark.8.27"]


def test_mac_semicolon_new_roman_chapter():
    """ACTS xiii. 44-52; xiv. 1-7 -> two refs, second uses same book."""
    assert parse_maclaren_ref("ACTS xiii. 44-52; xiv. 1-7") == [
        "Acts.13.44", "Acts.14.1"
    ]


def test_mac_semicolon_bare_verse_range():
    """ACTS ix. 1-12; 17-20 -> start of each segment."""
    assert parse_maclaren_ref("ACTS ix. 1-12; 17-20") == ["Acts.9.1", "Acts.9.17"]


def test_mac_comma_chapterverse_separator():
    """ACTS xi, 24 -> Acts.11.24 (comma as book-chapter separator)."""
    assert parse_maclaren_ref("ACTS xi, 24") == ["Acts.11.24"]


def test_mac_rv_suffix():
    """JER. x. 16, R.V -> Jer.10.16 (R.V annotation stripped)."""
    assert parse_maclaren_ref("JER. x. 16, R.V") == ["Jer.10.16"]


def test_mac_rv_with_space():
    """Mark i. 30, 31, R. V -> two refs (R. V annotation stripped)."""
    assert parse_maclaren_ref("Mark i. 30, 31, R. V") == ["Mark.1.30", "Mark.1.31"]


def test_mac_rv_period():
    """Phil. i. 9-11, R.V. -> Phil.1.9 (R.V. with trailing period stripped)."""
    assert parse_maclaren_ref("Phil. i. 9-11, R.V.") == ["Phil.1.9"]


def test_mac_dash_suffix():
    """ISAIAH liv, 10.-- -> Isa.54.10 (trailing .-- garbage stripped)."""
    assert parse_maclaren_ref("ISAIAH liv, 10.--") == ["Isa.54.10"]


def test_mac_numbered_book():
    """1 Peter i. 1 -> 1Pet.1.1."""
    assert parse_maclaren_ref("1 Peter i. 1") == ["1Pet.1.1"]


def test_mac_arabic_chapter_with_semicolon():
    """ISAIAH 1,1-9; 16-20 -> Isa.1.1 and Isa.1.16 (Arabic chapter, bare continuation)."""
    assert parse_maclaren_ref("ISAIAH 1,1-9; 16-20") == ["Isa.1.1", "Isa.1.16"]


def test_mac_three_comma_verses():
    """ACTS ii. 2, 3, 17 -> three individual OSIS refs."""
    assert parse_maclaren_ref("ACTS ii. 2, 3, 17") == [
        "Acts.2.2", "Acts.2.3", "Acts.2.17"
    ]


def test_mac_trailing_comma():
    """Mark xii. 34, -> Mark.12.34 (trailing comma stripped)."""
    assert parse_maclaren_ref("Mark xii. 34,") == ["Mark.12.34"]


def test_mac_high_roman_numerals():
    """PSALMS cxi. 3; cxii. 3 -> Ps.111.3 and Ps.112.3."""
    assert parse_maclaren_ref("PSALMS cxi. 3; cxii. 3") == ["Ps.111.3", "Ps.112.3"]


def test_mac_eph_abbreviated():
    """Eph. iv. 24 -> Eph.4.24 (lowercase abbreviated book with trailing period)."""
    assert parse_maclaren_ref("Eph. iv. 24") == ["Eph.4.24"]


def test_mac_no_period_after_chapter():
    """Mark vii 33, 34 -> Mark.7.33, Mark.7.34 (no period after chapter)."""
    assert parse_maclaren_ref("Mark vii 33, 34") == ["Mark.7.33", "Mark.7.34"]


def test_mac_no_period_chapter_no_separator():
    """ISAIAH liii 1 -> Isa.53.1 (no period, space only between chapter and verse)."""
    assert parse_maclaren_ref("ISAIAH liii 1") == ["Isa.53.1"]


def test_mac_saint_prefix():
    """ST. MATT. xxvii. 11-26 -> Matt.27.11 (Saint prefix stripped)."""
    assert parse_maclaren_ref("ST. MATT. xxvii. 11-26") == ["Matt.27.11"]


def test_mac_habbakkuk_typo():
    """HABBAKKUK iii. 19 -> Hab.3.19 (double-B typo in source corrected in lookup)."""
    assert parse_maclaren_ref("HABBAKKUK iii. 19") == ["Hab.3.19"]


def test_mac_no_space_between_book_and_chapter():
    """MATT.xxii.34-46 -> Matt.22.34 (no spaces, chained periods)."""
    assert parse_maclaren_ref("MATT.xxii.34-46") == ["Matt.22.34"]


def test_mac_book_comma_chapter():
    """DEUT, xxxii.9 -> Deut.32.9 (comma as book-to-chapter separator)."""
    assert parse_maclaren_ref("DEUT, xxxii.9") == ["Deut.32.9"]


def test_mac_cross_chapter_same_book():
    """JOSHUA xxi. 43-45; xxii. 1-9 -> Josh.21.43, Josh.22.1."""
    assert parse_maclaren_ref("JOSHUA xxi. 43-45; xxii. 1-9") == [
        "Josh.21.43", "Josh.22.1"
    ]


def test_mac_col_abbreviated():
    """COL. i. 2 -> Col.1.2 (Colossians abbreviated)."""
    assert parse_maclaren_ref("COL. i. 2") == ["Col.1.2"]


def test_mac_arabic_chapter_matt():
    """MATT. 1. 1-16 -> Matt.1.1 (Arabic chapter 1, range)."""
    assert parse_maclaren_ref("MATT. 1. 1-16") == ["Matt.1.1"]


def test_mac_comma_verse_list_no_space():
    """Mark v. 28,34 -> Mark.5.28, Mark.5.34 (comma list without spaces)."""
    assert parse_maclaren_ref("Mark v. 28,34") == ["Mark.5.28", "Mark.5.34"]


def test_mac_multiple_comma_ranges():
    """Mark v. 22-24, 35-43 -> Mark.5.22, Mark.5.35 (two ranges in same chapter)."""
    assert parse_maclaren_ref("Mark v. 22-24, 35-43") == ["Mark.5.22", "Mark.5.35"]


def test_mac_and_as_verse_separator():
    """ISAIAH xl. 26 and 29 -> Isa.40.26, Isa.40.29 ('and' as verse separator)."""
    assert parse_maclaren_ref("ISAIAH xl. 26 and 29") == ["Isa.40.26", "Isa.40.29"]


def test_mac_dot_as_verse_list_separator():
    """LUKE vii. 4. 6. 7 -> Luke.7.4, Luke.7.6, Luke.7.7 (dots as verse separators)."""
    assert parse_maclaren_ref("LUKE vii. 4. 6. 7") == [
        "Luke.7.4", "Luke.7.6", "Luke.7.7"
    ]


def test_mac_colon_as_range_separator():
    """LUKE x. 1-11: 17-20 -> Luke.10.1, Luke.10.17 (colon as range-group separator)."""
    assert parse_maclaren_ref("LUKE x. 1-11: 17-20") == ["Luke.10.1", "Luke.10.17"]


# ---------------------------------------------------------------------------
# Run directly for quick feedback
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
