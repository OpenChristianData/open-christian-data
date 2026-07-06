"""ABBYY-lineage value study — measure whether the alternate ABBYY scans add unique
correct readings to the NSH word-confusion table, or are redundant.

Design: plans/2026-06-19-abbyy-lineage-value-study-design.md (v2, post-Codex-reject).
Read-only study. This module currently holds the decisive pure-function core (triage,
scoring, stratification, Wilson CI). The integration layer (baseline-position build via
wct_builder, content-aligned alternate readings, image-crop emit, the human-review
worksheet) is gated and added behind --emit-worksheet / --score once this core is green.

Key correction from v1 (Codex reject): the decisive metric is UNIQUE recovery -- an
alternate scan supplying a correct reading the baseline panel lacks -- not redundant
recovery at positions where the panel already agrees. The cross-family proxy only routes
human attention (easy vs hard); it never serves as ground truth.
"""
from __future__ import annotations

import math

# Baseline panel families. The proxy counts agreement among the NON-ABBYY families only:
# all ABBYY scans collapse to one family, so abbyy agreement is not independent evidence.
# The study's internal vocabulary is SHORT names; WCT-sourced family names are normalized
# to these at the WCT-reading boundary (triage_position) via WCT_TO_STUDY_FAMILY.
_NON_ABBYY_FAMILIES = ("tesseract", "azure", "kraken")

# Canonical WCT engine_family -> study short-name map. Single source of truth for the two
# family vocabularies in this pipeline: the word-confusion-table-v1 enum uses long names
# (e.g. "azure-ai-vision", mapped from rendering-side "azure_read" by wct_builder._FAMILY_MAP),
# while the study keys on short names ("azure"). Every consumer that bridges the two
# vocabularies imports THIS map -- do not add a second copy (CC-ARCH-05). Consumed by
# nsh_gold_worksheet._baseline_candidates and by normalize_wct_families below.
WCT_TO_STUDY_FAMILY = {
    "tesseract": "tesseract",
    "abbyy": "abbyy",
    "azure-ai-vision": "azure",
    "kraken": "kraken",
}


def normalize_wct_families(
    candidates: dict[str, str | None],
) -> dict[str, str | None]:
    """Rename WCT engine-family keys to the study's short vocabulary.

    WCT emits long family names ("azure-ai-vision"); the study reasons in short names
    ("azure"). Keys already in short form pass through unchanged (the map is identity on
    them); families outside the map (e.g. surya/calamari, absent from JE) pass through
    untouched. This is the study's WCT-reading boundary: normalize once here so azure
    agreement is counted no matter which vocabulary the caller supplies.
    """
    return {
        WCT_TO_STUDY_FAMILY.get(family, family): reading
        for family, reading in candidates.items()
    }

# Stratum thresholds (percentile within the volume, 0..1). See design §6.
_DEGRADED_CONF_PCT = 0.25
_DENSE_WORDCOUNT_PCT = 0.75


def triage_position(baseline_candidates: dict[str, str | None]) -> str:
    """Route a position to human review.

    'easy' if >=2 non-ABBYY families (tesseract/azure/kraken) read the same word -- the
    correct candidate is already in the panel, so the position is low-value for measuring
    alternate-scan recovery. 'hard' otherwise: exactly the positions where an alternate
    ABBYY scan might supply a word nobody else has.
    """
    # Normalize any WCT-sourced long family names to the study's short vocabulary before
    # counting, so azure agreement (WCT "azure-ai-vision") is not read as absent.
    baseline_candidates = normalize_wct_families(baseline_candidates)
    readings: dict[str, int] = {}
    for family in _NON_ABBYY_FAMILIES:
        reading = baseline_candidates.get(family)
        if reading is None:
            continue
        readings[reading] = readings.get(reading, 0) + 1
    top = max(readings.values(), default=0)
    return "easy" if top >= 2 else "hard"


def score_position(
    baseline_candidates: dict[str, str | None],
    alternate_candidates: dict[str, str | None],
    true_reading: str,
) -> dict[str, bool]:
    """Score one human-verified position against its true reading.

    Returns the three per-position events the decision rule reads:
      unique_recovery   -- baseline lacks true_reading, an alternate supplies it (the value)
      redundant_recovery -- baseline already had true_reading, an alternate echoes it
      noise_added       -- an alternate introduces a wrong reading the baseline did not carry
    Noise is per position: many correlated ABBYY scans sharing one wrong reading is one event.
    """
    baseline_readings = {r for r in baseline_candidates.values() if r is not None}
    alternate_readings = {r for r in alternate_candidates.values() if r is not None}

    baseline_has_true = true_reading in baseline_readings
    alternate_has_true = true_reading in alternate_readings

    noise_added = any(
        r != true_reading and r not in baseline_readings for r in alternate_readings
    )
    return {
        "unique_recovery": (not baseline_has_true) and alternate_has_true,
        "redundant_recovery": baseline_has_true and alternate_has_true,
        "noise_added": noise_added,
    }


def stratify(page_features: dict) -> str:
    """Assign a page (or position) to a sampling stratum by priority:
    greek_hebrew > degraded > dense > clean. See design §6."""
    if page_features.get("has_greek_hebrew"):
        return "greek_hebrew"
    if page_features.get("primary_conf_pct", 1.0) < _DEGRADED_CONF_PCT:
        return "degraded"
    if page_features.get("word_count_pct", 0.0) > _DENSE_WORDCOUNT_PCT:
        return "dense"
    return "clean"


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval (default z=1.96). The decision rule reads the upper bound.
    An empty sample returns the full (0, 1) interval -- maximal uncertainty."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))
