# NSH Page-Image Corruption — Mechanism Diagnosis (primary-sourced)

**Date:** 2026-06-10
**Companion to:** `docs/NSH_CONTENT_POSITION_VERIFICATION.md` (the OCR symptom audit).
This doc is the **cause**; that doc is the **symptom**.
**Primary sources used:** the IA scandata XML for every volume (fetched live from
`https://archive.org/download/NewSchaffHerzogEncyclopediaOfReligious/<prefix>_scandata.xml`),
read leaf-by-leaf; the on-disk manifests; and the running-header OCR audit. Re-derived from
scratch — no prior narrative of the mechanism was trusted (every earlier model was wrong at least
once).

---

## Decision brief

- **The IA scandata `pageNumber` field is the true printed page number.** Confirmed by control
  triangulation: on the five clean volumes (03/04/07/09/12) scandata `pageNumber` == disk filename
  == OCR running header. The fetcher already names each file by this number, so a *clean* fetch
  produces `page_NNNN.jpg` = printed page N **by construction**.
- **Both failure signs come from the scandata, not from a single re-materialize bug.** The
  positive-offset (missing) majority and the negative-offset (duplicate) minority are two distinct
  scandata pathologies:
  - **Missing (positive offset):** scandata has **gaps** — printed pages with no scan leaf. Vols
    01 `{96,97}`, 02 `{253,254,255}`, 05 `{451–454}`, 08 `{96,97}`, 06 `{361–363, 451–458}`.
  - **Duplicate (negative offset):** scandata tags one printed page on **two leaves**. Vol 11
    page 478 on leaves `505,506`; vol 06 pages 462–468 on leaves `476–482` **and** `486–492`.
- **The on-disk corruption was a downstream "squeeze to contiguous" rename, not the fetcher.** A
  prior phantom-fix session renamed the gapped/duplicated file set into a dense `1..N` sequence to
  satisfy the structural verifier's contiguity invariant. Squeezing the gaps slid every file after
  a gap *down* (content now reads ahead of its filename → positive offset); re-materializing a
  duplicate leaf slid files *up* (content reads behind → negative offset). The exact cumulative
  per-volume offset is an artifact of multi-step corruption across compaction boundaries and is not
  recoverable from the current disk — which is *why* the repair re-fetches from scandata rather
  than trying to invert the squeeze.
