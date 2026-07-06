"""hf_classifier.py -- Classify OCR candidates via HuggingFace Inference API.

Uses HF Serverless Inference (free tier) with an instruction-tuned model.
Processes all candidates from annotated_candidates.json in batches, then
writes classifications for the Gemini backup pass to consume.

Prerequisites:
    pip install huggingface_hub
    Set HF_TOKEN to a read token from huggingface.co/settings/tokens

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/hf_classifier.py \
        --input  build/tools/ocr_scanner/llm_triage/annotated_candidates.json \
        --out    build/tools/ocr_scanner/llm_triage/hf_classifications.json \
        [--model meta-llama/Llama-3.3-70B-Instruct] \
        [--batch-size 20] \
        [--rpm 10] \
        [--resume]

Free-tier notes:
    - HF Serverless Inference is rate-limited; start at --rpm 10 and increase
      if you get no 429s, or lower it if you see frequent errors.
    - Larger models (70B) are slower but more accurate. If quota is tight,
      try meta-llama/Llama-3.1-8B-Instruct for a faster/cheaper pass.

Import-safe: no I/O at module level (PY-06).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

SYSTEM_PROMPT = """\
You classify OCR scan candidates from the Schaff-Herzog Encyclopedia of Religious Knowledge \
(19th-century German theological djvu scan). Each candidate is a suspicious text token.

Classify each as:
- "error"     : genuine OCR mistake (digit replaces letter, stray punctuation, garbled text)
- "not_error" : false positive (proper name, legitimate abbreviation, foreign word, valid formatting)
- "uncertain" : ambiguous; cannot determine from context alone

