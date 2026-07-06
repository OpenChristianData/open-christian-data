# NSH Pipeline — Project State (Anchor Doc)

**This is the anchor document for the New Schaff-Herzog (NSH) OCR-to-publication pipeline and the
gold-free corrector stack built on top of it.** A cold session should read this instead of the
scattered set (`PROJECT_STATE.md`, `ARCHITECTURE_CONTEXT.md`, `PIPELINE_BUILD_STATE.md`,
`BUILD_ROADMAP_2026-06-05.md`). It carries the context a session cannot infer from code (Part 1)
and an audit of what has drifted between the plans and reality (Part 3).

> **Current state lives in the tracker:** `plans/tei-reviewer/00-progress-tracker.md`
> (execution plan: `00-execution-plan.md` in the same dir; master plan / design of record:
> `plans/2026-07-02-tei-reviewer-architecture-plan.md`). This anchor owns Part 1 (invariants +
> decisions) and Part 3 (append-only audit history) only. When any status or next-action prose here
> conflicts with the tracker, the tracker wins — read forward-looking prose below as historical.
> Corrector per-module ☑/☐ detail: `docs/BUILD_PLAN_gold_free_corrector.md` §0/§0b (the tracker's
> owned sub-tracker). This structure was set by the 2026-07-04 architecture review
> (`plans/2026-07-04-fable-architecture-review.md` — a dated record, not a live source of truth).

> **Vocabulary note (2026-06-25).** Human-facing names for this pipeline were unified in `SHARED-LEXICON.md` (the "NSH OCR pipeline — Layer 1" section) and `docs/adr/0016`. This doc keeps the **code-level** names (`sidecar`, `rendering`, `WCT`, `corrector`, the `S0`–`S6` stage numbers) because they match the unchanged schema ids and code — the rename is name-layer only; the physical rename is deferred (ADR-0016 map). When producing anything **human-facing** (orientation docs, summaries, explanations), use the lexicon names — page transcription · standardised transcription · word alignment table · Reconciliation · the ten-stage taxonomy — not the code names used below.

**Leaf-rekey chain COMPLETE as of 2026-06-17** (R-final.3, `abf9abbd`). Every S1 sidecar, S2
rendering, and WCT page is keyed on `canonical_leaf_id`; it is **required on all 4 schemas**
(sidecar-page-v1, sidecar-manifest-v1, rendering-v1, word-confusion-table-v1) via a
`oneOf [canonical_leaf_id | clid_exempt]` constraint, with a `clid_exempt: true` marker for
non-body / unmappable pages (no in-record body/non-body discriminator exists, so the explicit
marker is the mechanism). C1 (zero re-OCR) is confirmed by R6b corpus-wide AND a live `0 to OCR`
regression. The decoupled full render+WCT coverage rebuild
(`docs/RENDER_WCT_full_coverage_plan_2026-06-16.md`) can run before or after; flipping first means
its output is born clid-valid. The detail below is the **historical build record**.

**Edition page-key + 2-D completeness gate COMPLETE as of 2026-06-20** (integration batch 06;
decomposition `plans/_archive/nsh-page-key/`). This lifts the per-copy `canonical_leaf_id` to a
scan-independent **edition page key** and adds a standing completeness invariant. Four facts a cold
session needs:
1. **`edition_page_key = {section, anchor, ordinal}`** is a NEW, **required** field on all 4
   leaf-keyed schemas (sidecar-page-v1, sidecar-manifest-v1 page_ref, rendering-v1 rendered_page,
   word-confusion-table-v1) — the scan-independent cross-copy JOIN KEY. `canonical_leaf_id` is
   **unchanged** (integer per-copy leaf coordinate, demoted in meaning to provenance + monotonic-
   binding substrate; Option 1, additive — design §3a). All 38,970 on-disk sidecars were backfilled
   by `source_payload_sha256` (**zero re-OCR**); a recovered keyless page gets its true edition slot
   (vol_01 p96 → `{body, 96, 0}` with `canonical_leaf_id` still None).
2. **Four disk-true page classes** (read disk, never `gaps[]`): class-1 keyless_ocrd (26 corpus-wide,
   all now keyed — COVERED, not a defect), class-2 stale_gap_record (0, batch 05 reconciled), class-3
   image_not_ocrd (0, batch 05 OCR'd), class-4 true_hole (199 = 196 reasoned `out_of_range` + 3 vol_13
   `permanently_missing`). Owner: `reconcile_page_classes.py` (re-run it; do not recompute).
3. **The 2-D completeness gate is a standing invariant:** `py -3
   build/tools/verify_nsh_page_accounting.py --completeness` (exit 0 = PASS; GREEN corpus-wide
   2026-06-20). Axis (a) coverage — class-2/-3 and unreasoned class-4 and any keyless covered BODY
   page are HARD failures; axis (b) reconciliation **depth** — count of distinct physical scan-copies
   per edition page, **RECORDED as a neutral statistic only** (no flag, no pass/fail effect, no
   confidence/quality judgement; depth-1 is NOT a backlog and we do NOT acquire more scans); axis (c)
   content-read — a SAMPLED running-header read whose sustained printed-vs-key delta run is a HARD
   positioning failure (isolated mismatches are NOTEs, PIPE-29).
