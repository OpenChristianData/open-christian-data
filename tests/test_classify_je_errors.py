"""Tests for the JE gold-free error-class classifier + coverage measurement.

The tool under test (`build/tools/ocr_pipeline/classify_je_errors.py`) is a
read-only measurement analysis script. These tests cover the two pieces of
logic the U11b prompt names: (1) per-pair error classification, and (2)
gold-free detection-signal coverage. All fixtures are in-memory or written to
pytest's tmp_path -- nothing reads the gitignored quarantine data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools.ocr_pipeline.classify_je_errors import (
    aggregate_coverage,
    classify_article,
    load_gold_article,
    load_wct_positions,
    pair_signals,
    parse_position_id,
)


# ---------------------------------------------------------------------------
# parse_position_id
# ---------------------------------------------------------------------------


def test_parse_position_id_extracts_page_zone_column():
    parsed = parse_position_id("vol_02:page_0013:body:c1:l002:p010")
    assert parsed["page_id"] == "page_0013"
    assert parsed["zone_type"] == "body"
    assert parsed["column"] == "c1"


def test_parse_position_id_handles_second_column():
    parsed = parse_position_id("vol_02:page_0046:body:c2:l000:p003")
    assert parsed["column"] == "c2"


# ---------------------------------------------------------------------------
# classify_article -- clean / real_minor / far_isolated / far_clustered
# ---------------------------------------------------------------------------


def _pair(match, cd):
    return {"match": match, "confusion_dist": cd}


def test_classify_clean_pairs_are_clean():
    pairs = [_pair(True, 0.0), _pair(True, 0.0)]
    assert classify_article(pairs) == ["clean", "clean"]


def test_classify_real_minor_is_close_but_wrong():
    # not matched, 0 < cd <= 0.6 -> real_minor (neighbors clean)
    pairs = [_pair(True, 0.0), _pair(False, 0.3), _pair(True, 0.0)]
    assert classify_article(pairs) == ["clean", "real_minor", "clean"]


def test_classify_far_isolated_has_two_clean_neighbors():
    # cd > 0.6, both neighbors clean -> far_isolated
    pairs = [_pair(True, 0.0), _pair(False, 0.9), _pair(True, 0.0)]
    assert classify_article(pairs) == ["clean", "far_isolated", "clean"]


def test_classify_far_clustered_when_a_neighbor_also_failed():
    # two adjacent far errors -> both far_clustered
    pairs = [_pair(True, 0.0), _pair(False, 0.9), _pair(False, 0.8), _pair(True, 0.0)]
    assert classify_article(pairs) == [
        "clean",
        "far_clustered",
        "far_clustered",
        "clean",
    ]


def test_classify_boundary_far_error_with_one_clean_neighbor_is_isolated():
    # first pair is a far error; its only (right) neighbor is clean -> isolated
    pairs = [_pair(False, 0.9), _pair(True, 0.0)]
    assert classify_article(pairs) == ["far_isolated", "clean"]


def test_classify_threshold_is_tunable():
    # at minor_max=0.4 a cd=0.5 error is "far", not "real_minor"
    pairs = [_pair(True, 0.0), _pair(False, 0.5), _pair(True, 0.0)]
    assert classify_article(pairs, minor_max=0.4) == [
        "clean",
        "far_isolated",
        "clean",
    ]
    assert classify_article(pairs, minor_max=0.6) == [
        "clean",
        "real_minor",
        "clean",
    ]


# ---------------------------------------------------------------------------
# pair_signals -- gold-free detection coverage per pair
# ---------------------------------------------------------------------------


def _sig(**overrides):
    """Default to an all-clear (uncaught) position; override one signal."""
    base = dict(
        candidate_count=1,
        ocr_norm="house",
        lexicon_words={"house"},
        script="latin",
        low_confidence=False,
        protected=False,
    )
    base.update(overrides)
    return pair_signals(**base)


def test_pair_signals_engine_disagreement_when_multiple_candidates():
    sig = _sig(candidate_count=2)
    assert sig["engine_disagree"] is True
    assert sig["caught_any"] is True


def test_pair_signals_non_lexical_when_token_absent_from_lexicon():
    sig = _sig(ocr_norm="garbld", lexicon_words={"garbled"})
    assert sig["non_lexical"] is True
    assert sig["caught_any"] is True


def test_pair_signals_uncaught_when_no_signal_fires():
    # single candidate, lexical token, latin, full attestation, not protected
    sig = _sig()
    assert sig["engine_disagree"] is False
    assert sig["non_lexical"] is False
    assert sig["protected"] is False
    assert sig["non_latin"] is False
    assert sig["low_confidence"] is False
    assert sig["caught_any"] is False


def test_pair_signals_non_latin_fires_on_hebrew():
    sig = _sig(ocr_norm="x", lexicon_words={"x"}, script="hebrew")
    assert sig["non_latin"] is True
    assert sig["caught_any"] is True


def test_pair_signals_low_confidence_is_a_gold_free_tell():
    # alignment_confidence below 0.99 (not all engines attest) -> observable
    sig = _sig(ocr_norm="x", lexicon_words={"x"}, low_confidence=True)
    assert sig["low_confidence"] is True
    assert sig["caught_any"] is True


def test_pair_signals_does_not_use_error_class_as_a_signal():
    # far_clustered membership is gold-DEFINED, not observable at NSH runtime,
    # so pair_signals must not accept or use it. A latin, lexical, attested,
    # single-candidate token stays UNCAUGHT regardless of its true class.
    sig = _sig(ocr_norm="x", lexicon_words={"x"})
    assert sig["caught_any"] is False


def test_pair_signals_protected_counts_as_caught():
    sig = _sig(ocr_norm="x", lexicon_words={"x"}, protected=True)
    assert sig["protected"] is True
    assert sig["caught_any"] is True


# ---------------------------------------------------------------------------
# aggregate_coverage -- per-class roll-up of caught vs uncaught
# ---------------------------------------------------------------------------


def test_aggregate_coverage_counts_caught_and_uncaught_per_class():
    rows = [
        {"klass": "real_minor", "engine_disagree": True, "non_lexical": False,
         "protected": False, "non_latin": False, "low_confidence": False,
         "caught_any": True},
        {"klass": "real_minor", "engine_disagree": False, "non_lexical": False,
         "protected": False, "non_latin": False, "low_confidence": False,
         "caught_any": False},
        {"klass": "far_isolated", "engine_disagree": False, "non_lexical": True,
         "protected": False, "non_latin": False, "low_confidence": False,
         "caught_any": True},
    ]
    agg = aggregate_coverage(rows)
    assert agg["real_minor"]["n"] == 2
    assert agg["real_minor"]["caught_any"] == 1
    assert agg["real_minor"]["uncaught"] == 1
    assert agg["real_minor"]["engine_disagree"] == 1
    assert agg["far_isolated"]["n"] == 1
    assert agg["far_isolated"]["uncaught"] == 0


# ---------------------------------------------------------------------------
# loaders -- tmp_path fixtures, no quarantine reads
# ---------------------------------------------------------------------------


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_gold_article_reads_aligned_pairs(tmp_path):
    gold = {
        "article_slug": "test-article",
        "n_aligned": 1,
        "pages_missing_wct": [],
        "aligned_pairs": [
            {
                "position_id": "vol_02:page_0001:body:c1:l000:p000",
                "reference_token": "Word",
                "reference_norm": "word",
                "ocr_consensus": "Word",
                "ocr_norm": "word",
                "match": True,
                "confusion_dist": 0.0,
            }
        ],
    }
    art_dir = tmp_path / "test-article"
    art_dir.mkdir()
    _write_json(art_dir / "gold.json", gold)

    loaded = load_gold_article(art_dir / "gold.json")
    assert loaded["article_slug"] == "test-article"
    assert loaded["aligned_pairs"][0]["reference_token"] == "Word"


def test_load_wct_positions_indexes_by_position_id(tmp_path):
    page = {
        "schema_version": "word-confusion-table-v1",
        "page_id": "page_0001",
        "positions": [
            {
                "position_id": "vol_02:page_0001:body:c1:l000:p000",
                "script": {"text_level": {"label": "latin"}},
                "candidate_set": [
                    {"candidate_id": "c1", "raw_reading": "Word",
                     "candidate_key": "word", "attesting_families": ["azure", "tesseract"]}
                ],
                "alignment_confidence": 0.99,
            }
        ],
    }
    _write_json(tmp_path / "page_0001.json", page)

    by_pos = load_wct_positions(tmp_path)
    pid = "vol_02:page_0001:body:c1:l000:p000"
    assert pid in by_pos
    assert by_pos[pid]["alignment_confidence"] == 0.99


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
