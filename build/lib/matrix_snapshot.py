"""S4 immutable, replayable matrix snapshots + the promotion inconsistency gate (B11).

Contract source: ``plans/2026-05-27-arch4-weight-matrix-synthesis.md`` section 8
(snapshot model, non-circular identity) and the lock
``plans/2026-05-28-archC-integration-locked-architecture.md`` section 6 item 24
(replay byte-identical as a publication gate).

Identity is non-circular (arch4 8.2): the snapshot_id is derived from the payload
hash, never included in the hashed payload. Loading verifies
``payload_hash == sha256(canonical_bytes(payload))`` before any cell is read, so
an in-place edit of the payload is detected and rejected. Promotion re-replays
the ledger and rejects any candidate whose counters do not match the
authoritative replay (the inconsistency gate).

B11 path note: ``weight-matrix-snapshot-v1.schema.json`` is arch3-owned per the
arch4 handoff section 1; it is NOT minted here. The payload/envelope are
validated structurally in-code, and byte-identical replay is enforced by hash,
not by a JSON Schema. See the B11 entry in the implementation tracker.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from build.lib.matrix_counters import MatrixCounters, WeightCell
from build.lib.matrix_observation_sink import MatrixObservationSink

SNAPSHOT_SCHEMA_VERSION = "weight-matrix-v1"
COMPARISON_PROFILE_ID = "source-faithful-token-v1"
PRIOR_ORIGIN = "neutral"
PRIOR_POLICY_ID = "hierarchical-prior-v1"


class SnapshotIntegrityError(Exception):
    """Raised when a loaded payload's bytes do not match its envelope hash."""


class PromotionBlockedError(Exception):
    """Raised when a promotion candidate conflicts with the authoritative ledger replay."""


def canonical_bytes(payload: dict) -> bytes:
    """Deterministic canonical serialisation of a payload.

    Sorted keys + compact separators give the same bytes for the same value on
    every run -- the property byte-identical replay depends on. All payload
    values are strings/ints or the two fixed prior floats (1.0/1.0), whose Python
    repr is stable, so this is sufficient for v1 (full RFC 8785 is an arch3
    follow-up if non-trivial floats ever enter the payload).
    """
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def payload_hash(payload: dict) -> str:
    """sha256 hex of the canonical payload bytes."""
    return sha256(canonical_bytes(payload)).hexdigest()


def _serialise_cell(cell: WeightCell) -> dict:
    """One snapshot cell. Only persisted (non-derived) fields go in the payload.

    Derived quantities (posterior, phase, n_observed) are recomputed on load, so
    they cannot drift from the counts and cannot destabilise the hash.
    """
    return {
        "cell_key": {
            "engine_version_key": cell.cell_key.engine_version_key,
            "scan_lineage_id": cell.cell_key.scan_lineage_id,
            "volume": cell.cell_key.volume,
            "region_class": cell.cell_key.region_class,
            "comparison_profile_id": COMPARISON_PROFILE_ID,
        },
        "observed": {
            "correct": cell.correct,
            "incorrect": cell.incorrect,
            "retracted": cell.retracted,
        },
        "prior": {
            "alpha": cell.alpha,
            "beta": cell.beta,
            "origin": PRIOR_ORIGIN,
            "policy_id": PRIOR_POLICY_ID,
        },
        "threshold_class": cell.threshold_class,
    }


def build_payload(
    *,
    cells: list[WeightCell],
    ledger_tail_hash: str,
    matrix_policy_version: str,
    namespace: dict,
) -> dict:
    """Assemble the hashed payload (no snapshot_id field -- arch4 8.2).

    Cells are sorted by cell key so the same ledger always yields the same
    payload bytes regardless of dict insertion order.
    """
    ordered = sorted(cells, key=lambda c: c.cell_key.as_tuple())
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "matrix_policy_version": matrix_policy_version,
        "namespace": dict(namespace),
        "ledger_tail_hash": ledger_tail_hash,
        "cells": [_serialise_cell(cell) for cell in ordered],
    }


def build_envelope(
    payload: dict,
    *,
    created_at: str,
    created_by: str,
    events_covered_first: str,
    events_covered_last: str,
) -> dict:
    """Wrap a payload in its non-circular envelope (arch4 8.2)."""
    full_hash = payload_hash(payload)
    return {
        "snapshot_id": f"wm-{created_at[:10]}-{full_hash[:12]}",
        "payload_hash": full_hash,
        "payload_path": None,  # set by write_snapshot once the file path is known
        "metadata": {
            "created_at": created_at,
            "created_by": created_by,
            "events_covered_first": events_covered_first,
            "events_covered_last": events_covered_last,
        },
    }


