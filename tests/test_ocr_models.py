"""test_ocr_models.py -- unit tests for OCR scanner data models.

Run: py -3 -m pytest tests/test_ocr_models.py -v
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.tools.ocr_scanner.models import Candidate, ScanResult, REASON_CODES  # noqa: E402


def _make_candidate(**overrides) -> Candidate:
    """Construct a Candidate with sensible defaults; overrides replace defaults."""
    defaults = dict(
        id="cand-0001",
        tier=1,
        reason="digit_in_letter",
        source_id="schaff-herzog",
        entry_id="schaff-herzog.theotokos",
        field_path="term",
        value="THE0T0K0S",
        suggestion="THEOTOKOS",
        suggestion_source="digit_substitution_table",
        confidence=0.95,
        context_before="prior entry text",
        context_after="Greek theological term",
        occurrences=1,
    )
    defaults.update(overrides)
    return Candidate(**defaults)


# ---------------------------------------------------------------------------
# Candidate.to_dict roundtrip
# ---------------------------------------------------------------------------

def test_candidate_to_dict_roundtrip():
    """to_dict() produces a plain dict with all expected keys."""
    c = _make_candidate()
    d = c.to_dict()
    assert isinstance(d, dict)
    assert d["id"] == "cand-0001"
    assert d["tier"] == 1
    assert d["reason"] == "digit_in_letter"
    assert d["value"] == "THE0T0K0S"
    assert d["suggestion"] == "THEOTOKOS"
    assert d["confidence"] == 0.95
    assert d["occurrences"] == 1


def test_candidate_optional_fields_none():
    """suggestion and suggestion_source can be None."""
    c = _make_candidate(suggestion=None, suggestion_source=None)
    d = c.to_dict()
    assert d["suggestion"] is None
    assert d["suggestion_source"] is None


# ---------------------------------------------------------------------------
# ScanResult.candidates_by_tier
# ---------------------------------------------------------------------------

def test_scan_result_candidates_by_tier_empty():
    """Zero candidates produces zeroed tier counts."""
    r = ScanResult(
        source_id="schaff-herzog",
        scanned_at="2026-04-15T10:00:00+11:00",
        entries_scanned=0,
        pattern_set="ia_djvu",
        pattern_set_version="1",
    )
    counts = r.candidates_by_tier()
    assert counts == {"tier1": 0, "tier2": 0, "tier3": 0}


def test_scan_result_candidates_by_tier_mixed():
    """Counts correctly across mixed tiers."""
    r = ScanResult(
        source_id="schaff-herzog",
        scanned_at="2026-04-15T10:00:00+11:00",
        entries_scanned=100,
        pattern_set="ia_djvu",
        pattern_set_version="1",
        candidates=[
            _make_candidate(id="cand-0001", tier=1),
            _make_candidate(id="cand-0002", tier=1),
            _make_candidate(id="cand-0003", tier=2, reason="apparent_space_insertion"),
            _make_candidate(id="cand-0004", tier=3, reason="hapax_legomenon"),
        ],
    )
    counts = r.candidates_by_tier()
    assert counts["tier1"] == 2
    assert counts["tier2"] == 1
    assert counts["tier3"] == 1


def test_candidates_by_tier_ignores_unknown_tier():
    """Candidates with tier values outside 1/2/3 are silently dropped.

    NOTE: Must bypass __post_init__ validation since tier=99 is not in REASON_CODES.
    We test this by constructing normally then mutating tier after construction.
    __post_init__ is only called at construction time, not on attribute assignment.
    This tests the defensive guard in candidates_by_tier().
    """
    c = _make_candidate(id="cand-bad")
    c.tier = 99  # mutate after construction to bypass __post_init__
    r = ScanResult(
        source_id="test",
        scanned_at="2026-04-15T10:00:00+11:00",
        entries_scanned=1,
        pattern_set="ia_djvu",
        pattern_set_version="1",
        candidates=[c],
    )
    counts = r.candidates_by_tier()
    assert counts == {"tier1": 0, "tier2": 0, "tier3": 0}


# ---------------------------------------------------------------------------
# ScanResult.to_dict top-level keys
# ---------------------------------------------------------------------------

def test_scan_result_to_dict_keys():
    """to_dict() includes all top-level keys expected by report.write_report()."""
    r = ScanResult(
        source_id="schaff-herzog",
        scanned_at="2026-04-15T10:00:00+11:00",
        entries_scanned=8351,
        pattern_set="ia_djvu",
        pattern_set_version="1",
        candidates=[_make_candidate()],
    )
    d = r.to_dict()
    required_keys = {
        "source_id", "scanned_at", "entries_scanned",
        "pattern_set", "pattern_set_version",
        "candidates_total", "candidates_by_tier",
        "truncated", "truncated_reason", "candidates",
    }
    assert required_keys.issubset(d.keys())
    assert d["candidates_total"] == 1
    assert isinstance(d["candidates"], list)
    assert isinstance(d["candidates"][0], dict)
    assert d["candidates_by_tier"] == {"tier1": 1, "tier2": 0, "tier3": 0}


# ---------------------------------------------------------------------------
# REASON_CODES coverage
# ---------------------------------------------------------------------------

def test_reason_codes_has_all_tier1_ia_djvu():
    """All Tier 1 ia_djvu reason codes are present with tier=1.

    ligature_ae_loss was demoted to Tier 3 in the OCR Scanner Fixes plan.
    """
    expected = ["digit_in_letter", "ligature_bracket", "stray_pipe_backslash"]
    for code in expected:
        assert code in REASON_CODES, f"Missing reason code: {code}"
        assert REASON_CODES[code] == 1, f"{code} should be tier 1"


def test_reason_codes_has_tier3_ia_djvu():
    """ligature_ae_loss is Tier 3 (demoted from Tier 1 — 0% precision on SH)."""
    assert REASON_CODES.get("ligature_ae_loss") == 3


def test_reason_codes_has_tier2_ia_djvu():
    """All three Tier 2 ia_djvu reason codes present with tier=2."""
    expected = ["short_allcaps_orphan", "apparent_space_insertion", "apparent_space_deletion"]
    for code in expected:
        assert code in REASON_CODES
        assert REASON_CODES[code] == 2


def test_reason_codes_ccel_thml():
    """ccel_thml reason codes present with correct tiers."""
    assert REASON_CODES["entity_leak"] == 1
    assert REASON_CODES["unusual_bigram"] == 2