4. **Status of the two earlier-flagged items (corrected 2026-06-20):** (i) the design §3 "rung-1
   printed-signal binding gate" is **NOT an open gap — it is stale for NSH and was deliberately
   superseded by R7** (2026-06-15 content alignment). NSH's printed signal is the unreliable input
   (scandata field collides; running-header glyph has digit confusion 2↔8/3↔8), so
   `abbyy_content_alignment.py` correctly binds alternate scans by content (monotone overlap vs the
   primary), printed signal as corroboration only — the inverse of rung-1-first. Per-binding provenance
   lives in each lineage's `leafmap.json`. An earlier batch-06 note called this a "deferred gap"; that
   was a review error (it read the §3 design doc as ground truth instead of the R7 implementation). See
   the SUPERSEDED-FOR-NSH note in `docs/DESIGN_nsh_page_key_edition_vs_copy.md` §3. (ii) **Lane B
   front/back: Phases 2a + 2b LANDED 2026-06-20.** 2a (`809e1308`): 79 junk leaves discarded + recycled,
   147 record-blanks already applied — `discard_frontback_leaves.py`. **2b: the ~203 kept front/back now
   enter the OCR-input gateway** — `page_order.volume_image_paths(vol_dir, include_front_back=True)`
   appends the kept front/back (sourced from the authoritative source-manifest `leaves[]`, the degenerate
   `page_order.json` front-matter entries are bypassed — O5 resolved Option (c)); the NSH S1 runners opt
   in, so the **next** scheduled OCR run picks them up (no re-OCR this session — the currentness gates
   skip covered body pages). The completeness gate's front/back half is now **exercised, not stubbed**
   (`verify_nsh_page_accounting --completeness` exit 0: vol_01 covered=28, vols 02-13 awaiting_ocr =
   their kept counts, unkeyed=0 orphans=0 corpus-wide). The body/non-body partition rides on
   `edition_page_key.section` (no `leaf_kind` field was added — it would duplicate `section`); body
   aggregates stay body-only because `ocr_inventory` / `verify_leaf_keying` derive from body-only
   `ocr_input`. This **reverses the prior "front/back stay out of the WCT" invariant** — recorded in
   **ADR-0017**. Phase 2c (real-word-ratio noise sweep) is a gated follow-up that runs only after the next
   OCR pass produces front/back text. The WCT/reconciled data stores remain stale (pre-backfill,
   quarantined) pending the decoupled render+WCT rebuild; the JOIN CODE is migrated to `edition_page_key`
   and the live render flows the key. Design: `docs/DESIGN_nsh_page_key_edition_vs_copy.md`;
   `plans/2026-06-18-nsh-frontback-discard-promote-plan.md` ("Phase 2b — RECONCILED").

