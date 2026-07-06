# R7 alternate-scan alignment — same-stem was wrong; content alignment (2026-06-15)

This records a correctness finding made while completing R7, the fix, and the new tool.
It supersedes the "0% — R7 never ran / just run the existing tool" framing in
`docs/BLOCKED-leafrekey-R-final-2026-06-15.md` for the six alternate ABBYY lineages.

## The finding: the existing R7 oracle mis-maps alternate scans

R7 must stamp `canonical_leaf_id` on every alternate-ABBYY page. The existing oracle
(`build/tools/ocr_pipeline/abbyy_leaf_alignment.py`) maps each rich stem to a canonical
leaf by **implicit same-stem** (`canonical_leaf_id(stem, manifest)`) and "verifies" by
comparing the ABBYY scandata `page_num` **field** to the canonical page number. That is
correct **only when the lineage IS the canonical scan**.

Two of the eight lineages are the canonical scan and align fine by same-stem:
- `ia-abbyy-v1` — the same IA item as the primary (`NewSchaffHerzogEncyclopediaOfReligious`);
  full-page text overlap vs primary **Jaccard 0.805**, 100% per-stem clid agreement.
- `azure-ai-vision-v1` — cloud OCR of the **same canonical page images**; 100% per-stem
  clid agreement with the primary tesseract.

The other six are **different physical scans of the same edition**, each with its own
leaf order (different front matter, plus duplicate / missing / mis-bound / inserted-plate
leaves). For these, same-stem is wrong, and the field check is **defeated**: the scandata
`page_num` field numerically collides with the canonical page number (both count from 1
at body start), faking a constant **offset 0** while the actual leaf content is shifted.
The running-header glyph — the only content signal the old oracle carries — is degraded by
NSH digit confusion, so corroboration was ~0 and never caught it.

**Non-circular proof** (clid-per-stem agreement is circular — every engine derives clid
from the same `canonical_leaf_id(stem, manifest)`): full-page word-overlap of each rich
page vs the primary tesseract at the **same stem**:

| lineage | same-stem Jaccard vs primary | **best-match** Jaccard | verdict |
|---|---|---|---|
| `ia-abbyy-v1` | 0.805 | — | same scan → same-stem valid |
| `ia-abbyy-dli-v1` | 0.071 | 0.85 | same edition, **reordered** |
| `ia-abbyy-haucgoog-v1` | 0.067 | (same shape) | same edition, reordered |

A same-stem stamp run had been started this session; it was killed and its 8 mis-stamped
cells were reverted (`canonical_leaf_id` cleared from the manifests) before any pipeline
consumed them. Leaving wrong stamps would be worse than 0%: R-final's precondition would
read as met while every cross-engine WCT join on those pages was silently mis-aligned
(PIPE-29).

## The fix: content-based monotone alignment (design sec 6, finally implemented)

Design sec 6 always required computing the **reorder, "not implicit same-stem"** — it was
never implemented. New tool `build/tools/ocr_pipeline/abbyy_content_alignment.py`:

- For each alternate leaf, a cheap word-set **Jaccard** shortlists the top-k candidate
  canonical leaves within a **monotone band** (`[last-back_slack, last+window]`), then the
  shared OCR-tolerant **text aligner** (`build/lib/text_alignment.align_tokens` +
  `looks_like_ocr_difference`, which folds digit/letter OCR confusion and ligatures into
  matches) re-scores the shortlist; the best ≥ 0.40 is accepted.
- **Monotone** (reading order is preserved across editions) so the alignment absorbs scan
  defects: a duplicate alt leaf maps to the same canonical leaf, a missing alt leaf skips
  a canonical leaf, a mis-bound/out-of-order or extra leaf matches nothing and is left
  **unmapped and logged** — never force-mapped. Per-leaf scoring means each page is judged
  on its own content, not a volume-wide constant offset (errors are not uniform within a
  volume).
