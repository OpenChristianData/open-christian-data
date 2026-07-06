# DESIGN — NSH unified leaf-sequence manifest model (Phase P0)

**Date:** 2026-06-11
**Status:** DRAFT for approval. Design-and-approve only — no manifest migrated, no schema
applied to `schemas/v1/`, no enums regenerated, no images fetched. Approval unblocks P1
(vol_11 swap), P2 (migrate all 13 manifests), P3 (front/back imaging).
**Supersedes:** the shelved "refined Option A" in
`research/2026-06-11-nsh-manifest-schema-nonnumbered-leaves.md` (it would have blessed the
double-record bug).
**Program tracker:** `docs/NSH_PROJECT_STATE.md` Part 2 ("NSH manifest model redesign").
**Evidence base:** `research/2026-06-11-nsh-coverage-positioning-audit.md` (F1–F6) plus the
live verification recorded in §0 below.

---

## 0. What was verified live this session (vs carried from the audit)

The migration's foundation is the claim "scandata is the complete physical-leaf spine, and
its `leafNum` is the leaf coordinate the manifest already keys on." The audit could not check
this offline (no live scandata). This session pulled live scandata and reconciled it.

| Claim | How checked this session | Result |
|---|---|---|
| scandata enumerates every physical leaf, contiguous, no internal numbering holes | `build/tools/probe_nsh_scandata.py 3 1 12 7` (live) | **Verified** on 4 volumes: vol_03=531 leaves, vol_01=541, vol_12=645, vol_07=533; each a contiguous `leafNum` run `0..total-1`; in-range scan gaps only on vol_01 (printed 96,97) |
| scandata leaf set reconciles to the manifest's leaf set | recomputed vol_03 manifest leaf span vs scandata total | **Verified**: 500 pages + 32 front + 8 back = 540 records; unique leaf span `0..530` (531 leaves) = scandata total; `540 − 531 = 9` = the overlap |
| vol_03 front/body overlap is leaves 23–31 (the double-record bug) | census probe + offset math (offset 22: printed 1 = leaf 23) | **Verified**: front_matter leaves 23–31 are identical to reconstructed body pages 1–9 |
| vol_01 has 52 orphan `leaf_*.jpg` not referenced by its manifest | disk glob of `vol_01/leaf_*.jpg` | **Verified**: 52 files = leaves `0..45` (46) + `535..540` (6) |
| (new finding) some of vol_01's orphan images are body pages, not front matter | offset math (vol_01 offset 36: printed 1 = leaf 37) | **Verified**: leaves 37–45 are printed pages 1–9, already imaged as `page_0001..page_0009.jpg`; 9 of the 52 orphans double the body |
| printed numbering can start at a page other than 10 | vol_07 probe | **Verified**: vol_07 numbers from printed page **3** (offset 24), not 10 |
| every listed consumer's coupling to the manifest shape | read each call site (§3) | **Verified** by reading the code, not memory; `export_hf_dataset.py` does **not** read source manifests |

**Carried from the audit / handoffs, NOT re-verified against pixels this session:**

- vol_11's 2 plates and 4 discards content analysis (perceptual distance 0.26, ink %, text
  continuity 260→261) — from `research/2026-06-11-handoff-vol11-resume.md`. The census is
  consistent with it (vol_11 shows mid-body leaf jumps and 4 tail holes), but I did not
  re-OCR vol_11 pixels here.
- vol_10's ordering anomaly (−11 leaf jump at printed 496→497) — from the census on the
  current (pre-repair-finalization) manifest.
- F5 (blank detection needs pixels; scandata `pageType` is uniform "Normal") — carried.
- scandata completeness for the **other 9 volumes** (02, 04, 05, 06, 08, 09, 10, 11, 13):
  **not probed live this session.** P2 must run `probe_nsh_scandata.py` per volume before
  migrating it. The 4 probed volumes span old-form (03, 07, 12) and a rebuilt vol (01) and
  all behaved identically, which raises confidence but is not proof for the rest.

---

## 1. The leaf record + manifest shape

### 1.1 The one idea

Replace the two arrays `pages[]` + `unnumbered_leaves[]` with **one ordered array
`leaves[]`**, one record per physical leaf, sorted by `leaf_num`. Each leaf carries its
printed `page_num` if the book printed one (`null` if not). `front_matter` / `body` /
`plate` / `back_matter` are **derived from position**; `discarded` is the one editorial flag.
Image provenance is present **only when the leaf's image is downloaded**, mirroring the
conditional already used by `page_record`.

Because every leaf appears exactly once and is keyed by its physical coordinate, the
double-record bug (a leaf in both `pages[]` and `front_matter`) becomes structurally
impossible — there is nowhere to record it twice.

### 1.2 The leaf coordinate (load-bearing definition)

`leaf_num` is the **primary-scan** `leafNum` from IA scandata — the physical position in the
bound volume. It is the primary key and the sort key.

- For a leaf scandata numbered (printed body page), `leaf_num` = scandata `leafNum` and
  `page_num` = scandata `pageNumber`.
- For the **reconstructed leading run** (pages the book printed before scandata starts its
  numbering — vol_03 printed 1–9), `page_num` is reconstructed from the front offset
  (`leaf_num = page_num + offset`), cross-checked against the existing `pages[]` and, where
  pixels exist, the running-header OCR. It is **one record**, `kind = "body"` — never also a
  front-matter record.
- For a body page whose image was recovered from an **alternate source** (haucgoog holes in
  vols 02/05/06/08/10), `leaf_num` is still the **primary-scan** coordinate
  (`page_num + offset`). The alternate item's own leaf index lives in provenance
  (`ia_item_id` + `ia_leaf_id`), never in `leaf_num`. This is the single most important rule
  for mixed-source volumes: ordering by `leaf_num` is only coherent because `leaf_num` is
  always the primary-scan coordinate.

### 1.3 The leaf record