**(Historical) Active build (2026-06-13): NSH chain leaf-rekey** — re-architecting the download→S2 chain off
filename/volume-hash keying onto `leaf_num` (stable join) + `source_payload_sha256` (immutable
reuse, zero re-OCR), after a rename re-triggered a 10.5h vol_01 re-OCR. Canonical tracker:
`docs/BUILD_PLAN_leaf_rekey.md` §0 (steps R0-1 → R-final). Design + three Codex reviews:
`plans/2026-06-13-nsh-leaf-rekey-design.md`. R0-1 → R3-build done. **R3-apply COMPLETE 2026-06-14
(`4d5e2641`)** — all 16 work-cells leaf-keyed on disk (zero re-OCR); the 3 held up-shift cells
landed after two apply-transaction bug fixes (`6ca1e9e4` snapshot-before-write + `927e8a1f`
orphan-quarantine-before-write). **R4a DONE 2026-06-14 (`8e7c80a9`)** — both S2 currentness gates
moved onto the per-page triple `(canonical_leaf_id, source_payload_sha256, sidecar sha)`; ids
reseeded from leaf; expected-set purge added; suite green (3206). Per-cell status, counts, and the
up-shift diagnostics live in the tracker (`docs/BUILD_PLAN_leaf_rekey.md` §0/§2) — this anchor does
not copy them. **R4b DONE 2026-06-15 (`a005d88d`)** — `canonical_leaf_id` (int) is now the
first-class cross-engine / cross-stage page-level JOIN KEY for the primary chain (WCT, CCEL
alignment, gold proposal); `build_from_files` fails closed when engines disagree on the leaf; the
ABBYY geometry lane + `build_gold_sample` grouping stay filename-keyed with marked TODOs R7 closes;
the `page_id` string is kept as display (filename demoted per design §2 — the int leaf is the key).
Suite green (3214 passed). **R6a BUILT 2026-06-15 (`150e1aef`)** — `verify_leaf_keying.py`
(primary-chain verifier / TEST-08) reads the gitignored S1+S2 stores and asserts, per primary
(engine,volume) cell: (a) body sidecar/manifest-page + current-shape S2 rendering carry
`canonical_leaf_id`; (b) reuse held / no re-OCR; (c) cross-engine joins leaf-keyed; (d) S2 dir ⊆
S1 leaves. Wired to `.githooks/pre-commit` (`--gate`, scoped + graceful-skip); pre-run reuse
logging added to all 4 S1 runners + the orchestrator. Suite green (3236). **Verdict is ◐ not ☑:**
(b)/(c) clean (zero re-OCR holds), but (a)+(d) flag 14 un-stamped body leaves in 3 kraken cells
(vol_01/04/05) — sha-resolvable, a contained R3-apply stamp gap to re-stamp before R-final/R6b,
NOT a re-OCR. Per-cell detail in the tracker (`docs/BUILD_PLAN_leaf_rekey.md` §0 R6a) — this
anchor does not copy it. `.bak` retention purge N/A (0 `.bak`); do NOT purge the R3-apply
quarantine dirs (the verifier not fully passing gates the purge). **R7 IN PROGRESS 2026-06-15
(`925d5873`)** — ABBYY alternate-source alignment. New oracle `abbyy_leaf_alignment.py` (PIPE-29
bulk-offset: offset from the ABBYY scandata `page_num` field; the running-header glyph is
corroboration only, not a strict gate, because it suffers the documented NSH digit confusion
2↔8/3↔8 that fakes constant offset runs; hard-stops on sustained non-constant offset >5).
`normalize_abbyy_rich_volume` stamps `canonical_leaf_id` + logs unmapped; WCT geometry lane CLOSED
(render_s2 → build_wct join). Lineage **ia-abbyy-v1 done** (the canonical scan, same-stem). **R7 SUBSTANTIALLY COMPLETE 2026-06-15
(~21:54)** — the prior session's same-stem oracle was found to **mis-map the 6 alternate lineages**
(`dli`/`haucgoog`/`c1-c4` are different physical scans of the same edition with their own leaf order;
the scandata field collides numerically → false offset 0). Fixed by a NEW OCR-tolerant **monotone
content aligner** `build/tools/ocr_pipeline/abbyy_content_alignment.py` (design §6, finally
implemented; reuses `build/lib/text_alignment`; persists a per-cell `leafmap.json` the normalizer now
consumes). Disk now (zero re-OCR): **ia-abbyy-v1 + azure 100%** (vol_11 RESOLVED, content-confirmed),
the **6 alternate lineages ~93%/cell** (the ~7% unmapped = front/back/plate/defect leaves, logged),
**independent primary cross-check 99.8-100% correct**. Task 4 (14 kraken residual) already done
(`166084a2`; R6a OVERALL PASS). Read `docs/R7-alternate-scan-content-alignment-2026-06-15.md`.
**R7 FLIP-READINESS COMPLETE 2026-06-16** — sidecar+manifest `canonical_leaf_id` is now correct
across ALL engines: on-disk verify shows **0 mismatch / 0 missing over 30,429 body sidecars** (azure
normalizer one-line fix copying clid onto the sidecar record + a `force=True` re-emit of every
abbyy+azure cell; closed the azure-0/4509 + dli-2808-stale gaps). The aligner gained a gated
**global fallback pass** (>=0.55 floor + >=0.20 independent primary cross-check, PIPE-29) and a
**primary-tesseract fallback** for reference-gap leaves (the `ia-abbyy-v1` vol_10 reference is missing
22 letter-S leaves; recovers up to 22/cell). Body-page coverage is **~97-100%/cell**, every exclusion
classified `non-body`/`body-unrecoverable` and persisted per leafmap (`unmapped_classified`); the only
2 cells <97% are explained (garbled alt-scan OCR on vols 5-6, canonically covered by the primary, left
unstamped per PIPE-29). **vol_08 RESOLVED** — confirmed canonical vol_01 content (91.7% maps to vol_01,
100% primary-verified), quarantined (546 files, REL-05; BLOCKED doc -> RESOLVED).
`verify_leaf_keying.py` still OVERALL PASS; fast suite 3100.
**Remaining for R-final (named, NOT this session's sidecar scope):** (1) abbyy/azure S2 renderings are
**legacy-monolithic, 0 clid** — a bounded re-render (the abbyy/azure analog of R4a) is required before
the `rendering-v1` flip; (2) WCT (vol_01/02 only) carries **0 clid** (predates R4b) — a `build_wct`
rebuild is required before the `word-confusion-table-v1` flip; (3) build R6b with
**alternate-source-aware (a)/(b)/(c) semantics + exemption of each leafmap's classified-unmapped set**
((b)/(c) sha checks are primary-only — skip for alternate scans); (4) flip the 2 ready schemas + the 2
after their preconditions. The R-final prompt was **rewritten** this session
(`prompts/2026-06-13-1508-leafrekey-Rfinal-verify-and-require.md`). The earlier
"0% / 14-kraken / ~23k-invalid" R-final census (`docs/BLOCKED-leafrekey-R-final-2026-06-15.md`) is
**stale** — read `docs/R7-alternate-scan-content-alignment-2026-06-15.md` (flip-readiness section)
instead.

**Last reconciled: 2026-07-04** — architecture review + single-source-of-truth restructure: the
stateful Part 2 was replaced by pointers (banner at top of this doc); current state is owned by the
NSH-side campaign tracker (`plans/tei-reviewer/00-progress-tracker.md`), with
`docs/BUILD_PLAN_gold_free_corrector.md` §0/§0b as its corrector-module sub-tracker. Track C → U11 →
M15 = campaign batches 09 → 10, first SH publish = batch 11; ADR-0021 (`machine_release` ledger
import semantics) Accepted; the nsh-page-key campaign archived to
`plans/_archive/nsh-page-key/`. Earlier: **2026-07-01** — M15 publish gate built (`publish_gate.py` + the standalone
`publish-projection-v1` schema; route-until-measured embargo default; 14 TDD tests, full fast suite
3565 green). The corrector module chain M1–M15 is now **code-complete** — only Track C adjudication +
the U11 measurement run + M15 threshold certification remain (all eyes/maintainer-gated). Tracker box
flipped; module status owned there. Earlier: **2026-06-20** — integration batch 06: the edition
page-key + 2-D completeness gate
shipped and is integration-verified (full suite 3702 passed; completeness gate + verify_leaf_keying
both OVERALL PASS corpus-wide; a recovered keyless page renders end-to-end with its edition key). See
the milestone banner near the top + Part-1 invariant 8. The earlier leaf-rekey reconcile:
**2026-06-17** — R-final.3 (`abf9abbd`): R5 required-schema flip on all 4 schemas
+ `clid_exempt` marker + 3,731-record migration + full suite green + `0 to OCR` regression; the
leaf-rekey chain is COMPLETE (tracker §0 every row ☑). Earlier 2026-06-16: R7 flip-readiness (sidecar/manifest clid clean across all engines,
global-fallback coverage, vol_08 resolved) landed; see the active-build note above. Earlier:
2026-06-15 (~21:54) R7 alternate-scan alignment landed. Earlier: 2026-06-12 added the OCR coverage inventory pointer (`ocr_inventory.py status`,
the disk-derived SSOT for what OCR exists; Phase 1 of the data-layer redesign, commit `7fbe4b43`);
earlier added the U11b gold-free error-class catalogue pointer
(`docs/JE_ERROR_CLASSES_gold_free.md`); prior full reconcile 2026-06-09 over the architecture sessions, the formal design docs,
the build tracker, the JE surrogate findings, the session logs, and disk ground truth. American
English; relative paths from the repo root.

**Maintenance contract — what this doc owns vs points to.** It *owns* Part 1 (invariants, decisions,
rationale, the reading map): that content lives nowhere else and changes rarely. It carries **no
current-state section** — every volatile fact has a live owner (batch/wave status → the campaign
tracker; module status → `docs/BUILD_PLAN_gold_free_corrector.md` §0; measurement numbers →
`docs/JE_SURROGATE_FINDINGS.md`; OCR coverage → `ocr_inventory.py status`) and this doc points
instead of copying — copied facts drift, and that drift is the problem this doc exists to fix.
Part 3 is a dated snapshot, not living truth. Never hand-patch a volatile number into this doc —
fix it at the owner and let this doc point.

> **Authority order when docs conflict:** (1) disk + `git log`; (2) the campaign tracker
> `plans/tei-reviewer/00-progress-tracker.md` for what's done / what's next, with
> `docs/BUILD_PLAN_gold_free_corrector.md` §0 as its owned corrector-module sub-tracker; (3) the
> running deliverable `docs/JE_SURROGATE_FINDINGS.md` for measurement numbers; (4) the locked design
> `docs/DESIGN_gold_free_corrector_locked.md` + revised ADR-0014/0015 for the corrector contract;
> (5) `plans/2026-05-28-archC-integration-locked-architecture.md` for the base-pipeline lock.
> Where `PROJECT_STATE.md` "Next actions" or `ARCHITECTURE_CONTEXT.md` "Where we are" disagree with
> these, they are stale — see Part 3.

---

# Part 1 — Context for Claude sessions (permanent reference)

## North star and non-negotiable invariants

The pipeline reproduces public-domain Christian reference texts faithfully from multi-engine OCR,
publishing structured JSON. The NSH track is the hard case: a five-engine panel reconciled into a
word-confusion table (WCT), then a gold-free corrector that may compose readings past an
attestation gate but never publishes a machine-composed reading as if a human attested it.

Invariants that cannot be inferred from reading the code alone:

1. **Layer-1 makes no irreversible choice.** Voting is a *choice*, so it stays out of
   `build_wct_page` / `_align_engines`. The corrector is a separate package
   (`build/lib/gold_free_corrector/`) that consumes a *frozen* WCT page and emits a corrected-page
   sidecar. The separation is a determinism guard, not cleanliness — the WCT determinism tests must
   stay green and the surrogate harness must be able to diff corrector versions against the same
   frozen WCT. Source: `docs/DESIGN_gold_free_corrector_locked.md` §2; `wct_builder.py` boundary
   docstring.

2. **Gold-free (HR7).** No human-adjudicated label feeds the corrector at runtime. The in-corpus LM
   trains on WCT **L0 consensus only**, excluding the current run's own L1–L3 output (a test pins
   this). Human gold and the JE surrogate are *validators*, never runtime inputs. Source:
   `docs/DESIGN_gold_free_corrector_locked.md` §3 P3 / §5; `docs/BUILD_PLAN_gold_free_corrector.md`
   §5.