- The correct-vs-wrong score separation is wide (mapped ~0.9, unmapped ~0.08), so the 0.40
  threshold has large slack for cross-scan OCR noise.

The alignment is persisted per cell as `raw/.../vol_NN.<lineage>.leafmap.json`
(`stem_to_leaf` + the `unmapped` list + provenance). The ABBYY normalizer
(`s1_abbyy_normalizer._stamp_canonical_leaf_id`) now **consumes a leafmap when present**
(authoritative: stems absent from it are unmapped, never same-stem) and falls back to
same-stem only when no leafmap exists (i.e. the canonical scan `ia-abbyy-v1`). So a future
plain normalizer re-run cannot re-introduce the same-stem mis-map. Tests:
`tests/test_abbyy_content_alignment.py` (11). Zero re-OCR throughout (text lifted from
existing rich sidecars).

## Per-lineage results (leafmap, reference = ia-abbyy-v1)

Disk census after stamping (`canonical_leaf_id` on S1 manifest page_refs):

| lineage | cells | stamped | leafmap meanScore | mono_viol (max) |
|---|---|---|---|---|
| `ia-abbyy-dli-v1` | 7 | 3284/3505 = 93.7% | 0.88-0.95 | 0 |
| `ia-abbyy-haucgoog-v1` | 11 | 4677/5513 = 84.8% (vol_08 0% defect) | 0.00-0.93 | 0 |
| `ia-abbyy-haucgoog-c1-v1` | 10 | 4676/5014 = 93.3% | 0.86-0.94 | 2 |
| `ia-abbyy-haucgoog-c2-v1` | 8 | 3521/3780 = 93.1% | 0.48-0.91 | 0 |
| `ia-abbyy-haucgoog-c3-v1` | 5 | 2368/2515 = 94.2% | 0.89-0.95 | 0 |
| `ia-abbyy-haucgoog-c4-v1` | 2 | 942/1007 = 93.5% | 0.92-0.94 | 0 |
| `ia-abbyy-v1` (canonical) | 13 | 6271/6274 = 100% | — same-stem | — |
| `azure-ai-vision-v1` (canonical) | 11 | 4509/4511 = 100% | — same-stem | — |

Independent primary cross-check (every alternate cell with a primary, vols 1-5,10,11):
**99.8-100%** of stamped pages overlap the primary tesseract at the assigned leaf; the c2
cell at meanScore 0.48 (poorer scan OCR, not misalignment) cross-checks 246/246 = 100%.

Typical mapped rate ~93% per cell with mono_violations 0 (one c1 cell =2); the ~7% unmapped per cell
is front/back matter + plate/blank leaves + a few mis-bound/duplicate defect leaves
(verified on dli vol_03: 10-page mis-bound "Consistory" run between consecutive canonical
leaves 275/276; an out-of-order printed-398 leaf at sequence 421). The unmapped set is
persisted so R6b can exempt it.

## What this means for R-final

- The six lineages are now content-aligned and stamped (not 0%). R-final's per-lineage
  census must be re-derived from disk (`.tmp_audit/r7_census.py`).
- The legitimately-unmapped alternate body pages (logged per cell) carry **no**
  `canonical_leaf_id`. Under the required-clid schema flip they would be invalid, so R6b /
  R-final must **exempt** them — keyed on the canonical manifest's `kind` field (a leaf with
  `kind` != body is exempt by category), not a fragile per-page list. ~85-95% of each cell's
  unmapped set is front/back matter + blank plates (no canonical body leaf, correct to leave
  unmapped); only ~2-11 mid-body pages/cell are recoverable (mis-bound/out-of-order leaves the
  monotone pass skipped). The real metric is **body-page coverage** (~98%+), not total-page.

## Post-commit flip-readiness audit (2026-06-15, after `77772c20`) — sidecars are NOT flip-safe

