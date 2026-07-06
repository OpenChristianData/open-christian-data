from __future__ import annotations

from build.lib.gold_free_corrector.column_vote import ColumnVoteResult, correct_position
from build.lib.gold_free_corrector.decide import decide


def _make_position(position_id: str, readings: list[tuple[str, list[str]]]) -> dict:
    candidates = [
        {
            "candidate_id": f"{position_id}-c{i}",
            "raw_reading": text,
            "candidate_key": text,
            "attesting_families": families,
            "attesting_engines": [f"eng-{families[0]}"] if families else [],
        }
        for i, (text, families) in enumerate(readings)
    ]
    return {
        "position_id": position_id,
        "candidate_set": candidates,
        "span_records": [],
        "zone": {"zone_id": "zone-body", "zone_type": "body"},
        "script": {"text_level": {"label": "latin"}},
        "alignment_confidence": 0.9,
    }


def _thresholds_reject() -> dict:
    return {
        "body": {
            "L1": {"auto_accept_enabled": False},
        }
    }


def _flagged(position: dict) -> ColumnVoteResult:
    return decide(correct_position(position), _thresholds_reject(), region_class="body")


def _queue_item(position_id: str, **overrides) -> dict:
    item = {
        "position_id": position_id,
        "reason": "release_flagged",
        "external_check_absent": False,
        "region_class": "body",
        "region_class_pending": False,
        "audit_priority": "normal",
        "candidates": [{"candidate_id": f"{position_id}-c0", "raw_reading": "text"}],
        "chosen_reading": {"text": "text"},
    }
    item.update(overrides)
    return item


def test_residue_ranked_by_disagreement() -> None:
    from build.lib.gold_free_corrector.select import select_for_review

    pos_agree = _make_position(
        "pos-agree",
        [("grace", ["abbyy"]), ("grace", ["surya"]), ("grace", ["tesseract"])],
    )
    pos_disagree = _make_position(
        "pos-disagree",
        [("faith", ["abbyy"]), ("works", ["surya"])],
    )
    queue = [_queue_item("pos-agree"), _queue_item("pos-disagree")]

    selected = select_for_review(queue, [_flagged(pos_agree), _flagged(pos_disagree)])

    assert [item["position_id"] for item in selected] == ["pos-disagree", "pos-agree"]


def test_protected_pinned_to_top() -> None:
    from build.lib.gold_free_corrector.select import select_for_review

    protected_cvr = ColumnVoteResult(
        corrected_position={
            "position_id": "pos-protected",
            "protected_class": "proper_name",
            "derivable_readings": [],
            "chosen_reading_index": None,
            "chosen_action": "route_human_review",
            "derivation_method": None,
        },
        columns=[],
        agreement_score=1.0,
    )
    body_position = _make_position(
        "pos-body",
        [("abc", ["abbyy"]), ("xyz", ["surya"]), ("qrs", ["tesseract"])],
    )
    queue = [_queue_item("pos-body"), _queue_item("pos-protected", reason="route_human_review")]

    selected = select_for_review(queue, [_flagged(body_position), protected_cvr])

    assert selected[0]["position_id"] == "pos-protected"
    assert selected[0]["review_features"]["is_protected"] is True


def test_s3_queue_fields_preserved() -> None:
    from build.lib.gold_free_corrector.select import select_for_review

    position = _make_position("pos-field", [("truth", ["abbyy"]), ("trvth", ["surya"])])
    original = _queue_item("pos-field")

    selected = select_for_review([original], [_flagged(position)])

    returned = selected[0]
    for key in (
        "position_id",
        "reason",
        "external_check_absent",
        "region_class",
        "region_class_pending",
        "audit_priority",
        "candidates",
        "chosen_reading",
    ):
        assert returned[key] == original[key]
    assert "review_features" in returned
    assert "review_features" not in original


def test_review_features_added() -> None:
    from build.lib.gold_free_corrector.select import select_for_review

    position = _make_position("pos-features", [("mercy", ["abbyy"]), ("mercie", ["surya"])])

    selected = select_for_review([_queue_item("pos-features")], [_flagged(position)])

    assert set(selected[0]["review_features"]) == {
        "informativeness_score",
        "agreement_score",
        "family_disagreement_entropy",
        "level_penalty",
        "is_protected",
    }
