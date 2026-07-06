# Phase A4 — Claude Round 1 audit
# Schema and reconcile re-verification

**Work handle:** `reference/schaff/encyclopedia/1908-1914`
**Reviewer:** Claude (independent pass)
**Date:** 2026-05-20
**Records checked:** 12 (`original/vol_01.json` – `original/vol_12.json`)
**Total blocks:** 8,157

Script used: `_a4_checks.py` (written, run, deleted per constraint).

---

## Context

The catalog (`data/reference/schaff/encyclopedia/1908-1914/catalog.json`) declares:
- `pd_anchor_decision.chosen_rendering`: `ccel/schaff/encyclopedia/1908-1914/thml`
- Two renderings registered: `ccel/schaff/encyclopedia/1908-1914/thml` (pd_anchor) and `ia/schaff/encyclopedia/1908-1914/ocr` (pd_attestor)

The reconciled records use short aliases (`ccel-thml`, `ia-ocr`) instead of the catalog's full rendering IDs. This alias question is the central referential-integrity issue in A4.

---

## A4.1 — Schema re-validation

**Schema:** `schemas/v1/reconciled_record.schema.json`
**Validator:** `jsonschema` (Python)

| Record | Result |
|---|---|
| vol_01.json | VALID |
| vol_02.json | VALID |
| vol_03.json | VALID |
| vol_04.json | VALID |
| vol_05.json | VALID |
| vol_06.json | VALID |
| vol_07.json | VALID |
| vol_08.json | VALID |
| vol_09.json | VALID |
| vol_10.json | VALID |
| vol_11.json | VALID |
| vol_12.json | VALID |

**Verdict: VERIFIED — 12/12 records pass schema validation.**

No schema errors. The schema does not constrain `rendering_id` values to a specific enumeration (no `$ref` to catalog), so alias values pass schema validation even though they don't match catalog rendering IDs.

---

## A4.2 — pd_anchor consistency

Comparing `meta.pd_anchor` in each record against the catalog's declared pd_anchor rendering ID.

| Record | meta.pd_anchor | Resolves to | Catalog pd_anchor | Verdict |
|---|---|---|---|---|
| vol_01.json | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | CONSISTENT |
| vol_02.json | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | CONSISTENT |
| vol_03.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_04.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_05.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_06.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_07.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_08.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_09.json | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | CONSISTENT |
| vol_10.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_11.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |
| vol_12.json | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | `ccel/schaff/encyclopedia/1908-1914/thml` | MISMATCH |

**Consistent: 3/12. Mismatch: 9/12.**

### Interpretation

The catalog declares `ccel/schaff/encyclopedia/1908-1914/thml` as the universal pd_anchor. But for vols 3–8 and 10–12, the CCEL XML files are stub files (~125 KB, essentially empty structure with no article content). The reconciler correctly chose `ia-ocr` as the effective pd_anchor for those volumes because there is no CCEL content to anchor to.

The catalog's `pd_anchor_decision.rationale` says: "CCEL ThML preserves entry structure **where text is available**." This acknowledges CCEL is unavailable for some volumes, but `chosen_rendering` still names CCEL globally — no per-volume pd_anchor table exists.

**Verdict: DEFECT (A4-D01)** — the catalog's global pd_anchor declaration conflicts with the per-record pd_anchor for 9/12 volumes. Both the records and the catalog contain true information; the conflict is that there is no mechanism for per-volume pd_anchor variation in the catalog schema.

**Separate but related — alias mismatch:** `meta.pd_anchor = 'ccel-thml'` (records) vs `'ccel/schaff/encyclopedia/1908-1914/thml'` (catalog). This is an alias/naming convention issue, not a content mismatch for the 3 consistent volumes. The alias is out-of-band knowledge — the schema does not enforce or document it.

---

## A4.3 — source_pages rendering_id referential integrity

All unique `rendering_id` values found in `source_pages` across all 12 records:

| rendering_id | In catalog? | Resolves via alias? | Resolves to | Verdict |
|---|---|---|---|---|
| `ccel-thml` | No | Yes | `ccel/schaff/encyclopedia/1908-1914/thml` | RESOLVABLE |
| `ia-ocr` | No | Yes | `ia/schaff/encyclopedia/1908-1914/ocr` | RESOLVABLE |

**Verdict: VERIFIED (with alias) — 2/2 unique rendering_ids are resolvable via known alias mapping.**

However, this depends on out-of-band knowledge. The alias mapping (`ccel-thml` → full ID) is not documented in any schema, catalog field, or project file. A machine that only reads the reconciled record and catalog cannot verify referential integrity without this knowledge.

**Defect A4-D02 (MEDIUM):** Alias mapping is undocumented. The schema allows any string for `rendering_id`, and the alias is a silent convention. If the alias table is not persisted (e.g., in the catalog as an `aliases` field), the referential integrity check cannot be automated correctly.

---

## A4.4 — attested_by referential integrity

All unique `attested_by` rendering_ids across 8,157 blocks:

| rendering_id | In catalog? | Resolvable? |
|---|---|---|
| `ccel-thml` | No | Yes (alias) |
| `ia-ocr` | No | Yes (alias) |

Total attested_by entries: 8,157 (one per block — each block is attested by exactly one rendering).
Unresolvable attested_by entries: 0.

**Verdict: VERIFIED (with alias) — same alias caveat as A4.3 applies.**

---

## A4.5 — attested_by ⊆ source_pages rendering_ids

For each block: `attested_by` must be a subset of `{rendering_id for sp in source_pages}`.

- Total blocks checked: 8,157
- Violations: 0

**Verdict: VERIFIED — 0 violations.**

Every block has exactly one rendering in `source_pages` and the same rendering in `attested_by`. The 1:1 relationship is consistent across all volumes and blocks.

---

## Defect summary

| ID | Severity | Check | Description |
|---|---|---|---|
| A4-D01 | HIGH | A4.2 | Catalog declares a single global pd_anchor (`ccel/schaff/encyclopedia/1908-1914/thml`) but 9/12 records use `ia-ocr` as their pd_anchor. The catalog has no per-volume pd_anchor mechanism. Records are correct; catalog declaration is misleading. |
| A4-D02 | MEDIUM | A4.3, A4.4 | Rendering_id alias mapping (`ccel-thml` → `ccel/schaff/encyclopedia/1908-1914/thml`; `ia-ocr` → `ia/schaff/encyclopedia/1908-1914/ocr`) is out-of-band knowledge. Not documented in schema, catalog, or any project file. Automated referential integrity cannot be verified without this knowledge. |
| A4-D03 | LOW | A4.1 | Schema does not constrain `rendering_id` to catalog-registered values. Schema validation passes even for arbitrary strings in `source_pages[].rendering_id` and `attested_by[]`. |

---

## Exit status

| Check | Verdict | Evidence |
|---|---|---|
| A4.1 Schema re-validation | VERIFIED | 12/12 records pass jsonschema validation |
| A4.2 pd_anchor consistency | DEFECT | 9/12 records use ia-ocr; catalog declares ccel universally |
| A4.3 source_pages rid integrity | VERIFIED (with alias) | 2 unique rids; both resolve via alias mapping |
| A4.4 attested_by integrity | VERIFIED (with alias) | 0 unresolvable entries |
| A4.5 attested_by ⊆ source_pages | VERIFIED | 0 violations |

**A4 Claude round 1: complete.**
