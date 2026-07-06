"""B16 deliverable #2 — threshold-calibration B->A gate (matrix promotion).

The matrix counters (``matrix_counters.py``, B11) hold Beta-Binomial cells whose
phase is a pure function of observation count (arch4 section 4.1/4.2). Promotion
of a candidate branch from class **B** (logged, not voting at full authority) to
class **A** is a *separate* judgment: it requires the candidate's accuracy to be
provably better than its comparison branch, measured as **Beta credible-interval
non-overlap** (arch4 section 6.5; lock section 4 item 1), AND enough trusted
observations for the branch's risk class (the N2 threshold), AND -- where a rule
specifies one (lock item 3) -- a minimum absolute accuracy difference.

Why this lives apart from ``matrix_counters``: phase controls whether a cell
votes; calibration decides whether a *candidate cell-key dimension* (a substyle,
a banded sub-counter, a cross-product) earns promotion to a real cell key. The
two are different gates on the same Beta posterior (arch4 section 8 "credible-
interval-non-overlap criterion").

The actual calibration verdict on real vol1+vol2 data is a **phase-2**
measurement; this module is the machinery, proven on synthetic fixtures (B16
builds the measurement, not the verdict).

Pure-Python only: scipy/numpy are not CI dependencies (requirements-ci.txt), so
the incomplete-beta / inverse-CDF are implemented here with no third-party math.

Contract sources:
- ``plans/2026-05-27-arch4-weight-matrix-synthesis.md`` 4.1 (thresholds),
  5 (posterior), 5.1 (95% credible interval), 6.5 / 8 (CI-non-overlap promotion).
- ``plans/2026-05-28-archC-integration-locked-architecture.md`` section 4
  items 1 + 3 (CI-non-overlap; stays B until passed; >=0.05 abs diff for body
  sub-class).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from build.lib.matrix_counters import NEUTRAL_PRIOR, thresholds_for, threshold_class_for

# Default credible level. arch4 section 5.1 measures the matrix on the 95%
# credible interval; the promotion gate uses the same level so "non-overlap"
# means the same thing everywhere.
DEFAULT_LEVEL = 0.95


# ---------------------------------------------------------------------------
# Beta distribution: regularized incomplete beta + inverse CDF (pure Python)
# ---------------------------------------------------------------------------

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method).

    Adapted from the standard Numerical-Recipes ``betacf`` recurrence. Converges
    for x < (a+1)/(a+b+2); the caller routes the complementary tail otherwise.
    """
    tiny = 1e-30
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """``I_x(a, b)`` -- the Beta CDF at ``x``. Returns a probability in [0, 1]."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    # ln of the front factor x^a (1-x)^b / (a B(a,b)).
    ln_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(ln_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_ppf(p: float, a: float, b: float) -> float:
    """Inverse Beta CDF (quantile) via bisection on the monotone CDF.

    Bisection is slow but dependency-free and deterministic -- the calibration
    gate runs on a handful of branches, not a hot loop.
    """
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if regularized_incomplete_beta(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return 0.5 * (lo + hi)


def beta_credible_interval(
    *,
    correct: int,
    incorrect: int,
    alpha: float = NEUTRAL_PRIOR[0],
    beta: float = NEUTRAL_PRIOR[1],
    level: float = DEFAULT_LEVEL,
) -> tuple[float, float]:
    """Central ``level`` credible interval for ``Beta(correct+alpha, incorrect+beta)``.

    The posterior is ``Beta(correct + alpha, incorrect + beta)`` (arch4 section 2).
    A central interval splits the excluded mass equally into both tails.
    """
    if not 0.0 < level < 1.0:
        raise ValueError(f"level must be in (0, 1), got {level!r}")
    a = correct + alpha
    b = incorrect + beta
    tail = (1.0 - level) / 2.0
    lo = beta_ppf(tail, a, b)
    hi = beta_ppf(1.0 - tail, a, b)
    return (lo, hi)


def intervals_overlap(
    ci_a: tuple[float, float], ci_b: tuple[float, float]
) -> bool:
    """True if the two closed intervals intersect.

    Touching boundaries count as overlap: a shared edge is not separation, so the
    gate fails closed toward "not promotable".
    """
    lo_a, hi_a = ci_a
    lo_b, hi_b = ci_b
    return not (hi_a < lo_b or hi_b < lo_a)


# ---------------------------------------------------------------------------
# Promotion gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Branch:
    """One accuracy branch under calibration (a candidate or its comparison)."""

    region_class: str
    correct: int
    incorrect: int

    @property
    def n_observed(self) -> int:
        return self.correct + self.incorrect

    @property
    def posterior_mean(self) -> float:
        a = self.correct + NEUTRAL_PRIOR[0]
        b = self.incorrect + NEUTRAL_PRIOR[1]
        return a / (a + b)


@dataclass(frozen=True)
class PromotionVerdict:
    """The B->A calibration decision for one candidate branch."""

    promoted: bool
    final_class: str  # "A" if promoted else "B"
    reason: str
    candidate_ci: tuple[float, float]
    comparison_ci: tuple[float, float]
    required_n: int | None  # N2 for the risk class; None for ineligible
    candidate_n: int


def evaluate_promotion(
    candidate: Branch,
    comparison: Branch,
    *,
    level: float = DEFAULT_LEVEL,
    min_absolute_difference: float = 0.0,
) -> PromotionVerdict:
    """Decide whether ``candidate`` promotes B->A against ``comparison``.

    Promotion requires ALL of:
      1. the candidate's region_class is not ``ineligible`` (no vote authority
         without explicit promotion, arch4 section 4.1);
      2. enough trusted observations: ``candidate.n_observed >= N2`` for the
         risk class (lock item 1 "stays B until then");
      3. credible-interval non-overlap between candidate and comparison
         (arch4 section 6.5);
      4. where required, ``|posterior_diff| >= min_absolute_difference``
         (lock item 3, body sub-class gate).

    Any failure -> stays B. Fail-closed: an unrecognized/ineligible class, or a
    thin candidate, never promotes regardless of how clean the separation looks.
    """
    cand_ci = beta_credible_interval(
        correct=candidate.correct, incorrect=candidate.incorrect, level=level
    )
    comp_ci = beta_credible_interval(
        correct=comparison.correct, incorrect=comparison.incorrect, level=level
    )

    tc = threshold_class_for(candidate.region_class)
    n1_n2 = thresholds_for(candidate.region_class)
    required_n = n1_n2[1]  # N2, or None for ineligible

    def _stay_b(reason: str) -> PromotionVerdict:
        return PromotionVerdict(
            promoted=False,
            final_class="B",
            reason=reason,
            candidate_ci=cand_ci,
            comparison_ci=comp_ci,
            required_n=required_n,
            candidate_n=candidate.n_observed,
        )

    if tc == "ineligible" or required_n is None:
        return _stay_b(
            f"region_class {candidate.region_class!r} is ineligible for vote "
            "authority without explicit promotion"
        )

    if candidate.n_observed < required_n:
        return _stay_b(
            f"insufficient observations: n={candidate.n_observed} < "
            f"required N2={required_n} for {tc} class"
        )

    if intervals_overlap(cand_ci, comp_ci):
        return _stay_b(
            f"credible intervals overlap (candidate {cand_ci}, "
            f"comparison {comp_ci}); stays B"
        )

    abs_diff = abs(candidate.posterior_mean - comparison.posterior_mean)
    if abs_diff < min_absolute_difference:
        return _stay_b(
            f"absolute accuracy difference {abs_diff:.4f} < required "
            f"{min_absolute_difference}"
        )

    return PromotionVerdict(
        promoted=True,
        final_class="A",
        reason=(
            f"credible intervals separated (candidate {cand_ci}, comparison "
            f"{comp_ci}); n={candidate.n_observed} >= N2={required_n}"
        ),
        candidate_ci=cand_ci,
        comparison_ci=comp_ci,
        required_n=required_n,
        candidate_n=candidate.n_observed,
    )


__all__ = [
    "DEFAULT_LEVEL",
    "regularized_incomplete_beta",
    "beta_ppf",
    "beta_credible_interval",
    "intervals_overlap",
    "Branch",
    "PromotionVerdict",
    "evaluate_promotion",
]
