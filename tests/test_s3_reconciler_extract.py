"""M10 extraction guards for S3 degraded reconciler internals."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build.lib.s3_reconciler import (  # noqa: E402
    DEFAULT_MATRIX_POLICY_VERSION,
    _assemble_position_blocks,
    _assert_no_premature_matrix_labels,
    _build_reviewer_queue_item,
    _choose_position_reading,
    _finalize_reconcile_invariants,
    _iter_ordered_positions,
    _make_matrix_candidate,
    _stamp_region_class,
    reconcile_degraded,
)

OCCURRED_AT = "2026-06-01T23:38:49.834292+10:00"
EXPECTED_RECORD_SHA256 = "93430b5689f4f5e4c33f3f1c288923cfa8345aa6277ab1b07a4b890dac21e4bb"
EXPECTED_MATRIX_SHA256 = "9ebbcafe295e84441cf6109d431ac94217947aba5ede2e876fb4504b1280f881"
EXPECTED_QUEUE_SHA256 = "506ac2b2d7e7709eeda1bb4b0ea808d445152fa5e98a200e826d24d871f59c58"
EXPECTED_SIGNALS_SHA256 = "a9ba93666472b5e165576c18553709a9bc785f451eef4055ac22bb263080c437"


def _load_json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_reconcile_degraded_real_page_serialises_to_pre_refactor_snapshot() -> None:
    if not (REPO_ROOT / "reports" / "wct" / "vol_01" / "page_0010.json").exists():
        # Live vol_01 WCT quarantined in R-final.3 (stale); restored by full WCT rebuild.
        pytest.skip("vol_01 WCT quarantined (R-final.3); restored by the full WCT rebuild")
    result = reconcile_degraded(
        _load_json("reports/wct/vol_01/page_0010.json"),
        _load_json("reports/reconciled/vol_01/work_meta.json"),
        occurred_at=OCCURRED_AT,
    )

    assert _sha256_json(result.reconciled_record) == EXPECTED_RECORD_SHA256
    assert _sha256_json({"candidates": result.matrix_event_candidates}) == EXPECTED_MATRIX_SHA256
    assert _sha256_json({"queue": result.reviewer_queue}) == EXPECTED_QUEUE_SHA256
    assert _sha256_json({"post_alignment_signals": result.post_alignment_signals}) == EXPECTED_SIGNALS_SHA256


def test_iter_ordered_positions_uses_reading_order_then_fixture_order_remainder() -> None:
    wct_page = {
        "reading_order": ["p2", "missing"],
        "positions": [
            {"position_id": "p1"},
            {"position_id": "p2"},
            {"position_id": "p3"},
        ],
    }

    assert [p["position_id"] for p in _iter_ordered_positions(wct_page)] == ["p2", "p1", "p3"]


def test_assemble_position_blocks_groups_zones_in_order() -> None:
    positions = [
        {"position_id": "p2", "zone": {"zone_id": "z2"}},
        {"position_id": "p1", "zone": {"zone_id": "z1"}},
        {"position_id": "p3", "zone": {"zone_id": "z2"}},
    ]

    blocks = _assemble_position_blocks(positions)

    assert [(zone_id, [p["position_id"] for p in zone_positions]) for zone_id, zone_positions in blocks] == [
        ("z2", ["p2", "p3"]),
        ("z1", ["p1"]),
    ]


def test_stamp_region_class_wraps_assignment_shape() -> None:
    assert _stamp_region_class("running-header", "latin") == {
        "region_class": "unknown",
        "policy_id": "v1",
        "pending": True,
    }


def test_choose_position_reading_accepts_parameterised_source() -> None:
    candidates = [
        {"candidate_id": "b", "raw_reading": "later"},
        {"candidate_id": "a", "raw_reading": "corrected"},
    ]

    assert _choose_position_reading(candidates, lambda items: items[1]) == {
        "candidate_id": "a",
        "raw_reading": "corrected",
    }


def test_make_matrix_candidate_uses_reason_mapping_and_sequence() -> None:
    assert _make_matrix_candidate(
        volume_id="vol_01",
        page_id="page_0010",
        position_id="p1",
        reason="dispute",
        entry_seq=7,
        occurred_at=OCCURRED_AT,
        matrix_policy_version=DEFAULT_MATRIX_POLICY_VERSION,
    ) == {
        "schema_version": "matrix-events-v1",
        "entry_seq": 7,
        "prev_entry_hash": "0000000000000000000000000000000000000000000000000000000000000000",
        "event_id": "vol_01:page_0010:p1",
        "event_type": "dispute_observation",
        "occurred_at": OCCURRED_AT,
        "policy_version": DEFAULT_MATRIX_POLICY_VERSION,
        "outcome": "not_measurement_eligible",
    }


def test_build_reviewer_queue_item_preserves_candidates_and_region_state() -> None:
    pos_region = type("Region", (), {"region_class": "unknown", "pending": True})()
    candidates = [{"raw_reading": "Abelard"}, {"raw_reading": "▲belavd"}]

    assert _build_reviewer_queue_item(
        position_id="p1",
        reason="region_class_pending",
        external_check_absent=False,
        pos_region=pos_region,
        candidates=candidates,
        chosen_reading="▲belavd",
    ) == {
        "position_id": "p1",
        "reason": "region_class_pending",
        "external_check_absent": False,
        "region_class": "unknown",
        "region_class_pending": True,
        "audit_priority": True,
        "candidates": ["Abelard", "▲belavd"],
        "chosen_reading": "▲belavd",
    }


def test_finalize_reconcile_invariants_keeps_premature_matrix_label_guard() -> None:
    record = {
        "blocks": [
            {
                "block_id": "b1",
                "annotations": {
                    "region_class": {
                        "region_class": "body",
                        "policy_id": "v1",
                        "pending": False,
                    },
                },
            },
        ],
    }
    candidates = [
        {
            "outcome": "labels_emitted",
        },
    ]

    with pytest.raises(ValueError, match="labels_emitted matrix candidate"):
        _finalize_reconcile_invariants(record, candidates)


def test_assert_no_premature_matrix_labels_still_fires_directly() -> None:
    with pytest.raises(ValueError, match="labels_emitted matrix candidate"):
        _assert_no_premature_matrix_labels([{"outcome": "labels_emitted"}])
