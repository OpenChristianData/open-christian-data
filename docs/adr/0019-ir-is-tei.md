# ADR-0019: The intermediate representation (IR) is TEI

**Status:** Accepted (2026-07-01)

## Context

Open Christian Data produces faithful, machine-readable reproductions of public-domain Christian texts and makes them freely available online — including texts that are public domain in principle but have no correct free digital edition (works surviving only as page scans or uncorrected OCR). Serving that end means every source normalizes into one faithful **intermediate representation (IR)** that a human can verify against the original, and from which every output is a projection.

The IR's concrete format was the project's largest undocumented decision. The unified pipeline plan framed it as "JSON-AST vs TEI-lite — the 6-month lock-in," to be decided in a City of God pilot. Two clarifications resolved it earlier than the pilot:

1. **The IR's purpose is verification + standardization, not reconciliation.** ADR-0001 chose a flat linear block sequence explicitly optimized for the Reconcile algorithm, and rejected a hierarchical tree. But reconciliation is a stage that *can* run inside the model, not its reason for existing. The reasons are: a human must be able to visually verify the IR against the original, and everything must standardize into one durable, openly reusable format — for uses not yet conceived.
2. **Scan-anchored facsimile verification is in scope.** The OCR pipeline (whose first and largest target, the Schaff-Herzog Encyclopedia, grew subproject-sized) already produces word-level bounding-box geometry linking each word to a region of the scanned page (`word-confusion-table-v1`, `sidecar-page-v1`). Verifying text against a scan image is the hardest verification case, and it is a first-class construct in TEI.

## Decision

**The IR is TEI** — **unconstrained TEI P5 for now.** Every output, including the AI-training JSON published to HuggingFace, is a **projection** from the TEI IR, each carrying a **loss receipt** declaring what it dropped. A constrained TEI customization (ODD) is **deferred** until real material (the City of God pilot) reveals the subset actually used; the project constrains from evidence, not up front.

TEI is chosen because the project's goals are standardization, robustness, longevity, and digitally-correct fidelity — and TEI is the recognized international standard for faithful digital editions. A bespoke JSON schema is, by definition, not a standard.

## Consequences

**Positive**
- The IR is a recognized standard, not a project-local format — durable and reusable independent of this project's own code surviving.
- The human-verification surface is largely tooling to adopt, not build: TEI renders to HTML off the shelf (CETEIcean, TEI Publisher, XSLT stylesheets).
- Scan-anchored verification has a standard home: `<facsimile>`/`<surface>`/`<zone>`/`@facs`. The OCR pipeline's existing word-box geometry ports into it directly.
- Attestation and disagreement records have a standard construct: `<app>`/`<lem>`/`<rdg>`/`<wit>`.

**Negative**
- The current pipeline (66 parsers, the OCR-fusion schemas) is JSON-native. The IR boundary is where JSON becomes TEI; validation and transforms move onto XML tooling (lxml, RelaxNG/Schematron, XSLT).
- Each output needs a TEI → output projection stage. This is wanted (it is the loss-receipt boundary) but is real work.
- Authoring the constrained ODD is deferred, not skipped.

**Relationship to ADR-0001**
- ADR-0001's flat linear-block-sequence choice is **superseded as the IR / published shape** by this ADR. Its underlying principle — structure captured as annotation, never fabricating hierarchy the source lacks — still informs how the project uses TEI.
- **Open:** whether the OCR-fusion *internal* working schemas (`word-confusion-table-v1`, `corrected-page-v1`) also become TEI, or remain JSON internal representations that serialize to TEI only at the IR boundary. This ADR does not decide that.

## Alternatives considered

- **Bespoke JSON-AST (with typed spans).** Rejected. It fits the current JSON-native stack — builder convenience — but is not a standard. The stated goals are standardization, robustness, and longevity, which a project-local schema does not serve. (An earlier draft recommended JSON-AST on the basis that facsimile linking was already solved in JSON; that showed JSON *can* anchor text to scans, but "can, bespoke" was never the goal.)
- **TEI-lite.** Rejected. TEI-lite is text-focused and omits the facsimile module the scan-anchored verification needs. If TEI is the answer, TEI-lite is the wrong subset.
- **A constrained TEI ODD authored up front.** Deferred, not rejected. Constrain the subset from evidence (the City of God pilot), then generate the ODD.
