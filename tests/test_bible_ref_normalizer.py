"""test_bible_ref_normalizer.py
Unit tests for build.lib.bible_ref_normalizer.parse_thml_refs.

All cases derived from real examples confirmed in Barnes and Wesley SWORD modules.
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path so imports work when running directly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.bible_ref_normalizer import parse_thml_refs  # noqa: E402


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
