"""preflight_rules.py -- Rule-based hint annotator for OCR scan candidates.

Annotates each candidate with a `rule_hint` (suggested classification based on
high-confidence heuristics). The hint is NOT a final decision — it feeds into
the Groq classifier prompt as a signal, not a conclusion.

Groq must CONFIRM or OVERRIDE every rule hint. Auto-decisions only fire in the
merge step when Groq and the rule agree.

Rules applied:
  1. ligature_bracket    -> hint: not_error
  2. stray_pipe_backslash-> hint: error
  3. digit_in_letter w/ suggestion != value -> hint: error
  4. short_allcaps_orphan w/ non-alpha chars -> hint: error

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/preflight_rules.py \
        --scan-report build/tools/ocr_scanner/reports/schaff-herzog_2026-04-23.json \
        --out         build/tools/ocr_scanner/llm_triage/annotated_candidates.json

Output is a flat list of all candidates, each with an added `rule_hint` field
(one of: "error", "not_error", or None = no confident rule applies).

Import-safe: no I/O at module level (PY-06).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_NON_ALPHA_RE = re.compile(r"[^A-Za-z0-9]")


def _has_non_alpha(value: str) -> bool:
    return bool(_NON_ALPHA_RE.search(value))


def _rule_hint(cand: dict) -> str | None:
    """Return a rule-based hint, or None if no confident rule applies."""
    reason = cand["reason"]
    value = cand["value"]
    suggestion = cand.get("suggestion", value)

    if reason == "ligature_bracket":
        return "not_error"
    if reason == "stray_pipe_backslash":
        return "error"
    if reason == "digit_in_letter" and suggestion != value:
        return "error"
    if reason == "short_allcaps_orphan" and _has_non_alpha(value):
        return "error"
    return None


def run(scan_report_path: Path, out_path: Path) -> None:
    with open(scan_report_path, encoding="utf-8") as f:
        report = json.load(f)

    candidates = report.get("candidates", [])
    source_id = report.get("source_id", "unknown")

    annotated = []
    hint_counts: dict[str | None, int] = {}
    reason_stats: dict[str, dict] = {}

    for cand in candidates:
        hint = _rule_hint(cand)
        entry = dict(cand)
        entry["rule_hint"] = hint
        annotated.append(entry)

        hint_counts[hint] = hint_counts.get(hint, 0) + 1
        reason = cand["reason"]
        if reason not in reason_stats:
            reason_stats[reason] = {"hint_error": 0, "hint_not_error": 0, "hint_none": 0, "total": 0}
        reason_stats[reason]["total"] += 1
        if hint == "error":
            reason_stats[reason]["hint_error"] += 1
        elif hint == "not_error":
            reason_stats[reason]["hint_not_error"] += 1
        else:
            reason_stats[reason]["hint_none"] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_id": source_id,
            "total": len(annotated),
            "hint_summary": {
                "error": hint_counts.get("error", 0),
                "not_error": hint_counts.get("not_error", 0),
                "no_hint": hint_counts.get(None, 0),
            },
            "candidates": annotated,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")

    total = len(annotated)
    print(f"Annotated {total} candidates -> {out_path}")
    print(f"  Rule hint 'error':    {hint_counts.get('error', 0):5d}")
    print(f"  Rule hint 'not_error':{hint_counts.get('not_error', 0):5d}")
    print(f"  No rule hint:         {hint_counts.get(None, 0):5d}")
    print()
    print("Per-reason breakdown:")
    for reason in sorted(reason_stats):
        s = reason_stats[reason]
        print(
            f"  {reason:30s}  n={s['total']:5d}  "
            f"hint_error={s['hint_error']:5d}  "
            f"hint_not_error={s['hint_not_error']:5d}  "
            f"no_hint={s['hint_none']:5d}"
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="Annotate OCR candidates with rule-based hints (not final decisions)."
    )
    p.add_argument("--scan-report", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    run(Path(args.scan_report), Path(args.out))


if __name__ == "__main__":
    main()
