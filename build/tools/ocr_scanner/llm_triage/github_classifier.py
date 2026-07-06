"""github_classifier.py -- Classify OCR candidates via GitHub Models (Llama 3.3 70B).

GitHub Models free tier (high models): 10 RPM / 50 RPD / 8K input / 4K output per request.
At batch-size 20, 50 RPD = ~1,000 candidates/day.

Run AFTER groq_classifier.py with --resume to extend daily throughput.
Both write to the same output file; --resume skips already-classified IDs.

Prerequisites:
    pip install openai
    Set GITHUB_TOKEN to a GitHub PAT with models:read scope
    (Settings -> Developer settings -> Personal access tokens -> Fine-grained)

Usage:
    py -3 build/tools/ocr_scanner/llm_triage/github_classifier.py \
        --input  build/tools/ocr_scanner/llm_triage/annotated_candidates.json \
        --out    build/tools/ocr_scanner/llm_triage/hf_classifications.json \
        [--model meta-llama-3.3-70b-instruct] \
        [--batch-size 20] \
        [--rpm 8] \
        [--resume]

If the default model ID gives a 404, check the exact ID in the GitHub Models playground:
    https://github.com/marketplace/models -> select model -> Code tab -> Python -> OpenAI

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
- digit_in_letter: digit (0->O, 1->l/i, 5->S, 6->o/b/G, 8->s/S, 9->g/q) replaces a letter \
-- nearly always "error"; "not_error" only for manuscript sigla like O2/N1
- ligature_bracket: opening ( at word start misreads a ligature (ff/fi/fl) \
-- nearly always "not_error" (real parenthetical)
- stray_pipe_backslash: | or \\ in running text -- always "error"
- apparent_space_deletion: compound word or proper name read without space \
-- names in term field are almost always "not_error"
- apparent_space_insertion: erroneous space inside a word -- usually "error"
- short_allcaps_orphan: short ALL-CAPS token -- "not_error" if plausible abbreviation \
(JE, MPL, ZKG etc.), "error" if non-alpha or clearly garbled

Respond ONLY with a compact JSON array -- no markdown fences, no explanation:
[{"id":"cand-XXXXXX","c":"error"},{"id":"cand-YYYYYY","c":"not_error"},...]
"""

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"


def _make_batch_message(batch: list[dict]) -> str:
    """Compact JSON representation of a candidate batch."""
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
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": message},
                    ],
                    temperature=0.0,
                    max_tokens=512,
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
                elif "daily" in err.lower() or "RPD" in err or "requests per day" in err.lower():
                    print(f"  Batch {batch_idx + 1}: daily limit reached -- stopping.")
                    print(f"  Run again tomorrow with --resume, or switch to another provider.")
                    for cid in expected_ids:
                        results.append({"id": cid, "classification": "uncertain",
                                        "note": "api_error"})
                    return results  # Exit early, not a transient error
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
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("ERROR: openai not installed. Run: pip install openai")
        sys.exit(1)

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("ERROR: GITHUB_TOKEN environment variable not set.")
        print("  Create a PAT at: https://github.com/settings/tokens")
        print("  Required scope: models:read")
        sys.exit(1)

    client = OpenAI(
        base_url=GITHUB_MODELS_ENDPOINT,
        api_key=token,
    )

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
            # Skip api_error entries so they get retried
            if c.get("note") == "api_error":
                continue
            already_done[c["id"]] = c["classification"]
            existing_classifications.append(c)
        print(f"Resume: loaded {len(already_done)} existing classifications from {out_path}")
        print(f"  (api_error entries will be retried)\n")

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
            "classifier": f"github/{model}",
            "total": len(all_classifications),
            "summary": dict(counts),
            "classifications": all_classifications,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Written: {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Classify OCR candidates via GitHub Models (Llama 3.3 70B)."
    )
    p.add_argument("--input", required=True,
                   help="annotated_candidates.json from preflight_rules.py")
    p.add_argument("--out", required=True,
                   help="Output path for classifications JSON (same file as groq_classifier if chaining).")
    p.add_argument("--model", default="meta-llama-3.3-70b-instruct",
                   help="GitHub Models model ID (check exact ID in the playground)")
    p.add_argument("--batch-size", type=int, default=20,
                   help="Candidates per API call (default: 20; keep under 8K token input limit)")
    p.add_argument("--rpm", type=int, default=8,
                   help="Max requests per minute (default: 8, under GitHub free 10 RPM cap)")
    p.add_argument("--resume", action="store_true",
                   help="Skip already-classified IDs; retry api_error entries from previous run.")
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
