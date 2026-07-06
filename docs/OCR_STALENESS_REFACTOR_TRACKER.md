# OCR Staleness Refactor + vol01/02 Build — Tracker

**Canonical source of truth for this program of work.** If status here disagrees with a
memory file, a `LAST_SESSION_*.md`, or a bootstrap prompt, **this doc wins** — update the
others to match. Committed (unlike the gitignored memory/PROJECT_STATE) so every parallel
session sees current progress via git.

Scope: fix the S1/S2 index-layer staleness (manifests/renderings silently shrink below
real sidecar coverage on a partial `--pages` run), then finish the vol_01 + vol_02
reconciliation build on top of the fixed pipeline. This is the program described in
`prompts/2026-06-05-pipeline-staleness-fix-and-finish-build.md` (the parent plan).

**Not in scope here** (separate threads, separate docs — do not conflate): the gold-free
corrector design (`docs/BUILD_ROADMAP_2026-06-05.md`, ADR-0014/0015), the SH engine-panel
phase-1 plan (`docs/BUILD_PHASE1_PLAN_vol01_02.md`), and the JE surrogate validator.

## How to use this doc
1. Before starting a unit, read its row + the linked detail (memory `project_ocr_pipeline_staleness`, the parent plan, the unit's bootstrap).
2. On completing a unit, **update its row here** (status → ✅, fill the Commit column) in the same session, before writing the next unit's bootstrap. This is part of the self-propagating workflow (one unit per session; each session writes the next unit's bootstrap + updates this tracker).
3. Each unit runs the loop: Claude designs the Codex contract → Codex codes at MEDIUM effort → Claude reviews (run tests + `git diff HEAD` + read diff) → Claude commits by explicit pathspec. Codex never commits (CODEX-05).

Status legend: ✅ done · 🔄 in progress · 🔲 not started · ⏸ deferred

## Refactor units (fix the index layer)

| Unit | What | Status | Commit | Notes |
|---|---|---|---|---|
| **R1** | Reindex-from-disk manifest tool (`build/tools/ocr_pipeline/reindex_manifest.py` + tests) — rebuild an engine/vol manifest+state as the union of on-disk sidecars; never scoped-shrink; never OCR | ✅ | `77535456` | 4 live-OCR engines. Ran on vol_01: kraken 2→543, kraken-greek 2→13, surya 2→137, tesseract 543→543; 0 existing-sidecar pages would re-OCR. tesseract vol_01 re-OCR landmine defused. |
| **R2** | Skip-OCR keyed on valid sidecar-on-disk (not the state file); demote `manifest.state.json` to a derived view — across the 4 live runners | ✅ | `d65e8994` | 7 skip sites changed (tesseract+kraken pre-compute, kraken-greek+surya single-page, surya batch, ABBYY×2). HIGH adversarial review: all 8 attacks Accept. Shared-helper extraction deferred (R-opt). |
| **R3** | `doctor`/`status` command (cross-checks sidecars-on-disk vs manifest vs rendering per engine/vol, reports drift) + render-time drift assertion (warn/fail if manifest < sidecars on disk) | ✅ | `7a567bb6` | `sidecar_utils.count_sidecars` shared helper; `ocr_doctor.py` CLI (15 TDD tests); render_s2 warn-only drift check. Smoke: DRIFT flagged for tess/kraken/ia-abbyy (stale manifests confirmed), OK for kraken-greek/surya. |
| **R4** | Per-page renderings — re-architect `render_s2.py` (~600 lines) + chain to emit one rendering file per page per engine; drop `filter_rendering_to_page`; thin volume index. **Must precede Phase B.** | ✅ | `62ed1bea` | output_dir/pages/{page_native_id}.rendering-v1.json + index.json; summary return; filter_rendering_to_page removed; _single_rendering_paths reads per-page files directly. 14 TDD tests. Smoke: 537 pages written on vol_01 tesseract. |
| **R-opt** | (Optional) Extract shared `should_skip_page` + manifest-assembly module that runners AND `reindex_manifest.py` call — kills runner↔reindex drift | ⏸ | — | Deferred out of R2 to keep R2 small. Do only if drift becomes a real problem. |

## Build phases (finish vol_01 + vol_02 on the fixed pipeline)

