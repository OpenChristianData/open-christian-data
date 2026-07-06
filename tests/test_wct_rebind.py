from __future__ import annotations

from build.lib.wct_rebind import compare_pages, corpus_summary, dry_run_events


def _position(pid: str, text: str, x: int) -> dict:
    return {
        "position_id": pid,
        "candidate_set": [
            {
                "candidate_id": f"{pid}-cand",
                "raw_reading": text,
                "candidate_key": text,
            }
        ],
        "reference_bbox": {"x": x, "y": 10, "w": 20, "h": 10},
    }


def _page(page_id: str, readings: list[tuple[str, int]]) -> dict:
    positions = [
        _position(f"vol_02:{page_id}:body:c1:l000:p{i:03d}", text, x)
        for i, (text, x) in enumerate(readings)
    ]
    return {
        "schema_type": "word_confusion_table",
        "work_id": "jewish-encyclopedia.vol_02",
        "volume_id": "vol_02",
        "page_id": page_id,
        "source_image": {"path": f"raw/{page_id}.jpg", "sha256": "a" * 64},
        "reading_order": [position["position_id"] for position in positions],
        "positions": positions,
    }


def test_compare_pages_counts_stable_canonical_ids_as_identical() -> None:
    old = _page("page_0010", [("Alpha", 10), ("Beta", 40)])
    new = _page("page_0010", [("Alpha", 10), ("Beta", 40)])

    result = compare_pages(old, new, page_num_by_sha={})

    assert result["identical_count"] == 2
    assert result["rebound_count"] == 0
    assert result["orphaned_count"] == 0
    assert result["identity_rate"] == 1.0


def test_compare_pages_rebinds_same_text_and_bbox_after_ordinal_shift() -> None:
    old = _page("page_0010", [("Alpha", 10), ("Beta", 40)])
    new = _page("page_0010", [("Inserted", 100), ("Alpha", 10), ("Beta", 40)])

    result = compare_pages(old, new, page_num_by_sha={})

    assert result["identical_count"] == 0
    assert result["rebound_count"] == 2
    assert result["orphaned_count"] == 0
    assert result["addition_count"] == 1
    assert {item["match_method"] for item in result["rebound"]} == {"anchor_high_confidence"}


def test_compare_pages_does_not_rebind_same_text_far_from_bbox() -> None:
    old = _page("page_0010", [("Alpha", 10)])
    new = _page("page_0010", [("Inserted", 10), ("Alpha", 800)])

    result = compare_pages(old, new, page_num_by_sha={})

    assert result["identical_count"] == 0
    assert result["rebound_count"] == 0
    assert result["orphaned_count"] == 1
    assert result["orphaned"][0]["orphan_reason"] == "no_anchor_match"


def test_dry_run_events_use_workflow_rebind_and_orphan_shapes() -> None:
    old = _page("page_0010", [("Alpha", 10)])
    new = _page("page_0010", [("Inserted", 100), ("Alpha", 10)])
    result = compare_pages(old, new, page_num_by_sha={})

    events = dry_run_events(result, volume=2)

    assert len(events) == 1
    assert events[0]["event_type"] == "auto_rebind_system"
    assert events[0]["event_category"] == "workflow_event"
    assert events[0]["measurement_eligible"] is False


def test_corpus_summary_rolls_up_counts() -> None:
    pages = [
        compare_pages(_page("page_0010", [("Alpha", 10)]), _page("page_0010", [("Alpha", 10)]), page_num_by_sha={}),
        compare_pages(_page("page_0011", [("Beta", 10)]), _page("page_0011", [("Gamma", 10)]), page_num_by_sha={}),
    ]

    summary = corpus_summary(pages)

    assert summary["pages"] == 2
    assert summary["old_token_count"] == 2
    assert summary["identical_count"] == 1
    assert summary["orphaned_count"] == 1
