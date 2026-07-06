from __future__ import annotations

import json
from pathlib import Path

import pytest


WORK_HANDLE = "reference/test-work/2000"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _catalog() -> dict:
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
            {
                "rendering_id": "candidate-ocr",
                "role": "pending",
                "format": "ocr",
                "license": "public-domain",
                "engine": "tesseract@5.3.0",
            },
        ],
    }


def _gate_fixture(global_agreement: float, page_agreements: list[dict], windows: list[dict]) -> dict:
    return {
        "rendering_id": "candidate-ocr",
        "global_agreement": global_agreement,
        "pages": page_agreements,
        "three_page_windows": windows,
        "local_damage_clusters": [{"start_block": 12, "block_count": 10, "agreement": 0.45}],
    }


def test_r58_ocr_promotion_compound_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = tmp_path / "data/reference/test-work/2000"
    _write_json(work_dir / "catalog.json", _catalog())
    passing = _gate_fixture(
        0.91,
        [{"page": 1, "comparable_blocks": 6, "agreement": 0.72}],
        [{"start_page": 1, "end_page": 3, "comparable_blocks": 18, "agreement": 0.82}],
    )
    page_fail = _gate_fixture(
        0.91,
        [{"page": 2, "comparable_blocks": 6, "agreement": 0.65}],
        [{"start_page": 1, "end_page": 3, "comparable_blocks": 18, "agreement": 0.82}],
    )
    window_fail = _gate_fixture(
        0.92,
        [{"page": 1, "comparable_blocks": 6, "agreement": 0.72}],
        [{"start_page": 1, "end_page": 3, "comparable_blocks": 18, "agreement": 0.75}],
    )
    warning_only = _gate_fixture(
        0.91,
        [{"page": 1, "comparable_blocks": 6, "agreement": 0.72}],
        [{"start_page": 1, "end_page": 3, "comparable_blocks": 18, "agreement": 0.82}],
    )
    _write_json(work_dir / "reconcile-metrics/candidate-ocr.json", passing)
    monkeypatch.chdir(tmp_path)

    from build.tools.bootstrap_renderings import main

    result = main(["promote-pending", WORK_HANDLE, "--rendering-id", "candidate-ocr"])
    assert result in (0, None)
    promoted = json.loads((work_dir / "catalog.json").read_text(encoding="utf-8"))
    assert promoted["renderings"][1]["role"] == "pd_attestor"

    for fixture, expected_gate in [(page_fail, "per-page agreement"), (window_fail, "multi-page window")]:
        _write_json(work_dir / "catalog.json", _catalog())
        _write_json(work_dir / "reconcile-metrics/candidate-ocr.json", fixture)
        with pytest.raises(SystemExit, match=expected_gate):
            main(["promote-pending", WORK_HANDLE, "--rendering-id", "candidate-ocr"])
        refused = json.loads((work_dir / "catalog.json").read_text(encoding="utf-8"))
        assert refused["renderings"][1]["role"] == "pending"

    _write_json(work_dir / "catalog.json", _catalog())
    _write_json(work_dir / "reconcile-metrics/candidate-ocr.json", warning_only)
    result = main(["promote-pending", WORK_HANDLE, "--rendering-id", "candidate-ocr"])
    assert result in (0, None)
    warning_catalog = json.loads((work_dir / "catalog.json").read_text(encoding="utf-8"))
    assert warning_catalog["renderings"][1]["role"] == "pd_attestor"
