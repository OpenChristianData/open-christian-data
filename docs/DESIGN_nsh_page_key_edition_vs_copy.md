# NSH page key — edition vs. copy (design proposal)

**Status:** IMPLEMENTED 2026-06-20 (integration batch 06 verified). The key-value spec was locked
2026-06-19 (batch 02) after one independent Codex adversarial pass (high reasoning); the model
shipped across batches 03–05 and the 2-D completeness gate landed in batch 04. `edition_page_key`
is a **required** field on all 4 leaf-keyed schemas (commit `6db88612`); all 38,970 on-disk sidecars
were backfilled by `source_payload_sha256` (zero re-OCR); the completeness gate
(`verify_nsh_page_accounting.py --completeness`) is GREEN corpus-wide. §3 (key value + storage
decision §3a) and §3 precedence ladder are the locked spec; §5/§8 carry the completeness + migration
consequences. **Correction (2026-06-20, supersedes an earlier batch-06 note):** the §3 precedence
ladder's "rung-1 printed-signal first" is **stale for NSH and was already, deliberately superseded** —
it is NOT an open gap. The R7 alternate-scan work (2026-06-15,
`docs/R7-alternate-scan-content-alignment-2026-06-15.md` + `build/tools/ocr_pipeline/abbyy_content_alignment.py`)
binds alternate-scan images to edition leaves by **content** (monotone word-overlap alignment vs the
primary scan) precisely **because the printed signal is unreliable for NSH**: the scandata `page_num`
field numerically collides (fakes a constant offset 0) and the running-header glyph is corrupted by the
documented NSH digit confusion (2↔8, 3↔8). So for NSH, content+monotone is the *more*-trusted signal and
the printed number is weak corroboration — the §3 ladder's ordering is inverted here. PIPE-29 applies in
its correct sense ("never stamp a leaf the primary contradicts / never force-map"), NOT as "the printed
number wins." Per-binding provenance lives in each lineage's `leafmap.json` (`recovered_via`,
`unmapped_classified`, match scores), not on each page record. **Action: reconcile this §3 text to the
R7 reality (below), do not build a printed-signal-first gate.** The rest of the doc remains the
supporting proposal.
**Scope:** the page-level key for the NSH OCR pipeline, the completeness invariant that guarantees
the book is whole, and how recovered-gap pages, alternate scans, and front/back matter all attach
to it.
**Relationship to the leaf-rekey chain** — this lifts the key established by the leaf-rekey chain
(`docs/NSH_PROJECT_STATE.md`, R4b / R-final.3) up one level of abstraction. The lift is **additive**
(a new `edition_page_key` field), not a rename of `canonical_leaf_id` — see §3a. `canonical_leaf_id`
stays the integer per-copy leaf coordinate; `edition_page_key` is the scan-independent join key the
completeness gate runs over.

---

## Decision brief

