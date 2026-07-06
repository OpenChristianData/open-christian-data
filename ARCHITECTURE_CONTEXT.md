# Schaff-Herzog OCR Pipeline — Architecture Context Map

> **For current NSH pipeline state, read `docs/NSH_PROJECT_STATE.md` (the anchor doc) first.** This
> file is the **arch1–arch9 reading-order map only** — it explains what each design document is and
> the order to read them. Its "Where we are" / "Next step" sections are dated 2026-05-28 and are
> stale (the build is complete and the frontier is now the gold-free corrector); the anchor doc's
> drift audit supersedes them. Use this file to navigate the design history, not to learn current
> status.

Orientation for a fresh session working on the multi-engine OCR-to-publication pipeline for the Schaff-Herzog encyclopedia. **Read this first** — it says what each design document is and where to look. American English; relative paths from the repo root.

Most documents below live in `plans/` and `prompts/` (gitignored working-copy design records). The committed canonical artifact is the lock (`plans/2026-05-28-archC-integration-locked-architecture.md`, force-added).

## Two tracks — don't confuse them

- **New pipeline (this map):** the arch1–arch9 design sequence for the harder multi-engine OCR reconciliation of the Schaff-Herzog volumes. Being designed/built now.
- **Existing dataset (separate):** the broader Open Christian Data corpus already published on HuggingFace, with its own ~28 schemas and parsers under `schemas/v1/` and `build/`. Shared machinery, separate deliverable.

## Where we are

> **2026-06-05 update:** current direction is in `docs/BUILD_ROADMAP_2026-06-05.md` (gold-free corrector stack, cross-architect design, JE surrogate) and `docs/PIPELINE_BUILD_STATE.md` (real built-state). The text below is the 2026-05-28 design map, kept for the arch1–arch9 reading order.

**Build complete.** All batches B0–B17 landed — chain terminus `df212439`/`98bbec19` (2026-05-31). The **10-page vol_01 run is also complete** (2026-06-02). See `docs/MEASUREMENT_FINDINGS_vol01_10page.md` for M0–M3 results. M2/M3 headline rates are circular (CCEL-vs-agreement conditioned); see `docs/MEASUREMENT_REFERENCE_OPTIONS.md` for the non-circular path. M0 (single-best baseline) and family-independence results are now interpretable.

Open work (as of 2026-06-03):
- **Human adjudication** — ~300–500 disagreement-queue positions; lifts the tuning embargo. Scope in `docs/MEASUREMENT_REFERENCE_OPTIONS.md`.
- **OCR speed optimisation DONE** (2026-06-03, commit `5c89aea1`): Tesseract PSM=3 + batch subprocess; Kraken max-width 1800 + batch subprocess. A clean validation run on idle machine is recommended before relying on the committed timing figures (warm-process bias present in benchmarks).
- **B2.5 data work** — Azure OCR + ABBYY multi-source downloads still pending (independent; prompts in `prompts/`).
- **Vol 5/6/13 mid-volume gap investigation** — no prompt written yet; read `CLAUDE.local.md` "Known data quirks" for the cascade renumbering rule before starting.

Design: **locked through step C** (`plans/2026-05-28-archC-integration-locked-architecture.md`). Build plan: `plans/2026-05-28-archD-implementation-reconciled.md` (batch tracker §2 — all ☑). Macro-stages: design (done) → build (done, B0–B17) → 10-page run + measurements (done) → human adjudication → embargo lift → tuning → publish.

---

## Reading order

