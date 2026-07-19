from __future__ import annotations

from ocd_kernel.lib.queue_assembly import assemble_queue_item


def _token(candidate_attestations: list[dict] | None = None) -> dict:
    token = {
        "canonical_token_id": "tok-1",
        "batch_id": "batch-1",
        "matrix_phase": "phase_2",
        "decision_action": "review",
        "deferral_reason": "dispute",
    }
    if candidate_attestations is not None:
        token["candidate_attestations"] = candidate_attestations
    return token


def test_disagreement_score_zero_when_all_families_attest_same_candidate() -> None:
    item = assemble_queue_item(_token([
        {"candidate_id": "a", "attesting_families": ["pd", "ocr", "llm", "reference"]},
    ]))

    assert item["disagreement_score"] == 0.0


def test_disagreement_score_uses_largest_family_count_across_candidates() -> None:
    item = assemble_queue_item(_token([
        {"candidate_id": "a", "attesting_families": ["pd"]},
        {"candidate_id": "b", "attesting_families": ["ocr", "llm", "reference"]},
    ]))

    assert item["disagreement_score"] == 0.25


def test_disagreement_score_half_when_two_families_attest_different_candidates() -> None:
    item = assemble_queue_item(_token([
        {"candidate_id": "a", "attesting_families": ["pd"]},
        {"candidate_id": "b", "attesting_families": ["ocr"]},
    ]))

    assert item["disagreement_score"] == 0.5


def test_disagreement_score_defaults_to_zero_without_candidate_attestations() -> None:
    assert assemble_queue_item(_token([]))["disagreement_score"] == 0.0
    assert assemble_queue_item(_token())["disagreement_score"] == 0.0


def test_queue_item_has_exactly_eight_keys() -> None:
    item = assemble_queue_item(_token([]))

    assert list(item.keys()) == [
        "canonical_token_id",
        "batch_id",
        "candidate_attestations",
        "matrix_phase",
        "decision_action",
        "deferral_reason",
        "disagreement_score",
        "scan_crop",
    ]
