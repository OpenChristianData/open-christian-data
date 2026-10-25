# Source-to-TEI review patterns

Current single source of truth for the **catalog of learned failure patterns**.
The [skill](../.agents/skills/source-to-tei/SKILL.md) owns the workflow; linked
source policies, tests and review procedures own the actual checks. Per-work
receipts remain the evidence of outcomes. This index is neither an acceptance
ledger nor a claim that a historical repair exists in the current checkout.

The completed review and adoption record (historical maintainer record)
records the corrections and retained migration boundary.

## Use on each work

Inspect the source and route, then select the matching feature or symptom rows.
Follow the linked owning procedure and the row's source-specific check. Record
selected RP IDs, the actual check/evidence identity, outcome and remaining scope
in the existing work review. Nonapplicable rows need not be expanded into a
checklist; they are not passed tests. Unlisted features still require source-led
inspection under the skill.

The skill's cross-cutting requirements apply whether or not a historical pattern
is selected: exact authority and scope, recorded independent checking, and honest
visual coverage. A pattern supplies a useful example and boundary, not an
exception to those requirements.

## Read the evidence correctly

The retained development record (historical maintainer record)
preserves the incident accounts. The
incident concordance (historical maintainer record)
maps every historical incident to these IDs. Those accounts are historical
reports, not freshly verified original receipts. Their original repair and test
claims must be rebound to the work/checkout being reviewed before reuse.

Procedures linked below are live guidance. Test pointers are examples whose
code was inspected, not tests run by this migration and not complete regression
coverage. When no exact reusable regression has been located, perform the linked
bounded review procedure or record the missing proof; do not invent a pass.

## Select a pattern