### 1. Start here
- `LAST_SESSION_*.md` (newest mtime, in this repo's root) — what just happened. Cap of 5 files; older entries roll into `PROJECT_JOURNAL.md`.
- `plans/2026-05-28-archC-integration-locked-architecture.md` — **THE v1 architecture lock. Canonical.** Read its "Maintainer sign-off (2026-05-28)" section (the resolved decisions) and §9 (the divergence walk — every amendment to a prior session's contract).

### 2. Architecture context (what the lock builds on)
- `plans/2026-05-26-end-to-end-pipeline-brief.md` — founding requirements (§8 = the arch9 scope).
- `plans/2026-05-28-arch9-decomposition.md` — the A→B→C→tail carve + the STEP 0 engine inventory. (STEP tail = step D, **done** — see the reconciled plan in §3.)
- `plans/2026-05-28-research-synthesis.md` — the four locked research decisions, the matrix-training correction (§4.1), the build-and-measure list (§5), and the maintainer's §8 resolutions.
- `plans/2026-05-28-archA-alignment-reconciled-design.md` — the alignment layer (stage S2.5), the word-confusion-table (WCT) contract, and the locked engine set (§12).
- `plans/2026-05-28-archB-schema-reconciled-design.md` + `plans/2026-05-28-archB-schema-freeze-declaration.md` — the schema design + what is frozen (1 file built) vs design-locked (13 schemas, built in the implementation pass).
- The eight inherited contracts (read the relevant one when a stage touches it):
  - `plans/2026-05-26-arch1-preliminary-end-to-end-synthesis.md` (preliminary — **superseded** by the lock as canonical reference)
  - `plans/2026-05-27-arch2-precleaning-synthesis.md`
  - `plans/2026-05-27-arch3-output-schema-synthesis.md`
  - `plans/2026-05-27-arch4-weight-matrix-synthesis.md`
  - `plans/2026-05-28-arch5-reconciler-synthesis.md`
  - `plans/2026-05-28-arch6-llm-in-loop-synthesis.md`
  - `plans/2026-05-28-arch7-reviewer-synthesis.md`
  - `plans/2026-05-28-arch8-typography-synthesis.md`

### 3. The build plan (step D output — the sequence to build against)
- **`plans/2026-05-28-archD-implementation-reconciled.md` — THE implementation-order plan. Read after the lock.** Ordered (not scheduled): §1 phases + gates, §2 the 18-batch / 7-wave decomposition with a per-batch `Depends` column and explicit parallelism waves, §3 first-diagnostics sequencing, §4 engine rollout, §5 operational-deliverable specs (items 11–14), §6 risks + decisions awaiting maintainer sign-off. The lock is the canon; this plan is the sequence; this context file is the index.
- The four step-D working files (provenance, audit only): `plans/2026-05-28-archD-implementation-{claude,codex}-design.md` + `plans/2026-05-28-archD-{claude-reviews-codex,codex-reviews-claude}.md`.
- Source prompts (how step D was run): `prompts/2026-05-28-archD-implementation-order.md` (orchestration) + `prompts/2026-05-28-archD-implementation-codex.md` (shared brief).
- **Next step:** run `batch-decomposition` against the reconciled plan to produce single-context-window session prompts. The plan §2 flags which batches need splitting and which run in parallel.

### 4. Working / provenance files (audit only — not implementation inputs)
- Per step, the two independent design passes + the two cross-reviews. For step C: `plans/2026-05-28-archC-integration-{claude,codex}-design.md` and `plans/2026-05-28-archC-{claude-reviews-codex,codex-reviews-claude}.md`. Same pattern for archA/archB and arch1–arch8 (`…-claude`/`…-codex`/`…-reviews-…`). These show *how* a synthesis was reached; read them only to understand or re-litigate *why*.

### 5. Conventions, schema & code (for implementation)
- `docs/SCHEMA_SPEC.md` — schema spec + allowed enum values. Read before writing any parser.
- `.claude/rules/*.md` — workflow + parser conventions (loaded automatically when matching file types are opened; no index file).
- `build/lib/schema_enums.py` + `build/lib/_generated_enums.py` — the enum source of truth. Never hardcode enums.
- Pipeline schemas (7 in `schemas/v1/`): `word-confusion-table-v1`, `sidecar-page-v1`, `sidecar-manifest-v1`, `rendering-v1`, `rendering_catalog`, `decision-event-v1`, `family-map-v1`. Validated in-code without a JSON schema (B17 path deviation): `typography-snapshot-v1`, `evaluation_manifest`.
- `build/CLASSIFICATION_LOG.md` (classification rationale) + `UPSTREAM_BUGS.md` (external-bug log).

### 6. Background / history
- `PROJECT_JOURNAL.md` — permanent historical record.
- `README.md` — public project description.

---

## How to read the design docs safely

1. **Read the lock first.** It is the canonical reference; the eight syntheses are the *detail* beneath it.
2. **Where a synthesis conflicts with the lock, the lock wins.** The lock's §9 (divergence walk) lists every amendment.
3. **Known stale spots** — a raw read of these will mislead:
   - **arch5 §9.2** — the synthesis fires a training event on a *dictionary* corroboration; the lock amended this to the strict cross-family + independent-check bar (+ a family-map-readiness gate).
   - **Publication** — anything saying "option B" is stale; the maintainer settled **option C** (slim public, full audit private).
   - **Paid engines** — not "no paid services" absolutely; the posture is *no dependence, limited opportunistic use on hard pages*.
   - **Event-type naming** — the `decision-event-v1.event_type` reconciliation is deferred to the schema-build pass, not settled in any synthesis.

---

## Planned follow-up sessions (one-click chips, optional, non-blocking)

- **Grill-with-docs shared lexicon** — DONE. `SHARED-LEXICON.md` committed to repo root.
- **Per-phase + end-to-end pipeline diagrams** — a plain-language walkthrough diagram for each stage S0–S6 plus an end-to-end map. Not yet done.
