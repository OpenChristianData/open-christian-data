"""R54 — Source-transliteration lexicons detect grc and hbo terms.

RED until build.lib.source_transliteration_lexicons is created.
"""

from __future__ import annotations


from build.lib.source_transliteration_lexicons import load_source_transliteration_lexicons


def test_agape_detected_as_grc_transliteration() -> None:
    lexicon = load_source_transliteration_lexicons("grc")
    tokens = {token for entry in lexicon for token in entry["source_tokens"]}
    grc_entries = [entry for entry in lexicon if entry["underlying_language"] == "grc"]
    agape_entries = [
        entry for entry in grc_entries
        if "agapē" in entry["source_tokens"]
    ]
    assert agape_entries, "Expected 'agapē' in grc source-transliteration lexicon"
    assert agape_entries[0]["underlying_language"] == "grc"


def test_agape_variant_detected() -> None:
    # Without macron — variant spelling also in the lexicon
    lexicon = load_source_transliteration_lexicons("grc")
    all_tokens = {token for entry in lexicon for token in entry["source_tokens"]}
    assert "agape" in all_tokens, "Expected 'agape' (no macron) in grc source-transliteration lexicon"


def test_yahweh_detected_as_hbo_transliteration() -> None:
    lexicon = load_source_transliteration_lexicons("hbo")
    yahweh_entries = [
        entry for entry in lexicon
        if "Yahweh" in entry["source_tokens"]
    ]
    assert yahweh_entries, "Expected 'Yahweh' in hbo source-transliteration lexicon"
    assert yahweh_entries[0]["underlying_language"] == "hbo"


def test_pneuma_without_citation_not_flagged_as_transliteration() -> None:
    # "pneuma" appears in the Layer 2 grc term lexicon but is NOT in the
    # source-transliteration whitelist — source-transliteration means the
    # original source document explicitly transliterated the term.
    lexicon = load_source_transliteration_lexicons("grc")
    all_tokens = {token for entry in lexicon for token in entry["source_tokens"]}
    assert "pneuma" not in all_tokens, (
        "'pneuma' should NOT be in grc source-transliteration lexicon — "
        "it belongs only in the Layer 2 lexicon"
    )


def test_la_yaml_is_empty_in_phase1() -> None:
    lexicon = load_source_transliteration_lexicons("la")
    assert lexicon == [], "la source-transliteration lexicon must be empty in Phase 1"


def test_source_transliteration_entry_shape() -> None:
    lexicon = load_source_transliteration_lexicons("grc")
    assert lexicon, "grc source-transliteration lexicon must not be empty"
    for entry in lexicon:
        assert "rule_id" in entry, f"Missing 'rule_id' in entry: {entry}"
        assert "source_tokens" in entry, f"Missing 'source_tokens' in entry: {entry}"
        assert isinstance(entry["source_tokens"], list), "'source_tokens' must be a list"
        assert "underlying_language" in entry, f"Missing 'underlying_language' in entry: {entry}"
        assert "enabled" in entry, f"Missing 'enabled' in entry: {entry}"