| ID and trigger | Owning check and source-specific addition | Historical example | Boundary |
| --- | --- | --- | --- |
| RP-01: selected body within a larger document | [Reconstruct](../.agents/skills/source-to-tei/SKILL.md#reconstruct), carrier accounting; reconcile the selection's adjacent shell/head and parent attachment. | Ticket 24's preface/imprint; ThML head-only title. | Explicitly disposed material outside the assigned work is not automatically an omission. |
| RP-02: repeated keys, labels, headwords or milestones | [Record inventory](../.agents/skills/source-to-tei/references/inventory-strategies.md#json-and-record-oriented-text); compare parent/ordinal occurrences rather than set equality. | Duplicate headwords and repeated Baxter facsimile values. | Repetition is not itself corruption; use source order rather than an invented alphabetical comparator. |
| RP-03: multiple works, parts, members or review scopes | [Multiple witnesses](../.agents/skills/source-to-tei/references/inventory-strategies.md#multiple-witnesses-and-editions) and [visual coverage](../.agents/skills/source-to-tei/SKILL.md#visual-verification); check per-work boundaries, edition order and metadata independently. | Equiano metadata; child-work route on sibling tail; candidate versus larger catalog scope. | A faithful partial candidate can be correct; one candidate's traversal does not complete a larger corpus unit. |
| RP-04: text conservation or blobs/ledgers support a readable reconstruction | [Reconstruct mapping and independent check](../.agents/skills/source-to-tei/SKILL.md#reconstruct); inspect meaningful attributes/topology beyond text or blob equality. | John Owen's byte/ledger proof coexisted with missing readable semantics; see the [grouping and inline-order examples](#rp-0406-readable-relationships-and-independent-expectations). | Evidence carriers corroborate; unchanged whole-member TEI can use byte conservation for that member. |
| RP-05: binary, compressed, archive or index-driven source | [Archive](../.agents/skills/source-to-tei/references/inventory-strategies.md#archives-and-multiple-files) and [binary inventory](../.agents/skills/source-to-tei/references/inventory-strategies.md#databases-and-binary-modules); bind derivation to original member/range identities and inspect unexplained gaps. | SWORD sentinels/delimiters, discarded NULs, four textual members. | Nontextual ranges can have explicit dispositions; low-level compression proof follows the affected format/claim. |
| RP-06: establishing or reusing checker independence | [Independent check](../.agents/skills/source-to-tei/SKILL.md#reconstruct); compare source-derived expectations with actual TEI, including during repairs. | Separate producer/oracle files shared an incomplete projection; see [Strong's checker repair](#rp-0406-readable-relationships-and-independent-expectations). | The overlap assessment is always required for checker proof; library diversity alone does not establish independence. |
| RP-07: large nodes, dictionary variants or paging | [CVW evidence](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-evidence-profile); compare reachability/truncation for the actual node class, plus source-defined markers and visible risk anchors. See the JSON paging example below. | Truncated topic pages despite reaching all indices; entryFree not covered by entry behavior. | JSON paging tests do not cover every renderer; varying page maxima can be valid. |
| RP-08: source schemas differ or text occurs in several fields | [Record inventory](../.agents/skills/source-to-tei/references/inventory-strategies.md#json-and-record-oriented-text); bind the actual parent/field and its ordinal. | Creeds/TheologAI routes; Q107 apparent match came from its answer. | A matching phrase elsewhere cannot establish the requested field. |
| RP-09: screenshots or terminal anchors support a finding | [Capture profile](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-evidence-profile); use validated image metadata and inspect the exact native locus, including large-node scrolling and stale-pixel risks. | Clipped/off-screen anchors, JPEG mislabeled PNG, stale Chromium pixels; see the located boundary example below. | Index-only or repeated terminals are valid when located and visible. Ticket 15's accepted bounded implementation retains the labeled-frame fallback where equivalent binding is unavailable. |
| RP-10: launch/restart, worktree switch or browser failure | [Admission/continuation](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-admission-and-continuation); verify the actual serving identity and context tested. | Wrong-worktree imports, old listener, worker-only browser failure, unreadable host temp. | Current disk hashes cannot prove old loaded code; a worker error cannot establish host-wide absence. |
| RP-11: manifest byte mismatch or moved storage | [Manifest diagnosis](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#manifest-and-storage-diagnosis); compare materialization and resolved paths before a scoped repair. | Lexical/physical root mismatch; LF/CRLF and dependency drift. | Byte mismatch is not necessarily semantic drift; avoid blind resealing or source normalization. |
| RP-12: corrections, facsimile gaps or uncertain eligibility | [Synthesis/readiness](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#synthesize-findings-and-readiness) and [page inventory](../.agents/skills/source-to-tei/references/inventory-strategies.md#page-images-and-ocr-handoffs); separate each evidence role. | Seeded modernization, unresolved page scans, display correction versus retained reading. | Accounted pages do not prove viewed images; technical completion does not resolve eligibility or acceptance. |
| RP-13: recovered evidence, inherited completeness or absent routes | [Assess](../.agents/skills/source-to-tei/SKILL.md#assess-an-existing-result) and [admission](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-admission-and-continuation); compare claimed whole scope to actual bound members and identify missing route evidence. | BCP full label on a partial bundle; Baxter/Chadwick admission gaps; discovered historical candidates. | Discovery is not current validation; a route blocker does not invalidate all source-local evidence. |
| RP-14: electronic-header disclosure or authority-role ambiguity | [Evidence ownership](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#evidence-ownership); identify relevant contact/correction/rights statements and textual versus support roles. | Contributor/header information; rights/software-license members counted as witnesses; [constituent contributor example](#rp-14-constituent-contributor-example). | Personal names are not automatically prohibited; source retention and public disclosure are different decisions. |
| RP-15: a proposed mapping is generally plausible TEI | [XML/TEI inventory](../.agents/skills/source-to-tei/references/inventory-strategies.md#xml-html-and-tei); check the exact local schema including parent/child placement. | p@type rejected; a later chapter head needed a new wrapper. | An allowed element name alone does not establish valid placement; avoid changing source meaning to satisfy a guessed schema. |
| RP-16: location warnings, instrumentation logs or presentation transforms | [Capture profile](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#cvw-evidence-profile); classify against actual route semantics and record displayed versus selected location. | Truthful outside-range warning; Codex CSP instrumentation; uppercased entry title. | Nonempty warnings are not automatically app failures. A layout workaround or display transform does not establish correspondence. |

## Located test examples

### RP-04/06: readable relationships and independent expectations

Baltimore (historical maintainer record)
and Luther (historical maintainer record)
retain the original line-conservation passes alongside missing meaningful
grouping. Charnock (historical maintainer record)
adds discourse/note relationships; Findlay's inline-order receipt (historical maintainer record)
locates a displaced phrase despite retained-byte and flat-feature equality.
Strong's review (historical maintainer record)
records source headings flattened into line carriers and a successor checker
that compares the actual tree rather than constructing expected TEI with the
producer algorithm. Its shared source-heading inventory remains an explicit
assumption. These examples motivate source-grounded relationship checks, not
automatic conversion of every visually prominent line into a heading.

### RP-09: visual discovery and layer attribution

Calvin's index finding (historical maintainer record)
began with visual loss of row/column relationships; subsequent diagnosis and
repair established the reconstruction defect. In contrast,
Owen's stanza diagnosis (historical maintainer record)
records five native TEI lines inside note 31 despite their inline display.
Inspect the actual TEI before assigning the repair layer. These historical
findings do not establish the current renderer's behavior or a comparative
detection rate.

### RP-12: retained attribution anomaly

Keil's review (historical maintainer record)
records three retained 1CH1 occurrence strings matching Gill. Preserve the
retained reading and route the attribution anomaly to its source owner; the
match alone does not establish authorship or authorize relabeling, deduplication,
or source correction.

### Reusable test pointers

Resolve these paths under `<reviewed-project-root>`, not the active skill's
checkout. Locate and inspect that version before reusing a claim; an absent or
different test is a proof gap, not permission to substitute another checkout.
Package-owned guidance and retained history above remain package-relative.

- RP-07: `cvw_app/tests/test_review_core.py`,
  `test_large_single_line_json_is_losslessly_pageable_without_truncation` proves
  a bounded JSON example when run. It does not prove entryFree, every source
  segment, or visual anchor coverage.
- RP-10: `cvw_app/tests/test_launch_windows.py`,
  `test_launcher_opens_browser_only_after_readiness` and
  `test_launcher_reports_browser_exception_with_manual_url` cover launch ordering
  and exception reporting when run, not browser availability in every agent.
- RP-16: `cvw_app/tests/test_real_library_canary.py` has
  explicit outside-range location assertions for selected opposite-side pages.
  Its fixture/input scope must match any claimed reuse.

### RP-03/09/16: selected route versus visible work boundary

The Acts 37a-08 report (historical maintainer record)
retains a wrong-work ending frame as zero-credit diagnostics: the selected Acts
route coexisted with Romans body content and an outside-range warning. The
replacement locates the actual Acts ending at `vi.lv-p17`. A correct route or
image digest cannot establish a passage claim; retain each pane's actual visible
anchor and the warning. Truthful outside-range content can support its named
visible locus without completing the selected work's ending claim.

### RP-14 constituent contributor example

The existing META exact proposal (historical maintainer record)
supplies this bounded example:

> Shared-volume contributor lists do not establish every constituent work's translator. Compare work-specific title matter and translation-preface assignments; preserve author, translator and editor roles at their supported identity grain. In NPNF1-05, `ix-p14` assigns *Against Two Letters of the Pelagians* to Robert Ernest Wallis although the inherited config named Peter Holmes and Schaff. A digest match proves which config was used, not that its attribution is correct.

The September 8 adoption record (historical maintainer record)
binds the reviewed snapshot and disposition. Its evidence-class and
missing-registration clarification comes from the complete heading
“META-F004 — identity assessment completion and review corrections,” distinct
from “META-F004 — 2026-09-08 — Canonical byte and coordinator drift.” The review
cutoff is F001–F008; later findings remain with META. This example does not reopen
the applied repair or establish that every NPNF attribution is wrong. Metadata
changes and persistence retain their existing owner.

## September 25 additions to existing patterns

These are located examples for the existing branches, not universal mappings.
The September 25 adoption record (historical maintainer record)
records implementation and verification scope. Original log corrections remain
part of each example's evidence; historical repairs are not fresh corpus passes.

| Existing pattern | Added evidence and required distinction | Check owner |
| --- | --- | --- |
| RP-04/06: relationships beyond text | Prayer notes and verse (historical maintainer log), empty body (historical maintainer log), and semantic attributes (historical maintainer log): assert role, ownership, text-part boundaries and attribute values independently. Conserved words and recorded attributes do not prove readable semantics. | Source-local profile/oracle; reusable comparator in [preflight guidance](SOURCE_PREFLIGHT.md#profile-based-fidelity-comparison). |
| RP-04/06: links and page identity | Repeated link failure and repaired return (historical maintainer log): closure, intended target, source ID and printed page label are separate claims. IDs retained only as data cannot satisfy fragment targets. | [Local link check](SOURCE_PREFLIGHT.md#candidate-link-closure) plus source-specific target/label assertions; `tests/test_tei_link_check.py`. |
| RP-02/06: empty or stream carriers | Robertson empty line (historical maintainer log) and USFX verse streams (historical maintainer log): enumerate structural nodes separately from nonempty text; derive ownership across milestones from source order. | Format owner; OCR traversal belongs to EzraOCR. Do not infer a generic verse parser from one format. |
| RP-03/05/12: retained envelope versus provider description | Deleted scan leaves (historical maintainer log), linked Wikisource pages (historical maintainer log), TCP gaps (historical maintainer log): access-format agreement and readiness labels cannot establish full source scope or textual quality. | Source inventory and acquisition owner; inspect exclusions and preserve unknowns. A gap census does not count editorial errors. |
| RP-05/14: media and machine-data references | Referenced versus archive-only artwork (historical maintainer log) and OpenBible member references (historical maintainer log): reconcile references from every relevant record family; separate reference preservation, asset bytes, and actual image display. | [ZIP preflight](SOURCE_PREFLIGHT.md#zip-and-source-media-census) and [media handoff](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#source-media-handoff). OpenBible was excluded from that campaign; its diagnostic artifact is not campaign completion. |
| RP-09/10/16: admitted but not visible | PDF placeholder (historical maintainer log) and archive media (historical maintainer log): inspect actual source pixels, then bind caller observations to retained captures. | CVW presentation owner and [caller review template](SOURCE_TO_TEI_VISUAL_REVIEW_TEMPLATE.md). Admission/capture success is not visual comparison. |
| RP-11/13: discovery and stale bindings | Storage correction (historical maintainer log) and shared converter return (historical maintainer log): resolve configured paths and reconcile exact receipts before absence claims; refresh affected bindings after code changes. | [Intake](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#retained-source-intake) and existing binding reconciliation. No universal junction-creation or retained-source exclusion rule. |
| RP-12/15: source readings and transformations | Terminal glyphs (historical maintainer log), PDF extraction overlap return (historical maintainer log), and P4 migration (historical maintainer log): distinguish retained bytes, extraction, rendering and alternate readings. | Source reader and exact local schema; [advisory linter](SOURCE_PREFLIGHT.md#advisory-text-observations) does not correct or certify text. |

## Maintain this catalog

Retain each new failing example and exact evidence with its contribution issue
or pull request. Propose a pattern change there with a reproducing check;
maintainers retain the internal friction-log history. During an
authorized update, extend an existing RP entry where the trigger and failure
match; add a new entry only
for a distinct useful branch. Keep its applicability boundary and pointer to the
check owner. Prefer a regression in that component over repeating a diagnostic
recipe in every ticket. Record gaps in original evidence or regression coverage
explicitly. Original history is preserved; it is not edited into a new success.

Cross-corpus heuristics follow the [synthesis gate](SOURCE_TO_TEI_REVIEW_OPERATIONS.md#synthesize-findings-and-readiness).
The index itself does not promote sample-derived thresholds, change acceptance,
or create another source or candidate registry.
