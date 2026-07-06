# OCR Scanner — Future Directions

*Captured 2026-04-28 after first full LLM triage run (5,059 candidates, NVIDIA Llama 3.3 70B)*

---

## How does the classifier actually decide?

The LLM classifier is doing **zero-shot judgment** — not dictionary lookup, not corpus comparison.

Each candidate gets:
- The token value (e.g. `THE0T0K08`)
- The reason type (e.g. `digit_in_letter`)
- A rule-based suggestion (e.g. `THEOTOKOS`)
- Up to 60 chars of surrounding text before and after
- The entry ID and field (e.g. term vs. content)

The model applies its training knowledge about OCR error patterns in 19th-century
German theological scans. It does NOT consult a dictionary, does NOT compare to other
instances of the same word in the corpus, does NOT have access to the full document.

For `digit_in_letter`, this works very well: the digit-substitution patterns (0→O,
1→l/i, 5→S, 8→s/S) are mechanical and the model recognises them reliably.
For `short_allcaps_orphan`, it's harder: the model has to judge whether a short
all-caps token is a plausible theological abbreviation (JE, MPL, ZKG) or garbled text.
This is where most of the 53 "still uncertain" cases landed.

**What we could do instead / additionally:**
- **Corpus comparison**: check whether the same token appears elsewhere in the
  Schaff-Herzog entries with a different form. If `THE0T0K08` appears in 3 entries
  but `THEOTOKOS` appears in 50, that's strong signal.
- **Dictionary lookup**: a custom theological dictionary (or whitelist) for the
  Schaff-Herzog domain — NPNF index terms, place names, theologian names, Hebrew
  transliterations, etc.

---

## Dual check at the initial scan stage

The preflight_rules.py scan that generates the 5,059 candidates is purely rule-based
(regex patterns, digit-substitution tables, etc.). There's no LLM check at that stage —
the LLM only runs in the triage phase.

**The gap**: the scan could be flagging things it shouldn't (false positives in the rules
themselves) AND missing things it should flag (patterns the rules don't cover). An LLM
at the scan stage could catch both.

**Proposed: dual-check at scan**
- Run preflight_rules.py as now → rule-annotated candidates
- Spot-check a sample (e.g. 100 random entries NOT flagged) with the LLM to check
  for missed errors → validates scan recall
- The LLM triage already provides precision feedback (2,343 of 5,059 = 46% were
  false positives) — that's a recall problem in the rules that could be tightened

**Is this necessary hardening or overkill?**
For the current corpus size (~270K entries), the existing pipeline (scan → LLM triage)
is probably adequate. The 46% false positive rate in the rule flagging is high but
acceptable since the LLM handles it cheaply. Worth revisiting if corpus grows to 1M+.

---

## Confidence percentages — useful or noise?

Self-reported LLM confidence percentages are performative noise. When asked
"how confident are you?", the model gives a calibrated-sounding number that doesn't
reliably map to accuracy differences. 73% vs 68% from Llama 3.3 70B means nothing.

**What actually carries signal:**
1. **The 3-label system** (`uncertain` = low confidence) — enforced by the prompt,
   not self-reported. The model explicitly signals "I genuinely can't tell."
2. **Multi-model agreement** — if NVIDIA and Gemini independently agree, that's
   empirical confidence, not performative. We already use this (Gemini reviews
   `uncertain` cases).

**A better confidence approach (future):** Run two providers on every candidate,
surface only disagreements for human review. Disagreement is a non-performative
signal. The merged pipeline would be:
```
Provider A classifies all → Provider B classifies all → disagreements → human
```
This increases cost (~2x API calls) but gives you a genuine quality gate on the
approved corrections. Worth it once the corpus size warrants it.

---

## Ensemble re-OCR of error sections

Rather than re-OCRing the whole source, re-OCR only the specific page regions
containing confirmed errors.

**Approach:**
1. For each approved error correction, look up its source page + bounding box
   from the original djvu/scan
2. Extract just that text region as an image
3. Run 2-3 OCR engines (Tesseract, EasyOCR, Mistral Vision) on that region
4. If 2/3 agree on a reading that differs from the current text → high-confidence fix
5. If they disagree → flag for human review

**Where this beats the current approach:**
- The current pipeline can only apply corrections where the rule-based suggester
  found a plausible fix (790 of 2,663 errors had a suggestion). The remaining
  1,873 errors are confirmed bad but we don't know what they should be.
- Ensemble re-OCR on those 1,873 regions would generate new candidate corrections.
- Cross-verification means we're not trusting a single OCR engine's reread.

**Complexity:** Requires bounding box metadata from the original scan ingestion
(not currently stored). Would need to re-run the djvu extraction with coordinate
capture. Medium-term project.

---

## Project map — where OCR scanner fits

```
OCD corpus build (build/parsers/)
    ↓
Raw JSON in data/
    ↓
OCR scanner (build/tools/ocr_scanner/)
    ├── scan_report.json  ← flags suspicious tokens in committed JSON
    ├── preflight_rules.py  ← annotates candidates with rule hints
    └── llm_triage/
        ├── openai_compat_classifier.py  ← primary (NVIDIA/Cerebras/Mistral)
        ├── gemini_classifier.py  ← second opinion on uncertain cases
        ├── merge_decisions.py  ← combines outputs
        └── human_review.csv  ← remaining cases for manual review
    ↓
corrections/schaff-herzog.json  ← approved corrections table
    ↓
apply_approved_corrections.py  ← writes corrections to corpus
    ↓
HuggingFace publish (build/tools/hf_publish/)
```

The OCR scanner sits between raw corpus and HuggingFace publish. It's a quality
gate specifically for OCR corruption — it doesn't validate schema (that's CI/JSON
Schema) or content accuracy (that's human editorial work). Its job is narrow:
catch mechanical OCR errors before they propagate to the public dataset.

**Current state (2026-04-28):**
- Schaff-Herzog: 792 corrections in table; 1,926 candidates in human_review.csv
- No other sources have been scanned yet
- The pipeline is source-agnostic (source_id drives the corrections file name)
- Next source to scan: likely whichever corpus gets published next
