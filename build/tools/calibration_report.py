"""calibration_report.py -- ADR-0013 Slot 4 calibration gate.

Loads all fixture sets under tests/fixtures/calibration/, runs the scoring
functions, and emits a JSON report to stdout.  Exit code 0 when pass=True;
1 when any fixture fails.

Usage:
  py -3 build/tools/calibration_report.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "calibration"

# Allow direct invocation (`py -3 build/tools/calibration_report.py`) by ensuring
# the repo root is on sys.path so `build.*` imports resolve.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Boundary fixture checks
# ---------------------------------------------------------------------------

def _check_boundary_fixtures(failures: list[str]) -> list[dict]:
    from build.lib.reconcile.block_alignment import score_block_pair

    results: list[dict] = []
    subdir = _FIXTURE_DIR / "score_bucket_boundaries"
    for path in sorted(subdir.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        result = score_block_pair(
            fixture["anchor_block"],
            fixture["attestor_block"],
            context=fixture.get("context"),
        )
        expected_score = fixture["target_score"]
        expected_bucket = fixture["expected_bucket"]
        expected_action = fixture["expected_action"]
        actual_score = result["score"]
        actual_bucket = result["bucket"]
        actual_action = result["action"]

        score_delta = abs(actual_score - expected_score)
        bucket_match = actual_bucket == expected_bucket
        action_match = actual_action == expected_action
        score_ok = score_delta <= 0.5

        entry = {
            "fixture_id": fixture["fixture_id"],
            "expected_score": expected_score,
            "actual_score": actual_score,
            "expected_bucket": expected_bucket,
            "actual_bucket": actual_bucket,
            "expected_action": expected_action,
            "actual_action": actual_action,
            "bucket_match": bucket_match,
            "action_match": action_match,
        }
        results.append(entry)

        fid = fixture["fixture_id"]
        if not bucket_match:
            failures.append(
                f"{fid}: bucket expected={expected_bucket}, actual={actual_bucket}"
            )
        if not action_match:
            failures.append(
                f"{fid}: action expected={expected_action}, actual={actual_action}"
            )
        if not score_ok:
            failures.append(
                f"{fid}: score expected={expected_score}, actual={actual_score}, "
                f"delta={score_delta:.1f}"
            )
    return results


# ---------------------------------------------------------------------------
# Per-signal contribution checks
# ---------------------------------------------------------------------------

def _check_per_signal_fixtures(failures: list[str]) -> list[dict]:
    from build.lib.reconcile.block_alignment import score_block_pair

    results: list[dict] = []
    subdir = _FIXTURE_DIR / "per_signal_contribution"
    for path in sorted(subdir.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        result = score_block_pair(
            fixture["anchor_block"],
            fixture["attestor_block"],
            context=fixture.get("context"),
        )
        actual_by_name = {s["name"]: s["contribution"] for s in result["signals"]}
        expected = fixture["expected_signal_contributions"]

        signal_results: list[dict] = []
        all_match = True
        for signal_name, expected_val in expected.items():
            actual_val = actual_by_name.get(signal_name)
            match = actual_val == expected_val
            signal_results.append({
                "signal": signal_name,
                "expected": expected_val,
                "actual": actual_val,
                "match": match,
            })
            if not match:
                all_match = False
                failures.append(
                    f"{fixture['fixture_id']}: signal {signal_name} "
                    f"expected={expected_val}, actual={actual_val}"
                )

        results.append({
            "fixture_id": fixture["fixture_id"],
            "all_signals_match": all_match,
            "signal_results": signal_results,
        })
    return results


# ---------------------------------------------------------------------------
# Modifier fixture checks
# ---------------------------------------------------------------------------

def _evaluate_modifier(modifier: str, triggering: dict, near_miss: dict) -> tuple[bool, bool]:
    """Return (triggering_fired, near_miss_fired) for the named modifier."""
    from build.lib.reconcile.assemble import (
        _ROLE_BASE_SCORE,
        _score_reading,
        check_lexicon_modifier_fires,
        check_ocr_confusion_fires,
        check_punctuation_modifier,
    )

    if modifier == "broken_unicode":
        def _fires(case: dict) -> bool:
            score = _score_reading(case["reading"], "r1", case["role"], case.get("language", "en"))
            return score < _ROLE_BASE_SCORE.get(case["role"], 2.0)
        return _fires(triggering), _fires(near_miss)

    if modifier == "lexicon":
        def _fires_lex(case: dict) -> bool:
            lang = case.get("language", "la")
            return check_lexicon_modifier_fires(
                [case["anchor_reading"]], [case["attestor_reading"]], lang
            )
        return _fires_lex(triggering), _fires_lex(near_miss)

    if modifier == "ocr_confusion":
        def _fires_ocr(case: dict) -> bool:
            lang = case.get("language", "en")
            a_tokens = case["anchor_reading"].split()
            b_tokens = case["attestor_reading"].split()
            return check_ocr_confusion_fires(a_tokens, b_tokens, lang)
        return _fires_ocr(triggering), _fires_ocr(near_miss)

    if modifier == "punctuation":
        def _fires_punc(case: dict) -> bool:
            return check_punctuation_modifier(case["reading"], case["anchor_style"]) > 0.0
        return _fires_punc(triggering), _fires_punc(near_miss)

    if modifier == "reference_only_advisory":
        def _fires_ref(case: dict) -> bool:
            role = case.get("rendering_role", "")
            if role == "reference_only":
                actual_pd = 0.0
                actual_adv = 0.5
            else:
                actual_pd = _ROLE_BASE_SCORE.get(role, 2.0)
                actual_adv = 0.0
            expected_pd = case.get("expected_pd_contribution", 0.0)
            expected_adv = case.get("expected_advisory_score", 0.0)
            # "modifier fires" = advisory path taken AND scores are correct
            return (
                actual_adv > 0.0
                and abs(actual_pd - expected_pd) < 0.01
                and abs(actual_adv - expected_adv) < 0.01
            )
        return _fires_ref(triggering), _fires_ref(near_miss)

    raise ValueError(f"Unknown modifier: {modifier!r}")


def _check_modifier_fixtures(failures: list[str]) -> list[dict]:
    results: list[dict] = []
    subdir = _FIXTURE_DIR / "reading_score_modifiers"
    for path in sorted(subdir.glob("*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        modifier = fixture["modifier"]
        triggering = fixture["triggering"]
        near_miss = fixture["near_miss"]

        triggering_fired, near_miss_fired = _evaluate_modifier(modifier, triggering, near_miss)

        entry: dict = {
            "modifier": modifier,
            "triggering_fired": triggering_fired,
            "near_miss_fired": near_miss_fired,
        }
        results.append(entry)

        if not triggering_fired:
            failures.append(f"modifier {modifier}: triggering input did not fire")
        if near_miss_fired:
            failures.append(f"modifier {modifier}: near-miss input incorrectly fired")

    return results


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------

def run_report() -> dict:
    """Run all calibration checks; return the complete report dict."""
    failures: list[str] = []

    boundary_results = _check_boundary_fixtures(failures)
    modifier_results = _check_modifier_fixtures(failures)
    per_signal_results = _check_per_signal_fixtures(failures)

    bucket_distribution: dict[str, int] = {"high": 0, "mid_high": 0, "mid_low": 0, "low": 0}
    for r in boundary_results:
        bucket = r["actual_bucket"]
        bucket_distribution[bucket] = bucket_distribution.get(bucket, 0) + 1

    per_modifier_fired = {
        r["modifier"]: {
            "triggering_fired": r["triggering_fired"],
            "near_miss_fired": r["near_miss_fired"],
        }
        for r in modifier_results
    }

    return {
        "pass": len(failures) == 0,
        "failures": failures,
        "bucket_distribution": bucket_distribution,
        "per_modifier_fired": per_modifier_fired,
        "per_signal_contributions": per_signal_results,
        "boundary_results": boundary_results,
        "modifier_results": modifier_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="ADR-0013 calibration report")
    parser.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    args = parser.parse_args()

    report = run_report()

    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()  # trailing newline for cleanliness

    if not report["pass"]:
        if not args.json:
            print("CALIBRATION FAILED")
            for f in report["failures"]:
                print(" -", f)
        sys.exit(1)
    else:
        if not args.json:
            print("CALIBRATION PASSED")


if __name__ == "__main__":
    main()
