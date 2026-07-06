> **RESOLVED 2026-06-14.** Both apply-path bugs are fixed test-first and committed, and all 3 held cells
> have landed clean on disk. (1) up-shift source clobber → snapshot-before-write, `6ca1e9e4`. (2) a SECOND
> bug found while applying — the orphan-quarantine loop ran AFTER the rekey writes and clobbered migrated
> sidecars at up-shift top-boundary stems → quarantine orphans in Phase A, `927e8a1f`. Final on-disk:
> tesseract vol_05 500/500, tesseract vol_10 491/491, kraken vol_10 491/491; tesseract vol_11 (a bug-(2)
> victim from a prior run) recovered from quarantine + re-applied 499/499. Whole-corpus sweep: 0
> wrongly-quarantined corpus sidecars across all 16 cells; no engine invoked (zero re-OCR). R3-apply is
> complete (16/16); R4a is unblocked. See `docs/BUILD_PLAN_leaf_rekey.md` §0 + the R3-apply acceptance
> bullet for the full record. The section below is the original block report, kept for the audit trail.

# BLOCKED — leaf-rekey R3-apply: 3 up-shift cells hit a tool data-corruption bug

**Date:** 2026-06-14 (R3-apply live run)
**Step:** R3-apply (`prompts/2026-06-14-0840-leafrekey-R3-apply-run.md`)
**Outcome:** 13 of 16 work-cells migrated + verified. **3 cells HELD** — `tesseract vol_05`,
`tesseract vol_10`, `kraken vol_10` — because the migration tool's `--apply` transaction
**corrupts contiguous up-shift relocation chains**. No `--apply` was run on those 3 cells.

This is NOT the same block as `docs/BLOCKED-leafrekey-R3-apply-2026-06-14.md` (that was the
Phase-0 `gaps[]` anomaly gate, now cleared). This is a newly-found bug in the apply path,
discovered by the pre-apply collision gate this prompt required (C3 / VER-01 — verify the
tool's claims against the source before the first live run).

---

## TL;DR

- `migrate_s1_to_leaf_key.py` `--apply` processes rekey plans in **ascending image-stem order**
  and **re-reads each source sidecar from disk at apply time** (`_apply_rekey_plan`, line ~387:
  `record = _read_json(old_sidecar)` where `old_sidecar = pages_dir / f"{plan.old_stem}.json"`).
- For a contiguous **up-shift** chain (content moves to a HIGHER page number, e.g. `+8`), the move
  that writes `page_0459.json` runs **before** the plan that needs to read `page_0459.json` as its
  own source — so the source is overwritten before it is read. The earlier page's OCR propagates
  to the later stem and the later page's true OCR is destroyed.
- The **dry-run cannot see this** — it only produces plans; the corruption is purely an apply-time
  ordering effect.
- **Down-shifts are safe** (read-before-overwrite under ascending order); **in-place rekeys and
  duplicate-sha "relocations" are safe** (no distinct content at the target).

## The 3 affected cells (the only up-shift chains in the corpus)

| Cell | relocated | shift | verdict |
|---|---|---|---|
| tesseract vol_05 | 50 | up `+8` (page_0451→0459, 0452→0460, …) distinct content | HELD |
| tesseract vol_10 | 124 | up `+8` (page_0368→0376, …) distinct content | HELD |
| kraken vol_10 | 124 | up `+8` (same image lineage as tesseract vol_10) | HELD |

Evidence (distinct content per stem, so a real shift not a duplicate-sidecar leftover):
- vol_05: on-disk `page_0451.json` sha `7b3f2669…`, `page_0459.json` sha `320340a8…`,
  `page_0467.json` sha `fe2f3d84…` — all different.
- vol_10: `page_0368` sha `dd2ca417…` vs target `page_0376` sha `43691dfc…` — different.

## Why each safe cell is safe (the gate that separates them)

The pre-apply gate (`.tmp_audit/r3_apply_safe_cells.py::guard` and the corpus sweep) flags a cell
unsafe iff **any plan's `new_stem` equals a later plan's `old_stem`** (overwrite-before-read) OR
**two plans share a `new_stem`** (duplicate target). Both conditions are the exact preconditions
for the apply transaction to lose or mis-route content. Across all 16 work-cells only the 3 above
trip it. The recovered-overwrite vector (a relocation clobbering an in-place "recovered" stem) is
covered by the duplicate-target check, which was empty everywhere.

- **vol_11 (239 relocations) is safe** — every relocation is a **down-shift** (`page_0265→0261`),
  which reads before it overwrites under ascending order. 0 unsafe pairs. Applied + verified.
- **tesseract/kraken vol_02 (2 relocations) are safe** — those are **duplicate-sha leftovers**
  (`page_0254.json` and `page_0258.json` carry the identical sha), so overwriting the target with
  identical content loses nothing. Applied + verified.

## The fix (tool change — CODEX-05, test-first per TEST-16)

The apply transaction must not let a write clobber an unread source. Two viable fixes:

1. **Snapshot then write (preferred, direction-agnostic).** Before the write loop in `apply_cell`,
   read every source sidecar record (and copy/stage every source raw artifact) into memory or a
   staging area keyed by `old_stem`. Then `_apply_rekey_plan` consumes the snapshot instead of
   re-reading `pages_dir / old_stem.json`. Sidecars are ~0.5 MB; a full cell snapshot is ~250 MB —
   acceptable, or stage to a temp dir to bound memory.
2. **Order the moves safely.** Process relocation plans so no `new_stem` is written before its use
   as an `old_stem` — i.e. topologically sort the old→new edges (equivalently: apply up-shift
   chains in **descending** image order, down-shifts ascending). Cyclic shifts (rare/none here)
   still need a temp-rename, so fix #1 is the robust general answer.

Add a RED test first: a fixture cell with a 3-link distinct-content up-shift chain; assert each
migrated stem carries the sha of the image now at that stem (today this test fails — the middle
link is corrupted). Then implement, then re-enable the 3 held cells.

## After the fix — re-enable the 3 cells

`--apply --engine tesseract --volume 5`, `--engine tesseract --volume 10`,
`--engine kraken --volume 10`. Verify on disk (relocated→0, anomaly 0, every body leaf with a
sidecar carries `canonical_leaf_id` + `source_payload_sha256` matching `resolve_leaf`). The journals
make re-runs idempotent; the stores are gitignored — verify on disk, do not commit migrated data.

## What was done vs held

- **Migrated + on-disk-verified (13 cells):** tesseract vol_01/02/03/04/11; kraken vol_01/02/03/04/05/11;
  surya vol_01; kraken-greek vol_01.
- **Held (3 cells):** tesseract vol_05, tesseract vol_10, kraken vol_10 — pending the tool fix above.
- No engine was invoked during any apply (zero re-OCR — verified by code path + unchanged OCR bytes).
