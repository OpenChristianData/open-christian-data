# DESIGN — NSH manifest model v5: OCR-tolerant reconciliation + witness model

**Date:** 2026-06-11 (rev 2 — reframed after the scandata-OCR correction)
**Status:** DRAFT. Rev 1 (the "53 holes" witness-model draft) was built on a false
premise — see §0. Rev 2 corrects the problem statement and the fix order.
**Supersedes (on approval):** the v4 leaf-sequence model in
`docs/DESIGN_nsh_leaf_sequence_manifest.md` (P0/P0.5/P1/P2). v4 stays live until v5
is approved + migrated.
**Inputs that shaped this rev:** the P2 migration run; a Codex adversarial review
(`.tmp_audit/witness-model-adversarial-output.log`, verdict ACCEPT WITH CHANGES);
and the maintainer correction that IA scandata `pageNumber` is OCR output carrying
3↔8 / 2↔9 digit confusion (`reference_nsh_page_number_verification`).

---

## 0. The real problem (corrected)

Rev 1 claimed 53 body pages across 7 volumes have no primary-scan leaf and so
cannot be placed. **That count was an artifact of a tool bug, not a corpus fact.**

The P2 migration tool built its scandata page→leaf map from IA's raw scandata
`pageNumber`. But that field is **IA's OCR of the printed page number**, and NSH
scans carry systematic 3↔8 / 2↔9 digit confusion. So whenever IA misread a page
number, the tool failed to find that page in scandata and flagged it a "hole."

