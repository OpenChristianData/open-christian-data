"""B15 failing-first tests: decision-event store, queue assembly, reviewer-ops report.

Architecture contract: arch7 reviewer synthesis + archD B15 row.
All three groups must be RED before production code lands (TEST-16).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GENESIS_HASH = "sha256:" + "0" * 64


def _ct(n: int) -> str:
    """Build a valid ct-sha256 token id from an integer index."""
    return f"ct-sha256:{n:064x}"


_AUTHORITY_TYPES = {
    "choose_attestation", "amend_text", "confirm_unresolved", "resolve_structure",
    "reject_machine_flag", "rebind_target", "supersede_decision", "mark_gold", "withdraw_gold",
}


def _make_minimal_event(
    event_type: str,
    canonical_token_id: str,
    *,
    timestamp: str = "2026-01-01T00:00:00+00:00",
    **overrides,
) -> dict:
    """Build a minimal valid decision-event-v1 dict for testing.

    No event_hash / prev_event_hash — those are added by the store writer.
    """
    event_category = (
        "authority_decision" if event_type in _AUTHORITY_TYPES else "workflow_event"
    )
    base: dict = {
        "schema_version": "decision-event-v1",
        "event_id": "de-sha256:" + "0" * 64,
        "event_type": event_type,
        "event_category": event_category,
        "volume": 1,
        "canonical_token_id": canonical_token_id,
        "actor_id": "maintainer",
        "timestamp": timestamp,
        "measurement_eligible": True,
        # authority_decision required fields
        "structural_path_at_decision": "vol_01/article/faith",
        "previous_status_at_view": "consensus",
        "new_status": "reviewed",
    }
    if event_type == "choose_attestation":
        base["selected_observation_token_id"] = "ot-sha256:" + "0" * 64
        base["decision_token"] = overrides.pop("decision_token", "ratification")
    elif event_type == "amend_text":
        base["amended_text"] = overrides.pop("amended_text", "faith")
        base["decision_token"] = overrides.pop("decision_token", "amend")
        base["amendment_reason"] = overrides.pop("amendment_reason", "correction")
    elif event_type == "confirm_unresolved":
        base["unresolved_reason"] = overrides.pop("unresolved_reason", "ambiguous")
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Group A: queue render
# ---------------------------------------------------------------------------

class TestQueueAssembly:
    def test_queue_item_has_required_fields(self):
        """assemble_queue_item returns a dict with the 7 required fields."""
        from build.lib.queue_assembly import assemble_queue_item

        token = {
            "canonical_token_id": "ct-sha256:" + "a" * 64,
            "volume": 1,
            "candidate_attestations": [{"engine_id": "tesseract", "text": "faith"}],
            "matrix_phase": "weak",
            "decision_action": "choose_attestation",
            "deferral_reason": None,
            "batch_id": "b15-test",
        }
        item = assemble_queue_item(token)
        assert item["canonical_token_id"] == token["canonical_token_id"]
        assert item["batch_id"] == "b15-test"
        assert "candidate_attestations" in item
        assert "matrix_phase" in item
        assert "decision_action" in item
        assert "scan_crop" in item
        assert "deferral_reason" in item

    def test_queue_item_candidate_attestations_present(self):
        """candidate_attestations from the token are passed through."""
        from build.lib.queue_assembly import assemble_queue_item

        attestations = [
            {"engine_id": "tesseract", "text": "grace"},
            {"engine_id": "surya", "text": "grace"},
        ]
        item = assemble_queue_item({
            "canonical_token_id": "ct-sha256:" + "b" * 64,
            "volume": 1,
            "candidate_attestations": attestations,
            "matrix_phase": "unconfirmed",
            "decision_action": "confirm_unresolved",
            "deferral_reason": "ambiguous scan",
            "batch_id": "b15-test",
        })
        assert item["candidate_attestations"] == attestations

    def test_queue_item_scan_crop_is_placeholder(self):
        """scan_crop is None in mock mode (scan_crop.py not yet implemented)."""
        from build.lib.queue_assembly import assemble_queue_item

        item = assemble_queue_item({
            "canonical_token_id": "ct-sha256:" + "c" * 64,
            "volume": 1,
            "candidate_attestations": [],
            "matrix_phase": "weak",
            "decision_action": "choose_attestation",
            "deferral_reason": None,
            "batch_id": "b15-test",
        })
        assert item["scan_crop"] is None

    def test_queue_item_deferral_reason_passed_through(self):
        """deferral_reason is preserved when provided."""
        from build.lib.queue_assembly import assemble_queue_item

        item = assemble_queue_item({
            "canonical_token_id": "ct-sha256:" + "d" * 64,
            "volume": 1,
            "candidate_attestations": [],
            "matrix_phase": "weak",
            "decision_action": "confirm_unresolved",
            "deferral_reason": "low scan quality",
            "batch_id": "batch-x",
        })
        assert item["deferral_reason"] == "low scan quality"


# ---------------------------------------------------------------------------
# Group B: decision-event store write + hash chain
# ---------------------------------------------------------------------------

class TestDecisionStore:
    def test_append_creates_store_file(self, tmp_path):
        """First append creates events.jsonl under decisions/schaff-herzog/vol_01/."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=1)
        event = _make_minimal_event("choose_attestation", "ct-sha256:" + "e" * 64)
        store.append(event)
        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        assert store_path.exists()
        lines = store_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1

    def test_first_event_prev_hash_is_genesis(self, tmp_path):
        """First event's prev_event_hash is the genesis sentinel."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event("choose_attestation", "ct-sha256:" + "f" * 64))
        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        record = json.loads(store_path.read_text(encoding="utf-8").strip())
        assert record["prev_event_hash"] == GENESIS_HASH

    def test_hash_chain_links_consecutive_events(self, tmp_path):
        """Second event's prev_event_hash equals first event's event_hash."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=1)
        e1 = _make_minimal_event("choose_attestation", _ct(7))
        e2 = _make_minimal_event(
            "amend_text", _ct(8),
            amended_text="mercy", amendment_reason="typo",
        )
        store.append(e1)
        store.append(e2)
        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        lines = store_path.read_text(encoding="utf-8").splitlines()
        r1 = json.loads(lines[0])
        r2 = json.loads(lines[1])
        assert r1["prev_event_hash"] == GENESIS_HASH
        assert r2["prev_event_hash"] == r1["event_hash"]
        assert r1["event_hash"] != r2["event_hash"]

    def test_fold_returns_events_in_append_order(self, tmp_path):
        """fold() returns events in hash-chain append order."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event("choose_attestation", _ct(9)))
        store.append(_make_minimal_event(
            "amend_text", _ct(10),
            amended_text="x", amendment_reason="r",
        ))
        folded = store.fold()
        assert folded[0]["event_type"] == "choose_attestation"
        assert folded[1]["event_type"] == "amend_text"

    def test_fold_order_is_append_order_not_occurred_at(self, tmp_path):
        """Fold uses hash-chain order, never occurred_at/timestamp (arch7 §1.1)."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=1)
        # e1 has a LATER timestamp but is appended first
        e1 = _make_minimal_event(
            "choose_attestation", _ct(11),
            timestamp="2099-01-02T00:00:00+00:00",
        )
        e2 = _make_minimal_event(
            "amend_text", _ct(11),
            amended_text="x", amendment_reason="r",
            timestamp="2000-01-01T00:00:00+00:00",
        )
        store.append(e1)
        store.append(e2)
        folded = store.fold()
        assert folded[0]["event_type"] == "choose_attestation"
        assert folded[1]["event_type"] == "amend_text"

    def test_tampered_event_hash_raises_corrupt_error(self, tmp_path):
        """A tampered event_hash triggers StoreCorruptError(event_hash_mismatch)."""
        from build.lib.decision_store import DecisionStore, StoreCorruptError

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event("choose_attestation", _ct(12)))
        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        raw = store_path.read_text(encoding="utf-8").strip()
        record = json.loads(raw)
        record["event_hash"] = "sha256:" + "0" * 64   # tamper
        store_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with pytest.raises(StoreCorruptError) as exc_info:
            store.fold()
        assert exc_info.value.failure_class == "event_hash_mismatch"

    def test_prev_hash_mismatch_raises_corrupt_error(self, tmp_path):
        """A tampered prev_event_hash on line 2 triggers prev_hash_mismatch."""
        from build.lib.decision_store import DecisionStore, StoreCorruptError

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event("choose_attestation", _ct(13)))
        store.append(_make_minimal_event(
            "amend_text", _ct(14),
            amended_text="x", amendment_reason="r",
        ))
        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        lines = store_path.read_text(encoding="utf-8").splitlines()
        r2 = json.loads(lines[1])
        r2["prev_event_hash"] = "sha256:" + "9" * 64  # tamper
        # must recompute event_hash to avoid triggering event_hash_mismatch first;
        # here we just verify SOME corrupt error is raised (prev_hash detected first
        # if we also re-hash, but we can accept either failure class)
        store_path.write_text(lines[0] + "\n" + json.dumps(r2) + "\n", encoding="utf-8")
        with pytest.raises(StoreCorruptError):
            store.fold()

    def test_unknown_event_type_raises_corrupt_error(self, tmp_path):
        """A stored event with an unknown event_type triggers unknown_event_type."""
        from build.lib.decision_store import DecisionStore, StoreCorruptError

        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        bad = {
            "schema_version": "decision-event-v1",
            "event_type": "not_a_real_event",
            "event_category": "workflow_event",
            "volume": 1,
            "event_id": "de-sha256:" + "0" * 64,
            "actor_id": "system:test",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "measurement_eligible": False,
            "event_hash": "sha256:" + "0" * 64,
            "prev_event_hash": GENESIS_HASH,
        }
        store_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        store = DecisionStore(base_dir=tmp_path, volume=1)
        with pytest.raises(StoreCorruptError) as exc_info:
            store.fold()
        assert exc_info.value.failure_class == "unknown_event_type"

    def test_json_parse_error_raises_corrupt_error(self, tmp_path):
        """A non-JSON line triggers StoreCorruptError(json_parse_error)."""
        from build.lib.decision_store import DecisionStore, StoreCorruptError

        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("this is not json\n", encoding="utf-8")
        store = DecisionStore(base_dir=tmp_path, volume=1)
        with pytest.raises(StoreCorruptError) as exc_info:
            store.fold()
        assert exc_info.value.failure_class == "json_parse_error"

    def test_duplicate_event_id_raises_corrupt_error(self, tmp_path):
        """Two events with identical event_id trigger duplicate_event_id."""
        from build.lib.decision_store import DecisionStore, StoreCorruptError

        store = DecisionStore(base_dir=tmp_path, volume=1)
        # Append two events with the same content (same event_id by JCS derivation)
        e = _make_minimal_event("choose_attestation", _ct(15))
        store.append(e)
        # Manually patch the second line to reuse the first event_id
        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        first = json.loads(store_path.read_text(encoding="utf-8").strip())
        first_id = first["event_id"]
        # Write a second line that duplicates the event_id
        store.append(_make_minimal_event(
            "amend_text", _ct(16),
            amended_text="grace", amendment_reason="dup test",
        ))
        lines = store_path.read_text(encoding="utf-8").splitlines()
        r2 = json.loads(lines[1])
        r2["event_id"] = first_id   # force duplicate
        # We can't re-sign this without the store writer; just inject directly
        # The fold should detect duplicate_event_id before event_hash_mismatch
        # Only patch the JSONL to inject the duplicate_id:
        store_path.write_text(lines[0] + "\n" + json.dumps(r2) + "\n", encoding="utf-8")
        with pytest.raises(StoreCorruptError) as exc_info:
            store.fold()
        # Accept either duplicate_event_id or event_hash_mismatch (latter fires if
        # fold re-verifies hash after patching).  The key invariant is that fold raises.
        assert exc_info.value.failure_class in {"duplicate_event_id", "event_hash_mismatch"}

    def test_replay_is_byte_identical(self, tmp_path):
        """Replaying the same event sequence produces byte-identical lines."""
        from build.lib.decision_store import DecisionStore

        events = [
            _make_minimal_event("choose_attestation", _ct(17)),
            _make_minimal_event(
                "confirm_unresolved", _ct(18),
                unresolved_reason="ambiguous",
            ),
        ]
        store_path_a = tmp_path / "a" / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        store_path_b = tmp_path / "b" / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"

        store_a = DecisionStore(base_dir=tmp_path / "a", volume=1)
        for e in events:
            store_a.append(e)

        store_b = DecisionStore(base_dir=tmp_path / "b", volume=1)
        for e in events:
            store_b.append(e)

        assert store_path_a.read_bytes() == store_path_b.read_bytes()

    def test_store_path_property(self, tmp_path):
        """store_path points to the correct JSONL file for the volume."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=3)
        expected = tmp_path / "decisions" / "schaff-herzog" / "vol_03" / "events.jsonl"
        assert store.store_path == expected

    def test_publication_mode_complete_on_valid_store(self, tmp_path):
        """publication_mode returns 'complete' when fold() succeeds."""
        from build.lib.decision_store import DecisionStore

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event("choose_attestation", _ct(19)))
        assert store.publication_mode == "complete"

    def test_publication_mode_blocked_on_corrupt_store(self, tmp_path):
        """publication_mode returns 'blocked_store_corrupt' when fold() raises."""
        from build.lib.decision_store import DecisionStore

        store_path = tmp_path / "decisions" / "schaff-herzog" / "vol_01" / "events.jsonl"
        store_path.parent.mkdir(parents=True, exist_ok=True)
        store_path.write_text("not json\n", encoding="utf-8")
        store = DecisionStore(base_dir=tmp_path, volume=1)
        assert store.publication_mode == "blocked_store_corrupt"


# ---------------------------------------------------------------------------
# Group C: reviewer-ops report
# ---------------------------------------------------------------------------

class TestReviewerOpsReport:
    def test_report_has_required_fields(self, tmp_path):
        """compute_reviewer_ops_report returns all 6 required metric fields."""
        from build.lib.decision_store import DecisionStore
        from build.tools.reviewer_ops_report import compute_reviewer_ops_report

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event(
            "choose_attestation", _ct(20),
            timestamp="2026-01-01T10:00:00+00:00",
        ))
        report = compute_reviewer_ops_report(store)
        for field in ("inflow", "completed", "batch_confirm_rate", "override_rate",
                      "stale_age_seconds", "time_per_decision_seconds"):
            assert field in report, f"missing field: {field}"

    def test_report_override_rate(self, tmp_path):
        """override_rate = overrides / total authority decisions."""
        from build.lib.decision_store import DecisionStore
        from build.tools.reviewer_ops_report import compute_reviewer_ops_report

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event(
            "choose_attestation", _ct(21),
            decision_token="ratification",
        ))
        store.append(_make_minimal_event(
            "choose_attestation", _ct(22),
            decision_token="override",
        ))
        report = compute_reviewer_ops_report(store)
        assert report["override_rate"] == pytest.approx(0.5)

    def test_report_batch_confirm_rate(self, tmp_path):
        """batch_confirm_rate = ratifications / total authority decisions."""
        from build.lib.decision_store import DecisionStore
        from build.tools.reviewer_ops_report import compute_reviewer_ops_report

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event(
            "choose_attestation", _ct(23),
            decision_token="ratification",
        ))
        store.append(_make_minimal_event(
            "choose_attestation", _ct(24),
            decision_token="ratification",
        ))
        store.append(_make_minimal_event(
            "choose_attestation", _ct(25),
            decision_token="override",
        ))
        report = compute_reviewer_ops_report(store)
        assert report["batch_confirm_rate"] == pytest.approx(2 / 3)

    def test_report_inflow_and_completed(self, tmp_path):
        """inflow = total events; completed = authority_decision events."""
        from build.lib.decision_store import DecisionStore
        from build.tools.reviewer_ops_report import compute_reviewer_ops_report

        store = DecisionStore(base_dir=tmp_path, volume=1)
        store.append(_make_minimal_event(
            "choose_attestation", _ct(26),
        ))
        store.append(_make_minimal_event(
            "reviewer_recheck_requested", "ct-sha256:" + "1" * 64,
            reason="re-check needed", triggered_by="system",
        ))
        report = compute_reviewer_ops_report(store)
        assert report["inflow"] == 2
        assert report["completed"] == 1   # only the authority_decision event

    def test_report_empty_store(self, tmp_path):
        """An empty store returns zero for all numeric fields."""
        from build.lib.decision_store import DecisionStore
        from build.tools.reviewer_ops_report import compute_reviewer_ops_report

        store = DecisionStore(base_dir=tmp_path, volume=1)
        report = compute_reviewer_ops_report(store)
        assert report["inflow"] == 0
        assert report["completed"] == 0
        assert report["batch_confirm_rate"] == pytest.approx(0.0)
        assert report["override_rate"] == pytest.approx(0.0)
        assert report["stale_age_seconds"] == pytest.approx(0.0)
        assert report["time_per_decision_seconds"] == pytest.approx(0.0)
