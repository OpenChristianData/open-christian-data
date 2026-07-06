# Phase 1 Checkpoint — vol01/02 Engine-Panel Build

**Status: VERIFIED STATE + PLAN. Phase 2/3 proceeding.** This is the pre-Phase-3
checkpoint required by the build task. All counts below are from a live disk
survey (`.tmp_audit/phase1_survey.py`, 2026-06-05), not the task's prior table.

## Decision brief

- The task's CURRENT STATE table was stale in two material ways. **Surya vol_01 is
  85/491 present (406 missing), not ~170/491.** Surya vol_02 is 477/488 in-range
  (11 missing: pages 1-8, 253-255), not "full". Verified against disk.
- **Surya is the binding constraint.** It is the mandatory WCT layout authority
  (`wct_builder._surya_rendering` raises without it), so the 417 Surya-less pages
  (406 vol_01 + 11 vol_02) **cannot be reconciled** until Surya runs. At ~185s/page
  that is ~21h of compute — a multi-run unattended job, not an in-session task.
- **Azure is not in the panel because no Azure→rendering-v1 path exists.** The data
  (491+488 cloud sidecars) is present and all schema enums accept it
  (`azure_read` in sidecar-manifest-v1 + rendering-v1; `azure-ai-vision` in WCT).
  The fix is a new S1 normalizer mirroring rich-ABBYY ingest (Azure is an imported
  word-geometry engine), then `render_s2` produces the rendering. Not a flag flip.
- **kraken-greek is NOT an independent family** — its `ENGINE_FAMILY` is `kraken`,
  so it collapses into the kraken block (matches the findings doc). It improves
  Greek-span text recovery; it adds no independent vote. There is no existing
  Greek-page detector — page selection was manual. A text-based detector (scan
  all-page ABBYY/Tesseract/Azure raw_text for Greek codepoints) will drive it.
- Plan: (1) build+wire+verify Azure now (bounded, the named blocker); (2) start
  the Surya background fill (417 pages, resumable); (3) detect+run kraken-greek on
  Greek pages; (4) run the full chain WITH Azure on every Surya-covered page and
  emit the surviving measurements; (5) honest attempted/succeeded/failed report.

## Verified coverage (S1 sidecar page counts on disk)

| Engine lineage          | vol_01 | vol_02 | Notes |
|-------------------------|-------:|-------:|-------|
| surya-py312-v1          |     85 |    488 | vol_01 **406 missing**; vol_02 11 missing in [1,488] |
| tesseract-py314-v1      |    492 |    488 | full |
| kraken-py312-v1         |    491 |    488 | full |
| kraken-greek-py312-v1   |     11 |      0 | Greek pages only; family=kraken |
| ia-abbyy-v1             |    539 |    536 | full (incl. extra leaves) |
| azure (cloud sidecar)   |    491 |    488 | full; NOT yet a rendering |
| **reconciled outputs**  |     10 |      0 | only the measurement-run pages |

Expected body pages: vol_01 = 491, vol_02 = 488 (~979 total).

## Gap list — what must be OCR'd

- **Surya vol_01:** 406 pages — `1-9, 88-99, …, 472-491` (present band ≈ 10-87,
  100-471). The long pole.
- **Surya vol_02:** 11 pages — `1-8, 253-255`.
- **kraken-greek:** Greek-bearing pages in both volumes, to be detected from
  existing all-page OCR text (threshold ≥ N Greek-script chars). vol_01 has 11
  done; the rest of vol_01 and all of vol_02 to assess.
- **No re-OCR of covered pages** — all runners are skip-existing.

## Azure wiring — decision and status

- **Status: NOT wired (no producer exists).** Confirmed by grep: `azure_read`
  appears only in `wct_builder._FAMILY_MAP` and the schema enum, never in a
  producer.
- **Decision: add `build/parsers/s1_azure_normalizer.py`** (TDD + test file, per
  OCD parser gate) that reads `raw/.../vol_NN/page_NNNN.azure.json` and emits
  `sidecar-page-v1` records with per-word `bbox_native` + 0-100 confidence and a
  `sidecar-manifest-v1` with `engine_family: "azure_read"`,
  `source_lineage_id: "azure-ai-vision-v1"`. `render_s2.render_manifest` then
  produces the rendering-v1; `wct_builder` maps `azure_read → azure-ai-vision`.
- Wire as an imported engine in `run_ocr_pipeline.py` and add the lineage to
  `drive_reconciliation_chain.DEFAULT_ENGINES`.
- No schema change required (enums already accept the values) → no
  `_generated_enums.py` regen needed.

## Estimated long-pole compute

- Surya: 417 missing pages × ~185s/page ≈ **21.4 h** wall-clock (CPU, no GPU),
  background + resumable. This is why Phase 3 full coverage spans multiple runs.
- Azure normalize: imported (no inference) — minutes for both volumes.
- kraken-greek: fast (seconds/page), bounded to detected Greek pages.
- Chain (WCT+reconcile) per Surya-covered page: subprocess-bound, ~562 pages
  reconcilable now (those with Surya); the rest fill in as Surya completes.

## Sequence (proceeding, no approval wait)

1. **Azure:** TDD `s1_azure_normalizer.py` → normalize vol_01+02 → render S2.
2. **Verify gate:** run the chain on page_0010 with Azure; diff vs known-good
   `reports/reconciled/vol_01/page_0010.json`; confirm `azure-ai-vision` is a
   family in the reconciled output. Stop-and-fix if absent.
3. **Phase 2:** start Surya background fill (417 pages); detect + run kraken-greek.
4. **Phase 3:** drive the full chain (complete panel incl. Azure) over every
   Surya-covered page; emit family-independence (incl. Azure block test) + ECE
   calibration. M2/M3 NOT reported (circular — settled).
5. **Report:** `docs/BUILD_COMPLETION_vol01_02.md` with attempted/succeeded/failed
   per volume per engine, and an explicit statement of the Surya-pending remainder.