- The page-level join key (`canonical_leaf_id`, today equal to the **primary scan's** leaf index)
  is a *per-copy* coordinate used as if it were a property of the *edition*. That is why a page the
  primary scan missed (but another scan has) gets OCR'd with **no key**, and why there is no
  whole-book completeness guarantee.
- Model it as **two keys**: an **edition page key** (scan-independent — the spine, the join key, the
  axis completeness is checked over) and a **copy/image key** (the image fingerprint + which scan
  supplied it — provenance, and the basis for comparing two scans of one page).
- One edition page may be backed by **many** copy-images over time (primary scan, alternate scan, a
  future re-scan). They share the edition page key and differ in the copy/image key.
- Add a **loud completeness invariant**: every edition page is either covered by an OCR'd image or
  an explicitly-reasoned hole. A "located but not fetched" state must **fail the build**, not pass
  silently. (Today it passes silently — see the vol_01 94/95 incident in section 6.)
- **Recommendation (locked 2026-06-19):** adopt the two-key model; **add a new `edition_page_key`
  field** as the edition-scoped join key (NOT a rename of `canonical_leaf_id`); keep
  `canonical_leaf_id` as the integer per-copy leaf coordinate, demoted in meaning to provenance and
  retained as the substrate for monotonic-position binding; ship the completeness gate in the same
  change. The "rename in place" both prior drafts implied is rejected — see §3a for why (it is
  type-unsafe: the field is integer-typed in four schemas and the ABBYY aligner does integer
  arithmetic on it). Treat the 23 class-1 keyless pages as the first test population.

---

## 1. Symptoms (how you recognize you have this problem)

1. During an S1 OCR run you see, for certain pages:
   ```
   <engine> vol_NN: leaf unresolved for sha sha256:<...> (sha <...> resolved to 0 leaves);
   emitting without canonical_leaf_id
   ```
   This is **handled, not a crash** — the runner OCRs the page and saves the sidecar, just with no
   `canonical_leaf_id`. **Disk-verified 2026-06-18: 23 such pages** (sidecar exists, `clid = None`):
   vol_01 (96,97) · vol_02 (253–255) · vol_05 (451–454) · vol_06 (361–363, 451–458) · vol_10 (356,359,366).
   (An earlier "about two dozen" estimate was computed from `gaps[]` metadata and was wrong; see §6 and
   `plans/2026-06-18-nsh-page-key-implementation-plan.md` §A for the disk re-grounding.)
2. Those pages are **excluded from the leaf-keyed reconciliation chain** (WCT, cross-engine /
   cross-source alignment) because that chain joins on `canonical_leaf_id`, which they lack.
3. A page can be marked `"status": "resolved"` in a manifest's `gaps[]` yet have **no image on disk
   and no OCR**, and nothing fails. (vol_01 pages 94-95 — see section 6.)

## 2. Root cause

`build/lib/nsh_leaf_model.py` defines `leaf_num` as *the primary scan's physical leaf coordinate*
(see its module docstring), and the leaf-rekey chain made `canonical_leaf_id` (= `leaf_num`) the
first-class cross-engine / cross-stage join key. `resolve_leaf(manifest, sha)` only indexes body
leaves (`leaf_by_sha`) and raises "resolved to 0 leaves" for anything else.

So the join key is a property of **one physical copy** (the primary scan):

- A page the primary scan skipped has no primary leaf, so no key — even though the *edition* page
  plainly exists and another copy captured it.
- The per-copy leaf index is not stable across copies: edition page 96 sits at primary leaf `0130`
  (and was even mislabeled in primary scandata) but at haucgoog leaf `0128`. So the index cannot be
  the cross-copy key.
- There is no edition-level sequence to check completeness against, so missing pages do not surface.

`gap_by_sha()` exists in `nsh_leaf_model.py` precisely so a consumer can recognize a gap-page image,
but it is only consumed by tooling (`migrate_s1_to_leaf_key.py`, `verify_leaf_keying.py`), **not** by
the reconciliation chain.

### The defect is the key's *scope*, not its absence

It is easy to misread the problem as "we have no positional key." We do. `leaf_num` already orders
**every** leaf — body, front, back, and plates — in one physical sequence; an unnumbered page carries
a `leaf_num` with a null `page_num` (disk-verified vol_02: a mid-body illustration is a real leaf
`{"leaf_num": 275, "page_num": null, "kind": "plate"}`). The structured positional key exists. The
actual defect is that `leaf_num` is the **primary scan's** leaf index — a per-copy coordinate that
works for everything the primary copy photographed and silently fails for everything it did not (a
page the primary skipped has no `leaf_num`; the same edition page sits at a different `leaf_num` in a
different copy). So the fix is **not** "add a positional key." It is lift the existing positional key
from primary-copy scope to edition scope, and demote `leaf_num` to per-copy provenance — changing the
key's *definition*, not adding a mechanism.

## 3. The model: edition vs. copy

The corpus reproduces a fixed **edition** (e.g. the 1908 New Schaff-Herzog vol 1 — fixed text,
layout, and pagination). Each scan is a physical **copy** of that edition. A page's place in the book
is a property of the edition; the pixels are a property of the copy.

### Edition page key (the spine — scan-independent)

- One per page of the edition, in reading order, assigned once for the whole edition.
- It is **not** the raw printed page number: printed numbers restart (front matter i, ii, iii; body
  restarts at 1), duplicate, and are absent on plates. The edition page key is a defined, gap-aware
  ordered sequence over the whole edition, **cross-checked** against printed page numbers and
  running-header OCR where they exist.
- Every page gets one regardless of which copy supplied the image — including recovered-gap pages and
  front/back matter. A recovered page receives its **true** edition position (page 96 is
  edition-page-96), not a fabricated number.
- This is the join key for reconciliation and the axis the completeness invariant runs over.

### Copy / image key (provenance — per scan)

- The image fingerprint `source_payload_sha256` (SHA-256 of the image bytes) identifies the exact
  image OCR'd.
- Plus: which scan/item it came from (`ia_item_id`, `resolved_from`, `provenance.*`) and **that
  scan's own internal leaf index** (e.g. `ia_leaf_id`) as a locator only.
- One edition page maps to potentially many copy-images over time. They share the edition page key
  and differ in the copy/image key. This is what makes "OCR a different scan of the same page later
  and compare them" well-defined.

### Edition page key value — `(section, anchor, ordinal)`  [LOCKED 2026-06-19]

The edition key is a sortable triple `(section, anchor, ordinal)`, edition-scoped and
insertion-tolerant — **not** a dense `1..N` sequence. A dense ordinal is fragile to discovery: assign
it from a scan that skipped pp. 94–95 and there is no slot for them; inserting them later renumbers
every downstream record and breaks the immutable join key. For the **body**, the printed number is a
near-perfect edition key — it is edition-intrinsic (page 96 is page 96 in every copy) and
insertion-proof; the objection that numbers restart/duplicate/vanish is true only for the
**unnumbered** matter, not the body.

**section** — the page's structural region, reusing the existing **schema-backed `kind` vocabulary**
(do not invent a parallel enum — PIPE-21). Sort namespace = the three sequential regions in reading
order: `front_matter` < `body` < `back_matter`. A **plate** (illustration) is *not* a fourth sort
namespace — it interleaves *within* a region (almost always body), so it is keyed in that region by
the preceding numbered page (anchor) with an `ordinal ≥ 1`, and its plate-ness is recorded separately
as an attribute (`kind = plate`, OCR-exempt — see §5). `discarded` leaves are not edition pages and
receive **no** edition key. The section component therefore takes a value in
`{front_matter, body, back_matter}`; `kind` (which adds `plate`) stays an independent attribute.

**anchor** (an integer) — for a `body` page, the printed page number. For an unnumbered page, the
printed number of the page *immediately before it* in reading order. For `front_matter` / `back_matter`,
the section's own printed number when one is verifiably present (e.g. front-matter roman numerals,
converted to int), else the leaf's 1-based position within its region. The section namespace keeps
front-matter roman "ii" (anchor 2, front_matter) from ever colliding or interleaving with body "2"
(anchor 2, body).

