"""gemini_classifier.py -- Gemini 2.5 Flash second-opinion on uncertain cases.

Reads groq_classifications.json, extracts 'uncertain' cases, re-classifies
them one-by-one (not batched) via Gemini 2.5 Flash for higher accuracy.

Gemini gets full candidate context including Groq's original classification
and the rule hint, and is asked to give a definitive answer where possible.

Prerequisites:
    pip install google-genai
    set GEMINI_API_KEY=<your key from aistudio.google.com>

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/gemini_classifier.py \
        --groq-out       build/tools/ocr_scanner/llm_triage/groq_classifications.json \
        --annotated      build/tools/ocr_scanner/llm_triage/annotated_candidates.json \
        --out            build/tools/ocr_scanner/llm_triage/gemini_classifications.json \
        [--rpm 8]        # free tier: ~10 RPM, be conservative

Import-safe: no I/O at module level (PY-06).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

SYSTEM_PROMPT = """\
You are a specialist in 19th-century OCR errors from German theological encyclopedia scans \
(Schaff-Herzog Encyclopedia, djvu source). You are reviewing cases that a previous \
classifier (Llama 3.3 70B) marked as 'uncertain'. Your job is to give a definitive \
classification where possible.

Classify as:
- "error"     : definitely a genuine OCR mistake
- "not_error" : definitely a false positive (legitimate text)
- "uncertain" : genuinely impossible to determine — use ONLY when truly ambiguous

Think carefully. You have full context: value, suggestion, entry_id, field, surrounding \
text, reason type, and what the previous model said.

