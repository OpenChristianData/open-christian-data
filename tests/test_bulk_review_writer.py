"""Tests for build/tools/bulk_review_writer.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.lib.atomic_io import AtomicWriteError
from build.tools import bulk_review_writer as brw


@pytest.fixture
def record(tmp_path: Path) -> Path:
    data_path = tmp_path / "data" / "reference" / "test.json"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(
        json.dumps(
            {
                "meta": {"id": "test", "schema_type": "reference_entry"},
                "data": [{"entry_id": "test.e1", "term": "X"}],
            }
        ),
        encoding="utf-8",
    )
    return data_path


def _warnings_fixture() -> list[dict]:
    return [
        {
            "producer": "ocr_scanner",
            "code": "digit_in_letter",
            "signature": "ocr_scanner.digit_in_letter.aa1",
            "entry_id": "test.e1",
            "field_path": "term",
        },
        {
            "producer": "ocr_scanner",
            "code": "digit_in_letter",
            "signature": "ocr_scanner.digit_in_letter.bb2",
            "entry_id": "test.e1",
            "field_path": "term",
        },
        {
            "producer": "text_suspicion",
            "code": "possible_broken_hyphenation",
            "signature": "text_suspicion.broken.cc3",
            "entry_id": "test.e1",
            "field_path": "term",
        },
    ]


def test_dry_run_returns_preview_does_not_write(record, tmp_path, monkeypatch):
    monkeypatch.setattr(brw, "REPO_ROOT", tmp_path)
    result = brw._bulk_apply(
        record_path=record,
        by_code="digit_in_letter",
        by_producer=None,
        by_query=None,
        reason="wont_fix",
        note=None,
        confirm=False,
        action="dismiss",
        warnings=_warnings_fixture(),
    )
    assert result["matched"] == 2
    assert result["dry_run"] is True
    assert result["written"] is False
    sidecar = tmp_path / "review" / "state" / "reference" / "test.json"
    assert not sidecar.exists()


def test_confirm_writes_sidecar_dismissals(record, tmp_path, monkeypatch):
    monkeypatch.setattr(brw, "REPO_ROOT", tmp_path)
    result = brw._bulk_apply(
        record_path=record,
        by_code="digit_in_letter",
        by_producer=None,
        by_query=None,
        reason="wont_fix",
        note=None,
        confirm=True,
        action="dismiss",
        warnings=_warnings_fixture(),
    )
    assert result["matched"] == 2
    assert result["written"] is True
    sidecar_path = tmp_path / "review" / "state" / "reference" / "test.json"
    assert sidecar_path.exists()
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    dismissed = sidecar["entries"]["test.e1"]["warnings_dismissed"]
    assert len(dismissed) == 2
    assert all(d["reason"] == "wont_fix" for d in dismissed)


def test_acknowledge_uses_warnings_acknowledged(record, tmp_path, monkeypatch):
    monkeypatch.setattr(brw, "REPO_ROOT", tmp_path)
    result = brw._bulk_apply(
        record_path=record,
        by_code=None,
        by_producer="ocr_scanner",
        by_query=None,
        reason="confirmed",
        note=None,
        confirm=True,
        action="acknowledge",
        warnings=_warnings_fixture(),
    )
    sidecar = json.loads((tmp_path / "review" / "state" / "reference" / "test.json").read_text(encoding="utf-8"))
    ack = sidecar["entries"]["test.e1"]["warnings_acknowledged"]
    assert len(ack) == 2
    assert all(a["reason"] == "confirmed" for a in ack)
    audit_path = tmp_path / "review" / "audit.jsonl"
    events = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    bulk_events = [e for e in events if e.get("event_type") == "bulk_acknowledged"]
    assert len(bulk_events) == 1
    assert bulk_events[0]["counts"]["affected"] == 2


def test_audit_event_emitted_once_per_batch(record, tmp_path, monkeypatch):
    monkeypatch.setattr(brw, "REPO_ROOT", tmp_path)
    brw._bulk_apply(
        record_path=record,
        by_code="digit_in_letter",
        by_producer=None,
        by_query=None,
        reason="wont_fix",
        note=None,
        confirm=True,
        action="dismiss",
        warnings=_warnings_fixture(),
    )
    audit_path = tmp_path / "review" / "audit.jsonl"
    assert audit_path.exists()
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    bulk_events = [e for e in events if e.get("event_type") == "bulk_dismissed"]
    assert len(bulk_events) == 1
    assert bulk_events[0]["counts"]["affected"] == 2


def test_no_match_returns_zero_no_write(record, tmp_path, monkeypatch):
    monkeypatch.setattr(brw, "REPO_ROOT", tmp_path)
    result = brw._bulk_apply(
        record_path=record,
        by_code="missing_code_xyz",
        by_producer=None,
        by_query=None,
        reason="wont_fix",
        note=None,
        confirm=True,
        action="dismiss",
        warnings=_warnings_fixture(),
    )
    assert result["matched"] == 0
    assert result["written"] is False


def test_cli_rejects_invalid_reason(record):
    with pytest.raises(SystemExit):
        brw.main(
            [
                "dismiss",
                "--resource",
                str(record),
                "--by-code",
                "digit_in_letter",
                "--reason",
                "invalid_reason",
            ]
        )


def test_audit_append_fallback_only_swallows_atomic_write_error(
    record, tmp_path, monkeypatch
):
    """A-F13-tail: AtomicWriteError triggers the fallback append; any other
    exception (e.g. PermissionError) propagates instead of being swallowed."""
    monkeypatch.setattr(brw, "REPO_ROOT", tmp_path)

    def raise_atomic(*args, **kwargs):
        raise AtomicWriteError("simulated atomic failure")

    monkeypatch.setattr(brw, "append_jsonl_atomic", raise_atomic)

    brw._append_audit_event(
        record_path=record,
        resource_id="test",
        event_type="bulk_dismissed",
        affected=[{"signature": "x"}],
        reason="wont_fix",
    )

    audit_path = tmp_path / "review" / "audit.jsonl"
    assert audit_path.exists()
    events = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(events) == 1
    assert events[0]["event_type"] == "bulk_dismissed"
    assert events[0]["decision_reason"] == "wont_fix"

    def raise_permission(*args, **kwargs):
        raise PermissionError("simulated permission denial")

    monkeypatch.setattr(brw, "append_jsonl_atomic", raise_permission)

    with pytest.raises(PermissionError):
        brw._append_audit_event(
            record_path=record,
            resource_id="test",
            event_type="bulk_dismissed",
            affected=[{"signature": "y"}],
            reason="wont_fix",
        )
