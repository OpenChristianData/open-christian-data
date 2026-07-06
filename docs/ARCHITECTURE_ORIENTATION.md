# OCD Architecture Orientation

**Date:** 2026-07-01
**Scope:** The Open Christian Data **dataset** is the project. The OCR pipeline is a capability the dataset needs for its hardest source class — texts that survive only as page scans or uncorrected OCR. Its first and largest target, the Schaff-Herzog Encyclopedia (NSH), grew subproject-sized in its own right, but it is not a separate project: it manufactures faithful text that enters the dataset like any other source.
**Purpose:** Orient a cold session on what the architecture is *for*, and record the central decision: **the intermediate representation (IR) is TEI** ([ADR-0019](adr/0019-ir-is-tei.md)). No implementation, no `data/` edits. Supersedes the 2026-06-22 and earlier 2026-07-01 drafts, which mis-scoped the project and mis-recommended a bespoke JSON format.

---

## Telos — why the project exists

Open Christian Data produces **faithful, machine-readable reproductions of public-domain Christian texts and makes them freely available online** — a correct digital copy anyone can use. Its reason for existing is the class of texts that are public domain in principle but have **no correct free digital edition**: works surviving only as page scans or as uncorrected OCR (Migne's Patrologia, patristics beyond ANF/NPNF, the Schaff-Herzog stub volumes). The pipeline exists to turn those into faithful, verifiable text.

Audiences: researchers, Bible-software developers, and anyone building on public-domain Christian texts. Everything below — the IR, verification, standardization — serves that end: the most accurate re-representation of the original text and authorial intent, made durable and openly reusable.

---

## Decision brief

- **One purpose: verification + standardization.** Every source normalizes into one faithful IR a human can visually verify against the original. From the IR, every output — the AI-training JSON included — is a **projection** that declares exactly what it dropped (a loss receipt). The goal is the most accurate re-representation of the original text and authorial intent, with losses on the record rather than silent.
- **The IR is TEI** (unconstrained TEI P5 for now; a constrained customization comes later, once real material shows which subset is actually used). Chosen because the maintainer's stated goals are standardization, robustness, longevity, and digitally-correct fidelity — and TEI is the recognized international standard for exactly that. A bespoke JSON schema is, by definition, not a standard.
- **The pipeline is: many sources → one TEI IR → human verification → projections.** Born-digital sources (CCEL, Standard Ebooks, Gutenberg, …) produce faithful text via parsers; NSH produces it via OCR-fusion from scans. Both serialize into the same TEI IR. The AI-training JSON is one projection *from* TEI, not the IR itself.
- **Real costs, accepted with eyes open.** The current pipeline (66 parsers, the NSH schemas, the reconciliation code) is JSON-native; making the IR TEI re-tools the validation/transform layer onto XML (lxml, RelaxNG/Schematron, XSLT). Each output needs a TEI→output projection stage (which you want anyway — it's the loss-receipt boundary). Authoring the TEI customization (ODD) is deferred, not skipped.
- **An asset that ports:** NSH already produces word-level bounding-box geometry (`word-confusion-table-v1`, `sidecar-page-v1`) linking each word to a region of the scanned page. That maps directly onto TEI's `<facsimile>`/`<surface>`/`<zone>`/`@facs` — so the scan-anchored verification you already built is a standard construct in TEI, not something to reinvent.
- **No ADR exists for the IR format** — the single biggest architectural decision in the project is currently undocumented. Capturing "IR = TEI" as an ADR is the immediate next step after approval. Everything else (June redesign, fidelity-IR, unified pipeline, format-state map) folds in as implementation detail.

---

## 1. The purpose

The current passes go **raw source → final JSON in one jump** — which cannot be easily validated. There is no point at which a human can confirm the download was faithful and the structure is right. The fix splits that un-checkable jump into two checkable ones:

- **raw → IR** — a faithful TEI representation a human can *visually* verify against the original (TEI renders to HTML off the shelf via CETEIcean / TEI Publisher / XSLT, so the verification surface is largely tooling you adopt, not build).
- **IR → output** — a code-checkable projection that declares exactly what it dropped (loss receipt).

Two reasons this earns its keep, both independent of how many copies a work has:

1. **Verification** — the TEI IR is the human-checkable surface; for scanned sources it anchors to the page image via facsimile zones.
2. **Standardization** — one uniform intermediate everything normalizes into. Once a text is TEI, projecting it to any output is the easy part, including outputs not yet conceived. TEI's self-describing, tool-supported form is what makes "not yet conceived" a real property rather than a hope.

Reconciliation of multiple copies is a stage that *can* run inside this model; it is **not** the reason the model exists.

---

## 2. The shape — sources into one IR

| Layer | Owns | Form |
|---|---|---|
| **Sources** | acquiring faithful text from each origin | born-digital: parsers (CCEL ThML, Standard Ebooks, Gutenberg, SWORD, JSON). scanned: **NSH OCR-fusion** (multi-engine reconciliation → one `our-ocr` rendering) |
| **IR** | the faithful, verifiable, standardized representation | **TEI** (unconstrained P5 for now) |
| **Verification** | human confirms IR against the original | TEI → HTML (CETEIcean / TEI Publisher), with facsimile-zone overlay on scans for NSH-sourced text |
| **Projections** | every output, each declaring its losses | TEI → AI-training JSON (+ future targets), each with a loss receipt |
| **Envelope metadata** | who/what: author, title, dates, tradition, era, audience | author + works registries (from the June redesign — compatible, keep) |

**NSH's role.** NSH is the source that manufactures inputs the others can't — a faithful digital text from a scan of an edition that has no free correct digital version. Its internal machinery (word-confusion table, per-engine attestation, the gold-free corrector) is *how* it produces that text; the product serializes into the TEI IR like any other source's output, carrying its bbox geometry into TEI facsimile zones. NSH "unifies with this side" exactly by feeding it texts.

---

## 3. Why TEI, and what it costs

**Why TEI is the right IR for the stated goals:**
- **Standardization** — "the most robust format that exists" for faithful editions is TEI; it is the standard, not a candidate.
- **Digitally-correct fidelity** — representing primary sources with authorial-intent fidelity, verifiably, is TEI's founding purpose.
- **Longevity / open-ended reuse** — self-describing and tool-supported; readable and transformable in decades, independent of OCD's own code surviving.
- **Verification tooling off the shelf** — CETEIcean, TEI Publisher, XSLT stylesheets give the visual human-verification surface without building it.
- **Facsimile** — `<facsimile>`/`<zone>`/`@facs` is the standard home for NSH's already-built word-box geometry.
- **Apparatus** — `<app>`/`<lem>`/`<rdg>`/`<wit>` is a standardized construct for the attestation/disagreement records both the OCR-fusion and any multi-source reconciliation produce.

**The honest costs (to manage, not to avoid):**
- **XML in a JSON-native pipeline** — validation/transform moves to lxml + RelaxNG/Schematron + XSLT. The 66 existing parsers and NSH schemas emit JSON today; the IR boundary is where JSON becomes TEI.
- **A projection stage per output** — TEI → training JSON is an XSLT/lxml transform. This is the loss-receipt boundary, so it is wanted, but it is real work.
- **Customization design (deferred)** — the maintainer chose **unconstrained TEI P5 for now**. A constrained ODD (naming the exact subset OCD uses, generating schema + docs) should follow once real material — the City of God pilot is the natural first — reveals the needed elements. Deferring it is deliberate: constrain from evidence, not up front.

**The prior JSON-AST recommendation is withdrawn.** It over-weighted "fits the current stack," which is builder convenience, over standardization and robustness, which are the actual goals. The facsimile-in-JSON finding shows JSON *can* anchor text to scans — but "can, bespoke" was never the goal; "the robust standard" was.

---

## 4. Effort map (dataset-first)

| Effort | Date | Status | Role under the unified frame |
|---|---|---|---|
| **2026-05-14 rearchitecture** (`plans/2026-05-14-multi-source-rearchitecture.md`, `SHARED-LEXICON.md`, ADRs 0001–0015) | 05-14 | Built for NSH only; born-digital migration never started | The canonical model: work/edition/source/format/rendering, `pd_anchor`, the pipeline, the lexicon. Its ADR-0001 "linear block sequence" is a JSON-era choice now superseded by TEI as the IR (see §6). |
| **NSH / OCR pipeline** (`docs/NSH_PROJECT_STATE.md`, schemas `sidecar-page-v1`/`word-confusion-table-v1`/`corrected-page-v1`) | ongoing | S1→S2.5 production; S3 + corrector code-complete, unreviewed | The hardest **source**. Manufactures faithful text from scans; its bbox geometry ports into TEI facsimile zones. |
| **Fidelity-IR plan** (`plans/2026-06-18-fidelity-ir-architecture-plan.md`, `plans/_archive/2026-06-18-fidelity-execution/`) | 06-18 | Draft; 0 batches run | The born-digital IR design. Its "IR" becomes TEI; its **loss receipt** is the genuinely additive idea and stays. The 3 bug fixes are real and format-independent. |
| **Data-structure redesign** (`docs/DESIGN_data_structure_redesign.md`, `docs/BUILD_PLAN_data_structure_redesign.md`) | 06-17 | Designed, DO-NOT-SHIP; 0 commits | The envelope-metadata layer (author + works registries). Compatible; keep. |
| **Unified pipeline** (`docs/BUILD_PLAN_unified_pipeline.md`) | 06-18 | Sequencing keystone; not started | Correctly unifies envelope + content. Its open "IR format — JSON-AST vs TEI-lite, the 6-month lock-in" (U6-A) is now **decided: TEI** (see §6). |
| **Format-state map** (`docs/FORMAT_STATE_MAP.md`) | 06-18 | 4 of 10 families walked | Orientation input — which parsers need IR work. Finish the walks as scoping. |
| **Dataset project state** (`docs/DATASET_PROJECT_STATE.md`) | 06-16 | Current dataset anchor | Never references the 05-14 model; re-point it at this doc + the TEI decision. |

---

## 5. Fold / keep / close verdict

| Effort | Verdict | Action |
|---|---|---|
| Fidelity-IR plan | **Fold** | The "IR" becomes TEI; keep the loss receipt as a published manifest per projection. |
| Fidelity-execution bug fixes (City of God, Catholic Encyclopedia, Creeds) | **Keep — do now** | Real, disk-confirmed corruption, independent of the format choice. |
| Data-structure redesign | **Fold** | Keep the author + works registries as the envelope layer; retire the standalone layout-redesign. |
| Unified pipeline | **Close U6-A** | Adopt its envelope/content unification; resolve the format lock-in as **TEI** rather than an open pilot. Salvage U0 (ownership + ID scheme). |
| Format-state map | **Keep** | Finish the remaining 6 family walks as scoping for the TEI IR build. |
| Dataset project state anchor | **Re-point** | Reference the 05-14 model, the TEI decision, and this doc. |

---

## 6. Open decisions and next step

**Decided (this session):** IR = TEI, unconstrained P5 for now; all outputs including the AI-training JSON are projections from the TEI IR, each with a loss receipt.

**Recorded (this session):**
- **[ADR-0019](adr/0019-ir-is-tei.md) — "IR = TEI (unconstrained P5; ODD deferred)"** — written; the project's biggest architectural decision is now documented.
- **[ADR-0001](adr/0001-linear-block-sequence.md) marked partially superseded** by 0019 as the IR / published shape. Its annotation-not-hierarchy principle still informs TEI usage; whether the OCR-fusion internal schemas remain JSON is left open in 0019.

**Still open (for the maintainer):**
1. **Born-digital IR build order** — which source-format families migrate to TEI first (the format-state map is the input; City of God is the natural pilot).
2. **TEI customization (ODD) timing** — deferred by decision; revisit after the City of God pilot reveals the used subset.
3. **Reconciliation scope on the born-digital side** — most born-digital works are single-source (parse → TEI, no N-way reconcile); only a handful (e.g. City of God across CCEL + Standard Ebooks) exercise the multi-rendering path. Confirm lazy-reconcile-per-work is acceptable.

**Next step:** for approval, not implementation. On approval: write the IR-format ADR, update `SHARED-LEXICON.md` (add TEI as the IR; the `format` enum already lists `tei`) and `DATASET_PROJECT_STATE.md`. No code, no `data/` changes until then.