| Field | Type | When required | Meaning |
|---|---|---|---|
| `leaf_num` | int ≥ 0 | always | primary-scan leaf coordinate; primary key + sort key |
| `page_num` | int ≥ 1 \| null | always | printed page number, or `null` if the leaf carries no printed number |
| `kind` | enum | always | `front_matter` \| `body` \| `plate` \| `back_matter` \| `discarded`; **derived** (§1.5), stored for queryability, pinned by a test |
| `image_state` | enum | always | `present` \| `pending` \| `unresolved` \| `not_imaged` (§1.4) |
| `after_page_num` | int ≥ 1 | plates only | the printed page a plate follows (vol_11 plate → 260); cross-checked against leaf order |
| `blank` | bool | optional (default false) | a positioned leaf with no content; no image expected (R2 exemption) |
| `discard_reason` | string | iff `kind = discarded` | e.g. `"blank plate back"`, `"exact duplicate of printed 408"` |
| `duplicate_of_page` | int ≥ 1 | optional (discarded dupes) | the printed page this discarded leaf duplicates |
| `local_path` | string | optional | repo-root-relative image path; its presence triggers the provenance block |
| `ia_leaf_id` | string `^[0-9]+$` | with `local_path` | **source item's** leaf index (may differ from `leaf_num` for alternate sources) |
| `ia_filename` | string | with `local_path` | source archive path |
| `ia_item_id` | string | with `local_path` | source IA item (primary or alternate) |
| `sha256` | `^sha256:[0-9a-f]{64}$` | with `local_path` | image hash |
| `fetched_at` | date-time | with `local_path` | fetch timestamp |
| `image_mode` | string | with `local_path` | PIL mode |
| `image_size` | [int,int] | with `local_path` | pixel dims |

### 1.4 `image_state` — makes R2 auditable in one pass

| value | meaning | `local_path`? |
|---|---|---|
| `present` | image downloaded and on disk | yes |
| `pending` | image expected (non-blank, recoverable) but not yet fetched | no |
| `unresolved` | the primary scan has no usable derivative (a body hole); recovery from an alternate source is open | no |
| `not_imaged` | no image expected — `blank` leaf or `discarded` leaf | no |

R2 audit = "every non-blank, non-discarded leaf eventually reaches `present`." A leaf at
`pending` is the P3 work-list; a leaf at `unresolved` is the Part-B hole work-list.

### 1.5 `kind` derivation (the rule a test pins)

`kind` is a pure function of the other fields, computed by the migration and re-derived by a
test (no human/OCR guess enters it):

```
first_body = min(leaf_num for leaves where page_num is not null)
last_body  = max(leaf_num for leaves where page_num is not null)

def derive_kind(leaf):
    if leaf.discard_reason is not None:      return "discarded"
    if leaf.page_num is not None:            return "body"
    if leaf.leaf_num < first_body:           return "front_matter"
    if leaf.leaf_num > last_body:            return "back_matter"
    return "plate"                            # null page_num, inside the body span
```

A `tests/` case re-derives `kind` for every leaf of every migrated manifest and asserts
equality with the stored value (TEST-08: automate the invariant in the same change).

### 1.6 Image naming convention (keeps the `page_*` namespace clean)

| kind | filename | key | globbed by existing tooling? |
|---|---|---|---|
| body | `page_NNNN.jpg` | `page_num` | yes — `page_*.jpg` (unchanged) |
| front_matter / back_matter | `leaf_NNNN.jpg` | `leaf_num` | yes — `leaf_*.jpg` (existing vol_01 convention) |
| plate | `plate_<after_page>_<seq>.jpg` → `plate_0260_01.jpg` | — | **no** — non-`page_` / non-`leaf_` prefix; invisible to every current glob |
| discarded | (no live image; pixels quarantined) | — | no |

The three numbered-page consumers (`verify_nsh_page_accounting.py`,
`nsh_precommit_ocr_gate.py`, `generate_page_order.py`) glob `page_*.jpg` and parse
`int(stem.split("_")[1])` as a **page number**. `plate_0260_01.jpg` matches none of their
globs, so it can never be mis-parsed as page 260. Confirmed by reading the globs (§3).

### 1.7 DRAFT JSON Schema (NOT applied to `schemas/v1/` this session)

