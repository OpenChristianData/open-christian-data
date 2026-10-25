from __future__ import annotations

import json
from pathlib import Path

from cvw_app.session_observability import (
    EVENT_CONTRACT,
    SESSION_CONTRACT,
    SessionRecorder,
    make_session_descriptor,
)


def test_session_descriptor_contains_bounded_runtime_identity() -> None:
    descriptor = make_session_descriptor(
        session_id="session-one",
        host="127.0.0.1",
        requested_port=0,
        port=43821,
        origin="http://127.0.0.1:43821",
        pid=1234,
        state="ready",
        catalog_sha256="a" * 64,
        candidate_sha256=("b" * 64, "c" * 64),
        implementation_sha256="d" * 64,
    )

    assert descriptor["contract"] == SESSION_CONTRACT
    assert descriptor["session"] == {
        "session_id": "session-one",
        "host": "127.0.0.1",
        "requested_port": 0,
        "port": 43821,
        "origin": "http://127.0.0.1:43821",
        "pid": 1234,
        "state": "ready",
        "catalog_sha256": "a" * 64,
        "candidate_sha256": ["b" * 64, "c" * 64],
        "implementation_sha256": "d" * 64,
    }


def test_session_recorder_writes_events_and_latest_receipt(tmp_path: Path) -> None:
    recorder = SessionRecorder("session-two", tmp_path / "session-output")
    descriptor = make_session_descriptor(
        session_id="session-two",
        host="127.0.0.1",
        requested_port=8766,
        port=8766,
        origin="http://127.0.0.1:8766",
        pid=5678,
        state="ready",
    )

    recorder.emit("session_start", requested_port=8766)
    recorder.emit("ready", port=8766)
    recorder.write_receipt(descriptor)

    assert recorder.event_path is not None
    assert recorder.receipt_path is not None
    events = [json.loads(line) for line in recorder.event_path.read_text(encoding="utf-8").splitlines()]
    receipt = json.loads(recorder.receipt_path.read_text(encoding="utf-8"))

    assert [event["event"] for event in events] == ["session_start", "ready"]
    assert all(event["contract"] == EVENT_CONTRACT for event in events)
    assert all(event["session_id"] == "session-two" for event in events)
    assert receipt == descriptor
    assert recorder.paths() == {
        "event_log": str(recorder.event_path),
        "receipt": str(recorder.receipt_path),
    }
