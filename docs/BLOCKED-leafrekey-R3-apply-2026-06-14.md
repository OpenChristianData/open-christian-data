# BLOCKED — leaf-rekey R3-apply (Phase 0 gate not cleared)

**Date:** 2026-06-14 (autonomous overnight run; **diagnosis corrected later the same day after
maintainer pushback — see the CORRECTION banner**)
**Step:** R3-apply (`prompts/2026-06-13-1503-leafrekey-R3-apply-migration.md`)
**Outcome:** HARD STOP at the Phase 0 gate. **No `--apply` was run. No file was mutated.**

---

## UPDATE (2026-06-14): Phase 0 gate CLEAR — only `--apply` remains (next session)

Both blockers are resolved:

1. **`gaps[]`-aware fix** committed `239369f2` (test-first, full suite 3192 green):
   `nsh_leaf_model.gap_by_sha` + recovered-gap (migrated byte-identical to a fresh emit) and
   needs-alternate classes. Cleared the 5 recovered-gap anomalies.
2. **2 black pages recovered** from alternate IA items, committed `6e852969` (maintainer
   decision "black pages need alternate pages"): vol_03 p398 ← `newschaffherzog04jackgoog`
   leaf 420 (printed header "398" read); vol_04 p183 ← `newschaffherzog13haucgoog` leaf 202
   (content continuity p182→p183→p184 verified). Each leaf updated in-place in `leaves[]` with
   a `provenance` block (alternate-sourced body leaf, like vol_10's haucgoog leaves); black
   images backed up to `vol_NN/_superseded/`; both manifests schema-valid; the repo's
   `nsh-ocr-gate` pre-commit hook re-OCR'd samples and passed.

**Real-data dry-run is now fully clean: anomaly 0, dup-sha-fanout 0, needs-alternate 0**
(recovered-gap 10; the 2 recovered pages are need-first-OCR — the pipeline will OCR the new
images). **The only remaining step is `--apply` per cell (most-cautious first, verify on disk),
to be run in a new session.** The diagnosis below stands.

---

## CORRECTION (2026-06-14, supersedes the first cut of this doc)

The first version of this doc claimed the 14 dry-run anomalies were a **manifest data-loss
problem** — "5 real body pages dropped from the vol_01/vol_10 manifests" + "vol_10 has duplicate
`ia_leaf_id`s (internally inconsistent)". **Both claims were wrong.** They came from reading
`leaves[]` through the `nsh_leaf_model` accessor and never checking the manifest's `gaps[]` array
(a VER-01 miss — trusted the secondary view, not the primary file). Verified facts:

- **The 5 "0-leaf" pages are NOT dropped — they are RESOLVED `gaps[]` records** (the P2
  recovered-gap model, commit `0df0e3ac`). Each carries `status: resolved`, full image
  provenance, and a running-header-verified recovery note. They were missing from the *primary*
  scan and recovered from the **haucgoog alternate IA scan**. Example (vol_01 p96):
  `status=resolved`, `resolved_from=newschaffherzog11haucgoog`,
  *"recovered from newschaffherzog11haucgoog leaf 128; running-header OCR confirmed header=96
  (exact match)"*.
- **vol_10's duplicate `ia_leaf_id`s (0388, 0390) are by design**, not an inconsistency: an
  alternate-sourced leaf (ia_item `newschaffherzog41haucgoog`) collides on `ia_leaf_id` with a
  primary-scan leaf, but `leaf_num` is unique (leaf 382 vs 388; 384 vs 390). The P2 commit
  message states this explicitly: *"an alternate-sourced body leaf's ia_leaf_id collides with a
  primary id; leaf_num never does."*

**The real block is a TOOL/accessor gap, not a data problem:** `resolve_leaf` (via
`leaf_by_sha` → `leaves_view`) consults only `leaves[]`. A gap page is still listed in
`page_order.json` as a body OCR input and *was* OCR'd, so the migration hashes its image, finds
the sidecar, calls `resolve_leaf`, gets 0 leaves, and reports "anomaly." The gap page legitimately
has no `leaf_num` (it is a `gaps[]` record, not a leaf).

**The earlier recommendation to "re-author the dropped leaves" was actively wrong** — it would have
created duplicate leaves for pages already resolved in `gaps[]`, corrupting the recovered-gap model.
The HARD STOP (no `--apply`, nothing mutated) was the correct action and is what prevented that.

The body below is the corrected analysis.

---

## TL;DR (corrected)

- Full dry-run reproduced **14 anomalies / 0 dup-sha-fanout** across 52 cells. They are **7 distinct
  physical pages** in two classes:
  1. **5 "recovered-gap" pages (benign).** vol_01 p96/p97, vol_10 p356/p359/p366 are resolved
     `gaps[]` records (recovered from the haucgoog alt scan, header-verified). The migration flags
     them only because `resolve_leaf` doesn't read `gaps[]`. **No data fix needed.**
  2. **2 all-black failed scans (the only real data item).** vol_03 p398, vol_04 p183 are uniform
     black images (mean=0.0) sitting on real body leaves (leaf 420 / 201); their black sha collides
     with the all-black blank front/back-matter leaves, so `resolve_leaf` returns 9 / 3.
- **Fix = a tool/accessor change (make the migration `gaps[]`-aware) + a decision on the 2 black
  leaves.** Not a canonical `raw/` manifest edit.

## Why each class trips the tool (corrected)

### Class 1 — recovered-gap pages (benign; tool-awareness gap)

The current manifests carry a top-level `gaps[]` array (schema 4.1.0). For each of these 5 pages
there is a `gap_record` with `page_num`, `sha256`, `local_path` (the `page_NNNN.jpg` on disk),
`status: resolved`, `resolved_from`, and a `provenance` block (source item, source leaf,
derivation). The page's OCR sidecar is valid OCR of the recovered image (its
`source_payload_sha256` matches the gap record's sha).

`resolve_leaf` returns 0 because it indexes `leaves[]` only. The migration needs to treat a
body-namespace image whose sha resolves to a `gaps[]` record as a **recovered-gap page**, not an
anomaly. Options for the tool (supervised decision):
- key the gap-page sidecar on `(page_num, sha)` from the gap record (gaps have no `leaf_num`), or
- classify gap-page sidecars as a distinct migration category (carry them as-is; they are not
  leaf-keyed body leaves), or
- exclude gap pages from `page_order.json`'s OCR-input set if their OCR is not wanted.

Any of these is a code change in `migrate_s1_to_leaf_key.py` / `nsh_leaf_model.py` (CODEX-05),
**not** an edit to `vol_NN.manifest.json`.

### Class 2 — all-black failed scans (the real data item)

vol_03 p398 (leaf 420) and vol_04 p183 (leaf 201) are real body leaves whose image is a uniform
black scan (mean=stdev=0.0). The black sha is byte-identical to several all-black blank
front/back-matter leaves, so `resolve_leaf` returns 9 (vol_03) / 3 (vol_04). The body leaf already
exists and is the correct target; the blocker is the blank-matter collision. Fix options:
- **re-fetch** p398 / p183 from IA so the image carries real page content (changes its sha,
  removes the collision); and/or
- give `resolve_leaf` a "prefer the single body leaf when the others are non-body" semantics
  (a tested R0-1 invariant — change with care).

(vol_03 p398 is a known-black page to the maintainer; vol_04 p183 surfaced here as a second one.)

## Evidence (primary sources on disk)

### Dry-run
`.tmp_audit/r3_dryrun_20260614_023621.log` — 14 anomalies, 0 dup-sha-fanout. Reproduce:
`PYTHONPATH=<repo-root> py -3 build/tools/ocr_pipeline/migrate_s1_to_leaf_key.py`

### The 7 pages

| Class | Vol | Page | Disk file | sha (16) | Real state | Pixels |
|---|---|---|---|---|---|---|
| recovered-gap | 01 | 96 | page_0096.jpg | e11717a6560b40bc | `gaps[]` resolved (haucgoog leaf 128) | real text, header "96" |
| recovered-gap | 01 | 97 | page_0097.jpg | af085d806929be08 | `gaps[]` resolved (haucgoog leaf 129) | real text, header "97" |
| recovered-gap | 10 | 356 | page_0356.jpg | 60e2e207d69f4d14 | `gaps[]` resolved | real text |
| recovered-gap | 10 | 359 | page_0359.jpg | ccf95d45c61a2b6f | `gaps[]` resolved | real text |
| recovered-gap | 10 | 366 | page_0366.jpg | a984da2981b5b159 | `gaps[]` resolved | real text |
| black scan | 03 | 398 | page_0398.jpg | a5ccbb7f1b43… | body leaf 420; sha collides w/ blank matter | all-black (mean 0.0) |
| black scan | 04 | 183 | page_0183.jpg | d26424e9c562… | body leaf 201; sha collides w/ blank matter | all-black (mean 0.0) |

Diagnostics (read-only): `.tmp_audit/r3_anomaly_diagnose.py`, `r3_gap_truth.py` (current-vs-snapshot
+ `gaps[]`), `r3_make_thumbs.py` + `thumbs/`. Provenance of the recovered gaps: P2 commit
`0df0e3ac` message; gap records in `raw/internet-archive/schaff-herzog-pages/vol_{01,10}.manifest.json`.

## Recommended resolution (for a supervised session)

1. **Make the migration `gaps[]`-aware** (the actual unblock) so recovered-gap pages are recognized
   instead of flagged as anomalies. Pick the keying/handling per "Class 1" above. Tool change
   (CODEX-05), no manifest edit.
2. **Decide the 2 black scans** (vol_03 p398, vol_04 p183): re-fetch from IA and/or adjust
   `resolve_leaf` body-leaf preference. Small, isolated.
3. **Re-run the dry-run** to a clean `anomaly 0 / dup-sha-fanout 0`, then per-cell `--apply`. The
   clean cells (everything except vol_01/03/04/10) already show `anomaly 0`.

## What was NOT done

- No `--apply`. No manifest, page_order, sidecar, raw-artifact, or store file was mutated.
- No clean cells were migrated (the Phase 0 gate is global, per the prompt).
- The migration tool is sound for the clean cells; the two issues above are the only blockers.
