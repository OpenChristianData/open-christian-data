from __future__ import annotations

from build.tools.check_evaluation_manifest_stability import (
    check_manifest_stability,
    compute_manifest_id,
    reproduce_promotion,
)


def make_manifest(**overrides) -> dict:
    manifest = {
        "promotion_surface": "matrix_b_to_a",
        "sample_ids": ["s1", "s2"],
        "artifact_hashes": {"reconciled": "a" * 64},
        "policy_version": "weight-matrix-policy-v1",
        "thresholds": {"min_n": 250, "min_abs_acc_delta": 0.05},
        "report_hash": "b" * 64,
        "decision_event_ids": ["de1"],
        "decision": "promote",
        "scope": {"work_id": "schaff_herzog"},
        "cross_scope_approval": None,
        "metrics": {"n_observed": 300, "abs_acc_delta": 0.07},
    }
    manifest.update(overrides)
    manifest["eval_manifest_id"] = compute_manifest_id(manifest)
    return manifest


def _codes(result) -> set[str]:
    return {failure.code for failure in result.failures}


def test_valid_manifest_passes():
    manifest = make_manifest()

    result = check_manifest_stability(manifest)

    assert result.ok is True
    assert result.decision == "pass"


def test_changed_sample_membership_fails():
    manifest = make_manifest()
    manifest["sample_ids"] = ["s1", "s3"]

    result = check_manifest_stability(manifest)

    assert "id_content_mismatch" in _codes(result)


def test_threshold_change_without_policy_version_fails():
    prior = make_manifest()
    current = make_manifest(thresholds={"min_n": 300, "min_abs_acc_delta": 0.05})

    result = check_manifest_stability(current, prior_manifest=prior)

    assert "policy_version_unchanged" in _codes(result)


def test_cross_work_reuse_without_approval_fails():
    manifest = make_manifest()

    result = check_manifest_stability(manifest, reuse_scope={"work_id": "other_work"})

    assert "cross_scope_reuse_unapproved" in _codes(result)


def test_missing_report_hash_fails():
    manifest = make_manifest(report_hash="")

    result = check_manifest_stability(manifest)

    assert "missing_report_hash" in _codes(result)


def test_promotion_reproducible_from_manifest_only():
    promote = make_manifest()
    hold = make_manifest(decision="hold", metrics={"n_observed": 300, "abs_acc_delta": 0.01})

    assert reproduce_promotion(promote) == promote["decision"]
    assert reproduce_promotion(hold) == hold["decision"]