def _snapshot_dir(repo_root: Path) -> Path:
    return Path(repo_root) / "cache" / "weight_matrix" / "snapshots"


def write_snapshot(repo_root: Path, payload: dict, envelope: dict) -> tuple[Path, Path]:
    """Write the immutable payload + envelope files atomically. Returns their paths.

    The payload is written with the exact canonical bytes that were hashed, so a
    later ``load_snapshot`` re-hash matches unless the file is tampered with.
    """
    snapshot_dir = _snapshot_dir(repo_root)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_id = envelope["snapshot_id"]
    payload_path = snapshot_dir / f"{snapshot_id}.payload.json"
    envelope_path = snapshot_dir / f"{snapshot_id}.envelope.json"

    payload_blob = canonical_bytes(payload)
    envelope = dict(envelope)
    envelope["payload_path"] = payload_path.name

    _atomic_write_bytes(payload_path, payload_blob)
    _atomic_write_bytes(
        envelope_path,
        json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8") + b"\n",
    )
    return payload_path, envelope_path


def _atomic_write_bytes(target: Path, blob: bytes) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(target)


def load_snapshot(envelope_path: Path) -> dict:
    """Load a snapshot, verifying payload bytes against the envelope hash first.

    Raises ``SnapshotIntegrityError`` if the on-disk payload does not hash to the
    envelope's ``payload_hash`` -- the in-place-edit rejection (lock item 24).
    """
    envelope_path = Path(envelope_path)
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    payload_path = envelope_path.with_name(envelope["payload_path"])
    payload_blob = payload_path.read_bytes()
    actual = sha256(payload_blob).hexdigest()
    if actual != envelope["payload_hash"]:
        raise SnapshotIntegrityError(
            f"payload hash {actual} does not match envelope hash "
            f"{envelope['payload_hash']} for {payload_path.name}"
        )
    return json.loads(payload_blob.decode("utf-8"))


def rebuild_payload_from_ledger(
    sink: MatrixObservationSink,
    *,
    matrix_policy_version: str,
    namespace: dict,
) -> dict:
    """Replay the ledger into a fresh payload -- the authoritative materialisation."""
    counters = MatrixCounters.from_ledger(sink.iter_entries())
    return build_payload(
        cells=list(counters.cells.values()),
        ledger_tail_hash=sink.head_hash(),
        matrix_policy_version=matrix_policy_version,
        namespace=namespace,
    )


def promote_snapshot(
    sink: MatrixObservationSink,
    candidate_envelope: dict,
    *,
    matrix_policy_version: str,
    namespace: dict,
    requested_by: str,
) -> dict:
    """Promote a candidate snapshot, gated on consistency with a clean ledger replay.

    The inconsistency gate (arch4 8.5 / lock item 24): re-replay the ledger,
    recompute the payload hash, and reject the candidate if its hash differs --
    that means the candidate's posteriors do not match the authoritative ledger
    (forged counts, stale state, or tampering). Returns the promoted envelope on
    success.
    """
    clean_payload = rebuild_payload_from_ledger(
        sink, matrix_policy_version=matrix_policy_version, namespace=namespace
    )
    clean_hash = payload_hash(clean_payload)
    if clean_hash != candidate_envelope["payload_hash"]:
        raise PromotionBlockedError(
            "candidate payload hash does not match a clean ledger replay: "
            f"candidate={candidate_envelope['payload_hash']} replay={clean_hash}"
        )
    # Re-derive the integrity-bearing envelope (snapshot_id, payload_hash,
    # payload_path) from the clean payload rather than trusting the candidate's
    # copies. The hash match above only proves the counts agree; it does not
    # vouch for a forged snapshot_id or payload_path on the candidate envelope.
    # Only the candidate's coverage window is carried forward as provenance.
    candidate_meta = candidate_envelope.get("metadata", {})
    promoted = build_envelope(
        clean_payload,
        created_at=candidate_meta.get("created_at", ""),
        created_by=requested_by,
        events_covered_first=candidate_meta.get("events_covered_first", ""),
        events_covered_last=candidate_meta.get("events_covered_last", ""),
    )
    promoted["metadata"]["promoted_by"] = requested_by
    return promoted


__all__ = [
    "SnapshotIntegrityError",
    "PromotionBlockedError",
    "canonical_bytes",
    "payload_hash",
    "build_payload",
    "build_envelope",
    "write_snapshot",
    "load_snapshot",
    "rebuild_payload_from_ledger",
    "promote_snapshot",
]