**ordinal** (an integer ≥ 0) — **the page's position within its `(section, anchor)` group, counted in
reading order.** The first (or only) page carrying that anchor is `0`; each subsequent page sharing the
same `(section, anchor)` takes the next integer. This single rule makes the **whole triple unique by
construction** — it is *not* "0 for every numbered page" (that earlier wording was the bug the
adversarial pass caught: two leaves printing the same number would both be `…,0` and collide). A
numbered page is `ordinal 0` *because* it is normally the only page with that anchor, not by fiat.

Uniqueness / collision rules (the cases the adversarial pass constructed — A1/A2):
- **Unnumbered insertions** (plate, illustration) after page N: `(region, N, 1)`, `(region, N, 2)`, …
- **Duplicate printed number** (publisher misprint: two distinct leaves both print "96"): the second,
  later in reading order, becomes `(body, 96, 1)`, its binding note recording `duplicate_printed_number`.
  Uniqueness holds; ordering stays deterministic by reading order.
- **Numbering reset within a region** (a body that restarts numbering mid-volume — *not* observed in
  NSH, unverified): handled only by splitting the region into ordered sub-regions; flagged as a
  **batch-03 data check** (confirm NSH has no in-body duplicate or reset before assigning — Codex could
  not verify this, nor has this spec). If a reset is found, escalate before assigning keys.
- **Reading order itself ambiguous** (two unnumbered plates between the same two pages with no inherent
  order): the tie-break is the supplying copy's physical sheet order (provenance), recorded at binding
  time so the assignment is reproducible, never hash-order-dependent.

| Page | Edition key | `kind` | Note |
|---|---|---|---|
| Body page 274 (numbered) | `(body, 274, 0)` | body | the printed number; only page with anchor 274 |
| Unnumbered image between 274 and 275 | `(body, 274, 1)` | plate | anchored to the page before; OCR-exempt |
| Body page 275 (numbered) | `(body, 275, 0)` | body | |
| Class-1 recovered-gap page 96 | `(body, 96, 0)` | body | its true slot, whichever scan supplied it |
| Color plate, no header, between 94 and 96 | `(body, 94, 1)` | plate | confirmed by position (precedence rung 2) |
| Front-matter title leaf (roman ii) | `(front_matter, 2, 0)` | front_matter | section namespace separates it from body 2 |
| Second leaf misprinting "96" | `(body, 96, 1)` | body | duplicate_printed_number; reading-order tiebreak |

