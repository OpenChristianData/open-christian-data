# BLOCKED — leaf-rekey R7 (precondition not met: R6a verifier not built)

**Date:** 2026-06-14 (autonomous overnight run)
**Step:** R7 (`prompts/2026-06-13-1507-leafrekey-R7-abbyy-alignment.md`)
**Outcome:** Did NOT start ABBYY alignment. Precondition unmet. **No normalizer re-run, no
GZ→leaf offset computed, no WCT geometry rekey, no test added.** `build/parsers/`,
`build/lib/`, and `build/tools/ocr_pipeline/` are unchanged this run.

## The injected "Prior session context" is STALE — the block has MOVED

The R7 prompt's injected context (written by the early-2026-06-14 R6a epilogue) states the
whole chain is gated on R3-apply ("R3-apply (blocked, no apply) → R4a → R4b → R6a → R7") and
that "0 of ~41,135 S1 page sidecars carry `canonical_leaf_id`." **Both claims are now false.**
Verified against primary sources this run (VER-01):

- **R3-apply is COMPLETE** — `4d5e2641` + the data work; tracker §0 R3-apply row = ☑
  ("all 16 work-cells migrated + on-disk-verified 2026-06-14"). Two apply-transaction bugs were
  found and fixed test-first (`6ca1e9e4` up-shift snapshot-before-write; `927e8a1f`
  orphan-quarantine-before-write).
- **R4a is DONE** — `8e7c80a9` ("R4a S2 per-page leaf-rekey -- both gates + line-id reseed +
  expected-set purge"), 2026-06-14 19:36, full suite green (3206 passed),
  Co-Authored-By Claude Opus 4.8, author openchristiandata. Touched `render_s2.py`,
  `run_ocr_pipeline.py`, + `tests/test_r4a_s2_leaf_rekey.py` (319 lines).
- **`canonical_leaf_id` IS now on disk** — sampled `reports/s1-sidecars/tesseract-py314-v1/
  vol_01/pages/page_0001.json` → `canonical_leaf_id = 37`. The store is leaf-keyed for migrated
  successful sidecars. The old "0 of 41,135" no longer holds.

So the chain has advanced two steps past where the injected context claims. The real block is
not at R3-apply; it is at **R6a**.

## Why R7 cannot start now

R7's stated precondition (prompt header, tracker §0a ordering) is:
`… ► R4b ► R6a ► R7`. R7 builds the ABBYY/alternate-source lane *on top of* a leaf-keyed,
verified primary chain. The two steps between R4a and R7 have not been built:

- **R4b** (WCT / reconciliation / gold join re-keyed on `canonical_leaf_id`; `rendering_line_id`
  reseeded; hardcoded `page_NNNN` removed) — **not built.** No commit; working tree has no R4b
  code. R7 step 5 ("rekey the ABBYY-fed WCT geometry lane left as a TODO in R4b") presupposes
  R4b created that lane — it does not exist yet.
- **R6a** (primary-chain verifier `verify_leaf_keying.py` + TEST-08 + pre-run logging +
  pre-commit wiring) — **not built.** Verified this run: `build/tools/ocr_pipeline/
  verify_leaf_keying.py` does not exist. R7's acceptance ("WCT geometry lane closed", "suite
  green", subsuming the haucgoog-hole case) assumes the primary verifier exists to extend; it
  does not.

Starting R7 before R6a would mean aligning ABBYY onto a primary chain whose leaf-keying has
never been verified end-to-end — exactly the silent-mis-map risk (PIPE-29) R7 is meant to
guard against, with no verifier to catch a regression.

## What actually changed since the early-morning blocked runs

The early-2026-06-14 autonomous runs correctly wrote blocked docs for R4a / R4b / R6a while
R3-apply was still blocked. Later the same day a session unblocked and completed R3-apply
(`4d5e2641`) and then landed R4a (`8e7c80a9`). The R4a→R7 scheduled tasks then fired in
sequence against prompt contexts that still reflected the morning's blocked state.

**Net effect: the project is NOT stuck. R4b is the actual ready-to-start next step** (its
precondition — R3-apply ☑ + R4a done — is now met). The bottleneck moved down the chain, it
did not disappear.

## What unblocks R7

In order (each its own step / prompt / commit boundary):

1. **R4b** — `prompts/2026-06-13-1505-leafrekey-R4b-wct-recon-rekey.md`. **Ready now.** Its own
   injected "Prior session context" is also stale ("blocked — R3-apply unmet") — an R4b session
   following its "Read first" protocol will hit the corrected tracker §0 + newest
   `LAST_SESSION_*.md` (both made accurate by this run) and self-correct.
2. **R6a** — `prompts/2026-06-13-1506-leafrekey-R6a-primary-verifier.md`. After R4b lands. Build
   `verify_leaf_keying.py`, wire pre-commit, add pre-run logging, run the gated quarantine
   retention purge. (Do NOT purge the R3-apply quarantine dirs before R6a gates it.)
3. **R7** — this step. After R6a passes on the primary chain.

## What was NOT done this run

- No ABBYY lineage selected; no `probe_abbyy_confidence.py --compare` run; no GZ→leaf offset
  computed; no PIPE-29 running-header content-verify.
- No `s1_abbyy_normalizer.py` re-run; no `canonical_leaf_id` stamped on ABBYY sidecars.
- No WCT geometry ABBYY lane rekeyed (it does not exist yet — R4b creates it).
- No engine invoked; no store touched. Docs-only run.
