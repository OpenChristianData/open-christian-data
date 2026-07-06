# BLOCKED — leaf-rekey R4b (precondition not met: S2/S1 not leaf-keyed)

**Date:** 2026-06-14 (autonomous overnight run)
**Step:** R4b (`prompts/2026-06-13-1505-leafrekey-R4b-wct-recon-rekey.md`)
**Outcome:** Did NOT start. Precondition unmet. **No code changed, no WCT/reconciliation/gold
tool edited, no fixture updated.** `build_wct.py`, `drive_reconciliation_chain.py`,
`align_ccel_to_wct.py`, `measure_reconciliation.py`, `extract_ccel_page_gold.py`, and
`build_gold_sample.py` are all unchanged.

## Why R4b cannot start

R4b re-keys the WCT `page_id`, the cross-engine join, the reconciliation chain, and gold
alignment onto `canonical_leaf_id`. That join key only exists once the upstream artifacts carry
it. The ordering is `R3-apply ─► R4a ─► R4b`:

- **R3-apply** (leaf-keys the S1 sidecar store) is **blocked and never ran** —
  `docs/BLOCKED-leafrekey-R3-apply-2026-06-14.md`. The 14 dry-run anomalies are NOT a manifest
  data problem (corrected 2026-06-14): 5 are resolved `gaps[]` records (recovered-gap model) the
  migration's `resolve_leaf` doesn't yet read, and 2 are all-black scans (vol_03 p398, vol_04
  p183). Fix = make the migration `gaps[]`-aware + decide the 2 black scans; not a `raw/` edit.
- **R4a** (re-keys S2 renderings off the leaf-keyed S1) **could not start** because R3-apply
  never produced leaf-keyed S1 — `docs/BLOCKED-leafrekey-R4a-2026-06-14.md`.
- So R4b's own precondition (tracker §2: cross-engine join on `canonical_leaf_id`) is unmet:
  neither the S1 sidecars nor the S2 renderings carry `canonical_leaf_id` to join on.

The R4b prompt's own injected "Prior session context" states this explicitly:
*"R4a status (2026-06-14): BLOCKED — DO NOT START R4b YET … The blocking chain is: R3-apply
(blocked, no apply) → R4a (cannot start) → R4b (cannot start)."*

Making the R4b code changes now would key `build_wct`/reconciliation/gold join logic on a
field absent from every sidecar in the live store. The acceptance check ("WCT page_id +
cross-engine join on `canonical_leaf_id`; suite green") would pass only against synthetic
leaf-keyed fixtures while the real store has zero leaf-keyed pages — a false green relative to
production data (a VER-01 trap), and it would break the WCT build for anyone running it against
the current store. The leaf-id assignment for the affected pages can also still shift once the
upstream manifest fix lands, so building join logic against that id space now is premature.

## Verification (primary sources, this run)

1. **Git** — no R3-apply `--apply` commit, no R4a S2 commit. Recent commits are docs-only:
   `113791f9` (R4a deferred), `9fc8aea7` (R3-apply blocked), `cb231f3a` (R3-apply precondition).
   Tracker §0: R3-apply = `◐ blocked`; R4a = `☐ not started`; R4b = `☐`.
2. **Disk (untracked ground truth — VER-01)** — re-verified this run, not trusted from the
   prior BLOCKED docs. Grep across the entire S1 sidecar store
   (`reports/s1-sidecars`, 41,309 JSON incl. manifests; ~41,135 page sidecars):
   **0 page sidecars contain `canonical_leaf_id`.** Sampled primary-engine pages
   (`azure-ai-vision-v1/vol_01/pages/page_00{10,11,12}.json`) all return
   `'canonical_leaf_id' in sidecar == False` and still use the `page_NNNN.json` filename stem.
   The store is NOT leaf-keyed. (vol_11's 144 leaf-stemmed sidecars are its separate P1 v4-model
   migration, commit `d0c01173`, unrelated to R3-apply.)
3. **BLOCKED-R4a / BLOCKED-R3-apply docs** — confirm S2 store untouched and S1 store still
   filename-keyed; 14 anomalies unresolved.

## What unblocks R4b

The full upstream chain must land first, in order:

1. **R3-apply** — make the migration `gaps[]`-aware so the 5 recovered-gap pages (vol_01 p96/p97,
   vol_10 p356/p359/p366 — resolved `gaps[]` records) are recognized instead of flagged (a
   tool/accessor change, NOT a `raw/` manifest edit; vol_10's "duplicate `ia_leaf_id`s" are the
   expected cross-namespace alt-vs-primary collision, by design); decide the 2 all-black scans
   (vol_03 p398, vol_04 p183 — re-fetch and/or `resolve_leaf` body-leaf preference); re-run the
   dry-run to `anomaly 0 / dup-sha-fanout 0`; then per-cell `--apply` (zero re-OCR). Only
   then are the S1 sidecars leaf-keyed on disk.
2. **R4a** — bounded volume-by-volume S2 re-render keyed on `(leaf, sha, sidecar sha)`. Only
   then are the S2 renderings leaf-keyed.
3. **R4b** — only then may the WCT/reconciliation/gold join be re-keyed on `canonical_leaf_id`.

## Current state of the R4b targets (untouched, for the next session)

Hardcoded `page_NNNN` grep on `build/tools/ocr_pipeline/` (18 raw matches) — all are
docstrings, example CLI paths, or display-stem building, NOT join keys:
- `build_wct.py:17,19` — docstring example `--source-image-path … page_0010.jpg` / `--output … page_0010.json`
- `drive_reconciliation_chain.py:5` — docstring describing the `page_0010` slice
- `generate_je_gold.py:57` — docstring noting the `page_id` example value `page_0010`
- `reviewer_server.py:56,61` — display stem construction (`"vol_01_page_0060"` → `"page_0060"`)

These are the residuals R4b's grep-clean acceptance targets; none were modified this run.

## What was NOT done this run

- No edits to any WCT / reconciliation / gold tool or test or fixture.
- No `page_id` / join-key change; no hardcoded-id removal.
- No engine invoked; no store touched. The S2 store (~93 GB) is unchanged.
