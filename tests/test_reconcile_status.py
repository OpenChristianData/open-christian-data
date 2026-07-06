from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _catalog(role: str = "pd_anchor") -> dict:
    return {
        "work_id": "reference/test-work",
        "edition": "2000",
        "modernisation_intent": "not_applicable",
        "pd_anchor_decision": {
            "chosen_rendering": "rendering-a",
            "rationale": "Fixture anchor.",
            "decided_at": "2026-05-18T00:00:00+00:00",
            "alternates_considered": [],
        },
        "renderings": [{"rendering_id": "rendering-a", "role": role, "format": "plain", "license": "public-domain"}],
    }


def _stage_status_tree(root: Path, variant: str) -> str:
    work_handle = f"reference/status-{variant}/2000"
    work_dir = root / "data" / work_handle
    _write_json(work_dir / "catalog.json", _catalog("pending" if variant == "catalog_pending" else "pd_anchor"))
    _write_json(
        root / "review/state" / work_handle / "workbench.json",
        {"entries": {"b_0001": {"pending": [{"kind": "choice"}]}} if variant == "workbench_pending" else {}},
    )
    _write_json(
        root / "review/state" / work_handle / "warnings.json",
        {"warnings": [{"code": "CHECKER_WARNING", "message": "fixture"}] if variant == "warnings" else []},
    )
    audit_path = root / "review/audit.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    if variant != "audit_missing":
        audit_path.write_text(json.dumps({"event": "catalog_role_change", "work_handle": work_handle}) + "\n", encoding="utf-8")
    return work_handle


def test_reconcile_status_four_dimensions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    from build.tools.reconcile_status import main

    cases = {
        "clean": (0, "reviewer_clean"),
        "warnings": (1, "checker_warnings"),
        "workbench_pending": (1, "workbench_pending"),
        "catalog_pending": (1, "catalog_pending"),
        "audit_missing": (1, "audit_log_incomplete"),
    }
    for variant, (expected_code, expected_dimension) in cases.items():
        work_handle = _stage_status_tree(tmp_path, variant)
        result = main([work_handle, "--json"])
        output = json.loads(capsys.readouterr().out)
        assert result == expected_code
        assert expected_dimension in json.dumps(output)
        if variant == "clean":
            assert output["reviewer_clean"] is True
        else:
            assert output["reviewer_clean"] is False