Worked example (vol_10): scandata leaf 367 reports `pageNumber 843`; under 3→8
confusion that is printed page **343**. Leaf 380 reports `866` = **366**. Leaves
367–387 are pages 343–373 (OCR'd as 843–873). Those pages have real primary leaves
— the tool just couldn't match "343" to "843".

Reconciling the scandata **leaf set** (not its OCR'd numbers) against the
manifest's running-header-verified primary-page claims collapses the count:

| vol | alt-source recovered pages | interior scandata leaves unclaimed by a primary page | true holes (count upper bound) |
|---|---|---|---|
| 06 | 11 | 15 | 0 |
| 10 | 32 | 34 | 0 |
| 13 | 6 | 6 | 0 |
| 01 | 4 | 2 | 2 |
| 02 | 3 | 1 | 2 |
| 05 | 4 | 2 | 2 |
| 08 | 2 | 0 | 2 |
| **total** | **62** | | **≈ 8** |

(Count-level reconciliation per PIPE-29 is necessary, not sufficient — the residue
must be confirmed by content matching, §2. The true residue is ≤ 8 and may be
smaller or zero.)

**Two distinct problems were conflated:**
1. **The OCR-reconciliation bug (primary, high-value).** Hole detection must match
   scandata leaves to the manifest's verified page numbers with OCR tolerance
   (3↔8, 2↔9), never trust raw `pageNumber`. Fixing this resolves vols 06/10/13
   entirely and shrinks 01/02/05/08 to a tiny residue. **This is the real fix and
   it does not require a schema change.**
2. **The genuine-residue + model-cleanliness problem (secondary).** A handful of
   pages may still have no primary leaf (true never-scanned). Plus the existing v4
   model conflates position/provenance, which is why a recovered page with a real
   primary leaf but a bad primary image (the "9 cases") is awkward to represent.
   The witness model (§3) handles both cleanly — but it is now a smaller,
   optional improvement, not a forced rescue.

---

## 1. Fix the tool first (no schema change) — build-to-measure

Before any model change, fix and re-run hole detection so we know the *true*
residue (`feedback_build_to_measure_not_guess`):

1. **OCR-tolerant page→leaf reconciliation.** For each manifest page (whose
   `page_num` is running-header-verified, authoritative), find its primary
   scandata leaf by matching the verified number against scandata `pageNumber`
   under a digit-confusion equivalence (3↔8, 2↔9) AND positional monotonicity
   (the leaf must fall between its neighbours' leaves). A match means the page has
   a primary leaf — not a hole — regardless of the raw OCR'd number.
2. **Re-measure.** Output the true residue: pages with no primary leaf after
   OCR-tolerant matching. Expect ≤ 8 (vols 01/02/05/08), possibly fewer.
3. **Then decide** whether that residue needs the witness model, or whether option
   C (record the residue in `gaps[]`, leave `leaves[]` = scanned leaves; no schema
   change) is enough. With a single-digit residue, option C is likely sufficient.

This step is mandatory before committing to v5 — it sizes the problem the model is
meant to solve. The migration tool's current hole detection (`HolesRequireDecision`
keyed on raw scandata `pageNumber`) is the bug to fix.

---

## 2. If a true residue remains — the witness model

The witness model is still the right shape if the residue is non-trivial OR we
want to clean up the position/provenance conflation properly. It separates the
three jobs `leaf_num` does today:

| Concern | v4 (conflated on `leaf_num`) | v5 |
|---|---|---|
| Logical position (sort key) | scan leafNum | **`seq`** — sparse integer in **printed-page (logical book) order**, NOT scan order |
| Physical provenance | `leaf_num` + `ia_*` + `provenance` | **`witnesses[]`** — 0..N per-scan observations |
| Book attributes | `page_num`, `kind` | `printed_page`, `kind`, … (unchanged) |

### 2.1 `seq` — logical book order, deterministic (Codex must-fix #1, #2)
**`seq` orders by the book's logical sequence — printed-page order — not the
scan's physical leaf order.** This is the load-bearing correction from the Codex
review: `seq = leafNum × 1000` (rev 1) inherited the scan's physical disorder, and
vol_10's OCR-scrambled scan proved it. Define instead:
- Numbered body page P → `seq = P × 1000` (front offset folded out; logical order
  by printed page).
- Front matter → `seq` below the first body page; back matter → above the last.
- Plate after page P → `seq` in `(P×1000, (P+1)×1000)`.
- A residue page or insert between pages P and P+1, with `k` such inserts → a
  **pure batch-allocation** rule: `seq(rank r of n) = P×1000 + floor(1000 × r/(n+1))`.
  Deterministic from the neighbours + the page's rank, independent of insertion
  order (fixes the rev-1 midpoint instability: vol_01 pages 96, 97 get a stable
  `{343333, 343666}`-style pair regardless of processing order).

### 2.2 `witnesses[]` + chosen image (Codex must-fix #3)
Each leaf carries 0..N witnesses (one per scan that observed it). A witness has
`source_item`, `kind` (`primary|alternate`), and an **`image_state`** that can be
`present | unusable | absent`. The chosen image is selected by an explicit
`chosen_witness` pointer (or rule: best `present` witness, preferring `primary`
only when its state is `present`, not `unusable`). This fixes the "9 bad-primary"
cases: primary witness `image_state: unusable`, alternate witness `present` and
chosen — OCR never picks the bad primary.

### 2.3 `leaf_num` nullable
`leaf_num` keeps its meaning (primary-scan leafNum) but is `int | null` — null only
for a confirmed true-residue page with no primary leaf after OCR-tolerant matching.

---

## 3. Migration recipe (Codex must-fix #4 — placement is new logic)

The P2 tool's value is its scandata fetch + manifest read + **hole evidence**, not
its placement logic — `seq`/witness assignment is NEW code, not reused. Order:
1. Build the OCR-tolerant reconciliation + true-residue report (§1). Gate on it.
2. If proceeding to v5: apply schema 5.0.0 + regenerate enums + drift check + tests.
3. Migrate: v4 volumes (vol_11 + the 5 shipped) → mechanical (`seq = page-order`,
   single image block → one primary witness); legacy 7 → OCR-tolerant reconciliation
   assigns each page its primary leaf + witness, the residue gets `leaf_num: null`,
   batch-allocated `seq`, and an alternate witness.
4. Re-validate all 13; consumers + full suite; commit.

## 4. Accessor contract (Codex must-fix #5 — blast radius)
`build/lib/nsh_leaf_model.py` is the change surface, but it must publish an explicit
normalized contract, because consumers depend on concrete keys — e.g.
`ia_abbyy.py::_leaf_to_pagenum` (line 462) maps `int(p["ia_leaf_id"]) → page_num`,
which an alternate-only leaf (null `leaf_num`) breaks. The accessor must expose:
stable `page_num`/`local_path` (from the chosen witness)/`leaf_num` (nullable) keys,
the `seq` sort order, and a documented behaviour for `ia_leaf_id` on alternate-only
leaves. The TEST-08 gate extends to forbid direct `witnesses`/`seq` access outside
the accessor.

## 5. `gaps[]` decision (Codex must-fix #6)
v4 carried `gaps[]` verbatim (Q1). v5 must state its fate explicitly: **retire
`gaps[]`** — a body hole is a leaf with `image_state: unresolved` and no `present`
witness; a recovered page is a leaf with an alternate `present` witness. Both are
representable in `leaves[]`, so `gaps[]` becomes redundant. (If option C is chosen
instead of full v5, `gaps[]` stays as the residue's home.)

---

## 6. Decision for the maintainer

1. **Do §1 regardless** — fix OCR-tolerant reconciliation in the migration tool and
   re-measure the true residue. This is the real bug and unblocks vols 06/10/13
   (and likely the count for 01/02/05/08) with no schema change.
2. **Then choose**, sized by the measured residue:
   - residue ≈ 0 → finish P2 in v4 (the existing model is fine); no v5 needed.
   - residue small (≤ ~8) → option C (residue in `gaps[]`, no schema change), OR
     v5 if the position/provenance cleanup is judged worth it.
   - position/provenance conflation judged a recurring liability → full v5 (§2–§5).

The rev-1 recommendation "re-architect now" was premature — it solved an inflated
problem. Recommend: **build §1, measure, then decide** — do not commit to v5 before
the true residue is known.

## 7. Open risks
- **R-ocr-tolerance-overmatch** — 3↔8/2↔9 equivalence + monotonicity could match a
  wrong leaf. Mitigate: require positional monotonicity AND, for the residue,
  spot-check running-header OCR on the candidate leaf's pixels (PIPE-29 content
  check), not counts alone.
- **R-residue-still-needs-a-home** — even ≤8 pages must sort correctly; option C's
  `gaps[]` entries need a defined `printed_page` so downstream assembly can place
  them. (Same merge-by-page_num as before, just for far fewer pages.)
- **R-vol_11-and-5-shipped** — only re-touched if full v5 is chosen; §1 alone does
  not disturb them.
