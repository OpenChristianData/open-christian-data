from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _gold_strata():
    spec = importlib.util.find_spec("build.lib.gold_strata")
    assert spec is not None, "build.lib.gold_strata is missing"
    return importlib.import_module("build.lib.gold_strata")


def _bbox(x: int, y: int, w: int = 100, h: int = 100) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "h": h}


def _word(text: str, confidence: float | None) -> dict[str, Any]:
    suffix = f"{abs(hash((text, confidence))) % 10**8:064x}"[-64:]
    return {
        "observation_token_id": "ot-sha256:" + suffix,
        "word_native_id": "word-" + suffix[-8:],
        "source_raw": text,
        "confidence": confidence,
        "bbox_native": None,
    }


def _page(
    *,
    page_sequence: int,
    block_type: str,
    words: list[tuple[str, float | None]],
    block_bbox: dict[str, int] | None,
) -> dict[str, Any]:
    token_id = "ot-sha256:" + f"{page_sequence:064x}"[-64:]
    text = " ".join(word for word, _confidence in words)
    return {
        "schema_version": "sidecar-page-v1",
        "manifest_id": "sm-test",
        "rendering_id": "rendering-test",
        "page_native_id": str(page_sequence),
        "page_sequence": page_sequence,
        "page_dimensions_native": {"width": None, "height": None, "unit": "unknown"},
        "blocks": [
            {
                "block_id": f"block-{page_sequence:04d}",
                "block_type": block_type,
                "bbox_native": block_bbox,
                "lines": [
                    {
                        "observation_token_id": token_id,
                        "line_native_id": f"line-{page_sequence:04d}",
                        "source_raw": text,
                        "confidence": None,
                        "bbox_native": None,
                        "words": [_word(word, confidence) for word, confidence in words],
                    }
                ],
            }
        ],
        "parsed_keys_index": [],
        "page_extras_carried": {},
        "page_extras_carried_keys": [],
        "page_extras_jcs_sha256": "sha256:" + "0" * 64,
        "source_payload_sha256": "sha256:" + "1" * 64,
    }