A later audit corrected an earlier wrong assumption in this doc (that sidecars carry clid only
on manifests). The flip targets **four schemas at the per-page sidecar / rendering / WCT level**,
and "100% manifest coverage" is NOT flip-safe:

- **Most alternate-scan sidecars carry STALE same-stem clid** that mismatches the (correct)
  manifest leafmap clid — the leafmap re-stamp was non-force, so it fixed manifests but skipped
  sidecars (dli vol_03: 467/467 sidecars MISMATCH the manifest; c1 vol_05, which got re-emitted:
  463/463 match). Any consumer reading sidecar clid (incl R6b's (a) check) gets the wrong leaf.
- **Azure per-page sidecars carry 0 `canonical_leaf_id`** — the azure normalizer stamps the
  manifest `ref` but never copies clid into the sidecar `record` (the abbyy normalizer does, at
  `s1_abbyy_normalizer.py` ~lines 1010-1011). ~4,500 azure sidecars would fail `sidecar-page-v1`.
- Fix (both): a one-line azure normalizer change + a **force re-emit** of all abbyy+azure cells
  (zero re-OCR — text lifted from existing rich/azure JSON), then verify every body sidecar's
  clid == its manifest's. Plus a pre-flip clid audit at sidecar + rendering + WCT level across
  all four flip targets (manifest-green ≠ flip-safe). All of this is specified in the follow-up
  prompt `prompts/2026-06-15-2310-leafrekey-R7-maximize-coverage.md`.
- **The R-final prompt itself needs a rewrite** (not just a context injection): its R6b spec
  "assert the R6a checks across ALL engines" is wrong for alternate scans (sha-reuse/sha-equality
  are primary-only and would bucket every ABBYY page as a (b) re-OCR failure); it has no exemption
  for non-body pages; and its only pre-flip gate is the manifest-level verifier.

## Flip-readiness session COMPLETE (2026-06-16) — sidecar/manifest clean across all engines

The follow-up prompt was executed. Sidecar + manifest level is now flip-safe; the global
recovery pass closed the body-coverage gap; vol_08 was resolved; rendering + WCT gaps are
named precisely for R-final. Zero re-OCR throughout (text lifted from rich/azure JSON).

### Aligner extended (Task 1) — gated global fallback + primary-tesseract fallback
`abbyy_content_alignment.py` gained a **second, non-monotone global pass** over the mid-body
leaves the monotone pass left unmapped, behind a HIGH floor (`page_similarity >= 0.55`) + an
independent **primary tesseract cross-check** (`>= 0.20` word-overlap at the chosen leaf;
PIPE-29 — never stamp a leaf the primary contradicts). A second mechanism handles the case
where the `ia-abbyy-v1` reference itself is MISSING a body leaf (a real gap — vol_10 reference
has 22 missing letter-S leaves): the alt page is matched **directly against the primary
tesseract** (`PRIMARY_MATCH_FLOOR = 0.40` word-set Jaccard, an independent engine, so a strong
match is its own verification). The remaining unmapped set is classified per page:
`non-body` (front/back band, or `< MIN_BODY_WORDS = 50`) | `body-unrecoverable` (mid-body,
enough words, no clean home). Tests `tests/test_abbyy_content_alignment.py` (19, +8 this
session). Leafmaps now persist `recovered_pages`, `recovered_via`, and `unmapped_classified`.

### Sidecar-level clid CORRECT across all engines (Task 3) — the headline result
The azure normalizer one-line fix (copy clid onto the sidecar `record`, mirroring abbyy) +
a `force=True` re-emit of every abbyy + azure cell. **On-disk verify: every body sidecar's
`canonical_leaf_id` EQUALS its manifest's — 0 mismatch / 0 missing across all 8 lineages:**

| lineage | cells | body refs | sidecar==manifest |
|---|---|---|---|
| `ia-abbyy-v1` | 13 | 6271 | 100% (0/0) |
| `ia-abbyy-dli-v1` | 7 | 3316 | 100% (0/0) |
| `ia-abbyy-haucgoog-v1` | 10 | 4720 | 100% (0/0) |
| `ia-abbyy-haucgoog-c1-v1` | 10 | 4724 | 100% (0/0) |
| `ia-abbyy-haucgoog-c2-v1` | 8 | 3557 | 100% (0/0) |
| `ia-abbyy-haucgoog-c3-v1` | 5 | 2380 | 100% (0/0) |
| `ia-abbyy-haucgoog-c4-v1` | 2 | 952 | 100% (0/0) |
| `azure-ai-vision-v1` | 11 | 4509 | 100% (0/0) |

30,429 body sidecars now carry the correct leaf. The two gaps that motivated the session
(azure 0/4509; dli 2808 stale same-stem mismatches) are fully closed.

### Body-page coverage (Task 6) = mapped / (mapped + body-unrecoverable)
~97-100% per cell. The global pass recovered up to 22 pages/cell on the reference-gap volumes
(vol_10) and ~12/cell on vol_05. Only **2 cells fall marginally below 97%** — both **explained**:
`ia-abbyy-haucgoog-c1-v1 vol_06` (96.9%) and `ia-abbyy-haucgoog-c2-v1 vol_05` (96.8%). Their
`body-unrecoverable` residual is **heavily garbled alternate-scan OCR** on vols 5-6 (e.g.
"Orlswold Ghroninffen" = Griswold/Groningen; "Jmmgeu and ImAffe-Worshlp" = Images and
Image-Worship) plus a few garbled full-page plates — real body pages whose alt OCR is too
degraded to content-verify (overlap vs the primary < 0.40 floor), so correctly left unstamped
per PIPE-29. They are canonically covered by the primary tesseract; this is a per-scan OCR
limitation, not an alignment failure or corpus loss. vol_06 (and vols 7-9,12,13) have **no
primary tesseract**, so their reference-gap pages cannot use the primary fallback either —
an explained structural limit.

### vol_08 resolved (Task 2) — wrong-volume fetch quarantined
The `ia-abbyy-haucgoog-v1` vol_08 rich files are canonical **vol_01** content (aligning them
against the vol_01 reference maps **499/544 = 91.7%, mean 0.901, 100% primary(vol_01)
cross-check**). A genuine haucgoog vol_01 cell already exists and the primary + other ABBYY
lineages already cover vol_08, so the redundant duplicate was **quarantined** (546 files moved,
never deleted — REL-05) to
`reports/s1-sidecars/.quarantine_r7_vol08_wrongvolume/` and
`raw/.../.quarantine_r7_vol08_wrongvolume/`. The BLOCKED doc is updated to RESOLVED.

### Flip-readiness audit (Task 5) across all 4 schemas — two gaps named for R-final
| schema | status |
|---|---|
| `sidecar-page-v1` | **READY** — every body sidecar carries clid == manifest (table above) |
| `sidecar-manifest-v1` | **READY** — every body manifest page_ref carries int clid |
| `rendering-v1` | **CLOSED (R-final.1, 2026-06-16).** Correction to the earlier audit: the per-page leaf-keyed S2 shape **did exist** for abbyy/azure (`<cell>/pages/*.rendering-v1.json`); it just carried **0 clid**. The earlier "does not exist / legacy-monolithic" reading came from auditing only the cell-root `rendering-v1.json` monolith (`cell.glob("*.json")` never descends into `pages/`). R-final.1 re-keyed **all ~50 abbyy/azure per-page cells** (consumed-now + future-consumer alternates) so every body page now carries `canonical_leaf_id` == its S1 manifest leaf — **23,220 body pages stamped, 0 missing**. Mechanism: re-render through `render_s2` (which stamps clid from the now-leaf-keyed S1 manifest) with the redundant jsonschema re-validation skipped (`validate_schema=False`) — **proven byte-identical** to a validated render on real cells (abbyy 496/496, azure 489/489); zero re-OCR. The superseded cell-root monoliths (41) were quarantined to `reports/s2-renderings/.quarantine/legacy-monolithic/` (REL-05, reversible). vol_08/`ia-abbyy-haucgoog-v1` skipped (R7 quarantined its S1 source as wrong-volume — no manifest to key from). |
| `word-confusion-table-v1` | **DEFERRED (R-final.2, 2026-06-16) — flip after the full WCT rebuild, not this session.** WCT exists only for vol_01 (478) + vol_02 (466) and carries **0 clid** (predates R4b). R-final.2 found it is also **stale-content for 553/944 pages**: each WCT page's stored `source_image.sha256` resolves to a *different* canonical leaf than the current renderings (the 2026-06-09 phantom-page rename shifted ~half the files; e.g. page_0200 — current jpg → leaf 234 = S1/renderings, but the WCT was built pre-rename against the leaf-238 image and still records that sha). So a clid **stamp** would be clid≠content; the correct fix is a full `build_from_files` rebuild (~200 s/page → infeasible to do for a stale leftover this session). Since the WCT is also **incomplete** (no alternate ABBYY, no vols 3-13) and gitignored, the maintainer decision is to **defer**: the next full pipeline run regenerates the whole WCT with clid (`build_wct_page` emits it natively). R6b reports a wholesale-unkeyed WCT volume as **PENDING** (not a failure), so the production chain is green and `word-confusion-table-v1` is the one schema NOT flipped in session 3. A trial stamp was applied and **fully reverted** (snapshot `reports/.wct-backup-rfinal2`; 944 pages back to 0 clid). |

### R-final.1 consumed-vs-orphan split (2026-06-16)
The only S2 consumer is `drive_reconciliation_chain` → `build_wct.build_from_files`
(`DEFAULT_ENGINES = tesseract, ia-abbyy-v1, azure-ai-vision-v1, kraken`), and WCT has only
ever been built for vol_01 + vol_02. So **4 abbyy/azure cells are consumed today**
(vol_01/02 × {`ia-abbyy-v1`, `azure-ai-vision-v1`}); the alternate lineages (`dli`,
`haucgoog`, `c1`–`c4`) and vols 3–11 are not read by any consumer **yet** but are intended
future consumers — so they are **NOT orphans / NOT flip-exempt**. They were re-keyed too, so
the whole abbyy/azure per-page S2 layer is flip-ready. The genuine orphan is the superseded
cell-root monolithic `rendering-v1.json` (replaced by the per-page dir; read by nothing) —
those 41 were quarantined. **Real (validated) re-renders forced: 0** — every cell re-keyed via
the proven byte-identical no-validate path. vol_11's 4 pure-monolith cells (no per-page dir)
were left untouched (the monolith is their only rendering; they have no per-page shape to key).
Committed tool: `build/tools/ocr_pipeline/rekey_s2_renderings.py` + `render_s2.validate_schema`
flag + `tests/test_rekey_s2_renderings.py`.

### R6b / R-final exemption design (the classified-unmapped set)
Each leafmap now carries `unmapped_classified: {stem: {class, words, best_score}}` with
`class ∈ {non-body, body-unrecoverable}`. R6b should exempt an alternate-scan page from the
required-clid flip when **either** the canonical manifest's `kind` for its physical leaf is
not `body` (category exemption) **or** the leafmap classifies it `non-body`/`body-unrecoverable`.
Crucially, R6b's (b) sha-reuse and (c) sha-equality checks are **primary-only** and must be
skipped for alternate scans (they are different physical scans — their sha never appears in the
primary manifest); the alternate-source (a) check is "valid body `leaf_num` present **or**
classified-exempt", and the cross-engine (c) compares **leaf membership**, not sha. See the
rewritten R-final prompt.
