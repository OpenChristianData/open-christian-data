# NSH Content-Position Verification — running-header OCR audit

**Verdict: FAILED.** Genuine mis-names were found in **all seven** phantom-renamed
volumes (01, 02, 05, 06, 08, 10, 11). In each, every `page_NNNN.jpg` from the
documented first-renamed page through the last body page shows a printed page
number that does **not** equal N: the image content is offset from its filename
by a sustained constant (+4 for vols 01/02/08, +8 for vols 05/06/10, and −2…−5
for vol 11). The five un-renamed control volumes checked (03, 04, 07, 09, 12)
verify clean — `page_NNNN.jpg` shows printed page N. The structural verifier
`verify_nsh_page_accounting.py` reports ALL 130 checks PASS on the same disk,
because it counts filenames against the manifest and cannot see image content;
the running headers are the first source that reads the pixels.

This **disproves** the prior session's content-position caveat ("high
confidence, not pixel-proven"). It is not merely unproven — for the renamed
ranges it is wrong on the current disk.

Scope note: this audit verifies the **current on-disk image content** against
its filename. It does not diagnose *why* the disk is in this state, nor fix it
(out of task scope). The NSH `page_*.jpg` files are gitignored, and this exact
"disk silently reverted to pre-rename" failure is already on record (see
Residual risk). Root-cause and repair belong to the phantom-fix post-mortem.

---

## Method

### Ground-truth source

The printed page number was read from the **running header of the current
`page_NNNN.jpg` image**, OCR'd directly with Tesseract 5.5. This is the only
source independent of the bookkeeping under test: the phantom rename shifted
filenames, and a rename off-by-one would silently mis-name a run of pages while
every count still reconciles. The per-image OCR sidecars
(`page_NNNN.ia-abbyy.json`, S1 Tesseract sidecars) were **not** used as
ground truth — they are named by the manifest leaf→page map (the bookkeeping
under test) and are stale relative to the current files. The image pixels are
the only artifact a rename-logic bug cannot have corrupted.

Header layout (NSH 1908-1914):
- recto / odd printed page: `<N>  RELIGIOUS ENCYCLOPEDIA  <article>` (N top-left)
- verso / even printed page: `<article>  THE NEW SCHAFF-HERZOG  <N>` (N top-right)

The page number is isolated by anchoring on the fixed header words
(`RELIGIOUS`/`ENCYCLOPEDIA` → recto, `HERZOG`/`SCHAFF` → verso) and taking the
plausible integer (≤3 digits, 1–560) nearest the outer margin. Body numbers
(dates, verse refs) are excluded by the digit/range cap and edge selection.

Tooling: [`build/tools/verify_nsh_running_headers.py`](../build/tools/verify_nsh_running_headers.py).
Strip fraction 0.20 of image height covers both NSH scan geometries (the smaller
~5000×6959 leaves and the larger ~6050×7701 leaves; a strip tuned to the small
geometry alone reads the large-geometry volumes as 95% unreadable). Runs
non-zero on a detected rename signature so it can gate a future commit.

### Rename vs OCR-misread discriminator

A rename off-by-one shifts every page from its start to the **end** of the
volume by a single constant, so its delta-run never recovers to 0 before the
last readable page. A consistent OCR misread (e.g. a degraded gathering where
every `5` reads as `4`) produces an island that **recovers**. Calibration
surfaced exactly such an island in the clean control (vol_03 pp250-253 read
240-243, recovered at 254), proving the discriminator is necessary. The tool
classifies every sustained run as `recovering-ocr-cluster` or
`persistent-to-tail`; only the latter is the rename signature. Self-tested via
`--selftest` (true-positive shift + true-negative recovering island + isolated
misreads).

### Calibration on control volumes

| Control vol | Sample | Match rate | Tail (last 6) | Rename signature |
|---|---|---|---|---|
| vol_03 | 500 (full) | 87–93% | last p0500 → 500 | none (1 recovering OCR island, pp250-253) |
| vol_04 | spread | ~69% | clean | none |
| vol_07 | spread (48) | 88% | 5/6; last p0502 → 502 | none |
| vol_09 | spread (48) | 93% | 6/6; last p0499 → 499 | none |
| vol_12 | spread (56) | 86% | last body clean (end-index plates unreadable) | none |

