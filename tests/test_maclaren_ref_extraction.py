# tests/test_maclaren_ref_extraction.py
"""Regression tests for _dash_ref_from_content in gutenberg_maclaren.py.

Covers all four failure modes from the 2026-04-17 dip-check:
  Pattern 1: Numbered-book references (1 Samuel, 2 Peter, 1 John, etc.)
  Pattern 2: (R.V.) suffix after verse range
  Pattern 3a: Em-dash separator (U+2014)
  Pattern 3b: Single-dash separator
  Pattern 4: Inline ref after sentence punctuation (no separator)
"""
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build.parsers.gutenberg_maclaren import _dash_ref_from_content


# ---- Regression: already-working cases must not break ----

def test_plain_double_dash_uppercase_book():
    block = '"He was in the beginning with God."--JOHN i. 2.'
    assert _dash_ref_from_content([block]) == "JOHN i. 2"


def test_plain_double_dash_abbreviated_book():
    block = '"For by grace are ye saved."--EPH. ii. 8.'
    assert _dash_ref_from_content([block]) == "EPH. ii. 8"


def test_verse_range_no_annotation():
    block = '"The Lord is my shepherd."--PSALM xxiii. 1-6.'
    assert _dash_ref_from_content([block]) == "PSALM xxiii. 1-6"


def test_verse_range_hyphen_not_stolen_as_separator():
    # '-16' in '3-16' must not match as a separator; full ref must be extracted
    block = "the Lord, and dwelt in the land of Nod, on the east of Eden.' GENESIS iv. 3-16."
    assert _dash_ref_from_content([block]) == "GENESIS iv. 3-16"


# ---- Pattern 1: Numbered-book references ----

def test_numbered_book_double_dash_nt_abbreviated():
    # Entry 1175: '--2 THESS. ii. 16, 17.'
    block = '"Now our Lord Jesus Christ himself."--2 THESS. ii. 16, 17.'
    assert _dash_ref_from_content([block]) == "2 THESS. ii. 16, 17"


def test_numbered_book_double_dash_nt_lowercase():
    # Entry 1260: '--1 John iv. 10.'
    block = '"Herein is love."--1 John iv. 10.'
    assert _dash_ref_from_content([block]) == "1 John iv. 10"


def test_numbered_book_double_dash_ot_kings():
    # Entry 175: '--1 KINGS i. 28-39.'
    block = '"And the king sware."--1 KINGS i. 28-39.'
    assert _dash_ref_from_content([block]) == "1 KINGS i. 28-39"


def test_numbered_book_double_dash_nt_peter():
    # Entry 1227: '--1 Peter i. 8.'
    block = '"Whom having not seen, ye love."--1 Peter i. 8.'
    assert _dash_ref_from_content([block]) == "1 Peter i. 8"


def test_numbered_book_double_dash_chron():
    # Entry 219: '--1 CHRON. xii. 33.'
    block = '"Of Zebulun, such as went forth."--1 CHRON. xii. 33.'
    assert _dash_ref_from_content([block]) == "1 CHRON. xii. 33"


def test_numbered_book_double_dash_cor():
    # Entry 1099: '--2 COR. v. 5.'
    block = '"Now he that hath wrought us."--2 COR. v. 5.'
    assert _dash_ref_from_content([block]) == "2 COR. v. 5"


# ---- Pattern 1 + 3b: Numbered book with single dash ----

def test_numbered_book_single_dash():
    # Entry 161: '-2 SAMUEL vi.11.' (single dash + numbered book)
    block = "as he passed by, and the ark passed with it.'-2 SAMUEL vi.11."
    assert _dash_ref_from_content([block]) == "2 SAMUEL vi.11"


def test_single_dash_uppercase_non_numbered_book():
    # Single dash before a non-numbered uppercase book (Pattern 3b standalone)
    block = "As it is written, the just shall live by faith.'-GALA. iii. 11."
    assert _dash_ref_from_content([block]) == "GALA. iii. 11"


# ---- Pattern 2: (R.V.) suffix ----

