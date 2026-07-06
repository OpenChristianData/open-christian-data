"""test_hymnary_pd.py
TDD tests for hymnary_pd.py -- written before the parser.

Six test groups:
  1. parse_stanzas(full_text) -> list[str]
  2. parse_year_str(s) -> int | None
  3. parse_author_years(birth_str, death_str) -> tuple[int|None, int|None]
  4. detect_language(title, text) -> str
  5. slugify_title(text) -> str
  6. build_entry_id(title, author, hymnal_year, used_ids) -> str

All string fixtures anchored to real rows from oldest_pd_instances.csv.

Run with: py -3 -m pytest tests/test_hymnary_pd.py -v
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.parsers.hymnary_pd import (  # noqa: E402
    parse_stanzas,
    parse_year_str,
    parse_author_years,
    detect_language,
    slugify_title,
    build_entry_id,
)


# ===========================================================================
# Group 1: parse_stanzas(full_text) -> list[str]
# ===========================================================================
# Fixtures anchored to real rows from the Hymnary CSV.

# Real row: "A Babe is born in Bethlehem" (Hymnal for Church and Home, 1927)
_MULTI_STANZA = (
    "1 A Babe is born in Bethlehem,\r\nBethlehem,\r\n"
    "Rejoice, rejoice, Jerusalem,\r\nHallelujah, hallelujah.\r\n"
    "\r\n"
    "2 A lowly virgin gave Him birth,\r\nGave Him birth,\r\n"
    "Who rules the heavens and the earth,\r\nHallelujah, hallelujah."
)

# Real row: "At Bethlehem" (Clark, Luella) -- has Refrain section
_REFRAIN_TEXT = (
    "1 A Babe in the manger,\r\nA song in the sky;\r\n"
    "On earth benediction,\r\nRejoicing on high.\r\n"
    "\r\n"
    "Refrain:\r\nA Babe in the manger,\r\nA song in the sky;\r\n"
    "On earth benediction,\r\nRejoicing on high.\r\n"
    "\r\n"
    "2 A Prince and a Saviour,\r\nImmanuel, King;"
)


class TestParseStanzas:
    def test_splits_numbered_stanzas_on_blank_line(self):
        result = parse_stanzas(_MULTI_STANZA)
        assert len(result) == 2
        assert result[0].startswith("1 A Babe is born")
        assert result[1].startswith("2 A lowly virgin")

    def test_preserves_internal_line_breaks_as_newlines(self):
        result = parse_stanzas(_MULTI_STANZA)
        # Internal \r\n should be normalised to \n
        assert "\r" not in result[0]
        assert "\n" in result[0]

    def test_refrain_treated_as_own_stanza(self):
        result = parse_stanzas(_REFRAIN_TEXT)
        assert len(result) == 3
        assert result[1].startswith("Refrain:")

    def test_empty_text_returns_empty_list(self):
        assert parse_stanzas("") == []
        assert parse_stanzas("   ") == []

    def test_single_stanza_no_blank_line(self):
        result = parse_stanzas("Glory to God in the highest,\r\nin the highest!")
        assert len(result) == 1
        assert result[0] == "Glory to God in the highest,\nin the highest!"

    def test_strips_leading_trailing_whitespace_from_stanzas(self):
        text = "\r\n\r\n1 First stanza.\r\n\r\n2 Second stanza.\r\n\r\n"
        result = parse_stanzas(text)
        assert len(result) == 2
        assert not result[0].startswith("\n")
        assert not result[-1].endswith("\n")


# ===========================================================================
# Group 2: parse_year_str(s) -> int | None
# ===========================================================================

class TestParseYearStr:
    def test_valid_four_digit_year(self):
        assert parse_year_str("1869") == 1869

    def test_empty_string_returns_none(self):
        assert parse_year_str("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_year_str("   ") is None

    def test_semicolon_placeholder_returns_none(self):
        # Multi-author year placeholder from CSV
        assert parse_year_str(";") is None
        assert parse_year_str("; ") is None

    def test_multi_year_semicolon_returns_none(self):
        # "1783; 1877" -- ambiguous multi-author, not parseable as single year
        assert parse_year_str("1783; 1877") is None

    def test_non_numeric_returns_none(self):
        assert parse_year_str("ca. 1750") is None
        assert parse_year_str("unknown") is None

    def test_year_zero_or_negative_returns_none(self):
        assert parse_year_str("0") is None
        assert parse_year_str("-100") is None

    def test_unreasonably_future_year_returns_none(self):
        assert parse_year_str("3000") is None


# ===========================================================================
# Group 3: parse_author_years(birth_str, death_str) -> tuple[int|None, int|None]
# ===========================================================================
# Fixtures from real rows.

class TestParseAuthorYears:
    def test_single_author_with_both_years(self):
        # "Krauth, C. P., 1823-1883": birth='1823', death='1883'
        birth, death = parse_author_years("1823", "1883")
        assert birth == 1823
        assert death == 1883

    def test_empty_birth_and_death(self):
        birth, death = parse_author_years("", "")
        assert birth is None
        assert death is None

    def test_multi_author_birth_returns_none_for_both(self):
        # "1783; 1877" -- cannot attribute to a single author
        birth, death = parse_author_years("1783; 1877", "1872; 1970")
        assert birth is None
        assert death is None

    def test_birth_only(self):
        birth, death = parse_author_years("1823", "")
        assert birth == 1823
        assert death is None

    def test_death_only(self):
        birth, death = parse_author_years("", "1883")
        assert birth is None
        assert death == 1883

    def test_invalid_year_strings_return_none(self):
        birth, death = parse_author_years("ca. 1800", "after 1850")
        assert birth is None
        assert death is None


# ===========================================================================
# Group 4: detect_language(title, text) -> str
# ===========================================================================

class TestDetectLanguage:
    def test_ascii_title_and_text_returns_en(self):
        assert detect_language("A Babe is born in Bethlehem", "1 A Babe is born") == "en"

    def test_non_ascii_title_returns_mul(self):
        # Real row: Spanish hymn -- title has inverted ! (punctuation), text has accented u
        title = "\u00a1A Combatir!"
        text = "1 \u00a1A combatir! resuena la guerrera voz del buen Jes\u00fas"
        assert detect_language(title, text) == "mul"

    def test_non_ascii_text_only_returns_mul(self):
        # ASCII title but non-ASCII body (e.g. German or transliterated)
        assert detect_language("Praise Him", "Lob sei dem Herrn, \u00fcber alles Lob!") == "mul"

    def test_pure_ascii_with_punctuation_returns_en(self):
        # Common hymn punctuation should not trigger mul
        assert detect_language("O Come, All Ye Faithful", "O come, let us adore Him!") == "en"


# ===========================================================================
# Group 5: slugify_title(text) -> str
# ===========================================================================

class TestSlugifyTitle:
    def test_simple_ascii_title(self):
        assert slugify_title("At Bethlehem") == "at-bethlehem"

    def test_lowercases_all(self):
        assert slugify_title("Glory To God") == "glory-to-god"

    def test_strips_punctuation(self):
        assert slugify_title("O Come, All Ye Faithful!") == "o-come-all-ye-faithful"

    def test_collapses_multiple_spaces_to_single_hyphen(self):
        assert slugify_title("A   Babe  Is  Born") == "a-babe-is-born"

    def test_non_ascii_chars_replaced_with_ascii_or_removed(self):
        # Spanish exclamation mark should be dropped/replaced
        result = slugify_title("\u00a1A Combatir!")
        assert "\u00a1" not in result
        assert "a-combatir" in result or result == "a-combatir"

    def test_leading_trailing_hyphens_removed(self):
        result = slugify_title("--Glory--")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_numbers_kept(self):
        assert "23rd" in slugify_title("The 23rd Psalm")

    def test_empty_string_returns_untitled(self):
        assert slugify_title("") == "untitled"
        assert slugify_title("!!!") == "untitled"


# ===========================================================================
# Group 6: build_entry_id(title, author, hymnal_year, used_ids) -> str
# ===========================================================================

class TestBuildEntryId:
    def test_basic_id_from_title(self):
        used = set()
        result = build_entry_id("At Bethlehem", None, None, used)
        assert result == "at-bethlehem"
        assert "at-bethlehem" in used

    def test_collision_appends_author_slug(self):
        used = {"at-bethlehem"}
        result = build_entry_id("At Bethlehem", "Clark, Luella", None, used)
        assert result != "at-bethlehem"
        assert "clark" in result or "luella" in result

    def test_collision_with_author_appends_year(self):
        original = {"at-bethlehem", "at-bethlehem-clark"}
        used = set(original)
        result = build_entry_id("At Bethlehem", "Clark, Luella", 1900, used)
        assert result not in original  # new id does not collide with pre-existing ones
        assert "1900" in result
        assert result in used  # function records the chosen id

    def test_triple_collision_appends_counter(self):
        original = {"at-bethlehem", "at-bethlehem-clark", "at-bethlehem-clark-1900"}
        used = set(original)
        result = build_entry_id("At Bethlehem", "Clark, Luella", 1900, used)
        assert result not in original  # resolves to a new id beyond the three taken ones
        assert result in used

    def test_result_added_to_used_set(self):
        used = set()
        result = build_entry_id("Glory to God", None, None, used)
        assert result in used

    def test_no_author_no_year_collision_uses_counter(self):
        used = {"glory-to-god"}
        result = build_entry_id("Glory to God", None, None, used)
        assert result not in {"glory-to-god"}
        assert result in used

    def test_returns_kebab_case_only(self):
        used = set()
        result = build_entry_id("O Come, All Ye Faithful!", "Oakeley, Frederick, 1802-1880", 1852, used)
        assert result == result.lower()
        assert " " not in result
        assert "," not in result
