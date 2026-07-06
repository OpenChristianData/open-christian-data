from __future__ import annotations

import pytest

_DEFERRED = (
    "item 14 cold-storage migration tools are deferred "
    "(B17 ships spec + failing-first tests only)"
)


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_artifact_younger_than_window_not_eligible() -> None:
    from build.tools.plan_cold_storage_migration import plan_migration

    result = plan_migration(
        artifacts=[{"artifact_id": "a1", "age_days_after_release": 30}],
        age_window_days=180,
    )
    assert result.items[0].eligible is False
    assert result.items[0].reason == "younger_than_window"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_artifact_in_unresolved_reviewer_queue_not_eligible() -> None:
    from build.tools.plan_cold_storage_migration import plan_migration

    result = plan_migration(
        artifacts=[{"artifact_id": "a1", "age_days_after_release": 240}],
        reviewer_queues={"a1": "unresolved"},
    )
    assert result.items[0].eligible is False
    assert result.items[0].reason == "unresolved_reviewer_queue"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_missing_restore_uri_fails() -> None:
    from build.tools.apply_cold_storage_migration import apply_migration

    result = apply_migration(plan={"items": [{"artifact_id": "a1", "restore_uri": None}]})
    assert result.failed
    assert result.reason == "missing_restore_uri"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_hash_mismatch_after_restore_simulation_fails() -> None:
    from build.tools.apply_cold_storage_migration import apply_migration

    result = apply_migration(
        plan={
            "items": [
                {
                    "artifact_id": "a1",
                    "content_hash": "sha256:expected",
                    "restore_simulation_hash": "sha256:actual",
                    "restore_uri": "cold://release/a1",
                }
            ]
        }
    )
    assert result.failed
    assert result.reason == "restore_hash_mismatch"


@pytest.mark.xfail(reason=_DEFERRED, strict=False)
def test_pointer_verifier_requires_restored_bytes_match() -> None:
    from build.tools.apply_cold_storage_migration import verify_migrated_pointer

    pointer = {
        "manifest_path": "reports/storage/cold_storage_migration_run.json",
        "content_hash": "sha256:expected",
        "storage_uri": "cold://release/a1",
        "restore_instructions": "restore from cold URI and compare hash",
    }
    result = verify_migrated_pointer(pointer, restored_bytes_hash="sha256:expected")
    assert result.verified
