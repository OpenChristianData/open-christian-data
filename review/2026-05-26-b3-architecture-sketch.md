# B3 workbench — architecture sketch (post-D11 TUNE → PROCEED)

Conditional on the D11 tuning patch (drop insert/delete ops, normalise
Unicode quotes) landing first. Phase 2 D11 raw precision is 0.433 (TUNE);
filter 1 projects 0.684 (PROCEED). Build B3 only after re-measuring on the
tuned generator with n=50.

## Source data

Per-page artifacts already produced this session (vol 1):

- `data/reference/schaff/encyclopedia/1908-1914/oss-tesseract-v1/vol_01.json`
- `data/reference/schaff/encyclopedia/1908-1914/azure-v1/vol_01.json`
- `data/reference/schaff/encyclopedia/1908-1914/ia-abbyy-v1/vol_01.json`
- `raw/internet-archive/schaff-herzog-pages/vol_01/page_NNNN.jpg`
- `raw/internet-archive/schaff-herzog-pages/vol_01/page_NNNN.ia-abbyy.json`
  (word-level bbox + confidence)
- `raw/internet-archive/schaff-herzog-pages/vol_01/page_NNNN.oss-tesseract.json`
  (word-level bbox + x-size + confidence)
- Azure sidecars: page_NNNN.azure.json (single-block per page; per-word
  4-point polygon)

The flagger writes one JSONL file per volume:
`review/d11/vol_01.flags.jsonl` — one flag per non-`equal` `replace`-tag op
(after tuning), with anchor_pos, anchor_tokens, attestor_tokens,
attestor_engine, page_class.

## Rendering surface

The reviewer UI is one page at a time. For the current flag:

1. **Header**: page number, page class, flag count on this page.
2. **Scan pane** (left): the source JPEG with a **word-level highlight**
   over the disputed bbox region. Use
   `build/lib/ocr_coordinates.read_json_sidecar` + `lookup_word_bbox` to
   resolve the anchor token's bbox from the ABBYY sidecar; on hover, show
   the bbox of the Tesseract / Azure equivalent (different bbox because
   different segmentation). Annotate boxes by engine colour:
   ABBYY=gray, Tess=blue, Azure=green.
3. **Reading pane** (right): three columns side by side
   (`ABBYY | Tesseract | Azure`), showing ±5 tokens around the disputed
   span with the disputed tokens highlighted. Click any token to expand
   the underlying word's confidence and bbox.

## Reviewer actions

Per flag, the reviewer chooses one of:

| Action | Effect |
|---|---|
| Accept (anchor) | record ABBYY's reading as canonical; flag closed |
| Accept (attestor: tess) | record Tesseract's reading as canonical |
| Accept (attestor: azure) | record Azure's reading as canonical |
| Amend | type a corrected reading not present in any rendering |
| Reject (alignment artifact) | mark the flag as FP — alignment skew, no real disagreement |
| Defer | keep flag open; come back later |

Keyboard shortcuts: `a` / `t` / `z` / `e` (amend) / `r` (reject) / `d` (defer)
/ `n` (next) / `p` (previous).

## Output

One per-volume corrections JSON written atomically per accepted action:
`review/d11/vol_01.corrections.json`

Schema:

```json
{
  "vol": 1,
  "started_at": "2026-...",
  "reviewer": "username",
  "decisions": [
    {
      "flag_id": 14163,
      "page": 102,
      "anchor_pos": 311,
      "action": "accept_attestor",
      "attestor": "azure",
      "canonical_text": ["Grätz,", "Geschichte", "der", "Juden,", "vol.", "iv."],
      "decided_at": "2026-..."
    }
  ]
}
```

The canonical reading then flows into the reconciler output (block-level)
as a structural correction during the next reconcile pass.

## Implementation cost estimate

- Backend: ~300 LOC FastAPI service that loads the flag JSONL, serves
  per-flag context (3 OCR text windows + JPEG crop region), accepts POST
  for actions, atomically appends to corrections.json.
- Frontend: ~500 LOC React (or htmx + alpine) — scan pane uses a static
  JPEG with absolutely-positioned `<div>` highlights; reading pane is
  three vertically-aligned columns of `<span>`s. No fancy framework.
- Total: 1 dev-day for working v0, 2-3 days for keyboard polish + tests.

The B3 build does NOT touch the reconciler library (`build/lib/reconcile/*`)
or the cloud OCR runner. It is purely a per-flag adjudication UI plus a
correction-output writer.

## Out of scope for B3

- Multi-reviewer concurrent editing
- Per-flag confidence weighting (already in sidecars; UI displays it but
  doesn't gate actions)
- Auto-suggest corrections (deferred to B5)
- Per-volume progress dashboard (single-volume scope at first)
