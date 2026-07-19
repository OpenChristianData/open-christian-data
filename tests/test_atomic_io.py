"""Tests for ocd_kernel.lib.atomic_io.

Covers: JSON atomic writes, JSONL appends with line-schema validation, lock
acquire contention, stale-lock break with same-host PID liveness, and the
cross-host stale-lock manual-intervention requirement.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ocd_kernel.lib import atomic_io


SIMPLE_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["name", "value"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "value": {"type": "integer", "minimum": 0},
    },
}


def test_write_json_atomic_round_trip(tmp_path: Path):
    target = tmp_path / "out.json"
    atomic_io.write_json_atomic(target, {"name": "a", "value": 1}, SIMPLE_JSON_SCHEMA)
    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "a", "value": 1}


def test_write_json_atomic_schema_failure_keeps_existing_file(tmp_path: Path):
    target = tmp_path / "out.json"
    atomic_io.write_json_atomic(target, {"name": "ok", "value": 1}, SIMPLE_JSON_SCHEMA)
    original_bytes = target.read_bytes()

    with pytest.raises(atomic_io.SchemaValidationError):
        atomic_io.write_json_atomic(
            target,
            {"name": "bad", "value": -1},  # violates minimum: 0
            SIMPLE_JSON_SCHEMA,
        )
    # On-disk file unchanged.
    assert target.read_bytes() == original_bytes


def test_write_json_atomic_failure_leaves_no_tempfile(tmp_path: Path):
    target = tmp_path / "out.json"
    with pytest.raises(atomic_io.SchemaValidationError):
        atomic_io.write_json_atomic(
            target,
            {"name": "x"},  # missing required value
            SIMPLE_JSON_SCHEMA,
        )
    # No temp-file leftovers.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("out.json.tmp-")]
    assert leftovers == []
    # Target was never created.
    assert not target.exists()


def _sync_lock_error() -> OSError:
    """Build an OSError that looks like a cloud-sync client lock (WinError 5 / EACCES)."""
    import sys

    exc = OSError("Access is denied")
    if sys.platform == "win32":
        exc.winerror = 5
    else:
        import errno
        exc.errno = errno.EACCES
    return exc


def test_write_json_atomic_retries_on_sync_lock_then_succeeds(tmp_path: Path, monkeypatch):
    """write_json_atomic retries os.replace on transient sync-lock errors."""
    from unittest.mock import patch

    target = tmp_path / "out.json"
    real_replace = os.replace
    call_count = {"n": 0}

    def flaky_replace(src, dst):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _sync_lock_error()
        real_replace(src, dst)

    with patch("ocd_kernel.lib.atomic_io.os.replace", side_effect=flaky_replace):
        with patch("ocd_kernel.lib.atomic_io.time.sleep"):  # don't actually wait
            atomic_io.write_json_atomic(target, {"name": "a", "value": 1}, SIMPLE_JSON_SCHEMA)

    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "a", "value": 1}
    assert call_count["n"] == 3  # two failures then success


def test_write_json_atomic_raises_and_cleans_up_after_max_retries(tmp_path: Path):
    """write_json_atomic raises OSError and removes the temp file after retries exhausted."""
    from unittest.mock import patch

    target = tmp_path / "out.json"

    def always_fail(src, dst):
        raise _sync_lock_error()

    with patch("ocd_kernel.lib.atomic_io.os.replace", side_effect=always_fail):
        with patch("ocd_kernel.lib.atomic_io.time.sleep"):
            with pytest.raises(OSError):
                atomic_io.write_json_atomic(target, {"name": "a", "value": 1}, SIMPLE_JSON_SCHEMA)

    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("out.json.tmp-")]
    assert leftovers == []


LINE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["event"],
    "additionalProperties": False,
    "properties": {
        "event": {"type": "string"},
        "n": {"type": "integer"},
    },
}


def test_append_jsonl_atomic_appends_and_validates(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    atomic_io.append_jsonl_atomic(target, {"event": "a", "n": 1}, LINE_SCHEMA)
    atomic_io.append_jsonl_atomic(target, {"event": "b", "n": 2}, LINE_SCHEMA)
    lines = target.read_text(encoding="utf-8").splitlines()
    assert [json.loads(l) for l in lines] == [
        {"event": "a", "n": 1},
        {"event": "b", "n": 2},
    ]


def test_append_jsonl_atomic_invalid_line_no_io(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    with pytest.raises(atomic_io.SchemaValidationError):
        atomic_io.append_jsonl_atomic(target, {"event": 1}, LINE_SCHEMA)  # event must be string
    assert not target.exists()


def test_append_jsonl_atomic_lock_contention(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    # Pre-create a stale-free lock so the second acquire must wait.
    lock_path = target.with_name(target.name + ".lock")
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "hostname": socket.gethostname(),
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
                "target_path": str(target),
            }
        ),
        encoding="utf-8",
    )

    started = threading.Event()
    finished = threading.Event()
    captured: dict = {}

    def worker():
        try:
            started.set()
            atomic_io.append_jsonl_atomic(
                target,
                {"event": "late"},
                LINE_SCHEMA,
                acquire_timeout=0.5,
                stale_threshold=3600.0,
            )
        except atomic_io.LockAcquireTimeout as exc:
            captured["err"] = exc
        finished.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    started.wait(timeout=1.0)
    finished.wait(timeout=2.0)
    assert finished.is_set()
    assert "err" in captured
    # Release the lock so tmp_path cleanup doesn't complain.
    lock_path.unlink()  # standards: log/temp rotation


def test_append_jsonl_atomic_breaks_stale_local_lock(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    # A definitely-dead PID. Pick a pid that's almost certainly free; the
    # liveness check tolerates uncertainty, so we use 0 (returns False on POSIX
    # and Windows) to guarantee the breaker path runs.
    stale_created = (datetime.now(tz=timezone.utc) - timedelta(seconds=600)).isoformat()
    lock_path.write_text(
        json.dumps(
            {
                "pid": 0,
                "hostname": socket.gethostname(),
                "created_at": stale_created,
                "target_path": str(target),
            }
        ),
        encoding="utf-8",
    )
    breaks: list = []

    def on_break(meta):
        breaks.append(meta)

    atomic_io.append_jsonl_atomic(
        target,
        {"event": "post-break"},
        LINE_SCHEMA,
        acquire_timeout=1.0,
        stale_threshold=1.0,
        on_stale_break=on_break,
    )
    assert breaks and breaks[0].pid == 0
    lines = target.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[-1]) == {"event": "post-break"}


def test_append_jsonl_atomic_cross_host_stale_requires_manual(tmp_path: Path):
    target = tmp_path / "events.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    stale_created = (datetime.now(tz=timezone.utc) - timedelta(seconds=600)).isoformat()
    lock_path.write_text(
        json.dumps(
            {
                "pid": 0,
                "hostname": "some-other-host.example",
                "created_at": stale_created,
                "target_path": str(target),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(atomic_io.LockBrokenError):
        atomic_io.append_jsonl_atomic(
            target,
            {"event": "x"},
            LINE_SCHEMA,
            acquire_timeout=0.5,
            stale_threshold=1.0,
        )
    # Lock left in place for manual intervention.
    assert lock_path.exists()
    lock_path.unlink()  # standards: log/temp rotation
