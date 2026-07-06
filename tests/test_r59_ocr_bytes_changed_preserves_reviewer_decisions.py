from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _workbench_entries() -> dict:
    return {
        f"b_{index:04d}": {
            "adjudication": {
                "chosen_reading": f"reviewed reading {index}",
                "reviewer_id": "fixture-reviewer",
                "decided_at": "2026-05-18T00:00:00+00:00",
            }
        }
        for index in range(100)
    }


def test_r59_ocr_bytes_changed_preserves_reviewer_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_handle = "reference/test-work/2000"
    work_dir = tmp_path / "data" / work_handle
    changed_ids = {f"b_{index:04d}" for index in range(4)}
    _write_json(
        work_dir / "parses/ocr-old.json",
        {"rendering_id": "ocr-old", "blocks": [{"block_id": f"b_{index:04d}", "text": f"old {index}"} for index in range(100)]},
    )
    _write_json(
        work_dir / "parses/ocr-new.json",
        {
            "rendering_id": "ocr-new",
            "blocks": [
                {"block_id": f"b_{index:04d}", "text": f"{'new' if index < 4 else 'old'} {index}"}
                for index in range(100)
            ],
        },
    )
    _write_json(tmp_path / "review/state/reference/test-work/2000/workbench.json", {"entries": _workbench_entries()})
    monkeypatch.chdir(tmp_path)

    from build.tools.reconcile import main

    result = main([work_handle, "--superseding-rendering", "ocr-new", "--supersedes", "ocr-old"])
    assert result in (0, None)

    workbench = json.loads((tmp_path / "review/state/reference/test-work/2000/workbench.json").read_text(encoding="utf-8"))
    cleared = {block_id for block_id, entry in workbench["entries"].items() if "adjudication" not in entry}
    preserved = {block_id for block_id, entry in workbench["entries"].items() if "adjudication" in entry}
    assert cleared == changed_ids
    assert len(preserved) == 96

    warnings = json.loads((tmp_path / "review/state/reference/test-work/2000/warnings.json").read_text(encoding="utf-8"))
    changed_warnings = [item for item in warnings["warnings"] if item["code"] == "OCR_BYTES_CHANGED"]
    assert {item["block_id"] for item in changed_warnings} == changed_ids

    audit_lines = (tmp_path / "review/audit.jsonl").read_text(encoding="utf-8").splitlines()
    supersession = [json.loads(line) for line in audit_lines if "engine_supersession" in line]
    assert supersession == [
        {
            "event": "engine_supersession",
            "old_engine": "tesseract@5.2.0",
            "new_engine": "tesseract@5.3.0",
            "changed_count": 4,
            "preserved_count": 96,
        }
    ]
