from __future__ import annotations

import copy
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


def _record() -> dict:
    return {
        "meta": {
            "id": "test-work-2000-original",
            "title": "Test Work",
            "author_slug": "test-author",
            "author_display_name": "Test Author",
            "author_birth_year": None,
            "author_death_year": None,
            "original_publication_year": 2000,
            "language": "en",
            "tradition": ["ecumenical"],
            "license": "public-domain",
            "schema_type": "reconciled_record",
            "schema_version": "3.0.0",
            "edition": "2000",
            "pd_anchor": "test-rendering",
            "modernisation_ruleset_version": None,
            "attestation_summary": {
                "block_count": 1,
                "fully_attested_blocks": 0,
                "blocks_with_disagreements": 1,
                "blocks_with_structural_disagreements": 0,
            },
        },
        "blocks": [
            {
                "block_id": "b_test_0001",
                "block_id_history": [],
                "block_type": "paragraph",
                "language": "en",
                "language_confidence": 1.0,
                "language_alternates": [],
                "language_segments": [],
                "original_text": "Old reading.",
                "modern_text": "Old reading.",
                "annotations": {},
                "source_pages": [{"rendering_id": "test-rendering", "page_number": 1}],
                "attested_by": ["test-rendering"],
                "disagreements": [
                    {
                        "span": {"start_token": 0, "end_token": 2},
                        "kind": "text_variant",
                        "chosen_reading": "Old reading.",
                        "chosen_reading_attested_by": ["test-rendering"],
                        "readings": [
                            {
                                "rendering_id": "test-rendering",
                                "text": "Old reading.",
                            },
                            {
                                "rendering_id": "test-rendering-alt",
                                "text": "Adjudicated reading.",
                            },
                        ],
                    }
                ],
                "structural_disagreements": [],
                "modernisations": [],
            }
        ],
        "match_explanations": [],
    }


def _catalog() -> dict:
    return {
        "work_id": "reference/test-work",
        "edition": "2000",
        "modernisation_intent": "not_applicable",
        "pd_anchor_decision": {
            "chosen_rendering": "test-rendering",
            "rationale": "Initial anchor.",
            "decided_at": "2026-05-18T00:00:00+00:00",
            "alternates_considered": [],
        },
        "renderings": [
            {
                "rendering_id": "test-rendering",
                "role": "pd_anchor",
                "source": "test",
                "format": "plain",
                "license": "public-domain",
                "fetched_at": "2026-05-18",
                "source_hash": "sha256:" + "1" * 64,
                "coverage": {"pages": [1]},
            }
        ],
    }


def _build_fixture_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    record_path = tmp_path / RECORD_REL
    catalog_path = tmp_path / CATALOG_REL
    sidecar_path = derive_sidecar_path(record_path, repo_root=tmp_path)

    _write_json(record_path, _record())
    _write_json(catalog_path, _catalog())
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
                "chosen_reading": "Adjudicated reading.",
                "rationale": "Reviewer selected the alternate rendering.",
                "reviewer_id": "test-reviewer",
                "decided_at": "2026-05-18T00:00:00+00:00",
            },
            {
                "decision_kind": "catalog_role_change",
                "catalog_path": CATALOG_REL.as_posix(),
                "rendering_id": "test-rendering",
                "from_role": "pd_anchor",
                "to_role": "pd_attestor",
                "rationale": "Anchor role changed after review.",
                "reviewer_id": "test-reviewer",
                "decided_at": "2026-05-18T00:00:00+00:00",
            },
        ],
    }


def test_review_patch_round_trip_via_apply_review_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    record_path, sidecar_path, catalog_path = _build_fixture_tree(tmp_path)
    patch = _valid_patch(tmp_path, record_path, sidecar_path, catalog_path)
    patch_path = tmp_path / "review-patch.json"
    _write_json(patch_path, patch)

    monkeypatch.chdir(tmp_path)
    from build.tools.apply_review_patch import main

    result = main([str(patch_path)])
    assert result in (0, None)

    audit_path = tmp_path / "review/audit.jsonl"
    assert audit_path.exists()
    assert audit_path.read_text(encoding="utf-8").strip().splitlines()

    workbench = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert workbench["entries"]["b_test_0001"]["adjudication"]["chosen_reading"] == "Adjudicated reading."

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["renderings"][0]["role"] == "pd_attestor"

    bad_patch = copy.deepcopy(patch)
    bad_patch["decisions"][0]["decision_kind"] = "unknown_decision_kind"
    bad_patch_path = tmp_path / "bad-review-patch.json"
    _write_json(bad_patch_path, bad_patch)
    before_record = record_path.read_bytes()
    before_sidecar = sidecar_path.read_bytes()
    before_catalog = catalog_path.read_bytes()
    before_audit = audit_path.read_bytes()

    with pytest.raises(Exception):
        main([str(bad_patch_path)])

    assert record_path.read_bytes() == before_record
    assert sidecar_path.read_bytes() == before_sidecar
    assert catalog_path.read_bytes() == before_catalog
    assert audit_path.read_bytes() == before_audit
