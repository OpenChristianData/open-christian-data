# NSH render + WCT — full-coverage expansion plan (2026-06-16)

**Status: PLAN ONLY. No mass render or WCT build has run. Heavy compute is gated on maintainer approval (see §6 STOP/GATE).**

This plan expands the S2 **render** and the **WCT** (word-confusion table) toward every
engine/source × every volume (1–13) of the New Schaff-Herzog (NSH) corpus. It is the precondition
for the deferred `word-confusion-table-v1` schema flip (leaf-rekey R-final session 3). Every count
below comes from a disk census run this session against the gitignored `reports/` stores — the
ground truth — not from a doc.

Census commands (all read-only, run 2026-06-16):
- `py -3 build/tools/ocr_pipeline/ocr_inventory.py status` → `.tmp_audit/ocr_inventory_full_2026-06-16.txt` (leaf-keyed coverage SSOT)
- `.tmp_audit/census_s2_wct.py` → S2 render **shape** per cell (per-page vs legacy-monolith) + WCT clid presence
- `.tmp_audit/census_s1_raw.py` → **raw** S1 page-file counts per lineage/volume, ignoring leaf-key state (catches sidecars the inventory can't see)
- `.tmp_audit/size_wct.py` → WCT rebuild page-totals + wall-clock model
- `PYTHONPATH=. py -3 build/tools/ocr_pipeline/verify_leaf_keying.py --volumes 1-13` → R6b full-chain verifier (OVERALL PASS per the R-final.2 handoff; see §5)

---

## Decision brief

- **Full 13-volume × 4-engine WCT coverage is NOT reachable from existing sidecars — large OCR gaps
  block it.** The WCT engine set `DEFAULT_ENGINES = {tesseract, ia-abbyy-v1, azure, kraken}` has all
  four engines on disk for only **6 volumes (01–05, 10 = 2,992 body pages)**. Tesseract **and** kraken
  S1 are entirely absent for vols **06, 07, 08, 09, 12, 13**; azure is absent for 12/13 and thin on
  10/11; kraken is thin on 05/11. Closing those needs **new OCR** (a separate, large compute item),
  not a zero-re-OCR join.
- **Recommendation: do this in two gated tranches.** Tranche 1 = rebuild the full 4-engine WCT for the
  6 already-covered volumes (zero re-OCR) — **~21 h at 8 workers / ~10–13 h at 16 workers**. This alone
  unblocks the `word-confusion-table-v1` flip for the volumes that have a real panel. Tranche 2 (OCR the
  missing tesseract/kraken/azure lanes for vols 06–13, then WCT them) is a much bigger, separately-costed
  job that needs an explicit "yes, OCR these" decision.
- **The cheap render-gap fill is genuinely small for the current engine set.** S2 renderings are already
  per-page-leaf-keyed for every `DEFAULT_ENGINES` cell that has S1, **except vol_11 `ia-abbyy-v1`** (still
  legacy-monolith). One bounded `validate_schema=False` re-render fixes it. The other 17 monolith cells
  are surya (excluded from the WCT) or orphaned tesseract vols 06–09 (S1 deleted — see below).
- **The legacy tesseract vol_06–09 monolith renderings are stale orphans, not free coverage.** Their
  backing S1 `pages/` dirs are empty (`manifest.state.json` → `"emitted_pages": []`); the monolith refs
  point at sidecars that no longer exist anywhere under `reports/`. Treat tesseract 06–09 as "needs OCR,"
  same as 12/13 — do not mistake the orphan monoliths for usable input.
- **Engine-set call for the WCT (load-bearing): keep `DEFAULT_ENGINES` as the panel; leave the alternate
  ABBYY lineages (dli/haucgoog/c1–c4) reference-only for this expansion.** They roughly triple per-page
  alignment cost and alignment risk for confusion-coverage gain that is unmeasured. Recommend a
  bounded A/B on one volume before committing them — not a blind 13-volume inclusion (§3).

---

## 1. Coverage census matrix (disk-verified 2026-06-16)

Body-page denominator per volume ≈ the strongest engine's leaf-keyed S1 file count (ABBYY is present in
all 13). "S2 shape" is per the `DEFAULT_ENGINES` cells only.

### 1a. S1 sidecars — `DEFAULT_ENGINES`, leaf-keyed page-file counts (raw disk)

