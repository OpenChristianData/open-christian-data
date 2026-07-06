# NSH Affected-Volume Rebuild Runbook (phases 3–4)

**Date:** 2026-06-10
**Prerequisites (all landed):** the fetcher fix (`e6878b38`), the Model-B verifier
(`37344cce`), and the OCR tripwire (`80f80c88`). Read
`docs/NSH_FETCHER_MECHANISM_DIAGNOSIS.md` first.

**Why this is a runbook, not a script run blindly:** a correct rebuild of an
affected volume is volume-specific and partly needs human/OCR adjudication, so it
must be done supervised, one volume at a time, fetch-to-fresh-dir then swap only
after the OCR gate passes. It is NOT a single `--pages all` command — three things
the fetcher cannot infer alone:

1. **Front body pages are unnumbered in scandata.** Printed pages 1..(min−1) carry
   no `pageNumber` in the scandata; they are real body pages mapped by a constant
   leaf offset (`page = leaf − offset`). `--pages all` fetches only scandata-numbered
   pages and would drop them. The offset is per-volume (front-matter length varies).
2. **In-body scan gaps may be recoverable from the haucgoog alternate item** (vols
   2/5/6/8 are in `_HAUCGOOG_VOLS`), not permanently missing — recover via
   `--from-alternate-item` with a verified `--leaf-page-spec`, or mark permanent.
3. **Duplicate pageNumbers need OCR adjudication** (vol_06, vol_11): two leaves claim
   one printed page; only pixels say which is the clean one.

---

## Per-volume specs (from live scandata, 2026-06-10)

`offset = leaf − page` for the front run; front pages map `page → leaf` by it.

| Vol | Numbered range | Front body pages → leaves | Scan gaps | Duplicate pages (leaves) | Class |
|---|---|---|---|---|---|
| 01 | 10–500 | pp1–9 = leaves 37–45 (offset 36) | 96, 97 | — | simple |
| 02 | 9–499 | pp1–8 = leaves 23–30 (offset 22) | 253, 254, 255 | — | simple |
| 05 | 10–508 | pp1–9 = leaves 24–32 (offset 23) | 451–454 | — | simple |
| 08 | 10–500 | pp1–9 = leaves 23–31 (offset 22) | 96, 97 | — | simple |
| 06 | 10–505 | pp1–9 = leaves 21–29 (offset 20) | 361–363, 451–458 | 462–468 (476–482 **and** 486–492) | **adjudicate** |
| 11 | 10–508 | pp1–9 = leaves 28–36 (offset 27) | — | 478 (leaves 505, 506) | **adjudicate** |

Front-page offsets and duplicate-leaf choices are **OCR-verified per volume during
the rebuild**, not trusted blind (the front pages are unnumbered, so the offset is a
hypothesis until a sampled front page's running header confirms it).

For vol_06 the in-sequence copy is leaves 486–492 (they sit correctly between 461
and 469); leaves 476–482 are the misfiled duplicate — confirm by OCR before
discarding. For vol_11, leaves 505/506 both read 478; OCR both and keep the cleaner.

---

## Procedure (one volume at a time)

Throttle to protect the IA limiter (`reference_ia_rate_limit_fallback`): default
`--workers 4`, and if a fetch returns `Retry-After` > 300 the fetcher aborts that
page — stop and resume later, do not hammer. Build into a **fresh** directory so the
current disk is untouched until the OCR gate passes.

```bash
V=08                      # one volume
FRESH=raw/internet-archive/schaff-herzog-pages/vol_${V}_rebuild

# 1. Primary scandata-numbered body (gaps preserved as holes, named by printed page)
py -3 build/tools/fetch_ia_pages.py --volume $V --pages all \
    --out-dir $FRESH --manifest ${FRESH}.manifest.json --workers 4

# 2. Front body pages (unnumbered in scandata) by leaf offset — vol_08 example:
#    pages 1..9 = leaves 23..31. Fetch each leaf to its printed-page name.
#    Use --from-alternate-item with the SAME primary item id is not valid; instead
#    fetch by explicit page->leaf. (Front pages need a small dedicated fetch step;
#    confirm one front page's header by OCR before trusting the whole offset.)

# 3. Recover in-body scan gaps from the haucgoog alternate (vols 2/5/6/8), with a
#    verified leaf-page-spec, OR record them permanent. vol_08 gaps 96,97:
# py -3 build/tools/fetch_ia_pages.py --volume $V \
#     --from-alternate-item <haucgoog-item> --leaf-page-spec "<leaf>:96,<leaf>:97" \
#     --out-dir $FRESH --manifest ${FRESH}.manifest.json

# 4. OCR GATE (full audit) — the definition of done. Point it at the fresh dir.
py -3 build/tools/verify_nsh_running_headers.py --volume $V --pages all --json .tmp_audit/rebuild_v${V}.json
#    Done only when: delta-0 dominant, NO persistent-to-tail run, last body page reads its own N.

# 5. Regenerate manifest gaps[]/page_count (fetcher does page_count; record gaps),
#    then page_order:
py -3 build/tools/generate_page_order.py --vol $V        # (or generate_vol01_page_order.py for vol_01)

# 6. Structural verifier (Model B) must also pass:
py -3 build/tools/verify_nsh_page_accounting.py

# 7. Swap fresh -> live ONLY after 4+6 pass; then commit manifests + page_orders:
git add -f raw/internet-archive/schaff-herzog-pages/vol_${V}.manifest.json \
           raw/internet-archive/schaff-herzog-pages/vol_${V}/page_order.json
git commit -- <those paths>
```

**Order:** simple volumes first (08, 01, 02, 05) — each is deterministic given the
offset + gap recovery. Then the adjudication volumes (11, then 06) with a human/OCR
pass on the duplicate leaves. vol_06 is the hardest (disordered gathering + 7
duplicates + two gap runs) — expect to inspect leaves 476–492 by eye.

**Proof the chain is correct:** a 9-page probe of vol_08 across its gap (pp93–101)
fetched via the fixed fetcher produced files whose OCR'd headers equal their
filenames exactly (page_0098→98 … page_0100→100), with pp96–97 correctly absent.
The post-gap pages that read +offset on the squeezed disk now read delta-0.

**Do not** rebuild vol_10 (already correct, `b436274d`) or the clean controls
(03/04/07/09/12).