Properties: **edition-scoped** (anchor is a fact of the book, not of one scan); **insertion-tolerant**
(a later image after 274 becomes `(body, 274, 2)`; the numbered spine never shifts, so no downstream
record re-keys); **unique by construction** (the ordinal-as-position rule); duplicates/mislabels are
disambiguated by binding the anchor to a *verified* signal (running-header OCR), not to scandata.

**Sort comparator (explicit, so it is not left to language defaults):** order by
`(section_rank[section], anchor, ordinal)` where `section_rank = {front_matter:0, body:1, back_matter:2}`.
Never sort the triple lexically (lexical order puts `back` before `body` before `front` — wrong).

**Honest trade-off (SCALE-01):** NSH itself is a fixed edition with no future page additions, so a
plain dense edition sequence would also work for NSH alone. The sub-ordinal earns its slightly-more-
complex key **purely** for future corpora that must take insertions without renumbering — that
future-reuse requirement is the explicit reason to pay for it now. For a future fixed corpus the
scheme degrades gracefully to `ordinal = 0` everywhere.

### Precedence ladder for binding a copy-image to an edition key  [LOCKED 2026-06-19]

Content alignment is fuzzy and has already mis-fired (vol_11 plate offset, the R7 work). Binding a
physical copy-image to an edition key follows a trust hierarchy, most-trusted first:

1. **Verified printed signal** — read the printed page number / running header off the image itself.
2. **Monotonic position** — it falls in order between two already-confirmed neighbors.
3. **Manual review** — a human decides.

**Hard rule (PIPE-29): a content-to-content image match must never override a clearly-printed page
number** — the printed number *is* the edition fact.

**Enforcement status (A3 — must be honored by batch 03/04, not assumed today):** the current ABBYY
binder (`abbyy_content_alignment.align_by_content`) selects by word/text similarity within a monotone
band and has a PIPE-29 guard, but that guard is *content-overlap with the primary scan*
(`primary_floor` / `primary_match_floor`, `abbyy_content_alignment.py` docstring ~L274) — **not** a
read of the printed page number. So today the ladder operates at rung 2 (monotonic + content), with no
rung-1 printed-signal gate in the binding path. The locked requirement: **when a printed page number /
running header is legibly present on the image, rung 1 takes precedence and a conflicting content match
must be rejected (or routed to rung 3), not silently accepted.** Wiring the rung-1 gate is batch-03/04
work; the spec mandates it.

> **SUPERSEDED FOR NSH (2026-06-20).** The "rung-1 printed-signal first" requirement above does NOT
> hold for NSH and was correctly not built. R7 (2026-06-15,
> `docs/R7-alternate-scan-content-alignment-2026-06-15.md`) established that NSH's printed signal is the
> *unreliable* input: the scandata `page_num` field collides numerically (fakes offset 0) and the
> running-header glyph suffers documented digit confusion (2↔8, 3↔8), so a "legibly present" printed
> number can itself be wrong. `abbyy_content_alignment.py` therefore binds by **content** (monotone
> word-overlap vs the primary scan) as the primary signal, with the printed/field signal as weak
> corroboration only — the inverse of rung-1-first. PIPE-29 is honored in its correct sense (never stamp
> a leaf the primary contradicts; leave unmatched leaves unmapped, never force-map), which is exactly
> what the binder does. There is no rung-1 gate to build for NSH; the ladder's ordering above is the
> clean-world abstraction that NSH's OCR reality inverts. (A future corpus with reliable printed numbers
> could still use rung-1-first — this supersession is NSH-specific.)

