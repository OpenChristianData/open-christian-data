# A4 Codex Round 1 - Schema And Reconcile Re-verification

## Verdict

- Schema re-validation: PASS for all 12 `original/vol_*.json` records against `schemas/v1/reconciled_record.schema.json`.
- DEFECT: record-level `meta.pd_anchor` is not consistently aligned with the catalog `pd_anchor_decision.chosen_rendering`. Vols 3-8 and 10-12 use IA as the per-record anchor, while the catalog globally chooses CCEL. That may be a defensible per-volume source decision, but the catalog does not express a per-volume anchor override.
- `source_pages[].rendering_id` and `attested_by[]` resolve after applying known short aliases: `ccel-thml -> ccel/schaff/encyclopedia/1908-1914/thml`, `ia-ocr -> ia/schaff/encyclopedia/1908-1914/ocr`.
- `attested_by[]` subset check: PASS for every block.
- Alias judgement: the short IDs are intentional in migration/parser tooling, but they are not machine-declared in `catalog.json`; integrity currently depends on out-of-band alias knowledge. That is a design defect for referential checks.

## Catalog IDs And Aliases Used

- Catalog `pd_anchor_decision.chosen_rendering`: `ccel/schaff/encyclopedia/1908-1914/thml`
- Catalog rendering IDs: `ccel/schaff/encyclopedia/1908-1914/thml`, `ia/schaff/encyclopedia/1908-1914/ocr`
- Known aliases applied in this audit: `ccel-thml` -> `ccel/schaff/encyclopedia/1908-1914/thml`, `ia-ocr` -> `ia/schaff/encyclopedia/1908-1914/ocr`

## Per-Record Checks

| Vol | Record | Schema | meta.pd_anchor | Canonical anchor | Anchor status | Blocks | Null source pages |
|---:|---|---|---|---|---|---:|---:|
| 1 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_01.json` | PASS | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | matches_catalog_chosen_rendering_via_alias | 899 | 0 |
| 2 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_02.json` | PASS | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | matches_catalog_chosen_rendering_via_alias | 895 | 0 |
| 3 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_03.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 625 | 15 |
| 4 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_04.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 752 | 10 |
| 5 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_05.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 760 | 6 |
| 6 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_06.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 619 | 4 |
| 7 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_07.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 536 | 8 |
| 8 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_08.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 618 | 15 |
| 9 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_09.json` | PASS | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | matches_catalog_chosen_rendering_via_alias | 592 | 0 |
| 10 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_10.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 658 | 8 |
| 11 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_11.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 525 | 7 |
| 12 | `data/reference/schaff/encyclopedia/1908-1914/original/vol_12.json` | PASS | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | matches_volume_source_but_not_catalog_global_anchor | 678 | 7 |

## Check 1 - Schema Re-validation

PASS. `jsonschema.Draft202012Validator` reported zero errors for all 12 records.

## Check 2 - `pd_anchor` Consistency

DEFECTS / unresolved design mismatch:
- vol 3: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 4: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 5: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 6: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 7: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 8: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 10: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 11: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.
- vol 12: record `ia-ocr` canonicalises to `ia/schaff/encyclopedia/1908-1914/ocr`, catalog chosen rendering is `ccel/schaff/encyclopedia/1908-1914/thml`; status `matches_volume_source_but_not_catalog_global_anchor`.

## Check 3 - `source_pages.rendering_id` Referential Integrity

| rendering_id in source_pages | Count | Catalog exact? | Alias resolves? | Canonical |
|---|---:|---|---|---|
| `ccel-thml` | 2386 | False | True | `ccel/schaff/encyclopedia/1908-1914/thml` |
| `ia-ocr` | 5771 | False | True | `ia/schaff/encyclopedia/1908-1914/ocr` |

## Check 4 - `attested_by` Referential Integrity

| rendering_id in attested_by | Count | Catalog exact? | Alias resolves? | Canonical |
|---|---:|---|---|---|
| `ccel-thml` | 2386 | False | True | `ccel/schaff/encyclopedia/1908-1914/thml` |
| `ia-ocr` | 5771 | False | True | `ia/schaff/encyclopedia/1908-1914/ocr` |

## Check 5 - `attested_by` Subset Of `source_pages`

PASS. Every block has `attested_by[]` as a subset of its own `source_pages[].rendering_id` values.
