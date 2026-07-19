"""Tests for lang_classifier — existing interface and new classify_block interface (Slot 2).

The new import of classify_block makes this whole module RED until production
code adds the function. The existing classify/classify_spans tests are preserved
and will pass again once classify_block is implemented.
"""

from __future__ import annotations


from ocd_kernel.lib.lang_classifier import classify, classify_spans, classify_block


def test_classify_returns_no_hint_for_unmatched_english() -> None:
    assert classify("any text", "commentary") == (None, [])


def test_classify_spans_returns_empty_list_for_unmatched_english() -> None:
    assert classify_spans("any text") == []


def test_classify_block_returns_dict():
    result = classify_block("The grace of God", "commentary")
    assert isinstance(result, dict)
    for key in ("language", "language_confidence", "language_segments", "chosen_layer", "language_alternates"):
        assert key in result, f"Missing key: {key}"


def test_classify_block_english_text():
    result = classify_block("The grace of God, who hath made us", "commentary")
    assert result["language"] == "en"
    assert result["language_confidence"] >= 0.60


def test_classify_block_greek_script():
    # Native Greek Unicode — Layer 1 handles script detection
    result = classify_block("ἀγάπη", "commentary")
    assert result["language"] == "grc"
    assert result["chosen_layer"] == "layer1"


def test_classify_block_und_on_empty():
    result = classify_block("", "commentary")
    assert result["language"] == "und"
    assert result["language_confidence"] == 0.0


def test_classify_block_language_segments_type():
    result = classify_block("The grace of God", "commentary")
    assert isinstance(result["language_segments"], list)
