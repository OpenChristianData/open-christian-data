"""Tests for build/tools/replay_dead_letter.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from build.lib import review_state
from build.lib.atomic_io import AtomicWriteError
from build.tools import replay_dead_letter as rdl


def _write_entries(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _entry(reason: str = "producer_unknown", age_days: int = 0) -> dict:
    received_at = (datetime.now(tz=timezone.utc) - timedelta(days=age_days)).isoformat()
    return {
        "reason": reason,
        "received_at": received_at,
        "raw_warning": {"producer": "old_producer", "code": "old_code", "evidence": {}},
    }


def _read_entries(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_record(tmp_path: Path, resource_id: str = "alpha") -> str:
    record_path = tmp_path / "data" / f"{resource_id}.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps({"meta": {"id": resource_id}}), encoding="utf-8")
    return record_path.relative_to(tmp_path).as_posix()


def _write_sidecar(
    tmp_path: Path,
    *,
    record_path: str,
    resource_id: str = "alpha",
    dead_letter: list[dict] | None = None,
) -> Path:
    sidecar_path = review_state.derive_sidecar_path(record_path, repo_root=tmp_path)
    sidecar = review_state.empty_sidecar(
        record_path=record_path,
        record_resource_id=resource_id,
        record_checksum_sha256="a" * 64,
        parser_version_seen="build/parsers/test.py@v1.0.0",
    )
    if dead_letter is not None:
        sidecar["dead_letter"] = dead_letter
    review_state.save_sidecar(sidecar_path, sidecar)
    return sidecar_path


def test_gc_deletes_entries_older_than_retention(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    _write_entries(spill, [_entry(age_days=200), _entry(age_days=100), _entry(age_days=50)])

    result = rdl.replay(spill_path=spill, mode="gc", retention_days=180, dry_run=False)

    assert result["gc_deleted"] == 1
    assert result["kept"] == 2


def test_reinstate_marks_entries_reinstatable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    _write_entries(spill, [_entry(), _entry()])

    result = rdl.replay(spill_path=spill, mode="reinstate", dry_run=False)

    assert result["reinstated"] == 0
    assert result["marked_reinstatable"] == 2
    body = _read_entries(spill)
    assert all(e.get("replay_status") == "reinstatable" for e in body)
    audit = _read_entries(tmp_path / "review" / "audit.jsonl")
    assert audit[-1]["counts"]["reinstated"] == 0
    assert audit[-1]["counts"]["marked_reinstatable"] == 2


def test_reinstate_moves_entries_into_sidecar_when_present(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    record_path = _write_record(tmp_path)
    sidecar_path = _write_sidecar(tmp_path, record_path=record_path)
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    entry = _entry()
    _write_entries(spill, [entry])

    result = rdl.replay(spill_path=spill, mode="reinstate", dry_run=False)

    assert result["reinstated"] == 1
    assert _read_entries(spill) == []
    sidecar = review_state.load_sidecar(sidecar_path)
    assert sidecar["dead_letter"][-1]["received_at"] == entry["received_at"]
    audit = _read_entries(tmp_path / "review" / "audit.jsonl")
    assert audit[-1]["counts"]["reinstated"] == 1
    assert audit[-1]["counts"]["marked_reinstatable"] == 0


def test_reinstate_falls_back_to_marker_when_sidecar_missing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    _write_record(tmp_path)
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    entry = _entry()
    _write_entries(spill, [entry])

    result = rdl.replay(spill_path=spill, mode="reinstate", dry_run=False)

    assert result["reinstated"] == 0
    assert result["marked_reinstatable"] == 1
    body = _read_entries(spill)
    assert body[0]["received_at"] == entry["received_at"]
    assert body[0]["replay_status"] == "reinstatable"


def test_reinstate_respects_inline_dead_letter_bound(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    record_path = _write_record(tmp_path)
    sidecar_path = _write_sidecar(
        tmp_path,
        record_path=record_path,
        dead_letter=[_entry() for _ in range(100)],
    )
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    entry = _entry()
    _write_entries(spill, [entry])

    result = rdl.replay(spill_path=spill, mode="reinstate", dry_run=False)

    assert result["reinstated"] == 0
    assert result["marked_reinstatable"] == 1
    body = _read_entries(spill)
    assert body[0]["received_at"] == entry["received_at"]
    assert body[0]["replay_status"] == "reinstatable"
    sidecar = review_state.load_sidecar(sidecar_path)
    assert len(sidecar["dead_letter"]) == 100


def test_reclassify_writes_reclassified_at_timestamp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    _write_entries(spill, [_entry()])

    result = rdl.replay(spill_path=spill, mode="reclassify", dry_run=False)

    assert result["reclassified"] == 1
    body = _read_entries(spill)
    assert "reclassified_at" in body[0]


def test_dry_run_does_not_mutate_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    spill = tmp_path / "review" / "dead-letter" / "alpha.jsonl"
    _write_entries(spill, [_entry(age_days=200), _entry()])
    before = spill.read_bytes()

    result = rdl.replay(spill_path=spill, mode="gc", retention_days=180, dry_run=True)

    assert result["gc_deleted"] == 1
    assert spill.read_bytes() == before


def test_audit_append_fallback_only_swallows_atomic_write_error(
    tmp_path: Path, monkeypatch
) -> None:
    """A-F13-tail: AtomicWriteError triggers the fallback append; any other
    exception (e.g. PermissionError) propagates instead of being swallowed."""
    monkeypatch.setattr(rdl, "REPO_ROOT", tmp_path)
    event = rdl._audit_event(
        resource_id="alpha",
        record_path="data/alpha.json",
        event_type="dead_letter_replayed",
        counts={
            "reinstated": 0,
            "marked_reinstatable": 0,
            "reclassified": 0,
            "gc_deleted": 0,
            "kept": 0,
        },
        note="replay_dead_letter mode=reinstate",
    )

    def raise_atomic(*args, **kwargs):
        raise AtomicWriteError("simulated atomic failure")

    monkeypatch.setattr(rdl, "append_jsonl_atomic", raise_atomic)

    rdl._emit_audit(event)

    audit_path = tmp_path / "review" / "audit.jsonl"
    assert audit_path.exists()
    events = _read_entries(audit_path)
    assert len(events) == 1
    assert events[0]["event_type"] == "dead_letter_replayed"
    assert events[0]["resource_id"] == "alpha"

    def raise_permission(*args, **kwargs):
        raise PermissionError("simulated permission denial")

    monkeypatch.setattr(rdl, "append_jsonl_atomic", raise_permission)

    with pytest.raises(PermissionError):
        rdl._emit_audit(event)
