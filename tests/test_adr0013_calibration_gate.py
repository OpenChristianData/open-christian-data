"""ADR-0013 calibration gate — Slot 4 completion criterion.

Three named tests per the Phase 1 plan:
  1. test_phase1_calibration_fixture_set_exists_and_runs
  2. test_reading_score_modifier_coverage
  3. test_score_bucket_boundaries

RED state: ImportError on the line below (calibration_report.py not yet created).
GREEN state: all three tests pass after calibration_report.py is implemented.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# This import is the RED gate: raises ImportError until calibration_report.py exists.
from build.tools.calibration_report import run_report  # noqa: F401

_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "calibration"
_REPORT_SCRIPT = Path(__file__).resolve().parents[1] / "build" / "tools" / "calibration_report.py"


def _run_report_json() -> dict:
    result = subprocess.run(
        [sys.executable, str(_REPORT_SCRIPT), "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_phase1_calibration_fixture_set_exists_and_runs():
    """calibration_report.py runs to completion; all three fixture directories covered; report is pass=True."""
    for subdir in ("score_bucket_boundaries", "reading_score_modifiers", "per_signal_contribution"):
        assert (_FIXTURE_DIR / subdir).is_dir(), f"fixture directory missing: {subdir}"
        assert any((_FIXTURE_DIR / subdir).glob("*.json")), f"no JSON fixtures in: {subdir}"

    report = _run_report_json()
    assert report.get("pass") is True, (
        "calibration_report did not return pass=True.\n"
        f"Failures: {report.get('failures', [])}"
    )
    assert "bucket_distribution" in report
    assert "per_modifier_fired" in report
    assert "per_signal_contributions" in report


def test_reading_score_modifier_coverage():
    """Each modifier fixture's triggering input fires the modifier; each near-miss does not."""
    report = _run_report_json()
    modifier_results = report.get("modifier_results", [])
    assert modifier_results, "modifier_results missing from report"

    for mod in modifier_results:
        modifier_name = mod["modifier"]
        assert mod["triggering_fired"], (
            f"Modifier '{modifier_name}' did not fire on its triggering input. "
            f"Expected value: {mod.get('expected_triggering_value')}, "
            f"got: {mod.get('actual_triggering_value')}"
        )
        assert not mod["near_miss_fired"], (
            f"Modifier '{modifier_name}' incorrectly fired on its near-miss input. "
            f"Near-miss reason: {mod.get('near_miss_reason')}"
        )


def test_score_bucket_boundaries():
    """Each of the six boundary fixtures (78/77/60/59/45/44) lands in its target bucket with the correct action."""
    report = _run_report_json()
    boundary_results = report.get("boundary_results", [])
    assert len(boundary_results) == 6, (
        f"Expected 6 boundary fixtures, got {len(boundary_results)}"
    )

    for result in boundary_results:
        fixture_id = result["fixture_id"]
        assert result["bucket_match"], (
            f"{fixture_id}: expected bucket '{result['expected_bucket']}', "
            f"got '{result['actual_bucket']}'"
        )
        assert result["action_match"], (
            f"{fixture_id}: expected action '{result['expected_action']}', "
            f"got '{result['actual_action']}'"
        )
        score_delta = abs(result["actual_score"] - result["expected_score"])
        assert score_delta <= 0.5, (
            f"{fixture_id}: score {result['actual_score']} deviates from "
            f"expected {result['expected_score']} by {score_delta} (tolerance 0.5)"
        )
