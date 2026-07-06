"""Phase G: applier exercises approved text corrections.

Tests use a tmp copy of a synthetic commentary record so the suite is
hermetic. The end-to-end "two pilots" check runs against in-memory copies of
the real pilot records to verify the applier mutates layers.display without
touching structured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.tools import apply_correction as ac


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def commentary_record(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "commentaries" / "test" / "1-john.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "meta": {
            "id": "1-john",
            "schema_type": "commentary",
            "text_layer_shape": "single_field",
        },
        "data": [
            {
                "entry_id": "test.1John.1.1",
                "commentary_text": "We shew the testimony.",
                "layers": {
                    "commentary_text": {
                        "source_raw": "We shew the testimony.",
                        "normalised": "We shew the testimony.",
                        "structured": "We shew the testimony.",
                        "display": "We shew the testimony.",
                        "source_raw_origin": "observed",
                    }
                },
            }
        ],
    }
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "review" / "corrections" / "commentaries" / "test" / "1-john.jsonl"


def _seed_ledger(ledger_path: Path, correction: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(correction) + "\n")


@pytest.fixture
def approved_text_correction() -> dict:
    return {
        "schema_version": "1.0.0",
        "correction_id": "correction_test001",
        "resource_id": "1-john",
        "record_path": "data/commentaries/test/1-john.json",
        "entry_id": "test.1John.1.1",
        "field_path": "commentary_text",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "shew",
        "after_text": "show",
        "status": "approved",
        "created_at": "2026-05-13T00:00:00+00:00",
        "approved_at": "2026-05-13T00:01:00+00:00",
        "approved_by": "test-reviewer",
        "proposed_by": "test-reviewer",
    }


def test_applier_mutates_display_not_structured(
    commentary_record, ledger_path, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    _seed_ledger(ledger_path, approved_text_correction)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    applied = ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=commentary_record,
        writer_manifest_out=manifest_out,
    )

    assert len(applied) == 1
    record = json.loads(commentary_record.read_text(encoding="utf-8"))
    layer = record["data"][0]["layers"]["commentary_text"]
    assert layer["structured"] == "We shew the testimony."
    # display is the structured text with the targeted span replaced
    assert layer["display"] == "We show the testimony."
    assert layer["structured"] != layer["display"]
    # Surface field mirrors display
    assert record["data"][0]["commentary_text"] == layer["display"]


def test_applier_writes_writer_manifest_with_correct_checksums(
    commentary_record, ledger_path, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    _seed_ledger(ledger_path, approved_text_correction)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=commentary_record,
        writer_manifest_out=manifest_out,
    )

    assert manifest_out.exists()
    manifest = json.loads(manifest_out.read_text(encoding="utf-8"))
    assert manifest["writer_identity"] == "correction_applier"
    assert "before_sha256" in next(iter(manifest["checksums"].values()))
    assert "after_sha256" in next(iter(manifest["checksums"].values()))


def test_applier_promotes_ledger_entry_to_applied(
    commentary_record, ledger_path, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    _seed_ledger(ledger_path, approved_text_correction)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=commentary_record,
        writer_manifest_out=manifest_out,
    )

    ledger = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert ledger[0]["status"] == "applied"
    assert ledger[0]["applied_at"]
    assert ledger[0]["applier_run_id"]


def test_applier_emits_audit_event(
    commentary_record, ledger_path, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    _seed_ledger(ledger_path, approved_text_correction)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=commentary_record,
        writer_manifest_out=manifest_out,
    )

    audit_path = tmp_path / "review" / "audit.jsonl"
    assert audit_path.exists()
    events = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    correction_applied = [e for e in events if e.get("event_type") == "correction_applied"]
    assert len(correction_applied) == 1
    assert correction_applied[0]["correction_id"] == "correction_test001"
    assert "correction_id=" not in correction_applied[0]["note"]
    assert correction_applied[0]["field_path"] == "commentary_text"


def test_applier_rejects_structural_correction_type(
    commentary_record, ledger_path, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    structural = {**approved_text_correction, "correction_type": "structural", "correction_id": "correction_structural001"}
    _seed_ledger(ledger_path, structural)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    applied = ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=commentary_record,
        writer_manifest_out=manifest_out,
    )

    # Structural is deferred, not applied
    assert applied == []

    # The structural entry stays in approved, with applier_deferred_reason set
    # (in-memory deferral; we don't rewrite the ledger if no applied changes).


def test_structural_correction_exception_does_not_mutate_input(
    commentary_record, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    structural = {
        **approved_text_correction,
        "correction_type": "structural",
        "correction_id": "correction_structural002",
    }
    original_keys = set(structural)

    with pytest.raises(ac.StructuralCorrectionDeferred) as exc_info:
        ac.apply_correction(
            resource_record_path=commentary_record,
            correction=structural,
            writer_manifest_out=tmp_path / "review" / "writer-manifests" / "apply_run.json",
            run_id="test-run",
        )

    assert exc_info.value.applier_deferred_reason == "structural_deferred"
    assert set(structural) == original_keys
    assert "applier_deferred_reason" not in structural


def test_dry_run_does_not_mutate_data_or_ledger(
    commentary_record, ledger_path, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    _seed_ledger(ledger_path, approved_text_correction)
    record_before = commentary_record.read_bytes()
    ledger_before = ledger_path.read_text(encoding="utf-8")

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    applied = ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=commentary_record,
        writer_manifest_out=manifest_out,
        dry_run=True,
    )

    assert len(applied) == 1
    assert applied[0]["status"] == "would_apply"
    assert applied[0]["applied_at"]
    assert applied[0]["applier_run_id"]
    assert commentary_record.read_bytes() == record_before
    assert ledger_path.read_text(encoding="utf-8") == ledger_before


def test_applier_rejects_ambiguous_before_text_match(
    commentary_record, approved_text_correction, tmp_path, monkeypatch
):
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    record = json.loads(commentary_record.read_text(encoding="utf-8"))
    entry = record["data"][0]
    entry["commentary_text"] = "We shew and shew the testimony."
    entry["layers"]["commentary_text"]["display"] = "We shew and shew the testimony."
    commentary_record.write_text(json.dumps(record, indent=2), encoding="utf-8")
    correction = {
        **approved_text_correction,
        "correction_id": "correction_ambiguous001",
    }

    with pytest.raises(ac.ApplierError) as exc_info:
        ac.apply_correction(
            resource_record_path=commentary_record,
            correction=correction,
            writer_manifest_out=tmp_path / "review" / "writer-manifests" / "apply_run.json",
            run_id="test-run",
        )

    assert exc_info.value.code == "ambiguous_before_text_match"
    assert "commentary_text" in str(exc_info.value)
    assert "'shew'" in str(exc_info.value)


def test_applier_mirrors_nested_definition_block_display_back_to_surface(
    tmp_path, monkeypatch
):
    """B-F2: nested corrections must mirror the layer display back to the
    surface array entry so the Phase C surface-field invariant holds."""
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    record_path = tmp_path / "data" / "reference" / "tst.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "meta": {
            "id": "tst",
            "schema_type": "reference_entry",
            "text_layer_shape": "multi_field",
        },
        "data": [
            {
                "entry_id": "tst.term",
                "term": "Term",
                "alt_terms": [],
                "definition_blocks": ["original TH0 text"],
                "layers": {
                    "definition_blocks": {
                        "b8f3a1c2": {
                            "source_raw": "original TH0 text",
                            "normalised": "original TH0 text",
                            "structured": "original TH0 text",
                            "display": "original TH0 text",
                            "source_raw_origin": "observed",
                        }
                    }
                },
            }
        ],
    }
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    ledger_path = tmp_path / "review" / "corrections" / "reference" / "tst.jsonl"
    correction = {
        "schema_version": "1.0.0",
        "correction_id": "correction_nested001",
        "resource_id": "tst",
        "record_path": "data/reference/tst.json",
        "entry_id": "tst.term",
        "field_path": "definition_blocks.b8f3a1c2",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "TH0",
        "after_text": "THE",
        "status": "approved",
        "created_at": "2026-05-13T00:00:00+00:00",
        "approved_at": "2026-05-13T00:01:00+00:00",
        "approved_by": "test-reviewer",
        "proposed_by": "test-reviewer",
    }
    _seed_ledger(ledger_path, correction)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    applied = ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=record_path,
        writer_manifest_out=manifest_out,
    )

    assert len(applied) == 1
    updated = json.loads(record_path.read_text(encoding="utf-8"))
    entry = updated["data"][0]
    layer = entry["layers"]["definition_blocks"]["b8f3a1c2"]
    assert layer["display"] == "original THE text"
    # Surface array entry must mirror the display.
    assert entry["definition_blocks"][0] == "original THE text"


def test_applier_mirrors_nested_alt_term_display_back_to_surface(
    tmp_path, monkeypatch
):
    """B-F2: alt_terms.<idx> updates the indexed surface array entry."""
    monkeypatch.setattr(ac, "REPO_ROOT", tmp_path)
    record_path = tmp_path / "data" / "reference" / "tst.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "meta": {
            "id": "tst",
            "schema_type": "reference_entry",
            "text_layer_shape": "multi_field",
        },
        "data": [
            {
                "entry_id": "tst.term",
                "term": "Term",
                "alt_terms": ["wrong_alt"],
                "definition_blocks": [],
                "layers": {
                    "alt_terms": {
                        "0": {
                            "source_raw": "wrong_alt",
                            "normalised": "wrong_alt",
                            "structured": "wrong_alt",
                            "display": "wrong_alt",
                            "source_raw_origin": "observed",
                        }
                    }
                },
            }
        ],
    }
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    ledger_path = tmp_path / "review" / "corrections" / "reference" / "tst.jsonl"
    correction = {
        "schema_version": "1.0.0",
        "correction_id": "correction_alt001",
        "resource_id": "tst",
        "record_path": "data/reference/tst.json",
        "entry_id": "tst.term",
        "field_path": "alt_terms.0",
        "correction_type": "text",
        "blocker": "none",
        "before_text": "wrong_alt",
        "after_text": "right_alt",
        "status": "approved",
        "created_at": "2026-05-13T00:00:00+00:00",
        "approved_at": "2026-05-13T00:01:00+00:00",
        "approved_by": "test-reviewer",
        "proposed_by": "test-reviewer",
    }
    _seed_ledger(ledger_path, correction)

    manifest_out = tmp_path / "review" / "writer-manifests" / "apply_run.json"
    applied = ac.apply_pending_corrections(
        ledger_path=ledger_path,
        resource_record_path=record_path,
        writer_manifest_out=manifest_out,
    )

    assert len(applied) == 1
    updated = json.loads(record_path.read_text(encoding="utf-8"))
    entry = updated["data"][0]
    assert entry["layers"]["alt_terms"]["0"]["display"] == "right_alt"
    assert entry["alt_terms"][0] == "right_alt"