def _record(path: str, pages_by_engine: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gold_strata = _gold_strata()
    return {
        "page_path": path,
        "strata": gold_strata.derive_page_strata(pages_by_engine),
    }


def _fixture_records() -> list[dict[str, Any]]:
    greek = "\u03bb\u03bf\u03b3\u03bf\u03c2"
    hebrew = "\u05e9\u05dc\u05d5\u05dd"
    return [
        _record(
            "reports/s1/vol_01/page_0001.json",
            {
                "tesseract": _page(
                    page_sequence=1,
                    block_type="text",
                    words=[("Grace", 96.0), ("peace", 94.0)],
                    block_bbox=_bbox(0, 0),
                )
            },
        ),
        _record(
            "reports/s1/vol_01/page_0002.json",
            {
                "tesseract": _page(
                    page_sequence=2,
                    block_type="diagnostic",
                    words=[(greek, 25.0)],
                    block_bbox=_bbox(0, 0),
                ),
                "abbyy": _page(
                    page_sequence=2,
                    block_type="diagnostic",
                    words=[(greek, 25.0)],
                    block_bbox=_bbox(80, 80),
                ),
            },
        ),
        _record(
            "reports/s1/vol_01/page_0003.json",
            {
                "tesseract": _page(
                    page_sequence=3,
                    block_type="text",
                    words=[(hebrew, 72.0)],
                    block_bbox=_bbox(0, 0),
                ),
                "abbyy": _page(
                    page_sequence=3,
                    block_type="text",
                    words=[(hebrew, 74.0)],
                    block_bbox=_bbox(4, 4),
                ),
            },
        ),
        _record(
            "reports/s1/vol_01/page_0004.json",
            {
                "tesseract": _page(
                    page_sequence=4,
                    block_type="text",
                    words=[("Grace", 65.0), (greek, 62.0)],
                    block_bbox=_bbox(0, 0),
                ),
                "abbyy": _page(
                    page_sequence=4,
                    block_type="text",
                    words=[("Grace", 65.0), (greek, 62.0)],
                    block_bbox=_bbox(20, 20),
                ),
                "azure_read": _page(
                    page_sequence=4,
                    block_type="text",
                    words=[("Grace", 65.0), ("zzq", 62.0)],
                    block_bbox=_bbox(20, 20),
                ),
            },
        ),
        _record(
            "reports/s1/vol_01/page_0005.json",
            {
                "tesseract": _page(
                    page_sequence=5,
                    block_type="text",
                    words=[("12345", None)],
                    block_bbox=_bbox(0, 0),
                ),
                "abbyy": _page(
                    page_sequence=5,
                    block_type="text",
                    words=[("12345", None)],
                    block_bbox=_bbox(2, 2),
                ),
            },
        ),
    ]


def test_selection_covers_every_observed_hard_required_dimension_value() -> None:
    gold_strata = _gold_strata()
    records = _fixture_records()
    observed = gold_strata.enumerate_observed_values(records)

    result = gold_strata.select_stratified_sample(
        records,
        observed,
        target_total=20,
        min_per_value=1,
    )

    selected = set(result.selected_pages)
    for dimension in gold_strata.HARD_REQUIRED_DIMENSIONS:
        for value in observed[dimension]:
            assert any(
                record["page_path"] in selected and record["strata"][dimension] == value
                for record in records
            ), f"{dimension}={value} is uncovered"


def test_uncovered_observed_value_surfaces_empty_required_value_flag() -> None:
    gold_strata = _gold_strata()
    records = _fixture_records()[:2]
    observed = gold_strata.enumerate_observed_values(records)

    result = gold_strata.select_stratified_sample(
        records,
        observed,
        target_total=1,
        min_per_value=1,
    )

    assert any(
        stratum.coverage_flag == "empty_required_value_uncovered"
        for stratum in result.strata
    )


def test_latin_body_heavy_fixture_still_selects_minority_risky_page() -> None:
    gold_strata = _gold_strata()
    records = [
        _record(
            f"reports/s1/vol_01/latin_{index:04d}.json",
            {
                "tesseract": _page(
                    page_sequence=index,
                    block_type="text",
                    words=[("Grace", 97.0), ("church", 95.0)],
                    block_bbox=_bbox(0, 0),
                )
            },
        )
        for index in range(1, 13)
    ]
    records.append(
        _record(
            "reports/s1/vol_01/minority_risky.json",
            {
                "tesseract": _page(
                    page_sequence=99,
                    block_type="diagnostic",
                    words=[("\u03bb\u03bf\u03b3\u03bf\u03c2", 18.0)],
                    block_bbox=_bbox(0, 0),
                ),
                "abbyy": _page(
                    page_sequence=99,
                    block_type="diagnostic",
                    words=[("zzq", 20.0)],
                    block_bbox=_bbox(85, 85),
                ),
            },
        )
    )
    observed = gold_strata.enumerate_observed_values(records)

    result = gold_strata.select_stratified_sample(
        records,
        observed,
        target_total=3,
        min_per_value=1,
    )

    assert "reports/s1/vol_01/minority_risky.json" in result.selected_pages


def test_tight_budget_keeps_risky_value_over_safe_latin_body() -> None:
    # Regression for the lexical-order oversampling bug: under a budget too small
    # to cover every observed script value, a safe Latin-body page must NOT crowd
    # out a risky value (mixed script). Risk priority runs across values.
    gold_strata = _gold_strata()
    greek = "λογος"
    mixed_token = "Logosλ"
    records = [
        _record(
            "reports/s1/vol_01/latin_body.json",
            {"tesseract": _page(
                page_sequence=1, block_type="text",
                words=[("grace", 96.0), ("peace", 95.0)], block_bbox=_bbox(0, 0),
            )},
        ),
        _record(
            "reports/s1/vol_01/greek_risky.json",
            {"tesseract": _page(
                page_sequence=2, block_type="text",
                words=[(greek, 90.0)], block_bbox=_bbox(0, 0),
            )},
        ),
        _record(
            "reports/s1/vol_01/mixed_risky.json",
            {"tesseract": _page(
                page_sequence=3, block_type="text",
                words=[(mixed_token, 90.0)], block_bbox=_bbox(0, 0),
            )},
        ),
    ]
    observed = gold_strata.enumerate_observed_values(records)

    result = gold_strata.select_stratified_sample(
        records, observed, target_total=2, min_per_value=1,
    )

    assert "reports/s1/vol_01/mixed_risky.json" in result.selected_pages
    assert "reports/s1/vol_01/latin_body.json" not in result.selected_pages
