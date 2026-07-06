"""Tests for mixed_script diagnostic flag on classify_block output.

RED suite — all fail until _detect_mixed_script is implemented and
classify_block injects the flag into every return path.
"""

from __future__ import annotations


from build.lib.lang_classifier import classify_block


def test_mixed_script_key_always_present():
    result = classify_block("The grace of God", "commentary")
    assert "mixed_script" in result


def test_pure_english_is_not_mixed():
    result = classify_block("The grace of God who hath made us", "commentary")
    assert result["mixed_script"] is False


def test_pure_greek_unicode_is_not_mixed():
    result = classify_block("ἀγάπη", "commentary")
    assert result["mixed_script"] is False


def test_greek_unicode_plus_latin_is_mixed():
    result = classify_block("The word ἀγάπη means love", "commentary")
    assert result["mixed_script"] is True


def test_syriac_only_is_not_mixed():
    result = classify_block("ܐ ܒ ܓ", "commentary")
    assert result["mixed_script"] is False


def test_syriac_plus_latin_is_mixed():
    result = classify_block("The text ܐ ܒ ܓ in Syriac", "commentary")
    assert result["mixed_script"] is True


def test_empty_is_not_mixed():
    result = classify_block("", "commentary")
    assert result["mixed_script"] is False
