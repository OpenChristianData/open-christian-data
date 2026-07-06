# OCR LLM Triage Pipeline

Reduces 5,000+ OCR candidates to a manageable human-review queue using
Groq + GitHub Models (Llama 3.3 70B) as primary classifiers, combined daily for
maximum free-tier throughput, with Gemini 2.5 Flash as a backup for uncertain cases.

## Pipeline overview

```
scan report JSON
      |
      v
preflight_rules.py          -- annotates each candidate with a rule hint (not a final decision)
      |
      v
annotated_candidates.json
      |
      v
groq_classifier.py          -- Llama 3.3 70B via Groq, ~1,300 candidates/day
      |  (--resume)
github_classifier.py        -- Llama 3.3 70B via GitHub Models, ~1,000 more candidates/day
      |
      v                       Combined: ~2,300 candidates/day -> done in ~2-3 days
hf_classifications.json     (both classifiers write to the same file via --resume)
      |
      +-- uncertain cases
      |         |
      |         v
      |   gemini_classifier.py   -- Gemini 2.5 Flash second-opinion on uncertain cases
      |         |
      |         v
      |   gemini_classifications.json
      |
      v
merge_decisions.py          -- combines all outputs
      |
      +-- merged_approved.json    -> apply_approved_corrections.py (corrections table)
      +-- suggested_whitelist.txt -> review and add to schaff-herzog.json whitelist_terms
      +-- human_review.csv        -> human reviews remaining uncertain cases
```

## Setup

```
pip install groq openai google-generativeai
```

Get API keys:
- Groq: https://console.groq.com/keys (free, rate-limited)
- GitHub: https://github.com/settings/tokens (PAT with models:read scope)
- Gemini: https://aistudio.google.com/ (free tier, use GEMINI_API_KEY)

Set environment variables:
```
set GROQ_API_KEY=gsk_...
set GITHUB_TOKEN=github_pat_...
set GEMINI_API_KEY=AIza...
```

## Step-by-step run

### 1. Annotate with rule hints
```
py -3 build/tools/ocr_scanner/llm_triage/preflight_rules.py ^
    --scan-report build/tools/ocr_scanner/reports/schaff-herzog_2026-04-23.json ^
    --out build/tools/ocr_scanner/llm_triage/annotated_candidates.json
```

### 2. Primary classification — chain providers until all candidates are classified

Each provider writes to the same output file. `--resume` skips already-done IDs automatically.
Run them in order until `hf_classifications.json` has no `api_error` entries remaining.

**Step 2a: Cerebras** — try this first. 14,400 RPD / 1M TPD → may finish everything in ~10 min.
```
py -3 build/tools/ocr_scanner/llm_triage/openai_compat_classifier.py ^
    --provider cerebras ^
    --input build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --out   build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --resume
```
Signup: https://cloud.cerebras.ai/ (free, email only, no CC)
Key env var: `CEREBRAS_API_KEY`

**Step 2b: NVIDIA NIM** — actual Llama 3.3 70B, ~40 RPM, no published daily cap.
```
py -3 build/tools/ocr_scanner/llm_triage/openai_compat_classifier.py ^
    --provider nvidia ^
    --input build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --out   build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --resume
```
Signup: https://build.nvidia.com/ (free, phone verify). Accept model ToS for llama-3.3-70b-instruct.
Key env var: `NVIDIA_NIM_API_KEY`

**Step 2c: Groq** — Llama 3.3 70B, 1K RPD / 100K TPD
```
py -3 build/tools/ocr_scanner/llm_triage/groq_classifier.py ^
    --input build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --out   build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --rpm 5 ^
    --resume
```
Key env var: `GROQ_API_KEY`

**Step 2d: Mistral** — Mistral Large, 60 RPM, 1B tokens/month. Note: prompts may train Mistral.
```
py -3 build/tools/ocr_scanner/llm_triage/openai_compat_classifier.py ^
    --provider mistral ^
    --input build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --out   build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --resume
```
Key env var: `MISTRAL_API_KEY`