3. **Per-character provenance is complete or the gate fails closed.** Every released token with
   `canonical_derivation_level ≥ L1` must carry a well-formed `character_provenance[]` (one entry
   per grapheme; source in `{engine_family, confusion_rule, lexicon, language_model, human}`),
   including filtered losing glyphs. Source: ADR-0014 (revised); `docs/BUILD_SPEC_corrector_code_from_review.md` F2.

4. **Protected classes route before any score is read (HR5).** Proper names, numbers, dates,
   Scripture references, Greek, and Hebrew route to human review regardless of confidence. This is a
   precondition enforced by P0, not a downstream hope. Source:
   `docs/DESIGN_gold_free_corrector_locked.md` §3 P0; `docs/BUILD_SPEC_corrector_code_from_review.md` F4.

5. **The gate is a publication policy, not a build gate.** Every tier (L0–L3) is built and measured.
   The surrogate decides only which tiers publish *unflagged* vs *flagged* vs *routed*, per tier,
   per token-class stratum, per text. A false correction (a wrong "fix" that reads as clean) is the
   one failure the gate exists to prevent. Source: `docs/BUILD_PLAN_gold_free_corrector.md` decision
   brief; ADR-0015 (revised).

6. **Family-level voting, never engine-level.** A character's support is the count of *distinct
   engine families* that attested it. Kraken and Kraken-Greek collapse to one family (`kraken`);
   correlated engine agreement is not independent trust. Source:
   `docs/DESIGN_gold_free_corrector_locked.md` §3 P1; `s3_reconciler.py` `_best_candidate`.

