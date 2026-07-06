# Shared Design Brief — Gold-Free Corrector Stack

**This brief is shared identically by two independent architects (Claude and Codex) under the
cross-architect pattern (DEL-02). Each produces an independent design without reading the
other's. Do not anchor on the other design.** American English; relative paths.

## Goal

Design the gold-free unsupervised corrector stack that runs BEFORE any human adjudication —
using only multi-engine agreement and unsupervised signals (no trained weight matrix, no human
gold). The pipeline already aligns engine readings at the character level by confusion-weighted
edit distance (`build/lib/wct_builder.py`) but stops at "slot membership" and never votes within
a slot; the reconciler (`build/lib/s3_reconciler.py`) runs in degraded mode (all weights 0.0,
nothing auto-chosen). This stack adds the missing unsupervised middle.

## The five components (design each: inputs, outputs, algorithm, parameters, integration point)

- **P1 — Character-column voting.** Align candidate strings within a position character by
  character (reuse existing confusion costs), vote per column, score per-position agreement.
  Impossible-character filter (non-alphabetic glyph in alphabetic context is rejectable). Emit a
  voted reading PLUS per-character provenance (which engine families attested each character).
- **P2 — Lexicality rescore.** Score the voted reading against a domain lexicon built gold-free
  from consensus words + public-domain dictionaries + `build/lib/ocr_error_models/*.yaml`.
- **P3 — In-corpus LM rescore.** Cheap char/word n-gram model trained on the corpus's own
  high-confidence consensus text. Ranks plausibility; never authors free text.
- **P4 — Decision policy.** The canonical-text ceiling below.
- **P5 — Active-learning selection.** Rank the review residue by disagreement so a human gold
  sample is drawn from the most informative positions (Reul 2018, +16%).

## Hard requirements (identical for both designs — do not weaken)

- **HR1.** Build on the existing WCT confusion-weighted alignment; cite the functions you consume.
  Don't redesign alignment.
- **HR2. Canonical-text ceiling = levels 0-3, all built, none forbidden.** Level 0 attested
  whole-word; L1 character-voted (every char attested by >=1 engine); L2 confusion+lexicon
  correction where no engine got the char but it's a small-distance fix to a known word; L3
  LM/context-proposed. Every canonical token carries a derivation-method tag. Publication policy
  is a threshold on surrogate-measured error per method, NOT a fixed doctrine.
- **HR3. Per-character provenance.** Every canonical character traces to its evidence (engine
  attestation, confusion+lexicon rule, LM, or human). A synthesized reading stays fully auditable.
- **HR4. Real-word-error rate is a first-class metric, per level, distinct from CER.** Definition:
  output is a valid lexical word AND output != gold. Decompose every error into non-word vs
  real-word. This is the dangerous class lexical/LM filters are blind to; measure it explicitly.
- **HR5. Protected classes route to human/VLM regardless of engine agreement** — proper names,
  numbers, dates, Scripture references, Greek, Hebrew. They are the real-word-error reservoir;
  correlated engine agreement on these is not trust.
- **HR6. Validation via the Jewish Encyclopedia surrogate (non-circular), not human gold.** Per
  level: false-correction rate, coverage, real-word-error rate. Set the auto-accept threshold
  where surrogate false-correction ~ 0.1% (the 99.9% first-pass bar). Tiers above threshold are
  flagged or routed, not published unflagged.
- **HR7.** The corrector is gold-free — no dependency on human-adjudicated labels.
- **HR8.** LLM/VLM may rank, flag, or image-verify, but author canonical text only via the L3
  tagged, provenance-tracked, surrogate-measured path. No silent free-text generation.

## Deliverable

A DESIGN doc (not implementation): architecture, component interfaces, exact integration points
in the WCT/reconciler flow, the level-0-3 decision policy with parameterized thresholds, the
surrogate measurement harness (with the real-word-error metric), risks/open questions, and a
failing-first test inventory (name each test + the slot it covers; project TDD contract).

## Grounding (read before designing; cite files, don't assume)

`docs/BUILD_ROADMAP_2026-06-05.md`, `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md` (Reul 2018
character voting + active learning; Levchenko 2025 on corrector-injected real-word errors;
lexicality/profiler), `docs/PIPELINE_BUILD_STATE.md`, `build/lib/wct_builder.py`,
`build/lib/s3_reconciler.py`, `build/lib/ocr_error_models/`, and the vol_01 page_0010 WCT +
reconciled JSON on disk for the real candidate shape.
