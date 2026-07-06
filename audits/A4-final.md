# Phase A4 — Schema and Reconcile Re-verification: Final (Convergent) Verdict

**Work handle:** `reference/schaff/encyclopedia/1908-1914`
**Reviewers:** Claude + Codex (independent passes, round 1)
**Date:** 2026-05-20
**Records checked:** 12 (`original/vol_01.json` – `original/vol_12.json`)
**Total blocks:** 8,157

---

## Pass summary

Both passes are in full agreement on all five checks. No divergence.

| Check | Claude | Codex |
|---|---|---|
| A4.1 Schema re-validation | VERIFIED 12/12 | VERIFIED 12/12 |
| A4.2 pd_anchor consistency | DEFECT 9/12 mismatch | DEFECT 9/12 mismatch |
| A4.3 source_pages rid integrity | VERIFIED (with alias) | VERIFIED (with alias) |
| A4.4 attested_by integrity | VERIFIED (with alias) | VERIFIED (with alias) |
| A4.5 attested_by ⊆ source_pages | VERIFIED 0 violations | VERIFIED 0 violations |

---

## A4.1 — Schema re-validation

**Schema:** `schemas/v1/reconciled_record.schema.json`
**Validator:** `jsonschema` (Python, Draft-2020-12)

All 12 records pass schema validation. The schema does not constrain `rendering_id` values to a catalog-registered enumeration, so alias strings (`ccel-thml`, `ia-ocr`) pass without error. This is a schema design gap (A4-D03), not a data error.

**Verdict: VERIFIED — 12/12 records pass.**

---

## A4.2 — pd_anchor consistency

The catalog (`catalog.json`) declares `ccel/schaff/encyclopedia/1908-1914/thml` as the global `pd_anchor_decision.chosen_rendering`.

| Vol | meta.pd_anchor | Canonical (via alias) | Status |
|---:|---|---|---|
| 1 | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | CONSISTENT |
| 2 | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | CONSISTENT |
| 3 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 4 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 5 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 6 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 7 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 8 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 9 | `ccel-thml` | `ccel/schaff/encyclopedia/1908-1914/thml` | CONSISTENT |
| 10 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 11 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |
| 12 | `ia-ocr` | `ia/schaff/encyclopedia/1908-1914/ocr` | MISMATCH |

**3/12 consistent. 9/12 mismatch.**

The records are correct: CCEL files for vols 3–8 and 10–12 are stub files (~125KB with no article content). The reconciler correctly identified `ia-ocr` as the effective pd_anchor for those volumes. The catalog's global `chosen_rendering` is misleading because it names a rendering that provides no article content for 9 of 12 volumes. The catalog schema has no per-volume pd_anchor override mechanism.

**Verdict: DEFECT (A4-D01) — catalog's global pd_anchor conflicts with per-record pd_anchor for 9/12 volumes. Records are correct; catalog declaration is misleading.**

---

## A4.3 — source_pages rendering_id referential integrity

All unique `rendering_id` values in `source_pages` across all 12 records:

| rendering_id | Count | In catalog (exact)? | Alias resolves? | Canonical |
|---|---:|---|---|---|
| `ccel-thml` | 2,386 | No | Yes | `ccel/schaff/encyclopedia/1908-1914/thml` |
| `ia-ocr` | 5,771 | No | Yes | `ia/schaff/encyclopedia/1908-1914/ocr` |

**Verdict: VERIFIED (with alias) — 0 unresolvable rendering_ids. Alias is undocumented (A4-D02).**

---

## A4.4 — attested_by referential integrity

Identical distribution to A4.3: `ccel-thml` 2,386; `ia-ocr` 5,771. No unresolvable entries.

**Verdict: VERIFIED (with alias) — same alias caveat as A4.3.**

---

## A4.5 — attested_by ⊆ source_pages

Every block has exactly one rendering in `source_pages` and the same rendering in `attested_by`. The 1:1 relationship is consistent across all 8,157 blocks and all 12 volumes.

Violations: 0.

**Verdict: VERIFIED — 0 violations.**

---

## Carry-forward findings for A7

| ID | Severity | Check | Description |
|---|---|---|---|
| A4-D01 | HIGH | A4.2 | Catalog declares `ccel/schaff/encyclopedia/1908-1914/thml` as the global pd_anchor, but 9/12 records use `ia-ocr` as their effective anchor because CCEL files for those volumes are stubs with no article content. The catalog has no per-volume pd_anchor override mechanism. Fix: add a per-volume pd_anchor table to the catalog, or update `chosen_rendering` to document the volume-conditional logic. Records do not need to change. |
| A4-D02 | MEDIUM | A4.3, A4.4 | Rendering_id alias mapping (`ccel-thml` → `ccel/schaff/encyclopedia/1908-1914/thml`; `ia-ocr` → `ia/schaff/encyclopedia/1908-1914/ocr`) is out-of-band knowledge not documented in the schema, catalog, or any project file. Automated referential integrity checks must carry this alias table externally. Fix: add an `aliases` field to the catalog, or use full rendering IDs in the reconciled records. |
| A4-D03 | LOW | A4.1 | Schema does not constrain `rendering_id` to catalog-registered values. An arbitrary string passes schema validation. Fix: add an `$ref` or `enum` constraint, or add a post-schema referential integrity check to the validation pipeline. |

---

## Exit status

| Check | Verdict | Evidence |
|---|---|---|
| A4.1 Schema re-validation | VERIFIED | 12/12 records pass jsonschema validation |
| A4.2 pd_anchor consistency | DEFECT | 9/12 records use ia-ocr; catalog declares ccel universally |
| A4.3 source_pages rid integrity | VERIFIED (with alias) | 2 unique rendering_ids; both resolve via alias |
| A4.4 attested_by integrity | VERIFIED (with alias) | 0 unresolvable entries across 8,157 blocks |
| A4.5 attested_by ⊆ source_pages | VERIFIED | 0 violations |

**A4 final: complete. 3 carry-forwards to A7 (1 HIGH, 1 MEDIUM, 1 LOW). Full Claude–Codex agreement.**
