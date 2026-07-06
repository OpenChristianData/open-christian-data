from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from build.lib.review_state import derive_sidecar_path, empty_sidecar


RECORD_REL = Path("data/reference/test-work/2000/original.json")
CATALOG_REL = Path("data/reference/test-work/2000/catalog.json")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _build_fixture_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    record_path = tmp_path / RECORD_REL
    catalog_path = tmp_path / CATALOG_REL
    sidecar_path = derive_sidecar_path(record_path, repo_root=tmp_path)

    _write_json(
        record_path,
        {
            "meta": {
                "id": "test-work-2000-original",
                "schema_type": "reconciled_record",
                "schema_version": "3.0.0",
                "pd_anchor": "test-rendering",
            },
            "blocks": [
                {
                    "block_id": "b_test_0001",
                    "original_text": "State X.",
                    "disagreements": [{"chosen_reading": "State X."}],
                }
            ],
            "match_explanations": [],
        },
    )
    _write_json(
        catalog_path,
        {
            "work_id": "reference/test-work",
            "edition": "2000",
            "modernisation_intent": "not_applicable",
            "pd_anchor_decision": {
                "chosen_rendering": "test-rendering",
                "rationale": "Initial anchor.",
                "decided_at": "2026-05-18T00:00:00+00:00",
                "alternates_considered": [],
            },
            "renderings": [{"rendering_id": "test-rendering", "role": "pd_anchor"}],
        },
    )
    _write_json(
        sidecar_path,
        empty_sidecar(
            record_path=RECORD_REL.as_posix(),
            record_resource_id="test-work-2000-original",
            record_checksum_sha256=hashlib.sha256(record_path.read_bytes()).hexdigest(),
            parser_version_seen="build/parsers/test.py@1.0.0",
        ),
    )
    return record_path, sidecar_path, catalog_path


def _valid_patch(tmp_path: Path, record_path: Path, sidecar_path: Path, catalog_path: Path) -> dict:
    return {
        "schema_type": "review_patch",
        "schema_version": "3.0.0",
        "tool_version": "test",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_hashes": {
            RECORD_REL.as_posix(): _sha256(record_path),
            sidecar_path.relative_to(tmp_path).as_posix(): _sha256(sidecar_path),
            CATALOG_REL.as_posix(): _sha256(catalog_path),
        },
        "decisions": [
            {
                "decision_kind": "adjudication",
                "record_path": RECORD_REL.as_posix(),
                "workbench_path": sidecar_path.relative_to(tmp_path).as_posix(),
                "block_id": "b_test_0001",
                "disagreement_index": 0,
                "chosen_reading": "State X accepted.",
                "rationale": "Reviewer accepted state X before drift.",
                "decided_at": "2026-05-18T00:00:00+00:00",
            }
        ],
    }


def test_content_hash_drift_detection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record_path, sidecar_path, catalog_path = _build_fixture_tree(tmp_path)
    patch = _valid_patch(tmp_path, record_path, sidecar_path, catalog_path)
    patch_path = tmp_path / "review-patch.json"
    _write_json(patch_path, patch)

    drifted_record = json.loads(record_path.read_text(encoding="utf-8"))
    drifted_record["blocks"][0]["original_text"] = "State Y."
    _write_json(record_path, drifted_record)

    monkeypatch.chdir(tmp_path)
    import build.tools.apply_review_patch as apply_review_patch

    mismatch_error = getattr(apply_review_patch, "ContentHashMismatch", SystemExit)
    with pytest.raises((SystemExit, mismatch_error)) as excinfo:
        apply_review_patch.main([str(patch_path)])

    if isinstance(excinfo.value, SystemExit):
        assert excinfo.value.code not in (0, None)
    assert RECORD_REL.as_posix() in str(excinfo.value)
    assert not (tmp_path / "review/audit.jsonl").exists()
