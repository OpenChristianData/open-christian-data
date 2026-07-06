"""B16 deliverable #2 — threshold-calibration B->A test (TEST-16: CI-non-overlap).

Contract: ``plans/2026-05-27-arch4-weight-matrix-synthesis.md`` section 4.1
(per-risk-class thresholds 40/250, 60/400, 100/600) + section 6.5 credible-
interval-non-overlap promotion criterion; lock
``plans/2026-05-28-archC-integration-locked-architecture.md`` section 4 item 1
("promote on CI-non-overlap separation; stays B until then").

The calibration measurement is phase-2 against real vol1+vol2 data; this suite
proves the *machinery* on synthetic fixtures. A candidate is promoted B->A only
when its Beta credible interval is provably separated from the comparison branch
AND it carries enough trusted observations for its risk class. Everything else
fails closed to B.
"""

from __future__ import annotations

import math

import pytest

from build.lib.calibration import (
    Branch,
    beta_credible_interval,
    evaluate_promotion,
    intervals_overlap,
)


# ---------------------------------------------------------------------------
# Beta credible interval (pure-Python, no scipy/numpy in CI)
# ---------------------------------------------------------------------------

def test_uniform_prior_interval_is_symmetric_wide():
    # Beta(1, 1) is uniform; the central 95% interval is (0.025, 0.975).
    lo, hi = beta_credible_interval(correct=0, incorrect=0, alpha=1.0, beta=1.0, level=0.95)
    assert lo == pytest.approx(0.025, abs=1e-3)
    assert hi == pytest.approx(0.975, abs=1e-3)


def test_interval_narrows_as_observations_grow():
    _, _, narrow = _width(correct=900, incorrect=100)
    _, _, wide = _width(correct=9, incorrect=1)
    assert narrow < wide
    # Both centred near 0.9.
    assert narrow < 0.10


def test_interval_bounds_are_ordered_and_in_unit_range():
    lo, hi = beta_credible_interval(correct=37, incorrect=3, alpha=1.0, beta=1.0)
    assert 0.0 <= lo < hi <= 1.0


def _width(correct: int, incorrect: int):
    lo, hi = beta_credible_interval(correct=correct, incorrect=incorrect, alpha=1.0, beta=1.0)
    return lo, hi, hi - lo


# ---------------------------------------------------------------------------
# Interval overlap predicate
# ---------------------------------------------------------------------------

def test_intervals_overlap_true_when_they_intersect():
    assert intervals_overlap((0.10, 0.40), (0.30, 0.60)) is True


def test_intervals_overlap_false_when_disjoint():
    assert intervals_overlap((0.10, 0.40), (0.50, 0.80)) is False


def test_touching_intervals_count_as_overlap():
    # Shared boundary is not separation; fail closed toward "overlap".
    assert intervals_overlap((0.10, 0.50), (0.50, 0.80)) is True


# ---------------------------------------------------------------------------
# B->A promotion gate (the TEST-16 core)
# ---------------------------------------------------------------------------

def _branch(region_class: str, correct: int, incorrect: int) -> Branch:
    return Branch(region_class=region_class, correct=correct, incorrect=incorrect)


def test_non_overlapping_cis_promote_to_A():
    # Candidate: high accuracy, well past the ordinary N2=250 mature threshold.
    candidate = _branch("body", correct=290, incorrect=10)      # ~0.967
    # Comparison: clearly lower accuracy, also well-observed.
    comparison = _branch("body", correct=210, incorrect=90)     # ~0.70
    verdict = evaluate_promotion(candidate, comparison)
    assert verdict.promoted is True
    assert verdict.final_class == "A"
    assert intervals_overlap(verdict.candidate_ci, verdict.comparison_ci) is False


def test_overlapping_cis_stay_B():
    # Two similar accuracies -> credible intervals overlap -> no promotion.
    candidate = _branch("body", correct=255, incorrect=45)      # ~0.85
    comparison = _branch("body", correct=250, incorrect=50)     # ~0.83
    verdict = evaluate_promotion(candidate, comparison)
    assert verdict.promoted is False
    assert verdict.final_class == "B"
    assert intervals_overlap(verdict.candidate_ci, verdict.comparison_ci) is True


def test_insufficient_observations_fail_closed_to_B():
    # Accuracy gap is large, but the candidate has too few observations for the
    # ordinary risk class (N2=250). A candidate stays B until the threshold is met,
    # regardless of how clean the separation looks.
    candidate = _branch("body", correct=40, incorrect=0)        # n=40 < 250
    comparison = _branch("body", correct=10, incorrect=40)
    verdict = evaluate_promotion(candidate, comparison)
    assert verdict.promoted is False
    assert verdict.final_class == "B"
    assert "observation" in verdict.reason.lower()


def test_threshold_is_risk_class_specific():
    # protected N2 = 600; an n=300 candidate that would clear ordinary stays B here.
    candidate = _branch("headword", correct=300, incorrect=0)   # n=300 < 600
    comparison = _branch("headword", correct=50, incorrect=250)
    verdict = evaluate_promotion(candidate, comparison)
    assert verdict.promoted is False
    assert verdict.required_n == 600


def test_ineligible_region_class_never_promotes():
    candidate = _branch("quotation", correct=5000, incorrect=0)
    comparison = _branch("quotation", correct=10, incorrect=5000)
    verdict = evaluate_promotion(candidate, comparison)
    assert verdict.promoted is False
    assert verdict.final_class == "B"


def test_min_absolute_difference_can_be_required():
    # Lock item 3 (body sub-class): CI-non-overlap AND >= 0.05 absolute accuracy
    # difference. With a tiny real gap but (hypothetically) separated CIs, the
    # absolute-difference guard still blocks promotion.
    candidate = _branch("body", correct=900, incorrect=100)     # 0.90
    comparison = _branch("body", correct=880, incorrect=120)    # 0.88, diff 0.02
    verdict = evaluate_promotion(candidate, comparison, min_absolute_difference=0.05)
    assert verdict.promoted is False
    assert verdict.final_class == "B"


def test_verdict_is_deterministic():
    candidate = _branch("body", correct=290, incorrect=10)
    comparison = _branch("body", correct=210, incorrect=90)
    a = evaluate_promotion(candidate, comparison)
    b = evaluate_promotion(candidate, comparison)
    assert a == b


def test_interval_level_must_be_in_open_unit_interval():
    with pytest.raises(ValueError):
        beta_credible_interval(correct=1, incorrect=1, alpha=1.0, beta=1.0, level=1.5)
    with pytest.raises(ValueError):
        beta_credible_interval(correct=1, incorrect=1, alpha=1.0, beta=1.0, level=0.0)