**Step 2e: GitHub Models** — 50 RPD, last resort
```
py -3 build/tools/ocr_scanner/llm_triage/openai_compat_classifier.py ^
    --provider github ^
    --input build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --out   build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --resume
```
Check exact model ID: https://github.com/marketplace/models -> Code tab
Key env var: `GITHUB_TOKEN` (models:read scope)

**Note:** `hf_classifier.py` and `github_classifier.py` are superseded by `openai_compat_classifier.py`
but kept for reference. `groq_classifier.py` is still needed (Groq uses its own SDK, not openai).

### 3. Gemini second opinion (uncertain cases only)
```
py -3 build/tools/ocr_scanner/llm_triage/gemini_classifier.py ^
    --groq-out  build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --annotated build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --out       build/tools/ocr_scanner/llm_triage/gemini_classifications.json ^
    --rpm 30 ^
    --resume
```

Uses `GEMINI_API_KEY` or `GOOGLE_API_KEY` env var (checks both).
Safe to interrupt and resume with `--resume` (flushes to disk every 50 classifications).
Billing-enabled key: `--rpm 30` is conservative; raise if no 429s. Free-tier key: use `--rpm 8`.

### 4. Merge into final outputs
```
py -3 build/tools/ocr_scanner/llm_triage/merge_decisions.py ^
    --annotated  build/tools/ocr_scanner/llm_triage/annotated_candidates.json ^
    --hf-out     build/tools/ocr_scanner/llm_triage/hf_classifications.json ^
    --gemini-out build/tools/ocr_scanner/llm_triage/gemini_classifications.json ^
    --approved   build/tools/ocr_scanner/llm_triage/merged_approved.json ^
    --whitelist  build/tools/ocr_scanner/llm_triage/suggested_whitelist.txt ^
    --human-csv  build/tools/ocr_scanner/llm_triage/human_review.csv
```

### 5. Apply approved corrections
```
py -3 build/tools/ocr_scanner/apply_approved_corrections.py ^
    --scan-report build/tools/ocr_scanner/reports/schaff-herzog_2026-04-23.json ^
    --approved    build/tools/ocr_scanner/llm_triage/merged_approved.json ^
    --apply
```

### 6. Human review
Open `human_review.csv` in Excel. The `approve` column is blank — fill it with `y` for
candidates you want to approve as corrections, leave blank or write `n` to skip.
Then run `apply_approved_corrections.py` with the human-reviewed file.

## Rate limits

| Provider | Model | RPM | RPD | Notes |
|---|---|---|---|---|
| HuggingFace | Llama-3.3-70B-Instruct | ~10 | credit-limited | Monthly credits exhaust; not recommended |
| Groq (free) | llama-3.3-70b-versatile | 30 RPM / 5 effective | 1K RPD / 100K TPD | TPD is binding; ~1,300 candidates/day; 4-5 days total |
| Gemini (free) | gemini-2.5-flash | 10 | 250 RPD | Backup only; use `GEMINI_API_KEY` |

**Recommended path:** Groq as primary (steps 1-2), Gemini as backup for uncertain cases (step 3).
Use `--rpm 5` for Groq to stay within TPM cap. Safe to run over multiple days with `--resume`.

## Validation results (2026-04-28)

100-candidate sample validation (seed=42, proportional by reason):
- Overall Haiku/Sonnet agreement: 48% (below 90% threshold for two-model approach)
- Per-reason findings:
  - `ligature_bracket`: 100% agreement (both not_error) — rule confirmed
  - `stray_pipe_backslash`: 100% agreement (both error) — rule confirmed
  - `digit_in_letter`: 24% agreement — Haiku overcautious; Sonnet was correct
  - `short_allcaps_orphan`: 30% agreement — genuinely ambiguous

Lesson: single capable model (Llama 3.3 70B or Sonnet) outperforms two cheap models
for this dataset. Rule hints improve confidence but are not sufficient alone.