The new schema accepts **two top-level shapes** during the transition: the legacy two-list
shape (deprecated) and the new leaf-sequence shape. This lets P1 land vol_11 in the new model
while vols 1,2,5,6,8 keep validating in the legacy shape until P2 migrates them — no flag day.
A later major bump removes the legacy branch.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/openchristiandata/open-christian-data/schemas/v1/source_manifest.schema.json",
  "x-ocd-schema-version": "4.0.0",
  "title": "Internet Archive Source Manifest",
  "description": "Per-volume manifest of IA page images. v4 adds the unified leaf-sequence shape (leaves[]); the legacy pages[]+unnumbered_leaves[] shape is accepted-but-deprecated for the migration window.",
  "type": "object",
  "additionalProperties": false,
  "required": ["ia_item_id", "ia_derivative_type", "volume", "created_at"],
  "properties": {
    "ia_item_id": { "type": "string" },
    "ia_derivative_type": { "type": "string" },
    "volume": { "type": "integer", "minimum": 1 },
    "created_at": { "type": "string", "format": "date-time" },
    "page_count": {
      "type": ["integer", "null"], "minimum": 0,
      "description": "Count of numbered body leaves (page_num not null). Null retained for legacy."
    },
    "leaves": { "type": "array", "items": { "$ref": "#/$defs/leaf_record" } },
    "pages": { "type": "array", "items": { "$ref": "#/$defs/page_record" },
               "description": "DEPRECATED (legacy shape). Removed in a future major version." },
    "unnumbered_leaves": { "type": "array", "items": { "$ref": "#/$defs/unnumbered_record" },
               "description": "DEPRECATED (legacy shape)." },
    "gaps": { "type": "array", "items": { "$ref": "#/$defs/gap_record" } },
    "manifest_warnings": { "type": "array", "items": { "type": "string", "minLength": 1 } }
  },
  "oneOf": [
    { "title": "new leaf-sequence shape", "required": ["leaves"],
      "not": { "anyOf": [ { "required": ["pages"] }, { "required": ["unnumbered_leaves"] } ] } },
    { "title": "legacy two-list shape (deprecated)", "required": ["page_count", "pages"],
      "not": { "required": ["leaves"] } }
  ],
  "$defs": {
    "leaf_record": {
      "type": "object",
      "additionalProperties": false,
      "required": ["leaf_num", "page_num", "kind", "image_state"],
      "description": "One physical leaf. Provenance fields are required only when local_path is present (mirrors page_record).",
      "properties": {
        "leaf_num": { "type": "integer", "minimum": 0 },
        "page_num": { "type": ["integer", "null"], "minimum": 1 },
        "kind": { "type": "string",
                  "enum": ["front_matter", "body", "plate", "back_matter", "discarded"] },
        "image_state": { "type": "string",
                  "enum": ["present", "pending", "unresolved", "not_imaged"] },
        "after_page_num": { "type": "integer", "minimum": 1 },
        "blank": { "type": "boolean" },
        "discard_reason": { "type": "string", "minLength": 1 },
        "duplicate_of_page": { "type": "integer", "minimum": 1 },
        "local_path": { "type": "string", "minLength": 1 },
        "ia_leaf_id": { "type": "string", "pattern": "^[0-9]+$" },
        "ia_filename": { "type": "string", "minLength": 1 },
        "ia_item_id": { "type": "string", "minLength": 1 },
        "sha256": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" },
        "fetched_at": { "type": "string", "format": "date-time" },
        "image_mode": { "type": "string", "minLength": 1 },
        "image_size": { "type": "array", "items": { "type": "integer", "minimum": 1 },
                        "minItems": 2, "maxItems": 2 },
        "provenance": { "$ref": "#/$defs/provenance" },
        "source_note": { "type": "string" }
      },
      "allOf": [
        { "if": { "required": ["local_path"] },
          "then": { "required": ["sha256", "fetched_at", "image_mode", "image_size",
                                 "ia_leaf_id", "ia_filename", "ia_item_id"] } },
        { "if": { "properties": { "kind": { "const": "plate" } }, "required": ["kind"] },
          "then": { "required": ["after_page_num"] } },
        { "if": { "properties": { "kind": { "const": "discarded" } }, "required": ["kind"] },
          "then": { "required": ["discard_reason"] } },
        { "if": { "properties": { "kind": { "const": "body" } }, "required": ["kind"] },
          "then": { "properties": { "page_num": { "type": "integer" } } } }
      ]
    },
    "page_record": { "...": "UNCHANGED from 3.1.0 (legacy)" },
    "unnumbered_record": { "...": "UNCHANGED from 3.1.0 (legacy, deprecated)" },
    "gap_record": { "...": "UNCHANGED from 3.1.0" },
    "crop_box": { "...": "UNCHANGED" },
    "provenance": { "...": "UNCHANGED — now referenced by leaf_record too (alternate-source crop/hole audit trail: source_item_id, source_leaf, derivation crop_2up_left|right, crop_box, validation_status)" }
  }
}
```

> Positional invariants jsonschema cannot express — the **migration tool + a `tests/`
> assertion must enforce these**, not the schema: `leaf_num` unique and strictly increasing;
> `page_num` unique among non-null; a plate's `after_page_num` satisfies
> `leaf(after_page_num) < plate.leaf_num`; `page_num` monotonic with `leaf_num` (soft — flags
> vol_10); `kind` equals `derive_kind`; **a leaf whose pixels came from a non-primary IA item
> (`ia_item_id != ` the manifest's primary item — alternate-source crop/hole) carries a
> `provenance` block.** The last is a cross-field comparison jsonschema cannot make, so it is
> a migration + test invariant, not a schema rule; `provenance` is an optional property on
> `leaf_record` so the existing `crop_2up_left/right` audit trail (`fetch_ia_pages.py:582-587`)
> survives the migration intact.

### 1.8 Worked leaf records

Illustrative. vol_03 / vol_01 values use this session's verified offsets; vol_11 leaf numbers
are derived from the offset and marked for confirmation in P1.

```jsonc
// 1. Front matter, imaged (vol_01 leaf 5 — a real front leaf, page_num null)
{ "leaf_num": 5, "page_num": null, "kind": "front_matter", "image_state": "present",
  "local_path": "raw/internet-archive/schaff-herzog-pages/vol_01/leaf_0005.jpg",
  "ia_leaf_id": "0005", "ia_filename": "01.New...1909._jp2/01.New...1909._0005.jp2",
  "ia_item_id": "newschaffherzoge01macauoft", "sha256": "sha256:<64hex>",
  "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [1648, 2516] }

// 2. Numbered body page (vol_03 printed 100 = leaf 122, offset 22)
{ "leaf_num": 122, "page_num": 100, "kind": "body", "image_state": "present",
  "local_path": "raw/internet-archive/schaff-herzog-pages/vol_03/page_0100.jpg",
  "ia_leaf_id": "0122", "ia_filename": "03.New...1909._jp2/03.New...1909._0122.jp2",
  "ia_item_id": "newschaffherzo03macauoft", "sha256": "sha256:<64hex>",
  "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [1648, 2516] }

// 3. Reconstructed leading body page (vol_03 printed 1 = leaf 23) — ONE record, kind=body,
//    NOT also front_matter. This is the leaf the old form double-recorded.
{ "leaf_num": 23, "page_num": 1, "kind": "body", "image_state": "present",
  "local_path": "raw/internet-archive/schaff-herzog-pages/vol_03/page_0001.jpg",
  "ia_leaf_id": "0023", "ia_filename": "03.New...1909._jp2/03.New...1909._0023.jp2",
  "ia_item_id": "newschaffherzo03macauoft", "sha256": "sha256:<64hex>",
  "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [1648, 2516],
  "source_note": "page_num reconstructed from front offset; cross-checked vs pages[] + header OCR" }

// 4. Mid-body plate (vol_11, after printed 260; leaf_num illustrative, confirm in P1)
{ "leaf_num": 288, "page_num": null, "kind": "plate", "after_page_num": 260,
  "image_state": "present",
  "local_path": "raw/internet-archive/schaff-herzog-pages/vol_11/plate_0260_01.jpg",
  "ia_leaf_id": "0288", "ia_filename": "11.New...1911._jp2/11.New...1911._0288.jp2",
  "ia_item_id": "newschaffherzo11macauoft", "sha256": "sha256:<64hex>",
  "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "RGB", "image_size": [1648, 2516] }

// 5. Blank leaf, positioned but not imaged (R2 exemption) — e.g. a blank front-matter verso
{ "leaf_num": 6, "page_num": null, "kind": "front_matter", "image_state": "not_imaged",
  "blank": true }

// 6. Discarded duplicate (vol_11 leaf ~412 duplicates printed 408; pixels quarantined)
{ "leaf_num": 412, "page_num": null, "kind": "discarded", "image_state": "not_imaged",
  "discard_reason": "exact duplicate of printed 408", "duplicate_of_page": 408 }

// 7. Back matter, imaged (vol_01 leaf 536 — after body max leaf 534)
{ "leaf_num": 536, "page_num": null, "kind": "back_matter", "image_state": "present",
  "local_path": "raw/internet-archive/schaff-herzog-pages/vol_01/leaf_0536.jpg",
  "ia_leaf_id": "0536", "ia_filename": "01.New...1909._jp2/01.New...1909._0536.jp2",
  "ia_item_id": "newschaffherzoge01macauoft", "sha256": "sha256:<64hex>",
  "fetched_at": "2026-06-11T00:00:00+00:00", "image_mode": "L", "image_size": [1648, 2516] }
```

---

## 2. How each real case maps

| Case | Record shape | How its position is known |
|---|---|---|
| **Front matter** (all 13 vols) | `page_num: null`, `kind: front_matter`, `leaf_NNNN.jpg` | `leaf_num < first_body_leaf` (scandata leaf order) |
| **Numbered body page** (all) | `page_num: N`, `kind: body`, `page_NNNN.jpg` | scandata `leafNum` + `pageNumber` |
| **vol_03-style reconstructed leading page** (printed 1–9 = leaves 23–31) | **one** record: `page_num: 1..9`, `kind: body`, `page_000N.jpg` | `leaf_num = page_num + offset` (offset 22, verified); cross-checked vs `pages[]` + header OCR. The old form's second copy in `front_matter` is **dropped** |
| **vol_11 plate** (2 leaves between printed 260 and 261) | `page_num: null`, `kind: plate`, `after_page_num: 260`, `plate_0260_0S.jpg`, full provenance | `leaf(260) < plate.leaf_num < leaf(261)` |
| **vol_11 discard** (blank plate-backs 261/264; dup-of-408 at 412; dup-of-409 at 415) | `page_num: null`, `kind: discarded`, `discard_reason`, `duplicate_of_page` where applicable, `image_state: not_imaged` | positioned by `leaf_num`; pixels quarantined |
| **Blank leaf** (kept, unimaged) | `page_num: null`, `kind` by position, `blank: true`, `image_state: not_imaged` | positioned by `leaf_num`; blankness confirmed only after P3 pixels (F5) |
| **Back matter** (all) | `page_num: null`, `kind: back_matter`, `leaf_NNNN.jpg` | `leaf_num > last_body_leaf` |
| **Body hole** (vols 01/02/05/06/08 scan gaps) | `page_num: N`, `kind: body`, `image_state: unresolved` (or `present` if recovered from alternate; provenance carries the alternate item) | `leaf_num = N + offset` (primary coordinate, even when pixels came from haucgoog) |

**The double-count is gone by construction:** there is one `leaves[]`, each leaf appears
once. vol_03's leaves 23–31 are `kind: body` with `page_num 1..9` and have no second home.

---

## 3. Consumer impact

Traced by reading each call site this session (TEST-03), not from memory.

| Consumer | Reads today | Verdict | Exact change |
|---|---|---|---|
| `build/lib/s0_ingest.py` — `build_page_leaf_bijection`, `_expected_image_names`, `s0_integrity_check` | `manifest["pages"]` + `manifest["unnumbered_leaves"]` | **NEEDS CHANGE** | Switch to a shared accessor (below). The bijection becomes near-trivial — `leaves[]` *is* the leaf→record map. `_expected_image_names` derives `page_NNNN.jpg` / `leaf_NNNN.jpg` / `plate_*.jpg` from `kind` + key |
| **`build/lib/page_order.py` — `volume_image_paths` (THE OCR ENGINE GATEWAY)**, `volume_sidecar_files`, `volume_assembly_records`, `volume_duplicate_stems` | reads `page_order.json` (only vol_01 has one); **else falls back to a broad `glob("*.jpg")`** (line 50) | **NEEDS CHANGE (highest-leverage)** | This is the interface between the manifest and the OCR engines — surfaced only after the "how does this connect to OCR?" check, missed in both earlier passes. All six S1 runners (`s1_{tesseract,kraken,kraken_greek,calamari,surya}_runner`, `local_schaff_tesseract`) call `volume_image_paths`; ABBYY/Azure normalizers call `volume_sidecar_files`. The broad `*.jpg` fallback means new `leaf_*`/`plate_*` images get OCR'd unless selection moves to `kind` (see the OCR-selection note + R-ocr-glob risk below) |
| `build/tools/generate_page_order.py` — `_build_entries` | `pages` by num + `unnumbered_leaves` front/back; **de-overlaps** by skipping front leaves `>= first_body_leaf` (line 92) | **NEEDS CHANGE (simplifies)** | Derive front/body/back/plate directly from `leaves[].kind`. The line-92 de-overlap hack is deleted — the unified model removes the overlap it compensates for. Plates become a new sequence entry type |
| `build/tools/generate_vol01_page_order.py` (vol_01's special dual-naming generator) | vol_01 legacy shape | **NEEDS CHANGE → likely RETIRE** | Under the unified model vol_01 is no longer special (front/back leaves are ordinary `leaf_NNNN.jpg`). Fold into the general generator. See open question Q2 |
| `build/tools/fetch_ia_pages.py` — `load_unnumbered_leaves`, `fetch_unnumbered_leaf`, the `unnumbered_leaves` merge (lines 157–200, 660–741, 875–890, 1148–1186) | writes the lightweight 3-field `unnumbered_record`; classifies front/back by scandata index — **this is the source of the overlap** (it marks leaves 23–31 front-matter while `pages[]` reconstructs them as body) | **NEEDS CHANGE (P2/P3 work)** | The fetcher emits `leaves[]` records. Front/back classification becomes `kind` from `derive_kind`, not raw scandata index, so a reconstructed leading leaf is never emitted as front matter. This is the migration's write path |
| `build/tools/verify_nsh_page_accounting.py` | `pages[]`, `gaps[]`; globs `page_*.jpg` + `leaf_*.jpg` | **NEEDS CHANGE** | Read body leaves via the accessor; add plate + discard accounting; keep the `page_*` / `leaf_*` globs (still valid); `plate_*` ignored as intended |
| `build/tools/nsh_precommit_ocr_gate.py` | `manifest.get("pages", [])` for `page_num`; samples `page_NNNN.jpg` | **MINIMAL CHANGE** | One-line switch to `body_pages(manifest)` accessor. Sampling logic and the `page_*.jpg` namespace are unchanged; the rename tripwire keeps working |
| `build/parsers/ia_abbyy.py` (the ABBYY parser) — `manifest.get("pages", [])` at line 459; loads `vol_NN.manifest.json` at line 842 | builds leaf↔page mapping from `pages[]` | **NEEDS CHANGE** | Surfaced by the Codex red-team — was missed in the first pass. Switch to the accessor; the leaf↔page map *is* `leaves[]`. If left unmigrated it could emit leaf-named sidecars instead of page-named ones |
| `build/tools/fetch_haucgoog_pages.py` (Part-B hole recovery) — `manifest.get("pages", [])` at line 203 | reads primary `pages[]` image size, then writes via the legacy path | **NEEDS CHANGE** | Switch reads to the accessor; the writer must emit `leaves[]` (or be gated to legacy-only until P2) so a recovery can't append a legacy `pages[]` into a v4 manifest |
| `build/tools/ocr_pipeline/extract_ccel_page_gold.py` — `manifest.get("pages", [])` at line 135 | maps scans from `pages[]`; builds `leaf_{leaf}.jpg` | **NEEDS CHANGE** | Switch to the accessor; if unmigrated it sees zero scans on a v4 manifest (silent empty gold extraction) |
| `build/tools/swap_nsh_rebuild.py` (**the P1 vol_11 swap tool**) — rewrites only `("pages", "unnumbered_leaves")` (line 50); globs `page_*.jpg` only (line 87) | repoints `local_path` for the two legacy arrays; moves `page_*.jpg` | **NEEDS CHANGE (P1-blocking)** | Surfaced by the red-team. Must repoint `leaves[].local_path` and move `plate_*.jpg` + `leaf_*.jpg`, or vol_11's plates are left behind and the new-shape `local_path` is never repointed. P1 cannot proceed until this is extended |
| `build/tools/refetch_pending_pages.py` — `manifest.get("pages", [])` (line 66); calls `generate_volume` (line 189) | reads source `pages[]`; regenerates `page_order.json` | **NEEDS CHANGE** | Surfaced by the systematic sweep. Same fetch-helper class as `fetch_haucgoog_pages.py`; switch reads to the accessor and emit `leaves[]` |
| `build/tools/run_cloud_ocr.py` (Azure cloud OCR runner — a SECOND OCR gateway) — globs `page_????.jpg` (line 1360), `page_*.azure.json` (line 1122) | enumerates body page JPEGs directly, bypassing `volume_image_paths` | **LOW / SHOULD ADOPT** | Its glob is `page_????.jpg` (page-scoped), so it is **safe** from the P3 image sweep — it can only ever pick body pages. But it bypasses the model; for consistency it should read body leaves via the accessor. Not blocking |
| `schemas/v1/source_manifest.schema.json` (`x-ocd-schema-version: 3.1.0`) | — | **NEEDS CHANGE** (NOT this session) | Add `leaf_record`, the dual-shape `oneOf`, bump to `4.0.0`; regenerate `build/lib/_generated_enums.py` + drift check in the **same** change (AGENTS.md). New enums: `kind`, `image_state` |
| HF export — `build/tools/export_hf_dataset.py` | reads `data/reference/schaff/encyclopedia/1908-1914` (assembled records), **not** the source manifest | **NO CHANGE** | Verified: no `manifest` / `unnumbered_leaves` / `schaff-herzog-pages` reference in the file. The leaf-model change does not reach the publish path |
| `tests/test_fetch_ia_pages.py` (validates real manifests for vols `[1, 2, 5, 6, 8]`, line 809), **`tests/test_s0_ingest.py`, `tests/test_nsh_precommit_ocr_gate.py`, `tests/test_swap_nsh_rebuild.py`** | real manifests + the bijection / gate / swap behavior against the old shape | **NEEDS CHANGE** | After P2 all 13 validate against `4.0.0`; extend the parametrize from `[1,2,5,6,8]` to `range(1,14)`. The three sibling tests move with their modules. Add the `kind`/positional invariant tests (§1.5, §1.7) |

**Tally (revised across three passes): 1 no-change (HF export), 1 low/safe (`run_cloud_ocr`),
1 minimal (precommit gate), 14 need real change, + 6 S1 OCR runners and 2 normalizers
transitively (via `page_order.py`), + 4 sibling test files.** The first pass undercounted; the
Codex red-team added four source-manifest readers/writers (`ia_abbyy.py`,
`fetch_haucgoog_pages.py`, `extract_ccel_page_gold.py`, `swap_nsh_rebuild.py`, the last
P1-blocking); the "connect to OCR?" check added `build/lib/page_order.py` (the OCR gateway);
the systematic sweep added `refetch_pending_pages.py` and `run_cloud_ocr.py`. All verified
against the files. No consumer "works fully unchanged" — every reader of `pages[]` /
`unnumbered_leaves[]` *or* the image dir must move to the accessor / `kind`.

**What the sweep confirmed is NOT a consumer (the reassuring half).** The pipeline has TWO
distinct "manifest" artifacts: the **source manifest** (`vol_NN.manifest.json`, the one this
design changes) and the **S1 sidecar manifest** (`sidecar-manifest-v1`, OCR output, keyed by
`page_NNNN`). The entire S2→S3→WCT→publish chain consumes the *sidecar* manifest, not the
source manifest, so it needs **no direct change**: `wct_builder.py`, `build_wct.py`,
`publish_projection.py`, and the HF export returned zero source-manifest coupling;
`render_s2.py`, `corpus_coverage.py`, `reindex_manifest.py`, `align_ccel_to_wct.py`, and
`rendering_semantic_validator.py` read the sidecar / rendering / proposal objects (their
`.get("pages")` is a *different* `pages[]`). They are protected automatically by the OCR
gateway fix — fix `volume_image_paths` to select by `kind`, and the extra front/back/plate
images never become sidecars, so they never reach S2/S3/WCT. One item to confirm in P2:
`build_gold_sample.py:84` reads a `manifest.get("pages")` whose type (source vs sidecar) was
not resolved this pass — low risk (gold/measurement tooling), flagged not closed.

**Repair / rebuild tooling operates on the old shape (a class, not ongoing consumers).**
`rebuild_nsh_pages.py` (untracked, active), `reconcile_manifest_pages.py`,
`recover_vol10_terminal_pages.py`, `retrofit_vol01_manifest.py`, `fix_phantom_files.py`,
`fix_phantom_metadata.py`, `fix_manifest_gaps.py`, `apply_nsh_true_page_map.py`,
`apply_phantom_file_renames.py`, `delete_dup_terminal_pages.py` all read/write the legacy
shape. They are one-shot migration/repair scripts, not pipeline steps; P2 supersedes them.
They do not need the accessor, but must not be re-run against a v4 manifest — gate or archive
them when the legacy branch is removed (Q5).

**The OCR engine connection (the gap the "connect to OCR?" question exposed).** The six S1
engines do not read the manifest directly — they read the image dir through
`page_order.py::volume_image_paths(vol_dir)`. Today that returns `page_order.json`'s `file`
entries (vol_01 only) or, for the other 12 volumes, **every `*.jpg` in the dir**. So the OCR
input set is currently "whatever images are on disk," which happens to be body-only because
front/back/plate images were never fetched. **P3 breaks that assumption**: it lands
`leaf_*.jpg` + `plate_*.jpg`, and any volume still on the glob fallback would feed them to all
six engines — OCRing illustration plates (waste) and front/back matter (unplanned), emitting
sidecars that flow into the WCT/reconciler. The fix is twofold:
- **Select OCR input by `kind`, not by glob.** `volume_image_paths` should return leaves
  whose `kind` is in the OCR set, derived from `leaves[]`. The model's `kind` field is exactly
  the control surface vol_01's retired generator provided via `corpus_role`.
- **Ordering: every volume must have a regenerated `page_order.json` (or the accessor must read
  `leaves[]`) BEFORE P3 lands any non-body image.** Otherwise the broad `*.jpg` fallback is
  still live when the new images appear. This makes P2 (which regenerates page_order from
  `leaves[]`) a hard prerequisite of P3 — already the dependency in the program table, now with
  a concrete reason.

This needs a decision (Q6): **which `kind`s does the OCR set include?** Body, yes. Front/back
matter is real text (title, preface, contents, index) and is a plausible future OCR target, but
the current pipeline is body-only. Plates are illustrations — exclude. Discarded — exclude.
Recommend: OCR `kind ∈ {body}` now (preserve current behavior exactly), make front/back an
explicit opt-in later, never OCR `plate`/`discarded`.

**Mitigation — land one shared accessor first (TEST-02, integrate-don't-fork):** a new
`build/lib/nsh_leaf_model.py` with `body_pages(manifest)`, `front_matter(manifest)`,
`back_matter(manifest)`, `plates(manifest)`, `discarded(manifest)`, each deriving from
`leaves[]` **with a fallback that reads the legacy two-list shape** when `leaves[]` is absent.
Consumers switch to the accessor **before** any manifest is migrated, so they work against
both shapes during the P1→P2 window and the cutover is invisible to them.

**Enforce it (TEST-08, the red-team's recommendation):** ship a CI/pre-commit check that
fails on any direct `manifest.get("pages")` / `unnumbered_leaves` / `["pages"]` access to an
NSH source manifest **outside** `build/lib/nsh_leaf_model.py` and the migration tool. A prose
"switch every consumer" instruction silently rots; the grep gate makes a missed consumer
(exactly this finding) impossible to reintroduce. Without it, the next tool added against the
old shape re-creates the bug.

---

## 4. Migration plan (from both existing forms → the new model)

No body image is re-downloaded. Scandata is the leaf spine; existing `page_*.jpg` pixels stay.

### 4.1 Inputs per volume
1. Live scandata (`probe_nsh_scandata.py <vol>`) → ordered `(leaf_num, pageNumber)` rows +
   the derived front offset. **Re-run per volume** (only 4 probed this session).
2. The existing manifest (`pages[]`, `unnumbered_leaves[]`, `gaps[]`).
3. On-disk images (`page_*.jpg`, `leaf_*.jpg`).

### 4.2 Build `leaves[]` (deterministic from scandata)
For each scandata leaf in order:
- `pageNumber` present → `kind: body`, `page_num = pageNumber`, `leaf_num = leafNum`.
- before the first numbered leaf, within the reconstructed leading run (`leaf_num >=
  first_body_leaf` where `first_body_leaf = (lowest printed page) + offset`) → `kind: body`,
  `page_num = leaf_num - offset`. **Cross-check** the reconstructed `page_num` against the
  existing `pages[]` entry and, where a `page_*.jpg` exists, the running-header OCR
  (`verify_nsh_running_headers.py` machinery). Disagreement → flag, do not auto-write.
- before the reconstructed run → `kind: front_matter`, `page_num: null`.
- after the last numbered leaf → `kind: back_matter`, `page_num: null`.
- null `pageNumber` inside the body span → `kind: plate`, `page_num: null`,
  `after_page_num` = the printed page of the preceding body leaf.
- scandata duplicate `pageNumber` → adjudicate: clean leaf keeps `page_num`; the other
  becomes `kind: discarded`, `duplicate_of_page = N` (carry forward any existing
  `gap_record.discarded_leaves` adjudication).

### 4.3 Reconcile the double-record (old-form vols 03/04/07/09/10/12/13)
The leading-run leaves currently appear in **both** `pages[]` and `front_matter`. In the new
build they appear once (`kind: body`). The `front_matter` copies are simply not emitted —
they were never independent leaves, only a bookkeeping duplicate. Verified for vol_03:
`540 records − 9 overlap = 531 unique = scandata total`. The 9 overlap leaves (23–31) collapse
to the 9 body records 1–9.

### 4.4 Rebuilt vols (01/02/05/06/08) — restore the dropped front/back matter
These dropped `unnumbered_leaves` on rebuild. The new build re-derives front/back leaves from
scandata (every leaf before `first_body_leaf` and after `last_body_leaf`), so the map returns
without a re-fetch of body pages.

### 4.5 vol_01's 52 orphan `leaf_*.jpg` (verified this session)
The 52 files are leaves `0..45` + `535..540`. Map them by **scandata `leafNum`**, not blindly:
- leaves `0..36` → `front_matter`, `image_state: present`, `leaf_NNNN.jpg` (37 images).
- leaves `37..45` → these are **printed pages 1–9** (offset 36), already imaged as
  `page_0001..page_0009.jpg`. Do **not** emit them as front matter. The `leaf_0037..leaf_0045.jpg`
  files are redundant copies of the body pages → quarantine (move to `vol_01/_superseded/`),
  do not reference. This is vol_01's instance of the double-record bug in the **image** layer
  — the unified model resolves it because leaf 37 is one `body` record.
- leaves `535..540` → `back_matter`, `image_state: present`, `leaf_NNNN.jpg` (6 images).

So of 52 orphans: 43 become referenced front/back images, 9 are superseded body duplicates.

### 4.6 vol_11 (P1, the proof case)
Author from the verified rebuild in `vol_11_rebuild/`: 503 body leaves, the 2 plates as
`kind: plate` / `after_page_num: 260` / `plate_0260_0S.jpg`, the 4 discards as
`kind: discarded` with reasons. Confirm the plate leaf numbers against scandata during P1
(this session derived them from the offset only).

### 4.7 Order of operations
1. Land `build/lib/nsh_leaf_model.py` accessor + switch **all eleven** consumers (§3,
   including the four the red-team surfaced) to it (works on both shapes via fallback) + ship
   the TEST-08 grep gate.
2. Apply schema `4.0.0` (dual-shape) + regenerate enums + drift check + tests (separate
   change).
3. **Extend `build/tools/swap_nsh_rebuild.py`** to repoint `leaves[].local_path` and move
   `plate_*.jpg` / `leaf_*.jpg` (not just `page_*.jpg`). **P1-blocking** — without this the
   vol_11 swap leaves plates behind and never repoints the new-shape paths.
4. P1: vol_11 → new shape, swap (via the extended tool), commit.
5. P2: migrate the other 12 (probe scandata per vol first; reconcile per §4.2–4.5).
6. P3: fetch one image per `pending` front/back leaf; set `blank` where pixels show blank.
7. Future: a major bump removes the legacy branch; flip the test parametrize to all 13.

---

## 5. Versioning + validation story

- **Bump `3.1.0` → `4.0.0`** (major — a structural model change, not a widening).
- **During P1→P2 (dual-shape `4.0.0`):** a manifest validates if it matches **either** the
  legacy shape (`page_count` + `pages`, no `leaves`) **or** the new shape (`leaves`). So:
  vols 1,2,5,6,8 keep validating in legacy form (no regression to `tests/test_fetch_ia_pages.py`);
  vol_11 validates in new form after P1; the old-form vols 03/04/07/09/10/12/13 stay
  invalid exactly as today (no test covers them) until P2.
- **After P2:** all 13 validate as new-shape; extend the test parametrize to `range(1,14)`.
- **Backward-compatibility, stated precisely:**
  - *Schema validation:* backward-compatible through the transition (legacy branch retained).
  - *Consumers:* **not** backward-compatible — every reader of `pages[]`/`unnumbered_leaves[]`
    must move to the accessor. The accessor's legacy fallback is what keeps them green during
    the window; once the legacy branch is removed, any un-migrated consumer breaks. So the
    accessor switch (step 4.7.1) is a hard prerequisite, not optional.
  - *`page_*` namespace:* unchanged — `page_NNNN.jpg` still means "numbered body page." Plate
    and front/back images never enter it.
- **Enum regen:** `kind` and `image_state` are new generated enums → regenerate
  `build/lib/_generated_enums.py` and run `check_schema_enums_fresh.py` in the same change as
  the schema apply (AGENTS.md). The existing generated `section` enum stays until the legacy
  branch is removed.
- **What validates before/after, mechanically:** before = vols 1,2,5,6,8 (5 of 13); after
  P2 = 13 of 13.

---

## 6. Open questions / risks

### Open questions for the maintainer
1. **Q1 — `gaps[]`: fold into `leaves[]` or keep separate?** A body hole is already a `body`
   leaf with `image_state: unresolved`, so `gaps[]` becomes partly redundant. Keeping `gaps[]`
   (image-recovery tracking consumed by `generate_page_order` / `verify`) is least-disruption;
   folding it in is cleaner but widens P2's blast radius. **Recommend: keep `gaps[]` for
   P0–P2, revisit after.**
2. **Q2 — retire `generate_vol01_page_order.py`?** vol_01 stops being special under the
   unified model. **Recommend: retire it in P2, fold vol_01 into the general generator.**
3. **Q3 — store `kind` or compute on read?** Stored is queryable and test-pinned; computed
   avoids any drift risk. **Recommend: store + pin with a re-derivation test (§1.5).**
4. **Q4 — blank policy after P3.** R2 exempts blanks from imaging, but blankness needs pixels
   (F5). **Recommend: P3 fetches every front/back leaf, sets `blank: true` where the image is
   blank, and keeps the (cheap) image anyway** — so "blank" is evidence-backed, not a guess.
5. **Q5 — when to remove the legacy branch** (the `5.0.0` that drops `pages[]`/
   `unnumbered_leaves[]`)? After P2 + the accessor switch are both proven green.
6. **Q6 — which `kind`s enter the OCR input set?** (§3 OCR connection.) Recommend `{body}`
   only now (exact current behavior), front/back matter as an explicit later opt-in, never
   `plate`/`discarded`. This decides what `volume_image_paths` returns and what P3's images do.

### Risks
- **R-mixed-source leaf coordinate (highest).** `leaf_num` must be the **primary-scan**
  coordinate; alternate-sourced pages (haucgoog holes in 02/05/06/08/10) carry a different
  leaf index in their own item. If the migration uses the alternate leaf as `leaf_num`,
  ordering corrupts. Mitigation: `leaf_num = page_num + offset` for every body leaf regardless
  of pixel source; alternate leaf lives only in provenance (§1.2). **Probe + verify per
  mixed-source volume in P2.**
- **R-variable-offset.** The front offset is constant only until the first plate. vols 10, 11
  have mid-body plates, so a single global offset is wrong there. Mitigation: the migration
  walks scandata leaf-by-leaf (§4.2); it never applies one offset across a plate.
- **R-scandata-unverified-for-9-vols.** Only 4 of 13 volumes were probed live this session.
  The model assumes the other 9 behave the same. Mitigation: P2 runs `probe_nsh_scandata.py`
  per volume and reconciles leaf count before migrating it; do not migrate a volume whose
  scandata does not reconcile.
- **R-vol_10 ordering anomaly.** The −11 leaf jump (printed 496→497) means `page_num` is not
  monotonic with `leaf_num`. The model **holds** it (each leaf positioned by `leaf_num`) but
  a soft check flags it for human resolution in P2. Not a model failure, but vol_10 needs a
  manual decision (likely a mis-sourced repair leaf).
- **R-blank-unknowable-pre-P3.** Until P3 fetches pixels, every front/back leaf is `pending`,
  not `blank`. The R2 audit can only report "imaged vs not," not "blank vs not," before P3.
- **R-consumer-window.** Between the accessor switch and legacy removal, two code paths exist
  (new array, legacy fallback). The accessor's fallback must be tested against both shapes
  (a fixture per shape) or a volume could read empty.
- **R-ocr-glob (high — newly surfaced).** `page_order.py::volume_image_paths` falls back to a
  broad `glob("*.jpg")` for any volume without a `page_order.json` (12 of 13 today). When P3
  lands `leaf_*.jpg`/`plate_*.jpg`, that fallback would silently feed front/back/plate images
  to all six OCR engines. The `page_*` naming convention does NOT protect this path (it is not
  `page_*`-scoped, unlike the verifier/gate globs). Mitigation: select OCR input by `kind` and
  make a regenerated `page_order.json` (P2) a hard precondition of P3 imaging. Until then, P3
  must not run on a glob-fallback volume.

### Red-team verdict (VER-02): does the model represent every real corpus case?
Walked all eight cases in §2 against the verified data and the vol_11 handoff. The model
represents each, including the three that broke the old form (vol_03 double-record, vol_11
plates, vol_11 discards) and the two newly surfaced this session (vol_01 image-layer
double-imaging; vol_07 numbering starting at printed 3). The one case the model **cannot
finalize from metadata** is blank-vs-non-blank (F5) — correctly deferred to P3, represented
as `pending` until pixels arrive. No real case is left without a record shape.

### Codex adversarial pass (2026-06-11, gpt-5.5 high effort)
An independent Codex review (verdict: ACCEPT WITH CHANGES) confirmed the framing — the
`leaves[]` model is the right shape for R1+R2 — and the core model held against every named
corpus case (its finding 4, OUT). It landed three must-fixes, all verified against the files
and incorporated into this revision:
1. **Mixed-shape ambiguity** — the dual-shape `oneOf` let a manifest carrying *both* `leaves[]`
   and legacy `pages[]` validate as new-shape. Fixed: the new branch now `not`-excludes
   `pages` / `unnumbered_leaves` (§1.7).
2. **Dropped provenance** — `leaf_record` (with `additionalProperties:false`) omitted the
   `provenance` block that `fetch_ia_pages.py:582-587` writes for alternate-source 2-up crops,
   so a haucgoog recovery would fail validation or lose its audit trail. Fixed: `provenance`
   added as an optional property + a cross-field migration/test invariant (§1.7).
3. **Four missed consumers** — `ia_abbyy.py`, `fetch_haucgoog_pages.py`,
   `extract_ccel_page_gold.py`, and `swap_nsh_rebuild.py` (the P1 swap tool) read/write the
   old shape and were absent from §3. Added (§3) with file:line, tally corrected to 11, and a
   TEST-08 grep gate added to stop the omission recurring.
The review could not check the 9 un-probed volumes, blankness, or vol_11 pixels (no live IA
access) — same boundary as §0. Dispatch log: `.tmp_audit/nsh-leaf-design-adversarial-output.log`.
