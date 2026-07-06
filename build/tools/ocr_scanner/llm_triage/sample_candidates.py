"""sample_candidates.py -- Draw a proportional stratified sample from the review CSV.

Outputs a JSON file with 100 candidates (proportional by reason) for LLM triage validation.

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/sample_candidates.py \
        --csv build/tools/ocr_scanner/reports/schaff-herzog_2026-04-23_review.csv \
        --out build/tools/ocr_scanner/llm_triage/sample_100.json \
        [--n 100] [--seed 42]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


def sample(csv_path: Path, out_path: Path, n: int = 100, seed: int = 42) -> None:
    """Draw stratified sample by reason and write to JSON."""
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    # Group by reason
    by_reason: dict[str, list[dict]] = {}
    for row in rows:
        by_reason.setdefault(row["reason"], []).append(row)

    total = len(rows)
    rng = random.Random(seed)

    # Compute per-reason sample sizes (proportional, at least 1 each, sum = n)
    counts = {reason: len(group) for reason, group in by_reason.items()}
    alloc: dict[str, int] = {reason: max(1, round(count / total * n))
                              for reason, count in counts.items()}
    # Adjust to exactly n
    diff = n - sum(alloc.values())
    # Add/subtract from largest group
    largest = max(alloc, key=lambda r: counts[r])
    alloc[largest] += diff

    sampled = []
    for reason, group in by_reason.items():
        k = min(alloc[reason], len(group))
        chosen = rng.sample(group, k)
        sampled.extend(chosen)

    # Sort for reproducibility
    sampled.sort(key=lambda r: (r["reason"], r["id"]))

    out = {
        "source_id": "schaff-herzog",
        "source_csv": str(csv_path),
        "total_candidates": total,
        "sample_size": len(sampled),
        "seed": seed,
        "allocation": alloc,
        "candidates": [
            {
                "id": r["id"],
                "tier": r["tier"],
                "reason": r["reason"],
                "value": r["value"],
                "suggestion": r["suggestion"],
                "confidence": r["confidence"],
                "entry_id": r["entry_id"],
                "field_path": r["field_path"],
                "context_before": r["context_before"],
                "context_after": r["context_after"],
                "occurrences": r["occurrences"],
            }
            for r in sampled
        ],
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Sampled {len(sampled)} candidates -> {out_path}")
    for reason, k in sorted(alloc.items()):
        print(f"  {reason}: {k}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()
    sample(Path(args.csv), Path(args.out), n=args.n, seed=args.seed)


if __name__ == "__main__":
    main()
