# OCR Pipeline — Architecture Reframe and Design Exploration

**Status: EXPLORATION / DECISION PENDING. Not adopted.** This document records a from-the-ground-up rethink of the reconciliation pipeline plus two independent designs. The choice between them is deliberately deferred to a measurement (the 10-page run); nothing here changes the build until those numbers land.

**Companion docs:** `docs/OCR_RESEARCH_SYNTHESIS_2026-05-31.md` (the research this rests on); `prompts/codex-10page-measurement-reconciled.md` (the experiment that resolves the open decision).

---

## 1. The reframe

The built pipeline (B0–B17) answers a 2015-era question: *how do we vote N weak, correlated OCR engines into truth?* That produced the Beta-Binomial reliability matrix, calibration gates, family-independence measurement, and confusion-weighted N-way voting.

A from-the-ground-up look says that may be the wrong frame for this specific work. The New Schaff-Herzog is ~95% clean Roman-type English prose that strong modern engines (Surya, Kraken) recover at low CER on a first pass. The hard parts are narrow: layout/reading order, the Greek/Hebrew snippets, proper names and theological terms, and the rare error hiding inside otherwise-clean text.

That makes this fundamentally a **verification-and-triage problem, not a reconciliation problem.** The reframe, stated once:

> **Optimize the review queue, not the reliability model. Expert reviewer time is the scarce resource and the real cost of the project. Every component should serve making the queue as small and as well-ranked as possible.**

This is the one principle held with high confidence. Everything below is downstream of it.

## 2. Two independent designs

Two architects designed from the same brief and research with no access to each other's work (the cross-architect pattern). One is this system's lead design; the other is an independent GPT-5.5 pass.

**Design 1 — Two-signal escalator (minimal).** Establish one strong baseline draft (a human transcription if it proves faithful, else the single best OCR per region). Run one genuinely-independent second signal whose only job is to disagree. Agreement → auto-accept. Disagreement, plus all non-Latin and low-confidence spans → escalate to the review queue. The system-wide auto-accept error rate is measured once on a gold sample, not modeled per token. Most matrix machinery is deleted.

**Design 2 — Calibrated fan (independent GPT-5.5 design).** Run engines by role (existing ABBYY as cheap evidence, Surya for layout, Tesseract as an independent baseline, Kraken+Ciaconna for Greek, a Hebrew lane on demand, cloud OCR on exception). Keep confidence-weighted character-level reconciliation, but only after per-engine calibration, with engine families as voters and same-wrong-string independence measured on gold. Per-page primary-image selection by measured scan quality. An explicit active-learning feedback loop.

### Where they converged (independently)

| Question | Both designs agree |
|---|---|
| Problem type | Verification / reviewer-minimization, not pure OCR |
| The pivot decision | Whether the existing human transcription is faithful to this edition |
| PAGE XML | Interchange / evaluation format, not the internal canonical format |
| LLM/VLM role | Flag and rank evidence; never author canonical text |
| Layout | First-class truth; reading-order error must be tracked (invisible to CER) |
| Hebrew | Route all spans to review; no specialist model yet |
| Review queue | Ranked by uncertainty; reviewers adjudicate spans, never proofread pages |

Independent convergence on the reframe is the strongest available signal that the built architecture is heavier than this problem requires.

### Where they genuinely disagree

1. **The reconciliation matrix** — Design 2 keeps confidence-weighted reconciliation + calibration; Design 1 deletes it for agree→accept / disagree→escalate.
2. **Family independence** — Design 2 measures it live on gold; Design 1 engineers it in by choosing one independent second signal.
3. **Signal count** — Design 2 runs a broad calibrated fan; Design 1 runs two signals.

These three are not independent. They all reduce to one empirical question: **how good is the single best baseline?** If one engine (or a faithful human transcription) is near-clean, two signals suffice and the matrix is dead weight. If the best single baseline is mediocre, the calibrated fan earns its place. Neither architect can answer that without real data scored against ground truth — which the project has never had until now.

## 3. What the gold text changes

A full human-proofread digital text of the encyclopedia is now (believed) available, alongside the CCEL transcription. The critical distinction:

> **It is an evaluation oracle, not a production input.** It does not change what the build does; it changes what we can know about it. It does not get published — the public deliverable is independently-attested, image-verified text, and the gold's fidelity to the 1908–1914 edition is unverified. But it turns every contested assumption into a measurement.

Caveat that both the architecture work and the execution session independently hit: **agreement cannot be graded against the source that produced it.** Where the engines and the human text agree, that is not an independent measurement. The non-circular signal comes only from human adjudication of the *disagreements* against the page image. That adjudicated-disagreement set is simultaneously the embargo-lifting measurement and the well-ranked review queue. The two goals are the same artifact.

## 4. Is the matrix machinery useless? No — conditional and prematurely built

An honest accounting of what survives a rebuild and what is on the bubble:

| Machinery | Verdict | Reason |
|---|---|---|
| Alignment before truth choice | Survives, always | Locked constraint; every design needs it |
| Family-independence measurement | Survives | Both designs need to know which signals are correlated |
| Gold-sample error measurement | Survives, becomes central | Sets the escalation threshold |
| Provenance / decision store / public-slim-private-audit split | Survives — the real innovation | Token-level auditable provenance on top of the standard stack |
| Beta-Binomial per-cell posteriors | On the bubble | Needed only if combining many calibrated signals |
| Confusion-weighted N-way voting | On the bubble | Alignment survives; the N-way vote is conditional on the fan |
| Calibration / promotion gates | On the bubble | Needed only if the matrix is needed |

The original mistake was not wrong machinery. It was two things: building it before measuring whether single-baseline quality demanded it, and building it to *decide each token* when its real value is *measuring the system*. The reframe demotes the matrix from the spine to a conditional branch; it does not throw it away.

## 5. Relationship to the standard stack (OCR-D, eScriptorium, PAGE XML)

The build genuinely extends the standard historical-OCR stack rather than reinventing it. OCR-D is a recognition pipeline (one engine's output is the result); this is a reconciliation pipeline with token-level provenance, an auditable decision store, and a public/audit split that the standard stack has no equivalent for. eScriptorium is the right tool for gold annotation and likely the right basis for the reviewer UI (it already shows image-crop-alongside-line-text, which is what the deferred reviewer work needs). PAGE XML belongs at the import/evaluation boundary — a thin export from the S1 layer would unlock eScriptorium, dinglehopper, and external GT comparison without disturbing the reconciliation core.

## 6. The decision and how it resolves

No rebuild-vs-keep-vs-fork decision is made here. The sequence:

1. **Verify the gold asset** — edition, completeness, fidelity of both the digital text and CCEL; what is authoritative vs proposal.
2. **The 10-page instrumented run** (`prompts/codex-10page-measurement-reconciled.md`) — drives the existing chain on ~10 real pages spanning the failure surface, and measures: single-best-baseline CER (M0), per-engine confidence calibration (M1), auto-accept error rate (M2), and matrix-vs-agree→escalate truth-rule A/B (M3), plus the adjudication queue.
3. **Read the numbers, then decide.** If single-baseline quality is high and confidence is calibrated → demote the matrix to a documented fallback and ship the simpler spine. If not → the calibrated fan earned its place; keep it. A clean rebuild around the verification spine is only justified later, on operability grounds, and only after the numbers show the simple design holds quality.

The execution work that drove the first real page is not wasted under either outcome: it proved the chain *runs* on real data and built the harness that lets us test whether the machinery is *necessary*. "Runs" and "is necessary" are different claims; the 10-page run separates them.

---

*Decision pending the 10-page measurement. Update this document with the verdict once those numbers land.*
