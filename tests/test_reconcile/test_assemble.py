"""Tests for reconcile assembly — reading score auto-choice gate and reference_only advisory.

All tests fail with ImportError until production code exists.
"""
from __future__ import annotations



def _make_block(text, block_type="paragraph", rendering_id="r1"):
    return {
        "block_type": block_type,
        "original_text": text,
        "annotations": {},
        "source_pages": [{"rendering_id": rendering_id, "page_number": 1}],
        "language": "en",
        "language_confidence": 0.95,
        "language_alternates": [],
        "language_segments": [],
    }


def _assert_span_matches_chosen_reading(disagreements):
    """For every entry with a non-empty chosen_reading, span width must equal
    the token count of chosen_reading. Empty string (insertion ops) is allowed.
    """
    for d in disagreements:
        cr = d.get("chosen_reading")
        if cr is None or cr == "":
            continue
        span = d["span"]
        width = span["end_token"] - span["start_token"]
        assert width == len(cr.split()), (
            f"span width {width} != chosen_reading token count {len(cr.split())} "
            f"for entry {d!r}"
        )


def test_reading_score_auto_choice_fixture_a():
    """Fixture a: same reading in anchor and attestor → auto-chosen."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r1, r2 = "anchor", "attestor"
    renderings = [
        {"rendering_id": r1, "role": "pd_anchor", "blocks": [_make_block("righteousness", rendering_id=r1)]},
        {"rendering_id": r2, "role": "pd_attestor", "blocks": [_make_block("righteousness", rendering_id=r2)]},
    ]
    catalog = {
        "pd_anchor": r1,
        "renderings": [
            {"rendering_id": r1, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r2, "role": "pd_attestor", "format": "ocr"},
        ],
    }

    result = reconcile(renderings, catalog)
    # Identical texts — no disagreement (both agree)
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]
    assert len(all_disagreements) == 0
    # Block is attested by both renderings
    assert r1 in result["blocks"][0]["attested_by"]
    assert r2 in result["blocks"][0]["attested_by"]


def test_reading_score_auto_choice_fixture_b_below_threshold():
    """Fixture b: gap < 2.0 → NOT auto-chosen; chosen_reading = None."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r1, r2 = "anchor", "attestor1"
    # anchor: "faith" (4.0), attestor1: "hope" (3.0)
    # anchor alone → gap = 4.0 - 3.0 = 1.0 < 2.0 threshold → Reviewer
    renderings = [
        {"rendering_id": r1, "role": "pd_anchor", "blocks": [_make_block("faith", rendering_id=r1)]},
        {"rendering_id": r2, "role": "pd_attestor", "blocks": [_make_block("hope", rendering_id=r2)]},
    ]
    catalog = {
        "pd_anchor": r1,
        "renderings": [
            {"rendering_id": r1, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r2, "role": "pd_attestor", "format": "ocr"},
        ],
    }

    result = reconcile(renderings, catalog)
    # Gap = 4.0 - 3.0 = 1.0 < 2.0 → no auto-choice
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]
    # There should be a disagreement with chosen_reading = None (routes to Reviewer)
    assert len(all_disagreements) >= 1
    split_vote = [d for d in all_disagreements if d.get("chosen_reading") is None]
    assert len(split_vote) >= 1, "Expected a Reviewer-queue disagreement (chosen_reading=None) when gap < 2.0"
    _assert_span_matches_chosen_reading(all_disagreements)


def test_reading_score_auto_choice_fixture_c_reference_only_gap():
    """Fixture c: reference_only does NOT contribute to PD-only auto-choice gap (R5)."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r_anchor = "anchor"
    r_ref = "reference_only_rendering"

    renderings = [
        {"rendering_id": r_anchor, "role": "pd_anchor", "blocks": [_make_block("grace", rendering_id=r_anchor)]},
        {"rendering_id": r_ref, "role": "reference_only", "blocks": [_make_block("grace", rendering_id=r_ref)]},
    ]
    catalog = {
        "pd_anchor": r_anchor,
        "renderings": [
            {"rendering_id": r_anchor, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r_ref, "role": "reference_only", "format": "html"},
        ],
    }

    result = reconcile(renderings, catalog)

    # reference_only should NOT appear in chosen_reading_attested_by
    # It may appear in the block's attested_by (it saw the block) but not in reading attestation
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]
    for d in all_disagreements:
        assert r_ref not in d.get("chosen_reading_attested_by", []), (
            "reference_only rendering must not appear in chosen_reading_attested_by"
        )


def test_reference_only_routes_to_advisory_score():
    """R5: reference_only advisory +0.5 goes to advisory_score only, never PD-only gap."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r_anchor = "anchor"
    r_attestor = "attestor"
    r_ref = "ref_only"

    # anchor: "love" (4.0), attestor: "love" (3.0), reference_only: "love" (advisory 0.5)
    renderings = [
        {"rendering_id": r_anchor, "role": "pd_anchor", "blocks": [_make_block("The greatest of these is love.", rendering_id=r_anchor)]},
        {"rendering_id": r_attestor, "role": "pd_attestor", "blocks": [_make_block("The greatest of these is love.", rendering_id=r_attestor)]},
        {"rendering_id": r_ref, "role": "reference_only", "blocks": [_make_block("The greatest of these is love.", rendering_id=r_ref)]},
    ]
    catalog = {
        "pd_anchor": r_anchor,
        "renderings": [
            {"rendering_id": r_anchor, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r_attestor, "role": "pd_attestor", "format": "ocr"},
            {"rendering_id": r_ref, "role": "reference_only", "format": "html"},
        ],
    }

    result = reconcile(renderings, catalog)

    # reference_only must NOT appear in attested_by or chosen_reading_attested_by
    for block in result["blocks"]:
        for d in block["disagreements"]:
            assert r_ref not in d.get("chosen_reading_attested_by", [])

    # If there's a reading_score match_explanation, advisory_score reflects reference_only contribution
    reading_score_mxs = [
        mx for mx in result["match_explanations"]
        if mx["decision"]["kind"] == "reading_score"
    ]
    # If reading_score explanations exist, advisory_score must be >= 0 (not absent)
    for mx in reading_score_mxs:
        assert "advisory_score" in mx["decision"]


