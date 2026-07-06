# BLOCKED — leaf-rekey R6a (precondition not met: primary chain not leaf-keyed)

**Date:** 2026-06-14 (autonomous overnight run)
**Step:** R6a (`prompts/2026-06-13-1506-leafrekey-R6a-primary-verifier.md`)
**Outcome:** Did NOT build. Precondition unmet. **No verifier written, no pre-commit wiring,
no runner/orchestrator logging changed, no test added.** `build/tools/ocr_pipeline/` is
unchanged this run; no `verify_leaf_keying.py` was created.

## Why R6a cannot build now

R6a delivers the primary-chain verifier (TEST-08) that asserts every S1 sidecar + S1 manifest
page + S2 rendering carries `canonical_leaf_id`, that no sha was re-OCR'd, that cross-engine
joins are leaf-keyed, and that each S2 rendering dir equals the current manifest expected set.
None of those invariants can hold yet because the upstream chain that *produces* leaf-keyed
artifacts has not run. The ordering is `R3-apply ─► R4a ─► R4b ─► R6a`:

- **R3-apply** (leaf-keys the S1 sidecar store) is **blocked and never ran** —
  `docs/BLOCKED-leafrekey-R3-apply-2026-06-14.md`. The R3-build dry-run's 14 anomalies are NOT a
  manifest data problem (corrected 2026-06-14): 5 are resolved `gaps[]` records (recovered-gap
  model) the migration's `resolve_leaf` doesn't yet read; 2 are all-black scans (vol_03 p398,
  vol_04 p183). Fix = make the migration `gaps[]`-aware + decide the 2 black scans; not a `raw/` edit.
- **R4a** (re-keys S2 renderings off the leaf-keyed S1) **could not start** —
  `docs/BLOCKED-leafrekey-R4a-2026-06-14.md`. S1 store still filename-keyed.
- **R4b** (re-keys WCT / reconciliation / gold join) **could not start** —
  `docs/BLOCKED-leafrekey-R4b-2026-06-14.md`. No `canonical_leaf_id` to join on.

The R6a prompt's own injected "Prior session context" states this explicitly:
*"R4b status (2026-06-14): BLOCKED — DO NOT START R6a YET … The full blocking chain is:
R3-apply (blocked, no apply) → R4a (cannot start) → R4b (cannot start) → R6a (cannot start)."*

## Why building it now would be actively harmful, not just premature

Two concrete failures, beyond a false-green-against-fixtures (VER-01) trap:

1. **The verifier would trigger its own documented hard stop.** R6a's autonomous-mode hard stop
   is "verifier fails assertion (a) — missing `canonical_leaf_id` — across > 5 cells." On the
   current store the assertion fails on **every** primary cell (every vol × tesseract / kraken /
   surya / kraken-greek / azure), because 0 of ~41,135 page sidecars carry the field. That is the
   stop condition by design ("indicates a prior step left un-migrated artifacts; stop rather than
   masking the root cause").
2. **Wiring it into pre-commit (acceptance item 2) would break commits repo-wide.** A scoped
   pre-commit gate that runs the verifier would fail on the un-migrated store and block **every**
   commit — including the epilogue commits of this very run and any unrelated work in the repo.
   Shipping a gate that the live data cannot pass is a regression, not an enforcement win.

The verifier must be authored against a store where the invariant *can* pass, so its passing is
real evidence and the pre-commit gate is safe to wire. That state only exists after R3-apply →
R4a → R4b land.

## Verification (primary sources, this run)

1. **Git** — no R3-apply `--apply` commit, no R4a S2 commit, no R4b WCT commit. Recent commits
   are docs-only: `9826c226` (R4b blocked), `113791f9` (R4a deferred), `9fc8aea7` (R3-apply
   blocked), `cb231f3a` (R3-apply precondition). Tracker §0: R3-apply = `◐ blocked`;
   R4a = `☐ not started`; R4b = `☐ not started`; R6a = `☐`.
2. **Disk (untracked ground truth — VER-01)** — re-verified this run, not trusted from the prior
   BLOCKED docs. Sampled primary-engine pages
   (`azure-ai-vision-v1/vol_01/pages/page_00{10,11}.json`,
   `tesseract-py314-v1/vol_01/pages/page_0010.json`) — all return
   `'canonical_leaf_id' in sidecar == False` and still use the `page_NNNN.json` filename stem.
   Consistent with the R4b run's full-store grep (0 of ~41,135 page sidecars carry the field).
   The store is NOT leaf-keyed. (vol_11's 144 leaf-stemmed sidecars are its separate P1 v4-model
   migration, commit `d0c01173`, unrelated to R3-apply.)
3. **BLOCKED-R4b / BLOCKED-R4a / BLOCKED-R3-apply docs** — confirm the S1 store is still
   filename-keyed, the S2 store untouched, and the 14 anomalies unresolved.

## What unblocks R6a

The full upstream chain must land first, in order:

1. **R3-apply** — make the migration `gaps[]`-aware so the 5 recovered-gap pages (vol_01 p96/p97,
   vol_10 p356/p359/p366 — resolved `gaps[]` records) are recognized instead of flagged (a
   tool/accessor change, NOT a `raw/` manifest edit; vol_10's "duplicate `ia_leaf_id`s" are the
   expected cross-namespace alt-vs-primary collision, by design); decide the 2 all-black scans
   (vol_03 p398, vol_04 p183 — re-fetch and/or `resolve_leaf` body-leaf preference); re-run
   the dry-run to `anomaly 0 / dup-sha-fanout 0`; then per-cell `--apply` (zero re-OCR). S1
   sidecars then carry `canonical_leaf_id` on disk.
2. **R4a** — bounded volume-by-volume S2 re-render keyed on `(leaf, sha, sidecar sha)`. S2
   renderings then leaf-keyed.
3. **R4b** — WCT / reconciliation / gold join re-keyed on `canonical_leaf_id`; hardcoded
   `page_NNNN` removed.
4. **R6a** — only then build `verify_leaf_keying.py` (`--primary-only` default), wire it to
   pre-commit, add the pre-run `vol_NN: N leaves | R reused | K to OCR` logging, and run the
   gated `.bak` retention purge.

## What was NOT done this run

- No `verify_leaf_keying.py` created; no test added; no pre-commit hook edited.
- No pre-run logging added to the four primary runners, `render_s2.py`, or `run_ocr_pipeline.py`.
- No `.bak` retention purge run (gated on the verifier passing, which is unreachable).
- No engine invoked; no store touched.
