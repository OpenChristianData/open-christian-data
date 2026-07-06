"""TDD contract for the ABBYY-lineage value study core.

Per the design (plans/2026-06-19-abbyy-lineage-value-study-design.md v2) and TEST-16,
these tests are the architectural contract for the decisive pure-function logic:
the proxy triage router (which positions need human review), the unique/redundant/noise
scorer (the metric Codex's reject said v1 got wrong), the stratifier, and the Wilson CI.

Written-failed-first: the module does not exist yet when these are authored.
"""
from __future__ import annotations

import pytest

from build.tools.ocr_pipeline.abbyy_lineage_value_study import (
    WCT_TO_STUDY_FAMILY,
    normalize_wct_families,
    score_position,
    stratify,
    triage_position,
    wilson_ci,
)


# --------------------------------------------------------------------------- #
# triage_position: >=2 NON-ABBYY families agree -> 'easy' (skip human review);
# else 'hard' (the positions where alternate scans might uniquely help).
# Baseline panel families: tesseract, azure, kraken (non-abbyy) + abbyy.
# --------------------------------------------------------------------------- #

def test_triage_three_non_abbyy_agree_is_easy():
    base = {"tesseract": "word", "azure": "word", "kraken": "word", "abbyy": "word"}
    assert triage_position(base) == "easy"


def test_triage_two_non_abbyy_agree_is_easy():
    base = {"tesseract": "word", "azure": "word", "kraken": "xxxx", "abbyy": "word"}
    assert triage_position(base) == "easy"


def test_triage_no_two_non_abbyy_agree_is_hard():
    base = {"tesseract": "word", "azure": "yyyy", "kraken": "zzzz", "abbyy": "word"}
    assert triage_position(base) == "hard"


def test_triage_abbyy_agreement_does_not_make_easy():
    # abbyy must NOT count toward the non-abbyy proxy: tesseract + abbyy agreeing is
    # only one non-abbyy family, so the position is still hard.
    base = {"tesseract": "word", "azure": None, "kraken": None, "abbyy": "word"}
    assert triage_position(base) == "hard"


# --------------------------------------------------------------------------- #
# The WCT emits LONG engine-family names (word-confusion-table-v1 enum), e.g.
# "azure-ai-vision". triage_position must normalize those to the study's short
# vocabulary at its boundary, or azure agreement is invisible and every azure
# position is mis-classified as a disagreement (inflating the "hard" pool).
# These tests feed real WCT family names -- the exact class of bug that stayed
# hidden in CI while the fixtures used the short "azure" alias.
# --------------------------------------------------------------------------- #

def test_triage_counts_azure_under_real_wct_family_name():
    # tesseract + azure agree on "word" -- but azure arrives as the WCT long name.
    base = {"tesseract": "word", "azure-ai-vision": "word", "kraken": "zzzz", "abbyy": "word"}
    assert triage_position(base) == "easy"


def test_triage_hard_when_real_wct_azure_disagrees():
    base = {"tesseract": "word", "azure-ai-vision": "yyyy", "kraken": "zzzz", "abbyy": "word"}
    assert triage_position(base) == "hard"


def test_normalize_wct_families_maps_long_names_to_short():
    raw = {"tesseract": "a", "azure-ai-vision": "b", "kraken": "c", "abbyy": "d"}
    assert normalize_wct_families(raw) == {
        "tesseract": "a",
        "azure": "b",
        "kraken": "c",
        "abbyy": "d",
    }


def test_wct_to_study_family_maps_azure_long_name():
    assert WCT_TO_STUDY_FAMILY["azure-ai-vision"] == "azure"


# --------------------------------------------------------------------------- #
# score_position: the decisive metric. true_reading is human ground truth.
#   unique_recovery  = baseline lacks T*, an alternate has T*  (the value Codex said v1 missed)
#   redundant_recovery = baseline already has T*, an alternate also has it
#   noise_added      = an alternate introduces a reading != T* not already in baseline
# Noise is per-position (six scans agreeing on one wrong reading == one noise event).
# --------------------------------------------------------------------------- #

def test_score_unique_recovery():
    base = {"tesseract": "modem", "azure": "modem", "kraken": "modem", "abbyy": "modem"}
    alts = {"haucgoog": "modern"}
    v = score_position(base, alts, true_reading="modern")
    assert v["unique_recovery"] is True
    assert v["redundant_recovery"] is False
    assert v["noise_added"] is False


def test_score_redundant_recovery():
    base = {"tesseract": "modem", "azure": "modern", "kraken": "modem", "abbyy": "modem"}
    alts = {"haucgoog": "modern"}
    v = score_position(base, alts, true_reading="modern")
    assert v["redundant_recovery"] is True
    assert v["unique_recovery"] is False
    assert v["noise_added"] is False


def test_score_noise_added():
    base = {"tesseract": "modern", "azure": "modern", "kraken": "modern", "abbyy": "modern"}
    alts = {"haucgoog": "rnodern"}
    v = score_position(base, alts, true_reading="modern")
    assert v["noise_added"] is True
    assert v["unique_recovery"] is False
    assert v["redundant_recovery"] is False


def test_score_unique_and_noise_together_per_position():
    # one alternate recovers T*, another adds a new wrong reading: both events fire,
    # noise counted once for the position regardless of how many scans share it.
    base = {"tesseract": "modem", "azure": "modem", "kraken": "modem", "abbyy": "modem"}
    alts = {"haucgoog": "modern", "c1": "rnodem", "c2": "rnodem"}
    v = score_position(base, alts, true_reading="modern")
    assert v["unique_recovery"] is True
    assert v["noise_added"] is True


def test_score_no_alternate_signal():
    base = {"tesseract": "word", "azure": "word", "kraken": "word", "abbyy": "word"}
    alts = {"haucgoog": "word"}
    v = score_position(base, alts, true_reading="word")
    assert v["redundant_recovery"] is True
    assert v["noise_added"] is False


# --------------------------------------------------------------------------- #
# stratify: priority greek_hebrew > degraded > dense > clean.
# percentiles are 0..1 within the volume.
# --------------------------------------------------------------------------- #

def test_stratify_greek_hebrew_wins():
    f = {"has_greek_hebrew": True, "primary_conf_pct": 0.1, "word_count_pct": 0.9}
    assert stratify(f) == "greek_hebrew"


def test_stratify_degraded_over_dense():
    f = {"has_greek_hebrew": False, "primary_conf_pct": 0.1, "word_count_pct": 0.9}
    assert stratify(f) == "degraded"


def test_stratify_dense():
    f = {"has_greek_hebrew": False, "primary_conf_pct": 0.5, "word_count_pct": 0.9}
    assert stratify(f) == "dense"


def test_stratify_clean():
    f = {"has_greek_hebrew": False, "primary_conf_pct": 0.5, "word_count_pct": 0.5}
    assert stratify(f) == "clean"


# --------------------------------------------------------------------------- #
# wilson_ci: 95% Wilson score interval. The decision rule reads the upper bound.
# --------------------------------------------------------------------------- #

def test_wilson_zero_successes_low_is_zero_high_is_known():
    low, high = wilson_ci(0, 10)
    assert low == pytest.approx(0.0, abs=1e-6)
    assert high == pytest.approx(0.2775, abs=0.005)


def test_wilson_half_is_symmetric_around_half():
    low, high = wilson_ci(50, 100)
    assert low == pytest.approx(1 - high, abs=1e-6)
    assert low < 0.5 < high


def test_wilson_empty_sample_is_full_interval():
    low, high = wilson_ci(0, 0)
    assert low == pytest.approx(0.0)
    assert high == pytest.approx(1.0)
