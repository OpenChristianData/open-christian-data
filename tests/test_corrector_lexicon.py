from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from build.lib.gold_free_corrector.column_vote import correct_position
from build.lib.gold_free_corrector.lexicon.build_lexicon import (
    build_lexicon_from_wct_pages,
    lexicon_from_dict,
)


def _page(*positions: dict) -> dict:
    return {
        "schema_type": "word_confusion_table",
        "schema_version": "word-confusion-table-v1",
        "positions": list(positions),
    }


def _position(*candidates: dict) -> dict:
    return {
        "position_id": "vol_01:page_0001:body:c1:l000:p000",
        "candidate_set": list(candidates),
        "span_records": [],
    }


def _candidate(key: str, families: list[str]) -> dict:
    return {
        "candidate_id": f"cand_{key}",
        "candidate_key": key,
        "raw_reading": key,
        "attesting_families": families,
    }


def test_consensus_candidate_with_two_distinct_families_is_in_lexicon() -> None:
    lexicon = build_lexicon_from_wct_pages([
        _page(_position(_candidate("edition", ["abbyy", "tesseract"])))
    ])

    assert lexicon.is_word("edition")


def test_single_family_short_and_non_alpha_candidates_are_excluded() -> None:
    lexicon = build_lexicon_from_wct_pages([
        _page(
            _position(_candidate("solo", ["abbyy"])),
            _position(_candidate("of", ["abbyy", "tesseract"])),
            _position(_candidate("word2", ["abbyy", "tesseract"])),
        )
    ])

    assert not lexicon.is_word("solo")
    assert not lexicon.is_word("of")
    assert not lexicon.is_word("word2")


def test_kraken_variants_count_as_one_family_for_consensus() -> None:
    lexicon = build_lexicon_from_wct_pages([
        _page(_position(_candidate("logos", ["kraken", "kraken-greek"])))
    ])

    assert not lexicon.is_word("logos")


def test_corrector_output_is_not_ingestable() -> None:
    position = _position(_candidate("created", ["abbyy", "tesseract"]))
    corrected = correct_position(position).corrected_position

    with pytest.raises(ValueError, match="raw WCT page"):
        build_lexicon_from_wct_pages([corrected])


def test_nearest_uses_wct_confusion_distance_and_excludes_beyond_bound() -> None:
    lexicon = build_lexicon_from_wct_pages([
        _page(
            _position(_candidate("corn", ["abbyy", "tesseract"])),
            _position(_candidate("edition", ["abbyy", "tesseract"])),
        )
    ])

    assert lexicon.nearest("com", max_distance=0.07) == [("corn", pytest.approx(0.0625))]
    assert lexicon.nearest("com", max_distance=0.05) == []


def test_no_dictionary_supplied_records_absent_source_and_still_serializes() -> None:
    lexicon = build_lexicon_from_wct_pages([
        _page(_position(_candidate("edition", ["abbyy", "tesseract"])))
    ])
    artifact = lexicon.to_dict()

    assert artifact["dictionary_source"] is None
    assert artifact["dictionary_word_count"] == 0
    assert artifact["sources"]["wct_consensus"] == "raw-wct-candidate-attestation"
    assert lexicon_from_dict(artifact).is_word("edition")


def test_optional_dictionary_headwords_are_union_source_when_supplied() -> None:
    lexicon = build_lexicon_from_wct_pages(
        [_page(_position(_candidate("edition", ["abbyy", "tesseract"])))],
        dictionary_headwords=["Covenant", "of", "faith-hope"],
        dictionary_source="pd-headwords-test-fixture",
    )

    assert lexicon.is_word("covenant")
    assert not lexicon.is_word("of")
    assert not lexicon.is_word("faith-hope")
    assert lexicon.to_dict()["dictionary_source"] == "pd-headwords-test-fixture"
    assert lexicon.to_dict()["dictionary_word_count"] == 1


def test_serialized_output_is_deterministic_for_page_order_and_hash_seed() -> None:
    script = r"""
import json
from build.lib.gold_free_corrector.lexicon.build_lexicon import build_lexicon_from_wct_pages

def page(key):
    return {
        "schema_type": "word_confusion_table",
        "schema_version": "word-confusion-table-v1",
        "positions": [{
            "candidate_set": [{
                "candidate_id": "cand_" + key,
                "candidate_key": key,
                "raw_reading": key,
                "attesting_families": ["tesseract", "abbyy"],
            }]
        }],
    }

pages = [page("zeta"), page("alpha"), page("logos")]
if %s:
    pages = list(reversed(pages))
lexicon = build_lexicon_from_wct_pages(pages, languages=["en", "la"])
print(json.dumps(lexicon.to_dict(), sort_keys=True, separators=(",", ":")))
"""
    outputs = []
    for seed, reverse in [("0", "False"), ("1", "True")]:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script % reverse],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        outputs.append(result.stdout.strip())

    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["words"] == ["alpha", "logos", "zeta"]
