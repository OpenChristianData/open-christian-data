from __future__ import annotations

from build.tools.ocr_pipeline.nsh_gold_worksheet import _iou, rejoin_by_geometry


PAGE_SHA = "a" * 64


def _candidate(reading: str) -> dict:
    return {"candidate_key": reading, "raw_reading": reading}


def _position(position_id: str, bbox: dict, reading: str) -> dict:
    return {
        "position_id": position_id,
        "reference_bbox": bbox,
        "candidate_set": [_candidate(reading)],
    }


def _wct_page(positions: list[dict], sha: str = PAGE_SHA) -> dict:
    return {"source_image": {"sha256": sha}, "positions": positions}


def _gold(bbox: dict, *, sha: str = PAGE_SHA, context_window: dict | None = None) -> dict:
    record = {"page_image_sha256": "sha256:" + sha, "bbox": bbox}
    if context_window is not None:
        record["context_window"] = context_window
    return record


def test_iou_known_pairs() -> None:
    assert _iou({"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 0, "y": 0, "w": 10, "h": 10}) == 1.0
    assert _iou({"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 5, "y": 0, "w": 10, "h": 10}) == 1 / 3
    assert _iou({"x": 0, "y": 0, "w": 0, "h": 10}, {"x": 0, "y": 0, "w": 10, "h": 10}) == 0.0


def test_rejoin_by_geometry_exact_match_single_position() -> None:
    results = rejoin_by_geometry(
        [_gold({"x": 0, "y": 0, "w": 10, "h": 10})],
        _wct_page([_position("p1", {"x": 0, "y": 0, "w": 10, "h": 10}, "word")]),
    )

    assert results == [
        {
            "page_image_sha256": "sha256:" + PAGE_SHA,
            "bbox": {"x": 0, "y": 0, "w": 10, "h": 10},
            "matched_position_ids": ["p1"],
            "best_iou": 1.0,
            "reason": None,
        }
    ]


def test_rejoin_by_geometry_below_threshold_reports_no_overlap() -> None:
    results = rejoin_by_geometry(
        [_gold({"x": 0, "y": 0, "w": 10, "h": 10})],
        _wct_page([_position("p1", {"x": 30, "y": 0, "w": 10, "h": 10}, "word")]),
    )

    assert results[0]["matched_position_ids"] == []
    assert results[0]["best_iou"] == 0.0
    assert results[0]["reason"] == "no_overlap"


def test_rejoin_by_geometry_returns_all_resegmented_positions() -> None:
    results = rejoin_by_geometry(
        [_gold({"x": 0, "y": 0, "w": 20, "h": 10})],
        _wct_page(
            [
                _position("left-half", {"x": 0, "y": 0, "w": 10, "h": 10}, "seg"),
                _position("right-half", {"x": 10, "y": 0, "w": 10, "h": 10}, "ment"),
            ]
        ),
        min_iou=0.5,
    )

    assert results[0]["matched_position_ids"] == ["left-half", "right-half"]
    assert results[0]["best_iou"] == 0.5
    assert results[0]["reason"] is None


def test_rejoin_by_geometry_uses_context_window_only_to_reorder_ties() -> None:
    results = rejoin_by_geometry(
        [
            _gold(
                {"x": 0, "y": 0, "w": 10, "h": 10},
                context_window={"left_reading": "left-b", "right_reading": "right-b"},
            )
        ],
        _wct_page(
            [
                _position("left-a", {"x": 40, "y": 0, "w": 5, "h": 5}, "left-a"),
                _position("candidate-a", {"x": 0, "y": 0, "w": 10, "h": 10}, "A"),
                _position("right-a", {"x": 50, "y": 0, "w": 5, "h": 5}, "right-a"),
                _position("left-b", {"x": 60, "y": 0, "w": 5, "h": 5}, "left-b"),
                _position("candidate-b", {"x": 0, "y": 0, "w": 10, "h": 10}, "B"),
                _position("right-b", {"x": 70, "y": 0, "w": 5, "h": 5}, "right-b"),
            ]
        ),
    )

    assert results[0]["matched_position_ids"] == ["candidate-b", "candidate-a"]
    assert results[0]["best_iou"] == 1.0
    assert results[0]["reason"] is None


def test_rejoin_by_geometry_different_page_does_not_attempt_match() -> None:
    results = rejoin_by_geometry(
        [_gold({"x": 0, "y": 0, "w": 10, "h": 10}, sha="b" * 64)],
        _wct_page([_position("p1", {"x": 0, "y": 0, "w": 10, "h": 10}, "word")]),
    )

    assert results[0]["matched_position_ids"] == []
    assert results[0]["best_iou"] == 0.0
    assert results[0]["reason"] == "different_page"
