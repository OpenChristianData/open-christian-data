"""Tests for build.lib.reconcile.classify — disagreement classification decision tree.

All tests fail with ImportError until production code exists.
"""
from __future__ import annotations

import pytest



def test_classify_ocr_noise():
    """'worn' vs 'wom' (rn→m OCR confusion) → ocr_noise."""
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement("worn", "wom", language="en")
    assert kind == "ocr_noise"


def test_classify_capitalisation():
    """'The Lord' vs 'the Lord' → capitalisation."""
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement("The Lord", "the Lord", language="en")
    assert kind == "capitalisation"


def test_classify_punctuation():
    """'Lord, God' vs 'Lord God' (comma removed) → punctuation."""
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement("Lord, God", "Lord God", language="en")
    assert kind == "punctuation"


def test_classify_spelling_variant():
    """'honour' vs 'honor' (UK/US spelling) → spelling_variant."""
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement("honour", "honor", language="en")
    assert kind == "spelling_variant"


def test_classify_word_substitution():
    """'saith' vs 'says' (archaic/modern word swap) → word_substitution."""
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement("saith", "says", language="en")
    assert kind == "word_substitution"


def test_classify_paraphrase():
    """Substantial rewrite → paraphrase."""
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    anchor = "The Son of Man came not to be served but to serve"
    attestor = "Christ came to serve others"
    kind = classify_disagreement(anchor, attestor, language="en")
    assert kind == "paraphrase"


def test_r31_typo_correction_reprint_collapse_requires_delta_classification():
    """R31: 'recieve' (typo) vs 'receive' (reprint correction) → spelling_variant not ocr_noise.

    OCR noise is driven by OCR error model patterns (rn→m, cl→d etc).
    Spelling variant is driven by edit-distance + lexicon validity.
    A reprint typo-correction should classify as spelling_variant.
    """
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    # "recieve" is not an OCR error pattern (no rn→m, cl→d etc).
    # It's a misspelling in the source, corrected in a later reprint.
    kind = classify_disagreement("recieve", "receive", language="en")
    assert kind == "spelling_variant", (
        f"Expected spelling_variant (reprint typo-correction), got {kind!r}. "
        "OCR noise must be driven by OCR error models, not just edit distance."
    )


def test_same_family_disagreement_gets_correlated_prefix():
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement(
        "The Lord",
        "the Lord",
        language="en",
        attesting_families=["ocr", "ocr"],
    )

    assert kind == "correlated_capitalisation"


def test_cross_family_disagreement_keeps_base_classification():
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement(
        "The Lord",
        "the Lord",
        language="en",
        attesting_families=["ocr", "llm"],
    )

    assert kind == "capitalisation"


def test_none_attesting_families_keeps_base_classification():
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement(
        "Lord, God",
        "Lord God",
        language="en",
        attesting_families=None,
    )

    assert kind == "punctuation"


def test_empty_attesting_families_keeps_base_classification():
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement(
        "honour",
        "honor",
        language="en",
        attesting_families=[],
    )

    assert kind == "spelling_variant"


@pytest.mark.parametrize(
    ("anchor", "attestor", "expected"),
    [
        ("worn", "wom", "correlated_ocr_noise"),
        ("The Lord", "the Lord", "correlated_capitalisation"),
        ("Lord, God", "Lord God", "correlated_punctuation"),
        ("honour", "honor", "correlated_spelling_variant"),
        ("saith", "says", "correlated_word_substitution"),
        (
            "The Son of Man came not to be served but to serve",
            "Christ came to serve others",
            "correlated_paraphrase",
        ),
    ],
)
def test_all_base_classifications_have_correlated_variants(anchor, attestor, expected):
    from build.lib.reconcile.classify import classify_disagreement  # noqa: PLC0415

    kind = classify_disagreement(
        anchor,
        attestor,
        language="en",
        attesting_families=["ocr", "ocr"],
    )

    assert kind == expected