Respond with a single JSON object only:
{"classification": "error"|"not_error"|"uncertain", "reasoning": "one sentence"}
"""


def _make_single_message(cand: dict, groq_classification: str) -> str:
    msg = {
        "reason": cand["reason"],
        "value": cand["value"],
        "entry_id": cand.get("entry_id", ""),
        "field": cand.get("field_path", "").split("[")[0],
        "context_before": cand.get("context_before", ""),
        "context_after": cand.get("context_after", ""),
        "groq_said": groq_classification,
    }
    if cand.get("suggestion") and cand["suggestion"] != cand["value"]:
        msg["suggestion"] = cand["suggestion"]
    return json.dumps(msg, ensure_ascii=False)


def _parse_single(text: str) -> tuple[str, str]:
    """Extract (classification, reasoning) from model response."""
    try:
        # Try direct JSON parse
        data = json.loads(text.strip())
        cls = data.get("classification", "uncertain")
        if cls not in ("error", "not_error", "uncertain"):
            cls = "uncertain"
        return cls, data.get("reasoning", "")
    except json.JSONDecodeError:
        pass

    # Fallback: scan for the label
    text_lower = text.lower()
    if '"not_error"' in text_lower or "not_error" in text_lower:
        return "not_error", text[:200]
    if '"error"' in text_lower or "error" in text_lower:
        return "error", text[:200]
    return "uncertain", text[:200]


def run(
    groq_out_path: Path,
    annotated_path: Path,
    out_path: Path,
    rpm: int,
    resume: bool,
) -> None:
    try:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore
    except ImportError:
        print("ERROR: google-genai not installed. Run: pip install google-genai")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable not set.")
        print("  Get a key at: https://aistudio.google.com/")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    # Load Groq output and annotated candidates
    with open(groq_out_path, encoding="utf-8") as f:
        groq_data = json.load(f)
    with open(annotated_path, encoding="utf-8") as f:
        annotated_data = json.load(f)

    groq_by_id = {c["id"]: c["classification"] for c in groq_data.get("classifications", [])}
    cands_by_id = {c["id"]: c for c in annotated_data.get("candidates", [])}
    source_id = annotated_data.get("source_id", "unknown")

    # Find uncertain cases
    uncertain_ids = [
        cid for cid, cls in groq_by_id.items()
        if cls == "uncertain"
    ]

    # Resume: load already-classified IDs from a previous partial run
    already_done: dict[str, dict] = {}
    if resume and out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
        for c in existing.get("classifications", []):
            already_done[c["id"]] = c
        print(f"Resume: loaded {len(already_done)} existing Gemini classifications from {out_path}\n")

    remaining_ids = [cid for cid in uncertain_ids if cid not in already_done]

    print(f"Primary classifier: {len(groq_by_id)} candidates")
    print(f"Uncertain (Gemini will re-review): {len(uncertain_ids)}")
    print(f"Already done: {len(already_done)}")
    print(f"Remaining: {len(remaining_ids)}")
    if not remaining_ids:
        print("No uncertain cases remaining -- nothing for Gemini to do.")
        if not already_done:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({
                    "source_id": source_id,
                    "classifier": "gemini/gemini-2.5-flash",
                    "total": 0,
                    "classifications": [],
                }, f, indent=2)
                f.write("\n")
        return

    print(f"Rate limit: {rpm} RPM  |  Estimated time: {len(remaining_ids) / rpm:.0f} min")
    print()

    min_interval = 60.0 / rpm
    results: list[dict] = list(already_done.values())

    total_uncertain = len(uncertain_ids)
    for i, cid in enumerate(remaining_ids):
        cand = cands_by_id.get(cid)
        if not cand:
            results.append({"id": cid, "classification": "uncertain", "reasoning": "candidate not found"})
            continue

        groq_cls = groq_by_id[cid]
        message = _make_single_message(cand, groq_cls)

        done_so_far = len(already_done) + i + 1
        attempt = 0
        while True:
            attempt += 1
            t0 = time.time()
            try:
                resp = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=message,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.0,
                        max_output_tokens=128,
                    ),
                )
                text = resp.text or ""
                cls, reasoning = _parse_single(text)
                results.append({
                    "id": cid,
                    "classification": cls,
                    "reasoning": reasoning,
                    "groq_was": groq_cls,
                })
                print(
                    f"  [{done_so_far:4d}/{total_uncertain}] {cid}: "
                    f"primary={groq_cls} -> gemini={cls}  ({cand.get('reason', '?')})"
                )
                break

            except Exception as exc:
                err = str(exc)
                err_lower = err.lower()
                is_payment = "402" in err or "payment" in err_lower or "billing" in err_lower
                is_rate_limit = (
                    "429" in err
                    or "rate_limit" in err_lower
                    or "ratelimit" in err_lower
                    or "too many requests" in err_lower
                    or "quota" in err_lower
                    or "resource_exhausted" in err_lower
                )
                if is_payment:
                    print(f"  [{done_so_far}/{total_uncertain}] payment required (402): {err[:200]}")
                    results.append({"id": cid, "classification": "uncertain",
                                    "reasoning": f"api_error: {err[:100]}"})
                    break
                elif is_rate_limit:
                    wait = min(60.0 * (2 ** (attempt - 1)), 300.0)
                    print(f"  [{done_so_far}/{total_uncertain}] rate limit [{err[:120]}], waiting {wait:.0f}s")
                    time.sleep(wait)
                    continue
                elif attempt < 3:
                    print(f"  [{done_so_far}/{total_uncertain}] error: {exc!r}, retrying in 5s")
                    time.sleep(5)
                    continue
                else:
                    results.append({"id": cid, "classification": "uncertain",
                                    "reasoning": f"api_error: {exc!r}"})
                    break

            finally:
                elapsed = time.time() - t0
                sleep_needed = min_interval - elapsed
                if sleep_needed > 0:
                    time.sleep(sleep_needed)

                # Flush progress to disk every 50 classifications so --resume works
                if len(results) % 50 == 0:
                    with open(out_path, "w", encoding="utf-8") as f:
                        json.dump({
                            "source_id": source_id,
                            "classifier": "gemini/gemini-2.5-flash",
                            "total": len(results),
                            "summary": {},
                            "classifications": results,
                        }, f, indent=2, ensure_ascii=False)
                        f.write("\n")

    from collections import Counter
    counts = Counter(r["classification"] for r in results)
    print()
    print(f"Gemini complete: {len(results)} uncertain cases re-reviewed")
    print(f"  Resolved as error:     {counts['error']}")
    print(f"  Resolved as not_error: {counts['not_error']}")
    print(f"  Still uncertain:       {counts['uncertain']}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_id": source_id,
            "classifier": "gemini/gemini-2.5-flash",
            "total": len(results),
            "summary": dict(counts),
            "classifications": results,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Written: {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Gemini second-opinion on Groq's uncertain cases."
    )
    p.add_argument("--groq-out", required=True,
                   help="groq_classifications.json from groq_classifier.py")
    p.add_argument("--annotated", required=True,
                   help="annotated_candidates.json from preflight_rules.py")
    p.add_argument("--out", required=True,
                   help="Output path for Gemini classifications JSON.")
    p.add_argument("--rpm", type=int, default=30,
                   help="Requests per minute (default: 30; use 8 for free-tier keys)")
    p.add_argument("--resume", action="store_true",
                   help="Skip already-classified IDs from a previous partial run.")
    args = p.parse_args()

    run(
        groq_out_path=Path(args.groq_out),
        annotated_path=Path(args.annotated),
        out_path=Path(args.out),
        rpm=args.rpm,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
