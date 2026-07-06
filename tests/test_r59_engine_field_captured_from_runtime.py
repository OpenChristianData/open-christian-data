from __future__ import annotations

import json
import subprocess
from pathlib import Path

import jsonschema
import pytest


def _catalog(engine: str | None) -> dict:
    rendering = {
        "rendering_id": "ocr-rendering",
        "role": "pending",
        "source": "fixture",
        "format": "ocr",
        "license": "public-domain",
        "source_hash": "sha256:" + "1" * 64,
    }
    rendering["engine"] = engine
    return {
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
            rendering,
        ],
    }


def test_r59_engine_field_captured_from_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema = json.loads(Path("schemas/v1/rendering_catalog.schema.json").read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_catalog(None), schema)
    from build.tools.ocr_pipeline.build_rendering import validate_catalog_engines

    with pytest.raises(ValueError):
        validate_catalog_engines(_catalog(""))

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ["tesseract", "--version"]
        assert kwargs["check"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(args, 0, stdout="tesseract 5.3.0\n leptonica-1.82.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)

    from build.tools.ocr_pipeline.build_rendering import main

    result = main(["--rendering-id", "ocr-rendering", "--scan-dir", "scans/ocr-rendering"])
    assert result in (0, None)
    catalog = json.loads((tmp_path / "data/reference/test-work/2000/catalog.json").read_text(encoding="utf-8"))
    ocr_rendering = next(item for item in catalog["renderings"] if item["rendering_id"] == "ocr-rendering")
    assert ocr_rendering["engine"] == "tesseract@5.3.0"