| Vol | body | tesseract | ia-abbyy-v1 | azure | kraken | strong engines* |
|----:|----:|----:|----:|----:|----:|:--|
| 01 | 500 | 500 | 496 | 491 | 500 | 4 |
| 02 | 497 | 497 | 497 | 488 | 497 | 4 |
| 03 | 500 | 500 | 500 | 463 | 500 | 4 |
| 04 | 500 | 500 | 500 | 470 | 500 | 4 |
| 05 | 504 | 500 | 504 | 474 | **340** | 4 (kraken thin) |
| 06 | 494 | **0** | 494 | 454 | **0** | 2 (abbyy+azure) |
| 07 | 502 | **0** | 502 | 439 | **0** | 2 |
| 08 | 498 | **0** | 498 | 470 | **0** | 2 |
| 09 | 499 | **0** | 499 | 492 | **0** | 2 |
| 10 | 491 | 491 | 474 | **242** | 491 | 3–4 (azure thin) |
| 11 | 503 | 499 | 503 | **30** | **29** | 2 (tess+abbyy) |
| 12 | 599 | **0** | 599 | **0** | **0** | 1 (abbyy only) |
| 13 | 208 | **0** | 208 | **0** | **0** | 1 (abbyy only) |

\* "strong" = S1 file count ≥ 60% of the body denominator. **Bold = absent or thin.**

All present S1 sidecars carry `canonical_leaf_id` (page0 clid = `Y` for every non-zero cell in the raw
census) — they are R3-keyed and join-ready.

### 1b. S2 render shape — `DEFAULT_ENGINES` cells

Shape classes: **per-page** = `pages/page_NNNN.rendering-v1.json` (current, leaf-keyed) · **monolith** =
single `rendering-v1.json` at the cell root (legacy, 0 clid) · **absent** = no S2 dir.

| Vol | tesseract | ia-abbyy-v1 | azure | kraken |
|----:|:--|:--|:--|:--|
| 01–05 | per-page | per-page | per-page | per-page (05 partial) |
| 06–09 | **monolith-ORPHAN** | per-page | per-page | absent |
| 10 | per-page | per-page | per-page (partial) | per-page |
| 11 | per-page | **MONOLITH** | per-page (30) | per-page (29) |
| 12–13 | absent | per-page (12) / per-page (13) | absent | absent |

Full shape tally across **all** lineages: **66 per-page cells, 18 monolith cells.** The 18 monoliths:
surya vols 02–11 (10 — excluded from the WCT panel), tesseract vols 06–09 (4 — **orphans**, S1 deleted),
vol_11 alternates `ia-abbyy-v1`/`dli`/`haucgoog-v1`/`haucgoog-c2` (4 — real S1, residual from the vol_11
BLOCKED case).

### 1c. WCT

| Vol | WCT pages on disk | clid present | state |
|----:|----:|----:|:--|
| 01 | 478 | **0/478** | predates R4b; **stale-content for ~553/944 across 01+02** (phantom-page rename) — rebuild, not stamp |
| 02 | 466 | **0/466** | same |
| 03–13 | 0 | — | **absent — never built** |

Total WCT today = **944 pages, 0 clid**, covering 2 of 13 volumes, built on the old 4-engine set only.

---

## 2. Gap inventory

**(a) Volumes with no S1 for a `DEFAULT_ENGINES` engine → needs NEW OCR (NOT zero-re-OCR coverage):**
- **tesseract:** vols 06, 07, 08, 09, 12, 13 absent. (06–09 have orphan monolith renderings whose S1 is
  gone — `reports/s1-sidecars/tesseract-py314-v1/vol_06/pages/` is empty, `manifest.state.json`
  `emitted_pages: []`. Re-OCR, not recovery — confirm no legacy copy survives before OCRing.)
- **kraken:** vols 06, 07, 08, 09, 12, 13 absent; vol_05 thin (340/504), vol_11 thin (29/503).
- **azure:** vols 12, 13 absent; vol_10 thin (242/495), vol_11 thin (30/503).
- ABBYY (`ia-abbyy-v1`) is complete enough on all 13 (vol_10 = 474/495 the only notable shortfall).

**(b) S2 cells absent or legacy-monolith → bounded re-render (cheap, `validate_schema=False`):**
- **For the current WCT engine set, exactly one cell matters: vol_11 `ia-abbyy-v1`** (monolith → per-page;
  S1 is 503/503 so it is a pure re-key, byte-identical, ~ms/page). Optionally vol_11 azure/kraken if those
  lanes are OCR'd later.
- Not needed for the WCT: surya monoliths (engine excluded), tesseract 06–09 orphan monoliths (no S1 — see
  (a)). Recommend quarantining the 4 tesseract orphan monoliths so they can't be mistaken for input.

**(c) WCT gaps:**
- **vol_01/02:** rebuild from scratch (stale-content + 0 clid). 944 pages.
- **vols 03, 04, 05, 10:** build from existing 4-engine S1. ~1,995 pages. (05 kraken-thin, 10 azure-thin —
  the WCT degrades gracefully; thin engines simply attest fewer positions.)
- **vol_11:** buildable now as a tess+abbyy panel (2 geometry engines) after the (b) re-render; full panel
  waits on kraken+azure OCR.
