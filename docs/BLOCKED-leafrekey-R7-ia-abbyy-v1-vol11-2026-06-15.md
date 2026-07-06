# RESOLVED (2026-06-15) — R7 ABBYY alignment, `ia-abbyy-v1` vol_11

**Resolution:** Content-confirmed and stamped. The field-offset oracle could not
auto-verify vol_11 (multi-step field drift from inserted plates), so the design's
visual/manifest fallback was applied. The running-header **printed page** (PIPE-29
content oracle, read off the rich-file text — not the digit-confused scandata field)
confirms the stem assignment at every transition:

| stem | canonical page | rich running-header reads | verdict |
|---|---|---|---|
| `page_0261` | 261 | **261** | confirm |
| `page_0408` | 408 | 406 (6<->8 OCR misread) — **content = Theosophy**, a verso page bracketed by recto 407 (Theophilus) and recto 409 (Theosophy); the **primary tesseract** at canonical leaf 441 (page 408) also reads "Theosophy" | confirm |
| `page_0409` | 409 | **409** | confirm |
| `page_0410` | 410 | **410** | confirm |

The only "disagreement" (page_0408 header glyph "406") is a single-digit OCR misread,
not a mis-assignment: the page is a verso bracketed by correctly-read 407/409, its body
is unambiguously Theosophy content, and the **primary scan** (the canonical manifest's
own OCR) holds Theosophy at canonical page 408. So the stem -> leaf assignment is correct
across the +4 (canon 261) and +6 (canon 408-410) field-drift steps and the 408/409
binding transposition (encoded in the canonical manifest: page_0409 -> leaf 440, page_0408
-> leaf 441).

`ia-abbyy-v1` is the **same physical IA scan** as the canonical primary
(`NewSchaffHerzogEncyclopediaOfReligious`) — proven by full-page text overlap (mean
Jaccard 0.805 vs primary, 100% per-stem clid agreement) — so same-stem stamping is valid.
Stamped via `normalize_abbyy_rich_volume(source_lineage_id="ia-abbyy-v1", volume=11)`:
503 page_refs carry `canonical_leaf_id`, 0 unmapped. `ia-abbyy-v1` is now 100% (all 13
volumes). No re-OCR.

---

## (Original block, superseded — kept for the audit trail)

# BLOCKED — R7 ABBYY alignment, `ia-abbyy-v1` vol_11

**Date:** 2026-06-15
**Step:** R7 (ABBYY / alternate-source alignment)
**Scope of block:** ONE cell only — lineage `ia-abbyy-v1`, volume 11. All other
`ia-abbyy-v1` volumes (01–10, 12, 13) verified clean and were stamped this session.

## What tripped the hard-stop

The R7 alignment oracle (`build/tools/ocr_pipeline/abbyy_leaf_alignment.py`)
reports vol_11 **not verified**:

```
vol_11: VERIFIED=False  modal_offset=0  confidence=0.517  sustained_bad_run=147
offset distribution (abbyy page_num field - canonical page_num): {0: 260, 4: 148, 6: 95}
  canon_page 1   .. 260  : offset 0
  canon_page 261 .. 407  : offset +4
  canon_page 408         : offset +6   (the documented 408/409 binding transposition)
  canon_page 409         : offset +4
  canon_page 410 .. end  : offset +6
```

This is a **multi-step, non-constant offset** — exactly the hard-stop condition in
the R7 prompt ("a sustained, non-constant offset across > 5 consecutive pages …
complex misalignment not correctable by a single offset value"). It is **not** a
single global offset and cannot be corrected by one value.

## Why it is vol_11-specific (and consistent with prior findings)

The offset here is `ABBYY scandata page_num field` − `canonical manifest page_num`.
The `ia-abbyy-v1` alternate scan for vol_11 carries **extra leaves** (plates /
inserts) the primary scan does not, so ABBYY's *flat* `page_num` field drifts +4
after canon page 260 and +6 after canon page 407. This matches the recorded
vol_11 history:

- memory `project_nsh_p1_vol11_done`: "leaf_num = ABBYY page_index, page_num = true
  (**not ABBYY's field**); 408/409 binding transposition".
- `build/lib/nsh_leaf_model.py` docstring: "Volumes with a mid-body plate (vols
  10/11) have a non-constant offset".

So ABBYY's `page_num` field is a known-unreliable signal for vol_11 — which is why
the field-based oracle (correct for the other 12 volumes) cannot auto-verify it.

## Why it is NOT safe to stamp anyway

Stamping uses `nsh_leaf_model.canonical_leaf_id(stem, manifest)` — i.e. the rich
file's **primary stem** (`page_0261` → canonical page 261 via the plate-aware
manifest). If the stems were assigned correctly at fetch/assemble time, stamping
would be correct *despite* the field drift. **But the fetch step may have mapped
the alternate scan's leaves onto primary stems using that same flat field
sequence** — in which case `page_0261.ia-abbyy.json` could actually hold the
alternate scan's content for primary page 257 (off by 4). That is precisely the
PIPE-29 silent-mis-map this step exists to catch, and it cannot be ruled out from
the field alone.

The running-header glyph (the PIPE-29 content oracle) is degraded by the
documented NSH digit confusion (2↔8, 3↔8, 2↔9 — printed "20" OCRs as "80"), so it
cannot be trusted as an automated per-page proof on the affected runs either
(header corroboration on vol_11 is only 0.34).

## What unblocks it (human / next-session action)

The design's prescribed fallback (§6, Codex#3 OQ4): **visual / manifest sampling**
on the two transition runs. Concretely, confirm by eye (or a digit-confusion-
tolerant header check) that:

1. `page_0261.ia-abbyy.json` running header / content actually shows printed page
   **261** (not 257) — proves the stem was assigned to the right alternate leaf
   across the +4 step at canon 261.
2. `page_0408`/`page_0409` content matches the canonical 408/409 binding
   transposition.
3. `page_0410.ia-abbyy.json` content shows printed page **410** across the +6 step.

If all three confirm the stem assignment is correct, vol_11 can be stamped via the
existing normalizer path (no offset correction needed — the stem is the key, the
field drift is irrelevant). If any disagree, the rich files need re-mapping onto
the correct alternate leaves before stamping.

## State left on disk

- vol_11 `ia-abbyy-v1` S1 sidecars + manifest: **untouched** (not stamped).
- All other `ia-abbyy-v1` volumes: manifest page_refs stamped with
  `canonical_leaf_id` (WCT-lane closure), this session.
- No re-OCR. No engine invoked. Stores are gitignored.
