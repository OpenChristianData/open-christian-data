# BLOCKED — leaf-rekey R4a (precondition not met: R3-apply never ran)

> **SUPERSEDED 2026-06-14 — this block is historical only.** It records a point earlier on
> 2026-06-14 when R3-apply was still blocked. R3-apply later completed (`4d5e2641`, all 16 cells
> leaf-keyed), and **R4a then ran in full and is COMPLETE + disk-verified**: code `8e7c80a9`
> (both S2 gates rekeyed, suite green 3206) + all 16 primary cells re-rendered and independently
> verified on disk (16/16 == expected set, 6410 leaf-stamped renderings, 0 orphans). The
> "what was NOT done" section below is no longer true. See the tracker R4a row in
> `docs/BUILD_PLAN_leaf_rekey.md` §0 and the newest `LAST_SESSION_*.md`.

**Date:** 2026-06-14 (autonomous overnight run)
**Step:** R4a (`prompts/2026-06-13-1504-leafrekey-R4a-s2-rekey.md`)
**Outcome:** Did NOT start. Precondition unmet. **No S2 re-render, no gate changes, no file mutated.**
`render_s2.py` and `run_ocr_pipeline.py` are unchanged; the S2 store is untouched.

## Why R4a cannot start

R4a re-keys S2 rendering off the **leaf-keyed S1 sidecars**. Its precondition (ordering
`R3-apply ─► R4a`; tracker §2: "S1 sidecars leaf-keyed on disk") is that R3-apply has already
migrated the S1 store. **R3-apply is blocked and never ran** — see
`docs/BLOCKED-leafrekey-R3-apply-2026-06-14.md`. The R4a prompt's own injected "Prior session
context" states this explicitly: *"R3-apply status (2026-06-14): BLOCKED — DO NOT START R4a YET."*

Re-rendering S2 against the current (filename-keyed, pre-rekey) S1 would produce a stem pattern
R4b cannot join on, and would burn the bounded one-cell-at-a-time disk budget on output that must
be thrown away once R3-apply lands. Starting now would create exactly the mixed-state store the
R3-apply Phase 0 global gate exists to prevent.

## Verification (primary sources, this run)

1. **Git** — R3-apply produced no `--apply` commit. Only R3-build landed (`47c3dd73` = tool +
   dry-run). Latest commit `9fc8aea7` is the R3-apply BLOCKED record. Tracker §0: R3-apply = `◐
   blocked 2026-06-14 — no apply`; R4a = `☐ not started`.
2. **Disk (the untracked ground truth — VER-01)** — sampled the S1 sidecar store
   (`reports/s1-sidecars`, 41,135 page sidecars): every primary-engine page sidecar still uses the
   `page_NNNN.json` filename stem with `canonical_leaf_id` **absent**. The store is NOT leaf-keyed.
   (144 leaf-stemmed sidecars exist — vol_11's separate P1 v4-model migration, commit `d0c01173`,
   unrelated to R3-apply.)
3. **BLOCKED-R3-apply doc** — confirms "No `--apply` was run. No file was mutated."; the 14
   anomalies are NOT a manifest data problem (corrected 2026-06-14): 5 are resolved `gaps[]`
   records the migration doesn't yet recognize, 2 are all-black scans.

## What unblocks R4a

R3-apply must complete first (its own unblock path, from `docs/BLOCKED-leafrekey-R3-apply-2026-06-14.md`):

1. **Make the migration `gaps[]`-aware** so the 5 recovered-gap pages (vol_01 p96/p97, vol_10
   p356/p359/p366 — resolved `gaps[]` records, P2 recovered-gap model) are recognized instead of
   flagged. Tool/accessor change, NOT a `raw/` manifest edit. (vol_10's "duplicate `ia_leaf_id`s"
   are the expected cross-namespace alt-vs-primary collision — by design, leaf_num is unique.)
2. Decide the 2 all-black scans (vol_03 p398, vol_04 p183): re-fetch from IA and/or `resolve_leaf`
   body-leaf preference.
3. Re-run the migration dry-run to `anomaly 0 / dup-sha-fanout 0`, then per-cell `--apply`.

Only then is "S1 sidecars leaf-keyed on disk" true and R4a may run.

## What was NOT done this run

- No edits to `build/tools/ocr_pipeline/render_s2.py` or `run_ocr_pipeline.py`.
- No S2 staging dir created; no cell re-rendered; no quarantine; no purge. The S2 store
  (~93 GB) is untouched. Disk free on C: ~76 GB (unchanged).
- No engine invoked (C1 holds trivially — nothing ran).
