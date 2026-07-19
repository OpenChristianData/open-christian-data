from __future__ import annotations

import json
from pathlib import Path

import pytest


WORK_HANDLE = "reference/test-work/2000"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _catalog(anchor: str = "rendering-a") -> dict:
    return {
        "work_id": "reference/test-work",
        "edition": "2000",
        "modernisation_intent": "not_applicable",
        "pd_anchor_decision": {
            "chosen_rendering": anchor,
            "rationale": "Fixture anchor.",
            "decided_at": "2026-05-18T00:00:00+00:00",
            "alternates_considered": [],
        },
        "renderings": [
            {"rendering_id": "rendering-a", "role": "pd_anchor", "format": "plain", "license": "public-domain"},
            {"rendering_id": "rendering-b", "role": "pd_attestor", "format": "plain", "license": "public-domain"},
        ],
    }


def _record(record_id: str, anchor: str = "rendering-a") -> dict:
    return {
        "meta": {
            "id": record_id,
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
            "pd_anchor": anchor,
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
                "original_text": "Fixture text.",
                "modern_text": "Fixture text.",
                "annotations": {},
                "source_pages": [{"rendering_id": anchor, "page_number": 1}],
                "attested_by": [anchor, "rendering-b"],
                "disagreements": [],
                "structural_disagreements": [],
                "modernisations": [],
            }
        ],
        "match_explanations": [],
    }


def _stage_reconcile_inputs(tmp_path: Path) -> Path:
    work_dir = tmp_path / "data/reference/test-work/2000"
    _write_json(work_dir / "catalog.json", _catalog())
    for rendering_id in ("rendering-a", "rendering-b"):
        _write_json(
            work_dir / "parses" / f"{rendering_id}.json",
            {
                "rendering_id": rendering_id,
                "blocks": [{"block_id": "b_0001", "text": "Fixture text.", "page": 1}],
            },
        )
    return work_dir


def test_reconcile_cli_runs_against_work_handle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = _stage_reconcile_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    from build.tools.reconcile import main

    result = main([WORK_HANDLE])
    assert result in (0, None)
    assert (work_dir / "original").glob("*.json")
    audit_path = tmp_path / "review/audit.jsonl"
    assert audit_path.exists()
    assert audit_path.read_text(encoding="utf-8").strip().splitlines()


def test_reconcile_anchor_swap_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "data/reference/test-work/2000"
    _write_json(work_dir / "catalog.json", _catalog())
    for index in range(3):
        _write_json(work_dir / "original" / f"part-{index}.json", _record(f"part-{index}"))

    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in sorted([work_dir / "catalog.json", *list((work_dir / "original").glob("*.json"))])
    }
    monkeypatch.chdir(tmp_path)

    from build.tools.reconcile import main

    result = main(["anchor-swap", WORK_HANDLE, "--new-anchor", "rendering-b"])
    assert result in (0, None)
    catalog = json.loads((work_dir / "catalog.json").read_text(encoding="utf-8"))
    assert catalog["pd_anchor_decision"]["chosen_rendering"] == "rendering-b"
    for record_path in sorted((work_dir / "original").glob("*.json")):
        assert json.loads(record_path.read_text(encoding="utf-8"))["meta"]["pd_anchor"] == "rendering-b"

    _write_json(work_dir / "catalog.json", _catalog())
    for index in range(3):
        _write_json(work_dir / "original" / f"part-{index}.json", _record(f"part-{index}"))

    from ocd_kernel.lib import atomic_io

    calls = {"count": 0}
    real_write = atomic_io.write_json_atomic

    def fail_on_third_write(path: Path, payload: dict, schema: dict, **kwargs: object) -> None:
        calls["count"] += 1
        if calls["count"] == 3:
            raise atomic_io.AtomicWriteError("forced anchor-swap failure")
        real_write(path, payload, schema, **kwargs)

    monkeypatch.setattr(atomic_io, "write_json_atomic", fail_on_third_write)
    with pytest.raises(atomic_io.AtomicWriteError):
        main(["anchor-swap", WORK_HANDLE, "--new-anchor", "rendering-b"])

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in sorted([work_dir / "catalog.json", *list((work_dir / "original").glob("*.json"))])
    }
    assert after == before
    audit_path = tmp_path / "review/audit.jsonl"
    assert not audit_path.exists() or "anchor_swap" not in audit_path.read_text(encoding="utf-8")