All five un-renamed controls read delta-0 dominant with no persistent-to-tail
run and a last-body page that reads its own N — the method discriminates: clean
on un-renamed volumes, failed on every renamed one. (vol_04 reads at a lower
match rate because its larger ~6050×7701 scans carry more per-digit OCR noise,
not because of any offset.)

Match rate is the fraction of *readable* pages whose header equals N. The ~10%
shortfall from 100% on a clean volume is the intrinsic single-digit OCR-misread
noise floor on these scans (random, non-repeating deltas); it does **not** form
a sustained run and does not affect the verdict. The decisive control signal is
**delta-0 dominant + no persistent-to-tail run + the last body page reads its
own N**.

---

## Coverage table (affected volumes)

Per affected volume: the renamed range is uniformly offset. "Pre-rename match"
is the in-volume control (pages before the first renamed page, which read
clean); "renamed-range match" is 0% in every case — the signature of a genuine
systematic mis-name, not noise.

| Vol | First renamed pg | Pages on disk | Pre-rename match | Renamed-range match | Offset (printed − file) | Last body page reads |
|---|---|---|---|---|---|---|
| vol_01 | 96  | 498 | 65/91 (71%) | **0/381 (0%)** | **+4** | p0498 → 500 |
| vol_02 | 254 | 497 | 223/242 (92%) | **0/212 (0%)** | **+4** | p0497 → 499 |
| vol_05 | 451 | 504 | 371/428 (87%) | **0/51 (0%)** | **+8** | p0504 → 508 |
| vol_06 | 451 | 501 | 356/425 (84%) | **0/51 (0%)** | **+8** | p0501 → 505 |
| vol_08 | 96  | 498 | 84/94 (89%) | **0/370 (0%)** | **+4** | p0498 → 500 |
| vol_10 | 360 | ~496 | 266/323 (82%) | **~0/128 (2%)** | **+8** | p0491 → 499 (then blank plates 492-496) |
| vol_11 | 479 | 505 | 189/412 (46%) | **0/25 (0%)** | **−2 … −5** | p0505 → 503 |

(Counts above from the geometry-appropriate strip; the committed tool's uniform
0.20 strip reproduces the same verdict — exact counts in the per-volume JSON
under the audit run.)

The transition from clean to offset occurs **exactly at each volume's
documented first-renamed page** — that precise alignment, reproduced across
seven independent volumes, is conclusive that the rename operation is the cause.

---

## Mismatch log (adjudication)

Every checked page whose header ≠ N falls into one of these tags. The renamed
ranges produce thousands of systematic mismatches; they are characterized as a
single class per volume rather than enumerated row-by-row (the per-page records
are in the audit JSON).

| Tag | Where | Adjudication |
|---|---|---|
| **genuine-misname** | Every page in each affected volume's renamed range | The file's image shows a different printed page than its name. Clean, unambiguous OCR (e.g. vol_01 `page_0096.jpg` header reads "THE NEW SCHAFF-HERZOG **100**"). Uniform constant offset per volume. This is the FAILED finding. |
| **genuine-misname (duplicate content)** | vol_01 terminal pages | `page_0495.jpg` ≡ `page_0497.jpg` and `page_0496.jpg` ≡ `page_0498.jpg` — **SHA256 byte-identical**. The last two files are duplicates of pp495-496, not the real pp499-500. |
| **ocr-misread** | Scattered, ~10% of readable pages in every volume incl. controls | Random single-digit glyph misreads (e.g. vol_02 `page_0254.jpg` read "358" — a misread of 258; neighbors p255→259, p256→260 confirm the real local offset is +4). Non-repeating; never forms a sustained run. |
| **recovering-ocr-cluster** | vol_03 pp250-253 (control) | Read 240-243 (consistent `5`→`4` misread across a 4-page gathering), recovered to delta 0 at p254. Not a rename — classified by the discriminator. |
| **no-header-on-page / plate-or-insert** | vol_10 pp492-496; volume end-matter | Blank or plate leaves with no readable running header. Not adjudicable as match/mismatch. |
| **unreadable** | ~2–13% per volume | OCR found no plausible page number (faint header, scan damage, tight crop). Listed per volume in the audit JSON. |

