# ADR-0013: Reconcile scoring rubric, thresholds, edge combination, and N=2 tie-breaker (v1 draft)

**Status:** Accepted (2026-05-16) — v1 draft; calibration revisited against golden fixtures during Phase 1 and Phase 2; amended 2026-05-16 with canonical `bucket` enum, `action` enum, and per-block-type `surface` policy (reconciliation walkthrough verification V2).

## Context

Reconcile aligns N renderings of one edition per work into a single reconciled record. Two distinct scoring concerns exist:

1. **Block-pair matching.** Whether two parsed blocks from different renderings represent the same block in the edition. Drives clustering: do these blocks merge into one canonical block?
2. **Reading scoring.** Within a cluster, when renderings disagree on the text of a span, which reading is chosen? Drives auto-resolution vs Reviewer surfacing.

Plan v1 (Claude's plan) left both as composite formulas with "equal initial weights, refined empirically" — under-specified to the point that an implementer would invent the actual decision boundary during implementation. Plan v2 (Codex's plan) proposed an explainable 100-point breakdown for the block-pair score with named components and concrete thresholds, plus a weighted reading-scoring scheme.

The architectural questions surfaced during the cross-architect reconciliation walkthrough (item R4):

- **(a) Scoring rubric.** Codex's named-component 100-point breakdown, or Claude's α/β/γ/δ/ε formulation?
- **(b) Thresholds.** Four-bucket score-band gradient (`high` / `mid_high` / `mid_low` / `low`) with concrete cutoffs, action enum, and per-block-type surface policy — or undefined?
- **(c) Edge combination.** When the same node pair gets edges from multiple signal sources, do scores combine by **max** (use strongest signal only), **sum-capped-at-100** (additive but bounded), or **weighted union into one edge** (each signal contributes its slice of the 100-point total)?
- **(d) N=2 structural tie-breaker.** When exactly two renderings disagree structurally (Phase 1's Schaff-Herzog fan-in), the 2-of-N rule degenerates to 1-vs-1 ties on every split/merge. What wins?

ADR-0002 (within-edition only) frames disagreements as denoising — supports auto-resolution when signals are strong. ADR-0008 (built once) requires the chosen algorithm ships in Phase 1, not "calibrate later as a deferred capability." Calibration of weights and thresholds is the "quality grows over time" pattern (ADR-0008's accepted framing); the algorithm's structure is the locked thing.

## Decision

### (a) Block-pair scoring — explainable 100-point breakdown

| Signal | Max points | Notes |
|---|---|---|
| `annotation_key` | 30 (exact); 18 (compatible partial key) | Same verse ref, same headword, same date, same section path |
| `text_similarity` | up to 25 | Token alignment ratio after alignment-only normalisation |
| `source_order` | up to 15 | Monotonic order + expected local neighbourhood |
| `block_type` | 10 (exact); 5 (compatible heading/headword or paragraph/comment) | Type compatibility, not equality |
| `page_proximity` | up to 10 | Same or adjacent page where page data exists |
| `language_profile` | up to 5 | Compatible dominant language and script |
| `ocr_skeleton` | up to 5 | Close skeleton match where raw text differs |
| **Total cap** | **100** | |

Each per-signal score is capped at its column maximum. A signal with no data contributes 0 (not absent; explicitly zero, recorded for explainability).

### (b) Block-pair thresholds — four buckets

| Score range | Bucket | Action |
|---|---|---|
| `≥78` | `high` | `cluster` |
| `60–77` | `mid_high` | `cluster` |
| `45–59` | `mid_low` | `no_cluster` (emit `structural_disagreement` record) |
| `<45` | `low` | `no_edge` |

`bucket` is a **score-band classifier**, not an emitted action. Action and surface policy are separate concerns recorded in their own fields (below).

**Action enum** (`cluster` | `no_cluster` | `no_edge`): the structural outcome at scoring time. `cluster` means the two blocks merge into one canonical block; `no_cluster` means the candidate structural disagreement is emitted into `structural_disagreements[]` for Reviewer adjudication; `no_edge` means no relationship is recorded between the two parsed-block nodes.

**Surface enum** (`required` | `silent` | `none`): whether the decision is visible to the Reviewer. `required` means an entry is rendered in the Reviewer UI's pending-queue; `silent` means an audit-log entry is written but no Reviewer surface; `none` means no audit-log entry (the `<45` case has nothing to record).

**Per-block-type surface policy for `mid_high` (60–77) cluster decisions:**

| Block type | Surface |
|---|---|
| `headword` | `required` |
| `lemma` | `required` |
| `heading` | `required` |
| `verse_line` | `required` |
| `table_row` | `required` |
| `list_item` | `required` |
| `footnote` | `required` |
| `quote` | `required` |
| `paragraph` | `silent` |
| any future block-type added without explicit policy | `required` (fail-safe default) |

The fail-safe default exists because Reviewer fatigue is visible and recoverable; silent mis-clustering is harder to discover after the fact.

**Surface policy for the other three buckets:**

- `high` → `silent` (audit-log entry; no Reviewer surface — auto-cluster is the expected high-confidence path).
- `mid_low` → `required` (the candidate structural disagreement is emitted; Reviewer must adjudicate).
- `low` → `none` (no audit-log entry; nothing to surface).

### (c) Edge combination — weighted union into one edge

When the same parsed-block node pair receives signal from multiple sources, **the per-signal contributions sum into one weighted edge with one final score** (capped at 100). This is the natural reading of the 100-point breakdown: each signal contributes its slice when present and zero when absent. There is no "max" tie-break and no "sum-without-cap" runaway.

Concretely: `final_score(a, b) = min(100, sum_over_signals(score_per_signal(a, b)))`.

The combination rule preserves explainability — every clustering decision can be traced back to which signals contributed which points. The Reviewer UI shows the breakdown alongside the final score for any block-pair the Reviewer audits.

### (d) N=2 structural tie-breaker — anchor wins; attestor divergence becomes a structural disagreement

When exactly two renderings exist and they disagree structurally (one has a heading the other doesn't; one merges two blocks the other splits), the `pd_anchor` rendering's structure is canonical. The attestor's divergence is written as a `structural_disagreement` record on the affected block and surfaces to Reviewer for adjudication. Reconcile does not silently merge or split based on the attestor's structure at N=2.

This rule is a degenerate case of the 2-of-N rule (where N≥3, two-out-of-N renderings determine the structural element). At N=2 the rule degrades to "anchor wins by default; attestor disagreement still surfaces." The Reviewer can then accept the anchor's structure, accept the attestor's structure, or pick a different resolution via the structural-disagreement affordance.

At N≥3 the 2-of-N rule applies as written in the plan: ≥2 renderings agree → kept; exactly 1 has it → suspect / surface.

### Reading scoring — Codex's weighted scheme

Within a clustered block where renderings disagree on a token span, **per-reading scores** drive auto-choice vs Reviewer surfacing. Adopted from Codex's plan:

| Rendering role | Base score for a reading from that rendering |
|---|---|
| `pd_anchor` | 4.0 |
| `pd_attestor` | 3.0 |
| our-own-OCR with PD source (role `pending`) | 2.0 |
| `reference_only` | 0.0 for PD-gate purposes; advisory only |

Modifiers applied to each reading's score:

| Modifier | Effect |
|---|---|
| Reading is lexicon-valid for the detected language; competitor is not | `+1.0` |
| Reading preserves expected punctuation / capitalisation per the anchor's style (operationalised below — R25) | `+0.75` |
| Reading matches a known OCR confusion pattern in the per-language OCR error model | `−1.5` |
| Reading creates invalid Unicode / broken ligatures / replacement characters / impossible mixed script | `−2.0` |
| **Advisory:** reference-only rendering agrees with reading | **`+0.5` — applied to a separate `advisory_score` field only; does not enter the auto-choice gap calculation (see R5)** |

Auto-choice is allowed only when:

1. The winning reading has public-domain support (at least one `pd_anchor` or `pd_attestor` in the reading's attestation), and
2. The winning **PD-only score** (ignoring advisory bonus) is at least 2.0 higher than the runner-up's PD-only score, and
3. The disagreement classification is not `paraphrase` or `unclassified`.

Otherwise the block surfaces to Reviewer with the score breakdown visible.

### Anchor-style operationalisation for the `+0.75` modifier (R25)

"Expected punctuation / capitalisation per the anchor's style" is registered as a per-work-edition style profile, sampled from the anchor at Reconcile setup. Concrete rule:

1. **Sample.** Sample 10% of anchor blocks (or 200 blocks, whichever is greater) stratified by `block_type` so each block type contributes proportionally.
2. **Register conventions.** For each candidate convention (Oxford comma in list-blocks; sentence-initial capital after colon in heading-blocks; period vs no-period at the end of headings; double-quote vs single-quote style; em-dash vs en-dash; spaced-vs-unspaced em-dash), measure consistency. A convention registers iff it appears in **≥95%** of the sampled blocks where it could appear.
3. **Apply modifier.** During reading scoring, a reading earns `+0.75` iff the reading matches the registered convention at the span where the convention applies; a reading that violates the registered convention earns `0` for this modifier (not negative — the modifier is a bonus, not a penalty).
4. **No registered convention → no modifier.** If sampling didn't surface a confident convention (consistency below 95%), the `+0.75` modifier does not fire for that span; the reading is scored without it.

The per-work-edition style profile is written to `catalog.json` under a new `anchor_style` field (`{convention_name: registered}`), regenerated whenever the anchor changes (re-Reconcile triggers re-sample). Section 8 fixture: `test_r25_punctuation_modifier_requires_anchor_style_threshold` — synthetic fixture where the anchor uses Oxford comma in 96% of list-blocks; a reading without Oxford comma at a list-block span earns 0 for the punctuation modifier; with Oxford comma earns `+0.75`. A second fixture with 80% consistency proves the modifier does not fire when consistency falls below the 95% threshold.

The rule is intentionally less brittle than "exact span match against anchor" — it rewards reading-edition-consistent normalisation rather than mechanical mimicry of an OCR-noisy anchor rendering. It is also implementable from the catalog alone (no global style guide; no hand-curated convention list).

### Calibration mechanism

This is **v1 draft**. The weights, thresholds, and modifier values above are hand-tuned priors. They will be revisited as golden fixtures grow:

- **Phase 1 calibration gate.** Before Schaff-Herzog Reviewer-clean status is claimed, run Reconcile across the 13 volumes and tabulate: how many block pairs land in each bucket (`high` / `mid_high` / `mid_low` / `low`); how many `high`-bucket auto-clusters were later overridden by Reviewer; how many `mid_low`-bucket structural disagreements resolved which way. The bucket boundaries and the modifier weights are reviewed against this distribution.
- **Phase 2 calibration gate.** Repeat with cross-type fixtures (commentary, patristic, devotional, confession, structured prose). Different resource types may surface different distributions; weights stay shared unless evidence forces a per-language or per-resource-type adjustment.
- **Golden fixtures grow with every Reviewer session.** Each Reviewer-confirmed clustering decision (auto-cluster correct, manual override, structural resolution) becomes a labelled training point. Future weight revisions cite the fixture distribution that motivated them.

### Pattern from adjacent fields

The decision shape borrows from solved problems in:

- **Bioinformatics** multi-sequence alignment (ClustalW, MUSCLE, MAFFT) — progressive alignment + substitution matrices, weights tuned against known homologous families.
- **Textual criticism** (CollateX, Juxta) — anchor on agreement, hand-tuned defaults per corpus.
- **Record linkage** (Fellegi-Sunter) — per-field log-likelihood scores, dual thresholds (definite / clerical-review / definite-not), calibrated against a labelled training set.
- **OCR ensemble voting** — weighted majority voting with per-engine accuracy weights.

The OCD approach is a textual-criticism + record-linkage hybrid with the explicit calibration mechanism above.

### Explainability ledger — `match_explanations` schema contract

Every Reconcile match decision (block-pair edge, reading-score disagreement, structural rule application) writes one entry into the per-record `match_explanations` array. The array is the explainability substrate for the calibration gate, the Reviewer UI score-detail panel, and audit-log replays.

Entry shape:

```json
{
  "match_explanation_id": "mx_a1b2c3d4",
  "scope": "block_pair_edge" | "disagreement" | "structural_disagreement",
  "block_id": "b_0042",            // when scope ≠ block_pair_edge
  "block_id_pair": ["b_0042", "b_0099"],  // when scope == block_pair_edge
  "signals": [{ "name": "...", "raw_score": 0.92, "weight": 25, "contribution": 23 }, ...],
  "total_score": 96,
  "decision": { ...per-scope shape... }
}
```

`decision` is a discriminated union keyed on `decision.kind`. The kind is required, even where it currently maps 1:1 with `scope`, so the schema admits future sub-kinds (e.g., a second disagreement decision-shape) without reshaping the parent ledger.

Per-scope `decision` shapes:

```json
// scope: block_pair_edge
"decision": {
  "kind": "edge_match",
  "bucket": "mid_high",
  "score_range": "60-77",
  "action": "cluster",
  "surface": "required",
  "surface_reason": "footnote"   // free-text rationale (typically block-type)
}

// scope: disagreement
"decision": {
  "kind": "reading_score",
  "pd_only_gap": 2.4,
  "winning_has_pd_support": true,
  "classification": "ocr_noise",
  "advisory_score": 0.0
}

// scope: structural_disagreement
"decision": {
  "kind": "structural_rule",
  "surface": "required"
}
```

`decision.kind` enum: `edge_match` | `reading_score` | `structural_rule`. The JSON-schema for `match_explanations[]` enforces the scope→kind mapping via `oneOf`. A schema-validation test in Section 8 (Test strategy) covers the discriminated union.

The explanation records the **inputs** to the decision; the **outputs** live on their own record types (disagreement records carry the chosen reading and `resolution.kind`; structural disagreements carry the `kind` enum and rule applied). The two are linked by `match_explanation_id` on the output record. This separation prevents the same fact from drifting in two places.

## Consequences

**Positive**
- Reconcile is implementable from this ADR alone. The scoring rubric, thresholds, combination rule, and N=2 tie-breaker are concrete enough to ship in Phase 1.
- Every clustering and reading decision is explainable — the per-signal breakdown survives into the Reviewer UI and the audit log.
- Calibration is part of the architecture, not a deferred capability. ADR-0008 is satisfied: the calibration mechanism exists from day one; weights improve as fixtures grow.
- The N=2 case (Schaff-Herzog Phase 1) is well-defined: anchor wins by default; attestor disagreement surfaces via the existing structural-disagreement machinery rather than a new mechanism.
- Reference-only signal leak (R5) is closed structurally: advisory bonuses go to a separate `advisory_score` field, never the PD-only gap calculation.

**Negative**
- The 100-point breakdown is a v1 prior. Phase 1 calibration may reshape it materially. Anyone reading code mid-Phase-1 will see weight values that may not match the ADR-published ones; the ADR is updated when calibration motivates revision.
- Anchor-wins-at-N=2 means the PD-anchor choice is structurally consequential. A wrong anchor choice produces structurally wrong reconciliations until Reviewer adjudicates. Mitigated by surfacing every N=2 structural disagreement; not eliminated.
- The 60–77 silent-cluster case for plain paragraphs is a genuine residual Reviewer-blind spot. Phase 1 audit-log monitoring (proportion of 60–77 silent clusters; subsequent Reviewer overrides via re-reconcile) is the only check.

## Alternatives considered

- **Claude's α/β/γ/δ/ε equal-weights formulation.** Rejected. Hides the components inside Greek letters; weight choices become invisible; refining weights becomes a code change rather than a data change.
- **Max combination rule** (use the strongest single signal). Considered. Rejected because it loses signal: a node pair with strong text similarity (25/25) AND same page (10/10) is a better match than one with only text similarity at 25. Max would treat them as equivalent.
- **Sum-without-cap combination.** Rejected. Lets enough weak signals pile up to fake a strong match.
- **Always-Reviewer at N=2** (no auto-resolution; every disagreement surfaces). Considered. Rejected because Schaff-Herzog has ~13 volumes × thousands of blocks; if every N=2 structural disagreement requires Reviewer touch, Phase 1 throughput collapses. The anchor-wins default with a structural-disagreement record gives Reconcile a deterministic default; the Reviewer still sees it and can override.
- **Per-language weight tables.** Considered. Deferred until Phase 1 calibration shows whether a single weight table works across `en`, `la`, `grc`, `hbo` (the Phase 1 active languages). If evidence forces per-language weights, this ADR is amended; default remains shared.
- **Reference-only readings as advisory `+0.5` to the main score.** Codex's plan made this. Rejected (R5): bonus moves to a separate `advisory_score` field so it never tips the 2.0 PD-only auto-choice gap.
