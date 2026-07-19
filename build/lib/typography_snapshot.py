from __future__ import annotations

import json, hashlib, sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ocd_kernel.lib.atomic_io import write_json_atomic

SNAPSHOT_DIR = Path("reports") / "publish" / "typography_snapshots"
LIFECYCLE_STATES = {"draft", "approved", "superseded"}
LIFECYCLE_KEYS = {
    "approval_state",
    "superseded_by_snapshot_id",
    "approved_at",
    "approver_id",
}

_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": [
        "snapshot_id",
        "snapshot_payload_hash",
        "lifecycle",
        "lifecycle_registry_hash",
        "payload_path",
    ],
    "additionalProperties": True,
}


class TypographySnapshotIntegrityError(Exception):
    """Raised when a typography snapshot is inadmissible or fails integrity checks."""


def _canonical_bytes(obj: dict) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def lifecycle_hash(lifecycle: dict) -> str:
    return hashlib.sha256(_canonical_bytes(lifecycle)).hexdigest()


def build_typography_payload(
    cohort_id: str,
    tier_assignments: list,
    canonical_x_size: dict,
    substyles: list,
) -> dict:
    payload = {
        "cohort_id": cohort_id,
        "tier_assignments": list(tier_assignments),
        "canonical_x_size": dict(canonical_x_size),
        "substyles": list(substyles),
    }
    leaked = LIFECYCLE_KEYS.intersection(payload)
    if leaked:
        raise TypographySnapshotIntegrityError(
            f"lifecycle fields are not allowed in payload: {sorted(leaked)}"
        )
    return payload


def build_typography_envelope(
    payload: dict,
    *,
    approval_state: str = "draft",
    superseded_by_snapshot_id: str | None = None,
    approved_at: str | None = None,
    approver_id: str | None = None,
) -> dict:
    if approval_state not in LIFECYCLE_STATES:
        raise TypographySnapshotIntegrityError(
            f"unknown typography approval_state: {approval_state}"
        )
    full_payload_hash = payload_hash(payload)
    lifecycle = {
        "approval_state": approval_state,
        "superseded_by_snapshot_id": superseded_by_snapshot_id,
        "approved_at": approved_at,
        "approver_id": approver_id,
    }
    return {
        "snapshot_id": f"typography-{full_payload_hash[:12]}",
        "snapshot_payload_hash": full_payload_hash,
        "lifecycle": lifecycle,
        "lifecycle_registry_hash": lifecycle_hash(lifecycle),
        "payload_path": None,
    }


def write_typography_snapshot(
    repo_root: Path, payload: dict, envelope: dict
) -> tuple[Path, Path]:
    snapshot_dir = Path(repo_root) / SNAPSHOT_DIR
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_id = str(envelope["snapshot_id"])
    payload_path = snapshot_dir / f"{snapshot_id}.payload.json"
    envelope_path = snapshot_dir / f"{snapshot_id}.envelope.json"

    _atomic_write_bytes(payload_path, _canonical_bytes(payload))
    persisted = dict(envelope)
    persisted["payload_path"] = payload_path.name
    write_json_atomic(envelope_path, persisted, _ENVELOPE_SCHEMA)
    return payload_path, envelope_path


def _atomic_write_bytes(target: Path, blob: bytes) -> None:
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(blob)
    tmp.replace(target)


def load_typography_snapshot(envelope_path: Path) -> dict:
    envelope_path = Path(envelope_path)
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    payload_path = envelope_path.with_name(str(envelope["payload_path"]))
    payload_blob = payload_path.read_bytes()
    actual = hashlib.sha256(payload_blob).hexdigest()
    expected = envelope["snapshot_payload_hash"]
    if actual != expected:
        raise TypographySnapshotIntegrityError(
            f"payload hash {actual} does not match envelope hash {expected}"
        )
    lifecycle = envelope.get("lifecycle", {})
    actual_lifecycle = lifecycle_hash(lifecycle)
    if actual_lifecycle != envelope["lifecycle_registry_hash"]:
        raise TypographySnapshotIntegrityError(
            "lifecycle registry hash does not match envelope lifecycle"
        )
    loaded = dict(envelope)
    loaded["payload"] = json.loads(payload_blob.decode("utf-8"))
    return loaded


def assert_admissible(envelope: dict) -> None:
    # S2 admits only an `approved` snapshot, and an approved snapshot must carry a
    # complete, hash-consistent lifecycle -- an "approved" state with no approver
    # or a tampered lifecycle registry is not a real approval (Codex review
    # finding 7). The payload-hash check stays in load_typography_snapshot.
    lifecycle = envelope.get("lifecycle", {})
    approval_state = lifecycle.get("approval_state")
    if approval_state != "approved":
        raise TypographySnapshotIntegrityError(
            f"typography snapshot is not approved: {approval_state}"
        )
    if not lifecycle.get("approved_at") or not lifecycle.get("approver_id"):
        raise TypographySnapshotIntegrityError(
            "approved typography snapshot is missing approved_at / approver_id"
        )
    registry_hash = envelope.get("lifecycle_registry_hash")
    if registry_hash is not None and registry_hash != lifecycle_hash(lifecycle):
        raise TypographySnapshotIntegrityError(
            "lifecycle registry hash does not match envelope lifecycle"
        )


__all__ = [
    "TypographySnapshotIntegrityError",
    "payload_hash",
    "lifecycle_hash",
    "build_typography_payload",
    "build_typography_envelope",
    "write_typography_snapshot",
    "load_typography_snapshot",
    "assert_admissible",
]