Key signals per reason type:
- digit_in_letter: a digit replaces a visually similar letter \
(0->O, 1->l/i, 5->S, 6->o/b/G/oe, 8->s/S, 9->g/q) — nearly always "error"; \
exception: manuscript sigla such as O2, N1, I where digits are intentional
- ligature_bracket: opening ( at a word start misreads a ligature (ff/fi/fl) \
— usually "not_error" (genuine parenthetical); rarely error
- stray_pipe_backslash: | or \\ appearing in running prose — always "error"
- apparent_space_deletion: two tokens OCR'd as one — check entry_id; \
proper names in the `term` field are almost always "not_error"; \
body-text cases may be genuine splits
- apparent_space_insertion: erroneous space inserted inside a word — usually "error"
- short_allcaps_orphan: short ALL-CAPS token not in the standard whitelist — \
"not_error" if it looks like a real abbreviation (ZKG, MPL, JE, etc.); \
"error" if it contains non-alpha characters or is clearly garbled

Respond ONLY with a compact JSON array — no markdown fences, no explanation:
[{"id":"cand-XXXXXX","c":"error"},{"id":"cand-YYYYYY","c":"not_error"},...]
"""


def _make_batch_message(batch: list[dict]) -> str:
    """Compact JSON representation of a candidate batch (no rule hints)."""
    items = []
    for cand in batch:
        item: dict = {
            "id": cand["id"],
            "reason": cand["reason"],
            "value": cand["value"],
        }
        if cand.get("suggestion") and cand["suggestion"] != cand["value"]:
            item["suggestion"] = cand["suggestion"]
        if cand.get("entry_id"):
            item["entry_id"] = cand["entry_id"]
        if cand.get("field_path"):
            item["field"] = cand["field_path"].split("[")[0]
        if cand.get("context_before") and cand["context_before"].strip():
            item["ctx_before"] = cand["context_before"][:60]
        if cand.get("context_after") and cand["context_after"].strip():
            item["ctx_after"] = cand["context_after"][:60]
        items.append(item)
    return json.dumps(items, ensure_ascii=False)


_JSON_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)


def _parse_response(text: str, expected_ids: list[str]) -> list[dict]:
    """Extract classification list from model response."""
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        raise ValueError(f"No JSON array in response: {text[:300]!r}")
    raw = json.loads(match.group())

    results = []
    for item in raw:
        cid = item.get("id", "")
        cls = item.get("c", item.get("classification", ""))
        if cls not in ("error", "not_error", "uncertain"):
            cls = "uncertain"
        results.append({"id": cid, "classification": cls})

    returned_ids = {r["id"] for r in results}
    for eid in expected_ids:
        if eid not in returned_ids:
            results.append({"id": eid, "classification": "uncertain",
                            "note": "missing_from_response"})
    return results


def classify_all(
    candidates: list[dict],
    client,
    model: str,
    batch_size: int,
    rpm: int,
    already_done: dict[str, str],
) -> list[dict]:
    remaining = [c for c in candidates if c["id"] not in already_done]
    total = len(candidates)
    done_count = len(already_done)

    batches = [remaining[i:i + batch_size] for i in range(0, len(remaining), batch_size)]
    min_interval = 60.0 / rpm

    print(f"Total candidates : {total}")
    print(f"Already done     : {done_count}")
    print(f"To classify      : {len(remaining)}")
    print(f"Batches          : {len(batches)} x up to {batch_size}")
    print(f"Model            : {model}")
    print(f"Rate limit       : {rpm} RPM  (min {min_interval:.1f}s between requests)")
    print()

    results: list[dict] = []

    for batch_idx, batch in enumerate(batches):
        expected_ids = [c["id"] for c in batch]
        message = _make_batch_message(batch)

        attempt = 0
        while True:
            attempt += 1
            t0 = time.time()
            try:
                resp = client.chat_completion(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": message},
                    ],
                    temperature=0.0,
                    max_tokens=600,
                )
                text = resp.choices[0].message.content or ""
                batch_results = _parse_response(text, expected_ids)
                results.extend(batch_results)

                so_far = done_count + len(results)
                pct = so_far / total * 100
                print(
                    f"  Batch {batch_idx + 1:4d}/{len(batches)}"
                    f"  [{so_far:5d}/{total} = {pct:5.1f}%]"
                    f"  ok ({len(batch_results)} classified)"
                )
                break

            except Exception as exc:
                err = str(exc)
                if "429" in err or "rate" in err.lower() or "quota" in err.lower():
                    wait = min(60.0 * (2 ** (attempt - 1)), 300.0)
                    print(f"  Batch {batch_idx + 1}: rate limit -- waiting {wait:.0f}s (attempt {attempt})")
                    time.sleep(wait)
                    continue
                elif attempt < 3:
                    print(f"  Batch {batch_idx + 1}: error ({exc!r}) -- retrying in 10s (attempt {attempt})")
                    time.sleep(10)
                    continue
                else:
                    print(f"  Batch {batch_idx + 1}: failed after {attempt} attempts: {exc!r}")
                    for cid in expected_ids:
                        results.append({"id": cid, "classification": "uncertain",
                                        "note": "api_error"})
                    break

            finally:
                elapsed = time.time() - t0
                sleep_needed = min_interval - elapsed
                if sleep_needed > 0:
                    time.sleep(sleep_needed)

    return results


def run(
    input_path: Path,
    out_path: Path,
    model: str,
    batch_size: int,
    rpm: int,
    resume: bool,
) -> None:
    try:
        from huggingface_hub import InferenceClient  # type: ignore
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    hf_token = os.environ.get("HF_TOKEN", "")
    if not hf_token:
        print("ERROR: HF_TOKEN environment variable not set.")
        print("  Get a read token at: https://huggingface.co/settings/tokens")
        sys.exit(1)

    client = InferenceClient(token=hf_token)

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    candidates = data.get("candidates", [])
    source_id = data.get("source_id", "unknown")

    already_done: dict[str, str] = {}
    existing_classifications: list[dict] = []
    if resume and out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
        for c in existing.get("classifications", []):
            already_done[c["id"]] = c["classification"]
            existing_classifications.append(c)
        print(f"Resume: loaded {len(already_done)} existing classifications from {out_path}\n")

    new_results = classify_all(candidates, client, model, batch_size, rpm, already_done)
    all_classifications = existing_classifications + new_results

    counts = Counter(c["classification"] for c in all_classifications)
    print()
    print(f"Done: {len(all_classifications)} classified")
    print(f"  error:     {counts['error']:5d}")
    print(f"  not_error: {counts['not_error']:5d}")
    print(f"  uncertain: {counts['uncertain']:5d}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "source_id": source_id,
            "classifier": f"huggingface/{model}",
            "total": len(all_classifications),
            "summary": dict(counts),
            "classifications": all_classifications,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Written: {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Classify OCR candidates via HuggingFace Inference API."
    )
    p.add_argument("--input", required=True,
                   help="annotated_candidates.json from preflight_rules.py")
    p.add_argument("--out", required=True,
                   help="Output path for classifications JSON.")
    p.add_argument("--model", default="meta-llama/Llama-3.3-70B-Instruct",
                   help="HF model ID (default: meta-llama/Llama-3.3-70B-Instruct)")
    p.add_argument("--batch-size", type=int, default=20,
                   help="Candidates per API call (default: 20)")
    p.add_argument("--rpm", type=int, default=10,
                   help="Max requests per minute (default: 10, conservative)")
    p.add_argument("--resume", action="store_true",
                   help="Skip already-classified IDs from a previous partial run.")
    args = p.parse_args()

    run(
        input_path=Path(args.input),
        out_path=Path(args.out),
        model=args.model,
        batch_size=args.batch_size,
        rpm=args.rpm,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
