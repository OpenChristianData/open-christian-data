from __future__ import annotations

from pathlib import Path

import pytest


def _machine_release_event() -> dict:
    return {
        "schema_version": "decision-event-v1",
        "event_id": "jewish-encyclopedia.vol_02:vol_02:page_0010:token_0",
        "event_type": "machine_release",
        "event_category": "authority_decision",
        "volume": 2,
        "canonical_token_id": "ct-sha256:" + "1" * 64,
        "structural_path_at_decision": "vol_02:page_0010:body:c1:l000:p000",
        "previous_status_at_view": "unresolved",
        "new_status": "consensus",
        "status_authority": "consensus",
        "evidence_seen": {
            "wct_page_sha256": "cc7dfc066531135243667f5032621f9efba0ce7d2d8419a2080e1cc49ca54cca",
            "chosen_candidate_text": "on",
            "thresholds_file_id": "prompts/je-measurement-thresholds.json",
        },
        "decision_extras_carried": {
            "origin_kind": "observed",
            "derivation_method": "L0",
            "chosen_action": "release_accepted",
            "chosen_reading_index": 0,
        },
        "measurement_eligible": False,
        "actor_id": "system:corrector",
        "timestamp": "2026-07-04T02:12:32.236865Z",
    }


def _resolve_structure_event() -> dict:
    return {
        "schema_version": "decision-event-v1",
        "event_id": "de-sha256:" + "2" * 64,
        "event_type": "resolve_structure",
        "event_category": "authority_decision",
        "volume": 2,
        "canonical_token_id": "ct-sha256:" + "2" * 64,
        "structural_path_at_decision": "vol_02:page_0010:body:c1:l000:p000",
        "previous_status_at_view": "unresolved",
        "new_status": "reviewed",
        "structure_resolution": {"kind": "page_repair"},
        "measurement_eligible": True,
        "actor_id": "maintainer",
        "timestamp": "2026-07-04T02:12:32.236865Z",
    }


def test_complete_machine_release_live_shape_has_no_missing_fields() -> None:
    from build.lib.event_completeness import check_event_completeness

    assert check_event_completeness(_machine_release_event()) == []


def test_machine_release_reports_missing_context_fields() -> None:
    from build.lib.event_completeness import check_event_completeness

    missing_wct = _machine_release_event()
    del missing_wct["evidence_seen"]["wct_page_sha256"]
    assert check_event_completeness(missing_wct)

    missing_snapshot = _machine_release_event()
    del missing_snapshot["evidence_seen"]["thresholds_file_id"]
    assert check_event_completeness(missing_snapshot)

    missing_candidate = _machine_release_event()
    del missing_candidate["evidence_seen"]["chosen_candidate_text"]
    assert check_event_completeness(missing_candidate)


def test_non_ratification_event_is_not_gated_without_evidence_seen() -> None:
    from build.lib.event_completeness import check_event_completeness

    assert check_event_completeness(_resolve_structure_event()) == []


def test_append_many_enforced_context_raises_and_writes_nothing(tmp_path: Path) -> None:
    from build.lib.decision_store import DecisionStore
    from build.lib.event_completeness import EventIncompleteError

    event = _machine_release_event()
    del event["evidence_seen"]["wct_page_sha256"]

    store = DecisionStore(
        base_dir=tmp_path,
        volume=2,
        corpus_slug="jewish-encyclopedia",
        volume_id="vol_02",
    )
    with pytest.raises(EventIncompleteError):
        store.append_many([event], enforce_ratification_context=True)

    assert not store.store_path.exists()


def test_append_many_default_preserves_incomplete_event_behavior(tmp_path: Path) -> None:
    from build.lib.decision_store import DecisionStore

    event = _machine_release_event()
    del event["evidence_seen"]["wct_page_sha256"]

    store = DecisionStore(
        base_dir=tmp_path,
        volume=2,
        corpus_slug="jewish-encyclopedia",
        volume_id="vol_02",
    )
    store.append_many([event], enforce_ratification_context=False)

    assert store.store_path.exists()
    assert len(store.fold()) == 1
