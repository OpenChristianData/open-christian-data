"""Tests for build.lib.reconcile.structural — N=2 anchor-wins and N≥3 2-of-N rules.

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


def test_r27_attestor_retained_after_anchor_structure_acceptance():
    """R27: attestors remain in attested_by even when anchor structure wins over a structural disagreement."""
    from build.lib.reconcile import reconcile  # noqa: PLC0415

    anchor_id = "anchor"
    attestor_id = "attestor"

    anchor_blocks = [
        _make_block("Block A text.", rendering_id=anchor_id),
        _make_block("Block B text.", rendering_id=anchor_id),
    ]
    # Attestor merges A + B
    attestor_blocks = [_make_block("Block A text. Block B text.", rendering_id=attestor_id)]

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

    # Anchor wins: 2 blocks in output
    assert len(result["blocks"]) == 2

    # Attestor rendering_id MUST appear in attested_by on at least the blocks that matched
    attested_ids = {rid for block in result["blocks"] for rid in block["attested_by"]}
    assert attestor_id in attested_ids, (
        "Attestor rendering_id must remain in attested_by even after anchor structure acceptance"
    )

    # structural_disagreement recorded on affected block(s)
    all_sds = [sd for block in result["blocks"] for sd in block["structural_disagreements"]]
    assert len(all_sds) >= 1