**Per-binding provenance (must-fix #4):** each copy→edition binding records its `method`
(`printed_signal` | `monotonic` | `manual`) and a `confidence`, stored **on the page/key binding record
itself** (not only in aggregate leaf-map metadata), so a low-trust binding stays auditable and
re-verifiable. This is exactly what vol_01's `gaps[]` notes already did by hand ("running-header OCR
confirmed header=96"; p95, a color plate with no header, confirmed by position between 94 and 96) — the
spec makes that the written, stored rule for every copy→edition binding.

### 3a. Storage decision — new field, not a rename  [LOCKED 2026-06-19, Option 1]

Where does the edition key live, given the existing join field `canonical_leaf_id` is integer-typed?
Three options were weighed; **Option 1 is locked** after an independent Codex adversarial pass (high
reasoning) that, blind to this doc, reached the same verdict.

| Option | What it does | Verdict |
|---|---|---|
| **1. New field (LOCKED)** | Add `edition_page_key` (the `(section, anchor, ordinal)` triple) as the edition join key, on **every** page incl. the 23 keyless + front/back/plate. Keep `canonical_leaf_id` as the integer per-copy leaf coordinate, demoted in *meaning* to provenance + retained as the substrate for monotonic-position binding. Backfill the new field by `source_payload_sha256` (zero re-OCR). | **Chosen.** Additive, type-safe, reversible. |
| 2. Rename in place, keep integer (dense edition seq) | Redefine `canonical_leaf_id` as a dense 1..N edition sequence. | Rejected — abandons the insertion-tolerance the triple is paid for (SCALE-01). |
| 3. Rename in place, change type to the triple | Redefine `canonical_leaf_id` to hold the triple. | Rejected — **type-unsafe.** |

**Why not rename in place (the type-safety evidence, verified against code):**
`canonical_leaf_id` is typed `{"type":"integer","minimum":0}` in **four** schemas — `sidecar-page-v1`
(L32), `sidecar-manifest-v1` (L112), `rendering-v1` (L538), `word-confusion-table-v1` (L36) — each via
`oneOf [canonical_leaf_id | clid_exempt]`. It is read ~239× across **23** `.py` files (the plan said 22;
the +1 is batch 01's new `reconcile_page_classes.py`). Crucially, `abbyy_content_alignment.py`'s
`monotonic_violations` (L145–158) does **integer arithmetic** on the same leaf quantity
(`p.canonical_leaf_id < prev - DEFAULT_BACK_SLACK`; `max(prev, p.canonical_leaf_id)`) — a per-copy
ordering check used during binding. A tuple cannot be subtracted/`max`'d, so Option 3 silently breaks
this; Option 1 leaves the integer (and this arithmetic) untouched. The Codex pass independently
verified the arithmetic is on the same quantity `canonical_leaf_id()` resolves (A5: OUT).

**The cost, stated honestly (A4 — the load-bearing consequence for batch 03):** Option 1 is type-safe
but **not automatically semantically safe**. Several sites today read `canonical_leaf_id` *as the join
key*; for primary body pages that keeps working (they keep their int), but the 23 keyless /
alternate-scan pages have no `canonical_leaf_id` and will **under-join** unless the join migrates to
`edition_page_key`. Batch 03 MUST migrate these join-key reads to `edition_page_key` (verified call
sites, Codex A4 + the batch-01 grep):
- `build/tools/ocr_pipeline/build_wct.py:48` (WCT page-group join key) and `build/lib/wct_builder.py`
- `build/tools/ocr_pipeline/align_ccel_to_wct.py:162`/`:167` (CCEL→WCT join)
- `build/tools/ocr_pipeline/render_s2.py:693` (S2 per-page currentness key; keyless pages already fall
  back to the filename stem there — confirmed)
- `build/tools/ocr_pipeline/run_ocr_pipeline.py` currentness, and `verify_leaf_keying.py:221` gates
The S1 runners, `stamp_*`, `reindex_manifest`, `migrate_s1_to_leaf_key` mostly *stamp* the field
(declaration sites) — they emit `edition_page_key` additionally; their `canonical_leaf_id` writes stay.
The `oneOf` requirement: `edition_page_key` is required for **all** edition pages (no exempt branch —
every physical page has an edition position); `canonical_leaf_id`'s existing `oneOf`/`clid_exempt` stays
as-is (primary-scan pages have the int; gap/alternate pages remain `clid_exempt`).

**Independent adversarial pass — verdict record (the one Codex pass of the effort, DEL-02):**
- **Verdict: OPTION 1**, reached independently (Codex was barred from this doc + the plan/research/state
  docs so it could not echo them).
- A1 IN, A2 IN — duplicate/reset printed-number collision in the *old* ordinal wording → fixed in §3
  (ordinal-as-position-in-group; uniqueness by construction; duplicate/reset rules added).
- A3 IN (narrowed) — printed-signal rung not enforced in the binder today → mandated in §3 precedence
  ladder as batch-03/04 work (the existing guard is content-overlap-with-primary, not printed-number).
- A4 PARTIAL — accepted; the join-migration list above is the result.
- A5 OUT — my type-safety evidence verified correct (no integer confusion).
- A6 PARTIAL — Option 1 + an optional canonical sortable-string form (`body:000274:000`) as a
  convenience index; stored value stays structured. Recorded as nice-to-have, not required.
- No key-collision with no clean fix was found, so no DEL-02 escalation was triggered.

## 4. Mapping to existing fields

| Concept | Today | Proposed |
|---|---|---|
| Concept | Today | Locked (Option 1 — see §3a) |
|---|---|---|
| Edition page key (join key) | *(none — `canonical_leaf_id` is misused as one)* | **new field `edition_page_key`** = the `(section, anchor, ordinal)` triple, on every page incl. recovered/front/back/plate; scan-independent |
| Printed page number | `page_num` | unchanged — an *attribute* + the `anchor` source; a cross-check input, not the key |
| Image key | `source_payload_sha256` | unchanged — the copy/image key + the backfill/re-stamp key |
| Which copy supplied it | `ia_item_id` / `resolved_from` / `provenance` (rich on repaired vols, sparse on others) | normalize so every copy-image carries it |
| Per-scan leaf index (per-copy coordinate) | `canonical_leaf_id` = primary `leaf_num`; also `ia_leaf_id` | **kept as-is** — `canonical_leaf_id` stays the integer per-copy leaf coordinate (provenance + monotonic-binding substrate); it is NOT the cross-copy key |

The four schemas (`sidecar-page-v1`, `sidecar-manifest-v1`, `rendering-v1`, `word-confusion-table-v1`)
**gain `edition_page_key`** (required for every edition page — no exempt branch, every physical page has
an edition position). Their existing `oneOf [canonical_leaf_id | clid_exempt]` stays unchanged:
primary-scan pages keep the int, gap/alternate pages stay `clid_exempt`. So `canonical_leaf_id`'s
*presence and definition both stay*; the new field carries the lifted edition meaning (this is why
Option 1 is additive and reversible — §3a).

## 5. The completeness invariant (must fail loudly)

This is the part specifically called out: a missing page must never pass silently.

Define a gate that, per volume, asserts over the **edition page key**:

1. The edition page sequence is contiguous and in order (no unexplained jumps).
2. Every edition body page is in exactly one terminal state:
   - **covered** — at least one copy-image exists on disk AND has a successful OCR sidecar; or
   - **known-hole** — explicitly recorded as absent with a reason (page genuinely missing from all
     available copies), a deliberate reviewed exception, not a default.
3. A page that is **located but not fetched** (a `gaps[]` record marked `resolved` / `resolved_from`
   set, but with no `local_path` / `sha256` on disk) is a **hard failure** — this is the exact state
   that hid vol_01 94/95. "We know where it is" is not "we have it."
4. A copy-image present on disk with no OCR sidecar is a failure (image fetched but not OCR'd).

Wire it as: a runnable verifier under `build/tools/ocr_pipeline/` (extend
`verify_nsh_page_accounting.py` / `verify_leaf_keying.py` rather than adding a third overlapping
one), invoked by the pipeline and by a pre-commit gate, with adversarial self-tests (TEST-09): one
true-positive (a located-but-unfetched page) and one true-negative (a clean volume) per rule.
Counting names is not enough — the verifier must reconcile *edition pages -> images on disk -> OCR
sidecars*, and read content (printed page / running header) to confirm position, per PIPE-29.

### Make the invariant two-dimensional

Keep the coverage axis above and add a second:

- **(a) Coverage** — is every edition page present in at least one copy with a successful OCR sidecar?
- **(b) Reconciliation depth** — for each edition page, **how many independent copies did we actually
  OCR?** The gate **records** the depth per edition page (and the corpus distribution) as a neutral
  statistic — a measurement only, with no confidence/quality judgement attached and no effect on
  pass/fail. (The two-key model is what makes this measurable: distinct scans of one page share the
  edition page key and differ in the copy/image key.)

### Plates and corrections are named terminal states

- **Plates are a named terminal state, not a vague case:** "edition page, OCR-exempt." They are real
  physical pages (they count toward the book being whole) but carry no OCR text — distinct from
  "OCR'd body" and from "discarded copy-artifact."
- **Key corrections are append-only events:** when a binding turns out wrong (the §6 mislabel class),
  log old→new and re-stamp by `source_payload_sha256` (zero re-OCR, the leaf-rekey pattern). A key,
  once bound to an image sha, is re-bound only through a logged correction — never silently.

## 6. Test cases — four disk-verified classes (CORRECTED 2026-06-18 after disk re-grounding)

An earlier draft of this section claimed vol_01 pages 94–95 had been located but not fetched, and
prescribed re-fetching them. **That was wrong** — it read the `gaps[]` record (secondary) instead of
disk (the exact PIPE-29 trap §5 warns against). Disk truth: pages 94 and 95 have images (5.6 / 5.1 MB),
tesseract + kraken sidecars, and a stamped `canonical_leaf_id` 130 / 131 — they are fully keyed body
leaves. **Do not re-fetch them; that would clobber existing OCR'd images.**

The Phase 0 reconciler (`build/tools/ocr_pipeline/reconcile_page_classes.py`) classifies every
recovered-gap page into one of **four** classes from disk (image present, sidecar present, sidecar
`canonical_leaf_id`), never from the `gaps[]` status field. Corpus-wide counts, disk-verified
2026-06-18 (the reconciler is the source of truth — re-run it, do not trust this list if it drifts):

- **Class 1 — keyless OCR'd recovered page** (the edition-key target): image + sidecar exist, the
  sidecar's `canonical_leaf_id` is `None`. **23 corpus-wide:** vol_01 (96,97) · vol_02 (253–255) ·
  vol_05 (451–454) · vol_06 (361–363, 451–458) · vol_10 (356,359,366). True-positive for the keying
  gap. (An earlier "about two dozen" was a `gaps[]`-derived estimate; disk-true is 23.)
- **Class 2 — stale `gaps[]` record (manifest↔disk desync)**: the page is a keyed body leaf on disk
  (its sidecar carries an int `canonical_leaf_id`) yet a leftover `gaps[]` entry still lists it.
  **31 corpus-wide:** vol_01 (94,95) · vol_06 (462–468) · vol_10 (343–355,357,358,360–365,367).
  Example vol_01 **94/95**. True-positive for the bookkeeping/reconciliation check. **Fix is to
  reconcile the record, never to fetch** — the image is already on disk and OCR'd. (The plan's §A only
  named 94/95; the reconciler found 31 — recorded here so a cold reader does not re-discover them.)
- **Class 3 — image present, not OCR'd (coverage gap)**: image on disk, no sidecar. **3 corpus-wide:**
  vol_08 (96,97) · vol_10 (369). vol_10 369 is 2.7 MB vs ~5 MB neighbors — inspect for blank/plate
  before OCR. True-positive for the coverage check; fix is OCR (or record-blank), not the key model.
- **Class 4 — true hole (no image anywhere)**: a `gaps[]` page number with no image and no sidecar.
  **199 corpus-wide** — of which **196 are out-of-range phantoms** (page numbers requested past the
  last printed body page; vol_03 501–531, vol_04 501–523, vol_07 503–533, vol_09 500–534, vol_12
  600–645, vol_13 212–241), and **3 are real `permanently_missing` pages** (vol_13 209–211 — printed
  pages whose image is absent from every IA scan but whose ABBYY text exists; `pages_parsed=211`
  confirms the book's true length). **Zero interior true holes confirmed.** The 196 phantoms were
  generated by `record_unresolved_gaps` being fed a requested range that ran to the *leaf* count
  instead of the *page* count; ABBYY `coverage.ia-abbyy.json` `pages_parsed` is the independent true
  page count (PIPE-29). They have been **reclassified in the manifests from status `unresolved` to
  `out_of_range`** (preserving the record, not deleting it — `reclassify_out_of_range_gaps.py`), and
  `record_unresolved_gaps` is now guarded to never re-record a page beyond `pages_parsed`. Batch 04's
  gate should distinguish phantom (`out_of_range`) from real-missing (`permanently_missing`) by the
  authoritative manifest status, not by the reconciler's `last_body_page` heuristic (which undercounts
  vol_13 and would mislabel its 3 real missing pages as out-of-range).

The completeness gate (§5) catches classes 1–3 as defects and ignores the out-of-range class-4 tail.
Use one page from each of classes 1, 2, 3 as its self-tests (TEST-09).

## 7. How this unifies three problems

- **Recovered-gap pages** (section 1): get their true edition page key from the copy that has them;
  join reconciliation normally; provenance records the source copy.
- **Alternate ABBYY scans** (the R7 work): already "map another copy's images onto the edition's
  pages by content" — this model names what that machinery produces (an edition page key from a
  non-primary copy). Content alignment becomes the general way any copy-image acquires the edition
  page key when filename/index cannot be trusted.
- **Front/back matter** (Lane B — **LANDED 2026-06-20**, `discard_frontback_leaves.py` (2a) +
  the OCR-gateway promotion (2b, commits `51d6ddf5`/`6ccdc1f7`/`7f7b255a`)): same question — these
  leaves have no body leaf number, so they get the edition page key in the front/back portion of the
  sequence and stop being orphans that trip the S2 count guard. `edition_page_key.section`
  (front_matter / back_matter) is the body/non-body partition key — no `leaf_kind` field. The ~203 kept
  leaves now enter the OCR-input gateway (`volume_image_paths(include_front_back=True)`, no re-OCR — the
  next scheduled run OCRs them); the completeness gate's front/back half is exercised. This reverses the
  prior "front/back stay out of the WCT" invariant — **ADR-0017**.
  **Remaining gated follow-up — Phase 2c (real-word-ratio noise sweep):** after the next OCR pass
  produces front/back text, score each kept leaf's real-word ratio and discard confirmed noise (2a-style).
  It cannot run until the keepers are actually OCR'd. Spec:
  `plans/2026-06-18-nsh-frontback-discard-promote-plan.md` (Phase 2c).

## 8. Migration & open questions for the implementer

1. **Rename vs. new field — RESOLVED 2026-06-19 (§3a): new field `edition_page_key`, `canonical_leaf_id`
   kept as the integer per-copy coordinate.** Not "rename in place": that is type-unsafe (integer in 4
   schemas; integer arithmetic at `abbyy_content_alignment.py:145-158`). Verified: ~239 reads across 23
   `.py` files. Batch 03 migrates the join-key reads listed in §3a to `edition_page_key`; it does NOT
   change `canonical_leaf_id`'s type or retire it.
2. **Edition sequence definition:** the algorithm that assigns `(section, anchor, ordinal)` per §3 and
   cross-checks the anchor against printed numbers + running headers (precedence rung 1, where present).
   Front/back/plate handling per §3. **Batch-03 data check (Codex A1/A2 could not verify):** confirm NSH
   has no in-body duplicate or reset printed page number before assigning; if one exists, escalate.
3. **Backfill:** stamp `edition_page_key` onto existing sidecars/renderings/WCT. Must be zero-re-OCR
   (reuse on `source_payload_sha256`); see the leaf-rekey chain for the pattern, and
   `build/tools/ocr_pipeline/stamp_s1_cache_version.py` for the in-place re-stamp shape. (Re-rendering S2
   is jsonschema re-validation, not NLP — cheap; re-running S1 OCR is the expensive thing to avoid.)
4. **Lock-in — DONE:** the DEL-02 hardening pass ran (one independent Codex adversarial review, high
   reasoning, 2026-06-19); verdict + adjudication recorded in §3a. Implementation proceeds in batch 03.

## 9. References

- `build/lib/nsh_leaf_model.py` — `leaf_num` definition, `ocr_input`, `resolve_leaf`, `leaf_by_sha`,
  `gap_by_sha` (the hook unused downstream), `canonical_leaf_id`.
- `docs/NSH_PROJECT_STATE.md` — anchor; leaf-rekey chain (R4b join key, R-final.3 required-clid).
- `docs/DESIGN_nsh_leaf_sequence_manifest.md` — the leaf-sequence manifest model this builds on; the
  recovered-gap model (schema 4.1.0, `gaps[]`).
- `build/tools/ocr_pipeline/render_s2.py` (`count_sidecars` S2 guard),
  `verify_nsh_page_accounting.py`, `verify_leaf_keying.py` — where the completeness gate lands.
- `build/tools/ocr_pipeline/README.md` — store layout and the reuse model.
- Evidence: `raw/internet-archive/schaff-herzog-pages/vol_01.manifest.json` `gaps[]` (pages 94-97).
