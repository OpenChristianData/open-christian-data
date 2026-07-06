from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


WORK_HANDLE = "reference/test-work/2000"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _record() -> dict:
    return {
        "meta": {
            "id": "fixture-record",
            "title": "Fixture Work",
            "author_slug": "fixture-author",
            "author_display_name": "Fixture Author",
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 2000,
            "language": "en",
            "tradition": ["ecumenical"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": "2000",
            "pd_anchor": "anchor",
            "modernisation_ruleset_version": None,
            "attestation_summary": {
                "block_count": 1,
                "fully_attested_blocks": 1,
                "blocks_with_disagreements": 0,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": [
            {
                "block_id": "b_0001",
                "block_id_history": [],
                "block_type": "paragraph",
                "language": "en",
                "language_confidence": 1.0,
                "language_alternates": [],
                "language_segments": [],
                "original_text": "Anchor text.",
                "modern_text": "Anchor text.",
                "annotations": {},
                "source_pages": [{"rendering_id": "anchor", "page_number": 1}],
                "attested_by": ["anchor"],
                "disagreements": [],
                "structural_disagreements": [],
                "modernisations": [],
            }
        ],
        "match_explanations": [],
    }


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_pending_dry_run_emits_report_without_attestation_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir = tmp_path / "data/reference/test-work/2000"
    _write_json(
        work_dir / "catalog.json",
        {
            "work_id": "reference/test-work",
            "edition": "2000",
            "modernisation_intent": "not_applicable",
            "pd_anchor_decision": {
                "chosen_rendering": "anchor",
                "rationale": "Fixture anchor.",
                "decided_at": "2026-05-18T00:00:00+00:00",
                "alternates_considered": [],
            },
            "renderings": [
                {"rendering_id": "anchor", "role": "pd_anchor", "format": "plain", "license": "public-domain"},
                {
                    "rendering_id": "pending-ocr",
                    "role": "pending",
                    "format": "ocr",
                    "license": "public-domain",
                    "engine": "tesseract@5.3.0",
                },
            ],
        },
    )
    record_path = work_dir / "original/part-1.json"
    _write_json(record_path, _record())
    audit_path = tmp_path / "review/audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(json.dumps({"event": "initial"}) + "\n", encoding="utf-8")
    before_hash = _hash(record_path)
    before_audit_lines = audit_path.read_text(encoding="utf-8").splitlines()
    before_attestors = json.loads(record_path.read_text(encoding="utf-8"))["blocks"][0]["attested_by"]
    monkeypatch.chdir(tmp_path)

    from build.tools.reconcile import main

    result = main([WORK_HANDLE, "--dry-run"])
    assert result in (0, None)
    reports = list((work_dir / "dry-runs").glob("pending-ocr_*.json"))
    assert len(reports) == 1
    assert _hash(record_path) == before_hash
    assert audit_path.read_text(encoding="utf-8").splitlines() == before_audit_lines
    assert json.loads(record_path.read_text(encoding="utf-8"))["blocks"][0]["attested_by"] == before_attestors
