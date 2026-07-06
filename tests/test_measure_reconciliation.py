from __future__ import annotations

import pytest

from build.tools.ocr_pipeline import measure_reconciliation as measure


def test_expected_calibration_error_uses_bin_population_weights() -> None:
    rows = [
        measure.CalibrationRow(confidence=0.95, correct=True),
        measure.CalibrationRow(confidence=0.85, correct=False),
        measure.CalibrationRow(confidence=0.15, correct=True),
    ]

    curve = measure.calibration_curve(rows, bins=2)

    assert curve["token_count"] == 3
    assert curve["ece"] == pytest.approx(((0.15 - 1.0) * -1) / 3 + abs(0.9 - 0.5) * 2 / 3)
    assert [bucket["n"] for bucket in curve["bins"]] == [1, 2]


def test_independent_family_agreement_counts_collapsed_blocks_once() -> None:
    candidates = [
        {
            "raw_reading": "grace",
            "attesting_families": ["abbyy", "tesseract", "abbyy"],
        },
        {
            "raw_reading": "graoe",
            "attesting_families": ["surya"],
        },
    ]
    family_blocks = {"abbyy": "family-block-1", "tesseract": "family-block-1", "surya": "family-block-2"}

    agreed = measure.independent_agreement_candidates(candidates, family_blocks)

    assert agreed == []

    family_blocks["tesseract"] = "family-block-3"
    agreed = measure.independent_agreement_candidates(candidates, family_blocks)

    assert [candidate["raw_reading"] for candidate in agreed] == ["grace"]
