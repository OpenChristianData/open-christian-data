from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_r59_rendering_supersession_preserves_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_raw = tmp_path / "data/ocr-old/raw/source.txt"
    new_raw = tmp_path / "data/ocr-new/raw/source.txt"
    old_raw.parent.mkdir(parents=True)
    new_raw.parent.mkdir(parents=True)
    old_raw.write_bytes(b"old OCR bytes")
    new_raw.write_bytes(b"new OCR bytes")
    _write_json(
        tmp_path / "data/reference/test-work/2000/catalog.json",
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
                    "rendering_id": "ocr-old",
                    "role": "pd_attestor",
                    "format": "ocr",
                    "license": "public-domain",
                    "engine": "tesseract@5.2.0",
                },
                {
                    "rendering_id": "ocr-new",
                    "role": "pending",
                    "format": "ocr",
                    "license": "public-domain",
                    "engine": "tesseract@5.3.0",
                    "supersedes": "ocr-old",
                },
            ],
        },
    )
    before_old = old_raw.read_bytes()
    before_new = new_raw.read_bytes()
    monkeypatch.chdir(tmp_path)

    from build.tools.bootstrap_renderings import main

    result = main(["promote-pending", "reference/test-work/2000", "--rendering-id", "ocr-new"])
    assert result in (0, None)
    assert old_raw.read_bytes() == before_old
    assert new_raw.read_bytes() == before_new
    audit_lines = (tmp_path / "review/audit.jsonl").read_text(encoding="utf-8").splitlines()
    supersession_events = [json.loads(line) for line in audit_lines if "engine_supersession" in line]
    assert supersession_events == [
        {"event": "engine_supersession", "old_engine": "tesseract@5.2.0", "new_engine": "tesseract@5.3.0"}
    ]
