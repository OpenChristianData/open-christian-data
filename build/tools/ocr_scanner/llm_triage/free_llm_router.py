"""free_llm_router.py -- Classify OCR candidates via any OpenAI-compatible API.

Covers: Cerebras, NVIDIA NIM, Mistral, HuggingFace, OpenRouter, GitHub Models, and any
other provider with an OpenAI-compatible chat completions endpoint.

Use --provider <name> to load a preset, or override with --base-url / --model / --api-key-env.

## Provider presets (--provider <name>)

| Name       | Model                                    | RPM       | RPD    | TPD    |
|------------|------------------------------------------|-----------|--------|--------|
| cerebras   | gpt-oss-120b                             | 5 (trial) | unkwn  | 1M     |
| nvidia     | meta/llama-3.3-70b-instruct              | ~40       | none   | unkwn  |
| mistral    | mistral-large-latest                     | 2         | unkwn  | 1B/mo  |
| hf         | meta-llama/Llama-3.3-70B-Instruct        | ~8        | unkwn  | credits|
| openrouter | meta-llama/llama-3.3-70b-instruct:free   | 20        | 50     | unkwn  |
| github     | meta/llama-3.3-70b-instruct              | 10        | 50     | unkwn  |

Rate limits verified 2026-06-04 from official docs.
- Cerebras: free trial = 5 RPM / 1M TPD. Activated accounts reported ~30 RPM / 14.4K RPD.
- Mistral free tier is 2 RPM (very low) -- use for token volume, not speed.
- OpenRouter: 50 RPD without credits; $10 loaded once unlocks 1K RPD permanently.
- GitHub: 50 RPD high-tier models, 150 RPD low-tier. Endpoint: models.github.ai/v1.
- NVIDIA: no daily cap, ~40 RPM, but credit-limited (1K credits on signup).

Cerebras is the best free option if account is provisioned (1M TPD).

## Recommended daily run order (chain with --resume)

  1. cerebras   -- likely finishes everything in one shot (~10 min)
  2. nvidia     -- if Cerebras doesn't cover all (actual Llama 3.3 70B)
  3. groq       -- see groq_classifier.py (uses groq SDK, not this script)
  4. mistral    -- quality alternative, 1B tokens/month
  5. hf         -- HF monthly credits ($0.10, resets each month)
  6. github     -- 50 RPD last resort
  7. openrouter -- fallback; useful RPD only with $10 credit loaded

## Prerequisites

  pip install openai

  Set ONE of these env vars (matching your chosen provider):
    CEREBRAS_API_KEY   -- https://cloud.cerebras.ai/  (free, email only)
    NVIDIA_API_KEY     -- https://build.nvidia.com/   (free, accept model ToS first)
    MISTRAL_API_KEY    -- https://console.mistral.ai/ (free, phone verify)
    HF_TOKEN           -- https://huggingface.co/settings/tokens ($0.10/mo free credits)
    OPENROUTER_API_KEY -- https://openrouter.ai/      (free; 50 RPD, $10 unlocks 1K permanently)
    GITHUB_TOKEN       -- https://github.com/settings/tokens (any PAT, no special scope)

## Usage

  py -3 build/tools/ocr_scanner/llm_triage/free_llm_router.py ^
      --provider cerebras ^
      --input  build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
      --out    build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
      --resume

  # Override model or RPM:
  py -3 ... --provider cerebras --model zai-glm-4.7 --rpm 25

  # Use a provider not in the preset list:
  py -3 ... --base-url https://api.example.com/v1 --api-key-env MY_KEY --model my-model

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

# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, dict] = {
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        # As of 2026-06-04: only gpt-oss-120b and zai-glm-4.7 are live.
        # qwen-3-235b-a22b-instruct-2507 and llama3.1-8b have been removed.
        "model": "gpt-oss-120b",
        "rpm": 25,  # conservative under 30 cap
        "notes": (
            "14,400 RPD / 1M TPD -- fastest free option. All 5,059 in ~10 min. "
            "Live models (2026-06-04): gpt-oss-120b, zai-glm-4.7."
        ),
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_API_KEY",
        "model": "meta/llama-3.3-70b-instruct",
        # Other available models: qwen/qwen2.5-coder-32b-instruct (coding-focused, less ideal)
        "rpm": 35,  # conservative under ~40 published cap
        "notes": (
            "Llama 3.3 70B -- actual model, good quality. "
            "Accept model ToS on build.nvidia.com before first call. "
            "Endpoint: integrate.api.nvidia.com/v1"
        ),
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "model": "mistral-large-latest",
        "rpm": 2,  # free tier is 2 RPM (not 60 -- that was wrong). Good for token volume only.
        "notes": "2 RPM / 1B tokens/month free. Slow but generous on total volume. WARNING: prompts may train Mistral models.",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
        # Other strong free models: qwen/qwen3-235b-a22b:free, deepseek/deepseek-r1:free
        "rpm": 18,  # conservative under 20 cap
        "notes": "50 RPD free (no credits). $10 loaded once unlocks 1K RPD permanently.",
    },
    "hf": {
        "base_url": "https://router.huggingface.co/v1",
        "api_key_env": "HF_TOKEN",
        "model": "meta-llama/Llama-3.3-70B-Instruct",
        "rpm": 8,  # conservative; HF docs say "few hundred requests per hour"
        "notes": "$0.10/month free credits, resets monthly. Use HF_TOKEN.",
    },
    "cloudflare": {
        # base_url is constructed at runtime using CLOUDFLARE_ACCOUNT_ID
        # Set: setx CLOUDFLARE_ACCOUNT_ID <your account ID from dash.cloudflare.com>
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1",
        "api_key_env": "CLOUDFLARE_API_KEY",
        "model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "rpm": 8,  # conservative; free tier is neuron-based (10K neurons/day)
        "notes": (
            "10,000 neurons/day free. Llama 3.3 70B fp8-quantized. "
            "Also needs CLOUDFLARE_ACCOUNT_ID env var for base URL. "
            "Other models: @cf/openai/gpt-oss-120b, @cf/qwen/qwen3-30b-a3b"
        ),
    },
    "github": {
        # Old endpoint (models.inference.ai.azure.com) is deprecated — returns 401.
        "base_url": "https://models.github.ai/v1",
        "api_key_env": "GITHUB_TOKEN",
        "model": "meta/llama-3.3-70b-instruct",
        "rpm": 8,  # conservative under 10 RPM cap; 50 RPD free (high-tier models)
        "notes": "50 RPD / 10 RPM free. No special scope needed — any valid GitHub PAT works.",
    },
}

# ---------------------------------------------------------------------------
# Shared prompt and batch helpers (identical across all providers)
# ---------------------------------------------------------------------------

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


def _make_batch_message(batch: list[dict]) -> str:
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


# ---------------------------------------------------------------------------
# Core classify loop
# ---------------------------------------------------------------------------

def classify_all(
    candidates: list[dict],
    client,
    model: str,
    batch_size: int,
    rpm: int,
    already_done: dict[str, str],
    provider_name: str,
) -> list[dict]:
    remaining = [c for c in candidates if c["id"] not in already_done]
    total = len(candidates)
    done_count = len(already_done)

    batches = [remaining[i:i + batch_size] for i in range(0, len(remaining), batch_size)]
    min_interval = 60.0 / rpm

    print(f"Provider         : {provider_name}")
    print(f"Total candidates : {total}")
    print(f"Already done     : {done_count}")
    print(f"To classify      : {len(remaining)}")
    print(f"Batches          : {len(batches)} x up to {batch_size}")
    print(f"Model            : {model}")
    print(f"Rate limit       : {rpm} RPM  (min {min_interval:.1f}s between requests)")
    if len(remaining) > 0:
        est_min = len(batches) * min_interval / 60
        print(f"Est. time        : {est_min:.0f} min (if no rate limits hit)")
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
                err_lower = err.lower()
                # 402 / payment: account needs billing — stop immediately, not transient
                is_payment_required = "402" in err or "payment" in err_lower or "billing" in err_lower
                is_rate_limit = (
                    "429" in err
                    or "too many requests" in err_lower
                    or "rate limit" in err_lower
                    or "rate_limit" in err_lower
                    or "ratelimit" in err_lower
                    or "quota" in err_lower
                )
                is_daily_limit = any(p in err_lower for p in ("daily", "per day", "rpd", "day limit"))

                if is_payment_required:
                    print(f"  Batch {batch_idx + 1}: payment required (402) -- this provider needs billing.")
                    print(f"  Error: {err[:200]}")
                    print(f"  Visit your provider billing page, then re-run. Switching to next provider with --resume.")
                    for cid in expected_ids:
                        results.append({"id": cid, "classification": "uncertain",
                                        "note": "api_error"})
                    return results  # non-transient, stop immediately

                elif is_daily_limit:
                    print(f"  Batch {batch_idx + 1}: daily limit reached -- stopping.")
                    print(f"  Switch to next provider with --resume, or resume tomorrow.")
                    for cid in expected_ids:
                        results.append({"id": cid, "classification": "uncertain",
                                        "note": "api_error"})
                    return results  # early exit, not transient

                elif is_rate_limit:
                    wait = min(60.0 * (2 ** (attempt - 1)), 300.0)
                    print(f"  Batch {batch_idx + 1}: rate limit [{err[:120]}] -- waiting {wait:.0f}s (attempt {attempt})")
                    time.sleep(wait)
                    continue

                elif attempt < 3:
                    print(f"  Batch {batch_idx + 1}: error ({exc!r}) -- retrying in 10s")
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


# ---------------------------------------------------------------------------
# run() and main()
# ---------------------------------------------------------------------------

def run(
    provider_name: str,
    base_url: str,
    api_key_env: str,
    model: str,
    input_path: Path,
    out_path: Path,
    batch_size: int,
    rpm: int,
    resume: bool,
) -> None:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("ERROR: openai not installed. Run: pip install openai")
        sys.exit(1)

    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        print(f"ERROR: {api_key_env} environment variable not set.")
        preset = PROVIDERS.get(provider_name, {})
        if "notes" in preset:
            print(f"  Setup: {preset['notes']}")
        sys.exit(1)
    # Defensive strip: setx on Windows can store leading/trailing % signs when
    # the user types  setx KEY=%value%  in cmd.exe (% is variable expansion).
    api_key = api_key.strip("%")

    # Substitute any {ENV_VAR} placeholders in base_url (e.g. Cloudflare account ID)
    import re as _re
    for placeholder in _re.findall(r"\{(\w+)\}", base_url):
        value = os.environ.get(placeholder, "").strip("%")
        if not value:
            print(f"ERROR: {placeholder} environment variable not set (needed for base URL).")
            print(f"  Set it with: setx {placeholder} <your value>")
            sys.exit(1)
        base_url = base_url.replace(f"{{{placeholder}}}", value)

    client = OpenAI(base_url=base_url, api_key=api_key)

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

    new_results = classify_all(
        candidates, client, model, batch_size, rpm, already_done, provider_name
    )
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
            "classifier": f"{provider_name}/{model}",
            "total": len(all_classifications),
            "summary": dict(counts),
            "classifications": all_classifications,
        }, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Written: {out_path}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Classify OCR candidates via any OpenAI-compatible API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(
            f"  {name:12s}: {preset['notes']}"
            for name, preset in PROVIDERS.items()
        ),
    )
    p.add_argument("--provider", choices=list(PROVIDERS), default=None,
                   help="Provider preset (loads base-url, model, api-key-env defaults)")
    p.add_argument("--base-url", default=None,
                   help="API base URL (overrides provider preset)")
    p.add_argument("--model", default=None,
                   help="Model ID (overrides provider preset)")
    p.add_argument("--api-key-env", default=None,
                   help="Env var name for the API key (overrides provider preset)")
    p.add_argument("--input", required=True,
                   help="annotated_candidates.json from preflight_rules.py")
    p.add_argument("--out", required=True,
                   help="Output path for classifications JSON.")
    p.add_argument("--batch-size", type=int, default=20,
                   help="Candidates per API call (default: 20)")
    p.add_argument("--rpm", type=int, default=None,
                   help="Max requests per minute (defaults to provider preset, or 10)")
    p.add_argument("--resume", action="store_true",
                   help="Skip already-classified IDs; retry api_error entries from previous run.")
    args = p.parse_args()

    # Resolve provider preset vs explicit overrides
    preset = PROVIDERS.get(args.provider or "", {})
    base_url = args.base_url or preset.get("base_url")
    model = args.model or preset.get("model")
    api_key_env = args.api_key_env or preset.get("api_key_env")
    rpm = args.rpm if args.rpm is not None else preset.get("rpm", 10)
    provider_name = args.provider or "custom"

    if not base_url:
        p.error("--base-url required when not using --provider")
    if not model:
        p.error("--model required when not using --provider")
    if not api_key_env:
        p.error("--api-key-env required when not using --provider")

    run(
        provider_name=provider_name,
        base_url=base_url,
        api_key_env=api_key_env,
        model=model,
        input_path=Path(args.input),
        out_path=Path(args.out),
        batch_size=args.batch_size,
        rpm=rpm,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
