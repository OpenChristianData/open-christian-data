"""merge_decisions.py -- Merge Groq + Gemini outputs into final review artefacts.

Decision logic:
  - Groq says "error" or "not_error"   -> accepted (classified)
  - Groq says "uncertain", Gemini resolves it -> Gemini's answer accepted
  - Groq says "uncertain", Gemini still "uncertain" -> goes to human CSV

Also validates rule hints against LLM decisions:
  - rule_hint agrees with Groq -> noted as "confirmed" (high confidence)
  - rule_hint disagrees with Groq -> flagged as "override" in output (Groq wins)
  - no rule_hint -> just Groq/Gemini decision

Final outputs:
  1. approved.json  -- error candidates ready for apply_approved_corrections.py
  2. whitelist.txt  -- not_error candidate values for adding to config whitelist_terms
  3. human_review.csv -- still-uncertain cases for manual inspection

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/merge_decisions.py \
        --annotated  build/tools/ocr_scanner/llm_triage/annotated_candidates.json \
        --hf-out     build/tools/ocr_scanner/llm_triage/hf_classifications.json \
        --gemini-out build/tools/ocr_scanner/llm_triage/gemini_classifications.json \
        --approved   build/tools/ocr_scanner/llm_triage/merged_approved.json \
        --whitelist  build/tools/ocr_scanner/llm_triage/suggested_whitelist.txt \
        --human-csv  build/tools/ocr_scanner/llm_triage/human_review.csv

Import-safe: no I/O at module level (PY-06).
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def run(
    annotated_path: Path,
    hf_path: Path,
    gemini_path: Path | None,
    approved_path: Path,
    whitelist_path: Path,
    human_csv_path: Path,
) -> None:
    # Load inputs
    with open(annotated_path, encoding="utf-8") as f:
        annotated_data = json.load(f)
    with open(hf_path, encoding="utf-8") as f:
        groq_data = json.load(f)

    gemini_data: dict = {}
    if gemini_path and gemini_path.exists():
        with open(gemini_path, encoding="utf-8") as f:
            gemini_data = json.load(f)

    # Build lookup maps
    cands_by_id = {c["id"]: c for c in annotated_data.get("candidates", [])}
    hf_by_id = {c["id"]: c["classification"] for c in groq_data.get("classifications", [])}
    gemini_by_id = {c["id"]: c["classification"] for c in gemini_data.get("classifications", [])}
    source_id = annotated_data.get("source_id", "unknown")

    # Merge decisions
    approved_errors: list[dict] = []
    not_error_values: list[str] = []
    human_review: list[dict] = []

    rule_confirmed = 0
    rule_overridden = 0

    stats = Counter()

    for cid, cand in cands_by_id.items():
        hf_cls = hf_by_id.get(cid, "uncertain")
        gemini_cls = gemini_by_id.get(cid)  # only set if Gemini ran
        rule_hint = cand.get("rule_hint")

        # Determine final classification
        if hf_cls in ("error", "not_error"):
            final_cls = hf_cls
            final_source = "hf"
        elif hf_cls == "uncertain" and gemini_cls in ("error", "not_error"):
            final_cls = gemini_cls
            final_source = "gemini"
        else:
            final_cls = "uncertain"
            final_source = "none"

        # Track rule hint agreement
        if rule_hint and final_cls != "uncertain":
            if rule_hint == final_cls:
                rule_confirmed += 1
            else:
                rule_overridden += 1

        stats[final_cls] += 1

        if final_cls == "error":
            # Only include if there's an actual correction suggestion
            suggestion = cand.get("suggestion", "")
            value = cand.get("value", "")
            if suggestion and suggestion != value:
                approved_errors.append({
                    "candidate_id": cid,
                    "bad": value,
                    "good": suggestion,
                    "reason": cand.get("reason", ""),
                    "entry_id": cand.get("entry_id", ""),
                    "classification_source": final_source,
                    "rule_hint": rule_hint,
                })
            else:
                # Error but no auto-correction available -> human review
                human_review.append({
                    "id": cid,
                    "final_cls": "error_no_fix",
                    "reason": cand.get("reason", ""),
                    "value": value,
                    "suggestion": suggestion,
                    "entry_id": cand.get("entry_id", ""),
                    "field_path": cand.get("field_path", ""),
                    "context_before": cand.get("context_before", ""),
                    "context_after": cand.get("context_after", ""),
                    "hf_cls": hf_cls,
                    "gemini_cls": gemini_cls or "",
                    "rule_hint": rule_hint or "",
                    "note": "error confirmed but no correction suggestion",
                })

        elif final_cls == "not_error":
            value = cand.get("value", "")
            not_error_values.append(value)

        else:  # uncertain
            human_review.append({
                "id": cid,
                "final_cls": "uncertain",
                "reason": cand.get("reason", ""),
                "value": cand.get("value", ""),
                "suggestion": cand.get("suggestion", ""),
                "entry_id": cand.get("entry_id", ""),
                "field_path": cand.get("field_path", ""),
                "context_before": cand.get("context_before", ""),
                "context_after": cand.get("context_after", ""),
                "hf_cls": hf_cls,
                "gemini_cls": gemini_cls or "",
                "rule_hint": rule_hint or "",
                "note": "",
            })

    # Write approved errors
    approved_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed_at = ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        reviewed_at = datetime.now(tz=ZoneInfo("Australia/Melbourne")).strftime("%Y-%m-%dT%H:%M:%S")
    except (ImportError, KeyError):
        pass  # timestamp is best-effort; missing tz data is non-fatal

    with open(approved_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_id": source_id,
            "reviewed_by": "hf+gemini_llm_triage",
            "reviewed_at": reviewed_at,
            "approved": [e["candidate_id"] for e in approved_errors],
            "rejected": [],
            "notes": {e["candidate_id"]: e["reason"] for e in approved_errors},
            "_corrections_detail": approved_errors,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Write whitelist suggestions
    unique_whitelist = sorted(set(not_error_values))
    with open(whitelist_path, "w", encoding="utf-8") as f:
        f.write("# Suggested additions to schaff-herzog.json whitelist_terms\n")
        f.write("# Review each before adding — these are LLM-classified not_error values\n")
        f.write("# Format: one value per line\n\n")
        for val in unique_whitelist:
            f.write(val + "\n")

    # Write human review CSV
    if human_review:
        human_csv_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "approve", "id", "final_cls", "reason", "value", "suggestion",
            "entry_id", "field_path", "context_before", "context_after",
            "hf_cls", "gemini_cls", "rule_hint", "note",
        ]
        with open(human_csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in sorted(human_review, key=lambda r: (r["reason"], r["id"])):
                row_out = {"approve": ""} | row
                writer.writerow(row_out)

    # Print summary
    total = len(cands_by_id)
    print(f"=== Merge complete ({total} candidates) ===")
    print(f"  error (approved for correction): {stats['error']:5d}")
    print(f"  not_error (false positives):     {stats['not_error']:5d}")
    print(f"  uncertain (needs human review):  {stats['uncertain']:5d}")
    print()
    print(f"  Correction entries (has fix):    {len(approved_errors):5d}  -> {approved_path}")
    print(f"  Error/no fix (in human CSV):     {stats['error'] - len(approved_errors):5d}")
    print(f"  Whitelist candidates:            {len(unique_whitelist):5d}  -> {whitelist_path}")
    print(f"  Human review queue:              {len(human_review):5d}  -> {human_csv_path}")
    print()
    if rule_confirmed + rule_overridden > 0:
        print(f"  Rule hints confirmed by LLM: {rule_confirmed}")
        print(f"  Rule hints overridden by LLM: {rule_overridden}")
        pct = rule_confirmed / (rule_confirmed + rule_overridden) * 100
        print(f"  Rule confirmation rate: {pct:.1f}%")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Merge HF + Gemini classifications into final approved/human-review outputs."
    )
    p.add_argument("--annotated", required=True)
    p.add_argument("--hf-out", required=True,
                   help="hf_classifications.json from hf_classifier.py")
    p.add_argument("--gemini-out", default=None,
                   help="Optional Gemini output (if not provided, uncertain cases go straight to human CSV)")
    p.add_argument("--approved", required=True,
                   help="Output path for approved corrections JSON")
    p.add_argument("--whitelist", required=True,
                   help="Output path for whitelist suggestions text file")
    p.add_argument("--human-csv", required=True,
                   help="Output path for human review CSV")
    args = p.parse_args()

    run(
        annotated_path=Path(args.annotated),
        hf_path=Path(args.hf_out),
        gemini_path=Path(args.gemini_out) if args.gemini_out else None,
        approved_path=Path(args.approved),
        whitelist_path=Path(args.whitelist),
        human_csv_path=Path(args.human_csv),
    )


if __name__ == "__main__":
    main()