def test_rv_suffix_psalm():
    # Entry 339: '--PSALM xlv. 2-7 (R.V.).'
    block = '"Thou art fairer than the children of men." --PSALM xlv. 2-7 (R.V.).'
    assert _dash_ref_from_content([block]) == "PSALM xlv. 2-7"


def test_rv_suffix_phil():
    # Entry 1134: '--PHIL. ii. 14-16 (R.V.).'
    block = '"without blemish in the midst of a crooked generation."--PHIL. ii. 14-16 (R.V.).'
    assert _dash_ref_from_content([block]) == "PHIL. ii. 14-16"


def test_rv_suffix_with_space():
    # Entry 5: '--GENESIS iv. 7 (R. V.).' -- space between R. and V.
    block = "'...thou shalt rule over him.'--GENESIS iv. 7 (R. V.)."
    assert _dash_ref_from_content([block]) == "GENESIS iv. 7"


def test_rv_margin_suffix():
    # Entry 218: '--1 CHRON. vi. 32 (R.V. margin).'
    block = "'...according to their order.'--1 CHRON. vi. 32 (R.V. margin)."
    assert _dash_ref_from_content([block]) == "1 CHRON. vi. 32"


def test_av_suffix():
    # Entry 510: '--HOSEA xiii. 9 (A.V.).'
    block = "'O Israel, thou hast destroyed thyself; but in Me is thine help.'--HOSEA xiii. 9 (A.V.)."
    assert _dash_ref_from_content([block]) == "HOSEA xiii. 9"


# ---- Pattern 3a: Em dash separator ----

def test_em_dash_separator():
    # Entry 876: U+2014 before JOHN xiii. 27.
    block = "That thou doest, do quickly.\u2014JOHN xiii. 27."
    assert _dash_ref_from_content([block]) == "JOHN xiii. 27"


# ---- Multi-block: reference in second block ----

def test_ref_in_second_block():
    block0 = '"For the Lord himself shall descend from heaven'
    block1 = 'with a shout."--1 THESS. iv. 16.'
    assert _dash_ref_from_content([block0, block1]) == "1 THESS. iv. 16"


# ---- Pattern 4: Inline ref -- no separator, follows sentence punctuation ----

def test_inline_ref_after_exclamation():
    # Entry 22: 'Thee! GENESIS xvii. 18.' -- no dash, ref after exclamation mark
    block = "And thou didst say unto me, Multiply thy seed as the stars of Thee! GENESIS xvii. 18."
    assert _dash_ref_from_content([block]) == "GENESIS xvii. 18"


def test_inline_ref_after_period_quote():
    # Ref after closing-quote + period: '...his name." JOHN i. 12.'
    block = 'He gave them power to become sons of God, even to them that believe on his name." JOHN i. 12.'
    assert _dash_ref_from_content([block]) == "JOHN i. 12"


# ---- Pattern 4 must NOT fire on prose-only uppercase words ----

def test_inline_no_false_positive_on_allcaps_prose():
    # ALL-CAPS word at end of sentence with no chapter.verse should not match
    block = "He is the LORD. AMEN."
    assert _dash_ref_from_content([block]) is None


def test_inline_no_false_positive_mid_sentence():
    # Book-name-like token after a comma (not [.!?]) -- guard must reject it
    block = "He spoke about the book, JOHN i. 12 and related matters."
    assert _dash_ref_from_content([block]) is None


# ---- Sanity: no digit = no match ----

def test_no_digit_returns_none():
    # Sanity check: if the captured group has no digit, reject it
    block = '"Some text."--SOMEWORDS without.'
    assert _dash_ref_from_content([block]) is None


def test_no_alpha_returns_none():
    # Guard: if a widened separator steals a hyphen from a verse range,
    # leaving only digits (e.g. 'foo-16.'), reject the match.
    block = "foo-16."
    assert _dash_ref_from_content([block]) is None


# ---- No match at all ----

def test_no_separator_returns_none():
    block = "This block has no scripture reference at all, just prose."
    assert _dash_ref_from_content([block]) is None
