"""compare_classifiers.py -- Compare two LLM classifier outputs for triage validation.

Reads two classification JSON files, computes agreement rate, and reports:
- Agreement counts (both say error / both say not_error / both say uncertain)
- Disagreement cases (requires human review)
- Per-reason breakdown
- Recommendation: auto-decide vs human-queue

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/compare_classifiers.py \
        --a build/tools/ocr_scanner/llm_triage/haiku_classifications.json \
        --b build/tools/ocr_scanner/llm_triage/sonnet_classifications.json \
        [--sample build/tools/ocr_scanner/llm_triage/sample_100.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import Counter, defaultdict


def load(path: Path) -> dict[str, str]:
    """Return {candidate_id: classification} from a classifier output."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {c["id"]: c["classification"] for c in data["classifications"]}


def load_reasons(sample_path: Path) -> dict[str, str]:
    """Return {candidate_id: reason} from the sample file."""
    with open(sample_path, encoding="utf-8") as f:
        data = json.load(f)
    return {c["id"]: c["reason"] for c in data["candidates"]}


def compare(a_path: Path, b_path: Path, sample_path: Path | None) -> None:
    a_label = a_path.stem  # e.g. "haiku_classifications"
    b_label = b_path.stem  # e.g. "sonnet_classifications"

    a = load(a_path)
    b = load(b_path)

    all_ids = set(a) | set(b)
    only_a = set(a) - set(b)
    only_b = set(b) - set(a)
    common = set(a) & set(b)

    if only_a or only_b:
        print(f"WARNING: {len(only_a)} IDs in {a_label} only, {len(only_b)} IDs in {b_label} only")
        print(f"  Comparing {len(common)} common IDs only\n")

    reasons = load_reasons(sample_path) if sample_path else {}

    # Tally
    agree_error = []
    agree_not_error = []
    agree_uncertain = []
    disagree = []

    for cid in sorted(common):
        ca = a[cid]
        cb = b[cid]
        if ca == cb:
            if ca == "error":
                agree_error.append(cid)
            elif ca == "not_error":
                agree_not_error.append(cid)
            else:
                agree_uncertain.append(cid)
        else:
            disagree.append((cid, ca, cb))

    n = len(common)
    n_agree = len(agree_error) + len(agree_not_error) + len(agree_uncertain)
    agreement_pct = n_agree / n * 100 if n else 0

    print(f"=== Classifier agreement report ===")
    print(f"Classifier A: {a_label}  ({len(a)} classifications)")
    print(f"Classifier B: {b_label}  ({len(b)} classifications)")
    print(f"Common candidates: {n}")
    print()
    print(f"AGREEMENT: {n_agree}/{n}  ({agreement_pct:.1f}%)")
    print(f"  Both 'error':     {len(agree_error)}")
    print(f"  Both 'not_error': {len(agree_not_error)}")
    print(f"  Both 'uncertain': {len(agree_uncertain)}")
    print(f"DISAGREEMENT: {len(disagree)}/{n}  ({len(disagree)/n*100:.1f}%)")
    print()

    # Per-reason breakdown
    if reasons:
        print("--- Per-reason breakdown ---")
        by_reason: dict[str, list] = defaultdict(list)
        for cid in common:
            by_reason[reasons.get(cid, "unknown")].append(cid)

        for reason in sorted(by_reason):
            ids = by_reason[reason]
            r_agree = sum(1 for cid in ids if a[cid] == b[cid])
            r_n = len(ids)
            r_disagree_ids = [(cid, a[cid], b[cid]) for cid in ids if a[cid] != b[cid]]
            # Majority classification
            votes = Counter(a[cid] for cid in ids) + Counter(b[cid] for cid in ids)
            dominant = votes.most_common(1)[0][0]
            print(f"  {reason:30s} n={r_n:3d}  agree={r_agree:3d} ({r_agree/r_n*100:5.1f}%)  dominant={dominant}")
        print()

    # Disagreement detail
    if disagree:
        print("--- Disagreements (human review needed) ---")
        for cid, ca, cb in sorted(disagree, key=lambda x: reasons.get(x[0], "")):
            reason = reasons.get(cid, "?")
            print(f"  {cid}  reason={reason:30s}  {a_label}={ca:12s}  {b_label}={cb}")
        print()

    # Scale projection
    total_candidates = 5059
    if n > 0:
        projected_disagree = int(total_candidates * len(disagree) / n)
        print(f"--- Scale projection (total corpus = {total_candidates:,}) ---")
        print(f"  Disagreement rate: {len(disagree)/n*100:.1f}%")
        print(f"  Projected human-review queue: ~{projected_disagree:,} of {total_candidates:,}")
        print(f"  Projected auto-decided:       ~{total_candidates - projected_disagree:,} of {total_candidates:,}")
        print()

    # Recommendation
    print("--- Recommendation ---")
    if agreement_pct >= 90:
        print(f"  PASS ({agreement_pct:.1f}% >= 90%). LLM triage is viable.")
        print("  Next: scale to full 5,059 candidates.")
    elif agreement_pct >= 75:
        print(f"  PARTIAL ({agreement_pct:.1f}%). Triage reduces workload but agreement is moderate.")
        print("  Consider: tighten classifier prompt, or accept ~25% human-review rate.")
    else:
        print(f"  FAIL ({agreement_pct:.1f}% < 75%). LLM triage not reliable for this dataset.")
        print("  Consider: manual review, or rule-based auto-decision by reason type.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--a", required=True, help="Classifier A JSON output")
    p.add_argument("--b", required=True, help="Classifier B JSON output")
    p.add_argument("--sample", help="Original sample_100.json (for reason breakdown)")
    args = p.parse_args()
    compare(Path(args.a), Path(args.b), Path(args.sample) if args.sample else None)


if __name__ == "__main__":
    main()
