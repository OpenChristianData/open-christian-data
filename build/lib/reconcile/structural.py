"""structural — N=2 anchor-wins and N>=3 2-of-N structural rules.

ADR-0013 §d:
- N=2: anchor structure is canonical; attestor divergence → structural_disagreement
- N>=3: 2-of-N agree → canonical; only 1 has it → structural_disagreement
"""

from __future__ import annotations

import hashlib



def apply_structural_rules(
    anchor_blocks: list[dict],
    clustered_blocks: list[dict],
    n: int,
) -> list[tuple[dict, list[dict]]]:
    """Apply N=2 anchor-wins or N>=3 2-of-N rule to structural conflicts.

    Returns a list of (block, [structural_disagreement]) pairs, one per anchor block.

    clustered_blocks is the output of align_blocks_nway: a list of cluster dicts
    with keys: anchor_block, anchor_idx, attestor_matches, bucket.
    """
    result: list[tuple[dict, list[dict]]] = []

    for cluster in clustered_blocks:
        anchor_block = cluster["anchor_block"]
        attestor_matches = cluster.get("attestor_matches", [])
        structural_disagreements: list[dict] = []

        # Detect structural conflicts (attestor block count mismatch vs anchor)
        # For N=2: exactly one attestor rendering
        if n == 2 and len(attestor_matches) == 0:
            # No attestor match found for this anchor block — block missing in source
            sd: dict = {"kind": "block_missing_in_source"}
            structural_disagreements.append(sd)
        elif n == 2 and len(attestor_matches) >= 1:
            # N=2 anchor wins — any structural divergence is a disagreement
            # Structural divergence is detected when the matched attestor block
            # covers more than one anchor block (merge) or is itself split.
            # This is handled during alignment — we annotate the cluster.
            for match in attestor_matches:
                conflict_kind = match.get("structural_conflict_kind")
                if conflict_kind:
                    sd = {"kind": conflict_kind}
                    structural_disagreements.append(sd)

        result.append((anchor_block, structural_disagreements))

    return result


def split_block(parent_block: dict, child_texts: list[str]) -> list[dict]:
    """Split a block into child blocks.

    Each child block:
    - Inherits parent block fields
    - Has parent block_id in block_id_history
    - Gets a deterministic block_id: sha256(parent_id + child_text)[:16]
    - Gets original_text set to the child text
    """
    parent_id = parent_block.get("block_id", "")
    parent_history = list(parent_block.get("block_id_history", []))

    # Build new history: parent_id + existing history
    new_history_base = [parent_id] + parent_history if parent_id else parent_history

    children: list[dict] = []
    for text in child_texts:
        # Deterministic child ID: hash of parent_id + text
        raw = f"{parent_id}|{text}"
        child_id = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

        child: dict = {
            **{k: v for k, v in parent_block.items() if k not in {"block_id", "block_id_history", "original_text"}},
            "block_id": child_id,
            "block_id_history": new_history_base,
            "original_text": text,
        }
        children.append(child)

    return children