- **The real architectural fault is the page-accounting model, not one function.** The structural
  verifier (`verify_nsh_page_accounting.py`) and the page-order generators encode **Model A:
  `page_num` is a contiguous `1..N` sequence position**. The repair target ("every `page_NNNN.jpg`
  shows printed page N") is **Model B: `page_num` is the true printed page, gaps preserved as
  holes.** Model A is *incompatible* with the success criterion whenever a volume has a scan gap —
  squeezing to satisfy Model A's contiguity check is the corruption. The fetcher, verifier, and
  both page-order generators must move to Model B together.

---

## 1. The page → leaf mapping, and where each failure originates

`fetch_ia_pages.py::load_page_to_leaf` (lines 90–104) builds
`mapping[int(pageNumber)] = int(leafNum)` over every `<page>` in the scandata. The CLI then, for
`--pages all`, calls `parse_pages_arg("all", total_pages)` → `range(1, total_pages+1)` where
`total_pages` is the **leaf-element count**, and for each `page_num` writes the leaf
`mapping[page_num]` to `page_{page_num:04d}.jpg` (lines 156–164, 805, 814–831, 430).

Two scandata pathologies break this, each with a distinct, primary-sourced signature:

### 1a. Missing pages → positive offset (vols 01/02/05/06/08)

Scandata simply **skips** printed page numbers where the physical leaf is absent. Verbatim from the
vol_01 scandata (leaf → pageNumber):

```
leaf 131 -> page 95
leaf 132 -> page 98     <-- 96, 97 have NO leaf
leaf 133 -> page 99
leaf 134 -> page 100
```

So `mapping` has keys `{…,95,98,99,…}` — no 96, no 97. Under `--pages all`, `page_num=96`/`97` hit
`if page_num not in page_to_leaf: … skipping` (line 814) and **no file is written**. That is
*correct* Model-B behavior: printed pages 96–97 are genuinely missing from the scan and should be
holes. The corruption arises only when a later step renumbers `98→96, 99→97, …` to remove the hole,
at which point file `page_0096.jpg` carries the leaf whose true printed number is higher → printed
page reads **ahead** of the filename → **positive** offset. Sign confirmed for all five.

### 1b. Duplicate pages → negative offset (vols 11, 06)

Scandata tags the **same** printed page on two leaves. Verbatim:

```
vol_11:  leaf 505 -> page 478
         leaf 506 -> page 478     <-- duplicate
         leaf 507 -> page 479

vol_06:  leaf 476..482 -> pages 462..468     (out-of-order early copy)
         leaf 483..485 -> pages 459..461
         leaf 486..492 -> pages 462..468     (in-order correct copy)
         leaf 493      -> page 469
```

`mapping[pn]=leaf` is **last-wins**: it silently keeps the second leaf and drops the first, with no
warning and no record of the dropped leaf. This is a genuine fetcher bug (silent data loss), and —
critically — **the correct leaf is volume-specific**:
- **vol_11:** leaves 505 and 506 are consecutive re-scans of page 478; either could be the clean
  one — *needs OCR/visual adjudication*.
- **vol_06:** the **last** copy (leaves 486–492) is the in-sequence one (it sits correctly between
  461 and 469); the early copy (476–482) is the misfiled duplicate. Here last-wins is *accidentally
  correct*, but only by luck.

No blanket dedup policy (keep-first or keep-last) is correct for both. The fetcher must **detect**
the duplicate, retain both candidate leaves for adjudication, and never silently drop one. The
negative on-disk offset arose when a prior step materialized **both** duplicate leaves as separate
body files, sliding subsequent filenames up.

### 1c. Garbage scandata tails (vols 10, 13 — already handled / out of body)

vol_10 scandata claims printed numbers up to **873** with 378 internal gaps; vol_13 up to **811**
with 600 gaps. These high tails are auto-assigned junk, not real page numbers. vol_10 was already
repaired manually to a true 499-page volume (`b436274d`); vol_13's body (pages 10–208) is clean and
only its 209–211 appendix tail is a real gap. The fixed fetcher must **not** trust scandata
`pageNumber` blindly for these tails — body range must be bounded by the verified last body page,
not by `max(pageNumber)`.

---

## 2. Per-volume primary-source table (from live scandata)

| Vol | Class | Printed range | Distinct printed | Scan gaps (missing) | Duplicate pages (leaves) | Disk files now |
|---|---|---|---|---|---|---|
| 01 | AFFECTED | 10–500 | 489 | `{96,97}` | — | 498 |
| 02 | AFFECTED | 9–499 | 488 | `{253,254,255}` | — | 497 |
| 05 | AFFECTED | 10–508 | 495 | `{451,452,453,454}` | — | 504 |
| 06 | AFFECTED | 10–505 | 485 | `{361,362,363, 451–458}` | `462–468` (×2 each) | 501 |
| 08 | AFFECTED | 10–500 | 489 | `{96,97}` | — | 498 |
| 11 | AFFECTED | 10–508 | 499 | — | `478` (leaves 505,506) | 505 |
| 03 | control | 10–500 | 491 | none | — | 500 |
| 04 | control | 8–500 | 493 | none | — | 500 |
| 07 | control | 3–502 | 500 | none | — | 502 |
| 09 | control | 8–499 | 492 | none | — | 499 |
| 12 | control | 10–599 | 590 | none | — | 599 |
| 10 | repaired | (junk tail) | 488 | (manually repaired to 499) | — | 499 |
| 13 | control | (junk tail) | 202 | `{209,210,211}` body | — | 208 |

The five clean controls have **zero** scan gaps and **zero** duplicate page numbers — which is
exactly why their squeeze-free disk already satisfies file = printed page. The corruption is
one-to-one with scandata pathology.

---

## 3. The page_count semantic conflict — reconciled

Three consumers disagree on what `page_count` means:

| Consumer | Current treatment of `page_count` |
|---|---|
| `fetch_ia_pages.py::write_manifest_atomic` (line 293) | `len(pages)` — count of present entries |
| `verify_nsh_page_accounting.py` check 6 | body total = `disk_present + permanent_missing` |
| `generate_page_order.py` (line 108) | upper bound of `range(1, page_count+1)` — assumes `1..page_count` are the body pages |

For a complete volume these agree; for an incomplete one they diverge (vol_13: `len(pages)=208`
but the body runs to 211).

**Reconciled definition (Model B): `page_count` = the highest true printed body page number =
`present_body_pages + permanently_missing_body_pages`.** Under this definition all three consumers
become consistent:
- `write_manifest_atomic` must compute `page_count = max(present page_num ∪ in-range gap page_num)`
  within the body, **not** `len(pages)`.
- verifier check 6 (`page_count == present + permanent_missing`) holds.
- `generate_page_order`'s `range(1, page_count+1)` correctly enumerates the body, marking gap pages
  as holes.

The one verifier invariant that must change is **check 3** ("page_nums contiguous `1..len(pages)`"):
under Model B present `page_num`s are *not* contiguous (gaps are real). It must become: *present
page_nums and in-range gap page_nums tile `1..page_count` disjointly* (every body page is either a
present file or a recorded gap, never both, never neither).

---

## 4. What the fix is (and is not)

**Is:**
1. `load_page_to_leaf` must detect duplicate `pageNumber`s and **return** them (caller logs/retains
   both leaves; never a silent drop).
2. `--pages all` must enumerate the real numbered pages (`sorted(page_to_leaf.keys())`), not a
   leaf-count range, and the body must be bounded by the verified last body page (not scandata's
   junk tail).
3. `page_count` reconciled to the Model-B definition in §3.
4. Verifier check 3 and both page-order generators moved to Model B (gaps preserved, not squeezed).
5. The six affected volumes re-materialized from scandata so each file is named by its true printed
   page, with gaps recorded — then **OCR-gated** (`verify_nsh_running_headers.py`), since structural
   accounting is pixel-blind (PIPE-29).

**Is not:** renaming the corrupted disk in place (reverts on next fetch and cannot recover the true
offsets); trusting the manifest's per-file `ia_leaf_id` (it was hand-edited to a false linear
`page+36` and disagrees with the pixels); or auto-picking a duplicate leaf for vol_06/vol_11
without OCR adjudication.

**Adjudication flag:** vol_06 (disordered gathering + 7 duplicated pages + two scan gaps) and vol_11
(one ambiguous duplicate) cannot be auto-rebuilt to *verified-correct* without per-page OCR/visual
adjudication of which duplicate leaf is the clean printed page. The simple-shape volumes
(01/02/05/08 — gaps only, no duplicates) rebuild deterministically from scandata.

**Front body pages are unnumbered in scandata.** Printed pages 1..(min−1) carry no scandata
`pageNumber` (vol_08: pages 1–9 sit at primary leaves 23–31 but are unnumbered), so a plain
`--pages all` would drop them — they map by a per-volume constant leaf offset. The exact per-volume
front offsets, gap-recovery leaf specs, and the rebuild procedure are in
`docs/NSH_REBUILD_RUNBOOK.md` (phases 3–4). The fetcher fix, Model-B verifier, and OCR tripwire
(phases 1–2, 5–6) are landed; the six-volume disk re-materialization is the remaining supervised
work, gated per volume on the running-header OCR audit.
