from __future__ import annotations

import json

import pytest

from build.lib.typography_snapshot import (
    TypographySnapshotIntegrityError,
    assert_admissible,
    build_typography_envelope,
    build_typography_payload,
    load_typography_snapshot,
    write_typography_snapshot,
)

LIFECYCLE_KEYS = {
    "approval_state",
    "superseded_by_snapshot_id",
    "approved_at",
    "approver_id",
}


def _payload() -> dict:
    return build_typography_payload(
        cohort_id="cohort-schaff-herzog-v1",
        tier_assignments=[
            {"token_id": "v01-p0001-t0001", "relative_size_tier": "body"}
        ],
        canonical_x_size={"unit": "px", "value": 10.5},
        substyles=[{"substyle_id": "body-regular", "relative_size_tier": "body"}],
    )


def test_payload_envelope_hash_split() -> None:
    payload = _payload()
    draft = build_typography_envelope(payload, approval_state="draft")
    approved = build_typography_envelope(
        payload,
        approval_state="approved",
        approved_at="2026-05-31T00:00:00Z",
        approver_id="maintainer",
    )

    assert draft["snapshot_payload_hash"] == approved["snapshot_payload_hash"]
    assert draft["lifecycle_registry_hash"] != approved["lifecycle_registry_hash"]


def test_lifecycle_fields_not_in_payload() -> None:
    payload = _payload()
    assert LIFECYCLE_KEYS.isdisjoint(payload)


def test_load_detects_payload_tamper(tmp_path) -> None:
    payload = _payload()
    envelope = build_typography_envelope(payload)
    payload_path, envelope_path = write_typography_snapshot(tmp_path, payload, envelope)

    tampered = json.loads(payload_path.read_text(encoding="utf-8"))
    tampered["tier_assignments"][0]["relative_size_tier"] = "caption"
    payload_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(TypographySnapshotIntegrityError):
        load_typography_snapshot(envelope_path)


def test_conformance_admits_only_approved() -> None:
    approved = build_typography_envelope(
        _payload(),
        approval_state="approved",
        approved_at="2026-05-31T00:00:00Z",
        approver_id="maintainer",
    )
    assert_admissible(approved)

    for state in ("draft", "superseded"):
        envelope = build_typography_envelope(_payload(), approval_state=state)
        with pytest.raises(TypographySnapshotIntegrityError):
            assert_admissible(envelope)


def test_admissible_rejects_incomplete_approved_lifecycle() -> None:
    # An "approved" state with no approver / timestamp is not a real approval
    # and must not be admitted (Codex review finding 7).
    incomplete = build_typography_envelope(_payload(), approval_state="approved")
    with pytest.raises(TypographySnapshotIntegrityError):
        assert_admissible(incomplete)
