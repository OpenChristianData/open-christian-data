# RESOLVED (2026-06-16) — R7 `ia-abbyy-haucgoog-v1` vol_08 was a WRONG-VOLUME fetch; quarantined

**Date:** 2026-06-15 (resolved 2026-06-16)
**Scope:** ONE cell — lineage `ia-abbyy-haucgoog-v1`, volume 08.

## RESOLUTION

Confirmed the hypothesis below: aligning the vol_08-dir rich files against the **canonical
vol_01** reference (`ia-abbyy-v1` vol_01) maps **499/544 = 91.7%** at mean score 0.901 with
**100% primary(vol_01) cross-check** (499/499 >= 0.20 overlap). This is definitively canonical
vol_01 content. A genuine `ia-abbyy-haucgoog-v1` vol_01 cell already exists, and the primary +
other ABBYY lineages already cover vol_08, so the redundant duplicate was **quarantined** (move,
never delete — REL-05), NOT relabeled to a confusing second vol_01 alternate:

- S1 cell `reports/s1-sidecars/ia-abbyy-haucgoog-v1/vol_08/` ->
  `reports/s1-sidecars/.quarantine_r7_vol08_wrongvolume/ia-abbyy-haucgoog-v1__vol_08/`
- 544 wrong-volume rich files `raw/.../vol_08/*.ia-abbyy-haucgoog.json` + the empty leafmap ->
  `raw/.../.quarantine_r7_vol08_wrongvolume/`
- 546 files moved, 0 sources remain; a `README.txt` in the quarantine dir documents restore +
  the proper fix (re-fetch the correct letter-O haucgoog vol_08 IA item).

No vol_08 cell is stamped with vol_01 leaves under a vol_08 label. The haucgoog lineage now has
10 legitimate cells. **Remaining (optional corpus-acquisition follow-up, not a leaf-rekey
blocker):** re-fetch the correct letter-O haucgoog vol_08 scan, then run the content aligner +
normalizer for it.

---

## (original block, for the record)
**Scope:** ONE cell — lineage `ia-abbyy-haucgoog-v1`, volume 08. Not stamped.

## What was found

The content aligner mapped **0 / 544** haucgoog vol_08 leaves to canonical vol_08
(`align_lineage_volume_by_content`, reference `ia-abbyy-v1` vol_08 = 498 leaves, range
23..520). 0% with mean score 0.00 means the content does not match canonical vol_08 at
all — which the aligner correctly refused to force-map (PIPE-29).

Cause: the rich files under `raw/.../vol_08/*.ia-abbyy-haucgoog.json` contain **volume 1
content**, not volume 8. Sampled body pages:

| haucgoog vol_08 stem | running header (printed page) | article |
|---|---|---|
| `page_0135` | 108 | **Akiba** |
| `page_0271` | 241 | **Apostle / Apostles' Creed** |
| `page_0407` | (verso) | **Animatism**-ish |

The New Schaff-Herzog is alphabetical across 13 volumes; "Akiba / Apostle / Animatism"
are letter-A headwords (volume 1). Canonical vol_08 is letter O ("Oriental / Origen",
printed ~298). So the haucgoog "vol_08" fetch pulled the wrong IA item (a vol-1 scan
mislabeled into the vol_08 directory), or the same scan was duplicated. Independent
confirmation: the aligner cross-check on every OTHER haucgoog volume that has a primary
(vols 01-05,10,11) is 99.8-100% primary-verified, so the aligner is sound — vol_08 is
genuinely wrong-volume data, not an alignment failure.

## State left on disk

- haucgoog vol_08 S1 cell: **not stamped** (leafmap `stem_to_leaf` is empty; the
  normalizer stamps 0, leaving it 0% — honest: it cannot carry a vol_08 leaf).
- No re-OCR. No engine invoked. The wrong-volume rich files are untouched.

## What unblocks it (maintainer / data remediation, not R7)

Decide one of:
1. **Re-fetch** the correct haucgoog vol_08 IA item (letter-O scan), then re-run the
   content aligner + normalizer for vol_08.
2. **Re-label**: if this content is a useful *vol_01* alternate scan, move it under a
   vol_01 lineage cell and align it to canonical vol_01 (it would then map ~92% like the
   other haucgoog cells).
3. **Drop** the haucgoog vol_08 cell (the primary + other ABBYY lineages already cover
   vol_08).

This is a corpus-acquisition fix, out of scope for the leaf-rekey R7 alignment work.
Until resolved, haucgoog vol_08 stays unmapped and is exempt from the R-final required
flip the same way other legitimately-unmapped alternate pages are.
