# Free LLM Options for OCR Triage (researched 2026-04-28)

## Rate limits — corrected figures

| Provider | Model | RPD | RPM | Notes |
|---|---|---|---|---|
| **Groq** | Llama 3.3 70B | 14,400 | 30 | Genuinely free, no credit card, rate-limited only |
| **Gemini 2.5 Flash** | gemini-2.5-flash | 250 | 10 | Free tier only, EU/UK unavailable |
| **Gemini 2.5 Flash-Lite** | gemini-2.5-flash-lite | 1,000 | 15 | Lower quality than Flash |
| **NVIDIA NIM** | 100+ models | No cap | ~40 | Free with NVIDIA Developer Program signup |
| **GitHub Models** | 45+ models | Per-request | varies | Free for GitHub users, 8K input / 4K output limit |
| **Mistral** | Command family | ~1B tok/month | ~1 RPS | Free experiment plan, no credit card |
| **OpenRouter** | 35+ free models | 200 | 20 | Free tier, :free suffix models |

## Key corrections from previous assumptions
- Groq: **14,400 RPD** (not 1,000 as previously believed). Entire 5,059 candidates completable in one day.
- Gemini 2.5 Flash: **250 RPD** (not 500). Takes ~20 days for all candidates at full batch.
- HuggingFace: `~$0.10/month` free credits — these exhaust quickly. Not viable for bulk classification.

## Recommended path

**Option A — Groq primary (fastest):**
1. `wordfreq` preflight to auto-classify high-confidence `digit_in_letter` (suggestion is a known word) and all `stray_pipe_backslash` → estimated 1,500-2,000 candidates eliminated
2. Route remaining ~3,000-3,500 to Groq (Llama 3.3 70B) — completes in 1 day
3. Gemini 2.5 Flash for uncertain cases (already wired up in gemini_classifier.py)

**Option B — NVIDIA NIM (no daily cap):**
- Check model availability at https://build.nvidia.com/explore/reasoning
- If 70B model available: 253 batches × ~1.5s/req at 40 RPM = ~10 minutes total

## OCR post-correction library research findings

**Conclusion:** Nothing in the existing library ecosystem (cor-asv-ann, OCRfixr, OCHRE, CorrectOCR) is designed for candidate classification. They all target full-document correction, not binary classification of pre-flagged snippets. The custom pipeline is already best practice.

**Key papers:**
- "OCR Error Post-Correction with LLMs: No Free Lunches" (arXiv 2502.01205) — Llama 3.1 70B gives 38.7% CER reduction; GPT-4o gives 58.1%. Gap may be smaller for binary classification.
- "Multimodal LLMs for OCR in Historical Documents" (arXiv 2504.00414) — Gemini 2.5 Flash outperforms GPT-4o on 19th century German text specifically. Best free option for this domain.

## wordfreq preflight (not yet implemented)

`pip install wordfreq` — offline, gives word frequency scores.

Logic to add to preflight_rules.py:
- If `reason == "stray_pipe_backslash"` → auto `rule_hint = "error"` (100% confidence)  
- If `reason == "digit_in_letter"` AND suggestion is a known English word (wordfreq score > threshold) AND original is not → auto `rule_hint = "error"` (high confidence)

Estimated impact: 30-50% reduction in LLM calls before any API is touched.
