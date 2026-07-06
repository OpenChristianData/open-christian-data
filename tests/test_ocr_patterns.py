"""test_ocr_patterns.py -- unit tests for OCR scanner detector functions.

Run: py -3 -m pytest tests/test_ocr_patterns.py -v
Tasks 2 and 3 both add tests to this file.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_scanner import patterns  # noqa: E402


# ---------------------------------------------------------------------------
# Shared fixture: build a minimal DetectorContext for testing
# ---------------------------------------------------------------------------

def _make_ctx(**overrides) -> "patterns.DetectorContext":
    """Construct a stub DetectorContext. Use overrides to customise fields."""
    class _FakeDict:
        def __init__(self, known=None):
            self.known = {w.upper() for w in (known or [])}
        def check(self, token: str) -> bool:
            return token.upper() in self.known

    defaults = dict(
        source_id="test",
        entry_id="test.entry0",
        field_path="term",
        context_before="context before",
        context_after="context after",
        cand_id="cand-0001",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms=set(),
            enable_enchant=False,
        ),
        whitelist_terms=set(),
        whitelist_patterns=[],
        adjacent_prev=None,
        adjacent_next=None,
    )
    defaults.update(overrides)
    return patterns.DetectorContext(**defaults)


# ===========================================================================
# detect_digit_in_letter
# ===========================================================================

def test_digit_in_letter_positive_the0t0k0s():
    c = patterns.detect_digit_in_letter("THE0T0K0S", _make_ctx())
    assert c is not None
    assert c.reason == "digit_in_letter"
    assert c.tier == 1
    assert c.suggestion == "THEOTOKOS"
    assert c.suggestion_source == "digit_substitution_table"


def test_digit_in_letter_positive_the0t0k08():
    c = patterns.detect_digit_in_letter("THE0T0K08", _make_ctx())
    assert c is not None
    assert c.suggestion == "THEOTOKOS"  # 8 -> S


def test_digit_in_letter_positive_gl0ry():
    """Lowercase token with digit substitution."""
    c = patterns.detect_digit_in_letter("gl0ry", _make_ctx())
    assert c is not None
    assert c.reason == "digit_in_letter"
    assert "glory" in c.suggestion.lower()


def test_digit_in_letter_negative_zwingli():
    assert patterns.detect_digit_in_letter("ZWINGLI", _make_ctx()) is None


def test_digit_in_letter_negative_pure_year():
    assert patterns.detect_digit_in_letter("1980", _make_ctx()) is None


def test_digit_in_letter_negative_ad_with_period():
    """A.D. contains periods so the token-level regex should not match."""
    assert patterns.detect_digit_in_letter("A.D.", _make_ctx()) is None


def test_digit_in_letter_negative_chapter_verse():
    """3:16 contains a colon -- excluded by [^:] lookahead."""
    assert patterns.detect_digit_in_letter("3:16", _make_ctx()) is None


# ===========================================================================
# detect_ligature_bracket
# ===========================================================================

def test_ligature_bracket_positive_ecolampadius():
    c = patterns.detect_ligature_bracket("(ECOLAMPADIUS", _make_ctx())
    assert c is not None
    assert c.reason == "ligature_bracket"
    assert c.tier == 1
    assert c.suggestion == "OECOLAMPADIUS"


def test_ligature_bracket_positive_ealdhelm():
    c = patterns.detect_ligature_bracket("(EALDHELM", _make_ctx())
    assert c is not None
    assert c.suggestion == "OEALDHELM"


def test_ligature_bracket_positive_esar():
    c = patterns.detect_ligature_bracket("(ESAR", _make_ctx())
    assert c is not None


def test_ligature_bracket_negative_oecolampadius():
    """Correctly-spelled OE form must not be flagged."""
    assert patterns.detect_ligature_bracket("OECOLAMPADIUS", _make_ctx()) is None


def test_ligature_bracket_negative_parenthetical_lowercase():
    """(see) is a normal parenthetical, not a ligature."""
    assert patterns.detect_ligature_bracket("(see", _make_ctx()) is None


def test_ligature_bracket_negative_parenthetical_mixed():
    assert patterns.detect_ligature_bracket("(e.g.)", _make_ctx()) is None


# ===========================================================================
# detect_ligature_ae_loss
# ===========================================================================

def test_ligature_ae_loss_positive_cesar():
    c = patterns.detect_ligature_ae_loss("C(ESAR", _make_ctx())
    assert c is not None
    assert c.reason == "ligature_ae_loss"
    assert c.tier == 3  # demoted from Tier 1 -- 0% measured precision on SH


def test_ligature_ae_loss_positive_prelude():
    c = patterns.detect_ligature_ae_loss("pr(elude", _make_ctx())
    assert c is not None


def test_ligature_ae_loss_positive_diocesan():
    c = patterns.detect_ligature_ae_loss("DIOC(ESAN", _make_ctx())
    assert c is not None


def test_ligature_ae_loss_negative_caesar():
    assert patterns.detect_ligature_ae_loss("CAESAR", _make_ctx()) is None


def test_ligature_ae_loss_negative_leading_bracket():
    """(ECOLAMPADIUS starts at beginning -- ligature_bracket covers it, not ae_loss."""
    assert patterns.detect_ligature_ae_loss("(ECOLAMPADIUS", _make_ctx()) is None


def test_ligature_ae_loss_negative_standalone_paren():
    assert patterns.detect_ligature_ae_loss("(e.g.)", _make_ctx()) is None


# ===========================================================================
# detect_stray_pipe_backslash
# ===========================================================================

def test_stray_pipe_positive_chrst():
    c = patterns.detect_stray_pipe_backslash("CHR|ST", _make_ctx())
    assert c is not None
    assert c.reason == "stray_pipe_backslash"
    assert c.tier == 1
    assert c.suggestion is None  # no auto-suggestion


def test_stray_pipe_positive_book():
    c = patterns.detect_stray_pipe_backslash("b\\ok", _make_ctx())
    assert c is not None


def test_stray_pipe_positive_word():
    c = patterns.detect_stray_pipe_backslash("wor|d", _make_ctx())
    assert c is not None


def test_stray_pipe_negative_christ():
    assert patterns.detect_stray_pipe_backslash("CHRIST", _make_ctx()) is None


def test_stray_pipe_negative_book_clean():
    assert patterns.detect_stray_pipe_backslash("book", _make_ctx()) is None


def test_stray_pipe_negative_word_clean():
    assert patterns.detect_stray_pipe_backslash("word", _make_ctx()) is None


# ===========================================================================
# detect_short_allcaps_orphan
# ===========================================================================

_STD_ABBREVS = {"A", "B", "AD", "BC", "AM", "PM", "NT", "OT", "I", "II", "III", "IV", "V"}


def test_short_allcaps_orphan_positive_cn():
    """CN is not a standard abbreviation -- should be flagged."""
    ctx = _make_ctx(whitelist_terms=set())
    c = patterns.detect_short_allcaps_orphan("CN", ctx)
    assert c is not None
    assert c.reason == "short_allcaps_orphan"
    assert c.tier == 2


def test_short_allcaps_orphan_positive_pw():
    ctx = _make_ctx(whitelist_terms=set())
    c = patterns.detect_short_allcaps_orphan("PW", ctx)
    assert c is not None


def test_short_allcaps_orphan_positive_single_z():
    """Single non-standard uppercase letter should be flagged."""
    ctx = _make_ctx(whitelist_terms=set())
    c = patterns.detect_short_allcaps_orphan("Z", ctx)
    assert c is not None


def test_short_allcaps_orphan_negative_nt():
    """NT is a standard abbreviation (New Testament)."""
    ctx = _make_ctx(whitelist_terms=set())
    assert patterns.detect_short_allcaps_orphan("NT", ctx) is None


def test_short_allcaps_orphan_negative_ot():
    ctx = _make_ctx(whitelist_terms=set())
    assert patterns.detect_short_allcaps_orphan("OT", ctx) is None


def test_short_allcaps_orphan_negative_whitelisted():
    """Tokens in whitelist_terms are not flagged."""
    ctx = _make_ctx(whitelist_terms={"AM"})
    assert patterns.detect_short_allcaps_orphan("AM", ctx) is None


def test_short_allcaps_orphan_negative_longer_token():
    """3+ char tokens are not in scope for this detector."""
    ctx = _make_ctx(whitelist_terms=set())
    assert patterns.detect_short_allcaps_orphan("THE", ctx) is None


# ===========================================================================
# detect_apparent_space_insertion
# ===========================================================================

def _dict_ctx(known_words) -> "patterns.DetectorContext":
    """Context with a real DictionaryStack seeded with known_words."""
    return _make_ctx(
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms=set(known_words),
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )


def test_apparent_space_insertion_positive_theatines():
    """THE + ATINES -> THEATINES (in lexicon) -> flagged."""
    ctx = _dict_ctx(["THEATINES"])
    ctx_with_adjacent = _make_ctx(
        adjacent_prev="THE",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms={"THEATINES"},
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    c = patterns.detect_apparent_space_insertion("ATINES", ctx_with_adjacent)
    assert c is not None
    assert c.reason == "apparent_space_insertion"
    assert c.tier == 2
    assert c.suggestion == "THEATINES"


def test_apparent_space_insertion_positive_predestination():
    """PRE + DESTINATION -> PREDESTINATION (in lexicon) -> flagged."""
    ctx = _make_ctx(
        adjacent_prev="PRE",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms={"PREDESTINATION"},
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    c = patterns.detect_apparent_space_insertion("DESTINATION", ctx)
    assert c is not None
    assert c.suggestion == "PREDESTINATION"


def test_apparent_space_insertion_negative_thelord():
    """THE + LORD -> THELORD not in dictionary -> not flagged."""
    ctx = _make_ctx(
        adjacent_prev="THE",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms=set(),
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    assert patterns.detect_apparent_space_insertion("LORD", ctx) is None


def test_apparent_space_insertion_negative_no_prev():
    """No adjacent_prev -> cannot be a space-insertion candidate."""
    ctx = _make_ctx(
        adjacent_prev=None,
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms={"THEATINES"},
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    assert patterns.detect_apparent_space_insertion("ATINES", ctx) is None


def test_apparent_space_insertion_negative_too_long():
    """Tokens > 12 chars are outside the length bound (3 <= len <= 12)."""
    ctx = _make_ctx(
        adjacent_prev="THE",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms={"THEQUALIFICATION"},
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    # QUALIFICATION is 13 chars, outside len <= 12
    assert patterns.detect_apparent_space_insertion("QUALIFICATION", ctx) is None


# ===========================================================================
# detect_apparent_space_deletion
# ===========================================================================

def test_apparent_space_deletion_positive_andthe():
    """ANDTHE -> AND + THE (both in dictionary)."""
    ctx = _dict_ctx(["AND", "THE", "LORD", "SAID"])
    c = patterns.detect_apparent_space_deletion("ANDTHE", ctx)
    assert c is not None
    assert c.reason == "apparent_space_deletion"
    assert c.tier == 2
    assert "AND THE" in c.suggestion or ("AND" in c.suggestion and "THE" in c.suggestion)


def test_apparent_space_deletion_positive_godsaid():
    """GODSAID -> GOD + SAID."""
    ctx = _dict_ctx(["GOD", "SAID", "AND", "THE"])
    c = patterns.detect_apparent_space_deletion("GODSAID", ctx)
    assert c is not None


def test_apparent_space_deletion_negative_predestination():
    """PREDESTINATION is a real word in the lexicon -> not flagged."""
    ctx = _dict_ctx(["PREDESTINATION", "PRE", "DESTINATION"])
    # PREDESTINATION is in the dictionary, so it should not be flagged
    # even though it could split into PRE+DESTINATION
    assert patterns.detect_apparent_space_deletion("PREDESTINATION", ctx) is None


def test_apparent_space_deletion_negative_short_token():
    """Tokens < 6 chars are out of scope."""
    ctx = _dict_ctx(["AN", "THE", "AND"])
    assert patterns.detect_apparent_space_deletion("AND", ctx) is None


def test_apparent_space_deletion_negative_no_split():
    """XYZQQR (6 chars, in scope) has no dictionary-pair split point."""
    ctx = _dict_ctx(["AND", "THE"])
    assert patterns.detect_apparent_space_deletion("XYZQQR", ctx) is None


# ===========================================================================
# detect_entity_leak (ccel_thml, Tier 1)
# ===========================================================================

def test_entity_leak_positive_amp():
    c = patterns.detect_entity_leak("&amp;", _make_ctx())
    assert c is not None
    assert c.reason == "entity_leak"
    assert c.tier == 1


def test_entity_leak_positive_lt():
    c = patterns.detect_entity_leak("&lt;", _make_ctx())
    assert c is not None


def test_entity_leak_positive_numeric():
    c = patterns.detect_entity_leak("&#8212;", _make_ctx())
    assert c is not None


def test_entity_leak_negative_plain_ampersand():
    assert patterns.detect_entity_leak("&", _make_ctx()) is None


def test_entity_leak_negative_att():
    assert patterns.detect_entity_leak("AT&T", _make_ctx()) is None


def test_entity_leak_negative_plain_text():
    assert patterns.detect_entity_leak("GRACE", _make_ctx()) is None


# ===========================================================================
# Confidence value tests -- Task 4: update static values to measured precision
# ===========================================================================

def test_digit_in_letter_confidence_reflects_measured_precision():
    """digit_in_letter confidence reflects SH measured ~40-50%, not 0.95."""
    c = patterns.detect_digit_in_letter("THE0T0K0S", _make_ctx())
    assert c is not None
    # Pre-work measured ~40-50% precision on SH. Value must be < 0.60.
    assert c.confidence < 0.60, (
        f"digit_in_letter confidence {c.confidence} is too high; "
        "SH precision is ~40-50%, not 95%"
    )


def test_ligature_bracket_confidence_reflects_measured_precision():
    """ligature_bracket confidence reflects SH measured 2-5%, not 0.90."""
    c = patterns.detect_ligature_bracket("(ECOLAMPADIUS", _make_ctx())
    assert c is not None
    # Pre-work measured ~2-5% precision on SH (citation FPs dominate).
    assert c.confidence < 0.20, (
        f"ligature_bracket confidence {c.confidence} is too high; "
        "SH precision is ~2-5%"
    )


def test_short_allcaps_orphan_confidence_reflects_measured_precision():
    """short_allcaps_orphan confidence reflects 0% SH sample, not 0.60."""
    c = patterns.detect_short_allcaps_orphan("PW", _make_ctx())
    assert c is not None
    # Pre-work measured 0% on 30-sample SH. Use conservative 0.35 for non-SH corpora.
    assert c.confidence <= 0.40, (
        f"short_allcaps_orphan confidence {c.confidence} is too high; "
        "SH measured 0%"
    )


def test_stray_pipe_backslash_confidence_unchanged():
    """stray_pipe_backslash confidence stays at 0.90 (10/10 TPs confirmed)."""
    c = patterns.detect_stray_pipe_backslash("CHR|ST", _make_ctx())
    assert c is not None
    assert c.confidence == 0.90


def test_ligature_ae_loss_tier_is_3():
    """ligature_ae_loss detector produces Tier 3 candidates (REASON_CODES updated)."""
    from build.tools.ocr_scanner.models import REASON_CODES
    assert REASON_CODES["ligature_ae_loss"] == 3, (
        f"ligature_ae_loss should be Tier 3, got {REASON_CODES['ligature_ae_loss']}"
    )


# ===========================================================================
# detect_unusual_bigram -- reason label fix
# ===========================================================================

def test_unusual_bigram_reason_label():
    """detect_unusual_bigram produces reason='unusual_bigram', not 'apparent_space_insertion'.

    Prior implementation delegated entirely to detect_apparent_space_insertion,
    so candidates were mislabeled. The _detect_joined_word helper now takes the
    reason as a parameter so each caller stamps the correct reason code.
    """
    ctx = _make_ctx(
        adjacent_prev="THE",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(),
            lexicon_terms={"THEATINES"},
            enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    c = patterns.detect_unusual_bigram("ATINES", ctx)
    assert c is not None
    assert c.reason == "unusual_bigram", (
        f"Expected reason='unusual_bigram', got '{c.reason}'. "
        "detect_unusual_bigram was returning apparent_space_insertion candidates."
    )
    assert c.tier == 2
    assert c.suggestion == "THEATINES"


def test_unusual_bigram_no_match_returns_none():
    """detect_unusual_bigram returns None when join is not in dictionary."""
    ctx = _make_ctx(
        adjacent_prev="THE",
        dictionary=patterns.DictionaryStack(
            whitelist_terms=set(), lexicon_terms=set(), enable_enchant=False,
        ),
        whitelist_terms=set(),
    )
    assert patterns.detect_unusual_bigram("LORD", ctx) is None
