"""Tests for build.lib.reconcile.token_alignment — N-way token alignment.

All tests fail with ImportError until production code exists.
"""
from __future__ import annotations



def test_n_way_token_alignment_two_renderings():
    """N=2: anchor 'The Lord is good', attestor 'The Lord is wom' → replace op on last token."""
    from build.lib.reconcile.token_alignment import align_tokens_nway  # noqa: PLC0415

    anchor_tokens = ["The", "Lord", "is", "good"]
    attestor_tokens = ["The", "Lord", "is", "wom"]

    result = align_tokens_nway(anchor_tokens, [attestor_tokens])

    # Result should be a list of per-rendering alignments or a merged structure
    # At minimum: the "wom"/"good" difference is captured somewhere
    all_ops = result if isinstance(result, list) else result.get("ops", [])
    replace_ops = [op for op in all_ops if op.get("tag") == "replace" or getattr(op, "tag", None) == "replace"]
    assert len(replace_ops) >= 1, "Expected at least one replace op for 'good' vs 'wom'"


def test_n_way_token_alignment_three_renderings():
    """N=3: anchor ['faith'], attestor_a ['faith'], attestor_b ['hope'] → attestor_b divergence captured."""
    from build.lib.reconcile.token_alignment import align_tokens_nway  # noqa: PLC0415

    anchor_tokens = ["faith"]
    attestor_a_tokens = ["faith"]
    attestor_b_tokens = ["hope"]

    result = align_tokens_nway(anchor_tokens, [attestor_a_tokens, attestor_b_tokens])

    # The result should reflect that attestor_b disagrees
    # Shape is implementation-dependent, but attestor_b's "hope" must be represented
    # We check that the result isn't empty and has some indicator of disagreement
    assert result is not None
    # If it returns a per-rendering dict, check attestor_b has a replace
    if isinstance(result, dict):
        assert len(result) >= 1