- **vols 06–09:** buildable now only as an abbyy+azure panel; a real 4-engine WCT waits on tesseract+kraken OCR.
- **vols 12–13:** not a meaningful WCT (single engine) until OCR'd.

---

## 3. Engine-set decision for the WCT (recommend)

**Question:** should the alternate ABBYY lineages (`ia-abbyy-dli-v1`, `ia-abbyy-haucgoog-v1`,
`ia-abbyy-haucgoog-c1..c4-v1`) feed the WCT alongside `DEFAULT_ENGINES`, or stay reference-only?

| | Keep `DEFAULT_ENGINES` only (recommend) | Add alternate ABBYY lineages |
|---|---|---|
| Confusion coverage | 4 engines, 2 families (tesseract, abbyy, azure, kraken) | richer same-edition disagreement, but all alt lineages collapse to the **abbyy family** — under family-level voting (invariant #6) they add **0 independent family votes**, only intra-family confusion pairs |
| Alignment risk | low — already the proven path | higher — alt scans are different physical scans, leaf-keyed via R7 content-aligner (`canonical_leaf_id`, not sha); ~7% per-cell classified-unmapped leaves must be excluded per leafmap |
| Per-page compute | baseline (~200 s/page measured) | up to ~3× more engines to merge → materially higher `_align_engines` cost per page (progressive MSA is roughly linear in engine count, super-linear in token divergence) |
| Code changes | none | `drive_reconciliation_chain.DEFAULT_ENGINES` + `_single_rendering_paths`; `wct_builder.build_from_files` already fails closed on leaf disagreement (R4b) but the alt cells need their leafmap `unmapped_classified` set honored as a skip-list; the ABBYY geometry lane in `wct_builder` is still filename-keyed with an R7 TODO |

**Recommendation: keep `DEFAULT_ENGINES` as the WCT panel for this expansion.** The alternate lineages
add intra-family confusion richness but **no family-vote independence** (the signal the corrector's
auto-accept gate actually reads), at triple the per-page cost and added alignment risk. Before committing
them, run a **bounded A/B on one volume** (e.g. vol_03: build the WCT with and without the alt lineages,
diff confusion-pair coverage and per-page wall-clock). Decide from that measurement — not blind inclusion.
This keeps the alt lineages as the "intended future consumers" they are today without paying for them
unmeasured.

---

## 4. Performance + parallelism strategy

**Cost pole (code-read, not yet profiled live):** `wct_builder.build_wct_page` → `_align_engines`
(`build/lib/wct_builder.py:830`). `_align_engines` is a progressive multiple-sequence alignment: each
geometry-bearing engine merges into the spine via `_merge_engine`, which scores token pairs with
`_weighted_edit` (`:218`, an O(len_a × len_b) weighted DP per pair), then `_detect_merges` runs
pairwise `confusion_distance`. So consensus geometry and weighted edit are **not separable** — the
geometry merge *is* driven by the weighted-edit table. The measured **~200 s/page** (4-engine, 2026-06-16)
is dominated by this alignment, not by I/O (schemas are pre-loaded per worker via `_init_worker`; the
per-page disk reads are sidecar JSON, not images).

**Strategy: parallel run, not hot-path optimization (for now).** The driver already parallelizes well:
- `ProcessPoolExecutor` with `--throttle {4,8,none}` → 4 / 8 / `cpu_count` workers
  (`drive_reconciliation_chain.py:59`, `:600`). This machine = **16 cores**.
- **Per-page atomic writes + resume:** `skip_existing` (default on) skips any page whose reconciled
  output exists (`:451`); `--force` reprocesses. A crash loses only in-flight pages; re-running the same
  command continues. `KeyboardInterrupt` cancels queued pages and lets running ones finish (`:639`).
- Worker priority is set to IDLE (throttle 4) or BELOW_NORMAL (throttle 8) so an unattended overnight run
  doesn't starve the desktop (`:64`).

**Wall-clock estimate (from `.tmp_audit/size_wct.py`, 200 s/page):**

| Scope | pages | 8 workers | 16 workers |
|---|----:|----:|----:|
| **Tranche 1** — 4-engine WCT, vols 01–05, 10 (zero re-OCR) | 2,992 | **~20.8 h** | **~10.4 h** |
| + vol_11 (tess+abbyy) | +503 | ~24.3 h | ~12.1 h |
| + vols 06–09 as abbyy+azure (no new OCR) | +1,993 | ~38.1 h | ~19.1 h |
| ALL 13 at full 4-engine (requires the §2a OCR first) | 6,295 | ~43.7 h | ~21.9 h |

Notes: 16-worker throughput is optimistic if alignment is memory-bound or the OS de-prioritizes workers;
treat the 8-worker column as the planning number for an at-desk run and 16/throttle=none as an unattended
overnight ceiling. vols 06–09/11 pages are faster than 200 s (fewer engines), so those rows are upper
bounds. **Before a multi-day commit, profile `build_wct_page` on ~20 real pages** (cheap) to confirm the
200 s figure on the current engine renderings and to decide whether a hot-path optimization (e.g. caching
the weighted-edit table, or capping alignment on pathological pages) is worth it before Tranche 2.

---

## 5. Sequenced execution plan

Each phase has a runnable command, a cost, what's resumable, and the verification that proves it.
**No phase past Phase 0 runs without the §6 gate.**

**Phase 0 — render-gap fill (cheap, minutes).** Re-render vol_11 `ia-abbyy-v1` monolith → per-page
(`rekey_s2_renderings.py` / `render_s2.py` with `validate_schema=False`, byte-identical). Quarantine the
4 tesseract vol_06–09 orphan monoliths (move under `reports/s2-renderings/.quarantine/legacy-monolithic/`).
*Resumable:* per-cell. *Verify:* `census_s2_wct.py` shows vol_11 `ia-abbyy-v1` = per-page; no orphan
tesseract monoliths remain at active paths.

**Phase 1 — Tranche 1 WCT rebuild, vols 01–05, 10 (zero re-OCR, ~21 h @ 8w).** Per volume:
`PYTHONPATH=. py -3 build/tools/ocr_pipeline/drive_reconciliation_chain.py --volumes N --throttle 8`
(omit `--engines` → `DEFAULT_ENGINES`). vol_01/02 need `--force` (overwrite the stale WCT). *Resumable:*
per-page (`skip_existing`); re-run the same command to continue after a crash. *Verify per volume:* WCT
page count == body denominator; `census_s2_wct.py` clid > 0 (the new builder emits `canonical_leaf_id`
natively); then the full-chain gate below.

**Phase 2 — re-run R6b green + flip-readiness.**
`PYTHONPATH=. py -3 build/tools/ocr_pipeline/verify_leaf_keying.py --volumes 1-13` → OVERALL PASS with WCT
**no longer PENDING** for the rebuilt volumes (`.tmp_audit/r6b_chain.txt` is the last green baseline).
`.tmp_audit/r7_flip_audit.py` for the per-page clid gate where applicable. *This is the gate that unblocks
the schema flip.*

**Phase 3 — unblock the `word-confusion-table-v1` flip (R-final session 3, NOT this plan).** Once Phase 2
is green for the WCT-covered volumes, the flip session can add `canonical_leaf_id` to the WCT schema's
`required` array (today it is an optional property). **This plan stops at producing a green, clid-bearing
WCT; the flip itself is out of scope (do not expand into it).**

**Phase 4 (Tranche 2, separate decision) — OCR the missing lanes, then WCT vols 06–13.** Gated on a
"yes, OCR these" call (§6). Order: (a) OCR tesseract + kraken for vols 06–09, 12, 13 and the thin azure/
kraken cells via `run_ocr_pipeline.py` (S1) — **large, separately-costed; kraken is the slow engine**;
(b) render S2 per-page; (c) WCT those volumes; (d) re-run R6b. This is where the bulk of the remaining
compute lives and why it is a distinct tranche.

---

## 6. Open questions + STOP/GATE

**Decisions needed from the maintainer before any heavy run:**

1. **Tranche scope.** Approve **Tranche 1 only** (6 volumes, zero re-OCR, ~21 h @ 8w) now, and defer
   Tranche 2 (OCR vols 06–13) to a separate decision? (Recommended.)
2. **Engine set.** Keep `DEFAULT_ENGINES` for the WCT and leave alternate ABBYY reference-only, pending the
   one-volume A/B (§3)? Or include the alt lineages now?
3. **OCR the missing S1?** Tranche 2 requires **new** tesseract+kraken OCR for vols 06–09, 12, 13 (the
   orphan monoliths are not recoverable input). Confirm that's wanted, and confirm no legacy S1 copy
   survives off-`reports/` before re-OCRing (zero-re-OCR law applies only to sidecars that still exist).
4. **vol_01/02: rebuild vs accept stale.** Confirm the stale 944-page WCT should be `--force`-rebuilt
   (recommended — it is stale-content + 0 clid) rather than kept.
5. **Compute budget / scheduling.** Overnight at-desk (throttle 8, ~21 h spans ~one night + part of a day)
   vs. unattended background (throttle 4, longer but desk-friendly) vs. throttle none (16 workers, ~10–13 h
   but saturates the machine)?
6. **Profile first?** Run the cheap ~20-page `build_wct_page` profile to confirm 200 s/page before
   committing the multi-hour Tranche 1?

**STOP / GATE — do not start the heavy rebuild until the maintainer approves the scope, engine set, and
compute budget above.** The census and dry-runs in this plan are read-only and done; Phase 0 (the
minutes-scale render-gap fill) may proceed on a simple go; Phases 1–4 are the expensive work and are
blocked here by design.
