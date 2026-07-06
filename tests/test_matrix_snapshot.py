"""B11 — S4 immutable replayable matrix snapshots + inconsistency gate (TEST-16 RED-first).

Failing-first contract for build/lib/matrix_snapshot.py. Encodes the arch4
snapshot model (synthesis 2026-05-27 section 8.2: non-circular identity, payload
hash verified before any cell is read) and lock section 6 item 24 (replay
byte-identical as a publication gate):

- immutable replayable snapshots: a snapshot rebuilt from the ledger is
  byte-identical across rebuilds; loading verifies payload_hash == sha256(payload
  bytes), so an in-place edit of the payload breaks replay and is rejected.
- inconsistency gate: promotion re-replays the ledger and rejects a candidate
  whose posteriors (counts) do not match the authoritative replay.
"""

from __future__ import annotations

import json

import pytest

from build.lib.matrix_counters import record_observation
from build.lib.matrix_observation_sink import MatrixObservationSink
from build.lib.matrix_snapshot import (
    PromotionBlockedError,
    SnapshotIntegrityError,
    build_envelope,
    canonical_bytes,
    load_snapshot,
    payload_hash,
    promote_snapshot,
    rebuild_payload_from_ledger,
    write_snapshot,
)

POLICY_VERSION = "weight-matrix-policy-v1"
NAMESPACE = {
    "work_id": "schaff_herzog",
    "edition_id": "nsh_1908_1914",
    "matrix_policy_version": POLICY_VERSION,
}


def _label(binary_outcome="correct", region_class="body", volume=1):
    return {
        "engine_version_key": "tesseract|5.5.0|eng|default",
        "scan_lineage_id": "ia-abbyy-v1",
        "volume": volume,
        "region_class": region_class,
        "binary_outcome": binary_outcome,
    }


def _seed_ledger(tmp_path):
    sink = MatrixObservationSink(repo_root=tmp_path, policy_version=POLICY_VERSION)
    common = dict(
        family_map_readiness=True,
        family_diversity_count=2,
        independent_check_present=True,
        is_dictionary_pass_only=False,
        event_type="choose_attestation",
        occurred_at="2026-05-29T00:00:00Z",
    )
    record_observation(sink, event_id="a", label=_label("correct"), **common)
    record_observation(sink, event_id="b", label=_label("correct"), **common)
    record_observation(sink, event_id="c", label=_label("incorrect"), **common)
    return sink


def _envelope_for(payload):
    return build_envelope(
        payload,
        created_at="2026-05-29T00:00:00Z",
        created_by="b11-test",
        events_covered_first="a",
        events_covered_last="c",
    )


# --- byte-identical replay (lock item 24) ------------------------------------


def test_rebuild_from_ledger_is_byte_identical_across_runs(tmp_path):
    sink = _seed_ledger(tmp_path)
    payload_one = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    payload_two = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    assert canonical_bytes(payload_one) == canonical_bytes(payload_two)
    assert payload_hash(payload_one) == payload_hash(payload_two)


def test_written_snapshot_loads_back_byte_identically(tmp_path):
    sink = _seed_ledger(tmp_path)
    payload = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    envelope = _envelope_for(payload)
    _payload_path, envelope_path = write_snapshot(tmp_path, payload, envelope)

    loaded = load_snapshot(envelope_path)
    assert canonical_bytes(loaded) == canonical_bytes(payload)


def test_in_place_edit_of_payload_breaks_replay_and_is_rejected(tmp_path):
    sink = _seed_ledger(tmp_path)
    payload = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    envelope = _envelope_for(payload)
    payload_path, envelope_path = write_snapshot(tmp_path, payload, envelope)

    # Tamper the payload bytes on disk without updating the envelope hash.
    tampered = json.loads(payload_path.read_text(encoding="utf-8"))
    tampered["cells"][0]["observed"]["correct"] += 99
    payload_path.write_text(
        json.dumps(tampered, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(SnapshotIntegrityError):
        load_snapshot(envelope_path)


# --- inconsistency gate blocks promotion (arch4 8.5) -------------------------


def test_promotion_accepts_a_candidate_that_matches_a_clean_replay(tmp_path):
    sink = _seed_ledger(tmp_path)
    payload = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    candidate = _envelope_for(payload)
    promoted = promote_snapshot(
        sink,
        candidate,
        matrix_policy_version=POLICY_VERSION,
        namespace=NAMESPACE,
        requested_by="b11-test",
    )
    assert promoted["payload_hash"] == candidate["payload_hash"]


def test_promotion_rederives_envelope_and_ignores_forged_candidate_fields(tmp_path):
    # Codex review finding 2: promotion must re-derive the integrity-bearing
    # envelope (snapshot_id, payload_hash, payload_path) from the clean ledger
    # replay, not trust the candidate's copies. A candidate with the correct
    # payload_hash but a forged snapshot_id/payload_path must not have those
    # forged fields survive into the promoted envelope.
    sink = _seed_ledger(tmp_path)
    payload = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    candidate = _envelope_for(payload)
    candidate["snapshot_id"] = "wm-FORGED-deadbeefcafe"
    candidate["payload_path"] = "../../etc/forged.payload.json"

    promoted = promote_snapshot(
        sink,
        candidate,
        matrix_policy_version=POLICY_VERSION,
        namespace=NAMESPACE,
        requested_by="b11-test",
    )
    assert promoted["snapshot_id"] != "wm-FORGED-deadbeefcafe"
    assert promoted["payload_path"] != "../../etc/forged.payload.json"
    # The re-derived id is bound to the clean payload hash.
    assert promoted["payload_hash"] == payload_hash(payload)
    assert promoted["snapshot_id"].endswith(payload_hash(payload)[:12])


def test_promotion_blocked_when_candidate_posteriors_conflict_with_ledger(tmp_path):
    sink = _seed_ledger(tmp_path)
    payload = rebuild_payload_from_ledger(
        sink, matrix_policy_version=POLICY_VERSION, namespace=NAMESPACE
    )
    # Forge a candidate whose counts do not match a clean ledger replay
    # (inflated correct count => conflicting posterior).
    payload["cells"][0]["observed"]["correct"] += 5
    forged = _envelope_for(payload)

    with pytest.raises(PromotionBlockedError):
        promote_snapshot(
            sink,
            forged,
            matrix_policy_version=POLICY_VERSION,
            namespace=NAMESPACE,
            requested_by="b11-test",
        )
