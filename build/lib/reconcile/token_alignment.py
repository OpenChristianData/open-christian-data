"""token_alignment — N-way token alignment using text_alignment as the 2-way primitive."""

from __future__ import annotations

from build.lib.text_alignment import align_tokens


def align_tokens_nway(
    anchor_tokens: list[str],
    attestor_token_lists: list[list[str]],
) -> list[dict]:
    """Progressive pairwise N-way alignment.

    For each attestor token list, calls align_tokens (the 2-way primitive) and
    collects all replace/delete/insert ops.

    Returns a flat list of op dicts:
      {
        "tag": str,
        "anchor_span": [start, end],
        "attestor_idx": int,
        "anchor_text": list[str],
        "attestor_text": list[str],
      }

    Only non-equal ops are returned.
    """
    all_ops: list[dict] = []

    for attestor_idx, attestor_tokens in enumerate(attestor_token_lists):
        token_ops = align_tokens(anchor_tokens, attestor_tokens)
        for op in token_ops:
            if op.tag == "equal":
                continue
            all_ops.append({
                "tag": op.tag,
                "anchor_span": list(op.canonical_range),
                "attestor_idx": attestor_idx,
                "anchor_text": list(op.canonical_text),
                "attestor_text": list(op.witness_text),
            })

    return all_ops
