# BLOCKED — leaf-rekey R-final (2026-06-15, scheduled autonomous run)

**Status: HARD STOP. The schema flip was NOT performed. No data was mutated.**

R-final's two parts are (1) extend the verifier to the full chain (R6b) and run it
green corpus-wide, then (2) flip `canonical_leaf_id` to **required** on the four
schemas (`sidecar-page-v1`, `sidecar-manifest-v1`, `rendering-v1`,
`word-confusion-table-v1`). Part (2) is gated on part (1) being green corpus-wide —
"prove the data, then make the schema reject data without the key" (design §5; Codex
review #3-E/G; R5 is deliberately the last step).

**The gate is not green, by a wide margin. R7 (ABBYY / alternate-source alignment) is
substantially incomplete**, so flipping the schema would make ~23,000 already-on-disk
sidecar / manifest / rendering pages schema-invalid in one commit. That is precisely
the failure the optional-first ordering exists to prevent. The autonomous-mode hard
stop ("R6b fails assertion (a) across > 2 cells — do NOT flip the schema while data is
non-compliant") is triggered.

## Why R6b was not built/committed this run

The hard-stop condition R6b's assertion (a) guards — every body page across every
engine carries `canonical_leaf_id` — was measured **directly from the gitignored S1
store** (VER-01: disk is ground truth), which is what R6b would read anyway. The
measurement is conclusive (≈46 non-compliant cells, far over the > 2 threshold), so
building and committing the full-chain verifier tonight would not change the verdict.
It was deferred rather than rushed because the correct alternate-source semantics are
non-trivial (see "R6b design notes" below) and committing a half-specified gate
unattended — with no Codex review or human sanity-check — risks encoding wrong gate
logic into the pre-commit hook. The design notes below are precise enough for the next
session to build R6b test-first and quickly.

## Measured disk state — `canonical_leaf_id` coverage per S1 lineage

Census run 2026-06-15 over `reports/s1-sidecars/*/vol_NN/manifest.json`
(counts = manifest page_refs carrying an int `canonical_leaf_id`):

| Lineage | Cells | Pages | With `canonical_leaf_id` | Coverage | In scope for required flip? |
|---|---|---|---|---|---|
| `tesseract-py314-v1` | 12 | 3487 | 3479 | 99.8% | yes — 8 missing are exempt gaps/needs-alternate |
| `kraken-py312-v1` | 8 | 2857 | 2835 | 99.2% | yes — **14 genuine body residual** + 8 exempt |
| `surya-py312-v1` | 1 | 85 | 85 | 100% | yes — clean |
| `kraken-greek-py312-v1` | 1 | 11 | 11 | 100% | yes — clean |
| `azure-ai-vision-v1` | 11 | 4513 | 3534 | 78.3% | yes — **~979 unaligned** |
| `ia-abbyy-v1` | 13 | 6326 | 5768 | 91.2% | yes — **vol_11 blocked (~558)** |
| `ia-abbyy-dli-v1` | 7 | 3539 | 0 | **0.0%** | yes — **R7 never ran on it** |
| `ia-abbyy-haucgoog-v1` | 11 | 5532 | 0 | **0.0%** | yes — **R7 never ran on it** |
| `ia-abbyy-haucgoog-c1-v1` | 10 | 5031 | 0 | **0.0%** | yes — **R7 never ran on it** |
| `ia-abbyy-haucgoog-c2-v1` | 8 | 3802 | 0 | **0.0%** | yes — **R7 never ran on it** |
| `ia-abbyy-haucgoog-c3-v1` | 5 | 2545 | 0 | **0.0%** | yes — **R7 never ran on it** |
| `ia-abbyy-haucgoog-c4-v1` | 2 | 1003 | 0 | **0.0%** | yes — **R7 never ran on it** |

These ABBYY/azure lineages are active engine inputs (referenced in `build/lib/wct_builder.py`,
`build/tools/ocr_pipeline/drive_reconciliation_chain.py`, `run_ocr_pipeline.py`), so
their pages are in scope for a leaf-required schema. Under the flip they would all fail
validation.

## Exact remaining work before R-final can run

### 1. Finish R7 — the dominant blocker (~23,000 unaligned pages)

Per `plans/2026-06-13-nsh-leaf-rekey-design.md` §6 + the `ocr-runners.md` lineage rule:

- **`ia-abbyy-v1` vol_11** — BLOCKED; needs visual sampling on the +4 (canon page 261)
  and +6 (canon page 410) field-offset transitions + the 408/409 binding transposition.
  See `docs/BLOCKED-leafrekey-R7-ia-abbyy-v1-vol11-2026-06-15.md`. (~558 pages.)
- **`ia-abbyy-dli-v1`** (7 cells), **`ia-abbyy-haucgoog-v1`** (11), **`-c1..c4`** (25 cells
  total) — never aligned (0% each). For each volume: select the lineage via
  `probe_abbyy_confidence.py --compare`, run `abbyy_leaf_alignment.compute_alignment`,
  PIPE-29 content-verify the offset against the running header (visual fallback on
  digit-confused runs), then `normalize_abbyy_rich_volume(..., force-stamp)`.
- **`azure-ai-vision-v1`** — 78.3%; top up the unaligned cells/pages the same way the
  aligned azure cells were stamped (the 2C azure import path already stamps; re-run on
  the missing cells).

The alignment oracle + normalizer paths exist and are tested; this is execution +
content verification work, not new design — except vol_11, which needs human judgment.

### 2. Re-stamp the R6a primary residual — 14 kraken body leaves (3 cells)

All sha-resolvable (reuse held; NOT a re-OCR). Confirmed on disk 2026-06-15:

- `kraken-py312-v1/vol_01`: `page_0168`  (1)
- `kraken-py312-v1/vol_04`: `page_0285, 0302, 0336, 0356, 0433, 0454, 0461, 0474, 0494`  (9)
- `kraken-py312-v1/vol_05`: `page_0084, 0203, 0224, 0259`  (4)

(The tesseract "missing" pages and the kraken `page_0096/0097/0398` etc. are exempt
recovered-`gaps[]` / needs-alternate pages — they legitimately carry no single
`canonical_leaf_id` and are NOT failures.)

Re-stamp via the fixed migration tool (`migrate_s1_to_leaf_key.py --apply` on those
cells) or a targeted stamp pass. Deferred this run: it does not unblock R-final (ABBYY
still blocks), and autonomous `--apply` on the gitignored store carries the
clobber-class risk that R3-apply already burned two sessions on — better done with a
human watching.

### 3. Build + run R6b green corpus-wide, THEN flip

Only after 1 + 2: extend `verify_leaf_keying.py` to full chain, run green, flip schema.

## R6b design notes (so the next session can build it correctly)

R6a's `classify_page` keys on the **primary** manifest's `leaf_by_sha`. ABBYY/azure
pages cannot use that path — by design their `source_payload_sha256 = sha(rich GZ /
azure JSON)` from an **alternate scan**, so they never SHA-match a primary image and
`by_sha.get(sha)` returns `None`. Feeding ABBYY pages through R6a's logic unchanged
would (wrongly) bucket every one as `UNRESOLVED` — i.e. as a re-OCR (b) failure, which
is meaningless for an alternate source. R6b therefore needs alternate-source-aware
rules:

- **(a) for alternate-source lineages:** require an int `canonical_leaf_id` that is a
  valid **body** `leaf_num` in the current manifest. The stamp itself is the join key
  (it was content-verified at R7 alignment time); the verifier confirms presence +
  structural validity, not sha-resolution. Legitimately-unmapped pages (recovered
  `gaps[]`, front/back matter the alignment logged as unmapped) are exempt — but the
  verifier cannot re-derive "should-have-been-mapped" without re-running alignment, so
  R6b should treat a 0%-stamped cell as a **failure** (R7 not run), and a mostly-stamped
  cell's stray unstamped body pages as failures unless they match the alignment's logged
  unmapped set. Decide the exemption source (persist the R7 `unmapped_pages` log per
  cell so R6b can read it) when building R6b.
- **(b) reuse / no-re-OCR:** does NOT apply to alternate sources (no SHA-match to a
  primary). Skip (b) for ABBYY/azure.
- **(c) cross-engine sha-equality:** does NOT apply across primary↔alternate (different
  scans → different shas by design). The leaf_num is the join, not the sha. R6b's
  cross-engine check must compare leaf_num membership/agreement, not sha equality, when
  an alternate source is involved.
- **(d) S2 rendering dir ⊆ S1 leaves:** applies as-is.
- Critically, for the **final gate** semantics: any in-scope body page that would become
  schema-invalid under the required flip MUST count as a failure (do NOT use R6a's
  "pending re-render / pending alignment = coverage gap, not failure" softening, or R6b
  would pass while leaving data the flip then rejects).

## Constraint compliance this run

- **C1 zero re-OCR:** no engine invoked; no data mutated. The (b) reuse check on the
  primary store is clean (census shows every primary residual page is sha-resolvable).
- **C3 / C5:** verdict derived from the current canonical manifests via the shared
  accessor census, not from stored values.
- Schema left **optional** (unchanged) — every intermediate state stays runnable.