---

## vol_13 ABBYY resolution (pp209-211)

**Settled fact: ABBYY OCR text IS present for printed pages 209, 210, 211.** The
page *images* are genuinely absent from IA; the *text* is not.

Primary evidence — streaming the actual ABBYY source
(`raw/internet-archive/schaff-herzog/13.…_abbyy.gz`) by leaf index:

| Leaf | Maps to page | Words | Header in OCR text |
|---|---|---|---|
| 224 | 208 | 916 | "…SCHAFF-HERZOG **208**" |
| 225 | **209** | **859** | "**S09** ENCYCLOPEDIA OF RELIGIOUS KNOWLEDGE" |
| 226 | **210** | **846** | "…NEW 8CHAFF-HERZOG **SIO**" (210) |
| 227 | **211** | **702** | "**811** ENCYCLOPEDIA…" (211) |
| 228 | 212 | 0 | (blank) |

The leaf→page mapping (leaf N → page N−16) is self-verified by the OCR'd running
headers themselves. Leaves 225-227 carry substantial bibliography text and were
**never skipped** by the parser (`coverage.ia-abbyy.json` `skipped_leaf_indices`
= front matter 0-16 and back matter 228-240 only).

Reconciling the two prior records:
- The **prior session's claim** ("file set jumps `page_0208` → `page_leaf0228`,
  implying no ABBYY text for pp209-211") is **wrong**. It inferred absence from
  the *on-disk sidecar files* — but the `page_0209/0210/0211.ia-abbyy.json`
  sidecars are absent on disk while the underlying `.gz` source has full text
  for those leaves. File-presence is not text-presence.
- The **manifest gap note's conclusion** ("ABBYY text IS present") is **correct**
  — but its cited evidence ("coverage.json confirms 211 pages_parsed") is **not
  load-bearing**: that aggregate was written against the pre-reconciliation
  211-entry manifest; the current manifest has only 208 `pages[]` entries, and an
  aggregate count never proves those three specific pages are covered. The
  conclusion holds for a different reason (the per-leaf text above).

Note (in scope only as an observation): the `page_0209/0210/0211.ia-abbyy.json`
sidecars are missing from disk and were not regenerated as leaf-fallbacks after
the manifest was reconciled to 208 entries. This is a sidecar-regeneration gap,
not a source-text gap.

---

## Residual risk

- **Why the disk is offset is not diagnosed here.** This audit verifies *current
  image content vs filename*. The likely cause — the gitignored `page_*.jpg`
  layer silently reverting to pre-rename state (or the prior session's renames
  never persisting) — is documented as a known NSH failure mode (a "renames
  done" claim once verified clean in git while five volumes' disk had reverted).
  Confirming the cause and repairing the disk is the phantom-fix post-mortem's
  job, not this task's.
- **Unreadable pages (~2–13% per volume) are unverified.** Faint headers, scan
  damage, and end-of-volume plates leave a minority of pages with no readable
  page number. They are listed per volume in the audit JSON. Closing this would
  need higher-resolution corner-crop OCR or a second engine on those specific
  pages; it does not change the verdict (the readable majority is decisive).
- **vol_11 pre-rename match was lower (~46%)** than the other controls' regions,
  i.e. noisier OCR on its earlier pages; its renamed range is still unambiguously
  offset negative. A targeted re-read of vol_11 pp1-478 would tighten that
  number but does not affect the FAILED finding for pp479-505.
- **The structural verifier still passes.** Until the disk is repaired,
  `verify_nsh_page_accounting.py` will keep reporting green while content is
  wrong. Wiring `verify_nsh_running_headers.py` (or a sampled subset) into the
  same gate would catch this class going forward.