| Phase | What | Status | Commit | Notes |
|---|---|---|---|---|
| **B** | Reindex + render full S2 for the panel on both volumes (tesseract, ia-abbyy, azure-ai-vision, kraken-py312; +kraken-greek/surya where sidecars exist). ABBYY staleness fixed by re-running the *importer* full-volume (cheap), NOT the reindex tool. Render azure vol_02 (missing). | ✅ | no code commit (operational) | ABBYY: all 7 lineages re-imported + rendered. tesseract/kraken/azure/surya: misplaced renders moved (render_s2 --output-dir omitted); re-rendered/moved to correct s2-renderings layout. surya vol_01=137p (partial sidecars); surya vol_02=0 (all sidecars surya_runtime_error → Phase C). kraken-greek vol_01=13p. Note: old bundles (vols 03–11) NOT re-rendered; Phase D uses a bundle-splitter script. |
| **page_0010 gate** | Drive vol_01 page 10 with the panel + geometric authority; confirm reconciled chosen text reproduces the known-good baseline; azure-ai-vision is a family; geometric is the authority (Surya not required). | ✅ | no code commit (operational) | Gate passed (exit 0). `reports/reconciled/vol_01/page_0010.json` confirmed present (1.1 MB). Chain used --engine append syntax (not space-separated list). surya page_0010 present in the 137-page partial set. |
| **C** | Driver change (Codex): `drive_reconciliation_chain` panel default engines (no surya in the geometry set), `build_wct_page` geometric mode, escalation two-pass (escalated ~2.4% pages get Surya-on-those-only then reconcile). Resumable, skip-existing, background-safe. Then drive vol_01 1-491 + vol_02 1-488 (~979 pages). | 🔄 | `f9547076` `a883d4ba` | Code landed. Full drive vol_01+vol_02 running (background). reviewer_queue.json uses queue[] array (no auto_accept field). `a883d4ba`: hardening — per-future REL-08 try/except, Ctrl+C cancel_futures, per-page occurred_at, _init_worker schema preload (_WORKER_SCHEMAS), BrokenProcessPool catch, removed dead _PageArgs fields. |
| **D** | Volume-scale measurements: family-independence + calibration ECE per engine (print reference + N before any rate); coverage table attempted/succeeded/failed per vol per engine. Write `docs/BUILD_COMPLETION_vol01_02.md`. End with full `py -3 -m pytest -p no:cacheprovider -q`. | 🔲 | — | M2/M3 NOT reported (circular — settled). |

## Dependencies
- R4 **must** land before Phase B (otherwise render volume-bundles then re-architect + re-render).
- R2 and R3 are hardening — R1 already closed the live re-OCR trap, so they can run before or after the build, but before Phase C's long drive is preferable (resumability matters over ~979 pages).
- page_0010 gate before the full Phase C drive.

## Settled decisions / constraints (detail in memory `project_ocr_pipeline_staleness`)
- NEVER re-OCR a page whose successful sidecar exists (~28s/page).
- `leaf_` are NOT duplicates (46/52 unique scans) — do not recycle. vol_01 input is a leaf_/page_ mix; `leaf_` classification done → `docs/LEAF_PAGES_vol01_findings.md`, `page_order.json`.
- Per-page renderings (#5) not required for correctness (root cause is the scoped manifest), but chosen for countability.
- Gold-free trust (≥2 independent family blocks agree = auto-accept; CCEL = proposal only). Azure is a full panel member — treated identically to tesseract, ABBYY, kraken in all metrics and coverage counts. M2/M3 circular — not headline.
- Sync.com paused (its lock interception breaks render's atomic `os.replace`). American English; `-p no:cacheprovider` on pytest; commits by explicit pathspec (GIT-01b — parallel sessions share the index); never `--no-verify`.

## Pointers
- Parent plan: `prompts/2026-06-05-pipeline-staleness-fix-and-finish-build.md`
- Live detail + workflow: memory `project_ocr_pipeline_staleness`
- Phase A (done, geometric layout authority): commit `e4757f88`, `ARCHITECTURE_CONTEXT.md`
- Chain code: `build/tools/ocr_pipeline/{drive_reconciliation_chain,build_wct,render_s2,run_ocr_pipeline,reindex_manifest}.py`; builder `build/lib/wct_builder.py`; detector `build/lib/consensus_layout.py`
