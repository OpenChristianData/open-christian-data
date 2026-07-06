"""Tests for lang_classifier confidence bands — existing span tests plus new
classify_block confidence-floor and LANG_BLOCK_NEEDS_REVIEW tests (Slot 2).

The new imports make this whole module RED until production code adds
classify_block, LANG_BLOCK_NEEDS_REVIEW, and check_language_confidence.
"""

from __future__ import annotations


from build.lib.lang_classifier import classify_spans, classify_block, LANG_BLOCK_NEEDS_REVIEW, check_language_confidence


def test_greek_script_is_high_confidence() -> None:
    spans = classify_spans("received αντιλεγομενα here")

    greek = [span for span in spans if span["lang"] == "grc"]
    assert greek
    assert {span["confidence"] for span in greek} == {"high"}


def test_hebrew_transliteration_is_low_confidence() -> None:
    spans = classify_spans("Jehovah and Elohim are transliterations.")

    he_latn = [span for span in spans if span["lang"] == "hbo_latn"]
    assert he_latn
    assert {span["confidence"] for span in he_latn} == {"low"}


def test_latin_abbreviation_is_medium_only_for_dictionary_match() -> None:
    spans = classify_spans("See ibid. and nonsense.")

    assert [span["confidence"] for span in spans if span["lang"] == "la"] == ["medium"]
    assert classify_spans("See xyzzy.") == []


def test_uncertain_spans_require_manual_override() -> None:
    assert classify_spans("plain text") == []
    assert classify_spans("plain text", uncertain_overrides=True) == [
        {"start": 0, "end": len("plain text"), "lang": "und", "confidence": "uncertain"}
    ]


# --- New Slot 2 tests ---


def test_confidence_floor_is_60_percent():
    # Empty string has no detectable language — must return und with zero confidence
    result = classify_block("", "commentary")
    assert result["language"] == "und"
    assert result["language_confidence"] == 0.0


def test_lang_block_needs_review_fires_on_und():
    result = classify_block("", "commentary")
    assert LANG_BLOCK_NEEDS_REVIEW in check_language_confidence(result)


def test_lang_block_needs_review_fires_on_low_confidence():
    # Single punctuation character is guaranteed to return low/zero confidence
    result = classify_block(".", "commentary")
    assert result["language_confidence"] < 0.60, f"Fixture should return low confidence, got {result['language_confidence']}"
    assert LANG_BLOCK_NEEDS_REVIEW in check_language_confidence(result)


def test_und_language_has_zero_confidence():
    result = classify_block(".", "commentary")
    assert result["language"] == "und"
    assert result["language_confidence"] == 0.0


def test_lang_block_needs_review_constant_exists():
    assert isinstance(LANG_BLOCK_NEEDS_REVIEW, str) and LANG_BLOCK_NEEDS_REVIEW
