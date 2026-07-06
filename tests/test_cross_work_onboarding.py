from __future__ import annotations

import pytest

_DEFERRED = (
    "item 13 onboard_cross_work_priors.py is deferred to the second-work-onboard "
    "activation trigger (B17 ships spec + failing-first tests only)"
)


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_no_approval_fails() -> None:
    from build.tools.onboard_cross_work_priors import transfer_priors

    result = transfer_priors(source_snapshot={}, approval=None, target_work={})
    assert result.rejected
    assert result.reason == "missing_approval"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_approval_without_manifest_hash_fails() -> None:
    from build.tools.onboard_cross_work_priors import transfer_priors

    approval = {"event_type": "human_approval"}
    result = transfer_priors(source_snapshot={}, approval=approval, target_work={})
    assert result.rejected
    assert result.reason == "approval_missing_manifest_hash"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_k_above_five_clamps_and_records_clamp() -> None:
    from build.tools.onboard_cross_work_priors import transfer_priors

    approval = {"event_type": "human_approval", "evaluation_manifest_hash": "sha256:abc"}
    result = transfer_priors(
        source_snapshot={"prior_strength_k": 20},
        approval=approval,
        target_work={},
    )
    assert result.prior_strength_k == 5
    assert "k_clamped_to_5" in result.notes


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_policy_mismatch_fails_closed() -> None:
    from build.tools.onboard_cross_work_priors import transfer_priors

    approval = {"event_type": "human_approval", "evaluation_manifest_hash": "sha256:abc"}
    result = transfer_priors(
        source_snapshot={
            "family": "latin",
            "region_class": "body",
            "schema_version": "matrix-v1",
            "transcription_policy": "source-faithful-token-v1",
        },
        approval=approval,
        target_work={
            "family": "greek",
            "region_class": "body",
            "schema_version": "matrix-v1",
            "transcription_policy": "source-faithful-token-v1",
        },
    )
    assert result.rejected
    assert result.reason == "policy_mismatch"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_transferred_prior_never_increments_observed_counts() -> None:
    from build.tools.onboard_cross_work_priors import transfer_priors

    approval = {"event_type": "human_approval", "evaluation_manifest_hash": "sha256:abc"}
    result = transfer_priors(
        source_snapshot={"correct": 50, "incorrect": 2},
        approval=approval,
        target_work={},
    )
    assert result.applied_as == "prior_only"
    assert result.observed_correct_delta == 0
    assert result.observed_incorrect_delta == 0
