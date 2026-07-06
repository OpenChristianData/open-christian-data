"""Tests for build.lib.reconcile.block_alignment — 100-point scoring per ADR-0013.

All tests fail with ImportError until production code exists.
"""
from __future__ import annotations



def _make_block(text, block_type="paragraph", annotations=None, page=1, rendering_id="r1"):
    return {
        "block_type": block_type,
        "original_text": text,
        "annotations": annotations or {},
        "source_pages": [{"rendering_id": rendering_id, "page_number": page}],
        "language": "en",
        "language_confidence": 0.95,
        "language_alternates": [],
        "language_segments": [],
    }


def test_split_merged_block_one_to_many_alignment():
    """Anchor has 1 block; attestor splits it into 2 — structural_disagreement surfaces as block_split_in_source."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "anchor"
    attestor_id = "attestor"
    anchor_blocks = [_make_block("First sentence. Second sentence.", rendering_id=anchor_id)]
    attestor_blocks = [
        _make_block("First sentence.", rendering_id=attestor_id),
        _make_block("Second sentence.", rendering_id=attestor_id),
    ]

    renderings = [
        {"rendering_id": anchor_id, "role": "pd_anchor", "blocks": anchor_blocks},
        {"rendering_id": attestor_id, "role": "pd_attestor", "blocks": attestor_blocks},
    ]
    catalog = {
        "pd_anchor": anchor_id,
        "renderings": [
            {"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": attestor_id, "role": "pd_attestor", "format": "ocr"},
        ],
    }

    result = reconcile(renderings, catalog)

    # Anchor structure wins: 1 block in output
    assert len(result["blocks"]) == 1
    # structural_disagreement of kind block_split_in_source
    sds = result["blocks"][0]["structural_disagreements"]
    assert len(sds) >= 1
    assert any(sd["kind"] == "block_split_in_source" for sd in sds)


def test_r24_promoted_ocr_scores_as_pd_attestor():
    """R24: rendering with role=pd_attestor (OCR-promoted) → base score 3.0, not 2.0."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "anchor"
    promoted_id = "promoted_ocr"  # was 'pending', now pd_attestor

    anchor_blocks = [_make_block("The word of God is living.", rendering_id=anchor_id)]
    # OCR-promoted attestor has a slight OCR variant
    promoted_blocks = [_make_block("The word of God is livmg.", rendering_id=promoted_id)]

    renderings = [
        {"rendering_id": anchor_id, "role": "pd_anchor", "blocks": anchor_blocks},
        {"rendering_id": promoted_id, "role": "pd_attestor", "blocks": promoted_blocks},
    ]
    catalog = {
        "pd_anchor": anchor_id,
        "renderings": [
            {"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": promoted_id, "role": "pd_attestor", "format": "ocr"},
        ],
    }

    result = reconcile(renderings, catalog)

    # The promoted attestor's OCR disagreement should have a match_explanation
    # with the reading_score decision showing pd_only_gap uses base 3.0 for pd_attestor
    reading_score_explanations = [
        mx for mx in result["match_explanations"]
        if mx["decision"]["kind"] == "reading_score"
    ]
    # There should be at least one reading_score explanation (the "livmg" vs "living" disagreement)
    assert len(reading_score_explanations) >= 1
    # The winning reading should have PD support (pd_anchor wins)
    assert reading_score_explanations[0]["decision"]["winning_has_pd_support"] is True


def test_r25_punctuation_modifier_requires_anchor_style_threshold():
    """R25: punctuation modifier fires at 96% consistency; does NOT fire at 80%."""
    from build.lib.reconcile.block_alignment import compute_anchor_style_profile  # noqa: PLC0415

    # Fixture 1: 96% Oxford comma consistency → convention registers
    list_blocks_96 = []
    for i in range(100):
        text = "faith, hope, and love" if i < 96 else "faith, hope and love"
        list_blocks_96.append({"block_type": "list_item", "original_text": text})

    profile_96 = compute_anchor_style_profile(list_blocks_96)
    assert profile_96.get("oxford_comma") is True, (
        "Expected oxford_comma convention to register at 96% consistency"
    )

    # Fixture 2: 80% Oxford comma consistency → convention does NOT register
    list_blocks_80 = []
    for i in range(100):
        text = "faith, hope, and love" if i < 80 else "faith, hope and love"
        list_blocks_80.append({"block_type": "list_item", "original_text": text})

    profile_80 = compute_anchor_style_profile(list_blocks_80)
    assert profile_80.get("oxford_comma") is not True, (
        "Expected oxford_comma convention NOT to register at 80% consistency (below 95% threshold)"
    )


def test_r28_checker_surfaces_threshold_and_bucket_metrics():
    """R28: reconcile emits bucket distribution metrics in the reconcile result."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "anchor"
    attestor_id = "attestor"

    # Create blocks with varying similarity to exercise multiple buckets
    anchor_blocks = [
        _make_block("The grace of our Lord Jesus Christ be with you all.", rendering_id=anchor_id),
        _make_block("Now unto him that is able to do exceeding abundantly.", rendering_id=anchor_id),
        _make_block("For by grace are ye saved through faith.", rendering_id=anchor_id),
    ]
    attestor_blocks = [
        _make_block("The grace of our Lord Jesus Christ be with you all.", rendering_id=attestor_id),  # identical
        _make_block("Naw unto him that is able to do exceeding abundantly.", rendering_id=attestor_id),  # OCR error
        _make_block("For by grace are ye saved through faith.", rendering_id=attestor_id),  # identical
    ]

    renderings = [
        {"rendering_id": anchor_id, "role": "pd_anchor", "blocks": anchor_blocks},
        {"rendering_id": attestor_id, "role": "pd_attestor", "blocks": attestor_blocks},
    ]
    catalog = {
        "pd_anchor": anchor_id,
        "renderings": [
            {"rendering_id": anchor_id, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": attestor_id, "role": "pd_attestor", "format": "ocr"},
        ],
    }

    result = reconcile(renderings, catalog)

    # R28: reconcile result includes bucket distribution under meta or a top-level key
    # Acceptable shapes: result["meta"]["bucket_metrics"] or result["bucket_metrics"]
    bucket_metrics = result.get("meta", {}).get("bucket_metrics") or result.get("bucket_metrics")
    assert bucket_metrics is not None, "Expected bucket_metrics in reconcile result for R28"
    for key in ("high_count", "mid_high_count", "mid_low_count", "low_count"):
        assert key in bucket_metrics, f"Missing {key} in bucket_metrics"