7. **Public label for L1–L3 is `machine_composed`, never "attested."** Source: ADR-0014 (revised).

8. **The cross-copy page join key is `edition_page_key`, not `canonical_leaf_id`.** `edition_page_key
   = {section, anchor, ordinal}` is scan-independent (a fact of the edition); `canonical_leaf_id` is
   the per-copy primary-scan leaf integer (provenance + monotonic-binding substrate). A page the
   primary scan missed has no `canonical_leaf_id` but still has a true `edition_page_key`, so it joins
   reconciliation normally. **Page facts are read from disk (image + sidecar + sidecar key), never
   recomputed from `gaps[]`** — `gaps[]` is desynced metadata and is the reason this whole effort
   existed. The whole-book guarantee is the 2-D completeness gate (`verify_nsh_page_accounting.py
   --completeness`), a standing invariant: coverage is HARD (a located-but-not-fetched or
   image-not-OCR'd page fails the build); reconciliation depth is RECORDED as a neutral statistic only
   (no confidence/quality judgement, depth-1 is not a backlog). Source:
   `docs/DESIGN_nsh_page_key_edition_vs_copy.md` §3/§3a/§5; the milestone banner at the top of this doc.

9. **The canonical read path for an NSH source manifest is `build/lib/nsh_leaf_model.py`** (the
   accessor: `body_pages` / `front_matter` / `back_matter` / `plates` / `discarded` / `ocr_input` /
   `leaves_view` / `derive_kind` / `expected_image_name`). **Never read `manifest["pages"]` /
   `["unnumbered_leaves"]` directly** outside the accessor and the write-path/migration code —
   `tests/test_nsh_source_manifest_gate.py` (TEST-08) fails the build if you do (documented
   `# nsh-legacy-read:` marker for the integrity-detector exceptions). Source: the leaf-sequence
   design `docs/DESIGN_nsh_leaf_sequence_manifest.md`; P0.5 (2026-06-11).

## Stable measurement verdicts (JE oracle)

The figures live in `docs/JE_SURROGATE_FINDINGS.md` (§1/§4/§6), the running deliverable — never
copy its percentages here; they re-baseline. What a cold session carries forward is the set of
*verdicts*, stable even as the numbers move:

- Reference = JE.com human diplomatic transcription (non-circular); aligner is B8-tuned
  (GAP_PENALTY=0.6, confirmed optimal). B8 is complete — the findings-doc rates are the tuned
  floor, not a pre-tuning estimate.
- **All-engine attestation (M3), not ≥2-family agreement, is the better auto-accept signal** —
  confirmed in both the aggregate and complete-page strata. M3 is all-engine *reading* agreement
  (includes text-only Kraken), not a geometry-only gate.
- The M1≈M0 gap is negligible: the accuracy ceiling is structural ("no engine had the right
  answer"), not a `_best_candidate` selection failure.
- Read the complete-page stratum as the conservative estimate; the aggregate is upward-biased by
  partial-page selection.

## Key decisions and rationale (invisible to a cold session)

| Decision | Why | Source |
|---|---|---|
| **Why gold-free** | The reconciler is an *unsupervised middle*: it has no human-labeled training set and must not wait for one. Consensus + public-domain lexicon + WCT confusion machinery are the only runtime inputs. Human gold gates *publication*, not correction. | `docs/DESIGN_gold_free_corrector_locked.md` §2, §5 |
| **Why JE as the measurement oracle** | The 10-page SH run produced *circular* M2/M3 — the only reference was CCEL, whose "gold" bucket is defined as CCEL == OCR. The 1901–1906 Jewish Encyclopedia has a **human** diplomatic transcription of the *same edition* the IA scanned, so scoring OCR against it is non-circular. JE is a measurement oracle only — never a Christian text, never published, correctly absent from `research/MANIFEST.md`. | `docs/JE_SURROGATE_FINDINGS.md` §2.1 |
| **Why CCEL is anchor only for specific volumes** | CCEL's page-keyed "gold" is correct-by-construction on the gold stratum and wrong-by-construction on the disagreement stratum; pooled rates re-report the bucket split, not accuracy. So CCEL anchors where it is edition-matched and used as one signal, not as a universal reference. | `docs/JE_SURROGATE_FINDINGS.md` §2.1; `docs/MEASUREMENT_FINDINGS_vol01_10page.md` |
| **Why Kraken-Greek is a separate lane** | Standard Kraken finds ~0 Greek words; Kraken-Greek is the Greek-script specialist (e.g. 75 Greek-range codepoints on JE p38 vs 0 for Kraken). It shares `engine_family="kraken"` so it does not inflate family-vote independence. | `docs/JE_SURROGATE_FINDINGS.md` §3, §5 |
| **Why Surya is excluded from the JE panel** | Compute ceiling (maintainer call); dropping Surya costs no WCT geometry because in the SH run only ABBYY and Tesseract carried word geometry (Surya's words sat inside `blocks`). A parallel thread is replacing Surya entirely with consensus word-box geometry. | `docs/JE_SURROGATE_FINDINGS.md` §3; memory `project_layout_authority_geometry` |
| **What arch7 (reviewer) became** | Static HTML + vanilla JS, no framework, ~1900 LoC budget; decisions accumulate in-browser and download as a JSON *review patch* (`schemas/v1/review_patch.schema.json`) applied by CLI. Reviewer tooling is built but not yet exercised on a gold set. | ADR-0012; `docs/PIPELINE_BUILD_STATE.md` |
| **Why "route-until-measured" is a flag, not 0.0** | An `accept = 0.0` default makes `false_correction <= accept` evaluate `0.0 <= 0.0 = True` and silently auto-accepts — the opposite of the intended embargo. The fix is a per-`(level, region_class)` `auto_accept_enabled` flag (default false) or a `null` measured rate. | `docs/DESIGN_gold_free_corrector_locked.md` §6, §8 must-fix #5 |
| **Why real-word-error rate is a first-class gate** | CER counts any character mismatch, but a "fix" of `modem`→`modern` is CER=0 yet introduces a real-word error that reads as clean. P4 carries an explicit `max_real_word_error_rate` per `(level, region_class)`; a tier that clears CER but fails the real-word bound is demoted. | `docs/DESIGN_gold_free_corrector_locked.md` §6, §7 |
| **Why the harness is corpus-parametric (JE AND SH)** | The corrector is *measured* on JE (has a diplomatic reference) but *deployed* on SH. The harness reports per-stratum JE↔SH **deltas**, turning ADR-0015's transfer question ("does a tier safe on JE stay safe on SH?") into a measured output rather than an assumption. | `docs/BUILD_PLAN_gold_free_corrector.md` §4; ADR-0015 |
| **Why ADR-0014/0015 were revised in place** | Both were same-day, pre-implementation ADRs; an adversarial review found 8 issues. Revising in place (maintainer call) is sound because the supersession rule protects an audit trail that did not yet exist. Decision-half → ADRs; code-half → `BUILD_SPEC_corrector_code_from_review.md` (F1–F8). | `PROJECT_JOURNAL.md` 2026-06-05; memory `feedback_adr_inplace_revision_same_day` |

## What to read for different tasks (replaces the scattered pointers)

| Task | Read |
|---|---|
| Corrector build status / what to do next | `docs/BUILD_PLAN_gold_free_corrector.md` §0 tracker + §0b execution units (canonical) |
| Corrector contract / invariants | `docs/DESIGN_gold_free_corrector_locked.md` + `docs/BUILD_SPEC_corrector_code_from_review.md` (F1–F8) |
| Formal decisions + their status | `docs/adr/` (ADR-0001 … ADR-0015) |
| Measurement numbers (JE oracle) | `docs/JE_SURROGATE_FINDINGS.md` — the running deliverable, authoritative for rates |
| Gold-free error-class catalogue (NSH risk register) | `docs/JE_ERROR_CLASSES_gold_free.md` — per-class detection/correction tells + the uncaught-remainder risk NSH inherits (U11b) |
| Base-pipeline architecture (arch1–arch9) | `ARCHITECTURE_CONTEXT.md` → `plans/2026-05-28-archC-integration-locked-architecture.md` (the lock) |
| Real built-state of S0–S6 stages | `docs/PIPELINE_BUILD_STATE.md` |
| **What OCR exists (per volume × engine × stage)** | run `py -3 build/tools/ocr_pipeline/ocr_inventory.py status` — the disk-derived SSOT; never stale (rebuilds each call). The **sole** coverage SSOT since Phase 2D retired `corpus-coverage` (commit `1800e96e`); replaces guessing/globbing and the stale `catalog.json coverage`. Coverage is keyed by `canonical_leaf_id` (= `leaf_num`, an int, via the `nsh_leaf_model` accessor) so leaf-keyed and page-keyed sidecars reconcile (Phase 2B, `f63bff9a`). Data-layer redesign: `plans/2026-06-12-ocr-datalayer-design-reconciled.md` (Phase 2A–2D done; 2E parked) |
| Operational gotchas before committing data/schema | `PIPELINE_REFERENCE.md` |
| Corpus acquisition (separate deliverable) | `research/MANIFEST.md` |
| What just happened | newest `LAST_SESSION_*.md` (sort by mtime) |

---

# Part 2 — Current state (pointer — not maintained here)

Stateful current state was removed from this anchor on 2026-07-04 (it had drifted; recover the old
Part 2 from git history if needed). Read the live owners instead:

1. **What's done / what's next (batches, waves, blockers):**
   `plans/tei-reviewer/00-progress-tracker.md` — the ONE NSH-side tracker, updated
   every session. Execution design: `plans/tei-reviewer/00-execution-plan.md`.
2. **Corrector per-module status (M1–M15, U11/U12/TC ☑/☐):**
   `docs/BUILD_PLAN_gold_free_corrector.md` §0/§0b — the tracker's owned sub-tracker.
3. **What OCR exists (per volume × engine × stage):**
   run `py -3 build/tools/ocr_pipeline/ocr_inventory.py status` — disk-derived, never stale.
4. **Measurement numbers:** `docs/JE_SURROGATE_FINDINGS.md` (the running deliverable).
5. **Page accounting / completeness:** run `py -3 build/tools/verify_nsh_page_accounting.py
   --completeness`; scan-coverage ground truth is the per-volume manifests at
   `raw/internet-archive/schaff-herzog-pages/vol_NN.manifest.json`.

This anchor owns Part 1 (invariants + decisions) and Part 3 (append-only audit history) only.

---

# Part 3 — Audit findings

Neutral catalog. `gap` = planned and committed to in a source doc, not present or only partially
built. `drift` = present but built differently from the plan. `superseded` = the plan rested on a
factual assumption that has since changed. Every row cites a source doc; inference-only observations
are omitted.

| # | Type | What was planned | What exists | Source doc | Notes |
|---|---|---|---|---|---|
| 1 | gap | M15 publish gate (`publish_gate.py`): L0+human unflagged, L1–L3 flagged-until-certified, `machine_composed` label | No `publish_gate.py` on disk; ☐ in tracker | `docs/BUILD_PLAN_gold_free_corrector.md` §0 line 41; `BUILD_SPEC…` F1 | Depends on M9 (done) + M13 *run* (not done) |
| 2 | gap | Track C — human-adjudicated SH transfer sample feeding M13 + M15 | Not acquired; ☐ in tracker | `docs/BUILD_PLAN_gold_free_corrector.md` §0 line 42 | Blocks unflagged release per token class |
| 3 | gap | U11 / Wave 5 — *run* M13 harness on JE + SH, present per-stratum deltas | M13 module committed (cf5a4797) but never executed on real data; no deltas produced | `docs/BUILD_PLAN_gold_free_corrector.md` §0b U11 | "Built" ≠ "run"; the measurement that answers M1/M2/M3 has not happened |
| 4 | superseded | `PROJECT_STATE.md` records JE M3t = 66.8% aggregate / 40.7% complete-page (4-engine run) | Running deliverable now 69.5% aggregate / 65.9% complete-page (5-engine; Azure added all 36 pages, expanded WCT 38,565→49,760 positions) | `PROJECT_STATE.md:21` vs `docs/JE_SURROGATE_FINDINGS.md` §1/§4 | The 4-engine "complete-page M3t ≈ M2" finding explicitly no longer holds (`FINDINGS` §1, lines 6–8) |
| 5 | superseded | `BUILD_PLAN` A3 row records JE M3t = 71.0% aggregate / 66.2% complete-page | Authoritative deliverable says 69.5% / 65.9% | `docs/BUILD_PLAN_gold_free_corrector.md:21` vs `docs/JE_SURROGATE_FINDINGS.md:27` | Smaller drift than #4; same root cause (tracker row not refreshed after the post-confusion_distance-fix measurement) |
| 6 | drift | `PROJECT_STATE.md` "Next actions": "Next to run: U8 (M11 reconcile_corrected)"; U9 "also unblocked" | M11–M14 all committed (5f5cb56f, d646c553, cf5a4797, e54bc701) | `PROJECT_STATE.md:32` vs `BUILD_PLAN…md` §0 lines 37–40 | The scattered next-action pointer is behind the canonical tracker — the reason this anchor doc exists |
| 7 | superseded | `PROJECT_STATE.md` / `ARCHITECTURE_CONTEXT.md`: B8 aligner tuning + threshold calibration is the "next" gating step; all JE rates are "floors under the un-tuned aligner" | B8 complete 2026-06-06; GAP_PENALTY=0.6 confirmed optimal (sweep showed 0.0pp M0 gain within the coverage constraint) | `PROJECT_STATE.md:33` vs `docs/JE_SURROGATE_FINDINGS.md` §1/§6 | The prompt's own example of a superseded assumption; rates are now the B8-confirmed floor |
| 8 | drift | ADR-0013 specifies a full 100-point weighted scoring rubric + four-bucket thresholds for the S3 reconciler | Reconciler is an unweighted stub: `alignment_confidence` weight 0.0, all `total_score` = 0.0; no automatic correction without a gold set | ADR-0013 vs `docs/PIPELINE_BUILD_STATE.md` | The gold-free corrector is the chosen path that doesn't wait on a trained weight matrix |
| 9 | drift | arch6 LLM-in-loop is part of the reconciliation pipeline | `llm_evidence_provider.py` built + tested as a library, **not wired** (tuning embargo) | arch6 synthesis vs `docs/PIPELINE_BUILD_STATE.md` | Deliberate hold, not a forgotten obligation |
| 10 | superseded | Surya was a panel engine in the base-pipeline engine set | Surya excluded from the JE panel (compute ceiling); a parallel thread is replacing it with consensus word-box geometry | `plans/2026-05-28-archA-…` engine set vs `docs/JE_SURROGATE_FINDINGS.md` §3; memory `project_layout_authority_geometry` | Documented scope decision |
| 11 | superseded | arch1 preliminary end-to-end synthesis as a design reference | Marked superseded by the archC lock as canonical | `ARCHITECTURE_CONTEXT.md:43` | Recorded supersession at the design layer |
| 12 | gap | Kraken vol_01 (31 pages) + vol_02 (22 pages) re-OCR should reprocess failed pages | Pre-`9547e0bc` bug wrote failures into `emitted_pages`; 53 pages silently skip on re-run; idempotent repair script provided but not confirmed run | `PIPELINE_REFERENCE.md` §18 | Operational known-issue; affects re-OCR only |
| 13 | gap | `fetch_ia_pages.py` should handle IA EU dead-node failures | Reference impl `_fetch_samu_direct.py` exists; primary fetcher still uses `_IA_BASE_URL` redirects; manual fallback only | `PIPELINE_REFERENCE.md` §19 | Vols 04/05/10 affected; not automated |
| 14 | drift | A6 folio cross-check guard confirms ABBYY GZ folios come only from body pages | Performed on 3 of 36 built pages (leaves 73–75); leaves 40–72 and 76–109 unchecked | `docs/JE_SURROGATE_FINDINGS.md` §6 ("Residual: folio cross-check guard") | Known open data-quality risk, not blocking |
| 15 | gap | Author registry encoding should be clean (no triple-encoded `display_name`/`aliases`) | adamnan-of-iona + vincent-of-lerins fixed; no automated detection; residual corruption unknown | `PIPELINE_REFERENCE.md` §15 | Manual `grep "Ã"` advised |
| 16 | gap | IA `page_numbers` cascade: renumber downstream entries when a leaf is skipped | Vol 11 manually fixed (31 entries, 2026-05-28); no automated cascade-fix; other volumes unverified | `PIPELINE_REFERENCE.md` §16 | Recto/verso parity check is the manual mitigation |
| 17 | superseded | `ARCHITECTURE_CONTEXT.md` §3 "Next step: run batch-decomposition against the reconciled plan" | The base-pipeline build (B0–B17) is complete; the active frontier is the gold-free corrector stack, not the archD batch decomposition | `ARCHITECTURE_CONTEXT.md:54` vs `docs/BUILD_PLAN_gold_free_corrector.md` | The 2026-05-28 map predates the 2026-06-05 corrector pivot (noted in `ARCHITECTURE_CONTEXT.md:14`) |
| 18 | drift | Manifests record each physical leaf once with a consistent position | 8 old-form volumes (03/04/07/09/10/12/13 + live 11) double-record the first body pages: leaves are in `pages[]` (reconstructed printed 1–N) AND in `unnumbered_leaves` `front_matter` (scandata left them unnumbered) — e.g. vol_03 leaves 23–31. Verified vs vol_03 scandata | `research/2026-06-11-nsh-coverage-positioning-audit.md` F2 | The bug the leaf-sequence redesign (Part 2 program) retires; P2 |
| 19 | gap | Every non-blank leaf has its own downloadable image (R2) | Front/back-matter images missing for all 13 vols; only body pages imaged. vol_01 alone has 52 `leaf_*.jpg` on disk but they are **unreferenced** by its manifest (orphans) | `research/2026-06-11-nsh-coverage-positioning-audit.md` F1 | P3 imaging pass; ~480 non-blank leaves |
| 20 | drift | Rebuilt volumes (01/02/05/06/08) carry a front/back-matter map | `unnumbered_leaves` dropped entirely on rebuild — front matter unrecorded (validates only because the field is optional). Less complete than the schema-invalid old volumes | `research/2026-06-11-nsh-coverage-positioning-audit.md` F3 | P2 migration restores it from scandata |

**Recorded as resolved, not a finding:** the D9 surrogate→WCT-position alignment (flagged
unspecified in both independent designs) is implemented for JE via `align_je_to_wct.py` /
`measure_je.py`, which produced the §4 numbers. The SH-side equivalent rides on the same harness
(M13). Source: `docs/JE_SURROGATE_FINDINGS.md` §2.4; `docs/DESIGN_gold_free_corrector_locked.md` §7.