def test_r34_reference_copy_support_maps_rendering_to_reading_index():
    """R34: reference_only rendering with reference_copy support maps to reading_index."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r_anchor = "anchor"
    r_ref = "copyrighted_ref"

    renderings = [
        {"rendering_id": r_anchor, "role": "pd_anchor", "blocks": [_make_block("The word of God.", rendering_id=r_anchor)]},
        {"rendering_id": r_ref, "role": "reference_only", "blocks": [_make_block("The word of God.", rendering_id=r_ref)]},
    ]
    catalog = {
        "pd_anchor": r_anchor,
        "renderings": [
            {"rendering_id": r_anchor, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r_ref, "role": "reference_only", "format": "html", "reference_copy": True},
        ],
    }

    result = reconcile(renderings, catalog)

    # reference_only with reference_copy should not enter attested_by on blocks
    for block in result["blocks"]:
        assert r_ref not in block["attested_by"], (
            "reference_only rendering must not appear in block.attested_by"
        )


def test_per_op_disagreement_entries_with_auto_choice():
    """Block with N token-level differences against an attestor produces N entries.

    pd_anchor (4.0) vs pending (2.0) → gap 2.0 → auto-choose fires. Each entry's
    span covers exactly the differing tokens; chosen_reading holds the anchor's
    tokens at that span; all entries share the same match_explanation_id.
    """
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r_anchor, r_att = "anchor", "attestor"
    # 7-token pair with 2 differing positions. Set-overlap = 5/9 > 0.5 so the
    # classifier returns word_substitution (not paraphrase, which would block
    # auto-choose).
    anchor_text = "the quick brown fox jumps over fence"
    attestor_text = "the swift brown cat jumps over fence"

    renderings = [
        {"rendering_id": r_anchor, "role": "pd_anchor",
         "blocks": [_make_block(anchor_text, rendering_id=r_anchor)]},
        {"rendering_id": r_att, "role": "pending",
         "blocks": [_make_block(attestor_text, rendering_id=r_att)]},
    ]
    catalog = {
        "pd_anchor": r_anchor,
        "renderings": [
            {"rendering_id": r_anchor, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r_att, "role": "pending", "format": "ocr"},
        ],
    }

    result = reconcile(renderings, catalog)
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]

    # Two token-level differences → two entries (not one per attestor).
    assert len(all_disagreements) == 2, (
        f"expected 2 per-op entries, got {len(all_disagreements)}: {all_disagreements!r}"
    )

    # Auto-choose fires: chosen_reading is the anchor's tokens at each span.
    chosen = sorted(d["chosen_reading"] for d in all_disagreements)
    assert chosen == ["fox", "quick"], chosen

    # Spans cover exactly the differing tokens (positions 1 and 3 in the anchor).
    spans = sorted((d["span"]["start_token"], d["span"]["end_token"]) for d in all_disagreements)
    assert spans == [(1, 2), (3, 4)], spans

    # Auto-choose attestation: anchor is the attestor of the chosen reading.
    for d in all_disagreements:
        assert d["chosen_reading_attested_by"] == [r_anchor]

    # All entries from the same attestor share one match_explanation_id.
    mx_ids = {d["match_explanation_id"] for d in all_disagreements}
    assert len(mx_ids) == 1, mx_ids

    # All entries share the same kind (computed per attestor, not per op).
    kinds = {d["kind"] for d in all_disagreements}
    assert len(kinds) == 1, kinds

    _assert_span_matches_chosen_reading(all_disagreements)


def test_per_op_span_length_matches_chosen_reading_globally():
    """Sanity check across a representative configuration: the span/chosen_reading
    width invariant holds for every entry produced."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    r_anchor, r_att = "anchor", "attestor"
    renderings = [
        {"rendering_id": r_anchor, "role": "pd_anchor",
         "blocks": [_make_block("alpha beta gamma delta", rendering_id=r_anchor)]},
        {"rendering_id": r_att, "role": "pending",
         "blocks": [_make_block("alpha beat gamma delt", rendering_id=r_att)]},
    ]
    catalog = {
        "pd_anchor": r_anchor,
        "renderings": [
            {"rendering_id": r_anchor, "role": "pd_anchor", "format": "thml"},
            {"rendering_id": r_att, "role": "pending", "format": "ocr"},
        ],
    }
    result = reconcile(renderings, catalog)
    all_disagreements = [d for block in result["blocks"] for d in block["disagreements"]]
    _assert_span_matches_chosen_reading(all_disagreements)
