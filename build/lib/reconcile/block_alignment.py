"""block_alignment — 100-point block-pair scoring per ADR-0013.

Signals:
  annotation_key  30 (exact) / 18 (partial)
  text_similarity 25
  source_order    15
  block_type      10 (exact) / 5 (compatible)
  page_proximity  10
  language_profile 5
  ocr_skeleton     5
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from build.lib.text_alignment import _ocr_skeleton  # type: ignore[attr-defined]


# Compatible block-type pairs (symmetric)
_COMPATIBLE_TYPES: set[frozenset[str]] = {
    frozenset({"heading", "headword"}),
    frozenset({"paragraph", "quote"}),
}


def _tokenise(text: str) -> list[str]:
    return text.lower().split()


def _page_number(block: dict) -> int | None:
    pages = block.get("source_pages", [])
    if pages:
        return pages[0].get("page_number")
    return None


def score_block_pair(block_a: dict, block_b: dict, context: dict | None = None) -> dict:
    """Score a candidate block pair on the 100-point scale.

    Returns {"score": int, "bucket": str, "action": str, "surface": str, "signals": list}.
    """
    signals: list[dict] = []
    total = 0

    # --- annotation_key (30 / 18) ---
    ann_a = block_a.get("annotations", {}) or {}
    ann_b = block_b.get("annotations", {}) or {}
    shared_keys = set(ann_a.keys()) & set(ann_b.keys())
    if shared_keys:
        exact_match = all(ann_a[k] == ann_b[k] for k in shared_keys)
        ann_contribution = 30 if exact_match else 18
    else:
        ann_contribution = 0
    signals.append({"name": "annotation_key", "raw_score": float(bool(shared_keys)), "weight": 30, "contribution": ann_contribution})
    total += ann_contribution

    # --- text_similarity (25) ---
    tokens_a = _tokenise(block_a.get("original_text", ""))
    tokens_b = _tokenise(block_b.get("original_text", ""))
    if tokens_a and tokens_b:
        sim = SequenceMatcher(None, tokens_a, tokens_b, autojunk=False).ratio()
    else:
        sim = 0.0
    text_contribution = round(sim * 25)
    signals.append({"name": "text_similarity", "raw_score": sim, "weight": 25, "contribution": text_contribution})
    total += text_contribution

    # --- source_order (15) ---
    order_contribution = 0
    if context:
        anchor_idx = context.get("anchor_idx")
        attestor_idx = context.get("attestor_idx")
        anchor_len = context.get("anchor_len", 1)
        attestor_len = context.get("attestor_len", 1)
        if anchor_idx is not None and attestor_idx is not None and anchor_len > 0 and attestor_len > 0:
            rel_a = anchor_idx / max(1, anchor_len - 1) if anchor_len > 1 else 0
            rel_b = attestor_idx / max(1, attestor_len - 1) if attestor_len > 1 else 0
            delta = abs(rel_a - rel_b)
            if delta < 0.05:
                order_contribution = 15
            elif delta < 0.20:
                order_contribution = 7
            else:
                order_contribution = 0
    signals.append({"name": "source_order", "raw_score": order_contribution / 15.0, "weight": 15, "contribution": order_contribution})
    total += order_contribution

    # --- block_type (10 / 5) ---
    bt_a = block_a.get("block_type", "")
    bt_b = block_b.get("block_type", "")
    if bt_a == bt_b:
        bt_contribution = 10
    elif frozenset({bt_a, bt_b}) in _COMPATIBLE_TYPES:
        bt_contribution = 5
    else:
        bt_contribution = 0
    signals.append({"name": "block_type", "raw_score": float(bt_a == bt_b), "weight": 10, "contribution": bt_contribution})
    total += bt_contribution

    # --- page_proximity (10) ---
    page_a = _page_number(block_a)
    page_b = _page_number(block_b)
    if page_a is not None and page_b is not None:
        page_diff = abs(page_a - page_b)
        if page_diff == 0:
            page_contribution = 10
        elif page_diff == 1:
            page_contribution = 5
        else:
            page_contribution = 0
    else:
        page_contribution = 0
    signals.append({"name": "page_proximity", "raw_score": float(page_contribution / 10.0), "weight": 10, "contribution": page_contribution})
    total += page_contribution

    # --- language_profile (5) ---
    lang_a = block_a.get("language", "")
    lang_b = block_b.get("language", "")
    if lang_a and lang_b:
        if lang_a == lang_b:
            lang_contribution = 5
        elif lang_a[:2] == lang_b[:2]:
            lang_contribution = 2
        else:
            lang_contribution = 0
    else:
        lang_contribution = 0
    signals.append({"name": "language_profile", "raw_score": float(lang_a == lang_b), "weight": 5, "contribution": lang_contribution})
    total += lang_contribution

    # --- ocr_skeleton (5) ---
    text_a = block_a.get("original_text", "")
    text_b = block_b.get("original_text", "")
    if text_a and text_b:
        skel_a = _ocr_skeleton(text_a.lower())
        skel_b = _ocr_skeleton(text_b.lower())
        skel_ratio = SequenceMatcher(None, skel_a, skel_b, autojunk=False).ratio()
    else:
        skel_ratio = 0.0
    ocr_contribution = round(skel_ratio * 5)
    signals.append({"name": "ocr_skeleton", "raw_score": skel_ratio, "weight": 5, "contribution": ocr_contribution})
    total += ocr_contribution

    score = min(100, total)

    # Bucket assignment
    if score >= 78:
        bucket = "high"
        action = "cluster"
        surface = "silent"
    elif score >= 60:
        bucket = "mid_high"
        action = "cluster"
        # Mid-high surface policy: paragraph → silent, everything else → required
        surface = "silent" if bt_a == "paragraph" else "required"
    elif score >= 45:
        bucket = "mid_low"
        action = "no_cluster"
        surface = "required"
    else:
        bucket = "low"
        action = "no_edge"
        surface = "none"

    return {
        "score": score,
        "bucket": bucket,
        "action": action,
        "surface": surface,
        "signals": signals,
    }


def compute_anchor_style_profile(anchor_blocks: list[dict]) -> dict:
    """Sample anchor list_item blocks; register style conventions at >=95% consistency.

    Returns {"oxford_comma": True} when Oxford comma is >=95% consistent,
    {"oxford_comma": False} when non-Oxford is >=95% consistent,
    or {} when below threshold.
    """
    # Oxford comma pattern: "X, Y, and Z" (serial comma before coordinating conjunction)
    _oxford = re.compile(r",\s+and\s+", re.IGNORECASE)
    # Non-oxford: "X, Y and Z" (no comma before 'and')
    # We look for ", and" (oxford) vs lack of it in lists that have "and"
    _list_and = re.compile(r"\band\b", re.IGNORECASE)

    list_blocks = [b for b in anchor_blocks if b.get("block_type") == "list_item"]
    if not list_blocks:
        return {}

    oxford_count = 0
    non_oxford_count = 0
    for block in list_blocks:
        text = block.get("original_text", "")
        if not _list_and.search(text):
            continue  # no 'and' in text — skip
        if _oxford.search(text):
            oxford_count += 1
        else:
            non_oxford_count += 1

    total = oxford_count + non_oxford_count
    if total == 0:
        return {}

    oxford_ratio = oxford_count / total
    if oxford_ratio >= 0.95:
        return {"oxford_comma": True}
    if (1 - oxford_ratio) >= 0.95:
        return {"oxford_comma": False}
    return {}


def align_blocks_nway(
    anchor_blocks: list[dict],
    attestor_renderings: list[dict],
    catalog: dict,
) -> list[dict]:
    """Progressive pairwise N-way alignment. Returns clusters.

    Each cluster is a dict:
      {
        "anchor_block": dict,
        "anchor_idx": int,
        "attestor_matches": [{"rendering_id": str, "block": dict, "score_result": dict}],
        "bucket": str,
      }
    """
    clusters: list[dict] = []

    n_anchor = len(anchor_blocks)

    for anchor_idx, anchor_block in enumerate(anchor_blocks):
        cluster: dict = {
            "anchor_block": anchor_block,
            "anchor_idx": anchor_idx,
            "attestor_matches": [],
            "bucket": "high",  # will be updated to worst bucket seen
        }

        for attestor_rendering in attestor_renderings:
            rendering_id = attestor_rendering["rendering_id"]
            attestor_blocks = attestor_rendering.get("blocks", [])
            n_attestor = len(attestor_blocks)

            best_score = -1
            best_block = None
            best_result = None

            for attestor_idx, attestor_block in enumerate(attestor_blocks):
                context = {
                    "anchor_idx": anchor_idx,
                    "attestor_idx": attestor_idx,
                    "anchor_len": n_anchor,
                    "attestor_len": n_attestor,
                }
                result = score_block_pair(anchor_block, attestor_block, context=context)
                # Accept all actions except no_edge; but if no cluster candidate is found
                # and only one attestor block exists, fall back to forced positional match.
                if result["score"] > best_score and result["action"] != "no_edge":
                    best_score = result["score"]
                    best_block = attestor_block
                    best_result = result

            # Forced positional match: when the attestor has exactly one block and no
            # match was found (all scored as no_edge), align by position anyway so that
            # disagreements between the only two candidates are still captured.
            if best_block is None and n_attestor == 1 and n_anchor >= 1:
                attestor_block = attestor_blocks[0]
                context = {
                    "anchor_idx": anchor_idx,
                    "attestor_idx": 0,
                    "anchor_len": n_anchor,
                    "attestor_len": n_attestor,
                }
                best_result = score_block_pair(anchor_block, attestor_block, context=context)
                # Override action to allow clustering (forced match)
                best_result = dict(best_result)
                best_result["action"] = "cluster"
                best_result["forced_positional"] = True
                best_block = attestor_block
                best_score = best_result["score"]

            if best_block is not None and best_result is not None:
                cluster["attestor_matches"].append({
                    "rendering_id": rendering_id,
                    "block": best_block,
                    "score_result": best_result,
                })
                # Track worst bucket for the cluster
                buckets_order = ["high", "mid_high", "mid_low", "low"]
                current_worst = cluster["bucket"]
                current_rank = buckets_order.index(current_worst) if current_worst in buckets_order else 0
                new_rank = buckets_order.index(best_result["bucket"]) if best_result["bucket"] in buckets_order else 3
                if new_rank > current_rank:
                    cluster["bucket"] = best_result["bucket"]

        clusters.append(cluster)

    return clusters
